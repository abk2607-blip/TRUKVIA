"""Iteration 2: Drivers CRUD+stats, Trip import (template/CSV/XLSX),
Invoice share token + public PDF, Dashboard receivables enrichment.
Plus a light regression on core endpoints."""
import io
import os
import pytest
import requests
import pandas as pd

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://trip-billing-pro-1.preview.emergentagent.com").rstrip("/")
TOKEN = os.environ["DEMO_TOKEN_VALUE"]
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
JSON_HEADERS = {**HEADERS, "Content-Type": "application/json"}
API = f"{BASE_URL}/api"


# ---------- Drivers CRUD + stats ----------
class TestDrivers:
    state = {}

    def test_01_create_driver(self):
        payload = {"name": "TEST_Driver_A", "phone": "9000000001", "license_number": "LIC-A-01"}
        r = requests.post(f"{API}/drivers", headers=JSON_HEADERS, json=payload)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["name"] == "TEST_Driver_A"
        assert d["phone"] == "9000000001"
        assert d["license_number"] == "LIC-A-01"
        assert "id" in d and "_id" not in d
        self.__class__.state["did"] = d["id"]

    def test_02_list_drivers_has_stats_zero(self):
        r = requests.get(f"{API}/drivers", headers=HEADERS)
        assert r.status_code == 200
        drivers = r.json()
        did = self.state["did"]
        d = next((x for x in drivers if x["id"] == did), None)
        assert d is not None
        assert "stats" in d
        s = d["stats"]
        for k in ("trips", "tons", "batta", "freight"):
            assert k in s, f"stats missing {k}"
            assert s[k] == 0

    def test_03_driver_stats_aggregation(self):
        # Create a customer
        r = requests.post(f"{API}/customers", headers=JSON_HEADERS,
                          json={"name": "TEST_DriverCust", "phone": "8888"})
        assert r.status_code == 200
        cid = r.json()["id"]
        self.__class__.state["cid"] = cid

        did = self.state["did"]
        # Two trips assigned to this driver
        trip1 = {
            "customer_id": cid, "date": "2026-01-15", "vehicle_number": "AP16TA0001",
            "driver_id": did, "driver_name": "TEST_Driver_A", "tons": 20,
            "freight_mode": "per_ton", "rate_per_ton": 1000,
            "expenses": {"diesel": 3000, "toll": 200, "batta": 500, "repair": 0, "other": 0},
        }
        trip2 = {
            "customer_id": cid, "date": "2026-01-16", "vehicle_number": "AP16TA0002",
            "driver_id": did, "driver_name": "TEST_Driver_A", "tons": 15,
            "freight_mode": "fixed", "fixed_amount": 30000,
            "expenses": {"diesel": 2500, "toll": 100, "batta": 700, "repair": 0, "other": 0},
        }
        r1 = requests.post(f"{API}/trips", headers=JSON_HEADERS, json=trip1)
        r2 = requests.post(f"{API}/trips", headers=JSON_HEADERS, json=trip2)
        assert r1.status_code == 200 and r2.status_code == 200
        self.__class__.state["trip_ids"] = [r1.json()["id"], r2.json()["id"]]

        r = requests.get(f"{API}/drivers", headers=HEADERS)
        d = next(x for x in r.json() if x["id"] == did)
        assert d["stats"]["trips"] == 2
        assert d["stats"]["batta"] == 1200.0  # 500 + 700
        assert d["stats"]["tons"] == 35.0
        assert d["stats"]["freight"] == 50000.0  # 20000 + 30000

    def test_04_update_driver(self):
        did = self.state["did"]
        payload = {"name": "TEST_Driver_A_Upd", "phone": "9000000099", "license_number": "LIC-A-99"}
        r = requests.put(f"{API}/drivers/{did}", headers=JSON_HEADERS, json=payload)
        assert r.status_code == 200
        assert r.json()["name"] == "TEST_Driver_A_Upd"
        r = requests.get(f"{API}/drivers", headers=HEADERS)
        d = next(x for x in r.json() if x["id"] == did)
        assert d["name"] == "TEST_Driver_A_Upd"
        assert d["license_number"] == "LIC-A-99"

    def test_05_delete_driver(self):
        did = self.state["did"]
        r = requests.delete(f"{API}/drivers/{did}", headers=HEADERS)
        assert r.status_code == 200
        r = requests.get(f"{API}/drivers", headers=HEADERS)
        assert not any(x["id"] == did for x in r.json())

    def test_99_cleanup(self):
        # Cleanup trips + customer created here
        for tid in self.state.get("trip_ids", []):
            requests.delete(f"{API}/trips/{tid}", headers=HEADERS)
        cid = self.state.get("cid")
        if cid:
            requests.delete(f"{API}/customers/{cid}", headers=HEADERS)


# ---------- Trip Import: template, CSV, XLSX ----------
class TestTripImport:
    state = {}

    def test_01_import_template(self):
        r = requests.get(f"{API}/trips/import/template", headers=HEADERS)
        assert r.status_code == 200
        ctype = r.headers.get("content-type", "")
        assert "spreadsheetml.sheet" in ctype, ctype
        assert r.content[:2] == b"PK", "xlsx should start with PK zip signature"
        assert len(r.content) > 3000, f"content-length={len(r.content)}"

    def _make_csv(self):
        rows = [
            # header
            ",".join([
                "date","customer_name","vehicle_number","driver_name","load_details",
                "tons","from_location","to_location","freight_mode","rate_per_ton",
                "fixed_amount","diesel","toll","batta","repair","other","notes",
            ]),
            # valid per_ton
            "2026-02-01,ImportCorp,ts01ab0001,DriverX,Bitumen VG 40,20,Chennai,Hyderabad,per_ton,1000,0,3000,200,400,0,0,imp1",
            # valid fixed
            "2026-02-02,ImportCorp,ts01ab0002,DriverY,Bitumen VG 40,10,Chennai,Bangalore,fixed,0,45000,2500,100,600,0,0,imp2",
            # invalid customer
            "2026-02-03,Nonexistent Co,ts01ab0003,DriverZ,Bitumen VG 40,5,X,Y,per_ton,1000,0,0,0,0,0,0,badrow",
        ]
        return ("\n".join(rows)).encode("utf-8")

    def test_02_setup_customer(self):
        # Ensure ImportCorp exists (delete any leftover first)
        existing = requests.get(f"{API}/customers", headers=HEADERS).json()
        for c in existing:
            if c["name"].lower() == "importcorp":
                requests.delete(f"{API}/customers/{c['id']}", headers=HEADERS)
        r = requests.post(f"{API}/customers", headers=JSON_HEADERS,
                          json={"name": "ImportCorp", "phone": "7777777777"})
        assert r.status_code == 200
        self.__class__.state["cid"] = r.json()["id"]

    def test_03_import_csv(self):
        csv_bytes = self._make_csv()
        files = {"file": ("trips.csv", csv_bytes, "text/csv")}
        r = requests.post(f"{API}/trips/import", headers=HEADERS, files=files)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["inserted"] == 2, data
        assert data["total_rows"] == 3, data
        assert len(data["errors"]) == 1
        err_msg = data["errors"][0]["error"].lower()
        assert "customer" in err_msg and ("not found" in err_msg or "nonexistent" in err_msg)

        # Verify trips exist with correct computed values
        cid = self.state["cid"]
        trips = requests.get(f"{API}/trips", headers=HEADERS, params={"customer_id": cid}).json()
        # Find one per_ton (tons=20 rate=1000) and one fixed (45000)
        per_ton = [t for t in trips if t.get("freight_mode") == "per_ton" and t.get("tons") == 20]
        fixed = [t for t in trips if t.get("freight_mode") == "fixed" and t.get("fixed_amount") == 45000]
        assert per_ton, f"per_ton trip not found: {trips}"
        assert fixed, f"fixed trip not found: {trips}"
        assert per_ton[0]["freight_amount"] == 20000.0
        # per_ton: expenses diesel=3000+toll=200+batta=400 = 3600 -> profit = 16400
        assert per_ton[0]["total_expense"] == 3600.0
        assert per_ton[0]["profit"] == 16400.0
        assert fixed[0]["freight_amount"] == 45000.0
        # fixed: 2500+100+600 = 3200 -> profit 41800
        assert fixed[0]["profit"] == 41800.0
        self.__class__.state["csv_trip_ids"] = [t["id"] for t in per_ton + fixed]

    def test_04_import_xlsx(self):
        # Build an xlsx with same content (only valid rows to avoid dup checks)
        df = pd.DataFrame([
            {"date": "2026-02-05", "customer_name": "ImportCorp",
             "vehicle_number": "ts02ab0001", "driver_name": "XL_A",
             "load_details": "Bitumen VG 40", "tons": 20, "from_location": "C",
             "to_location": "H", "freight_mode": "per_ton", "rate_per_ton": 1000,
             "fixed_amount": 0, "diesel": 3000, "toll": 200, "batta": 400,
             "repair": 0, "other": 0, "notes": "xlsx1"},
            {"date": "2026-02-06", "customer_name": "ImportCorp",
             "vehicle_number": "ts02ab0002", "driver_name": "XL_B",
             "load_details": "Bitumen VG 40", "tons": 10, "from_location": "C",
             "to_location": "B", "freight_mode": "fixed", "rate_per_ton": 0,
             "fixed_amount": 45000, "diesel": 2500, "toll": 100, "batta": 600,
             "repair": 0, "other": 0, "notes": "xlsx2"},
            {"date": "2026-02-07", "customer_name": "Nonexistent Co",
             "vehicle_number": "ts02ab0003", "driver_name": "XL_C",
             "load_details": "Bitumen VG 40", "tons": 5, "from_location": "X",
             "to_location": "Y", "freight_mode": "per_ton", "rate_per_ton": 1000,
             "fixed_amount": 0, "diesel": 0, "toll": 0, "batta": 0,
             "repair": 0, "other": 0, "notes": "badxlsx"},
        ])
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as w:
            df.to_excel(w, index=False, sheet_name="Trips")
        buf.seek(0)
        files = {"file": ("trips.xlsx", buf.getvalue(),
                          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        r = requests.post(f"{API}/trips/import", headers=HEADERS, files=files)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["inserted"] == 2, data
        assert data["total_rows"] == 3
        assert len(data["errors"]) == 1

    def test_99_cleanup(self):
        cid = self.state.get("cid")
        if not cid:
            return
        trips = requests.get(f"{API}/trips", headers=HEADERS, params={"customer_id": cid}).json()
        for t in trips:
            if t.get("status") == "pending":
                requests.delete(f"{API}/trips/{t['id']}", headers=HEADERS)
        requests.delete(f"{API}/customers/{cid}", headers=HEADERS)


# ---------- Invoice Share + Public PDF ----------
class TestInvoiceShare:
    state = {}

    def test_01_setup(self):
        # Create customer with phone
        r = requests.post(f"{API}/customers", headers=JSON_HEADERS,
                          json={"name": "TEST_ShareCust", "phone": "9123456789"})
        assert r.status_code == 200
        cid = r.json()["id"]
        # Create trip
        r = requests.post(f"{API}/trips", headers=JSON_HEADERS, json={
            "customer_id": cid, "date": "2026-01-20", "vehicle_number": "SH01",
            "tons": 10, "freight_mode": "per_ton", "rate_per_ton": 1000,
            "expenses": {"diesel": 0, "toll": 0, "batta": 0, "repair": 0, "other": 0},
        })
        assert r.status_code == 200
        tid = r.json()["id"]
        # Create invoice
        r = requests.post(f"{API}/invoices", headers=JSON_HEADERS, json={
            "customer_id": cid, "trip_ids": [tid],
            "gst_type": "cgst_sgst", "rcm": True,
        })
        assert r.status_code == 200, r.text
        iid = r.json()["id"]
        self.__class__.state.update({"cid": cid, "tid": tid, "iid": iid})

    def test_02_share_token_creation(self):
        iid = self.state["iid"]
        r = requests.post(f"{API}/invoices/{iid}/share", headers=HEADERS)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "share_token" in d
        assert isinstance(d["share_token"], str)
        assert len(d["share_token"]) > 8
        self.__class__.state["token"] = d["share_token"]

    def test_03_share_token_idempotent(self):
        iid = self.state["iid"]
        r = requests.post(f"{API}/invoices/{iid}/share", headers=HEADERS)
        assert r.status_code == 200
        assert r.json()["share_token"] == self.state["token"]

    def test_04_public_pdf_no_auth(self):
        token = self.state["token"]
        # Use fresh session with NO auth
        s = requests.Session()
        r = s.get(f"{API}/public/invoice/{token}/pdf")
        assert r.status_code == 200, r.text
        assert r.headers.get("content-type", "").startswith("application/pdf")
        assert r.content[:5] == b"%PDF-"
        assert len(r.content) > 1000

    def test_05_public_pdf_wrong_token(self):
        s = requests.Session()
        r = s.get(f"{API}/public/invoice/wrong-token-xyz/pdf")
        assert r.status_code == 404

    def test_99_cleanup(self):
        iid = self.state.get("iid")
        cid = self.state.get("cid")
        if iid:
            requests.delete(f"{API}/invoices/{iid}", headers=HEADERS)
        tid = self.state.get("tid")
        if tid:
            requests.delete(f"{API}/trips/{tid}", headers=HEADERS)
        if cid:
            requests.delete(f"{API}/customers/{cid}", headers=HEADERS)


# ---------- Dashboard receivables enrichment ----------
class TestDashboardReceivables:
    state = {}

    def test_01_setup_unpaid_invoice(self):
        r = requests.post(f"{API}/customers", headers=JSON_HEADERS,
                          json={"name": "TEST_RecvCust", "phone": "9998887777"})
        cid = r.json()["id"]
        r = requests.post(f"{API}/trips", headers=JSON_HEADERS, json={
            "customer_id": cid, "date": "2025-12-01", "vehicle_number": "RCV01",
            "tons": 10, "freight_mode": "per_ton", "rate_per_ton": 2000,
            "expenses": {"diesel": 0, "toll": 0, "batta": 0, "repair": 0, "other": 0},
        })
        tid = r.json()["id"]
        r = requests.post(f"{API}/invoices", headers=JSON_HEADERS, json={
            "customer_id": cid, "trip_ids": [tid], "invoice_date": "2025-12-01",
            "gst_type": "cgst_sgst", "rcm": True,
        })
        assert r.status_code == 200
        iid = r.json()["id"]
        self.__class__.state.update({"cid": cid, "tid": tid, "iid": iid})

    def test_02_dashboard_receivables_enriched(self):
        cid = self.state["cid"]
        r = requests.get(f"{API}/dashboard", headers=HEADERS)
        assert r.status_code == 200
        d = r.json()
        rec = next((x for x in d["receivables"] if x["customer_id"] == cid), None)
        assert rec is not None, "receivable entry not found"
        assert rec["customer_phone"] == "9998887777"
        assert "oldest_days" in rec
        assert isinstance(rec["oldest_days"], int)
        assert rec["oldest_days"] >= 0
        assert rec["balance"] > 0

    def test_99_cleanup(self):
        iid = self.state.get("iid")
        cid = self.state.get("cid")
        tid = self.state.get("tid")
        if iid: requests.delete(f"{API}/invoices/{iid}", headers=HEADERS)
        if tid: requests.delete(f"{API}/trips/{tid}", headers=HEADERS)
        if cid: requests.delete(f"{API}/customers/{cid}", headers=HEADERS)


# ---------- Light regression smoke ----------
class TestRegressionSmoke:
    def test_auth_me(self):
        r = requests.get(f"{API}/auth/me", headers=HEADERS)
        assert r.status_code == 200
        assert r.json()["user_id"] == "test-user-bitumen"

    def test_list_endpoints(self):
        for path in ["/customers", "/trips", "/invoices", "/drivers", "/dashboard"]:
            r = requests.get(f"{API}{path}", headers=HEADERS)
            assert r.status_code == 200, f"{path} -> {r.status_code} {r.text}"
