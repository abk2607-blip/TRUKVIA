"""Iteration 12 backend tests:
- Auto-GST based on company vs customer state
- Round-off to nearest rupee (with new gross_total + round_off fields)
- Invoice model fields (freight_total/halting_total/excess_total/shortage_total/gross_total/round_off)
- _recompute_invoice re-runs auto-GST + round-off
- PDF: DejaVu font, ₹ character, halting/shortage sub-rows, Total Amount + Round Off + FINAL PAYABLE, new T&C.
"""
import os
import re
import io
import pytest
import requests
import fitz  # PyMuPDF

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://trip-billing-pro-1.preview.emergentagent.com").rstrip("/")
TOKEN = os.environ["DEMO_TOKEN_VALUE"]
HDRS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def _cleanup(uid_prefix=""):
    """Best-effort cleanup: delete all invoices/trips/customers for the test user."""
    try:
        invs = requests.get(f"{BASE_URL}/api/invoices", headers=HDRS, timeout=15).json()
        for i in invs:
            requests.delete(f"{BASE_URL}/api/invoices/{i['id']}?reason=test-cleanup", headers=HDRS, timeout=15)
        trips = requests.get(f"{BASE_URL}/api/trips", headers=HDRS, timeout=15).json()
        for t in trips:
            requests.delete(f"{BASE_URL}/api/trips/{t['id']}?reason=test-cleanup", headers=HDRS, timeout=15)
        custs = requests.get(f"{BASE_URL}/api/customers", headers=HDRS, timeout=15).json()
        for c in custs:
            requests.delete(f"{BASE_URL}/api/customers/{c['id']}", headers=HDRS, timeout=15)
    except Exception as e:
        print(f"cleanup err: {e}")


@pytest.fixture(scope="module", autouse=True)
def _clean_around():
    _cleanup()
    yield
    _cleanup()


def _set_company(state):
    payload = {
        "name": "Test Bitumen Transports",
        "address": "Vijayawada",
        "phone": "9999999999",
        "email": "t@t.com",
        "gstin": "37ABCDE1234F1Z5",
        "pan": "ABCDE1234F",
        "state": state,
        "pincode": "520001",
        "bank_name": "SBI",
        "account_number": "1234567890",
        "ifsc": "SBIN0000123",
        "branch": "VJA",
        "hsn_sac": "996791",
        "invoice_prefix": "INV",
        "next_invoice_number": 1,
        "lr_prefix": "LR",
        "next_lr_number": 1,
        "logo": "",
    }
    r = requests.put(f"{BASE_URL}/api/company", headers=HDRS, json=payload, timeout=15)
    assert r.status_code == 200
    return r.json()


def _make_customer(state, name="TEST_Customer"):
    r = requests.post(f"{BASE_URL}/api/customers", headers=HDRS, json={
        "name": name, "address": "addr", "phone": "9", "gstin": "", "pan": "", "state": state, "pincode": ""
    }, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


def _make_trip(customer_id, tons, rate, extra=None):
    body = {
        "customer_id": customer_id,
        "date": "2026-02-01",
        "vehicle_number": "AP16TA1234",
        "vehicle_type": "own",
        "load_details": "Bitumen VG40",
        "tons": tons,
        "from_location": "A",
        "to_location": "B",
        "freight_mode": "per_ton",
        "rate_per_ton": rate,
    }
    if extra:
        body.update(extra)
    r = requests.post(f"{BASE_URL}/api/trips", headers=HDRS, json=body, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


def _make_invoice(customer_id, trip_ids, gst_type="cgst_sgst", rcm=False):
    r = requests.post(f"{BASE_URL}/api/invoices", headers=HDRS, json={
        "customer_id": customer_id,
        "trip_ids": trip_ids,
        "gst_type": gst_type,
        "rcm": rcm,
    }, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


# ---------- Auto-GST tests ----------
class TestAutoGST:
    def test_same_state_overrides_to_cgst_sgst(self):
        _cleanup()
        _set_company("Andhra Pradesh")
        c = _make_customer("Andhra Pradesh", "TEST_AP_Cust")
        t = _make_trip(c["id"], tons=10, rate=1000)  # freight=10000
        inv = _make_invoice(c["id"], [t["id"]], gst_type="igst", rcm=False)  # attempt to force igst
        assert inv["gst_type"] == "cgst_sgst", f"expected auto override to cgst_sgst, got {inv['gst_type']}"
        assert inv["cgst_amount"] == 250.0
        assert inv["sgst_amount"] == 250.0
        assert inv["igst_amount"] == 0.0

    def test_different_state_overrides_to_igst(self):
        _cleanup()
        _set_company("Andhra Pradesh")
        c = _make_customer("Telangana", "TEST_TS_Cust")
        t = _make_trip(c["id"], tons=10, rate=1000)  # freight=10000
        inv = _make_invoice(c["id"], [t["id"]], gst_type="cgst_sgst", rcm=False)
        assert inv["gst_type"] == "igst"
        assert inv["igst_amount"] == 500.0
        assert inv["cgst_amount"] == 0.0
        assert inv["sgst_amount"] == 0.0


# ---------- Round-off tests ----------
class TestRoundOff:
    def test_round_off_down(self):
        _cleanup()
        _set_company("Andhra Pradesh")
        c = _make_customer("Telangana", "TEST_RO1")
        # tons=13.333 rate=975.60 => freight = 13007.6628 -> 13007.66 (round 2)
        t = _make_trip(c["id"], tons=13.333, rate=975.60)
        inv = _make_invoice(c["id"], [t["id"]], gst_type="igst", rcm=False)
        # subtotal ~= 13007.66; igst 5% = 650.383 -> 650.38; gross = 13658.04
        assert inv["subtotal"] > 13000
        assert inv["gst_type"] == "igst"
        gross = inv["gross_total"]
        total = inv["total_amount"]
        round_off = inv["round_off"]
        # round-half-up to nearest rupee
        assert total == float(int(gross + 0.5))
        assert abs((total - gross) - round_off) < 0.01
        assert total.is_integer()

    def test_round_off_up(self):
        _cleanup()
        _set_company("Andhra Pradesh")
        c = _make_customer("Andhra Pradesh", "TEST_RO2")
        # Contrive freight so gross_total (with cgst+sgst=5%) ends in .60+ to force round up.
        # tons=1, rate=1000.60 -> freight = 1000.60; +5% = 1050.63 -> should round to 1051
        t = _make_trip(c["id"], tons=1, rate=1000.60)
        inv = _make_invoice(c["id"], [t["id"]], gst_type="cgst_sgst", rcm=False)
        gross = inv["gross_total"]
        total = inv["total_amount"]
        assert total >= gross  # rounded up
        assert total.is_integer()
        assert inv["round_off"] > 0


# ---------- Invoice model fields ----------
class TestInvoiceFields:
    def test_all_new_fields_present(self):
        _cleanup()
        _set_company("Andhra Pradesh")
        c = _make_customer("Andhra Pradesh", "TEST_FLD")
        t = _make_trip(c["id"], tons=5, rate=2000, extra={
            "halting_amount": 5000, "halting_amount_override": True,
            "chargeable_halting_days": 2, "halting_rate_per_day": 2500,
            "shortage_qty": 0.5, "product_rate_per_mt": 100, "shortage_amount": 50,
            "excess_qty": 0.0, "excess_amount": 0.0,
        })
        inv = _make_invoice(c["id"], [t["id"]], gst_type="cgst_sgst", rcm=False)
        for k in ("freight_total", "halting_total", "excess_total", "shortage_total",
                  "gross_total", "round_off", "total_amount"):
            assert k in inv, f"missing field {k}"
        assert inv["freight_total"] == 10000.0
        assert inv["halting_total"] == 5000.0
        assert inv["shortage_total"] >= 50.0


# ---------- Recompute on trip edit ----------
class TestRecompute:
    def test_edit_trip_reruns_gst_and_roundoff(self):
        _cleanup()
        _set_company("Andhra Pradesh")
        c = _make_customer("Andhra Pradesh", "TEST_REC")
        t = _make_trip(c["id"], tons=10, rate=1000)
        inv = _make_invoice(c["id"], [t["id"]], gst_type="cgst_sgst", rcm=False)
        assert inv["gst_type"] == "cgst_sgst"
        # Now change customer state to different
        r = requests.put(f"{BASE_URL}/api/customers/{c['id']}", headers=HDRS, json={
            "id": c["id"], "name": "TEST_REC", "address": "", "phone": "", "gstin": "", "pan": "",
            "state": "Telangana", "pincode": ""
        }, timeout=15)
        assert r.status_code == 200
        # Trigger recompute by editing trip (same payload)
        trip_body = {**t}
        trip_body.pop("created_at", None)
        r2 = requests.put(f"{BASE_URL}/api/trips/{t['id']}", headers=HDRS, json=trip_body, timeout=15)
        assert r2.status_code == 200
        # Fetch invoice
        inv2 = requests.get(f"{BASE_URL}/api/invoices/{inv['id']}", headers=HDRS, timeout=15).json()
        assert inv2["gst_type"] == "igst", f"recompute did not auto-flip to igst: {inv2['gst_type']}"
        assert inv2["igst_amount"] > 0


# ---------- PDF checks ----------
class TestPDF:
    def test_pdf_renders_all_features(self):
        _cleanup()
        _set_company("Andhra Pradesh")
        c = _make_customer("Telangana", "TEST_PDF")
        # Trip with halting and shortage
        t = _make_trip(c["id"], tons=10, rate=1000, extra={
            "halting_amount": 5000, "halting_amount_override": True,
            "chargeable_halting_days": 2, "halting_rate_per_day": 2500,
            "shortage_qty": 0.5, "product_rate_per_mt": 200,
            "shortage_amount": 100, "shortage_amount_override": True,
        })
        inv = _make_invoice(c["id"], [t["id"]], gst_type="igst", rcm=False)
        r = requests.get(f"{BASE_URL}/api/invoices/{inv['id']}/pdf", headers=HDRS, timeout=30)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("application/pdf")
        pdf_bytes = r.content
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        # Extract text
        text = ""
        for page in doc:
            text += page.get_text()
        print(f"PDF TEXT SAMPLE: {text[:500]}")
        # ₹ character present
        assert "\u20b9" in text, "Rupee symbol U+20B9 missing from PDF"
        # Halting sub-row description
        assert re.search(r"Halting Charges.*?day\(s\).*?×.*?\u20b9", text) or "Halting Charges" in text, "Halting sub-row missing"
        assert "day(s)" in text or "day\u00a0(s)" in text
        # Shortage sub-row
        assert "Shortage" in text
        assert "MT" in text
        # Totals labels
        assert "Total Amount" in text
        assert "FINAL PAYABLE" in text
        # Round Off if non-zero
        if abs(inv.get("round_off", 0)) >= 0.005:
            assert "Round Off" in text
        # New T&C
        assert "Halting Charges applicable after 48 hours" in text
        # Old T&C absent
        assert "Rs. 2,500 per day" not in text
        assert "2,500 per day" not in text

        # Check no black-rectangle glyphs by rendering to pixmap and looking for suspicious
        # font-fallback marker: reportlab draws missing glyphs as black boxes. We check that
        # the DejaVu font is embedded in the PDF fonts list.
        fonts_used = set()
        for page in doc:
            for f in page.get_fonts(full=True):
                fonts_used.add(f[3])  # basefont name
        print(f"Fonts used: {fonts_used}")
        assert any("DejaVu" in fn for fn in fonts_used), f"DejaVu font not embedded; fonts={fonts_used}"
        doc.close()
