"""Iteration 8 backend tests: Supplier freight detail, supplier profit formula,
invoice auto-recalc on trip edit, Supplier P&L report, P&L supplier cost,
LR PDF 2-page split.
"""
import io
import os
import pytest
import requests

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or "https://trip-billing-pro-1.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
TOKEN = "test_session_bitumen_2026"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
JSON_HEADERS = {**HEADERS, "Content-Type": "application/json"}

BASE_EXP = {"diesel": 0, "toll": 0, "batta": 0, "repair": 0, "other": 0,
            "firewood": 0, "shortage_amount": 0, "diesel_from_customer_qty": 0,
            "diesel_from_customer_rate": 0, "diesel_from_customer_amount": 0,
            "cash_advance_received": 0}


# ------------------------- shared fixtures -------------------------

@pytest.fixture(scope="module")
def customer_id():
    r = requests.post(f"{API}/customers",
                      headers=JSON_HEADERS,
                      json={"name": "TEST_iter8_Customer", "gstin": "29ABCDE1234F1Z5",
                            "state": "Karnataka", "address": "Test", "pincode": "560001"})
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    yield cid
    try:
        requests.delete(f"{API}/customers/{cid}", headers=HEADERS,
                        params={"reason": "cleanup"})
    except Exception:
        pass


def _create_trip(customer_id, **overrides):
    body = {
        "customer_id": customer_id,
        "date": "2026-01-10",
        "vehicle_number": "TS09AB1234",
        "vehicle_type": "own",
        "tons": 20,
        "freight_mode": "per_ton",
        "rate_per_ton": 1200,
        "expenses": BASE_EXP,
    }
    body.update(overrides)
    r = requests.post(f"{API}/trips", headers=JSON_HEADERS, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _cleanup_trip(tid):
    try:
        requests.delete(f"{API}/trips/{tid}", headers=HEADERS,
                        params={"reason": "cleanup"})
    except Exception:
        pass


# ------------------------- Compute tests ---------------------------

class TestSupplierCompute:

    def test_supplier_per_ton(self, customer_id):
        t = _create_trip(customer_id,
                         vehicle_number="TS09SUP001",
                         vehicle_type="supplier",
                         supplier_name="TEST_Sup_A",
                         supplier_freight_mode="per_ton",
                         supplier_rate_per_ton=1000,
                         supplier_quantity=20,
                         supplier_advance=5000,
                         supplier_other_recoveries=500,
                         tons=20,
                         freight_mode="per_ton",
                         rate_per_ton=1200)
        try:
            assert t["supplier_freight"] == 20000, t
            assert t["supplier_net_payable"] == 14500, t   # 20000-5000-500 (no diesel/shortage/income)
            assert t["total_expense"] == 14500, t          # now equals net_payable (all deductions applied)
            assert t["freight_amount"] == 24000
            assert t["profit"] == 9500                      # 24000 - 14500
        finally:
            _cleanup_trip(t["id"])

    def test_supplier_fixed_roundtrip(self, customer_id):
        t = _create_trip(customer_id,
                         vehicle_number="TS09SUP002",
                         vehicle_type="supplier",
                         supplier_name="TEST_Sup_B",
                         supplier_freight_mode="fixed",
                         supplier_round_trip_kms=400,
                         supplier_rate_per_km_per_ton=2,
                         supplier_quantity=15,
                         supplier_advance=0,
                         tons=15,
                         freight_mode="per_ton",
                         rate_per_ton=1500)
        try:
            # 15 * 400 * 2 = 12000
            assert t["supplier_freight"] == 12000, t
            assert t["total_expense"] == 12000
            # customer freight = 15*1500 = 22500 → profit = 22500 - 12000 = 10500
            assert t["profit"] == 10500
        finally:
            _cleanup_trip(t["id"])

    def test_supplier_manual_freight_preserved(self, customer_id):
        # No rates provided (per_ton mode but rate=0) → supplier_freight preserved
        t = _create_trip(customer_id,
                         vehicle_number="TS09SUP003",
                         vehicle_type="supplier",
                         supplier_name="TEST_Sup_C",
                         supplier_freight_mode="per_ton",
                         supplier_rate_per_ton=0,
                         supplier_freight=7777,
                         supplier_advance=1000,
                         tons=10,
                         freight_mode="per_ton",
                         rate_per_ton=1000)
        try:
            assert t["supplier_freight"] == 7777, t
            assert t["total_expense"] == 6777  # 7777 - 1000 (only advance; no other deductions)
            # profit = 10000 - 6777 = 3223
            assert t["profit"] == 3223
        finally:
            _cleanup_trip(t["id"])

    def test_own_vehicle_unchanged(self, customer_id):
        exp = dict(BASE_EXP, diesel=2000, toll=500, batta=300)
        t = _create_trip(customer_id,
                         vehicle_number="TS09OWN001",
                         vehicle_type="own",
                         tons=20,
                         freight_mode="per_ton",
                         rate_per_ton=1200,
                         expenses=exp)
        try:
            assert t["supplier_net_payable"] == 0.0
            assert t["total_expense"] == 2800
            assert t["profit"] == 24000 - 2800
        finally:
            _cleanup_trip(t["id"])


# ------------------------- Invoice recompute -----------------------

class TestInvoiceRecompute:

    def test_edit_invoiced_trip_recomputes_invoice(self, customer_id):
        t = _create_trip(customer_id,
                         vehicle_number="TS09INV001",
                         tons=10,
                         freight_mode="per_ton",
                         rate_per_ton=1000)
        tid = t["id"]
        try:
            inv_r = requests.post(f"{API}/invoices", headers=JSON_HEADERS,
                                  json={"customer_id": customer_id,
                                        "trip_ids": [tid],
                                        "gst_type": "cgst_sgst",
                                        "rcm": True})
            assert inv_r.status_code == 200, inv_r.text
            inv = inv_r.json()
            assert inv["subtotal"] == 10000
            iid = inv["id"]

            # Trip should now be invoiced
            g = requests.get(f"{API}/trips/{tid}", headers=HEADERS)
            # There might not be a single-trip GET; use list
            lst = requests.get(f"{API}/trips", headers=HEADERS,
                               params={"customer_id": customer_id}).json()
            match = [x for x in lst if x["id"] == tid][0]
            assert match["status"] == "invoiced"
            assert match["invoice_id"] == iid

            # Now EDIT the invoiced trip: change tons 10 → 15
            put_body = dict(match)
            put_body["tons"] = 15
            put_body["rate_per_ton"] = 1000
            put_body["freight_mode"] = "per_ton"
            r2 = requests.put(f"{API}/trips/{tid}", headers=JSON_HEADERS, json=put_body)
            assert r2.status_code == 200, r2.text
            updated = r2.json()
            assert updated["freight_amount"] == 15000
            assert updated["status"] == "invoiced"  # preserved
            assert updated["invoice_id"] == iid

            # Invoice must have auto-recomputed
            inv2 = requests.get(f"{API}/invoices/{iid}", headers=HEADERS).json()
            assert inv2["subtotal"] == 15000, inv2
            assert inv2["cgst_amount"] == 375.0
            assert inv2["sgst_amount"] == 375.0
            # rcm=True → total_amount = subtotal
            assert inv2["total_amount"] == 15000
        finally:
            # delete invoice then trip
            try:
                requests.delete(f"{API}/invoices/{iid}", headers=HEADERS,
                                params={"reason": "cleanup"})
            except Exception:
                pass
            _cleanup_trip(tid)


# ------------------------- Supplier P&L report ---------------------

class TestSupplierPLReport:

    def test_supplier_pl_aggregation(self, customer_id):
        t1 = _create_trip(customer_id,
                          vehicle_number="TS09RPT001",
                          vehicle_type="supplier",
                          supplier_name="TEST_RptSup",
                          supplier_freight_mode="per_ton",
                          supplier_rate_per_ton=1000,
                          supplier_quantity=10,
                          supplier_advance=2000,
                          supplier_other_recoveries=200,
                          tons=10,
                          freight_mode="per_ton",
                          rate_per_ton=1300)
        t2 = _create_trip(customer_id,
                          vehicle_number="TS09RPT002",
                          vehicle_type="supplier",
                          supplier_name="TEST_RptSup",
                          supplier_freight_mode="per_ton",
                          supplier_rate_per_ton=1000,
                          supplier_quantity=5,
                          supplier_advance=500,
                          supplier_other_recoveries=100,
                          tons=5,
                          freight_mode="per_ton",
                          rate_per_ton=1300)
        try:
            r = requests.get(f"{API}/reports/supplier-pl", headers=HEADERS)
            assert r.status_code == 200, r.text
            data = r.json()
            row = next((s for s in data["suppliers"]
                        if s["supplier_name"] == "TEST_RptSup"), None)
            assert row is not None, data
            assert row["trips"] == 2
            assert row["customer_freight"] == 10 * 1300 + 5 * 1300  # 19500
            assert row["supplier_freight"] == 10 * 1000 + 5 * 1000  # 15000
            assert row["supplier_advance"] == 2000 + 500            # 2500
            assert row["supplier_other_recoveries"] == 300
            # net_payable = 15000 - 2500 - 300 = 12200
            assert row["net_payable"] == 12200
            # profit = 19500 - (15000 - 2500) = 7000
            assert row["profit"] == 7000
            # margin = 7000/19500*100
            assert abs(row["margin_pct"] - 35.9) < 0.5
            # totals contain the aggregated row
            assert data["totals"]["profit"] >= 7000
        finally:
            _cleanup_trip(t1["id"])
            _cleanup_trip(t2["id"])


# ------------------------- P&L overall report ---------------------

class TestPLReport:

    def test_pl_supplier_net_payable(self, customer_id):
        t = _create_trip(customer_id,
                         vehicle_number="TS09PL001",
                         vehicle_type="supplier",
                         supplier_name="TEST_PLSup",
                         supplier_freight_mode="per_ton",
                         supplier_rate_per_ton=1000,
                         supplier_quantity=10,
                         supplier_advance=2000,
                         supplier_other_recoveries=0,
                         tons=10,
                         freight_mode="per_ton",
                         rate_per_ton=1500)
        try:
            r = requests.get(f"{API}/reports/pl", headers=HEADERS)
            assert r.status_code == 200
            data = r.json()
            assert "supplier_net_payable" in data["expenses"]
            # This trip contributes 10000-2000=8000 to supplier cost
            assert data["expenses"]["supplier_net_payable"] >= 8000
            # total expense should include supplier trip's total_expense
            assert data["expenses"]["total"] >= 8000
        finally:
            _cleanup_trip(t["id"])


# ------------------------- LR PDF 2-page ---------------------------

class TestLRPdfTwoPage:

    @pytest.mark.skipif(fitz is None, reason="PyMuPDF not installed")
    def test_lr_pdf_two_pages(self, customer_id):
        t = _create_trip(customer_id,
                         vehicle_number="TS09LR001",
                         tons=15,
                         freight_mode="per_ton",
                         rate_per_ton=1000,
                         lr_number="LR-TEST-8-001",
                         lr_time="10:30",
                         consignor_name="TEST Consignor",
                         driver_name="TEST Driver",
                         driver_mobile="9999999999",
                         waybill_no="EWB123456",
                         gross_weight=25.5,
                         tare_weight=10.5,
                         from_location="From-X",
                         to_location="To-Y")
        tid = t["id"]
        try:
            r = requests.get(f"{API}/trips/{tid}/lr", headers=HEADERS)
            assert r.status_code == 200, r.text
            assert "pdf" in r.headers.get("content-type", "").lower()
            d = fitz.open(stream=r.content, filetype="pdf")
            assert d.page_count == 2, f"Expected 2 pages, got {d.page_count}"

            p1 = d.load_page(0).get_text()
            p2 = d.load_page(1).get_text()

            # Page 1: operational details
            assert "LR-TEST-8-001" in p1
            assert "TS09LR001" in p1
            assert "TEST Driver" in p1
            assert "EWB123456" in p1

            # Page 2: T&C only
            assert "TERMS" in p2.upper()
            # Ensure operational details are NOT on page 2
            assert "TS09LR001" not in p2, "Vehicle number should not be on T&C page"
            assert "TEST Driver" not in p2, "Driver name should not be on T&C page"
            assert "EWB123456" not in p2, "Waybill should not be on T&C page"
        finally:
            _cleanup_trip(tid)
