"""Iter132c C2 refinement · CN/DN PDF redesign regression."""
import os, uuid, httpx

BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = BASE + "/api"
HDR = {"Authorization": f"Bearer {os.environ['DEMO_TOKEN_VALUE']}"}


def _ch():
    c = httpx.get(f"{API}/companies", headers=HDR, timeout=15).json()
    return c[0]["id"], {**HDR, "X-Company-Id": c[0]["id"]}


def _fresh_customer(h):
    tag = uuid.uuid4().hex[:8]
    r = httpx.post(f"{API}/customers", headers=h, json={
        "name": f"C2R-{tag}", "phone": f"9{tag[:9]}", "email": f"{tag}@c2r.test", "state": "Andhra Pradesh"
    }, timeout=15); assert r.status_code == 200
    return r.json()["id"]


def _inv(h, cust):
    tag = uuid.uuid4().hex[:6]
    tr = httpx.post(f"{API}/trips", headers=h, json={
        "customer_id": cust, "date": "2026-06-01", "vehicle_number": f"CR{tag[:4].upper()}",
        "tons": 20, "loaded_qty": 20, "unloaded_qty": 20,
        "freight_mode": "per_ton", "rate_per_ton": 900, "product_rate_per_mt": 40000,
        "from_location": "A", "to_location": "B", "loading_date": "2026-06-01", "unloading_date": "2026-06-02",
    }, timeout=15); assert tr.status_code == 200
    r = httpx.post(f"{API}/invoices", headers=h, json={
        "customer_id": cust, "trip_ids": [tr.json()["id"]], "invoice_date": "2026-06-15", "rcm": True
    }, timeout=15); assert r.status_code == 200
    return r.json()


def _cn(inv, h, amt=1500.0):
    r = httpx.post(f"{API}/credit-notes", headers=h, json={
        "invoice_id": inv["id"], "note_date": "2026-07-01",
        "reason_code": "quality_claim", "reason_text": "C2R test",
        "lines": [{"description": "Redesign line", "quantity": 1, "rate": amt}],
    }, timeout=15); assert r.status_code == 200
    return r.json()


def _dn(inv, h, amt=1200.0):
    r = httpx.post(f"{API}/debit-notes", headers=h, json={
        "invoice_id": inv["id"], "note_date": "2026-07-01",
        "reason_code": "freight_escalation", "reason_text": "C2R DN test",
        "lines": [{"description": "Debit line", "quantity": 1, "rate": amt}],
    }, timeout=15); assert r.status_code == 200
    return r.json()


def _pdf_text(b):
    try:
        from pdfminer.high_level import extract_text
        from io import BytesIO
        return extract_text(BytesIO(b))
    except Exception:
        return b.decode("latin-1", errors="ignore")


def test_cn_pdf_title_and_reference_invoice_present():
    _cid, h = _ch(); inv = _inv(h, _fresh_customer(h)); cn = _cn(inv, h)
    r = httpx.get(f"{API}/credit-notes/{cn['id']}/pdf", headers=h, timeout=30)
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    text = _pdf_text(r.content)
    assert "CREDIT NOTE" in text
    assert inv["invoice_number"] in text


def test_dn_pdf_title_and_reference_invoice_present():
    _cid, h = _ch(); inv = _inv(h, _fresh_customer(h)); dn = _dn(inv, h)
    r = httpx.get(f"{API}/debit-notes/{dn['id']}/pdf", headers=h, timeout=30)
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    text = _pdf_text(r.content)
    assert "DEBIT NOTE" in text
    assert inv["invoice_number"] in text


def test_cn_pdf_business_values_identical():
    _cid, h = _ch(); inv = _inv(h, _fresh_customer(h)); cn = _cn(inv, h, amt=2500)
    r = httpx.get(f"{API}/credit-notes/{cn['id']}/pdf", headers=h, timeout=30)
    text = _pdf_text(r.content)
    # Total amount must appear
    assert f"{cn['total_amount']:,.2f}" in text.replace(",", ",") or f"{cn['total_amount']:.2f}" in text


def test_dn_pdf_business_values_identical():
    _cid, h = _ch(); inv = _inv(h, _fresh_customer(h)); dn = _dn(inv, h, amt=1800)
    r = httpx.get(f"{API}/debit-notes/{dn['id']}/pdf", headers=h, timeout=30)
    text = _pdf_text(r.content)
    assert f"{dn['total_amount']:.2f}" in text or f"{dn['total_amount']:,.2f}" in text


def test_cn_pdf_amount_in_words_present():
    _cid, h = _ch(); inv = _inv(h, _fresh_customer(h)); cn = _cn(inv, h)
    r = httpx.get(f"{API}/credit-notes/{cn['id']}/pdf", headers=h, timeout=30)
    text = _pdf_text(r.content)
    assert "Amount in Words" in text and "Only" in text


def test_dn_pdf_reason_present():
    _cid, h = _ch(); inv = _inv(h, _fresh_customer(h)); dn = _dn(inv, h)
    r = httpx.get(f"{API}/debit-notes/{dn['id']}/pdf", headers=h, timeout=30)
    text = _pdf_text(r.content)
    assert "REASON" in text and "freight_escalation" in text
