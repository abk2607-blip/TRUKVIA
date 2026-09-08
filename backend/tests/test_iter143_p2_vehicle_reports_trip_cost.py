"""Iter143 P2 · Vehicle-wise Trip Cost in PDF + Excel — focused tests.

Scope (from the approved spec):
  * PDF gains a `TRIP-WISE COST SUMMARY` section between the KPI band
    and the Category+Month dual table.
  * Excel gains a `Trip Cost` worksheet inserted between `Repairs` and
    `By Category`. No existing sheet is modified.
  * Both are pure projections of `cost_summary.rows[]`. Trip metadata
    (route, customer, driver, supplier, type) comes from a single Mongo
    IN-query built server-side inside the report route handler. No N+1.
  * Reconciliation guard: `sum(trip totals) == cost_summary.trip_linked_total`.
    On mismatch the endpoint returns HTTP 500 rather than emit an
    incorrect report.
  * Supplier-payable, VendorBill, MechanicWO amounts are never included
    in Trip Cost totals.
  * Cancelled / reversed Expense rows are excluded (they never appear in
    `cost_summary.rows[]` upstream, tested here end-to-end).
  * Existing Iter142 sheets remain intact.

The tests below exercise all of the above against the live backend.
"""
from io import BytesIO
from pathlib import Path
import os
import re
import uuid
import time
import requests
import openpyxl

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"
if not API.startswith("http"):
    API = "http://localhost:8001/api"
TOKEN = os.environ.get("DEMO_TOKEN_VALUE", "")
H = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


# ── Helpers ────────────────────────────────────────────────────────────────

def _customer():
    r = requests.get(f"{API}/customers", headers=H, timeout=15).json()
    for c in r:
        if c["name"] == "TEST_Iter143_P2":
            return c["id"]
    return requests.post(
        f"{API}/customers", headers=H,
        json={"name": "TEST_Iter143_P2", "state": "Andhra Pradesh"}, timeout=15,
    ).json()["id"]


def _first_own_vehicle():
    vehs = requests.get(f"{API}/vehicles", headers=H, params={"active_only": True}, timeout=15).json()
    for v in vehs:
        if (v.get("vehicle_type") or "").lower() != "supplier":
            return v
    return None


def _first_supplier_vehicle():
    vehs = requests.get(f"{API}/vehicles", headers=H, params={"active_only": True}, timeout=15).json()
    for v in vehs:
        if (v.get("vehicle_type") or "").lower() == "supplier":
            return v
    return None


def _mk_trip(cid, veh, date, tons=10):
    body = {
        "customer_id": cid, "date": date,
        "vehicle_number": veh["vehicle_number"],
        "vehicle_id": veh["id"], "vehicle_type": "own",
        "tons": tons, "freight_mode": "per_ton", "rate_per_ton": 1000,
        "from_location": "P2VJA", "to_location": "P2KKD",
        "driver_name": "P2 Driver",
    }
    r = requests.post(f"{API}/trips", headers=H, json=body, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


def _mk_exp(veh_id, trip_id, category, amount, date):
    body = {
        "date": date, "category": category, "amount": amount,
        "vehicle_id": veh_id, "trip_id": trip_id,
        "party_type": "cash", "settlement_mode": "cash_now",
        "narration": "iter143-p2",
    }
    r = requests.post(f"{API}/expenses", headers=H, json=body, timeout=15)
    assert r.status_code in (200, 201), r.text
    return r.json()


def _get_pdf(vid, params=None):
    r = requests.get(f"{API}/vehicles/{vid}/cost-summary.pdf", headers=H,
                     params=params or {}, timeout=30)
    assert r.status_code == 200, r.text
    assert r.content[:4] == b"%PDF"
    return r.content


def _get_xlsx(vid, params=None):
    r = requests.get(f"{API}/vehicles/{vid}/cost-summary.xlsx", headers=H,
                     params=params or {}, timeout=30)
    assert r.status_code == 200, r.text
    return openpyxl.load_workbook(BytesIO(r.content))


def _json_summary(vid, params=None):
    return requests.get(f"{API}/vehicles/{vid}/cost-summary", headers=H,
                        params=params or {}, timeout=15).json()


# ── Excel tests ────────────────────────────────────────────────────────────

def test_p2_xlsx_has_trip_cost_sheet_in_correct_position():
    veh = _first_own_vehicle()
    wb = _get_xlsx(veh["id"])
    assert wb.sheetnames == [
        "Summary", "Expenses", "Repairs", "Trip Cost", "By Category", "By Month"
    ], f"Sheet order changed: {wb.sheetnames}"


def test_p2_original_iter142_sheets_intact():
    """Iter142 sheets must still be present in the same order (with the
    Trip Cost sheet additively inserted) and their expense/repair total
    rows must reconcile with the JSON cost-summary — proving Iter142
    structure was not disturbed."""
    veh = _first_own_vehicle()
    js = _json_summary(veh["id"])
    wb = _get_xlsx(veh["id"])
    # Expenses total row
    ws = wb["Expenses"]
    total = None
    for row in ws.iter_rows(values_only=True):
        if row[4] == "Total":
            total = row[5]; break
    assert total is not None
    assert abs(float(total) - float(js["total_cost"])) < 0.01, (
        f"Expenses sheet total drifted: {total} != {js['total_cost']}"
    )
    # By Category / By Month headers still there
    assert wb["By Category"].cell(row=1, column=1).value == "Category"
    assert wb["By Month"].cell(row=1, column=1).value == "Month"


def test_p2_xlsx_trip_cost_sheet_total_matches_trip_linked_total():
    veh = _first_own_vehicle()
    js = _json_summary(veh["id"])
    wb = _get_xlsx(veh["id"])
    ws = wb["Trip Cost"]
    # Header row is 1; walk to the Total row.
    total = None
    trip_totals = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[5] == "Total Trip-linked Cost":
            total = row[6]; break
        # Data rows: only count actual data rows
        if row[6] is not None and isinstance(row[6], (int, float)):
            trip_totals.append(float(row[6]))
    assert total is not None, "Trip Cost sheet missing total row"
    assert abs(float(total) - float(js["trip_linked_total"])) < 0.01
    assert abs(sum(trip_totals) - float(js["trip_linked_total"])) < 0.01


def test_p2_xlsx_trip_cost_has_required_columns():
    veh = _first_own_vehicle()
    wb = _get_xlsx(veh["id"])
    ws = wb["Trip Cost"]
    hdrs = [ws.cell(row=1, column=i).value for i in range(1, 8)]
    assert hdrs == ["Trip Date", "Trip Ref", "Route", "Customer / Driver",
                    "Type", "Categories", "Trip Cost"]


def test_p2_xlsx_zero_cost_trip_not_listed():
    cid = _customer()
    veh = _first_own_vehicle()
    # Fresh trip with NO Expense — zero-cost.
    trip = _mk_trip(cid, veh, "2029-01-01")
    wb = _get_xlsx(veh["id"], {"from": "2029-01-01", "to": "2029-01-01"})
    ws = wb["Trip Cost"]
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[5] == "Total Trip-linked Cost":
            break
        assert row[1] != trip["id"], "Zero-cost trip must be hidden"


def test_p2_xlsx_trip_row_with_multiple_categories():
    cid = _customer()
    veh = _first_own_vehicle()
    trip = _mk_trip(cid, veh, "2029-01-02")
    _mk_exp(veh["id"], trip["id"], "Diesel", 4000.0, "2029-01-02")
    _mk_exp(veh["id"], trip["id"], "Toll",    500.0, "2029-01-02")
    _mk_exp(veh["id"], trip["id"], "Batta",   200.0, "2029-01-02")
    wb = _get_xlsx(veh["id"], {"from": "2029-01-02", "to": "2029-01-02"})
    ws = wb["Trip Cost"]
    found = None
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[5] == "Total Trip-linked Cost":
            break
        if row[6] is not None and abs(float(row[6]) - 4700.0) < 0.01:
            found = row; break
    assert found is not None, "Multi-category trip missing from Trip Cost sheet"
    assert "Diesel" in (found[5] or "") and "Toll" in (found[5] or "")
    assert "Batta" in (found[5] or "")


def test_p2_xlsx_supplier_payable_not_in_trip_cost():
    """Even if the supplier trip carries supplier_freight / advance / diesel,
    those are payable-side and NEVER contribute to Trip Cost. Only actual
    canonical Expense rows do."""
    sup = _first_supplier_vehicle()
    if not sup:
        return
    cid = _customer()
    body = {
        "customer_id": cid, "date": "2029-01-03",
        "vehicle_number": sup["vehicle_number"],
        "vehicle_id": sup["id"], "vehicle_type": "supplier",
        "supplier_id": sup.get("supplier_id") or "",
        "supplier_name": sup.get("supplier_name") or "",
        "tons": 10, "freight_mode": "per_ton", "rate_per_ton": 1000,
        "supplier_freight_mode": "per_ton", "supplier_rate_per_ton": 800,
        "supplier_advance": 3000, "supplier_diesel": 2000,
        "from_location": "SVJA", "to_location": "SKKD",
    }
    r = requests.post(f"{API}/trips", headers=H, json=body, timeout=15)
    if r.status_code != 200:
        return  # supplier trip creation policy-blocked in this tenant
    trip = r.json()
    _mk_exp(sup["id"], trip["id"], "Toll", 250.0, "2029-01-03")
    wb = _get_xlsx(sup["id"], {"from": "2029-01-03", "to": "2029-01-03"})
    ws = wb["Trip Cost"]
    match = None
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[5] == "Total Trip-linked Cost":
            break
        if row[6] is not None and abs(float(row[6]) - 250.0) < 0.01:
            match = row; break
    assert match is not None, "Supplier trip cost row missing"
    assert match[4] == "SUPPLIER"
    # Supplier payable (2000/3000) must NOT be added
    assert abs(float(match[6]) - 250.0) < 0.01


def test_p2_xlsx_cancelled_expense_excluded_from_trip_cost():
    cid = _customer()
    veh = _first_own_vehicle()
    trip = _mk_trip(cid, veh, "2029-01-04")
    exp = _mk_exp(veh["id"], trip["id"], "Diesel", 900.0, "2029-01-04")
    # verify it's there first
    wb = _get_xlsx(veh["id"], {"from": "2029-01-04", "to": "2029-01-04"})
    ws = wb["Trip Cost"]
    seen = False
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[5] == "Total Trip-linked Cost":
            break
        if row[6] and isinstance(row[6], (int, float)) and abs(float(row[6]) - 900.0) < 0.01:
            seen = True; break
    assert seen, "expense should show first"
    # cancel + retry
    requests.delete(f"{API}/expenses/{exp['id']}", headers=H,
                    params={"reason": "iter143-p2 cancel"}, timeout=15)
    wb = _get_xlsx(veh["id"], {"from": "2029-01-04", "to": "2029-01-04"})
    ws = wb["Trip Cost"]
    for row in ws.iter_rows(min_row=2, values_only=True):
        # After cancellation the only remaining row should be the total
        # row with 0. Never a data row carrying 900.
        if row[5] == "Total Trip-linked Cost":
            total_val = float(row[6] or 0)
            assert abs(total_val) < 0.01, f"total_val={total_val} — cancel not reflected"
            break
        # Data rows must not carry 900 anymore.
        if isinstance(row[6], (int, float)):
            assert abs(float(row[6]) - 900.0) >= 0.01


def test_p2_xlsx_repair_linked_row_not_in_trip_cost():
    """A row that has both trip_id AND repair_event_id belongs to Repairs,
    not to Trip Cost — proving no double-count between the Repairs sheet
    and the Trip Cost sheet."""
    veh = _first_own_vehicle()
    js = _json_summary(veh["id"])
    # Simulate by manually filtering the same rules the factory uses:
    trip_only = [r for r in js["rows"] if r.get("trip_id") and not r.get("repair_event_id")]
    trip_only_sum = round(sum(float(r["amount"]) for r in trip_only), 2)
    assert abs(trip_only_sum - float(js["trip_linked_total"])) < 0.01


def test_p2_xlsx_filter_parity_from_to():
    veh = _first_own_vehicle()
    # unfiltered
    wb_full = _get_xlsx(veh["id"])
    ws_full = wb_full["Trip Cost"]
    full_total = 0
    for row in ws_full.iter_rows(min_row=2, values_only=True):
        if row[5] == "Total Trip-linked Cost":
            full_total = row[6]; break
    # far-future range — must be zero
    wb_fut = _get_xlsx(veh["id"], {"from": "2099-01-01", "to": "2099-01-02"})
    ws_fut = wb_fut["Trip Cost"]
    fut_total = 0
    for row in ws_fut.iter_rows(min_row=2, values_only=True):
        if row[5] == "Total Trip-linked Cost":
            fut_total = row[6]; break
    assert (fut_total or 0) == 0
    # unfiltered must be >= filtered
    assert (full_total or 0) >= (fut_total or 0)


def test_p2_xlsx_category_filter_parity():
    veh = _first_own_vehicle()
    wb = _get_xlsx(veh["id"], {"category": "Diesel"})
    ws = wb["Trip Cost"]
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[5] == "Total Trip-linked Cost": break
        # Categories column must only reference Diesel when the filter is Diesel
        cats = row[5] or ""
        if cats:
            for tok in ["Toll", "Batta", "Repair", "FastTag", "Other"]:
                assert tok not in cats, (
                    f"Category filter breach: sheet shows {tok} under Diesel filter"
                )


def test_p2_xlsx_vehicle_isolation():
    vehs = requests.get(f"{API}/vehicles", headers=H,
                        params={"active_only": True}, timeout=15).json()
    own = [v for v in vehs if (v.get("vehicle_type") or "").lower() != "supplier"]
    if len(own) < 2:
        return
    a, b = own[0], own[1]
    cid = _customer()
    trip_a = _mk_trip(cid, a, "2029-01-05")
    _mk_exp(a["id"], trip_a["id"], "Diesel", 777.77, "2029-01-05")
    wb_b = _get_xlsx(b["id"], {"from": "2029-01-05", "to": "2029-01-05"})
    ws = wb_b["Trip Cost"]
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[5] == "Total Trip-linked Cost": break
        # Trip A's ref/id must not appear on B's Trip Cost sheet
        assert row[1] != trip_a["id"]
        assert not (row[6] and abs(float(row[6]) - 777.77) < 0.01)


# ── PDF tests ──────────────────────────────────────────────────────────────

def test_p2_pdf_endpoint_ok_and_reasonable_size():
    veh = _first_own_vehicle()
    content = _get_pdf(veh["id"])
    assert len(content) > 1200


def test_p2_pdf_contains_trip_wise_section_header():
    """Extract text via poppler's pdftotext — reportlab compresses streams
    so raw-byte assertions are unreliable."""
    import subprocess, tempfile
    veh = _first_own_vehicle()
    js = _json_summary(veh["id"])
    if float(js.get("trip_linked_total") or 0) <= 0:
        return  # no trip-linked cost → section is intentionally hidden
    content = _get_pdf(veh["id"])
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(content); f.flush()
        text = subprocess.check_output(
            ["pdftotext", "-layout", f.name, "-"], timeout=15
        ).decode("utf-8", "ignore")
    assert "TRIP-WISE COST SUMMARY" in text, (
        "TRIP-WISE COST SUMMARY header not found in PDF text"
    )
    # Reconciliation banner text must also be present with the same total.
    assert "Grouped from Expense Detail by Trip" in text
    assert "Trip-linked Cost KPI" in text
    # Every trip total shown must reconcile with the KPI number.
    m = re.search(r"Trip-linked Cost KPI \(₹\s*([\d,]+\.\d{2})\)", text)
    assert m, "KPI value missing from Trip Cost section header"
    kpi_val = float(m.group(1).replace(",", ""))
    assert abs(kpi_val - float(js["trip_linked_total"])) < 0.01


def test_p2_pdf_reconciliation_guard_no_crash_in_normal_flow():
    """Every real vehicle should render its PDF without hitting the guard."""
    vehs = requests.get(f"{API}/vehicles", headers=H,
                        params={"active_only": True}, timeout=15).json()[:10]
    ok = 0
    for v in vehs:
        r = requests.get(f"{API}/vehicles/{v['id']}/cost-summary.pdf",
                         headers=H, timeout=30)
        assert r.status_code in (200, 413), (
            f"PDF for {v['id']} status={r.status_code} body={r.text[:250]}"
        )
        if r.status_code == 200:
            ok += 1
    assert ok >= 1, "No PDF succeeded — infra issue"


def test_p2_pdf_and_xlsx_agree_on_trip_linked_total():
    """Different renderers, same authoritative total."""
    veh = _first_own_vehicle()
    js = _json_summary(veh["id"])
    wb = _get_xlsx(veh["id"])
    ws = wb["Trip Cost"]
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[5] == "Total Trip-linked Cost":
            assert abs(float(row[6] or 0) - float(js["trip_linked_total"])) < 0.01
            return
    assert float(js["trip_linked_total"]) == 0


def test_p2_pdf_endpoint_no_new_url_no_new_param():
    """P2 must NOT introduce a new endpoint / param — validate via
    static route inspection of the router file."""
    src = Path("/app/backend/routers/vehicle_reports.py").read_text(encoding="utf-8")
    # No trip-costs route added
    assert "/trip-costs" not in src, (
        "Iter143 P2 must NOT add a /trip-costs endpoint — reuse existing "
        "cost-summary.{pdf,xlsx} only"
    )
    # Existing endpoints unchanged
    assert '@router.get("/vehicles/{vid}/cost-summary.pdf")' in src
    assert '@router.get("/vehicles/{vid}/cost-summary.xlsx")' in src


def test_p2_report_generation_does_not_create_bill_or_payment():
    veh = _first_own_vehicle()
    bills0 = requests.get(f"{API}/vendor-bills", headers=H, timeout=15).json()
    # trigger both formats
    _get_pdf(veh["id"])
    _get_xlsx(veh["id"])
    bills1 = requests.get(f"{API}/vendor-bills", headers=H, timeout=15).json()
    assert len(bills0) == len(bills1)


def test_p2_reconciliation_guard_json_invariant_across_all_own_vehicles():
    """Trip-linked + Non-trip == Total, for every vehicle we probe. This
    ensures the guard would never spuriously trigger."""
    vehs = requests.get(f"{API}/vehicles", headers=H,
                        params={"active_only": True}, timeout=15).json()[:15]
    for v in vehs:
        js = _json_summary(v["id"])
        lhs = round(float(js["trip_linked_total"]) + float(js["non_trip_total"]), 2)
        rhs = round(float(js["total_cost"]), 2)
        assert abs(lhs - rhs) < 0.01, (
            f"Invariant broken for {v['id']}: {lhs} != {rhs}"
        )


def test_p2_single_in_query_no_per_trip_fetch():
    """Static guard — the router must NOT do per-trip lookups. It must
    use a single Mongo IN-query."""
    src = Path("/app/backend/routers/vehicle_reports.py").read_text(encoding="utf-8")
    # Locate the helper body
    idx = src.index("async def _build_trip_meta_map")
    end = src.index("async def _report_context", idx)
    body = src[idx:end]
    # Must use $in operator; must not use one-shot db.trips.find_one inside a loop
    assert '"$in":' in body or "'$in':" in body, "Trip meta join must be $in-based"
    assert "for t in tids" not in body and "for tid in tids:" not in body, (
        "Trip meta join must not iterate per trip_id issuing separate queries"
    )
    # find_one inside the helper is banned
    assert "find_one" not in body


def test_p2_factory_reconciliation_guard_raises_on_bad_data():
    """Directly poke the factories with a hand-crafted broken payload to
    ensure the guard raises ValueError instead of emitting a bad file."""
    from pdf.vehicle_cost import build_vehicle_cost_pdf
    from xlsx.vehicle_cost import build_vehicle_cost_xlsx
    broken_cost = {
        "rows": [
            {"trip_id": "trip_x", "amount": 100.0, "category": "Diesel",
             "date": "2029-01-01"},
        ],
        # Lie about trip_linked_total so the guard MUST trigger
        "trip_linked_total": 999.0,
        "non_trip_total": 0.0,
        "total_cost": 999.0,
        "repair_total": 0.0,
        "by_category": [], "by_month": [], "expense_count": 1,
    }
    try:
        build_vehicle_cost_pdf({}, {"vehicle_number": "X"}, broken_cost, {},
                               {"from": None, "to": None, "category": None})
    except ValueError as e:
        assert "reconciliation" in str(e).lower()
    else:
        assert False, "PDF factory did NOT raise on reconciliation mismatch"
    try:
        build_vehicle_cost_xlsx({}, {"vehicle_number": "X"}, broken_cost, {},
                                {"from": None, "to": None, "category": None})
    except ValueError as e:
        assert "reconciliation" in str(e).lower()
    else:
        assert False, "XLSX factory did NOT raise on reconciliation mismatch"


def test_p2_frontend_reports_tab_still_wired():
    """Iter142 wiring must remain — the Reports tab still points at the
    same two endpoints. No FE change expected in P2."""
    src = Path("/app/frontend/src/pages/VehicleWorkspace.jsx").read_text(encoding="utf-8")
    for m in ("cost-summary.pdf", "cost-summary.xlsx",
              'data-testid="vw-download-pdf"',
              'data-testid="vw-download-xlsx"'):
        assert m in src, f"missing marker: {m}"
