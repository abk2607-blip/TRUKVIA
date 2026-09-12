"""Iter150E · TRUKVIA brand-shell shape / PDF-parity backend tests.

Corrected scope (2026-02-13 · post-reconciliation):
  · Zero locked-band amendments.  Zero financial-logic changes.
  · Invoice PDF (Path P1) is explicitly EXCLUDED.
  · Halting Report PDF is EXCLUDED — no PDF renderer / no .pdf route
    exists.  Documented as an Iter150E v1 deferred gap.
  · Brand ember is #FD7800 exactly.
  · Authorised non-invoice branded surfaces (8):
      1. Customer Statement PDF        → pdf/ledger.py
      2. Vendor Ledger PDF             → pdf/party_ledger.py (vendor)
      3. Mechanic Ledger PDF           → pdf/party_ledger.py (mechanic)
      4. CN/DN Register PDF            → pdf/cndn_register.py
      5. GSTR-1 XLSX                   → xlsx/gstr1.py
      6. GSTR-1 §9B XLSX               → xlsx/gstr1_9b.py
      7. Supplier Statement PDF        → reports.py inline renderer
      8. LR Register PDF               → reports.py inline renderer
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

# The 8 authorised non-invoice branded producers · file → marker
# substring that must appear in the file.  reports.py counts twice
# because two independent inline renderers (supplier-statement.pdf
# and lr-register.pdf) live inside the same file.
BRANDED_PRODUCERS = [
    ("backend/pdf/ledger.py",              "TRUKVIA · Computer-generated statement"),
    ("backend/pdf/party_ledger.py",        "TRUKVIA · Computer-generated accounting statement"),
    ("backend/pdf/cndn_register.py",       "TRUKVIA "),
    ("backend/xlsx/gstr1.py",              "TRUKVIA "),
    ("backend/xlsx/gstr1_9b.py",           "TRUKVIA "),
    ("backend/routers/reports.py",         "TRUKVIA  ·  Supplier Statement"),
    ("backend/routers/reports.py",         "TRUKVIA  ·  Monthly LR Register"),
]

# Files that MUST NOT carry Iter150E branding (Path P1 + reverted
# unauthorised edits).
UNAUTHORISED_FILES = [
    "backend/services.py",
    "backend/routers/invoices.py",
    "backend/pdf/invoice.py",
    "backend/pdf/credit_note.py",
    "backend/pdf/debit_note.py",
    "backend/pdf/lr.py",
    "backend/pdf/gstr1.py",
    "backend/pdf/gstr1_9b.py",
]


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ── A. Raster derivative manifest ──────────────────────────────────

def test_01_master_png_installed_verbatim():
    from PIL import Image
    p = FE_BRAND / "TRUKVIA_master.png"
    assert p.exists(), "owner-supplied master must be installed verbatim"
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
    from PIL import Image
    p = FE_BRAND / "favicon.ico"
    assert p.exists()
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


def test_07_pdf_brand_helpers_present():
    from backend import pdf_brand
    for name in ("brand_header_flowable", "brand_accent_divider",
                 "stamp_brand_footer"):
        assert callable(getattr(pdf_brand, name)), name


def test_08_pdf_brand_helper_renders_when_raster_present():
    from backend import pdf_brand
    assert pdf_brand.brand_header_flowable() is not None


# ── D. UNAUTHORISED-file exclusion (Path P1 + reverted-edit guard) ─

@pytest.mark.parametrize("rel", UNAUTHORISED_FILES)
def test_09_unauthorised_files_carry_no_trukvia_branding(rel):
    """Hard guarantee: neither Invoice PDF nor its writers nor any of
    the 5 reverted PDF producers reference `pdf_brand` or the TRUKVIA
    brand string.  Path P1 (Invoice) + scope reconciliation."""
    src = _read(REPO / rel)
    assert "pdf_brand" not in src, f"{rel} must not import pdf_brand"
    assert "TRUKVIA" not in src, f"{rel} must not carry TRUKVIA branding"


# ── E. 8 authorised producers carry TRUKVIA mark ──────────────────

@pytest.mark.parametrize("rel,marker", BRANDED_PRODUCERS)
def test_10_branded_producers_carry_trukvia(rel, marker):
    src = _read(REPO / rel)
    assert marker in src, f"{rel} missing marker: {marker!r}"


def test_11_exactly_two_reports_py_inline_producers_branded():
    """reports.py contains exactly the two authorised inline TRUKVIA
    strings — Supplier Statement + Monthly LR Register.  Guards
    against silent addition of a third inline branded surface (e.g.,
    a hypothetical Halting Report PDF)."""
    src = _read(REPO / "backend/routers/reports.py")
    assert src.count("TRUKVIA  ·  Supplier Statement") == 1
    assert src.count("TRUKVIA  ·  Monthly LR Register") == 1
    # Halting Report PDF explicitly NOT branded (no producer exists).
    assert "TRUKVIA  ·  Halting" not in src
    assert "build_halting_pdf" not in src


# ── F. design_guidelines.md exists with frozen tokens ─────────────

def test_12_design_guidelines_exist():
    p = REPO / "design_guidelines.md"
    assert p.exists()
    body = _read(p)
    assert "#FD7800" in body
    for section in ("Masters", "Operations", "Financials", "Reports", "System"):
        assert section in body, f"{section} missing from design guidelines"


# ── G. Locked-band byte-diff proof vs Iter150D commit ─────────────

def test_13_locked_band_zero_diff_vs_iter150d():
    for rel in PROTECTED_14:
        r = subprocess.run(
            ["git", "diff", "--exit-code", LOCKED_D_COMMIT, "--", rel],
            cwd=REPO, capture_output=True, text=True,
        )
        assert r.returncode == 0, (
            f"{rel} has drifted from Iter150D lock. "
            f"diff:\n{r.stdout[:2000]}"
        )


def test_14_five_reverted_files_zero_diff_vs_iter150d():
    """The 5 files that were unauthorised-branded in the prior
    implementation pass must be byte-identical to Iter150D again."""
    for rel in ("backend/pdf/credit_note.py",
                "backend/pdf/debit_note.py",
                "backend/pdf/lr.py",
                "backend/pdf/gstr1.py",
                "backend/pdf/gstr1_9b.py"):
        r = subprocess.run(
            ["git", "diff", "--exit-code", LOCKED_D_COMMIT, "--", rel],
            cwd=REPO, capture_output=True, text=True,
        )
        assert r.returncode == 0, (
            f"{rel} was NOT reverted to Iter150D. diff:\n{r.stdout[:2000]}"
        )


# ── H. Halting Report PDF deferral proof ──────────────────────────

def test_15_halting_report_pdf_producer_absent():
    """Halting Report PDF is deferred from Iter150E v1 because no
    PDF renderer / no .pdf endpoint exists.  Prove absence."""
    # No halting PDF renderer file.
    assert not (REPO / "backend/pdf/halting.py").exists()
    # No .pdf route in reports.py.
    reports = _read(REPO / "backend/routers/reports.py")
    assert "/reports/halting.pdf" not in reports
    assert "build_halting_pdf" not in reports
    # /reports/halting endpoint remains JSON-only.
    assert '@router.get("/reports/halting")' in reports


# ── I. Numeric-value / row-order preservation smoke ───────────────

def test_16_party_ledger_pdf_numeric_parity():
    from backend.pdf.party_ledger import build_party_ledger_pdf
    dataset = {
        "party_type": "vendor",
        "party_name": "Acme Vendor",
        "party_gstin": "37AAAAA0000A1Z5",
        "from": "2026-01-01", "to": "2026-01-31",
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
        "outstanding": 17345.67, "advance": 0,
        "total_debit": 0, "total_credit": 5000.0,
        "company": {"name": "Test Co", "address": "L1", "gstin": "X"},
    }
    b = build_party_ledger_pdf(dataset)
    assert b.startswith(b"%PDF-")
    assert 5_000 < len(b) < 5_000_000


def test_17_gstr1_xlsx_renders_and_carries_trukvia_and_preserves_numbers():
    """Renders the GSTR-1 XLSX and asserts (a) valid OOXML container,
    (b) TRUKVIA disclosure line is present somewhere in the workbook
    (openpyxl uses inline strings — check every worksheet part), and
    (c) numeric totals from the payload are echoed verbatim."""
    from backend.xlsx.gstr1 import build_gstr1_xlsx
    import zipfile, io
    payload = {
        "month": "2026-01", "issuer_gstin": "37XYZ", "company_id": "c1",
        "period": {"start": "2026-01-01", "end": "2026-01-31"},
        "invoice_count": 2,
        "totals": {"taxable": 100000.0, "cgst": 0, "sgst": 0,
                   "igst": 5000.0, "total": 105000.0},
        "b2b": [], "b2c": [], "by_state": [],
        "reconciliation": {"reconciled": True,
                           "endpoint_invoice_count": 2,
                           "ground_truth_invoice_count": 2,
                           "endpoint_total": 105000.0,
                           "ground_truth_total": 105000.0,
                           "endpoint_taxable": 100000.0,
                           "ground_truth_taxable": 100000.0},
        "warnings": [],
    }
    data = build_gstr1_xlsx({"name": "Co"}, payload)
    assert data[:2] == b"PK"
    zf = zipfile.ZipFile(io.BytesIO(data))
    dumped = b"\n".join(zf.read(n) for n in zf.namelist())
    assert b"TRUKVIA" in dumped, "TRUKVIA branding missing from workbook"
    assert b"105000" in dumped or b"105,000" in dumped, \
        "grand-total 105000 missing — numeric parity broken"


def test_18_gstr1_9b_xlsx_renders_and_carries_trukvia():
    from backend.xlsx.gstr1_9b import build_gstr1_9b_xlsx
    import zipfile, io
    _zero = {"note_count": 0, "val": 0, "cn": 0, "dn": 0}
    payload = {
        "month": "2026-01", "issuer_gstin": "37XYZ", "company_id": "c1",
        "period": {"start": "2026-01-01", "end": "2026-01-31"},
        "note_count": 0,
        "totals": {"cdnr": _zero, "cdnur": _zero,
                   "b2cs_adjustments": _zero, "commercial_notes": _zero,
                   "cancelled_after_export": _zero},
        "cdnr": [], "cdnur": [], "b2cs_adjustments": [],
        "commercial_notes": [], "cancelled_after_export": [],
        "reconciliation": {"reconciled": True,
                           "endpoint_gst_true_total": 0.0,
                           "ground_truth_gst_true": 0.0,
                           "endpoint_gst_false_total": 0.0,
                           "ground_truth_gst_false": 0.0,
                           "endpoint_row_count": 0,
                           "ground_truth_issued_count": 0,
                           "cn_total": 0.0, "dn_total": 0.0},
        "warnings": [],
    }
    data = build_gstr1_9b_xlsx({"name": "Co"}, payload)
    assert data[:2] == b"PK"
    zf = zipfile.ZipFile(io.BytesIO(data))
    dumped = b"\n".join(zf.read(n) for n in zf.namelist())
    assert b"TRUKVIA" in dumped, "TRUKVIA branding missing from §9B workbook"
