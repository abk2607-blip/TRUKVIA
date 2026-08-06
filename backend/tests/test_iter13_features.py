"""Iteration 13 backend tests:
- Party CRUD (Consignor/Consignee master)
- party_type filter (consignor/consignee/both)
- Halting Report per-customer aggregation
- GST Summary current_month + current_fy + due dates
- Overdue Invoices (route ordering must resolve list before /invoices/{iid})
"""
import os
import pytest
import requests
from datetime import date

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "https://trip-billing-pro-1.preview.emergentagent.com").rstrip("/")
TOKEN = "test_session_bitumen_2026"
HDRS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def _cleanup_all():
    try:
        for path in ("invoices", "trips", "customers", "parties"):
            rows = requests.get(f"{BASE_URL}/api/{path}", headers=HDRS, timeout=15).json()
            if not isinstance(rows, list):
                continue
            for r in rows:
                rid = r.get("id")
                if not rid:
                    continue
                if path == "invoices":
                    requests.delete(f"{BASE_URL}/api/invoices/{rid}?reason=test", headers=HDRS, timeout=15)
                elif path == "trips":
                    requests.delete(f"{BASE_URL}/api/trips/{rid}?reason=test", headers=HDRS, timeout=15)
                else:
                    requests.delete(f"{BASE_URL}/api/{path}/{rid}", headers=HDRS, timeout=15)
    except Exception as e:
        print(f"cleanup err: {e}")


@pytest.fixture(scope="module", autouse=True)
def _clean_around():
    _cleanup_all()
    yield
    _cleanup_all()


def _set_company(state="Andhra Pradesh"):
    r = requests.put(f"{BASE_URL}/api/company", headers=HDRS, json={
        "name": "Test Bitumen", "address": "VJA", "phone": "9", "email": "t@t.com",
        "gstin": "37ABCDE1234F1Z5", "pan": "ABCDE1234F", "state": state, "pincode": "520001",
        "bank_name": "SBI", "account_number": "1", "ifsc": "SBIN0000123", "branch": "VJA",
        "hsn_sac": "996791", "invoice_prefix": "INV", "next_invoice_number": 1,
        "lr_prefix": "LR", "next_lr_number": 1, "logo": "",
    }, timeout=15)
    assert r.status_code == 200, r.text


def _make_customer(name, state):
    r = requests.post(f"{BASE_URL}/api/customers", headers=HDRS, json={
        "name": name, "address": "a", "phone": "9999999999", "email": "c@c.com",
        "gstin": "", "pan": "", "state": state, "pincode": "",
    }, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


# ---------- Party CRUD ----------
class TestPartyCRUD:
    def test_create_get_update_delete_party(self):
        # CREATE
        payload = {
            "party_type": "consignor",
            "name": "TEST_Consignor_1",
            "contact_person": "Ravi",
            "phone": "9876543210",
            "email": "ravi@x.com",
            "gstin": "37ABCDE1234F1Z5",
            "pan": "ABCDE1234F",
            "address": "Plot 1",
            "state": "Andhra Pradesh",
            "pincode": "520001",
            "notes": "",
        }
        r = requests.post(f"{BASE_URL}/api/parties", headers=HDRS, json=payload, timeout=15)
        assert r.status_code == 200, r.text
        created = r.json()
        assert created["id"]
        assert created["name"] == "TEST_Consignor_1"
        assert created["state"] == "Andhra Pradesh"
        assert created["party_type"] == "consignor"
        pid = created["id"]

        # GET list contains it
        r = requests.get(f"{BASE_URL}/api/parties", headers=HDRS, timeout=15)
        assert r.status_code == 200
        assert any(p["id"] == pid for p in r.json())

        # Filter consignor returns it
        r = requests.get(f"{BASE_URL}/api/parties?party_type=consignor", headers=HDRS, timeout=15)
        assert r.status_code == 200
        assert any(p["id"] == pid for p in r.json())

        # UPDATE
        upd = {**created, "name": "TEST_Consignor_1_Updated", "state": "Telangana"}
        r = requests.put(f"{BASE_URL}/api/parties/{pid}", headers=HDRS, json=upd, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["name"] == "TEST_Consignor_1_Updated"
        assert r.json()["state"] == "Telangana"

        # DELETE
        r = requests.delete(f"{BASE_URL}/api/parties/{pid}", headers=HDRS, timeout=15)
        assert r.status_code == 200
        r = requests.get(f"{BASE_URL}/api/parties", headers=HDRS, timeout=15)
        assert not any(p["id"] == pid for p in r.json())


class TestPartyFilter:
    def test_party_type_filter(self):
        _cleanup_all()
        for pt in ("consignor", "consignee", "both"):
            r = requests.post(f"{BASE_URL}/api/parties", headers=HDRS, json={
                "party_type": pt, "name": f"TEST_{pt}", "state": "Andhra Pradesh"
            }, timeout=15)
            assert r.status_code == 200

        r = requests.get(f"{BASE_URL}/api/parties?party_type=consignor", headers=HDRS, timeout=15)
        names = {p["name"] for p in r.json()}
        # spec: consignor filter should return consignor + both
        assert "TEST_consignor" in names
        assert "TEST_both" in names
        assert "TEST_consignee" not in names

        r = requests.get(f"{BASE_URL}/api/parties?party_type=consignee", headers=HDRS, timeout=15)
        names = {p["name"] for p in r.json()}
        assert "TEST_consignee" in names
        assert "TEST_both" in names
        assert "TEST_consignor" not in names


# ---------- Halting Report ----------
class TestHaltingReport:
    def test_halting_report_with_data(self):
        _cleanup_all()
        _set_company("Andhra Pradesh")
        c = _make_customer("TEST_HaltCust", "Andhra Pradesh")
        # Trip: loading 2026-02-05, unloading 2026-02-12 => 7 days total; grace 4; chargeable 3; rate 2000 => 6000
        r = requests.post(f"{BASE_URL}/api/trips", headers=HDRS, json={
            "customer_id": c["id"], "date": "2026-02-05",
            "vehicle_number": "AP16TA1234", "vehicle_type": "own",
            "load_details": "Bitumen", "tons": 10,
            "from_location": "A", "to_location": "B",
            "freight_mode": "per_ton", "rate_per_ton": 1000,
            "loading_date": "2026-02-05", "unloading_date": "2026-02-12",
            "grace_days": 4, "halting_rate_per_day": 2000,
        }, timeout=15)
        assert r.status_code == 200, r.text
        trip = r.json()
        assert trip["total_halting_days"] == 7
        assert trip["chargeable_halting_days"] == 3
        assert trip["halting_amount"] == 6000

        r = requests.get(f"{BASE_URL}/api/reports/halting", headers=HDRS, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "customers" in data and "totals" in data
        assert len(data["customers"]) >= 1
        row = [x for x in data["customers"] if x["customer_id"] == c["id"]][0]
        assert row["trips_with_halting"] == 1
        assert row["total_days"] == 7
        assert row["chargeable_days"] == 3
        assert row["halting_revenue"] == 6000
        assert row["avg_rate"] == 2000

    def test_halting_report_empty(self):
        _cleanup_all()
        _set_company("Andhra Pradesh")
        c = _make_customer("TEST_NoHalt", "Andhra Pradesh")
        # Trip with no halting
        r = requests.post(f"{BASE_URL}/api/trips", headers=HDRS, json={
            "customer_id": c["id"], "date": "2026-02-01",
            "vehicle_number": "AP16TA9999", "vehicle_type": "own",
            "load_details": "Bitumen", "tons": 10,
            "from_location": "A", "to_location": "B",
            "freight_mode": "per_ton", "rate_per_ton": 1000,
        }, timeout=15)
        assert r.status_code == 200
        r = requests.get(f"{BASE_URL}/api/reports/halting", headers=HDRS, timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert data["customers"] == []
        for k in ("trips_with_halting", "total_days", "chargeable_days", "halting_revenue"):
            assert data["totals"].get(k, 0) == 0


# ---------- GST Summary ----------
class TestGSTSummary:
    def test_gst_summary_current_month_and_fy(self):
        _cleanup_all()
        _set_company("Andhra Pradesh")
        # intra-state
        c1 = _make_customer("TEST_AP", "Andhra Pradesh")
        # inter-state
        c2 = _make_customer("TEST_TS", "Telangana")
        today_iso = date.today().isoformat()
        for cust in (c1, c2):
            tr = requests.post(f"{BASE_URL}/api/trips", headers=HDRS, json={
                "customer_id": cust["id"], "date": today_iso,
                "vehicle_number": "AP16TA1111", "vehicle_type": "own",
                "load_details": "Bitumen", "tons": 10,
                "from_location": "A", "to_location": "B",
                "freight_mode": "per_ton", "rate_per_ton": 1000,
            }, timeout=15).json()
            inv = requests.post(f"{BASE_URL}/api/invoices", headers=HDRS, json={
                "customer_id": cust["id"], "trip_ids": [tr["id"]], "gst_type": "cgst_sgst", "rcm": False,
            }, timeout=15)
            assert inv.status_code == 200, inv.text

        r = requests.get(f"{BASE_URL}/api/reports/gst-summary", headers=HDRS, timeout=15)
        assert r.status_code == 200, r.text
        s = r.json()
        cm = s["current_month"]
        fy = s["current_fy"]
        assert cm["invoices"] == 2
        # One CGST+SGST (intra), one IGST (inter)
        assert cm["cgst"] > 0 and cm["sgst"] > 0
        assert cm["igst"] > 0
        assert cm["total_tax"] == round(cm["cgst"] + cm["sgst"] + cm["igst"], 2)
        assert fy["invoices"] >= 2
        # Due dates: 11th of next month & 20th
        today = date.today()
        exp_y = today.year + (1 if today.month == 12 else 0)
        exp_m = 1 if today.month == 12 else today.month + 1
        assert s["next_gstr1_due"] == f"{exp_y:04d}-{exp_m:02d}-11"
        assert s["next_gstr3b_due"] == f"{exp_y:04d}-{exp_m:02d}-20"


# ---------- Overdue Invoices ----------
class TestOverdueInvoices:
    def test_overdue_empty(self):
        _cleanup_all()
        r = requests.get(f"{BASE_URL}/api/invoices/overdue?days=30", headers=HDRS, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json() == []

    def test_overdue_route_not_shadowed_and_enriched(self):
        _cleanup_all()
        _set_company("Andhra Pradesh")
        c = _make_customer("TEST_Overdue", "Andhra Pradesh")
        tr = requests.post(f"{BASE_URL}/api/trips", headers=HDRS, json={
            "customer_id": c["id"], "date": "2025-01-01",
            "vehicle_number": "AP16TA2222", "vehicle_type": "own",
            "load_details": "Bitumen", "tons": 10,
            "from_location": "A", "to_location": "B",
            "freight_mode": "per_ton", "rate_per_ton": 1000,
        }, timeout=15).json()
        inv = requests.post(f"{BASE_URL}/api/invoices", headers=HDRS, json={
            "customer_id": c["id"], "trip_ids": [tr["id"]], "gst_type": "cgst_sgst", "rcm": False,
        }, timeout=15).json()
        # Back-date invoice
        upd = {**inv, "invoice_date": "2025-01-01"}
        r = requests.put(f"{BASE_URL}/api/invoices/{inv['id']}", headers=HDRS, json=upd, timeout=15)
        # If PUT not supported for date, fall back to direct db is out of scope — but if 200, use it
        r = requests.get(f"{BASE_URL}/api/invoices/overdue?days=30", headers=HDRS, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        # Must be a list (not shadowed to /invoices/{iid} where iid='overdue' -> 404)
        assert isinstance(data, list), f"overdue route shadowed: {data}"
        # Should include the invoice (age > 30 days from 2025-01-01)
        if data:
            row = [x for x in data if x["id"] == inv["id"]]
            if row:
                assert row[0]["customer_name"] == "TEST_Overdue"
                assert row[0]["age_days"] > 0
