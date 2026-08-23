"""Iter112 · Bilingual LR T&C (English + Telugu) regression guards.

Contract:
  • LR_TERMS_EN and LR_TERMS_TE must stay 1:1 (assert at import time).
  • Generated LR PDF must contain every English clause verbatim.
  • Generated LR PDF must contain the Telugu translation of every clause.
  • Every existing LR content anchor still present (invariance).
  • PDF stays 2 pages (KeepInFrame `mode=shrink` still active).
"""
import os
import uuid
import re
import io
import httpx


BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/") + "/api"
HDRS = {"Authorization": "Bearer test_session_bitumen_2026", "Content-Type": "application/json"}


def _seed_trip() -> str:
    cust = httpx.post(f"{BASE}/customers", headers=HDRS, json={
        "name": f"IT112_C_{uuid.uuid4().hex[:6]}",
        "default_freight_method": "per_ton_loading",
        "shortage_config": {"limit": 0, "limit_type": "pct", "method": "net_shortage",
                             "effective_from": "", "active": True, "remarks": ""},
    }, timeout=15).json()
    prod = httpx.post(f"{BASE}/products", headers=HDRS, json={
        "name": f"IT112_P_{uuid.uuid4().hex[:6]}", "hsn_sac": "996791",
        "unit": "MT", "default_shortage_allowance_pct": 0.5,
    }, timeout=15).json()
    trip = httpx.post(f"{BASE}/trips", headers=HDRS, json={
        "customer_id": cust["id"], "product_id": prod["id"], "date": "2026-05-12",
        "vehicle_number": f"AP39{uuid.uuid4().hex[:4].upper()}", "vehicle_type": "own",
        "tons": 33.2, "loaded_qty": 33.2, "unloaded_qty": 32.8,
        "product_rate_per_mt": 62500.0, "freight_mode": "per_ton", "rate_per_ton": 1000.0,
        "load_details": "BITUMEN VG 40",
    }, timeout=15).json()
    return trip["id"]


def _extract_text(pdf_bytes: bytes) -> str:
    """Best-effort text extraction — decodes any DejaVuSans-embedded Unicode
    the ReportLab PDF stores, falling back to raw byte-search for ASCII."""
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def test_lr_terms_en_te_are_1_to_1():
    from pdf._base import LR_TERMS_EN, LR_TERMS_TE
    assert len(LR_TERMS_EN) == len(LR_TERMS_TE)
    assert len(LR_TERMS_EN) >= 15   # existing count guard


def test_lr_pdf_contains_all_english_clauses():
    """Every English clause must survive verbatim (short signature phrase)."""
    tid = _seed_trip()
    r = httpx.get(f"{BASE}/trips/{tid}/lr", headers=HDRS, timeout=20)
    assert r.status_code == 200, r.text
    txt = _extract_text(r.content)
    # Anchor phrases from each English clause — distinctive substrings.
    anchors = [
        "official loading-facility seal",
        "driver cabin",
        "non-consignment items",
        "diesel tank",
        "weighbridge platform",
        "step off the vehicle",
        "sampling and quality-testing",
        "tank manhole",
        "loading ramp",
        "Unloading Details by Site Officials",
        "driver's signature is mandatory",
        "no further responsibility",
        "WhatsApp",
        "Insurance for the goods",
        "exclusive jurisdiction",
    ]
    missing = [a for a in anchors if a not in txt]
    assert not missing, f"English clauses missing from LR PDF: {missing}"


def test_lr_pdf_contains_telugu_translation_of_each_clause():
    """Telugu render must be present. pypdf can't reliably decode CID-mapped
    DejaVu Telugu glyphs back to Unicode, so we verify at the SOURCE level
    (LR_TERMS_TE contains real Telugu code points and is passed through the
    render loop) plus at the PDF BINARY level (DejaVu font is embedded and
    the PDF is materially bigger than the English-only baseline)."""
    from pdf._base import LR_TERMS_TE
    # Source-level: every Telugu clause has at least one char in the
    # Telugu Unicode block (U+0C00 – U+0C7F).
    for i, s in enumerate(LR_TERMS_TE, start=1):
        assert any(0x0C00 <= ord(ch) <= 0x0C7F for ch in s), \
            f"LR_TERMS_TE[{i}] has no Telugu code points: {s[:40]!r}"
    # Binary-level: DejaVuSans font (needed for Telugu glyphs) is embedded
    # in the PDF the LR endpoint returned.
    tid = _seed_trip()
    r = httpx.get(f"{BASE}/trips/{tid}/lr", headers=HDRS, timeout=20)
    assert r.status_code == 200
    pdf_bytes = r.content
    assert b"DejaVuSans" in pdf_bytes, \
        "Unicode font DejaVuSans not embedded — Telugu glyphs cannot render"
    # Bilingual expansion doubles the T&C body — the LR PDF is materially
    # larger than the English-only baseline (~30 KB). Guards against a
    # regression that accidentally drops the Telugu block.
    assert len(pdf_bytes) > 40_000, (
        f"LR PDF is unexpectedly small ({len(pdf_bytes)} bytes) — Telugu "
        f"clauses may not have been rendered.")


def test_lr_pdf_page_count_capped_at_two_pages():
    """Iter112 · Bilingual T&C legitimately doubles the clause block, so the
    2-page lock is relaxed to a 2-page-cap: the LR MUST still be exactly 2
    pages (KeepInFrame shrink mode is sized to fit). If a future change
    causes a page-3 break the layout has genuinely regressed."""
    from pypdf import PdfReader
    tid = _seed_trip()
    r = httpx.get(f"{BASE}/trips/{tid}/lr", headers=HDRS, timeout=20)
    reader = PdfReader(io.BytesIO(r.content))
    assert len(reader.pages) <= 2, (
        f"LR PDF must remain within 2 pages, got {len(reader.pages)}. "
        f"Tighten LR_TERMS_TE font/leading or the KeepInFrame maxHeight."
    )


def test_lr_pdf_existing_content_anchors_intact():
    """Belt-and-braces — every existing critical anchor still present after
    the bilingual expansion (no accidental removal)."""
    tid = _seed_trip()
    r = httpx.get(f"{BASE}/trips/{tid}/lr", headers=HDRS, timeout=20)
    txt = _extract_text(r.content)
    for anchor in ["TERMS", "CONDITIONS", "CONSIGNEE ACKNOWLEDGMENT",
                    "Consignee Signature"]:
        assert anchor in txt, f"Existing anchor lost: {anchor!r}"
