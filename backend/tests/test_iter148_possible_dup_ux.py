"""Iter148 UAT-FIX · Possible-Duplicate UX Hardening (Q2 · 2026-09-10).

Locks in the fix for the Sep-9 UAT bug where an IDFC ₹570 Toll for
AP31TF4858 was silently EXCLUDED from commit because a prior manual
Quick-Op Toll of ₹570 existed for the same vehicle on the previous
day. The backend correctly bucketed the row as ``possible_duplicate``;
the wizard omitted it from commit without explicit operator review.

The parser + preview bucketing are proven correct against the ORIGINAL
IDFC UAT file (`FASTag_IDFC_UAT_20260909.xlsx`). The frontend surface
must now:
  1. Require an EXPLICIT per-row decision on every possible_duplicate
     row (Import Anyway / Skip).
  2. Never allow a commit to silently exclude a possible_duplicate row.
  3. Show the existing match's details inline so the operator can
     compare source vs existing before deciding.
  4. Show a full commit-time breakdown of Ready / Skip / Pending.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from services_toll_import import parse_fastag


REPO_ROOT = Path(__file__).resolve().parent.parent
UAT_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "iter148" / "FASTag_IDFC_UAT_20260909.xlsx"
WIZARD_FILE = REPO_ROOT.parent / "frontend" / "src" / "components" / "quickexp" / "TollImportWizard.jsx"


# ── 1. Parser reconciliation against the REAL IDFC UAT file ────────────

def test_uat_idfc_parser_extracts_all_81_debits():
    assert UAT_FIXTURE.exists(), f"UAT fixture missing: {UAT_FIXTURE}"
    blob = UAT_FIXTURE.read_bytes()
    vendor, rows = parse_fastag(blob)
    assert vendor == "idfc"
    assert len(rows) == 81, f"expected 81 debit rows, got {len(rows)}"
    total = sum(r["amount"] for r in rows)
    assert abs(total - 30902.0) < 0.01, f"source debit total mismatch: {total}"
    errored = [r for r in rows if r.get("error")]
    assert errored == [], f"parser must not surface errors on UAT file: {errored}"


def test_uat_idfc_ap31tf4858_all_three_rows_present():
    """AP31TF4858 must have 3 rows summing to ₹1,065 — the entire
    reported UAT set (135 + 360 + 570)."""
    blob = UAT_FIXTURE.read_bytes()
    _, rows = parse_fastag(blob)
    tf = [r for r in rows if r["source_vehicle_ref"] == "AP31TF4858"]
    assert len(tf) == 3, [r["amount"] for r in tf]
    assert sorted(r["amount"] for r in tf) == [135.0, 360.0, 570.0]
    # The critical ₹570 row must retain its exact Txn ID from source.
    r570 = next(r for r in tf if r["amount"] == 570.0)
    assert r570["source_txn_ref"] == "0010002609091930473905"
    assert r570["date"] == "2026-09-09"
    assert "Tangatur" in r570["description"]
    assert r570.get("error") is None


# ── 2. Preview bucketing: prior manual Quick-Op creates a
#      possible_duplicate — never a silent drop, never exact_duplicate. ─

def test_prior_manual_quickop_flags_idfc_row_as_possible_duplicate():
    """Given a manual Quick-Op Toll ₹570 for AP31TF4858 on 2026-09-08
    and an IDFC file with the same vehicle + amount on 2026-09-09,
    the IDFC row MUST bucket as possible_duplicate (soft), not
    exact_duplicate (hard block), and not ready.

    This is the exact UAT-Fix reproduction of the Sep-9 bug. Uses a
    scoped test tenant against real MongoDB so the actual
    build_preview + _scan_possible_duplicates code path is exercised."""
    import asyncio
    import uuid

    from db import db
    from services_toll_import import build_preview

    async def _run():
        uid = f"uid_test_iter148_pdup_{uuid.uuid4().hex[:8]}"
        cid = f"cid_test_iter148_pdup_{uuid.uuid4().hex[:8]}"
        vid = f"veh_test_ap31tf4858_{uuid.uuid4().hex[:6]}"
        try:
            await db.vehicles.insert_one({
                "user_id": uid, "company_id": cid, "id": vid,
                "vehicle_number": "AP31TF4858", "is_active": True,
                "vehicle_type": "own",
            })
            # Prior manual Quick-Op Toll for AP31TF4858 on 2026-09-08.
            await db.expenses.insert_one({
                "user_id": uid, "company_id": cid,
                "id": "exp_prior_manual_test", "date": "2026-09-08",
                "category": "Toll", "amount": 570.0,
                "narration": "manual toll",
                "vehicle_id": vid, "vehicle_number": "AP31TF4858",
                "source_type": "quick_op", "source_key": "",
                "source": "", "source_txn_ref": "",
                "is_deleted": False, "is_reversed": False,
            })

            rows = [{
                "source": "idfc",
                "source_txn_ref": "0010002609091930473905",
                "source_vehicle_ref": "AP31TF4858",
                "source_vehicle_raw": "AP31TF4858",
                "date": "2026-09-09", "amount": 570.0,
                "description": "Issuer Debit Transaction for toll fare - 073002 - Tangatur Toll Plaza",
                "plaza": "", "row_index": 64, "error": None,
            }]
            preview = await build_preview(uid, cid, "idfc", rows)

            assert preview["counts"]["possible_duplicate"] == 1
            assert preview["counts"]["ready"] == 0
            assert preview["counts"]["exact_duplicate"] == 0
            pdup = preview["rows"][0]
            assert pdup["bucket"] == "possible_duplicate"
            assert pdup["possible_matches"], "possible_matches must be surfaced for UI review"
            m = pdup["possible_matches"][0]
            assert m["amount"] == 570.0
            assert m["date"] == "2026-09-08"
            assert m["vehicle_number"] == "AP31TF4858"
            # Existing match must expose its source_label so the UI can
            # tell the operator this is a MANUAL entry (not another
            # fastag import) — the crux of the Q1c decision.
            assert "manual" in (m.get("source_label", "").lower()) or \
                   m.get("kind") == "canonical_expense"
        finally:
            await db.vehicles.delete_many({"user_id": uid})
            await db.expenses.delete_many({"user_id": uid})

    asyncio.run(_run())


# ── 3. Frontend static guards: the wizard has the UX contract wired. ───

def _wizard_source() -> str:
    assert WIZARD_FILE.exists(), f"wizard file missing: {WIZARD_FILE}"
    return WIZARD_FILE.read_text()


def test_wizard_has_possible_dup_review_banner():
    src = _wizard_source()
    assert 'data-testid="toll-possible-dup-banner"' in src
    assert "need a duplicate decision" in src or "possible-duplicate" in src.lower()
    assert 'data-testid="toll-review-possible-dup-btn"' in src


def test_wizard_has_explicit_import_anyway_and_skip_radios():
    src = _wizard_source()
    # Explicit binary decision — radio testids per row.
    assert 'data-testid={`toll-override-keep-${r.row_index}`}' in src, \
        "wizard must expose per-row 'Import Anyway' radio testid"
    assert 'data-testid={`toll-override-skip-${r.row_index}`}' in src, \
        "wizard must expose per-row 'Skip' radio testid"
    # Pending-decision marker per row.
    assert 'data-testid={`toll-decision-pending-${r.row_index}`}' in src


def test_wizard_shows_possible_match_details_inline():
    src = _wizard_source()
    # Each match is rendered with a stable testid so the operator can
    # see WHY a row is a possible duplicate (source_label, date, amount,
    # vehicle) — no silent hand-wavy "N similar txns".
    assert 'toll-possible-match-${r.row_index}-${i}' in src
    for k in ("source_label", "date", "amount", "vehicle_number"):
        assert k in src, f"wizard must show existing match field: {k}"


def test_wizard_footer_shows_full_breakdown():
    src = _wizard_source()
    for testid in ("toll-footer-import-count", "toll-footer-skip-count",
                   "toll-footer-breakdown"):
        assert f'data-testid="{testid}"' in src, f"wizard must expose footer testid: {testid}"
    # Explicit words for each bucket in the breakdown.
    for lit in ("Ready", "Possible Dup", "Exact Dup", "Errors"):
        assert lit in src, f"footer breakdown must include literal {lit!r}"


def test_wizard_commit_button_requires_review_confirmation():
    src = _wizard_source()
    assert 'data-testid="toll-commit-confirm-dialog"' in src, \
        "wizard must show a confirmation dialog before committing with pending possible-duplicate decisions"
    assert 'data-testid="toll-commit-confirm-proceed"' in src
    assert 'data-testid="toll-commit-confirm-review"' in src


def test_wizard_commit_filter_excludes_possible_dup_without_explicit_keep():
    """The commit filter still requires explicit 'keep' for a possible-
    duplicate row to be included — Skip and undecided both exclude.
    This preserves the safety contract."""
    src = _wizard_source()
    # Filter line: only "keep" survives.
    m = re.search(r'r\.bucket === "possible_duplicate"[^;]*overrides\[r\.row_index\] !== "keep"', src)
    assert m is not None, "commit filter must exclude possible_duplicate rows unless overrides[row]==='keep'"


def test_wizard_exact_duplicate_still_hard_blocked():
    """Exact duplicate remains a hard block — never surfaced with an
    Import Anyway toggle. Verified by the commit filter."""
    src = _wizard_source()
    assert 'r.bucket === "exact_duplicate" || r.bucket === "error"' in src, \
        "exact_duplicate and error must be unconditionally excluded from commit"


def test_wizard_bumps_version_marker():
    src = _wizard_source()
    assert "v148-uat" in src, "wizard must carry the Iter148 UAT-FIX version stamp"
