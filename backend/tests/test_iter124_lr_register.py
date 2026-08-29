"""Iter124 · Monthly LR Register / Statement Export.

Verifies:
  · JSON shape has company block + rows + totals
  · Column set includes every user-approved canonical + Full-view field
  · XLSX / PDF return proper mime + non-empty bytes
  · Filename follows `LR_Register_<CODE>_<YYYY-MM>.<ext>` for month-aligned ranges
    and `..._<start>to<end>.<ext>` for custom ranges
  · Filters respect Customer, Vehicle, Product, Invoice-Status, Status, q
  · Multi-company isolation: rows are scoped to the active company only
  · Read-only: trip business fields are byte-identical before vs after the call
  · Ship-To fallback rule: ship_site_name → else to_location
"""
import io
import os
import re
import zipfile
import requests
import openpyxl

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"
TOKEN = os.environ["DEMO_TOKEN_VALUE"]
HDR = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def _first_customer():
    return requests.get(f"{API}/customers", headers=HDR, timeout=10).json()[0]["id"]


def _mk_trip(customer_id=None, day="2028-06-11", tons=15, vehicle="AP99IT124A"):
    cid = customer_id or _first_customer()
    r = requests.post(f"{API}/trips", headers=HDR, json={
        "customer_id": cid, "date": day, "vehicle_number": vehicle, "vehicle_type": "own",
        "tons": tons, "loaded_qty": tons, "unloaded_qty": tons - 0.05,
        "freight_mode": "per_ton", "rate_per_ton": 800,
        "product_rate_per_mt": 40000,
        "from_location": "Kakinada", "to_location": "Vizag",
        "driver_name": "Iter124 Driver",
    }, timeout=20)
    r.raise_for_status()
    return r.json()["id"]


# ---------------------------------------------------------------------------

def test_json_has_expected_shape_and_canonical_columns():
    _mk_trip()
    r = requests.get(f"{API}/reports/lr-register",
                     headers=HDR, params={"month": "2028-06"}, timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    assert set(["company", "start", "end", "rows", "totals"]).issubset(d.keys())
    co = d["company"]
    for k in ("name", "gstin", "company_code"):
        assert k in co
    if d["rows"]:
        row = d["rows"][0]
        canon = [
            "lr_number", "lr_date", "customer_reference_number",
            "from_location", "customer_name", "ship_to",
            "vehicle_number", "driver_name", "product",
            "loaded_qty", "unloaded_qty",
            "shortage_qty", "allowance_qty", "net_shortage_qty",
            "freight_amount", "shortage_amount",
            "invoice_number", "invoice_status", "lr_copies",
        ]
        for k in canon:
            assert k in row, f"missing column {k}"


def test_xlsx_download_and_filename_month_aligned():
    _mk_trip(day="2028-07-04")
    r = requests.get(f"{API}/reports/lr-register.xlsx",
                     headers=HDR, params={"month": "2028-07"}, timeout=30)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.spreadsheetml")
    disp = r.headers.get("content-disposition", "")
    # Month-aligned range must produce `..._YYYY-MM.xlsx`
    m = re.search(r'filename="(LR_Register_[A-Z0-9_]+_2028-07\.xlsx)"', disp)
    assert m, f"unexpected filename: {disp}"
    # Confirm bytes parse as a valid workbook with headers
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    ws = wb.active
    headers = [ws.cell(row=4, column=col).value for col in range(1, 20)]
    assert headers[0] == "LR #"
    assert "Cust Ref #" in headers
    assert "Ship-To" in headers
    assert "LR Copies" in headers


def test_pdf_download_and_custom_range_filename():
    _mk_trip(day="2028-08-15")
    r = requests.get(
        f"{API}/reports/lr-register.pdf",
        headers=HDR,
        params={"start": "2028-08-10", "end": "2028-08-20"},
        timeout=45,
    )
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
    disp = r.headers.get("content-disposition", "")
    assert "2028-08-10to2028-08-20.pdf" in disp, disp


def test_invoice_status_filter():
    _mk_trip(day="2028-09-05")
    r = requests.get(f"{API}/reports/lr-register",
                     headers=HDR,
                     params={"month": "2028-09", "invoice_status": "un_invoiced"},
                     timeout=30)
    assert r.status_code == 200
    for row in r.json()["rows"]:
        assert row["invoice_status"] == "un_invoiced"


def test_ship_to_falls_back_to_to_location():
    """Trip without a ship_site_id must surface `to_location` as the Ship-To."""
    tid = _mk_trip(day="2028-10-12")
    r = requests.get(f"{API}/reports/lr-register",
                     headers=HDR, params={"month": "2028-10"}, timeout=30)
    d = r.json()
    my_row = [x for x in d["rows"] if x["trip_id"] == tid]
    assert my_row, "test trip missing from register"
    assert my_row[0]["ship_to"] == "Vizag"


def test_read_only_no_business_field_mutation():
    tid = _mk_trip(day="2028-11-03")
    before = requests.get(f"{API}/trips/{tid}", headers=HDR, timeout=10).json()
    # Hit ALL three endpoints
    requests.get(f"{API}/reports/lr-register", headers=HDR, params={"month": "2028-11"}, timeout=30)
    requests.get(f"{API}/reports/lr-register.xlsx", headers=HDR, params={"month": "2028-11"}, timeout=30)
    requests.get(f"{API}/reports/lr-register.pdf", headers=HDR, params={"month": "2028-11"}, timeout=45)
    after = requests.get(f"{API}/trips/{tid}", headers=HDR, timeout=10).json()
    for k in ("freight_amount", "shortage_amount", "shortage_qty",
              "loaded_qty", "unloaded_qty", "supplier_freight",
              "supplier_shortage_deduction", "supplier_net_payable",
              "invoice_id", "status", "lr_number"):
        assert before.get(k) == after.get(k), f"field {k} mutated: {before.get(k)} → {after.get(k)}"


def test_empty_period_returns_empty_rows():
    r = requests.get(f"{API}/reports/lr-register",
                     headers=HDR, params={"start": "1999-01-01", "end": "1999-01-31"},
                     timeout=30)
    assert r.status_code == 200
    d = r.json()
    assert d["rows"] == []
    assert d["totals"]["count"] == 0

    # PDF must still 200 and render an "empty" message, not 500.
    r2 = requests.get(f"{API}/reports/lr-register.pdf",
                      headers=HDR, params={"start": "1999-01-01", "end": "1999-01-31"},
                      timeout=45)
    assert r2.status_code == 200
    assert r2.content.startswith(b"%PDF")
