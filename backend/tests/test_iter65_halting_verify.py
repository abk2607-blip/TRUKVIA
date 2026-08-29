"""Iter65 · Priority 1 — Halting Live Verification endpoint contract.

Verifies:
 - Endpoint returns rows with per-stage fields for every trip that has
   halting_days > 0 OR halting_amount > 0.
 - 4-day exemption is correctly applied (grace_days=4 default) with
   chargeable_halting_days = max(total - grace, 0).
 - Auto Halting Days computed from loading_date/unloading_date.
 - Manual halting_amount_override is respected (does not flag as mismatch).
 - Invoice line halting mirrors Trip halting.
 - only_mismatches=true returns 0 rows when everything is consistent.
 - Multi-company isolation.
"""
import os, uuid, pytest, httpx
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

BASE = os.environ.get("BACKEND_URL_INTERNAL", "http://localhost:8001")
TOKEN = os.environ["DEMO_TOKEN_VALUE"]
HDR = {"Authorization": f"Bearer {TOKEN}"}
UNIQUE = f"IT65_{uuid.uuid4().hex[:6]}"


def _companies():
    return httpx.get(f"{BASE}/api/companies", headers=HDR, timeout=60).json()


def _h(cid=None):
    return {**HDR, "X-Company-Id": cid or _companies()[0]["id"]}


@pytest.fixture(scope="module")
def env():
    cs = _companies()
    cid_a = cs[0]["id"]
    cid_b = cs[1]["id"] if len(cs) > 1 else cid_a
    ha = _h(cid_a)
    cust = httpx.post(f"{BASE}/api/customers", headers=ha, json={
        "name": f"IT65_C_{UNIQUE}", "phone": "9110000065", "state": "AP",
    }, timeout=60).json()
    veh = httpx.post(f"{BASE}/api/vehicles", headers=ha, json={
        "vehicle_number": f"AP65A{UNIQUE[:5]}", "vehicle_type": "own",
    }, timeout=60).json()
    return {"cid_a": cid_a, "cid_b": cid_b, "ha": ha, "cust": cust, "veh": veh}


def _make_trip(env, **overrides):
    base = {
        "customer_id": env["cust"]["id"], "date": "2026-06-01",
        "vehicle_id": env["veh"]["id"], "vehicle_number": env["veh"]["vehicle_number"],
        "tons": 20, "freight_mode": "per_ton", "rate_per_ton": 1500,
        "from_location": "K", "to_location": "V",
        "grace_days": 4,
    }
    base.update(overrides)
    return httpx.post(f"{BASE}/api/trips", headers=env["ha"], json=base, timeout=60).json()


# ---------------------------------------------------------------------------
# 1. Auto-halting-days derivation + 4-day exemption
# ---------------------------------------------------------------------------
def test_auto_halting_and_grace(env):
    trip = _make_trip(env,
        loading_date="2026-06-01", unloading_date="2026-06-10",  # 9 days
        halting_rate_per_day=500,
    )
    assert trip["total_halting_days"] == 9
    assert trip["chargeable_halting_days"] == 5  # 9 - 4 grace
    assert trip["halting_amount"] == 2500        # 5 × 500


# ---------------------------------------------------------------------------
# 2. Verify endpoint returns the trip with OK status
# ---------------------------------------------------------------------------
def test_halting_verify_ok_row(env):
    trip = _make_trip(env,
        date="2026-06-02", loading_date="2026-06-02", unloading_date="2026-06-08",
        halting_rate_per_day=400,
    )
    r = httpx.get(f"{BASE}/api/reports/halting-verify", headers=env["ha"],
                  params={"date_from": "2026-06-02", "date_to": "2026-06-02"}, timeout=60)
    assert r.status_code == 200
    body = r.json()
    row = next((x for x in body["rows"] if x["trip_id"] == trip["id"]), None)
    assert row is not None
    assert row["status"] == "OK"
    assert row["halting_calc"]["total_halting_days_stored"] == 6
    assert row["halting_calc"]["chargeable_halting_days_stored"] == 2
    assert row["halting_calc"]["halting_amount_stored"] == 800
    assert row["trip_entry"]["dates_present"] is True
    assert row["trip_entry"]["halting_amount_override"] is False


# ---------------------------------------------------------------------------
# 3. Manual override respected — no mismatch
# ---------------------------------------------------------------------------
def test_halting_override_not_flagged(env):
    trip = _make_trip(env,
        date="2026-06-03", loading_date="2026-06-03", unloading_date="2026-06-09",
        halting_rate_per_day=500,
        halting_amount=1500,                     # user manually overrode
        halting_amount_override=True,
    )
    assert trip["halting_amount"] == 1500
    r = httpx.get(f"{BASE}/api/reports/halting-verify", headers=env["ha"],
                  params={"date_from": "2026-06-03", "date_to": "2026-06-03"}, timeout=60)
    row = next((x for x in r.json()["rows"] if x["trip_id"] == trip["id"]), None)
    assert row and row["status"] == "OK"
    assert row["trip_entry"]["halting_amount_override"] is True


# ---------------------------------------------------------------------------
# 4. only_mismatches=true returns 0 rows for the OK trips above
# ---------------------------------------------------------------------------
def test_only_mismatches_filter(env):
    r = httpx.get(f"{BASE}/api/reports/halting-verify", headers=env["ha"],
                  params={"date_from": "2026-06-01", "date_to": "2026-06-03", "only_mismatches": "true"},
                  timeout=60)
    body = r.json()
    # Rows for these specific trips should not appear as mismatches
    unique_trip_dates = ["2026-06-01", "2026-06-02", "2026-06-03"]
    still_bad = [x for x in body["rows"] if x["date"] in unique_trip_dates]
    assert still_bad == []


# ---------------------------------------------------------------------------
# 5. Trip → Invoice: invoice halting mirrors the Trip
# ---------------------------------------------------------------------------
def test_invoice_halting_mirror(env):
    trip = _make_trip(env,
        date="2026-06-04", loading_date="2026-06-04", unloading_date="2026-06-11",
        halting_rate_per_day=600,
    )
    # Generate invoice for this trip
    inv = httpx.post(f"{BASE}/api/invoices", headers=env["ha"], json={
        "customer_id": env["cust"]["id"],
        "trip_ids": [trip["id"]],
        "date": "2026-06-12",
        "due_date": "2026-06-30",
    }, timeout=60).json()
    inv_id = inv["id"]
    # Invoice includes the halting
    inv_full = httpx.get(f"{BASE}/api/invoices/{inv_id}", headers=env["ha"], timeout=60).json()
    assert trip["id"] in inv_full["trip_ids"]
    assert inv_full["halting_total"] == trip["halting_amount"]
    # Verify endpoint reports the invoice mirror
    r = httpx.get(f"{BASE}/api/reports/halting-verify", headers=env["ha"],
                  params={"date_from": "2026-06-04", "date_to": "2026-06-04"}, timeout=60).json()
    row = next(x for x in r["rows"] if x["trip_id"] == trip["id"])
    assert row["invoice_stage"] is not None
    assert row["invoice_stage"]["trip_linked"] is True
    assert row["invoice_stage"]["invoice_line_halting"] == trip["halting_amount"]
    assert row["status"] == "OK"


# ---------------------------------------------------------------------------
# 6. Multi-company isolation
# ---------------------------------------------------------------------------
def test_multi_company_isolation(env):
    if env["cid_a"] == env["cid_b"]:
        pytest.skip("only one company")
    hb = _h(env["cid_b"])
    r = httpx.get(f"{BASE}/api/reports/halting-verify", headers=hb, timeout=60).json()
    a_dates = {"2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04"}
    leaked = [x for x in r["rows"] if x["date"] in a_dates and x["customer_name"] == env["cust"]["name"]]
    assert leaked == [], f"Company A halting trips leaked to Company B: {leaked}"
