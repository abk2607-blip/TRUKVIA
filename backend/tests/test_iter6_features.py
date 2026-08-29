"""Iteration 6 backend tests: Audit trail, Trip/Invoice edit-after-invoicing with
reason+cascade, supplier vehicles + profit, expense recoveries/deductions,
LR redesign (no Telugu), new trip optional fields flow into LR + Invoice PDFs."""
import os
import time
import pytest
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "https://trip-billing-pro-1.preview.emergentagent.com").rstrip("/")
TOKEN = os.environ["DEMO_TOKEN_VALUE"]
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
JSON_HEADERS = {**HEADERS, "Content-Type": "application/json"}
API = f"{BASE_URL}/api"

BASE_EXPENSES = {"diesel": 0, "toll": 0, "batta": 0, "repair": 0, "other": 0}


def _get_trip(tid):
    r = requests.get(f"{API}/trips", headers=HEADERS)
    assert r.status_code == 200
    return next((t for t in r.json() if t["id"] == tid), None)


# ==================== Trip DELETE with reason + audit ====================
class TestTripDeleteReasonAndAudit:
    state = {}

    @classmethod
    def setup_class(cls):
        r = requests.post(f"{API}/customers", headers=JSON_HEADERS,
                          json={"name": "TEST_iter6_del_cust", "state": "Telangana"})
        assert r.status_code == 200, r.text
        cls.state["cid"] = r.json()["id"]

    @classmethod
    def teardown_class(cls):
        if cls.state.get("cid"):
            requests.delete(f"{API}/customers/{cls.state['cid']}", headers=HEADERS)

    def _make_trip(self):
        r = requests.post(f"{API}/trips", headers=JSON_HEADERS, json={
            "customer_id": self.state["cid"], "date": "2026-01-10",
            "vehicle_number": "TS09DEL01", "tons": 10,
            "freight_mode": "fixed", "fixed_amount": 10000,
            "expenses": BASE_EXPENSES,
        })
        assert r.status_code == 200, r.text
        return r.json()["id"]

    def test_01_delete_without_reason_400(self):
        tid = self._make_trip()
        r = requests.delete(f"{API}/trips/{tid}", headers=HEADERS)
        assert r.status_code == 400, r.text
        assert "reason" in r.text.lower()
        # cleanup
        requests.delete(f"{API}/trips/{tid}?reason=cleanup", headers=HEADERS)

    def test_02_delete_with_reason_creates_audit(self):
        tid = self._make_trip()
        r = requests.delete(f"{API}/trips/{tid}", headers=HEADERS, params={"reason": "cleanup"})
        assert r.status_code == 200, r.text
        # Trip gone
        assert _get_trip(tid) is None
        # Audit log entry present
        time.sleep(0.3)
        r = requests.get(f"{API}/audit-logs", headers=HEADERS,
                         params={"module": "trip", "action": "delete", "entity_id": tid})
        assert r.status_code == 200, r.text
        logs = r.json()
        assert len(logs) >= 1
        e = logs[0]
        assert e["reason"] == "cleanup"
        assert e["module"] == "trip" and e["action"] == "delete"
        assert e["entity_id"] == tid
        assert "changes" in e and "snapshot" in e["changes"]


# ==================== Trip DELETE cascades to Invoice ====================
class TestTripDeleteCascade:
    state = {}

    @classmethod
    def setup_class(cls):
        r = requests.post(f"{API}/customers", headers=JSON_HEADERS,
                          json={"name": "TEST_iter6_casc_cust", "state": "Telangana",
                                "gstin": "36AAAAA0000A1Z5"})
        cls.state["cid"] = r.json()["id"]

        # Two trips
        t1 = requests.post(f"{API}/trips", headers=JSON_HEADERS, json={
            "customer_id": cls.state["cid"], "date": "2026-01-05",
            "vehicle_number": "TS09CS1", "tons": 10,
            "freight_mode": "fixed", "fixed_amount": 12000,
            "expenses": BASE_EXPENSES,
        }).json()
        t2 = requests.post(f"{API}/trips", headers=JSON_HEADERS, json={
            "customer_id": cls.state["cid"], "date": "2026-01-06",
            "vehicle_number": "TS09CS2", "tons": 10,
            "freight_mode": "fixed", "fixed_amount": 8000,
            "expenses": BASE_EXPENSES,
        }).json()
        cls.state["t1"], cls.state["t2"] = t1["id"], t2["id"]
        inv = requests.post(f"{API}/invoices", headers=JSON_HEADERS, json={
            "customer_id": cls.state["cid"], "invoice_date": "2026-01-07",
            "trip_ids": [t1["id"], t2["id"]], "gst_type": "cgst_sgst", "rcm": False,
        })
        assert inv.status_code == 200, inv.text
        cls.state["iid"] = inv.json()["id"]

    @classmethod
    def teardown_class(cls):
        if cls.state.get("iid"):
            requests.delete(f"{API}/invoices/{cls.state['iid']}?reason=cleanup", headers=HEADERS)
        for k in ("t1", "t2"):
            if cls.state.get(k):
                requests.delete(f"{API}/trips/{cls.state[k]}?reason=cleanup", headers=HEADERS)
        requests.delete(f"{API}/customers/{cls.state['cid']}", headers=HEADERS)

    def test_delete_cascades(self):
        # initial subtotal = 20000
        inv = requests.get(f"{API}/invoices/{self.state['iid']}", headers=HEADERS).json()
        assert inv["subtotal"] == 20000, inv
        # Delete t2 with reason
        r = requests.delete(f"{API}/trips/{self.state['t2']}", headers=HEADERS,
                            params={"reason": "wrong-entry"})
        assert r.status_code == 200, r.text
        self.state["t2"] = None
        # invoice subtotal should now be 12000
        inv2 = requests.get(f"{API}/invoices/{self.state['iid']}", headers=HEADERS).json()
        assert inv2["subtotal"] == 12000, inv2
        assert inv2["total_amount"] < inv["total_amount"]
        assert inv2["balance_due"] == inv2["total_amount"] - inv2.get("amount_paid", 0)


# ==================== Trip PUT after invoicing recomputes ====================
class TestTripUpdateAfterInvoicing:
    state = {}

    @classmethod
    def setup_class(cls):
        r = requests.post(f"{API}/customers", headers=JSON_HEADERS,
                          json={"name": "TEST_iter6_edit_cust", "state": "Telangana",
                                "gstin": "36AAAAA0000A1Z5"})
        cls.state["cid"] = r.json()["id"]
        t = requests.post(f"{API}/trips", headers=JSON_HEADERS, json={
            "customer_id": cls.state["cid"], "date": "2026-01-05",
            "vehicle_number": "TS09EDT1", "tons": 20,
            "freight_mode": "per_ton", "rate_per_ton": 1000,
            "expenses": BASE_EXPENSES,
        }).json()
        cls.state["tid"] = t["id"]
        assert t["freight_amount"] == 20000
        inv = requests.post(f"{API}/invoices", headers=JSON_HEADERS, json={
            "customer_id": cls.state["cid"], "invoice_date": "2026-01-07",
            "trip_ids": [t["id"]], "gst_type": "cgst_sgst", "rcm": False,
        }).json()
        cls.state["iid"] = inv["id"]

    @classmethod
    def teardown_class(cls):
        if cls.state.get("iid"):
            requests.delete(f"{API}/invoices/{cls.state['iid']}?reason=cleanup", headers=HEADERS)
        if cls.state.get("tid"):
            requests.delete(f"{API}/trips/{cls.state['tid']}?reason=cleanup", headers=HEADERS)
        requests.delete(f"{API}/customers/{cls.state['cid']}", headers=HEADERS)

    def test_put_recomputes_invoice(self):
        # Now update trip to tons=30
        trip = _get_trip(self.state["tid"])
        trip["tons"] = 30
        trip["rate_per_ton"] = 1000
        r = requests.put(f"{API}/trips/{self.state['tid']}", headers=JSON_HEADERS, json=trip)
        assert r.status_code == 200, r.text
        assert r.json()["freight_amount"] == 30000
        # invoice subtotal must be 30000
        inv = requests.get(f"{API}/invoices/{self.state['iid']}", headers=HEADERS).json()
        assert inv["subtotal"] == 30000, inv
        # audit log for trip update exists with changes
        time.sleep(0.2)
        logs = requests.get(f"{API}/audit-logs", headers=HEADERS,
                            params={"module": "trip", "action": "update",
                                    "entity_id": self.state["tid"]}).json()
        assert len(logs) >= 1
        assert "freight_amount" in logs[0].get("changes", {})


# ==================== Invoice PUT + DELETE ====================
class TestInvoiceUpdateDelete:
    state = {}

    @classmethod
    def setup_class(cls):
        r = requests.post(f"{API}/customers", headers=JSON_HEADERS,
                          json={"name": "TEST_iter6_inv_cust", "state": "Karnataka",
                                "gstin": "29AAAAA1111A1Z2"})
        cls.state["cid"] = r.json()["id"]
        t = requests.post(f"{API}/trips", headers=JSON_HEADERS, json={
            "customer_id": cls.state["cid"], "date": "2026-01-05",
            "vehicle_number": "TS09INV1", "tons": 10,
            "freight_mode": "fixed", "fixed_amount": 10000,
            "expenses": BASE_EXPENSES,
        }).json()
        cls.state["tid"] = t["id"]
        inv = requests.post(f"{API}/invoices", headers=JSON_HEADERS, json={
            "customer_id": cls.state["cid"], "invoice_date": "2026-01-07",
            "trip_ids": [t["id"]], "gst_type": "cgst_sgst", "rcm": False,
        }).json()
        cls.state["iid"] = inv["id"]

    @classmethod
    def teardown_class(cls):
        if cls.state.get("iid"):
            requests.delete(f"{API}/invoices/{cls.state['iid']}?reason=cleanup", headers=HEADERS)
        if cls.state.get("tid"):
            requests.delete(f"{API}/trips/{cls.state['tid']}?reason=cleanup", headers=HEADERS)
        requests.delete(f"{API}/customers/{cls.state['cid']}", headers=HEADERS)

    def test_01_put_without_reason_400(self):
        r = requests.put(f"{API}/invoices/{self.state['iid']}", headers=JSON_HEADERS,
                         json={"gst_type": "igst"})
        assert r.status_code == 400, r.text
        assert "reason" in r.text.lower()

    def test_02_put_igst_recompute(self):
        r = requests.put(f"{API}/invoices/{self.state['iid']}", headers=JSON_HEADERS,
                         json={"reason": "GST type change", "gst_type": "igst"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["gst_type"] == "igst"
        assert d["igst_amount"] == 500.0, d
        assert d["cgst_amount"] == 0.0
        assert d["sgst_amount"] == 0.0
        assert d["total_amount"] == 10500.0

    def test_03_delete_without_reason_400(self):
        # Create a throwaway invoice
        t = requests.post(f"{API}/trips", headers=JSON_HEADERS, json={
            "customer_id": self.state["cid"], "date": "2026-01-08",
            "vehicle_number": "TS09TMP1", "tons": 5, "freight_mode": "fixed",
            "fixed_amount": 5000, "expenses": BASE_EXPENSES,
        }).json()
        inv = requests.post(f"{API}/invoices", headers=JSON_HEADERS, json={
            "customer_id": self.state["cid"], "invoice_date": "2026-01-08",
            "trip_ids": [t["id"]], "gst_type": "cgst_sgst", "rcm": False,
        }).json()
        r = requests.delete(f"{API}/invoices/{inv['id']}", headers=HEADERS)
        assert r.status_code == 400, r.text
        # cleanup
        r2 = requests.delete(f"{API}/invoices/{inv['id']}", headers=HEADERS,
                             params={"reason": "duplicate"})
        assert r2.status_code == 200, r2.text
        # audit log
        time.sleep(0.2)
        logs = requests.get(f"{API}/audit-logs", headers=HEADERS,
                            params={"module": "invoice", "action": "delete",
                                    "entity_id": inv["id"]}).json()
        assert len(logs) >= 1
        assert logs[0]["reason"] == "duplicate"
        # cleanup child trip
        requests.delete(f"{API}/trips/{t['id']}?reason=cleanup", headers=HEADERS)


# ==================== Supplier Vehicle + Profit ====================
class TestSupplierVehicle:
    state = {}

    @classmethod
    def setup_class(cls):
        r = requests.post(f"{API}/customers", headers=JSON_HEADERS,
                          json={"name": "TEST_iter6_sup_cust"})
        cls.state["cid"] = r.json()["id"]
        r = requests.post(f"{API}/vehicles", headers=JSON_HEADERS, json={
            "vehicle_number": "TS09SUP01", "vehicle_type": "supplier",
            "supplier_name": "ABC Transport",
            "supplier_contact_person": "Ramesh",
            "supplier_mobile": "9876543210",
            "remarks": "Test hired vehicle",
        })
        assert r.status_code == 200, r.text
        cls.state["vid"] = r.json()["id"]
        cls.state["veh_body"] = r.json()

    @classmethod
    def teardown_class(cls):
        if cls.state.get("tid"):
            requests.delete(f"{API}/trips/{cls.state['tid']}?reason=cleanup", headers=HEADERS)
        if cls.state.get("vid"):
            requests.delete(f"{API}/vehicles/{cls.state['vid']}", headers=HEADERS)
        if cls.state.get("cid"):
            requests.delete(f"{API}/customers/{cls.state['cid']}", headers=HEADERS)

    def test_01_vehicle_supplier_fields_saved(self):
        v = self.state["veh_body"]
        assert v["vehicle_type"] == "supplier"
        assert v["supplier_name"] == "ABC Transport"
        assert v["supplier_contact_person"] == "Ramesh"
        assert v["supplier_mobile"] == "9876543210"
        assert v["remarks"] == "Test hired vehicle"
        # GET verifies persistence
        r = requests.get(f"{API}/vehicles", headers=HEADERS)
        vehicle = next(x for x in r.json() if x["id"] == self.state["vid"])
        assert vehicle["supplier_name"] == "ABC Transport"

    def test_02_trip_supplier_profit(self):
        r = requests.post(f"{API}/trips", headers=JSON_HEADERS, json={
            "customer_id": self.state["cid"], "date": "2026-01-10",
            "vehicle_number": "TS09SUP01", "tons": 25,
            "freight_mode": "fixed", "fixed_amount": 25000,
            "supplier_freight": 18000,
            "expenses": BASE_EXPENSES,
        })
        assert r.status_code == 200, r.text
        t = r.json()
        self.state["tid"] = t["id"]
        assert t["vehicle_type"] == "supplier", t
        assert t["supplier_name"] == "ABC Transport", t
        assert t["freight_amount"] == 25000
        assert t["total_expense"] == 18000
        assert t["profit"] == 7000


# ==================== Trip diesel recovery + shortage + cash advance ====================
class TestTripExpensesRecoveryShortage:
    state = {}

    @classmethod
    def setup_class(cls):
        r = requests.post(f"{API}/customers", headers=JSON_HEADERS,
                          json={"name": "TEST_iter6_exp_cust"})
        cls.state["cid"] = r.json()["id"]

    @classmethod
    def teardown_class(cls):
        for k in ("tid1", "tid2", "tid3"):
            if cls.state.get(k):
                requests.delete(f"{API}/trips/{cls.state[k]}?reason=cleanup", headers=HEADERS)
        if cls.state.get("cid"):
            requests.delete(f"{API}/customers/{cls.state['cid']}", headers=HEADERS)

    def test_01_diesel_recovery(self):
        # diesel 8000, recovery qty*rate = 5000 → own_expense_net = 3000, profit = 25000-3000 = 22000
        r = requests.post(f"{API}/trips", headers=JSON_HEADERS, json={
            "customer_id": self.state["cid"], "date": "2026-01-10",
            "vehicle_number": "TS09EXP01", "tons": 10,
            "freight_mode": "fixed", "fixed_amount": 25000,
            "expenses": {**BASE_EXPENSES, "diesel": 8000,
                         "diesel_from_customer_qty": 50,
                         "diesel_from_customer_rate": 100},
        })
        assert r.status_code == 200, r.text
        t = r.json()
        self.state["tid1"] = t["id"]
        assert t["expenses"]["diesel_from_customer_amount"] == 5000
        assert t["total_expense"] == 3000
        assert t["profit"] == 22000

    def test_02_shortage_reduces_profit(self):
        # freight 25000, shortage 500 → profit = 25000-500-0 = 24500
        r = requests.post(f"{API}/trips", headers=JSON_HEADERS, json={
            "customer_id": self.state["cid"], "date": "2026-01-11",
            "vehicle_number": "TS09EXP02", "tons": 10,
            "freight_mode": "fixed", "fixed_amount": 25000,
            "expenses": {**BASE_EXPENSES, "shortage_amount": 500},
        })
        assert r.status_code == 200, r.text
        t = r.json()
        self.state["tid2"] = t["id"]
        assert t["profit"] == 24500
        assert t["total_expense"] == 0

    def test_03_cash_advance_not_in_profit(self):
        # cash_advance=10000 must not affect profit; net_settlement = profit - 10000
        r = requests.post(f"{API}/trips", headers=JSON_HEADERS, json={
            "customer_id": self.state["cid"], "date": "2026-01-12",
            "vehicle_number": "TS09EXP03", "tons": 10,
            "freight_mode": "fixed", "fixed_amount": 20000,
            "expenses": {**BASE_EXPENSES, "cash_advance_received": 10000},
        })
        assert r.status_code == 200, r.text
        t = r.json()
        self.state["tid3"] = t["id"]
        assert t["profit"] == 20000
        assert t["net_settlement"] == 10000


# ==================== New Trip optional fields + LR/Invoice PDF ====================
class TestNewTripOptionalFieldsAndPDF:
    state = {}

    @classmethod
    def setup_class(cls):
        # ensure company set
        requests.put(f"{API}/company", headers=JSON_HEADERS, json={
            "name": "TEST Iter6 Co", "state": "Telangana",
            "gstin": "36AAAAA0000A1Z5", "pincode": "500032",
        })
        r = requests.post(f"{API}/customers", headers=JSON_HEADERS,
                          json={"name": "TEST_iter6_lr_cust", "state": "Telangana",
                                "gstin": "36BBBBB0000B1Z5"})
        cls.state["cid"] = r.json()["id"]
        r = requests.post(f"{API}/trips", headers=JSON_HEADERS, json={
            "customer_id": cls.state["cid"], "date": "2026-01-10",
            "vehicle_number": "TS09NEW01", "tons": 15,
            "from_location": "Hyderabad", "to_location": "Warangal",
            "freight_mode": "fixed", "fixed_amount": 20000,
            "driver_name": "Ramu", "driver_mobile": "9999",
            "customer_invoice_no": "CUST-101",
            "waybill_no": "WB-9",
            "invoice_value": 125000,
            "customer_purchased_at": "HPCL",
            "load_details": "Bitumen VG 30",
            "expenses": BASE_EXPENSES,
        })
        assert r.status_code == 200, r.text
        cls.state["tid"] = r.json()["id"]
        assert r.json()["customer_invoice_no"] == "CUST-101"
        assert r.json()["waybill_no"] == "WB-9"
        assert r.json()["invoice_value"] == 125000
        assert r.json()["customer_purchased_at"] == "HPCL"

    @classmethod
    def teardown_class(cls):
        if cls.state.get("iid"):
            requests.delete(f"{API}/invoices/{cls.state['iid']}?reason=cleanup", headers=HEADERS)
        if cls.state.get("tid"):
            requests.delete(f"{API}/trips/{cls.state['tid']}?reason=cleanup", headers=HEADERS)
        if cls.state.get("cid"):
            requests.delete(f"{API}/customers/{cls.state['cid']}", headers=HEADERS)

    def test_01_lr_pdf_no_telugu(self):
        r = requests.get(f"{API}/trips/{self.state['tid']}/lr", headers=HEADERS)
        assert r.status_code == 200, r.text
        assert r.headers.get("content-type", "").startswith("application/pdf")
        body = r.content
        assert body[:5] == b"%PDF-"
        assert len(body) > 3000
        # Telugu Unicode block (U+0C00 - U+0C7F) UTF-8 prefix bytes are 0xE0 0xB0 or 0xE0 0xB1
        # But since PDF stores text in encoded streams, use a simpler heuristic:
        # ensure the raw PDF bytes do not contain the Telugu UTF-8 lead pair. This is a
        # negative-only check as intended by the review request.
        assert body.count(b"\xe0\xb0") == 0, "PDF appears to contain Telugu unicode block"
        assert body.count(b"\xe0\xb1") == 0, "PDF appears to contain Telugu unicode block"

    def test_02_invoice_pdf_has_size(self):
        # Create invoice and fetch PDF
        inv = requests.post(f"{API}/invoices", headers=JSON_HEADERS, json={
            "customer_id": self.state["cid"], "invoice_date": "2026-01-15",
            "trip_ids": [self.state["tid"]], "gst_type": "cgst_sgst", "rcm": False,
        })
        assert inv.status_code == 200, inv.text
        self.state["iid"] = inv.json()["id"]
        r = requests.get(f"{API}/invoices/{self.state['iid']}/pdf", headers=HEADERS)
        assert r.status_code == 200, r.text
        body = r.content
        assert body[:5] == b"%PDF-"
        assert len(body) > 3000


# ==================== Audit log listing / filters ====================
class TestAuditLogFilters:
    def test_list_and_module_filter(self):
        r = requests.get(f"{API}/audit-logs", headers=HEADERS)
        assert r.status_code == 200, r.text
        docs = r.json()
        assert isinstance(docs, list)
        # sorted desc by timestamp
        ts = [d.get("timestamp", "") for d in docs]
        assert ts == sorted(ts, reverse=True)
        # module filter
        r = requests.get(f"{API}/audit-logs", headers=HEADERS, params={"module": "trip"})
        assert r.status_code == 200
        assert all(d["module"] == "trip" for d in r.json())


# ==================== Backward compat / regression ====================
class TestBackwardCompat:
    def test_endpoints_still_ok(self):
        for path in ["/auth/me", "/customers", "/trips", "/invoices",
                     "/drivers", "/products", "/vehicles", "/dashboard",
                     "/company", "/audit-logs"]:
            r = requests.get(f"{API}{path}", headers=HEADERS)
            assert r.status_code == 200, f"{path} -> {r.status_code}"

    def test_trip_without_new_fields_defaults(self):
        cust = requests.post(f"{API}/customers", headers=JSON_HEADERS,
                             json={"name": "TEST_iter6_bc_cust"}).json()
        r = requests.post(f"{API}/trips", headers=JSON_HEADERS, json={
            "customer_id": cust["id"], "date": "2026-01-20",
            "vehicle_number": "TS09BC01", "tons": 10,
            "freight_mode": "fixed", "fixed_amount": 10000,
            "expenses": BASE_EXPENSES,
        })
        assert r.status_code == 200, r.text
        t = r.json()
        assert t["vehicle_type"] == "own"
        assert t["supplier_freight"] == 0
        assert t["profit"] == 10000
        assert t["total_expense"] == 0
        # cleanup
        requests.delete(f"{API}/trips/{t['id']}?reason=cleanup", headers=HEADERS)
        requests.delete(f"{API}/customers/{cust['id']}", headers=HEADERS)
