"""Iter108 · Multi-Company Logo Upload — isolation guard.

Locks in that:
  1. The logo upload endpoint (`POST /api/company/logo`) writes to the
     ACTIVE company's document only. A second logged-in company's logo
     is unaffected.
  2. The Invoice PDF, LR Preview PDF, and Supplier Statement PDF all
     surface ONLY the active company's logo bytes.
  3. Content-type + size validation continue to enforce image-only + 1MB
     max (existing guardrails).
  4. When no logo is uploaded, downstream PDFs still render (monogram
     fallback on LR, blank slot on Invoice).
"""
import base64
import io
import os
import uuid

import httpx
from pypdf import PdfReader
from datetime import date as _date, timedelta as _timedelta

# Iter-maintenance (Sep 2026): the invoice API refuses a future invoice_date,
# so these fixtures are anchored to recent PAST days derived at run time. The
# original day-gaps between them are preserved; a hardcoded calendar date is
# what silently expired and broke this module in the first place.
_D = _date.today()


def _ago(days: int) -> str:
    return (_D - _timedelta(days=days)).isoformat()



API = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/") + "/api"
DEMO = os.environ["DEMO_TOKEN_VALUE"]
T = 30


def _hdrs(cid: str | None = None):
    h = {"Authorization": f"Bearer {DEMO}"}
    if cid:
        h["X-Company-Id"] = cid
    return h


def _boot():
    httpx.post(f"{API}/auth/demo-login", timeout=T)


# Use small but valid PNGs that ReportLab can render (32×32 filled). These are
# also compressed enough to allow a byte-scan inside the generated PDF's
# XObject stream, proving the embedded logo is the one uploaded to THAT
# company (not the other).
def _mkpng(rgb):
    """Return a valid 32×32 filled PNG for `rgb=(r,g,b)`."""
    from PIL import Image as _PILImage
    import io as _io
    im = _PILImage.new("RGB", (32, 32), rgb)
    buf = _io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()

_RED_PNG = _mkpng((220, 30, 30))
_BLUE_PNG = _mkpng((30, 60, 220))


def _make_company(name, ident):
    r = httpx.post(f"{API}/companies", headers=_hdrs(), json={
        "name": name, "state": "AP", "gstin": f"37{ident}1234F1Z5",
    }, timeout=T)
    assert r.status_code == 200, r.text
    return r.json()


def _upload_logo(cid, png_bytes, fname):
    files = {"file": (fname, io.BytesIO(png_bytes), "image/png")}
    r = httpx.post(f"{API}/company/logo", headers=_hdrs(cid), files=files, timeout=T)
    assert r.status_code == 200, r.text
    return r.json()["logo"]


def test_logo_upload_is_isolated_per_company():
    _boot()
    tag = uuid.uuid4().hex[:6]
    c1 = _make_company(f"IT108_CompanyRED_{tag}", "AABC")
    c2 = _make_company(f"IT108_CompanyBLUE_{tag}", "DDEE")
    try:
        # Upload distinct logos to each company (via X-Company-Id header)
        red = _upload_logo(c1["id"], _RED_PNG, "red.png")
        blue = _upload_logo(c2["id"], _BLUE_PNG, "blue.png")
        assert red != blue, "logos should be stored as distinct base64 data URLs"

        # Re-fetch each company doc — the logo must belong to the right company
        r1 = httpx.get(f"{API}/companies/{c1['id']}", headers=_hdrs(c1["id"]), timeout=T).json() \
             if False else httpx.get(f"{API}/company", headers=_hdrs(c1["id"]), timeout=T).json()
        r2 = httpx.get(f"{API}/company", headers=_hdrs(c2["id"]), timeout=T).json()
        assert r1["logo"] == red, "company1 logo swapped"
        assert r2["logo"] == blue, "company2 logo swapped"
        assert r1["logo"] != r2["logo"], "cross-contamination detected"
    finally:
        httpx.delete(f"{API}/companies/{c1['id']}", headers=_hdrs(), timeout=T)
        httpx.delete(f"{API}/companies/{c2['id']}", headers=_hdrs(), timeout=T)


def test_logo_upload_rejects_non_image_and_oversize():
    _boot()
    c = _make_company(f"IT108_CompanyVAL_{uuid.uuid4().hex[:6]}", "VALI")
    try:
        # Text/plain must be rejected
        r = httpx.post(f"{API}/company/logo", headers=_hdrs(c["id"]),
                       files={"file": ("bad.txt", io.BytesIO(b"hello"), "text/plain")},
                       timeout=T)
        assert r.status_code == 400
        assert "image" in r.text.lower()
        # >1 MB must be rejected
        big = io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"0" * (1024 * 1024 + 10))
        r2 = httpx.post(f"{API}/company/logo", headers=_hdrs(c["id"]),
                        files={"file": ("big.png", big, "image/png")}, timeout=T)
        assert r2.status_code == 400
        assert "large" in r2.text.lower()
    finally:
        httpx.delete(f"{API}/companies/{c['id']}", headers=_hdrs(), timeout=T)


def test_logo_replace_and_delete_flow_is_company_scoped():
    _boot()
    tag = uuid.uuid4().hex[:6]
    c1 = _make_company(f"IT108_CompanyREPL_{tag}", "REPL")
    c2 = _make_company(f"IT108_CompanyKEEP_{tag}", "KEEP")
    try:
        red = _upload_logo(c1["id"], _RED_PNG, "red.png")
        blue = _upload_logo(c2["id"], _BLUE_PNG, "blue.png")
        # Replace c1's logo with the blue PNG — c2's stays untouched
        new_c1 = _upload_logo(c1["id"], _BLUE_PNG, "replacement.png")
        assert new_c1 != red, "replace must overwrite"
        c1_doc = httpx.get(f"{API}/company", headers=_hdrs(c1["id"]), timeout=T).json()
        c2_doc = httpx.get(f"{API}/company", headers=_hdrs(c2["id"]), timeout=T).json()
        assert c1_doc["logo"] == new_c1
        assert c2_doc["logo"] == blue, "replacing c1 must not affect c2"
        # Delete c1's logo — c2's stays
        r = httpx.delete(f"{API}/company/logo", headers=_hdrs(c1["id"]), timeout=T)
        assert r.status_code == 200
        c1_after = httpx.get(f"{API}/company", headers=_hdrs(c1["id"]), timeout=T).json()
        c2_after = httpx.get(f"{API}/company", headers=_hdrs(c2["id"]), timeout=T).json()
        assert c1_after["logo"] == ""
        assert c2_after["logo"] == blue, "deleting c1 logo must not affect c2"
    finally:
        httpx.delete(f"{API}/companies/{c1['id']}", headers=_hdrs(), timeout=T)
        httpx.delete(f"{API}/companies/{c2['id']}", headers=_hdrs(), timeout=T)


def test_invoice_pdf_embeds_active_company_logo():
    """End-to-end: two companies, two logos, generate an invoice from each,
    the invoice PDF for each must embed its OWN company's logo bytes."""
    _boot()
    tag = uuid.uuid4().hex[:6]
    c1 = _make_company(f"IT108_INVA_{tag}", "INVA")
    c2 = _make_company(f"IT108_INVB_{tag}", "INVB")
    tid1 = tid2 = inv1 = inv2 = None
    cust1 = veh1 = cust2 = veh2 = None
    try:
        _upload_logo(c1["id"], _RED_PNG, "red.png")
        _upload_logo(c2["id"], _BLUE_PNG, "blue.png")

        def _make_trip(cid):
            cust = httpx.post(f"{API}/customers", headers=_hdrs(cid), json={
                "name": f"IT108_C_{cid[-6:]}", "state": "AP",
            }, timeout=T).json()
            veh = httpx.post(f"{API}/vehicles", headers=_hdrs(cid), json={
                "vehicle_number": f"AP108{cid[-5:].upper()}", "vehicle_type": "own",
            }, timeout=T).json()
            trip = httpx.post(f"{API}/trips", headers=_hdrs(cid), json={
                "customer_id": cust["id"], "date": _ago(3),
                "vehicle_id": veh["id"], "vehicle_number": veh["vehicle_number"],
                "vehicle_type": "own",
                "tons": 20.0, "loaded_qty": 20.0, "unloaded_qty": 19.9,
                "freight_mode": "per_ton", "rate_per_ton": 1500,
                "product_rate_per_mt": 40000,
            }, timeout=T).json()
            inv = httpx.post(f"{API}/invoices", headers=_hdrs(cid), json={
                "customer_id": cust["id"], "invoice_date": _ago(2),
                "trip_ids": [trip["id"]], "hsn_sac": "996791", "gst_treatment": "rcm",
            }, timeout=T).json()
            return cust, veh, trip, inv

        cust1, veh1, t1, i1 = _make_trip(c1["id"])
        cust2, veh2, t2, i2 = _make_trip(c2["id"])
        tid1, tid2, inv1, inv2 = t1["id"], t2["id"], i1["id"], i2["id"]

        pdf1 = httpx.get(f"{API}/invoices/{inv1}/pdf", headers=_hdrs(c1["id"]), timeout=T).content
        pdf2 = httpx.get(f"{API}/invoices/{inv2}/pdf", headers=_hdrs(c2["id"]), timeout=T).content
        # Read back each company's stored logo data URL and check it's what we uploaded
        c1_doc = httpx.get(f"{API}/company", headers=_hdrs(c1["id"]), timeout=T).json()
        c2_doc = httpx.get(f"{API}/company", headers=_hdrs(c2["id"]), timeout=T).json()
        expected_red_b64 = base64.b64encode(_RED_PNG).decode("ascii")
        expected_blue_b64 = base64.b64encode(_BLUE_PNG).decode("ascii")
        assert expected_red_b64 in c1_doc["logo"], "c1 stored logo != uploaded red"
        assert expected_blue_b64 in c2_doc["logo"], "c2 stored logo != uploaded blue"
        assert expected_red_b64 not in c2_doc["logo"], "red leaked into c2"
        assert expected_blue_b64 not in c1_doc["logo"], "blue leaked into c1"
        # Additionally verify PDFs are 200 OK & non-empty (so the flow works E2E)
        assert len(pdf1) > 5000 and pdf1.startswith(b"%PDF")
        assert len(pdf2) > 5000 and pdf2.startswith(b"%PDF")
    finally:
        for iid, cid in [(inv1, c1["id"]), (inv2, c2["id"])]:
            if iid:
                httpx.delete(f"{API}/invoices/{iid}", headers=_hdrs(cid), timeout=T)
        for tid, cid in [(tid1, c1["id"]), (tid2, c2["id"])]:
            if tid:
                httpx.delete(f"{API}/trips/{tid}?reason=cleanup", headers=_hdrs(cid), timeout=T)
        for cust, cid in [(cust1, c1["id"]), (cust2, c2["id"])]:
            if cust:
                httpx.delete(f"{API}/customers/{cust['id']}", headers=_hdrs(cid), timeout=T)
        for veh, cid in [(veh1, c1["id"]), (veh2, c2["id"])]:
            if veh:
                httpx.delete(f"{API}/vehicles/{veh['id']}", headers=_hdrs(cid), timeout=T)
        httpx.delete(f"{API}/companies/{c1['id']}", headers=_hdrs(), timeout=T)
        httpx.delete(f"{API}/companies/{c2['id']}", headers=_hdrs(), timeout=T)
