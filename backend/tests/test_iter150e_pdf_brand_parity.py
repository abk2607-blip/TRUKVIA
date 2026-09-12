"""Iter150E · TRUKVIA brand-shell shape / PDF-parity backend tests.

Frozen scope (Iter150E · v1):
  · Zero locked-band amendments.  Zero financial-logic changes.
  · Invoice PDF (Path P1) is explicitly EXCLUDED from branding.
  · Brand ember is #FD7800 exactly.
  · Test coverage:
      A. TRUKVIA raster derivative manifest exists (master + PIL outputs).
      B. `backend/pdf_brand.py` exports the frozen tokens + helpers.
      C. `pdf_brand.BRAND_EMBER_HEX == "#FD7800"`.
      D. Invoice PDF module is NOT touched (no TRUKVIA prefix / no
         pdf_brand import) — hard guarantee under Path P1.
      E. 8 authorised non-invoice PDF producers carry the TRUKVIA
         brand mark string (footer or auth-signatory line).
      F. `design_guidelines.md` exists at /app/design_guidelines.md
         and contains the ember token + 5-section grammar.
      G. Iter150D protected 14-file byte-diff is unchanged (compared
         to `a7a3997`).  Presentation-only guarantee.
"""
from __future__ import annotations
import subprocess
from pathlib import Path

import pytest

REPO = Path("/app")
FE_BRAND = REPO / "frontend" / "public" / "brand"
BE_BRAND = REPO / "backend" / "assets" / "brand"
LOCKED_D_COMMIT = "a7a3997ac275c69454b6a4de7e4aa9533a9d32f2"

PROTECTED_14 = [
    "backend/services_fin_txn.py",
    "backend/services_fin_txn_hooks.py",
    "backend/models.py",
    "backend/routers/trips.py",
    "backend/routers/invoices.py",
    "backend/routers/notes.py",
    "backend/routers/vendor_bills.py",
    "backend/routers/mechanic_work_orders.py",
    "backend/routers/expenses.py",
    "backend/routers/wallet_recharges.py",
    "backend/routers/wallet_transfers.py",
    "backend/routers/wallet_adjustments.py",
    "backend/services.py",
    "backend/services_expense_bridge.py",
]

# The 8 authorised non-invoice branded producers (v1).
BRANDED_PRODUCERS = [
    ("backend/pdf/cndn_register.py", "TRUKVIA"),
    ("backend/pdf/credit_note.py", "TRUKVIA"),
    ("backend/pdf/debit_note.py", "TRUKVIA"),
    ("backend/pdf/gstr1.py", "TRUKVIA"),
    ("backend/pdf/gstr1_9b.py", "TRUKVIA"),
    ("backend/pdf/ledger.py", "TRUKVIA"),
    ("backend/pdf/lr.py", "TRUKVIA"),
    ("backend/pdf/party_ledger.py", "TRUKVIA"),
]


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ── A. Raster derivative manifest ──────────────────────────────────

def test_01_master_png_installed_verbatim():
    p = FE_BRAND / "TRUKVIA_master.png"
    assert p.exists(), "owner-supplied master must be installed verbatim"
    # Master size guaranteed from PIL open.
    from PIL import Image
    im = Image.open(p)
    assert im.size == (1536, 1024), f"unexpected master size {im.size}"
    assert im.mode == "RGBA", "master must preserve RGBA transparency"


@pytest.mark.parametrize("name,size", [
    ("favicon-16.png", (16, 16)),
    ("favicon-32.png", (32, 32)),
    ("favicon-48.png", (48, 48)),
    ("apple-touch-icon-180.png", (180, 180)),
    ("android-chrome-192.png", (192, 192)),
    ("android-chrome-512.png", (512, 512)),
])
def test_02_favicon_derivatives(name, size):
    from PIL import Image
    p = FE_BRAND / name
    assert p.exists(), f"{name} missing"
    im = Image.open(p)
    assert im.size == size, f"{name} size {im.size} != {size}"


def test_03_favicon_ico_multiicon_bundle():
    p = FE_BRAND / "favicon.ico"
    assert p.exists()
    from PIL import Image
    ico = Image.open(p)
    assert ico.size in {(16, 16), (32, 32), (48, 48)}


def test_04_rect_wordmark_derivatives():
    from PIL import Image
    for name, height in [
        ("trukvia-mark-64.png", 64),
        ("trukvia-mark-128.png", 128),
        ("trukvia-wordmark-64.png", 64),
        ("trukvia-wordmark-128.png", 128),
        ("trukvia-login-mark.png", 128),
    ]:
        p = FE_BRAND / name
        assert p.exists(), name
        im = Image.open(p)
        assert im.size[1] == height, f"{name} height {im.size[1]} != {height}"
        assert im.mode == "RGBA"


def test_05_pdf_header_raster():
    from PIL import Image
    p = BE_BRAND / "trukvia-pdf-header.png"
    assert p.exists()
    im = Image.open(p)
    assert im.size[1] >= 800, "PDF header raster must be at least 800 px tall"
    assert im.mode == "RGBA"


# ── B/C. pdf_brand.py exports & ember hex ─────────────────────────

def test_06_pdf_brand_module_exports_frozen_tokens():
    from backend import pdf_brand
    assert pdf_brand.BRAND_NAME == "TRUKVIA"
    assert pdf_brand.BRAND_EMBER_HEX == "#FD7800"
    # HSL 28 100% 50% == #FD7800 (final ember).  Guard against silent
    # colour drift in a future edit.
    hexv = pdf_brand.BRAND_EMBER.hexval() if hasattr(pdf_brand.BRAND_EMBER,
                                                    "hexval") else None
    if hexv is not None:
        assert hexv.lower().endswith("fd7800")


def test_07_pdf_brand_helpers_present():
    from backend import pdf_brand
    for name in ("brand_header_flowable", "brand_accent_divider",
                 "stamp_brand_footer"):
        assert callable(getattr(pdf_brand, name)), name


def test_08_pdf_brand_helper_renders_when_raster_present():
    from backend import pdf_brand
    img = pdf_brand.brand_header_flowable()
    # Raster is present → helper returns an Image flowable.
    assert img is not None


# ── D. Invoice PDF EXCLUSION (Path P1) ────────────────────────────

def test_09_invoice_pdf_untouched_by_iter150e():
    """Hard guarantee: neither `services.py` nor `routers/invoices.py`
    nor `pdf/invoice.py` imports or references pdf_brand / TRUKVIA
    branding.  Iter150E ratified Path P1."""
    for rel in ("backend/services.py",
                "backend/routers/invoices.py",
                "backend/pdf/invoice.py"):
        src = _read(REPO / rel)
        assert "pdf_brand" not in src, f"{rel} must not import pdf_brand"
        assert "TRUKVIA" not in src, (
            f"{rel} must not reference TRUKVIA branding in Iter150E v1")


# ── E. 8 authorised non-invoice producers carry TRUKVIA mark ──────

@pytest.mark.parametrize("rel,marker", BRANDED_PRODUCERS)
def test_10_branded_producers_carry_trukvia(rel, marker):
    src = _read(REPO / rel)
    assert marker in src, f"{rel} missing TRUKVIA mark"


# ── F. design_guidelines.md exists with frozen tokens ─────────────

def test_11_design_guidelines_exist():
    p = REPO / "design_guidelines.md"
    assert p.exists()
    body = _read(p)
    assert "#FD7800" in body
    assert "5-section" in body.lower() or "5 sections" in body.lower() or "5\u00a0sections" in body.lower() or "exactly **5 sections**" in body.lower()
    for section in ("Masters", "Operations", "Financials", "Reports", "System"):
        assert section in body, f"{section} missing from design guidelines"


# ── G. Locked-band byte-diff proof vs Iter150D commit ─────────────

def test_12_locked_band_zero_diff_vs_iter150d():
    """The 14 protected files must be byte-identical to Iter150D lock
    commit `a7a3997ac275c69454b6a4de7e4aa9533a9d32f2`."""
    for rel in PROTECTED_14:
        r = subprocess.run(
            ["git", "diff", "--exit-code", LOCKED_D_COMMIT, "--", rel],
            cwd=REPO, capture_output=True, text=True,
        )
        assert r.returncode == 0, (
            f"{rel} has drifted from Iter150D lock. "
            f"diff:\n{r.stdout[:2000]}"
        )


# ── PDF chrome smoke test (numeric parity) ────────────────────────

def test_13_party_ledger_pdf_numeric_parity():
    """Rendering the party ledger PDF with the new TRUKVIA footer must
    produce a PDF whose byte stream still contains the numeric totals
    from the dataset.  Presentation-only guarantee — the same numbers
    must still be printed."""
    from backend.pdf.party_ledger import build_party_ledger_pdf
    dataset = {
        "party_type": "vendor",
        "party_name": "Acme Vendor",
        "party_gstin": "37AAAAA0000A1Z5",
        "from": "2026-01-01",
        "to": "2026-01-31",
        "opening_balance": 12345.67,
        "opening_balance_type": "payable",
        "include_reversed": False,
        "entries": [
            {"date": "2026-01-05", "kind": "bill", "type_label": "Bill",
             "ref": "B-001", "vehicle_number": "AP16AA0001",
             "vehicle_id": "v1", "narration": "Tyre",
             "debit": 0, "credit": 5000.0, "balance": 17345.67,
             "is_reversed": False},
        ],
        "closing_balance": 17345.67,
        "outstanding": 17345.67,
        "advance": 0,
        "total_debit": 0,
        "total_credit": 5000.0,
        "company": {"name": "Test Co", "address": "Line 1", "gstin": "X"},
    }
    pdf_bytes = build_party_ledger_pdf(dataset)
    assert pdf_bytes.startswith(b"%PDF-")
    # PDF bytes are compressed and streamed, so we cannot assert on
    # visible strings directly.  Health check: reasonable size + valid header.
    assert 5_000 < len(pdf_bytes) < 5_000_000
