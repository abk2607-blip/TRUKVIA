"""Iteration 4 backend tests: Vehicles CRUD (expiry alerts), Fuel Log + summary,
GSTR-1 monthly report, E-Way Bill JSON, Dashboard expiry_alerts."""
import os
from datetime import date, timedelta
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://trip-billing-pro-1.preview.emergentagent.com").rstrip("/")
TOKEN = "test_session_bitumen_2026"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
JSON_HEADERS = {**HEADERS, "Content-Type": "application/json"}
API = f"{BASE_URL}/api"


# ==================== Vehicles CRUD + Alerts ====================
class TestVehicles:
    state = {}

    def test_01_create_vehicle_with_expiries(self):
        today = date.today()
        rc = (today + timedelta(days=120)).isoformat()          # ok/far
        fc = (today + timedelta(days=15)).isoformat()           # expiring
        ins = (today - timedelta(days=10)).isoformat()          # expired
        r = requests.post(f"{API}/vehicles", headers=JSON_HEADERS, json={
            "vehicle_number": "AP16TA9999",
            "owner_name": "Owner1",
            "rc_expiry": rc, "fc_expiry": fc, "insurance_expiry": ins,
        })
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["vehicle_number"] == "AP16TA9999"
        assert "alerts" in d
        assert d["alerts"]["rc_expiry"]["status"] == "ok"
        assert d["alerts"]["fc_expiry"]["status"] == "expiring"
        assert d["alerts"]["insurance_expiry"]["status"] == "expired"
        assert d["alerts"]["insurance_expiry"]["days"] < 0
        assert d["alerts"]["fc_expiry"]["days"] == 15
        assert d["soonest_days"] == d["alerts"]["insurance_expiry"]["days"]
        assert "id" in d and "_id" not in d
        self.__class__.state["vid"] = d["id"]
        self.__class__.state["today"] = today

    def test_02_list_vehicles_has_alerts(self):
        r = requests.get(f"{API}/vehicles", headers=HEADERS)
        assert r.status_code == 200
        v = next((x for x in r.json() if x["id"] == self.state["vid"]), None)
        assert v is not None
        assert v["alerts"]["rc_expiry"]["status"] == "ok"
        assert v["alerts"]["insurance_expiry"]["status"] == "expired"

    def test_03_update_vehicle_recomputes(self):
        today = self.state["today"]
        new_ins = (today + timedelta(days=200)).isoformat()  # now far/ok
        r = requests.put(f"{API}/vehicles/{self.state['vid']}", headers=JSON_HEADERS, json={
            "id": self.state["vid"],
            "vehicle_number": "AP16TA9999",
            "owner_name": "Owner1",
            "rc_expiry": (today + timedelta(days=120)).isoformat(),
            "fc_expiry": (today + timedelta(days=15)).isoformat(),
            "insurance_expiry": new_ins,
        })
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["alerts"]["insurance_expiry"]["status"] == "ok"
        # soonest is now the fc_expiry (15 days)
        assert d["soonest_days"] == 15

    def test_04_delete_vehicle(self):
        r = requests.delete(f"{API}/vehicles/{self.state['vid']}", headers=HEADERS)
        assert r.status_code == 200
        r = requests.get(f"{API}/vehicles", headers=HEADERS)
        assert not any(v["id"] == self.state["vid"] for v in r.json())


# ==================== Fuel Log ====================
class TestFuel:
    state = {"fids": [], "vid": None}

    @classmethod
    def setup_class(cls):
        r = requests.post(f"{API}/vehicles", headers=JSON_HEADERS, json={
            "vehicle_number": "TESTFUEL01", "owner_name": "TEST_Fuel"})
        cls.state["vid"] = r.json()["id"]

    @classmethod
    def teardown_class(cls):
        for fid in cls.state["fids"]:
            requests.delete(f"{API}/fuel/{fid}", headers=HEADERS)
        if cls.state["vid"]:
            requests.delete(f"{API}/vehicles/{cls.state['vid']}", headers=HEADERS)

    def test_01_auto_amount(self):
        r = requests.post(f"{API}/fuel", headers=JSON_HEADERS, json={
            "date": "2026-01-05", "vehicle_number": "TESTFUEL01",
            "litres": 100, "rate_per_litre": 95, "amount": 0, "odometer": 5000,
        })
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["amount"] == 9500.0
        assert d["vehicle_number"] == "TESTFUEL01"
        self.state["fids"].append(d["id"])

    def test_02_provided_amount_kept(self):
        r = requests.post(f"{API}/fuel", headers=JSON_HEADERS, json={
            "date": "2026-01-06", "vehicle_number": "TESTFUEL01",
            "litres": 100, "rate_per_litre": 95, "amount": 9450, "odometer": 5100,
        })
        assert r.status_code == 200
        d = r.json()
        assert d["amount"] == 9450.0
        self.state["fids"].append(d["id"])

    def test_03_summary_km_per_litre(self):
        # Delete previous entries and start clean for this vehicle
        for fid in self.state["fids"]:
            requests.delete(f"{API}/fuel/{fid}", headers=HEADERS)
        self.state["fids"] = []
        vno = "TESTFUEL02"
        # 3 fills: odo 10000/10500/11200, litres 40/60/80
        for dt, odo, lit in [("2026-02-01", 10000, 40), ("2026-02-05", 10500, 60), ("2026-02-10", 11200, 80)]:
            r = requests.post(f"{API}/fuel", headers=JSON_HEADERS, json={
                "date": dt, "vehicle_number": vno,
                "litres": lit, "rate_per_litre": 100, "odometer": odo,
            })
            assert r.status_code == 200
            self.state["fids"].append(r.json()["id"])

        # single-entry vehicle
        r = requests.post(f"{API}/fuel", headers=JSON_HEADERS, json={
            "date": "2026-02-11", "vehicle_number": "TESTFUEL03",
            "litres": 50, "rate_per_litre": 100, "odometer": 8000,
        })
        assert r.status_code == 200
        self.state["fids"].append(r.json()["id"])

        r = requests.get(f"{API}/fuel/summary", headers=HEADERS)
        assert r.status_code == 200
        by_v = {x["vehicle_number"]: x for x in r.json()["by_vehicle"]}
        s = by_v.get(vno)
        assert s is not None
        assert s["entries"] == 3
        assert s["litres"] == 180.0
        assert s["km_run"] == 1200.0
        # 1200/180 = 6.666... → 6.67
        assert s["km_per_litre"] == 6.67, s

        s1 = by_v.get("TESTFUEL03")
        assert s1["entries"] == 1
        assert s1["km_run"] == 0.0
        assert s1["km_per_litre"] == 0.0


# ==================== GSTR-1 ====================
class TestGSTR1:
    state = {"cids": [], "tids": [], "iids": []}

    @classmethod
    def setup_class(cls):
        # Ensure company has some state (Andhra Pradesh)
        requests.put(f"{API}/company", headers=JSON_HEADERS, json={
            "name": "TEST Co", "state": "Andhra Pradesh", "gstin": "37AAAAA0000A1Z5",
        })

        # B2B customer (with gstin) in Andhra Pradesh
        r = requests.post(f"{API}/customers", headers=JSON_HEADERS, json={
            "name": "TEST_G_B2B", "gstin": "37BBBBB1111B1Z1", "state": "Andhra Pradesh"})
        b2b_cid = r.json()["id"]; cls.state["cids"].append(b2b_cid)
        # B2C customer (no gstin) in Andhra Pradesh
        r = requests.post(f"{API}/customers", headers=JSON_HEADERS, json={
            "name": "TEST_G_B2C_AP", "state": "Andhra Pradesh"})
        b2c1_cid = r.json()["id"]; cls.state["cids"].append(b2c1_cid)
        # B2C customer (no gstin) in Karnataka → igst
        r = requests.post(f"{API}/customers", headers=JSON_HEADERS, json={
            "name": "TEST_G_B2C_KA", "state": "Karnataka"})
        b2c2_cid = r.json()["id"]; cls.state["cids"].append(b2c2_cid)

        def mk_trip(cid, dt, tons=10, rate=1000):
            r = requests.post(f"{API}/trips", headers=JSON_HEADERS, json={
                "customer_id": cid, "date": dt, "vehicle_number": "GST01",
                "tons": tons, "freight_mode": "per_ton", "rate_per_ton": rate,
                "expenses": {"diesel": 0, "toll": 0, "batta": 0, "repair": 0, "other": 0},
            })
            assert r.status_code == 200
            tid = r.json()["id"]
            cls.state["tids"].append(tid)
            return tid

        # Use target month = 2026-05 (well in the future to avoid mixing)
        t1 = mk_trip(b2b_cid, "2026-05-03", tons=10, rate=1000)   # 10000
        t2 = mk_trip(b2c1_cid, "2026-05-08", tons=20, rate=1000)  # 20000
        t3 = mk_trip(b2c2_cid, "2026-05-15", tons=15, rate=1000)  # 15000

        def mk_inv(cid, tid, dt, gst_type):
            r = requests.post(f"{API}/invoices", headers=JSON_HEADERS, json={
                "customer_id": cid, "trip_ids": [tid],
                "invoice_date": dt, "gst_type": gst_type, "rcm": False,
            })
            assert r.status_code == 200, r.text
            iid = r.json()["id"]; cls.state["iids"].append(iid)
            return r.json()

        i1 = mk_inv(b2b_cid, t1, "2026-05-10", "cgst_sgst")  # AP intrastate → CGST+SGST
        i2 = mk_inv(b2c1_cid, t2, "2026-05-11", "cgst_sgst") # AP intrastate → CGST+SGST
        i3 = mk_inv(b2c2_cid, t3, "2026-05-16", "igst")      # KA interstate → IGST
        cls.state["invs"] = [i1, i2, i3]

        # Off-month invoice to verify exclusion
        t4 = mk_trip(b2c1_cid, "2025-11-01", tons=5, rate=1000)  # 5000
        i4 = mk_inv(b2c1_cid, t4, "2025-11-15", "cgst_sgst")
        cls.state["off_iid"] = i4["id"]

    @classmethod
    def teardown_class(cls):
        for iid in cls.state["iids"]:
            requests.delete(f"{API}/invoices/{iid}", headers=HEADERS)
        off = cls.state.get("off_iid")
        if off:
            requests.delete(f"{API}/invoices/{off}", headers=HEADERS)
        for tid in cls.state["tids"]:
            requests.delete(f"{API}/trips/{tid}", headers=HEADERS)
        for cid in cls.state["cids"]:
            requests.delete(f"{API}/customers/{cid}", headers=HEADERS)

    def test_01_gstr1_totals_and_split(self):
        r = requests.get(f"{API}/reports/gstr1", headers=HEADERS,
                         params={"month": "2026-05"})
        assert r.status_code == 200, r.text
        d = r.json()
        # our invoice numbers
        our_inv_nos = {i["invoice_number"] for i in self.state["invs"]}
        b2b = [x for x in d["b2b"] if x["invoice_number"] in our_inv_nos]
        b2c = [x for x in d["b2c"] if x["invoice_number"] in our_inv_nos]
        assert len(b2b) == 1, b2b
        assert len(b2c) == 2, b2c
        # B2B has gstin
        assert b2b[0]["gstin"] == "37BBBBB1111B1Z1"
        assert b2b[0]["state_code"] == "37"
        # taxable values match subtotals
        b2b_tax = sum(x["taxable_value"] for x in b2b)
        b2c_tax = sum(x["taxable_value"] for x in b2c)
        assert b2b_tax + b2c_tax == 45000.0

        # by_state check: state_code 37 aggregated (2 invoices: b2b_ap + b2c_ap = 30000)
        state_37 = next((s for s in d["by_state"] if s["state_code"] == "37"), None)
        state_29 = next((s for s in d["by_state"] if s["state_code"] == "29"), None)
        assert state_37 is not None
        assert state_29 is not None
        # 37 = 10000+20000; CGST 5% split = 2.5% each = 250+500 = 750
        # NOTE: by_state aggregates ALL invoices in month; check >= our contributions
        assert state_37["taxable"] >= 30000.0
        assert state_29["taxable"] >= 15000.0
        # igst on KA invoice: 15000*5% = 750
        # our KA contribution
        our_ka = next(x for x in b2c if x["state_code"] == "29")
        assert our_ka["igst"] == 750.0
        assert our_ka["cgst"] == 0.0

    def test_02_gstr1_excludes_out_of_month(self):
        # Query 2026-02: off_iid was 2025-11-15 → not present
        r = requests.get(f"{API}/reports/gstr1", headers=HEADERS,
                         params={"month": "2026-02"})
        assert r.status_code == 200
        d = r.json()
        all_nos = {x["invoice_number"] for x in (d["b2b"] + d["b2c"])}
        # Fetch invoice number for off_iid
        r2 = requests.get(f"{API}/invoices/{self.state['off_iid']}", headers=HEADERS)
        off_no = r2.json()["invoice_number"]
        assert off_no not in all_nos

    def test_03_gstr1_invalid_month_400(self):
        r = requests.get(f"{API}/reports/gstr1", headers=HEADERS,
                         params={"month": "not-a-date"})
        assert r.status_code == 400


# ==================== E-Way Bill JSON ====================
class TestEwayBill:
    state = {}

    @classmethod
    def setup_class(cls):
        # Set company state to AP
        requests.put(f"{API}/company", headers=JSON_HEADERS, json={
            "name": "TEST Co", "state": "Andhra Pradesh", "gstin": "37AAAAA0000A1Z5",
            "address": "Test Address, Vijayawada",
        })
        # Customer in AP
        r = requests.post(f"{API}/customers", headers=JSON_HEADERS, json={
            "name": "TEST_EW_AP", "state": "Andhra Pradesh", "gstin": "37CCCCC2222C1Z2"})
        cls.state["cid"] = r.json()["id"]
        # Trip
        r = requests.post(f"{API}/trips", headers=JSON_HEADERS, json={
            "customer_id": cls.state["cid"], "date": "2026-06-01",
            "vehicle_number": "AP16TA9999", "tons": 20,
            "from_location": "Vijayawada", "to_location": "Guntur",
            "freight_mode": "fixed", "fixed_amount": 25000,
            "round_trip_kms": 0, "rate_per_km_per_ton": 0,
            "load_details": "Bitumen VG 30",
            "expenses": {"diesel": 0, "toll": 0, "batta": 0, "repair": 0, "other": 0},
        })
        assert r.status_code == 200, r.text
        cls.state["tid"] = r.json()["id"]
        assert r.json()["freight_amount"] == 25000.0

    @classmethod
    def teardown_class(cls):
        tid = cls.state.get("tid")
        if tid: requests.delete(f"{API}/trips/{tid}", headers=HEADERS)
        cid = cls.state.get("cid")
        if cid: requests.delete(f"{API}/customers/{cid}", headers=HEADERS)

    def test_01_intrastate_ap(self):
        r = requests.get(f"{API}/trips/{self.state['tid']}/ewaybill", headers=HEADERS)
        assert r.status_code == 200, r.text
        d = r.json()
        bl = d["billLists"][0]
        assert bl["fromStateCode"] == 37
        assert bl["toStateCode"] == 37
        assert bl["vehicleNo"] == "AP16TA9999"
        item = bl["itemList"][0]
        assert item["cgstRate"] == 2.5
        assert item["sgstRate"] == 2.5
        assert item["igstRate"] == 0
        assert item["quantity"] == 20
        assert item["taxableAmount"] == 25000
        assert "productName" in item
        # doc No present (falls back to trip id)
        assert bl.get("docNo")

    def test_02_interstate_karnataka(self):
        # Change customer state to Karnataka
        requests.put(f"{API}/customers/{self.state['cid']}", headers=JSON_HEADERS, json={
            "id": self.state["cid"], "name": "TEST_EW_AP",
            "state": "Karnataka", "gstin": "37CCCCC2222C1Z2",
        })
        r = requests.get(f"{API}/trips/{self.state['tid']}/ewaybill", headers=HEADERS)
        assert r.status_code == 200
        bl = r.json()["billLists"][0]
        assert bl["fromStateCode"] == 37
        assert bl["toStateCode"] == 29
        item = bl["itemList"][0]
        assert item["cgstRate"] == 0
        assert item["sgstRate"] == 0
        assert item["igstRate"] == 5.0

    def test_03_unknown_state(self):
        requests.put(f"{API}/customers/{self.state['cid']}", headers=JSON_HEADERS, json={
            "id": self.state["cid"], "name": "TEST_EW_AP",
            "state": "Foo", "gstin": "37CCCCC2222C1Z2",
        })
        r = requests.get(f"{API}/trips/{self.state['tid']}/ewaybill", headers=HEADERS)
        assert r.status_code == 200
        bl = r.json()["billLists"][0]
        assert bl["toStateCode"] == 0


# ==================== Dashboard expiry_alerts ====================
class TestDashboardExpiry:
    state = {}

    @classmethod
    def setup_class(cls):
        today = date.today()
        # 1 vehicle expired ins, 1 vehicle ok
        r = requests.post(f"{API}/vehicles", headers=JSON_HEADERS, json={
            "vehicle_number": "TESTDASH01",
            "insurance_expiry": (today - timedelta(days=5)).isoformat(),
            "rc_expiry": (today + timedelta(days=200)).isoformat(),
        })
        cls.state["v1"] = r.json()["id"]
        r = requests.post(f"{API}/vehicles", headers=JSON_HEADERS, json={
            "vehicle_number": "TESTDASH02",
            "rc_expiry": (today + timedelta(days=400)).isoformat(),
        })
        cls.state["v2"] = r.json()["id"]

    @classmethod
    def teardown_class(cls):
        for k in ("v1", "v2"):
            vid = cls.state.get(k)
            if vid: requests.delete(f"{API}/vehicles/{vid}", headers=HEADERS)

    def test_dashboard_expiry_alerts(self):
        r = requests.get(f"{API}/dashboard", headers=HEADERS)
        assert r.status_code == 200
        d = r.json()
        assert "expiry_alerts" in d
        # v1 insurance expired should be in alerts
        matches = [a for a in d["expiry_alerts"] if a.get("vehicle_number") == "TESTDASH01"]
        assert any(a["status"] == "expired" for a in matches)
        # v2 has only far-future rc, should not appear
        v2_alerts = [a for a in d["expiry_alerts"] if a.get("vehicle_number") == "TESTDASH02"]
        assert v2_alerts == [], v2_alerts


# ==================== Regression: existing endpoints ====================
class TestRegression:
    def test_auth_and_lists(self):
        for path in ["/auth/me", "/customers", "/trips", "/invoices", "/drivers",
                     "/products", "/dashboard", "/vehicles", "/fuel", "/fuel/summary"]:
            r = requests.get(f"{API}{path}", headers=HEADERS)
            assert r.status_code == 200, f"{path} -> {r.status_code}"
