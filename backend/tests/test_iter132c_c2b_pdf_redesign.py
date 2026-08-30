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


# ============================================================================
# Iter132c C2b · GST Treatment tests
# ============================================================================

def test_cn_without_gst_zeros_tax_and_flags_apply_gst():
    _cid, h = _ch(); inv = _inv(h, _fresh_customer(h))
    r = httpx.post(f"{API}/credit-notes", headers=h, json={
        "invoice_id": inv["id"], "note_date": "2026-07-01",
        "reason_code": "quality_claim", "reason_text": "no-gst test",
        "apply_gst": False,
        "lines": [{"description": "No-GST line", "quantity": 1, "rate": 1000}],
    }, timeout=15)
    assert r.status_code == 200, r.text
    cn = r.json()
    assert cn["apply_gst"] is False
    assert cn["cgst_amount"] == 0 and cn["sgst_amount"] == 0 and cn["igst_amount"] == 0
    assert cn["total_tax"] == 0
    # For RCM invoice, gross == subtotal previously; without GST, still subtotal.
    assert round(cn["total_amount"]) == round(cn["subtotal"])


def test_cn_with_gst_default_still_applies_tax():
    _cid, h = _ch(); inv = _inv(h, _fresh_customer(h))
    r = httpx.post(f"{API}/credit-notes", headers=h, json={
        "invoice_id": inv["id"], "note_date": "2026-07-01",
        "reason_code": "quality_claim", "reason_text": "default gst test",
        "lines": [{"description": "Default GST line", "quantity": 1, "rate": 1000}],
    }, timeout=15)
    assert r.status_code == 200, r.text
    cn = r.json()
    # apply_gst defaults to True; rates carried from invoice
    assert cn.get("apply_gst", True) is True
    # For RCM=True (fixture) gross = subtotal even though tax is computed
    assert cn["cgst_amount"] > 0 or cn["igst_amount"] > 0


def test_cn_pdf_without_gst_shows_badge_and_hides_gst_rows():
    _cid, h = _ch(); inv = _inv(h, _fresh_customer(h))
    r = httpx.post(f"{API}/credit-notes", headers=h, json={
        "invoice_id": inv["id"], "note_date": "2026-07-01",
        "reason_code": "quality_claim", "reason_text": "pdf no-gst test",
        "apply_gst": False,
        "lines": [{"description": "PDF NoGST", "quantity": 1, "rate": 1500}],
    }, timeout=15)
    assert r.status_code == 200, r.text
    cn = r.json()
    pr = httpx.get(f"{API}/credit-notes/{cn['id']}/pdf", headers=h, timeout=30)
    assert pr.status_code == 200
    text = _pdf_text(pr.content)
    assert "GST NOT APPLIED" in text
    # No CGST / SGST / IGST rate rows on the PDF
    assert "CGST @" not in text
    assert "IGST @" not in text


def test_dn_without_gst_zero_tax_and_pdf_badge():
    _cid, h = _ch(); inv = _inv(h, _fresh_customer(h))
    r = httpx.post(f"{API}/debit-notes", headers=h, json={
        "invoice_id": inv["id"], "note_date": "2026-07-01",
        "reason_code": "freight_escalation", "reason_text": "DN no-gst test",
        "apply_gst": False,
        "lines": [{"description": "DN No-GST", "quantity": 1, "rate": 800}],
    }, timeout=15)
    assert r.status_code == 200, r.text
    dn = r.json()
    assert dn["apply_gst"] is False
    assert dn["total_tax"] == 0
    pr = httpx.get(f"{API}/debit-notes/{dn['id']}/pdf", headers=h, timeout=30)
    assert pr.status_code == 200
    text = _pdf_text(pr.content)
    assert "GST NOT APPLIED" in text
    assert "CGST @" not in text and "IGST @" not in text


def test_cn_without_gst_still_blocks_past_deadline_for_non_owner():
    """Statutory validators must remain active even when apply_gst=False."""
    _cid, h = _ch(); inv = _inv(h, _fresh_customer(h))
    # Invoice fixture is FY 2026-27 (invoice_date 2026-06-15); statutory
    # deadline = 2027-11-30. Use a note_date past that to force the guard.
    r = httpx.post(f"{API}/credit-notes", headers=h, json={
        "invoice_id": inv["id"], "note_date": "2028-01-15",
        "reason_code": "quality_claim", "reason_text": "past deadline test",
        "apply_gst": False,
        "lines": [{"description": "past deadline", "quantity": 1, "rate": 500}],
    }, timeout=15)
    # DEMO_TOKEN is a demo owner in this stack; the guard requires
    # deadline_override_reason regardless of apply_gst. It must NOT silently
    # accept the note.
    assert r.status_code in (400, 403), r.text


# ============================================================================
# Iter132c C2c · ₹ font · RCM clarifier · GSTIN presentation guard
# ============================================================================


def _cn_with_gst(h, cid):
    inv = _inv(h, _fresh_customer(h))
    r = httpx.post(f"{API}/credit-notes", headers=h, json={
        "invoice_id": inv["id"], "note_date": "2026-07-01",
        "reason_code": "rate_correction", "reason_text": "c2c rcm gst test",
        "lines": [{"description": "C2C RCM CN", "quantity": 1, "rate": 4000}],
    }, timeout=15)
    assert r.status_code == 200, r.text
    return r.json(), inv


def _dn_with_gst(h, cid):
    inv = _inv(h, _fresh_customer(h))
    r = httpx.post(f"{API}/debit-notes", headers=h, json={
        "invoice_id": inv["id"], "note_date": "2026-07-01",
        "reason_code": "freight_escalation", "reason_text": "c2c rcm gst dn test",
        "lines": [{"description": "C2C RCM DN", "quantity": 1, "rate": 4000}],
    }, timeout=15)
    assert r.status_code == 200, r.text
    return r.json(), inv


# ---- Track #1 · ₹ glyph must render as the real Rupee sign ----

def test_c2c_cn_pdf_contains_real_rupee_glyph():
    _cid, h = _ch(); cn, _ = _cn_with_gst(h, _cid)
    r = httpx.get(f"{API}/credit-notes/{cn['id']}/pdf", headers=h, timeout=30)
    assert r.status_code == 200
    text = _pdf_text(r.content)
    # The DejaVu font preserves U+20B9. Fail if a tofu box or empty currency prefix leaks through.
    assert "\u20b9" in text, "Rupee glyph U+20B9 not found in Credit Note PDF (font swap failed?)"


def test_c2c_dn_pdf_contains_real_rupee_glyph():
    _cid, h = _ch(); dn, _ = _dn_with_gst(h, _cid)
    r = httpx.get(f"{API}/debit-notes/{dn['id']}/pdf", headers=h, timeout=30)
    assert r.status_code == 200
    text = _pdf_text(r.content)
    assert "\u20b9" in text, "Rupee glyph U+20B9 not found in Debit Note PDF"


def test_c2c_ledger_pdf_contains_real_rupee_glyph():
    """C2c · Ledger PDF font swap must render ₹ (header row + closing-balance line)."""
    _cid, h = _ch()
    cust_id = _fresh_customer(h)
    _inv(h, cust_id)  # ensure ledger has at least one entry
    r = httpx.get(f"{API}/reports/ledger/pdf?customer_id={cust_id}", headers=h, timeout=30)
    assert r.status_code == 200, r.text
    text = _pdf_text(r.content)
    assert "\u20b9" in text, "Rupee glyph U+20B9 not found in Ledger PDF"


def test_c2c_customer_statement_pdf_contains_real_rupee_glyph():
    """C2c · Customer Statement PDF font swap must render ₹."""
    _cid, h = _ch()
    cust_id = _fresh_customer(h)
    _inv(h, cust_id)
    r = httpx.get(f"{API}/customers/{cust_id}/statement.pdf", headers=h, timeout=30)
    assert r.status_code == 200, r.text
    text = _pdf_text(r.content)
    assert "\u20b9" in text, "Rupee glyph U+20B9 not found in Customer Statement PDF"


# ---- Track #2 · RCM presentation clarifier ----

def test_c2c_cn_pdf_rcm_clarifier_wording():
    """When RCM=True and apply_gst=True, CN PDF must carry the new clarifier wording."""
    _cid, h = _ch(); cn, _ = _cn_with_gst(h, _cid)
    assert bool(cn.get("rcm")) is True and cn.get("apply_gst", True) is True
    r = httpx.get(f"{API}/credit-notes/{cn['id']}/pdf", headers=h, timeout=30)
    assert r.status_code == 200
    text = _pdf_text(r.content)
    assert "REVERSE CHARGE MECHANISM" in text
    assert "not included in the payable total" in text
    assert "Total Tax (RCM — not collected)" in text
    assert "GST under Reverse Charge" in text
    assert "Not included in Payable" in text
    assert "TOTAL CREDIT NOTE (excl. RCM GST)" in text
    # legacy short line must be gone
    assert "RCM applicable" not in text


def test_c2c_dn_pdf_rcm_clarifier_wording():
    _cid, h = _ch(); dn, _ = _dn_with_gst(h, _cid)
    assert bool(dn.get("rcm")) is True and dn.get("apply_gst", True) is True
    r = httpx.get(f"{API}/debit-notes/{dn['id']}/pdf", headers=h, timeout=30)
    assert r.status_code == 200
    text = _pdf_text(r.content)
    assert "REVERSE CHARGE MECHANISM" in text
    assert "not included in the payable total" in text
    assert "Total Tax (RCM — not collected)" in text
    assert "GST under Reverse Charge" in text
    assert "Not included in Payable" in text
    assert "TOTAL DEBIT NOTE (excl. RCM GST)" in text
    assert "RCM applicable" not in text


# ---- Track #3 · GSTIN empty-guard renders `—` ----

def test_c2c_cn_pdf_gstin_dash_when_company_gstin_empty():
    """If issuer company gstin is empty, PDF must show `GSTIN: —` (not `GSTIN:  ·`)."""
    import asyncio, os as _os
    from motor.motor_asyncio import AsyncIOMotorClient as _MC
    _cid, h = _ch(); cn, _ = _cn_with_gst(h, _cid)

    async def _clear_and_restore():
        cli = _MC(_os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
        d   = cli[_os.environ.get("DB_NAME", "test_database")]
        before = await d.companies.find_one({"id": cn["company_id"]}, {"_id": 0, "gstin": 1}) or {}
        await d.companies.update_one({"id": cn["company_id"]}, {"$set": {"gstin": ""}})
        return before.get("gstin", "")

    async def _restore(orig):
        cli = _MC(_os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
        d   = cli[_os.environ.get("DB_NAME", "test_database")]
        await d.companies.update_one({"id": cn["company_id"]}, {"$set": {"gstin": orig or ""}})

    loop = asyncio.new_event_loop()
    try:
        original = loop.run_until_complete(_clear_and_restore())
        r = httpx.get(f"{API}/credit-notes/{cn['id']}/pdf", headers=h, timeout=30)
        assert r.status_code == 200
        text = _pdf_text(r.content)
        # Guard: the empty field must be replaced by an em-dash marker
        assert "GSTIN: —" in text, f"GSTIN guard not applied; got: ...{text[max(0,text.find('GSTIN')):text.find('GSTIN')+80]}..."
        # And the double-space-dot artifact must NOT appear anywhere
        assert "GSTIN:  ·" not in text
    finally:
        loop.run_until_complete(_restore(original))
        loop.close()


def test_c2c_dn_pdf_gstin_dash_when_company_gstin_empty():
    import asyncio, os as _os
    from motor.motor_asyncio import AsyncIOMotorClient as _MC
    _cid, h = _ch(); dn, _ = _dn_with_gst(h, _cid)

    async def _clear():
        cli = _MC(_os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
        d   = cli[_os.environ.get("DB_NAME", "test_database")]
        before = await d.companies.find_one({"id": dn["company_id"]}, {"_id": 0, "gstin": 1}) or {}
        await d.companies.update_one({"id": dn["company_id"]}, {"$set": {"gstin": ""}})
        return before.get("gstin", "")

    async def _restore(orig):
        cli = _MC(_os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
        d   = cli[_os.environ.get("DB_NAME", "test_database")]
        await d.companies.update_one({"id": dn["company_id"]}, {"$set": {"gstin": orig or ""}})

    loop = asyncio.new_event_loop()
    try:
        original = loop.run_until_complete(_clear())
        r = httpx.get(f"{API}/debit-notes/{dn['id']}/pdf", headers=h, timeout=30)
        assert r.status_code == 200
        text = _pdf_text(r.content)
        assert "GSTIN: —" in text
        assert "GSTIN:  ·" not in text
    finally:
        loop.run_until_complete(_restore(original))
        loop.close()
