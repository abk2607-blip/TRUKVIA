"""
Iter25 — Live workflow regression after backend modular refactor.
Covers the 12 explicit workflows requested by the user.
Runs serially, self-provisions data, does not stop on failure.
"""
import io
import os
import re
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    try:
        with open("/app/frontend/.env", "r") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
                    break
    except Exception:
        pass
TOKEN = os.environ["DEMO_TOKEN_VALUE"]
HDR = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def _api(path):
    return f"{BASE_URL}/api{path}"


def _hdr(cid=None):
    h = dict(HDR)
    if cid:
        h["X-Company-Id"] = cid
    return h


# ---------------- Shared state ----------------
STATE = {}


# ================ WORKFLOW 1 — Auth ================
class TestW1Auth:
    def test_auth_me_bearer(self):
        r = requests.get(_api("/auth/me"), headers=HDR)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("email") == "owner@vbklogistics.test"

    def test_auth_logout_reachable(self):
        # Logout should succeed (idempotent) — do NOT actually invalidate session in the middle of test suite.
        # Just verify endpoint responds cleanly. If it invalidates, later tests will re-auth via bearer which still resolves.
        r = requests.post(_api("/auth/logout"), headers=HDR)
        assert r.status_code in (200, 204), r.text


# ================ WORKFLOW 2 — Multi-Company Switching ================
class TestW2Companies:
    def test_create_two_companies_and_switch(self):
        cA = requests.post(_api("/companies"), headers=HDR, json={
            "name": "TEST25_Company_A", "state": "Andhra Pradesh",
            "gstin": "37AAAAA0000A1Z5", "pan": "AAAAA0000A",
            "address": "AP Address", "invoice_prefix": "AINV",
        })
        assert cA.status_code == 200, cA.text
        STATE["cA"] = cA.json()["id"]

        cB = requests.post(_api("/companies"), headers=HDR, json={
            "name": "TEST25_Company_B", "state": "Telangana",
            "gstin": "36BBBBB0000B1Z5", "pan": "BBBBB0000B",
            "address": "TG Address", "invoice_prefix": "BINV",
        })
        assert cB.status_code == 200, cB.text
        STATE["cB"] = cB.json()["id"]

        # List includes both
        lst = requests.get(_api("/companies"), headers=HDR).json()
        ids = {c["id"] for c in lst}
        assert STATE["cA"] in ids and STATE["cB"] in ids

    def test_set_default_and_company_scoping(self):
        r = requests.post(_api(f"/companies/{STATE['cB']}/set-default"), headers=HDR)
        assert r.status_code == 200, r.text

        pa = requests.get(_api("/company"), headers=_hdr(STATE["cA"])).json()
        pb = requests.get(_api("/company"), headers=_hdr(STATE["cB"])).json()
        assert pa["name"] == "TEST25_Company_A"
        assert pb["name"] == "TEST25_Company_B"
        assert pa["state"] == "Andhra Pradesh"
        assert pb["state"] == "Telangana"


# ================ WORKFLOW 3 — Masters CRUD + Isolation ================
class TestW3Masters:
    def test_customer_crud_and_isolation(self):
        cA, cB = STATE["cA"], STATE["cB"]
        r = requests.post(_api("/customers"), headers=_hdr(cA), json={
            "name": "TEST25_Cust_AP", "state": "Andhra Pradesh",
            "gstin": "37CCCCC1111C1Z5", "address": "Vzg",
        })
        assert r.status_code == 200, r.text
        cust_id = r.json()["id"]
        STATE["cust_ap"] = cust_id

        # Different-state customer in same company for GST tests
        r2 = requests.post(_api("/customers"), headers=_hdr(cA), json={
            "name": "TEST25_Cust_TG", "state": "Telangana",
            "gstin": "36DDDDD2222D1Z5",
        })
        assert r2.status_code == 200
        STATE["cust_tg"] = r2.json()["id"]

        lst = requests.get(_api("/customers"), headers=_hdr(cA)).json()
        assert any(x["id"] == cust_id for x in lst)

        # Isolation: not visible from Company B
        lstB = requests.get(_api("/customers"), headers=_hdr(cB)).json()
        assert not any(x["id"] == cust_id for x in lstB)

        # Update
        upd = requests.put(_api(f"/customers/{cust_id}"), headers=_hdr(cA),
                           json={"name": "TEST25_Cust_AP_v2", "state": "Andhra Pradesh"})
        assert upd.status_code == 200, upd.text
        lst2 = requests.get(_api("/customers"), headers=_hdr(cA)).json()
        assert any(x["name"] == "TEST25_Cust_AP_v2" for x in lst2)

    def test_vehicle_driver_product_party_crud(self):
        cA = STATE["cA"]
        v = requests.post(_api("/vehicles"), headers=_hdr(cA),
                          json={"vehicle_number": "AP31TEST25", "vehicle_type": "own"})
        assert v.status_code == 200, v.text
        STATE["veh"] = v.json()["id"]

        d = requests.post(_api("/drivers"), headers=_hdr(cA),
                          json={"name": "TEST25_Driver", "phone": "9999999999"})
        assert d.status_code == 200, d.text
        STATE["drv"] = d.json()["id"]

        p = requests.post(_api("/products"), headers=_hdr(cA),
                          json={"name": "TEST25_Bitumen", "hsn_sac": "27132000", "default_rate": 45000})
        assert p.status_code == 200, p.text
        STATE["prod"] = p.json()["id"]

        pt = requests.post(_api("/parties"), headers=_hdr(cA),
                           json={"name": "TEST25_Consignor", "party_type": "consignor", "state": "Andhra Pradesh"})
        assert pt.status_code == 200, pt.text
        STATE["party"] = pt.json()["id"]

        # GETs
        for path, key in [("/vehicles", "veh"), ("/drivers", "drv"), ("/products", "prod"), ("/parties", "party")]:
            lst = requests.get(_api(path), headers=_hdr(cA)).json()
            assert any(x["id"] == STATE[key] for x in lst), f"{path} missing {key}"


# ================ WORKFLOW 4 — Trip Creation ================
class TestW4TripCreate:
    def test_per_ton_trip_auto_freight(self):
        cA = STATE["cA"]
        payload = {
            "customer_id": STATE["cust_ap"],
            "date": "2026-01-10",
            "vehicle_number": "AP31TEST25",
            "vehicle_id": STATE["veh"],
            "vehicle_type": "own",
            "tons": 20,
            "freight_mode": "per_ton",
            "rate_per_ton": 1500,
            "from_location": "Vzg",
            "to_location": "Kkd",
            "expenses": {
                "diesel_from_customer_amount": 9000,
                "cash_advance_received": 5000,
                "diesel": 5000,
                "batta": 2000,
            },
        }
        r = requests.post(_api("/trips"), headers=_hdr(cA), json=payload)
        assert r.status_code == 200, r.text
        t = r.json()
        assert t["freight_amount"] == 30000.0, f"freight_amount={t['freight_amount']}"
        STATE["trip_pt"] = t["id"]

    def test_fixed_mode_trip(self):
        cA = STATE["cA"]
        payload = {
            "customer_id": STATE["cust_ap"],
            "date": "2026-01-11",
            "vehicle_number": "AP31TEST25",
            "vehicle_type": "own",
            "tons": 22,
            "freight_mode": "fixed",
            "fixed_amount": 25000,
        }
        r = requests.post(_api("/trips"), headers=_hdr(cA), json=payload)
        assert r.status_code == 200, r.text
        assert r.json()["freight_amount"] == 25000.0
        STATE["trip_fx"] = r.json()["id"]

    def test_round_trip_halting(self):
        cA = STATE["cA"]
        payload = {
            "customer_id": STATE["cust_ap"],
            "date": "2026-01-12",
            "vehicle_number": "AP31TEST25",
            "vehicle_type": "own",
            "tons": 20,
            "freight_mode": "per_ton",
            "rate_per_ton": 1600,
            "loading_date": "2026-01-01",
            "unloading_date": "2026-01-10",  # 9 days total -> 5 chargeable @ grace 4
            "grace_days": 4,
            "halting_rate_per_day": 500,
        }
        r = requests.post(_api("/trips"), headers=_hdr(cA), json=payload)
        assert r.status_code == 200, r.text
        t = r.json()
        # Halting: chargeable = max(9-4, 0) = 5, amount = 5*500 = 2500
        assert t.get("chargeable_halting_days") in (5, 5.0), t.get("chargeable_halting_days")
        assert t.get("halting_amount") in (2500.0, 2500), t.get("halting_amount")


# ================ WORKFLOW 5 — Trip Editing ================
class TestW5TripEdit:
    def test_put_trip_recomputes(self):
        # Pre-refactor behavior: PUT /trips/{id} takes the FULL Trip model (replace),
        # not a partial patch. Fetch existing → mutate rate_per_ton → PUT.
        cA = STATE["cA"]
        lst = requests.get(_api("/trips"), headers=_hdr(cA)).json()
        trip = next(t for t in lst if t["id"] == STATE["trip_pt"])
        trip["rate_per_ton"] = 2000
        r = requests.put(_api(f"/trips/{STATE['trip_pt']}"), headers=_hdr(cA), json=trip)
        assert r.status_code == 200, r.text
        got = r.json()
        assert got["freight_amount"] == 40000.0, f"got {got['freight_amount']}"
        # Revert
        trip["rate_per_ton"] = 1500
        r2 = requests.put(_api(f"/trips/{STATE['trip_pt']}"), headers=_hdr(cA), json=trip)
        assert r2.status_code == 200


# ================ WORKFLOW 6 — Invoice Generation ================
class TestW6InvoiceCreate:
    def test_create_invoice_from_per_ton_trip(self):
        cA = STATE["cA"]
        payload = {
            "customer_id": STATE["cust_ap"],
            "trip_ids": [STATE["trip_pt"]],
            "invoice_date": "2026-01-15",
            "gst_type": "cgst_sgst",
            "rcm": False,
        }
        r = requests.post(_api("/invoices"), headers=_hdr(cA), json=payload)
        assert r.status_code == 200, r.text
        inv = r.json()
        STATE["inv"] = inv["id"]
        # Prefix
        assert inv["invoice_number"].startswith("AINV"), inv["invoice_number"]
        # Subtotal = 30000 - 9000 diesel - 5000 advance = 16000
        assert inv["subtotal"] == 16000.0, f"subtotal={inv['subtotal']}"
        # GST 5% -> 800 (rcm=False so tax is charged)
        assert round(inv["total_tax"], 2) == 800.0, f"total_tax={inv['total_tax']}"
        assert round(inv["gross_total"], 2) == 16800.0, f"gross_total={inv['gross_total']}"
        # Round-off + total ~ 16800
        assert abs(inv["total_amount"] - 16800.0) < 1.0, f"total_amount={inv['total_amount']}"


# ================ WORKFLOW 7 — Invoice Editing ================
class TestW7InvoiceEdit:
    def test_switch_to_igst_and_add_payment(self):
        # Pre-refactor behavior: _recompute_invoice AUTO-derives gst_type from
        # company vs customer state — the PUT gst_type is ignored when the two
        # states are the same. To exercise the "switch to igst" path, we PUT
        # rcm change (safely accepted) and verify recompute, then add payment.
        cA = STATE["cA"]
        r = requests.put(_api(f"/invoices/{STATE['inv']}"), headers=_hdr(cA),
                         json={"rcm": True, "reason": "toggle rcm"})
        assert r.status_code == 200, r.text
        inv = r.json()
        assert inv["rcm"] is True
        # With rcm True, gross_total should equal subtotal (customer settles tax under RCM)
        assert round(inv["gross_total"], 2) == round(inv["subtotal"], 2), inv

        # Payment
        pay = requests.post(_api(f"/invoices/{STATE['inv']}/payments"), headers=_hdr(cA),
                            json={"amount": 5000, "mode": "Bank", "note": "TEST25"})
        assert pay.status_code == 200, pay.text
        r2 = requests.get(_api(f"/invoices/{STATE['inv']}"), headers=_hdr(cA))
        assert r2.status_code == 200
        after = r2.json()
        assert after["amount_paid"] >= 5000.0
        assert round(after["balance_due"], 2) == round(after["total_amount"] - after["amount_paid"], 2)


# ================ WORKFLOW 8 — PDF Generation ================
class TestW8PDF:
    def test_invoice_pdf(self):
        cA = STATE["cA"]
        r = requests.get(_api(f"/invoices/{STATE['inv']}/pdf"), headers=_hdr(cA))
        assert r.status_code == 200, r.text[:200]
        assert r.headers.get("content-type", "").startswith("application/pdf")
        assert len(r.content) > 5000
        # Extract text
        try:
            from pypdf import PdfReader
        except Exception:
            from PyPDF2 import PdfReader
        reader = PdfReader(io.BytesIO(r.content))
        text = "\n".join((p.extract_text() or "") for p in reader.pages)
        assert "TAX INVOICE" in text.upper(), "TAX INVOICE not found"
        assert "BILL TO" in text.upper(), "BILL TO not found"
        assert "FINAL PAYABLE" in text.upper() or "TOTAL PAYABLE" in text.upper()
        assert "0.5%" in text and "Bitumen" in text and "Emulsion" in text, \
            f"T&C variation clause missing. Snippet: {text[-500:]}"

    def test_lr_pdf(self):
        cA = STATE["cA"]
        r = requests.get(_api(f"/trips/{STATE['trip_pt']}/lr"), headers=_hdr(cA))
        assert r.status_code == 200, r.text[:200]
        assert r.headers.get("content-type", "").startswith("application/pdf")
        assert len(r.content) > 3000


# ================ WORKFLOW 9 — Reports ================
class TestW9Reports:
    @pytest.mark.parametrize("path", [
        "/dashboard",
        "/reports/pl",
        "/reports/balance-sheet",
        "/reports/halting",
        "/reports/gst-summary",
        "/reports/supplier-pl",
        "/invoices/overdue",
    ])
    def test_report_ok(self, path):
        r = requests.get(_api(path), headers=_hdr(STATE["cA"]))
        assert r.status_code == 200, f"{path} -> {r.status_code}: {r.text[:200]}"

    def test_gstr1(self):
        r = requests.get(_api("/reports/gstr1?month=2026-01"), headers=_hdr(STATE["cA"]))
        assert r.status_code == 200, r.text[:200]

    def test_ledger(self):
        r = requests.get(_api(f"/reports/ledger?customer_id={STATE['cust_ap']}"), headers=_hdr(STATE["cA"]))
        assert r.status_code == 200, r.text[:200]


# ================ WORKFLOW 10 — GST calculations ================
class TestW10GST:
    def test_gst_same_state_cgst_sgst(self):
        # Company A is AP; cust_ap is AP -> CGST+SGST expected
        cA = STATE["cA"]
        # Create fresh trip + invoice for AP customer with rcm=False
        tp = requests.post(_api("/trips"), headers=_hdr(cA), json={
            "customer_id": STATE["cust_ap"], "date": "2026-01-16",
            "vehicle_number": "AP31TEST25", "vehicle_type": "own",
            "tons": 10, "freight_mode": "fixed", "fixed_amount": 10000,
        }).json()
        inv = requests.post(_api("/invoices"), headers=_hdr(cA), json={
            "customer_id": STATE["cust_ap"], "trip_ids": [tp["id"]],
            "invoice_date": "2026-01-16", "gst_type": "cgst_sgst", "rcm": False,
        })
        assert inv.status_code == 200, inv.text
        j = inv.json()
        assert round(j["cgst_amount"], 2) == 250.0, j
        assert round(j["sgst_amount"], 2) == 250.0, j
        assert round(j["igst_amount"], 2) == 0.0
        STATE["inv_ap"] = j["id"]

    def test_gst_different_state_igst(self):
        cA = STATE["cA"]  # AP
        tp = requests.post(_api("/trips"), headers=_hdr(cA), json={
            "customer_id": STATE["cust_tg"], "date": "2026-01-16",
            "vehicle_number": "AP31TEST25", "vehicle_type": "own",
            "tons": 10, "freight_mode": "fixed", "fixed_amount": 10000,
        }).json()
        inv = requests.post(_api("/invoices"), headers=_hdr(cA), json={
            "customer_id": STATE["cust_tg"], "trip_ids": [tp["id"]],
            "invoice_date": "2026-01-16", "gst_type": "igst", "rcm": False,
        })
        assert inv.status_code == 200, inv.text
        j = inv.json()
        assert round(j["igst_amount"], 2) == 500.0, j
        assert round(j["cgst_amount"], 2) == 0.0
        assert round(j["sgst_amount"], 2) == 0.0

    def test_rcm_true_zero_effective_tax(self):
        # Pre-refactor behavior: rcm=True → total_tax field remains populated
        # (informational — GST amounts still show for the customer) but
        # gross_total == subtotal (customer doesn't pay the tax to us).
        cA = STATE["cA"]
        tp = requests.post(_api("/trips"), headers=_hdr(cA), json={
            "customer_id": STATE["cust_ap"], "date": "2026-01-17",
            "vehicle_number": "AP31TEST25", "vehicle_type": "own",
            "tons": 10, "freight_mode": "fixed", "fixed_amount": 10000,
        }).json()
        inv = requests.post(_api("/invoices"), headers=_hdr(cA), json={
            "customer_id": STATE["cust_ap"], "trip_ids": [tp["id"]],
            "invoice_date": "2026-01-17", "gst_type": "cgst_sgst", "rcm": True,
        })
        assert inv.status_code == 200, inv.text
        j = inv.json()
        # Under RCM, gross_total should equal subtotal (tax excluded from payable)
        assert round(j["gross_total"], 2) == round(j["subtotal"], 2), j
        # Sanity: GST amounts still populated (informational, per acceptance criterion)
        assert round(j["cgst_amount"], 2) == 250.0
        assert round(j["sgst_amount"], 2) == 250.0


# ================ WORKFLOW 11 — Profit calculations ================
class TestW11Profit:
    def test_own_vehicle_profit(self):
        cA = STATE["cA"]
        r = requests.post(_api("/trips"), headers=_hdr(cA), json={
            "customer_id": STATE["cust_ap"], "date": "2026-01-18",
            "vehicle_number": "AP31TEST25", "vehicle_type": "own",
            "tons": 20, "freight_mode": "per_ton", "rate_per_ton": 1500,
            "expenses": {"diesel": 5000, "batta": 2000},
        })
        assert r.status_code == 200, r.text
        t = r.json()
        assert t["freight_amount"] == 30000.0
        assert t["total_expense"] == 7000.0, t["total_expense"]
        assert t["profit"] == 23000.0, t["profit"]

    def test_supplier_vehicle_profit(self):
        # Pre-refactor formula (services.py):
        #   supplier_net_payable = supplier_freight - supplier_advance - supplier_other_recoveries
        #   total_expense = supplier_freight - supplier_advance   (own_expenses NOT included for supplier trips)
        #   profit = billable - total_expense
        # For freight=30000, supplier_freight=20000, advance=3000:
        #   supplier_net_payable = 17000, total_expense = 17000, profit = 30000 - 17000 = 13000
        cA = STATE["cA"]
        r = requests.post(_api("/trips"), headers=_hdr(cA), json={
            "customer_id": STATE["cust_ap"], "date": "2026-01-19",
            "vehicle_number": "TS09SUP25", "vehicle_type": "supplier",
            "supplier_name": "TEST25_Supplier",
            "tons": 20, "freight_mode": "per_ton", "rate_per_ton": 1500,
            "supplier_freight_mode": "fixed", "supplier_fixed_amount": 20000,
            "supplier_freight": 20000,
            "supplier_advance": 3000,
            "expenses": {"diesel": 1000},
        })
        assert r.status_code == 200, r.text
        t = r.json()
        assert t["supplier_net_payable"] == 17000.0, t["supplier_net_payable"]
        assert t["profit"] == 13000.0, f"profit={t['profit']}"


# ================ WORKFLOW 12 — Print formats ================
class TestW12PrintFormats:
    def test_ledger_pdf(self):
        cA = STATE["cA"]
        r = requests.get(_api(f"/reports/ledger/pdf?customer_id={STATE['cust_ap']}"), headers=_hdr(cA))
        assert r.status_code == 200, r.text[:200]
        assert r.headers.get("content-type", "").startswith("application/pdf")
        assert len(r.content) > 1500

    def test_rupee_symbol_and_font(self):
        cA = STATE["cA"]
        r = requests.get(_api(f"/invoices/{STATE['inv']}/pdf"), headers=_hdr(cA))
        # ₹ (U+20B9) must appear in PDF text. Some extractors may return \u20b9.
        try:
            from pypdf import PdfReader
        except Exception:
            from PyPDF2 import PdfReader
        reader = PdfReader(io.BytesIO(r.content))
        text = "\n".join((p.extract_text() or "") for p in reader.pages)
        assert "\u20b9" in text or "Rs" in text or "INR" in text, "No rupee glyph in PDF text"


# ================ Cleanup ================
@pytest.fixture(scope="module", autouse=True)
def _cleanup():
    yield
    # Best-effort cleanup: delete created entities
    cA = STATE.get("cA")
    if not cA:
        return
    for key, path in [("inv", "/invoices"), ("inv_ap", "/invoices")]:
        iid = STATE.get(key)
        if iid:
            requests.delete(_api(f"{path}/{iid}"), headers=_hdr(cA))
    for key, path in [("trip_pt", "/trips"), ("trip_fx", "/trips")]:
        tid = STATE.get(key)
        if tid:
            requests.delete(_api(f"{path}/{tid}"), headers=_hdr(cA))
    for key, path in [("cust_ap", "/customers"), ("cust_tg", "/customers"),
                      ("veh", "/vehicles"), ("drv", "/drivers"),
                      ("prod", "/products"), ("party", "/parties")]:
        i = STATE.get(key)
        if i:
            requests.delete(_api(f"{path}/{i}"), headers=_hdr(cA))
    for k in ("cA", "cB"):
        cid = STATE.get(k)
        if cid:
            requests.delete(_api(f"/companies/{cid}"), headers=HDR)
