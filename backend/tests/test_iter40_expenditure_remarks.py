"""Iter40 — Dynamic Other-Expenditure Master + Remarks fields + LR Driver auto-fill.

Uses the live backend (same pattern as iter39). Verifies:
  1. /api/expenditure-types CRUD + default seeding
  2. Trip stores other_expenditures list; each row's amount aggregates into total_expense
  3. Trip stores halting/shortage/excess/other_income remarks; supplier_settlement_remarks
  4. Trip stores lr_driver_name / lr_driver_mobile independent of driver_name/mobile
  5. Invoice PDF renders remarks under Halting/Shortage/Diesel/Advance sub-rows
"""
import os
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"
TOKEN = "test_session_bitumen_2026"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def _customer():
    r = requests.get(f"{API}/customers", headers=HEADERS)
    for c in r.json():
        if c["name"] == "TEST_Iter40":
            return c["id"]
    return requests.post(f"{API}/customers", headers=HEADERS, json={"name": "TEST_Iter40", "state": "Andhra Pradesh"}).json()["id"]


def test_expenditure_types_default_seed_and_crud():
    r = requests.get(f"{API}/expenditure-types", headers=HEADERS)
    assert r.status_code == 200
    types = r.json()
    names = [t["name"] for t in types]
    assert "Driver Food" in names
    assert "Toll" in names
    # Duplicate insert is idempotent
    r2 = requests.post(f"{API}/expenditure-types", headers=HEADERS, json={"name": "Driver Food"})
    assert r2.status_code == 200
    # Add a fresh custom type
    r3 = requests.post(f"{API}/expenditure-types", headers=HEADERS, json={"name": "Iter40 Custom Type"})
    assert r3.status_code == 200
    assert r3.json()["name"] == "Iter40 Custom Type"
    tid = r3.json()["id"]
    r4 = requests.delete(f"{API}/expenditure-types/{tid}", headers=HEADERS)
    assert r4.status_code == 200


def test_trip_other_expenditures_and_other_income_affect_profit():
    cid = _customer()
    r = requests.post(f"{API}/trips", headers=HEADERS, json={
        "customer_id": cid, "date": "2026-02-15",
        "vehicle_number": "AP16TA0040", "tons": 10,
        "freight_mode": "per_ton", "rate_per_ton": 1000,
        "other_expenditures": [
            {"id": "oe_1", "date": "2026-02-15", "type": "Driver Food", "amount": 300, "remarks": "Highway dhaba"},
            {"id": "oe_2", "date": "2026-02-15", "type": "Parking", "amount": 200, "remarks": ""},
        ],
        "other_income": 100,
    })
    assert r.status_code == 200
    t = r.json()
    assert t["freight_amount"] == 10000.0
    assert t["total_expense"] == 500.0
    # Profit = billable(10000) - expense(500) + other_income(100)
    assert t["profit"] == 9600.0
    assert len(t["other_expenditures"]) == 2


def test_trip_remarks_and_lr_driver_persist():
    cid = _customer()
    r = requests.post(f"{API}/trips", headers=HEADERS, json={
        "customer_id": cid, "date": "2026-02-15",
        "vehicle_number": "AP16TA0041", "tons": 10,
        "freight_mode": "per_ton", "rate_per_ton": 1000,
        "halting_remarks": "Site delay",
        "shortage_remarks": "Weighbridge issue",
        "excess_remarks": "Overload accepted",
        "other_income_remarks": "Bonus",
        "supplier_settlement_remarks": "TDS deducted",
        "driver_name": "Original Driver",
        "driver_mobile": "9000000000",
        "lr_driver_name": "LR Override Driver",
        "lr_driver_mobile": "9111111111",
    })
    assert r.status_code == 200
    t = r.json()
    assert t["halting_remarks"] == "Site delay"
    assert t["shortage_remarks"] == "Weighbridge issue"
    assert t["excess_remarks"] == "Overload accepted"
    assert t["other_income_remarks"] == "Bonus"
    assert t["supplier_settlement_remarks"] == "TDS deducted"
    # Trip-level driver name/mobile untouched
    assert t["driver_name"] == "Original Driver"
    assert t["driver_mobile"] == "9000000000"
    # LR-side overrides stored independently
    assert t["lr_driver_name"] == "LR Override Driver"
    assert t["lr_driver_mobile"] == "9111111111"


def test_invoice_pdf_renders_remarks():
    """Rich trip → invoice; PDF text extraction must include every remark."""
    import pymupdf
    cid = _customer()
    trip = requests.post(f"{API}/trips", headers=HEADERS, json={
        "customer_id": cid, "date": "2026-02-15",
        "vehicle_number": "AP16TA0042", "tons": 20,
        "freight_mode": "per_ton", "rate_per_ton": 1500,
        "halting_amount": 2500, "halting_amount_override": True,
        "halting_remarks": "ITER40 HALTING REMARK",
        "shortage_amount": 500, "shortage_amount_override": True,
        "shortage_remarks": "ITER40 SHORTAGE REMARK",
        "customer_receipts": [
            {"id": "r1", "date": "2026-02-15", "type": "diesel", "litres": 100, "rate": 90, "amount": 9000, "remarks": "ITER40 DIESEL REMARK"},
            {"id": "r2", "date": "2026-02-15", "type": "advance", "amount": 5000, "mode": "UPI", "ref_no": "UPI-X", "remarks": "ITER40 ADVANCE REMARK"},
        ],
    }).json()
    tid = trip["id"]

    inv = requests.post(f"{API}/invoices", headers=HEADERS, json={
        "customer_id": cid, "trip_ids": [tid], "gst_type": "cgst_sgst", "rcm": True,
    }).json()
    assert inv["diesel_deduction_total"] == 9000.0
    assert inv["advance_deduction_total"] == 5000.0

    pdf = requests.get(f"{API}/invoices/{inv['id']}/pdf", headers=HEADERS)
    assert pdf.status_code == 200
    text = ""
    with pymupdf.open(stream=pdf.content, filetype="pdf") as doc:
        for p in doc:
            text += p.get_text()
    for kw in [
        "ITER40 HALTING REMARK",
        "ITER40 SHORTAGE REMARK",
        "ITER40 DIESEL REMARK",
        "ITER40 ADVANCE REMARK",
    ]:
        assert kw in text, f"Missing remark in PDF: {kw!r}"
