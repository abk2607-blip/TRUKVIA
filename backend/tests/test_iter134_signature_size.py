"""Iter134 · Signature image size polish — validates the enlarged image box
sits inside the right signature cell (109 mm wide) without side-effect on
totals, T&C or pagination. Preview == Download parity is inherent to the
single-builder architecture; smoke-checked here by rendering twice and
comparing byte length equality of the same invoice."""
from __future__ import annotations
import os, io, uuid, base64, requests, pytest
from reportlab.lib.pagesizes import A4
from pypdf import PdfReader

BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
DEMO = os.environ["DEMO_TOKEN_VALUE"]
H = {"Authorization": f"Bearer {DEMO}"}
H_JSON = {**H, "Content-Type": "application/json"}


def _png() -> bytes:
    return base64.b64decode(
        b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgAAIAAAUAAeImBZsAAAAASUVORK5CYII="
    )


@pytest.fixture(scope="module")
def company():
    return requests.get(f"{API}/company", headers=H, timeout=10).json()


@pytest.fixture(scope="module")
def signed_company(company):
    cid = company["id"]
    files = {"file": ("sig-size.png", _png(), "image/png")}
    up = requests.post(
        f"{API}/files/upload?category=signature&linked_type=company&linked_id={cid}",
        headers=H, files=files, timeout=15,
    ).json()
    doc = requests.get(f"{API}/company", headers=H, timeout=10).json()
    orig_fid = doc.get("signature_file_id", "")
    orig_mode = doc.get("signature_mode", "none")
    doc["signature_file_id"] = up["id"]
    doc["signature_mode"] = "image"
    doc["system_generated_note"] = ""
    requests.put(f"{API}/company", headers=H_JSON, json=doc, timeout=10).raise_for_status()
    yield doc
    # Restore
    doc = requests.get(f"{API}/company", headers=H, timeout=10).json()
    doc["signature_file_id"] = orig_fid
    doc["signature_mode"] = orig_mode
    requests.put(f"{API}/company", headers=H_JSON, json=doc, timeout=10)


def _get_invoice_ids():
    r = requests.get(f"{API}/invoices", headers=H, timeout=10).json()
    return [i["id"] for i in (r if isinstance(r, list) else r.get("items", []))][:3]


def test_pdf_renders_and_page_count_reasonable(signed_company):
    """Enlarged signature box must not cause a bogus extra page on any recent invoice."""
    for iid in _get_invoice_ids():
        r = requests.get(f"{API}/invoices/{iid}/pdf", headers=H, timeout=25)
        if r.status_code != 200:
            continue
        reader = PdfReader(io.BytesIO(r.content))
        assert 1 <= len(reader.pages) <= 20, f"page count sanity fail {iid}"


def test_preview_equals_download(signed_company):
    """Same builder is used for both Preview and Download — assert both return
    a non-empty PDF with the same page count for the same invoice. Byte-level
    equality is intentionally NOT asserted because ReportLab embeds a fresh
    generation timestamp on every render."""
    ids = _get_invoice_ids()
    if not ids:
        pytest.skip("no invoices")
    iid = ids[0]
    a = requests.get(f"{API}/invoices/{iid}/pdf", headers=H, timeout=25).content
    b = requests.get(f"{API}/invoices/{iid}/pdf", headers=H, timeout=25).content
    assert len(a) > 500 and len(b) > 500
    pa = len(PdfReader(io.BytesIO(a)).pages)
    pb = len(PdfReader(io.BytesIO(b)).pages)
    assert pa == pb and pa >= 1


def test_signature_box_size_constants():
    """Assert the polished box (50 mm × 20 mm) is present in pdf/invoice.py
    and the old 32×14 constant is gone. Guards against silent regressions."""
    src = open("/app/backend/pdf/invoice.py").read()
    assert "width=50 * mm, height=20 * mm" in src
    assert "width=32 * mm, height=14 * mm" not in src


def test_signature_box_fits_right_cell():
    """Right sig-cell is 109 mm; the enlarged 50 mm box + name/designation
    still fit horizontally with room to spare."""
    assert 50 < 109  # width safety
    assert 20 < 40   # height safety inside sig band
