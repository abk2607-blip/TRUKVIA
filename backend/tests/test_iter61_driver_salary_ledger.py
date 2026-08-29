"""Iter61 · Phase C — Driver Salary & Payment Ledger.

Covers:
 1. Salary master CRUD + effective-date rollover
 2. Manual ledger entry (advance / other_payment / other_deduction) + guard against system types
 3. Monthly salary posting idempotency + historical accuracy
 4. Monthly settlement create + update + clear
 5. Auto-sync from Trip create → trip_recovery entry appears in ledger
 6. Auto-sync from Trip update → recovery amount refreshed / cleared / driver-reassigned
 7. Auto-sync from Trip delete → ledger row removed
 8. Ledger listing: opening balance, running balance, closing balance, credit/debit totals
 9. Monthly rollup
10. CSV export
11. PDF export
12. Multi-company isolation
"""
import os, uuid, pytest, httpx
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

BASE = os.environ.get("BACKEND_URL_INTERNAL", "http://localhost:8001")
TOKEN = os.environ["DEMO_TOKEN_VALUE"]
HDR = {"Authorization": f"Bearer {TOKEN}"}
UNIQUE = f"IT61_{uuid.uuid4().hex[:6]}"


def _companies():
    return httpx.get(f"{BASE}/api/companies", headers=HDR, timeout=60).json()


def _h(cid=None):
    return {**HDR, "X-Company-Id": cid or _companies()[0]["id"]}


@pytest.fixture(scope="module")
def env():
    cs = _companies()
    cid_a = cs[0]["id"]
    cid_b = cs[1]["id"] if len(cs) > 1 else cid_a  # allow single-company fallback
    ha = _h(cid_a)
    # Policy so shortage trips generate a snapshot
    httpx.post(f"{BASE}/api/driver-shortage-policies", headers=ha, json={
        "name": f"IT61Pol_{UNIQUE}", "shortage_limit_kg": 100, "unit": "KG",
        "effective_from": "2026-01-01", "product_category": UNIQUE, "active": True,
    }, timeout=60)
    drv = httpx.post(f"{BASE}/api/drivers", headers=ha, json={
        "name": f"IT61_DRV_{UNIQUE}", "phone": "9998887777",
    }, timeout=60).json()
    drv2 = httpx.post(f"{BASE}/api/drivers", headers=ha, json={
        "name": f"IT61_DRV2_{UNIQUE}", "phone": "9990001111",
    }, timeout=60).json()
    cust = httpx.post(f"{BASE}/api/customers", headers=ha, json={
        "name": f"IT61_C_{UNIQUE}", "phone": "9111111111", "state": "AP",
    }, timeout=60).json()
    veh = httpx.post(f"{BASE}/api/vehicles", headers=ha, json={
        "vehicle_number": f"AP61{UNIQUE[:4]}{uuid.uuid4().hex[:2].upper()}",
        "vehicle_type": "own",
    }, timeout=60).json()
    return {"cid_a": cid_a, "cid_b": cid_b, "drv": drv, "drv2": drv2,
            "cust": cust, "veh": veh, "ha": ha}


# ---------------------------------------------------------------------------
# 1. Salary Master CRUD + effective-date rollover
# ---------------------------------------------------------------------------
def test_salary_master_create_and_rollover(env):
    did = env["drv"]["id"]
    ha = env["ha"]
    # v1
    r1 = httpx.post(f"{BASE}/api/drivers/{did}/salary-masters", headers=ha, json={
        "monthly_salary": 20000, "effective_from": "2026-01-01",
    }, timeout=60)
    assert r1.status_code == 200, r1.text
    v1 = r1.json()
    assert v1["monthly_salary"] == 20000
    assert v1["version"] >= 1
    # v2 with later effective_from → v1.effective_to auto-set to yesterday
    r2 = httpx.post(f"{BASE}/api/drivers/{did}/salary-masters", headers=ha, json={
        "monthly_salary": 25000, "effective_from": "2026-04-01",
    }, timeout=60)
    assert r2.status_code == 200, r2.text
    lst = httpx.get(f"{BASE}/api/drivers/{did}/salary-masters", headers=ha, timeout=60).json()["items"]
    by_id = {x["id"]: x for x in lst}
    assert by_id[v1["id"]]["effective_to"] == "2026-03-31"
    assert by_id[r2.json()["id"]]["effective_to"] is None


# ---------------------------------------------------------------------------
# 2. Manual ledger entry + system-type guard
# ---------------------------------------------------------------------------
def test_manual_ledger_and_system_guard(env):
    did = env["drv"]["id"]
    ha = env["ha"]
    # advance
    r = httpx.post(f"{BASE}/api/drivers/{did}/ledger", headers=ha, json={
        "entry_date": "2026-02-10", "entry_type": "advance", "amount": 3000,
        "remarks": "Feb advance",
    }, timeout=60)
    assert r.status_code == 200, r.text
    assert r.json()["direction"] == "debit"
    # other_deduction
    r2 = httpx.post(f"{BASE}/api/drivers/{did}/ledger", headers=ha, json={
        "entry_date": "2026-02-20", "entry_type": "other_deduction", "amount": 500,
    }, timeout=60)
    assert r2.status_code == 200
    # trip_recovery via manual endpoint MUST be rejected
    bad = httpx.post(f"{BASE}/api/drivers/{did}/ledger", headers=ha, json={
        "entry_date": "2026-02-10", "entry_type": "trip_recovery", "amount": 100,
    }, timeout=60)
    assert bad.status_code == 400
    # settlement also
    bad2 = httpx.post(f"{BASE}/api/drivers/{did}/ledger", headers=ha, json={
        "entry_date": "2026-02-10", "entry_type": "settlement", "amount": 100,
    }, timeout=60)
    assert bad2.status_code == 400
    # amount<=0 rejected
    bad3 = httpx.post(f"{BASE}/api/drivers/{did}/ledger", headers=ha, json={
        "entry_date": "2026-02-10", "entry_type": "advance", "amount": 0,
    }, timeout=60)
    assert bad3.status_code == 422


# ---------------------------------------------------------------------------
# 3. Monthly salary posting: idempotency + historical accuracy
# ---------------------------------------------------------------------------
def test_monthly_salary_posting_historical_accuracy(env):
    did = env["drv"]["id"]
    ha = env["ha"]
    # January uses v1 (20000)
    r_jan = httpx.post(f"{BASE}/api/drivers/{did}/ledger/post-monthly-salary",
                      headers=ha, json={"month": "2026-01"}, timeout=60)
    assert r_jan.status_code == 200, r_jan.text
    assert r_jan.json()["amount"] == 20000
    # April uses v2 (25000)
    r_apr = httpx.post(f"{BASE}/api/drivers/{did}/ledger/post-monthly-salary",
                      headers=ha, json={"month": "2026-04"}, timeout=60)
    assert r_apr.status_code == 200
    assert r_apr.json()["amount"] == 25000
    # Idempotent — reposting Jan updates the same entry, does not duplicate
    r_jan2 = httpx.post(f"{BASE}/api/drivers/{did}/ledger/post-monthly-salary",
                       headers=ha, json={"month": "2026-01"}, timeout=60)
    assert r_jan2.status_code == 200
    assert r_jan2.json()["amount"] == 20000
    assert r_jan2.json()["updated"] is True
    # Count salary entries — expect exactly 2 (Jan + Apr)
    ledger = httpx.get(f"{BASE}/api/drivers/{did}/ledger", headers=ha, timeout=60).json()
    salary_entries = [e for e in ledger["entries"] if e["entry_type"] == "salary"]
    assert len(salary_entries) == 2
    # No policy month rejects
    r_none = httpx.post(f"{BASE}/api/drivers/{did}/ledger/post-monthly-salary",
                       headers=ha, json={"month": "2025-06"}, timeout=60)
    assert r_none.status_code == 400


# ---------------------------------------------------------------------------
# 4. Monthly settlement create / update / clear
# ---------------------------------------------------------------------------
def test_monthly_settlement_flow(env):
    did = env["drv"]["id"]
    ha = env["ha"]
    r = httpx.post(f"{BASE}/api/drivers/{did}/ledger/settle", headers=ha, json={
        "month": "2026-02", "paid_amount": 2500, "remarks": "Feb close",
    }, timeout=60)
    assert r.status_code == 200
    assert r.json()["amount"] == 2500
    eid = r.json()["id"]
    # Update paid_amount → same id
    r2 = httpx.post(f"{BASE}/api/drivers/{did}/ledger/settle", headers=ha, json={
        "month": "2026-02", "paid_amount": 3000,
    }, timeout=60)
    assert r2.status_code == 200
    assert r2.json()["amount"] == 3000
    assert r2.json()["id"] == eid
    # Clear settlement (paid=0) → row deleted
    r3 = httpx.post(f"{BASE}/api/drivers/{did}/ledger/settle", headers=ha, json={
        "month": "2026-02", "paid_amount": 0,
    }, timeout=60)
    assert r3.status_code == 200
    assert r3.json()["cleared"] is True
    ledger = httpx.get(f"{BASE}/api/drivers/{did}/ledger", headers=ha, timeout=60).json()
    settlements = [e for e in ledger["entries"] if e["entry_type"] == "settlement"]
    assert len([s for s in settlements if s.get("month_key") == "2026-02"]) == 0


# ---------------------------------------------------------------------------
# 5. Trip → Ledger auto-sync (create with shortage)
# ---------------------------------------------------------------------------
def test_trip_recovery_auto_sync(env):
    did = env["drv"]["id"]
    ha = env["ha"]
    trip = httpx.post(f"{BASE}/api/trips", headers=ha, json={
        "customer_id": env["cust"]["id"], "date": "2026-05-10",
        "vehicle_id": env["veh"]["id"], "vehicle_number": env["veh"]["vehicle_number"],
        "driver_id": did, "driver_name": env["drv"]["name"],
        "tons": 20.0, "freight_mode": "per_ton", "rate_per_ton": 1500,
        "loaded_qty": 20.0, "unloaded_qty": 19.8,  # 200 KG shortage → 100 KG recoverable
        "product_rate_per_mt": 200.0, "product_category": UNIQUE,
        "from_location": "K", "to_location": "V",
    }, timeout=60).json()
    tid = trip["id"]
    # Recovery expected = (200-100 KG recoverable) × rate 200 = 20000 (Phase A convention: KG × rate)
    assert trip.get("driver_recovery", {}).get("final_recovery_amount") == 20000.0
    # Ledger has a trip_recovery entry with this trip's ref
    ledger = httpx.get(f"{BASE}/api/drivers/{did}/ledger", headers=ha, timeout=60).json()
    tr = [e for e in ledger["entries"] if e["entry_type"] == "trip_recovery"
          and (e.get("reference") or {}).get("id") == tid]
    assert len(tr) == 1
    assert tr[0]["amount"] == 20000.0
    assert tr[0]["direction"] == "debit"


# ---------------------------------------------------------------------------
# 6. Trip update — driver reassigned + amount refresh
# ---------------------------------------------------------------------------
def test_trip_update_ledger_sync(env):
    did = env["drv"]["id"]
    did2 = env["drv2"]["id"]
    ha = env["ha"]
    trip = httpx.post(f"{BASE}/api/trips", headers=ha, json={
        "customer_id": env["cust"]["id"], "date": "2026-05-11",
        "vehicle_id": env["veh"]["id"], "vehicle_number": env["veh"]["vehicle_number"],
        "driver_id": did, "driver_name": env["drv"]["name"],
        "tons": 20.0, "freight_mode": "per_ton", "rate_per_ton": 1500,
        "loaded_qty": 20.0, "unloaded_qty": 19.7,  # 300 KG shortage → 200 KG recoverable
        "product_rate_per_mt": 150.0, "product_category": UNIQUE,
        "from_location": "K", "to_location": "V",
    }, timeout=60).json()
    tid = trip["id"]
    # Reassign to drv2 + change unloaded to eliminate shortage
    upd_payload = {**trip, "driver_id": did2, "driver_name": env["drv2"]["name"],
                   "unloaded_qty": 20.0, "shortage_qty": 0.0}
    upd = httpx.put(f"{BASE}/api/trips/{tid}", headers=ha, json=upd_payload, timeout=60)
    assert upd.status_code == 200, upd.text
    # Old driver → no ledger entry for this trip
    l_old = httpx.get(f"{BASE}/api/drivers/{did}/ledger", headers=ha, timeout=60).json()
    old_hits = [e for e in l_old["entries"] if (e.get("reference") or {}).get("id") == tid]
    assert old_hits == []
    # New driver → snapshot preserves original limit, but shortage=0 so final=0 → no entry
    l_new = httpx.get(f"{BASE}/api/drivers/{did2}/ledger", headers=ha, timeout=60).json()
    new_hits = [e for e in l_new["entries"] if (e.get("reference") or {}).get("id") == tid]
    assert new_hits == []  # no shortage → no ledger row


# ---------------------------------------------------------------------------
# 7. Trip delete removes ledger entry
# ---------------------------------------------------------------------------
def test_trip_delete_ledger_cleanup(env):
    did = env["drv"]["id"]
    ha = env["ha"]
    trip = httpx.post(f"{BASE}/api/trips", headers=ha, json={
        "customer_id": env["cust"]["id"], "date": "2026-05-12",
        "vehicle_id": env["veh"]["id"], "vehicle_number": env["veh"]["vehicle_number"],
        "driver_id": did, "driver_name": env["drv"]["name"],
        "tons": 20.0, "freight_mode": "per_ton", "rate_per_ton": 1500,
        "loaded_qty": 20.0, "unloaded_qty": 19.5,
        "product_rate_per_mt": 100.0, "product_category": UNIQUE,
        "from_location": "K", "to_location": "V",
    }, timeout=60).json()
    tid = trip["id"]
    # There is a recovery entry before delete
    l0 = httpx.get(f"{BASE}/api/drivers/{did}/ledger", headers=ha, timeout=60).json()
    assert any((e.get("reference") or {}).get("id") == tid for e in l0["entries"])
    # Delete
    d = httpx.request("DELETE", f"{BASE}/api/trips/{tid}", headers=ha,
                      params={"reason": "iter61 cleanup"}, timeout=60)
    assert d.status_code == 200, d.text
    l1 = httpx.get(f"{BASE}/api/drivers/{did}/ledger", headers=ha, timeout=60).json()
    assert not any((e.get("reference") or {}).get("id") == tid for e in l1["entries"])


# ---------------------------------------------------------------------------
# 8. Ledger listing — opening / closing / totals
# ---------------------------------------------------------------------------
def test_ledger_totals_and_running_balance(env):
    did = env["drv"]["id"]
    ha = env["ha"]
    # Ask for Feb window — opening should be Jan salary (20000)
    r = httpx.get(f"{BASE}/api/drivers/{did}/ledger", headers=ha,
                  params={"date_from": "2026-02-01", "date_to": "2026-02-28"}, timeout=60)
    assert r.status_code == 200
    body = r.json()
    assert body["opening_balance"] == 20000.0  # from Jan salary posted earlier
    # Feb has advance 3000 + other_deduction 500 → both debits → closing = 20000 - 3500 = 16500
    assert body["debit_total"] == 3500.0
    assert body["credit_total"] == 0.0
    assert body["closing_balance"] == 16500.0
    # Running balance monotonically applied
    running = [e["balance"] for e in body["entries"]]
    assert running == sorted(running, reverse=True)  # only debits in Feb → balance drops


# ---------------------------------------------------------------------------
# 9. Monthly rollup
# ---------------------------------------------------------------------------
def test_monthly_rollup(env):
    did = env["drv"]["id"]
    ha = env["ha"]
    r = httpx.get(f"{BASE}/api/drivers/{did}/ledger/monthly", headers=ha, timeout=60)
    assert r.status_code == 200
    rows = r.json()["items"]
    jan = next((row for row in rows if row["month"] == "2026-01"), None)
    apr = next((row for row in rows if row["month"] == "2026-04"), None)
    feb = next((row for row in rows if row["month"] == "2026-02"), None)
    assert jan and jan["salary"] == 20000
    assert apr and apr["salary"] == 25000
    assert feb and feb["advance"] == 3000 and feb["other_deduction"] == 500


# ---------------------------------------------------------------------------
# 10-11. Export CSV + PDF
# ---------------------------------------------------------------------------
def test_export_csv(env):
    did = env["drv"]["id"]
    ha = env["ha"]
    r = httpx.get(f"{BASE}/api/drivers/{did}/ledger/export", headers=ha,
                  params={"format": "csv"}, timeout=60)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    body = r.content.decode("utf-8-sig")
    assert "Driver Ledger" in body
    assert env["drv"]["name"] in body
    assert "Opening Balance" in body and "Closing Balance" in body


def test_export_pdf(env):
    did = env["drv"]["id"]
    ha = env["ha"]
    r = httpx.get(f"{BASE}/api/drivers/{did}/ledger/export", headers=ha,
                  params={"format": "pdf"}, timeout=60)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# 12. Multi-company isolation
# ---------------------------------------------------------------------------
def test_multi_company_isolation(env):
    """A driver, salary master, and ledger entry from Company A must NOT
    be visible / mutable through Company B's context."""
    if env["cid_a"] == env["cid_b"]:
        pytest.skip("only one company in fixture — cannot verify multi-company isolation")
    did = env["drv"]["id"]
    hb = _h(env["cid_b"])
    # Driver 404 under B
    assert httpx.get(f"{BASE}/api/drivers/{did}/ledger", headers=hb, timeout=60).status_code == 404
    assert httpx.get(f"{BASE}/api/drivers/{did}/salary-masters", headers=hb, timeout=60).status_code == 404
    # Posting salary under B for A's driver → 404
    r_post = httpx.post(f"{BASE}/api/drivers/{did}/salary-masters", headers=hb, json={
        "monthly_salary": 99999, "effective_from": "2026-01-01",
    }, timeout=60)
    assert r_post.status_code == 404
    # Manual ledger under B for A's driver → 404
    r_led = httpx.post(f"{BASE}/api/drivers/{did}/ledger", headers=hb, json={
        "entry_date": "2026-06-01", "entry_type": "advance", "amount": 100,
    }, timeout=60)
    assert r_led.status_code == 404
