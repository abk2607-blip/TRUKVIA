"""Iter58 — Bulk actions on Trip Log (P1), Auth IP burst alerts (P2), Sparkline slice drill-down (P3)."""
import os
import time
import uuid
import pytest
import httpx
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

BASE = os.environ.get("BACKEND_URL_INTERNAL", "http://localhost:8001")
TOKEN = os.environ["DEMO_TOKEN_VALUE"]
HDR = {"Authorization": f"Bearer {TOKEN}"}
UNIQUE = f"IT58_{uuid.uuid4().hex[:6]}"


def _cid():
    return httpx.get(f"{BASE}/api/companies", headers=HDR, timeout=60).json()[0]["id"]


def _h(cid=None):
    return {**HDR, "X-Company-Id": cid or _cid()}


@pytest.fixture(scope="module")
def seeded():
    """Create a customer + 3 pending trips + 1 trip for a DIFFERENT customer."""
    h = _h()
    cust_a = httpx.post(f"{BASE}/api/customers", headers=h, json={
        "name": f"BULK_A_{UNIQUE}", "phone": "9111111111", "state": "AP",
    }, timeout=60).json()
    cust_b = httpx.post(f"{BASE}/api/customers", headers=h, json={
        "name": f"BULK_B_{UNIQUE}", "phone": "9222222222", "state": "AP",
    }, timeout=60).json()
    veh = httpx.post(f"{BASE}/api/vehicles", headers=h, json={
        "vehicle_number": f"AP58{UNIQUE[:4]}", "vehicle_type": "own",
    }, timeout=60).json()
    trips_a = []
    for i in range(3):
        r = httpx.post(f"{BASE}/api/trips", headers=h, json={
            "customer_id": cust_a["id"], "date": f"2026-09-{i+1:02d}",
            "vehicle_id": veh["id"], "vehicle_number": veh["vehicle_number"],
            "tons": 20, "freight_mode": "per_ton", "rate_per_ton": 1500,
            "from_location": "Kondapalli", "to_location": "Vijayawada",
            "load_details": f"BulkTest_{UNIQUE}",
        }, timeout=60)
        trips_a.append(r.json())
    trip_b = httpx.post(f"{BASE}/api/trips", headers=h, json={
        "customer_id": cust_b["id"], "date": "2026-09-01",
        "vehicle_id": veh["id"], "vehicle_number": veh["vehicle_number"],
        "tons": 10, "freight_mode": "per_ton", "rate_per_ton": 1500,
        "from_location": "Kondapalli", "to_location": "Vijayawada",
        "load_details": f"BulkTest_B_{UNIQUE}",
    }, timeout=60).json()
    return {"cust_a": cust_a, "cust_b": cust_b, "trips_a": trips_a, "trip_b": trip_b}


# ============================================================
# P1 — Bulk Invoice preflight
# ============================================================

def test_bulk_invoice_preflight_ok(seeded):
    ids = [t["id"] for t in seeded["trips_a"]]
    r = httpx.post(f"{BASE}/api/trips/bulk-invoice-preflight", headers=_h(),
                   json={"trip_ids": ids}, timeout=60)
    b = r.json()
    assert b["ok"] is True, b
    assert b["customer_id"] == seeded["cust_a"]["id"]
    assert b["trip_count"] == 3


def test_bulk_invoice_preflight_mixed_customers(seeded):
    ids = [seeded["trips_a"][0]["id"], seeded["trip_b"]["id"]]
    r = httpx.post(f"{BASE}/api/trips/bulk-invoice-preflight", headers=_h(),
                   json={"trip_ids": ids}, timeout=60)
    b = r.json()
    assert b["ok"] is False
    assert b["reason"] == "mixed_customers"
    assert "same customer" in b["detail"].lower()


def test_bulk_invoice_creates_real_invoice(seeded):
    """Full flow — preflight + POST /invoices — creates ONE invoice, links all
    selected trips, and sets their status to 'invoiced'."""
    ids = [t["id"] for t in seeded["trips_a"]]
    r = httpx.post(f"{BASE}/api/invoices", headers=_h(), json={
        "customer_id": seeded["cust_a"]["id"], "trip_ids": ids,
        "gst_type": "cgst_sgst", "rcm": False,
    }, timeout=60)
    assert r.status_code == 200, r.text
    inv = r.json()
    assert inv["id"].startswith("inv")
    assert set(inv["trip_ids"]) == set(ids)
    # Trips are now marked invoiced with invoice_id
    for tid in ids:
        t = httpx.get(f"{BASE}/api/trips/{tid}", headers=_h(), timeout=60).json()
        assert t["status"] == "invoiced"
        assert t["invoice_id"] == inv["id"]
    # Freight+halting rolled up correctly
    assert inv["freight_total"] == pytest.approx(sum(t.get("freight_amount", 0) for t in seeded["trips_a"]), abs=1)


def test_bulk_invoice_preflight_rejects_already_invoiced(seeded):
    """After the previous test invoiced trips_a, preflight must refuse."""
    r = httpx.post(f"{BASE}/api/trips/bulk-invoice-preflight", headers=_h(),
                   json={"trip_ids": [seeded["trips_a"][0]["id"]]}, timeout=60)
    b = r.json()
    assert b["ok"] is False
    assert b["reason"] == "already_invoiced"


# ============================================================
# P1 — Bulk Delete
# ============================================================

def test_bulk_delete_requires_reason():
    r = httpx.post(f"{BASE}/api/trips/bulk-delete", headers=_h(),
                   json={"trip_ids": ["fake"], "reason": ""}, timeout=60)
    assert r.status_code == 400
    assert "reason" in r.json()["detail"].lower()


def test_bulk_delete_invoiced_requires_force(seeded):
    """Selected trips include already-invoiced ones — without force, refuse."""
    ids = [t["id"] for t in seeded["trips_a"]]
    r = httpx.post(f"{BASE}/api/trips/bulk-delete", headers=_h(), json={
        "trip_ids": ids, "reason": "test iter58", "force_invoiced": False,
    }, timeout=60)
    b = r.json()
    assert b["ok"] is False
    assert b["requires_force"] is True
    assert b["invoiced_count"] == 3


def test_bulk_delete_with_force_recomputes_invoice(seeded):
    """With force_invoiced, invoiced trips are deleted and their invoice recomputed."""
    ids = [t["id"] for t in seeded["trips_a"]]
    r = httpx.post(f"{BASE}/api/trips/bulk-delete", headers=_h(), json={
        "trip_ids": ids, "reason": "iter58 bulk-delete test", "force_invoiced": True,
    }, timeout=60)
    b = r.json()
    assert b["ok"] is True
    assert b["deleted_count"] == 3
    assert len(b["recomputed_invoices"]) >= 1
    # Trips are gone
    for tid in ids:
        gr = httpx.get(f"{BASE}/api/trips/{tid}", headers=_h(), timeout=60)
        assert gr.status_code == 404


# ============================================================
# P1 — Export with explicit trip_ids
# ============================================================

def test_export_accepts_trip_ids(seeded):
    tid = seeded["trip_b"]["id"]
    r = httpx.get(f"{BASE}/api/trips/export", headers=_h(),
                  params={"format": "csv", "trip_ids": tid}, timeout=60)
    assert r.status_code == 200
    lines = r.content.decode("utf-8-sig").splitlines()
    # Exactly 1 header + 1 row
    assert len(lines) == 2, f"expected 1 row, got {len(lines) - 1}"


def test_export_trip_ids_respects_company(seeded):
    """Passing a valid trip_id from Company B while operating in Company A
    must NOT export it — company scoping still applies on top of trip_ids."""
    comps = httpx.get(f"{BASE}/api/companies", headers=HDR, timeout=60).json()
    if len(comps) < 2:
        pytest.skip("need 2+ companies")
    cid_a, cid_b = comps[0]["id"], comps[1]["id"]
    tid = seeded["trip_b"]["id"]  # created in Company A
    r = httpx.get(f"{BASE}/api/trips/export", headers=_h(cid_b),
                  params={"format": "csv", "trip_ids": tid}, timeout=60)
    lines = r.content.decode("utf-8-sig").splitlines()
    assert len(lines) == 1, "export ignored company scoping when trip_ids was set"


# ============================================================
# P2 — Auth IP Burst alerts
# ============================================================

def test_auth_ip_burst_fires_and_is_pii_safe():
    """After 21+ auth failures from THIS test's requests, expect at least one
    auth_ip_burst alert. Alert must be completely PII-safe."""
    import motor.motor_asyncio, asyncio
    async def _clear():
        c = motor.motor_asyncio.AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = c[os.environ["DB_NAME"]]
        # DELETE existing burst alerts entirely so per-IP cooldown resets.
        await db.save_health_alerts.delete_many({"kind": "auth_ip_burst"})
        c.close()
    asyncio.run(_clear())
    # Fire 25 bad-token requests. Iter121 · loopback is filtered from save_health,
    # so pytest must supply X-Forwarded-For (mimicking Kubernetes ingress) to be
    # counted toward the auth_ip_burst alert.
    for _ in range(25):
        httpx.get(f"{BASE}/api/auth/me",
                  headers={
                      "Authorization": f"Bearer iter58_burst_{uuid.uuid4().hex[:6]}",
                      "X-Forwarded-For": "203.0.113.58",
                  },
                  timeout=60)
    # Give the fire-and-forget task time to write alert
    for _ in range(10):
        time.sleep(0.5)
        async def _check():
            c = motor.motor_asyncio.AsyncIOMotorClient(os.environ["MONGO_URL"])
            db = c[os.environ["DB_NAME"]]
            docs = await db.save_health_alerts.find({"kind": "auth_ip_burst"}).to_list(5)
            c.close()
            return docs
        docs = asyncio.run(_check())
        if docs:
            break
    assert docs, "expected at least one auth_ip_burst alert to fire"
    a = docs[0]
    for k in ("ip", "count", "threshold", "window_minutes", "sample_paths"):
        assert k in a, f"missing key {k!r}"
    assert a["count"] >= 20
    assert a["window_minutes"] == 60
    # PII safety
    row_str = str(a).lower()
    for banned in ("authorization", "cookie", "token", "password", "bearer",
                   "session_token", "auth_header"):
        assert banned not in row_str, f"alert exposes sensitive field {banned!r}: {a}"


# ============================================================
# P3 — Sparkline slice drill-down
# ============================================================

def test_auth_failures_accepts_since_until():
    """The drill-down endpoint accepts since/until ISO params."""
    from datetime import datetime, timezone, timedelta
    since = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    until = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    r = httpx.get(f"{BASE}/api/admin/save-health/auth-failures",
                  params={"hours": 24, "limit": 50, "since": since, "until": until},
                  timeout=60)
    assert r.status_code == 200
    b = r.json()
    # Every row must fall in [since, until]
    for row in b["items"]:
        assert since <= row["ts_iso"] <= until, (
            f"row {row['ts_iso']} outside slice {since}..{until}"
        )


def test_auth_failures_narrow_window_returns_subset():
    """Narrow window should return <= full-window count."""
    from datetime import datetime, timezone, timedelta
    full = httpx.get(f"{BASE}/api/admin/save-health/auth-failures",
                    params={"hours": 24, "limit": 500}, timeout=60).json()["count"]
    since = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    r = httpx.get(f"{BASE}/api/admin/save-health/auth-failures",
                  params={"hours": 24, "limit": 500, "since": since}, timeout=60).json()
    assert r["count"] <= full, f"narrow window returned more ({r['count']}) than full ({full})"


# ============================================================
# Frontend testid presence
# ============================================================

def test_frontend_iter58_testids():
    with open("/app/frontend/src/pages/Trips.jsx") as f:
        c = f.read()
    for tid in ("bulk-action-bar", "bulk-select-all", "bulk-selected-count",
                "bulk-invoice-btn", "bulk-export-btn", "bulk-delete-btn",
                "bulk-clear-selection", "bulk-invoiced-warning"):
        assert tid in c, f"testid {tid!r} missing from Trips.jsx"
    with open("/app/frontend/src/pages/Dashboard.jsx") as f:
        c = f.read()
    for tid in ("sparkline-bucket-", "auth-drill-scope"):
        assert tid in c, f"testid {tid!r} missing from Dashboard.jsx"
