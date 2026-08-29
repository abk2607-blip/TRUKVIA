"""Backend API tests for Bitumen Transport Accounting.
Uses one big class TestFullFlow for stateful CRUD/invoice flow so that pytest-xdist
loadscope keeps all dependent tests in the same worker.
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://trip-billing-pro-1.preview.emergentagent.com").rstrip("/")
TOKEN = os.environ["DEMO_TOKEN_VALUE"]
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
API = f"{BASE_URL}/api"


def _trip_payload(cid, **kw):
    base = {
        "customer_id": cid, "date": "2026-01-10", "vehicle_number": "TS09AB1234",
        "driver_name": "Ravi", "load_details": "Bitumen VG 40", "tons": 25.5,
        "from_location": "Chennai", "to_location": "Hyderabad",
        "freight_mode": "per_ton", "rate_per_ton": 1200, "fixed_amount": 0,
        "expenses": {"diesel": 5000, "toll": 500, "batta": 1000, "repair": 0, "other": 0},
        "notes": "",
    }
    base.update(kw)
    return base


# Auth tests (standalone)
class TestAuth:
    def test_me_authenticated(self):
        r = requests.get(f"{API}/auth/me", headers=HEADERS)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["user_id"] == "test-user-bitumen"
        assert data["email"] == "owner@vbklogistics.test"

    def test_me_unauthenticated(self):
        r = requests.get(f"{API}/auth/me")
        assert r.status_code == 401


# Full stateful flow: company/customers/trips/invoices/dashboard
class TestFullFlow:
    state = {}

    def test_01_company_defaults(self):
        r = requests.get(f"{API}/company", headers=HEADERS)
        assert r.status_code == 200
        d = r.json()
        assert d["name"] == ""
        assert d["hsn_sac"] == "996791"

    def test_02_company_put_and_persist(self):
        payload = {
            "name": "VBK Logistics", "address": "Hyd", "phone": "9999",
            "email": "vbk@test.com", "gstin": "36ABCDE1234F1Z5", "pan": "ABCDE1234F",
            "state": "Telangana", "bank_name": "SBI", "account_number": "123",
            "ifsc": "SBIN0001", "branch": "Hyd", "hsn_sac": "996791",
            "invoice_prefix": "VBK", "next_invoice_number": 1,
        }
        r = requests.put(f"{API}/company", headers=HEADERS, json=payload)
        assert r.status_code == 200
        assert r.json()["name"] == "VBK Logistics"
        r2 = requests.get(f"{API}/company", headers=HEADERS)
        assert r2.json()["gstin"] == "36ABCDE1234F1Z5"

    def test_03_customers_crud(self):
        payload = {"name": "TEST_Cust1", "address": "A1", "phone": "1",
                   "gstin": "G1", "pan": "P1", "state": "Telangana"}
        r = requests.post(f"{API}/customers", headers=HEADERS, json=payload)
        assert r.status_code == 200, r.text
        cust = r.json()
        assert cust["name"] == "TEST_Cust1"
        assert "_id" not in cust
        cid = cust["id"]
        self.__class__.state["cid"] = cid

        r = requests.get(f"{API}/customers", headers=HEADERS)
        assert any(c["id"] == cid for c in r.json())

        payload["name"] = "TEST_Cust1_Updated"
        r = requests.put(f"{API}/customers/{cid}", headers=HEADERS, json=payload)
        assert r.status_code == 200 and r.json()["name"] == "TEST_Cust1_Updated"

    def test_04_customer_delete_flow(self):
        r = requests.post(f"{API}/customers", headers=HEADERS, json={"name": "TEST_ToDelete"})
        cid = r.json()["id"]
        r = requests.delete(f"{API}/customers/{cid}", headers=HEADERS)
        assert r.status_code == 200
        r = requests.get(f"{API}/customers", headers=HEADERS)
        assert not any(c["id"] == cid for c in r.json())

    def test_05_trip_per_ton(self):
        cid = self.state["cid"]
        r = requests.post(f"{API}/trips", headers=HEADERS, json=_trip_payload(cid))
        assert r.status_code == 200, r.text
        t = r.json()
        assert t["freight_amount"] == 30600.0  # 25.5 * 1200
        assert t["total_expense"] == 6500.0
        assert t["profit"] == 24100.0
        assert t["status"] == "pending"
        assert "_id" not in t
        self.__class__.state["trip1"] = t["id"]

    def test_06_trip_fixed(self):
        cid = self.state["cid"]
        r = requests.post(f"{API}/trips", headers=HEADERS,
                          json=_trip_payload(cid, freight_mode="fixed", fixed_amount=45000,
                                             tons=10, rate_per_ton=0))
        assert r.status_code == 200
        assert r.json()["freight_amount"] == 45000.0
        self.__class__.state["trip2"] = r.json()["id"]

    def test_07_trip_third(self):
        cid = self.state["cid"]
        r = requests.post(f"{API}/trips", headers=HEADERS,
                          json=_trip_payload(cid, date="2026-01-12", tons=20, rate_per_ton=1000))
        assert r.status_code == 200
        assert r.json()["freight_amount"] == 20000.0
        self.__class__.state["trip3"] = r.json()["id"]

    def test_08_trip_update_recomputes(self):
        cid = self.state["cid"]
        tid = self.state["trip1"]
        r = requests.put(f"{API}/trips/{tid}", headers=HEADERS,
                         json=_trip_payload(cid, tons=30, rate_per_ton=1200))
        assert r.status_code == 200
        assert r.json()["freight_amount"] == 36000.0

    def test_09_trip_list(self):
        r = requests.get(f"{API}/trips", headers=HEADERS)
        ids = [t["id"] for t in r.json()]
        assert self.state["trip1"] in ids and self.state["trip2"] in ids

    def test_10_invoice_cgst_sgst_rcm(self):
        cid = self.state["cid"]
        trip_ids = [self.state["trip1"], self.state["trip2"], self.state["trip3"]]
        payload = {"customer_id": cid, "trip_ids": trip_ids, "gst_type": "cgst_sgst", "rcm": True}
        r = requests.post(f"{API}/invoices", headers=HEADERS, json=payload)
        assert r.status_code == 200, r.text
        inv = r.json()
        assert inv["subtotal"] == 101000.0  # 36000 + 45000 + 20000
        assert inv["cgst_amount"] == 2525.0
        assert inv["sgst_amount"] == 2525.0
        assert inv["igst_amount"] == 0.0
        assert inv["total_tax"] == 5050.0
        assert inv["total_amount"] == 101000.0  # RCM: no tax added
        assert inv["balance_due"] == 101000.0
        assert inv["invoice_number"]
        assert "_id" not in inv
        self.__class__.state["inv1"] = inv["id"]

        r = requests.get(f"{API}/trips", headers=HEADERS)
        for t in r.json():
            if t["id"] in trip_ids:
                assert t["status"] == "invoiced"
                assert t["invoice_id"] == inv["id"]

    def test_11_reinvoice_locked(self):
        cid = self.state["cid"]
        r = requests.post(f"{API}/invoices", headers=HEADERS,
                          json={"customer_id": cid, "trip_ids": [self.state["trip1"]],
                                "gst_type": "cgst_sgst", "rcm": True})
        assert r.status_code == 400

    def test_12_cannot_edit_or_delete_invoiced_trip(self):
        cid = self.state["cid"]
        tid = self.state["trip1"]
        r = requests.put(f"{API}/trips/{tid}", headers=HEADERS, json=_trip_payload(cid))
        assert r.status_code == 400
        r = requests.delete(f"{API}/trips/{tid}", headers=HEADERS)
        assert r.status_code == 400

    def test_13_payments_accumulate(self):
        iid = self.state["inv1"]
        r = requests.post(f"{API}/invoices/{iid}/payments", headers=HEADERS,
                          json={"amount": 40000, "mode": "Bank"})
        assert r.status_code == 200
        assert r.json()["amount_paid"] == 40000.0
        assert r.json()["balance_due"] == 61000.0

        r = requests.post(f"{API}/invoices/{iid}/payments", headers=HEADERS,
                          json={"amount": 10000, "mode": "Cash"})
        assert r.json()["amount_paid"] == 50000.0
        assert r.json()["balance_due"] == 51000.0

    def test_14_pdf(self):
        iid = self.state["inv1"]
        r = requests.get(f"{API}/invoices/{iid}/pdf", headers=HEADERS)
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("application/pdf")
        assert r.content[:5] == b"%PDF-"
        assert len(r.content) > 2000

    def test_15_delete_invoice_releases_trips(self):
        iid = self.state["inv1"]
        trip_ids = [self.state["trip1"], self.state["trip2"], self.state["trip3"]]
        r = requests.delete(f"{API}/invoices/{iid}", headers=HEADERS)
        assert r.status_code == 200
        r = requests.get(f"{API}/trips", headers=HEADERS)
        for t in r.json():
            if t["id"] in trip_ids:
                assert t["status"] == "pending"
                assert t.get("invoice_id") is None

    def test_16_igst_invoice_non_rcm(self):
        cid = self.state["cid"]
        r = requests.post(f"{API}/trips", headers=HEADERS,
                          json=_trip_payload(cid, tons=10, rate_per_ton=1000))
        tid = r.json()["id"]
        r = requests.post(f"{API}/invoices", headers=HEADERS,
                          json={"customer_id": cid, "trip_ids": [tid],
                                "gst_type": "igst", "rcm": False})
        assert r.status_code == 200
        inv = r.json()
        assert inv["subtotal"] == 10000.0
        assert inv["igst_amount"] == 500.0
        assert inv["cgst_amount"] == 0.0
        assert inv["sgst_amount"] == 0.0
        assert inv["total_amount"] == 10500.0
        self.__class__.state["inv2"] = inv["id"]

    def test_17_dashboard(self):
        r = requests.get(f"{API}/dashboard", headers=HEADERS)
        assert r.status_code == 200
        d = r.json()
        assert d["total_profit"] == round(d["total_revenue"] - d["total_expense"], 2)
        assert any(x["balance"] > 0 for x in d["receivables"])
