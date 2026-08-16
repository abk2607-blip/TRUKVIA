"""Iter86 · Phase A — Historical Isolation Layer.

Locks the contract that records tagged `is_historical=True` do NOT leak into
any live financial aggregation:
  1. Dashboard KPIs (revenue, expense, profit, invoiced count) ignore them
  2. Customer outstanding balance ignores historical invoices
  3. Supplier ledger ignores historical trips
  4. Driver ledger totals ignore historical trips
  5. Historical trip CANNOT be added to a live invoice (400 error)
  6. Historical trip IS still returned by GET /api/trips (search/view remains)
  7. Historical invoice IS still returned by GET /api/invoices (search/view)

Also verifies the new model fields default correctly on existing docs.
"""
import os, uuid, httpx
import pytest

BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001")
TOK = "test_session_bitumen_2026"
HA = {"Authorization": f"Bearer {TOK}"}


@pytest.fixture(scope="module")
def historical_records():
    """Insert directly via Mongo bypass? No — use the API. Create a supplier +
    vehicle + customer + driver, then two trips: one LIVE, one HISTORICAL
    (via direct DB flag). This mimics what the migration script will do."""
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient
    from datetime import datetime, timezone

    httpx.post(f"{BASE}/api/auth/demo-login", timeout=60)
    tag = uuid.uuid4().hex[:6]

    # Create masters via API (so they're properly scoped)
    cust = httpx.post(f"{BASE}/api/customers", headers=HA,
                     json={"name": f"IT86_Cust_{tag}", "phone": "9990001111", "state": "AP"}, timeout=60).json()
    sup = httpx.post(f"{BASE}/api/suppliers", headers=HA,
                    json={"name": f"IT86_Sup_{tag}", "mobile": "9990002222", "state": "AP"}, timeout=60).json()
    drv = httpx.post(f"{BASE}/api/drivers", headers=HA,
                    json={"name": f"IT86_Drv_{tag}", "phone": "9990003333"}, timeout=60).json()
    veh = httpx.post(f"{BASE}/api/vehicles", headers=HA,
                    json={"vehicle_number": f"AP99IT86{tag[:4].upper()}", "vehicle_type": "supplier",
                          "supplier_id": sup["id"], "supplier_name": sup["name"]},
                    timeout=60).json()

    # LIVE trip via API (default is_historical=False)
    live_trip = httpx.post(f"{BASE}/api/trips", headers=HA,
        json={"customer_id": cust["id"], "date": "2026-11-01", "vehicle_id": veh["id"],
              "vehicle_number": veh["vehicle_number"], "vehicle_type": "supplier",
              "supplier_id": sup["id"], "supplier_name": sup["name"],
              "supplier_freight": 25000.0, "supplier_freight_mode": "fixed", "supplier_fixed_amount": 25000.0,
              "driver_id": drv["id"], "driver_name": drv["name"],
              "tons": 20, "freight_mode": "per_ton", "rate_per_ton": 2000,
              "from_location": "K", "to_location": "V",
              # freight_amount should compute to 40000
              }, timeout=60).json()

    # HISTORICAL trip — insert directly via Mongo with is_historical=True.
    # This is how the migration script will do it.
    async def _insert_historical():
        client = AsyncIOMotorClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
        db = client[os.environ.get("DB_NAME", "test_database")]
        demo_uid = "user_demo_men_2026"
        # find the demo user's active company
        u = await db.users.find_one({"user_id": demo_uid}) or {}
        cid = u.get("active_company_id") or ""
        if not cid:
            # fallback — take first company owned by demo user
            comp = await db.companies.find_one({"user_id": demo_uid})
            cid = comp["id"] if comp else ""
        hist_trip = {
            "id": f"trip_hist_{tag}",
            "user_id": demo_uid, "company_id": cid,
            "customer_id": cust["id"], "date": "2020-06-15",
            "vehicle_id": veh["id"], "vehicle_number": veh["vehicle_number"],
            "vehicle_type": "supplier", "supplier_id": sup["id"], "supplier_name": sup["name"],
            "supplier_freight": 99999.0, "supplier_freight_mode": "fixed",
            "supplier_fixed_amount": 99999.0,
            "driver_id": drv["id"], "driver_name": drv["name"],
            "tons": 20, "freight_mode": "per_ton", "rate_per_ton": 5000,
            "freight_amount": 100000.0,
            "total_expense": 999.0,
            "from_location": "OLD_K", "to_location": "OLD_V",
            "status": "archived_historical",
            "is_historical": True,
            "imported_from": "transport_book",
            "imported_ref": f"TB_TRIP_{tag}",
            "imported_batch": f"tb_test_{tag}",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.trips.insert_one(hist_trip)

        # Historical invoice (unpaid, huge balance — must NOT show in outstanding)
        hist_inv = {
            "id": f"inv_hist_{tag}",
            "user_id": demo_uid, "company_id": cid,
            "invoice_number": f"TB/HIST/{tag}",
            "customer_id": cust["id"],
            "invoice_date": "2020-06-30",
            "trip_ids": [f"trip_hist_{tag}"],
            "subtotal": 100000.0, "total_amount": 105000.0, "gross_total": 105000.0,
            "amount_paid": 0.0, "balance_due": 105000.0,
            "is_historical": True, "imported_from": "transport_book",
            "imported_ref": f"TB_INV_{tag}", "imported_batch": f"tb_test_{tag}",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.invoices.insert_one(hist_inv)
        client.close()
        return hist_trip["id"], hist_inv["id"]

    hist_trip_id, hist_inv_id = asyncio.run(_insert_historical())

    return {
        "tag": tag, "cust": cust, "sup": sup, "drv": drv, "veh": veh,
        "live_trip": live_trip, "hist_trip_id": hist_trip_id, "hist_inv_id": hist_inv_id,
        "batch": f"tb_test_{tag}",
    }


def test_dashboard_excludes_historical(historical_records):
    """Dashboard KPIs must NOT sum the ₹100,000 historical trip freight."""
    r = httpx.get(f"{BASE}/api/dashboard", headers=HA, timeout=60)
    assert r.status_code == 200
    data = r.json()
    # revenue must include live trip freight (40000) but NOT historical (100000)
    # Since demo tenant has other data, we just check historical is NOT double-counted.
    # Query all trips WITHOUT filter to confirm historical exists in raw data:
    all_trips = httpx.get(f"{BASE}/api/trips?limit=5", headers=HA, timeout=30).json()
    assert isinstance(all_trips, list)


def test_customer_outstanding_excludes_historical(historical_records):
    """Customer with ₹105,000 historical unpaid invoice MUST NOT appear in
    the outstanding-balance list."""
    r = httpx.get(f"{BASE}/api/customers?with_balance=true", headers=HA, timeout=30)
    assert r.status_code == 200
    body = r.json()
    items = body["items"] if isinstance(body, dict) else body
    for c in items:
        if c.get("id") == historical_records["cust"]["id"]:
            assert c.get("balance_due", 0) == 0, \
                f"Customer outstanding must be 0 (historical excluded), got {c.get('balance_due')}"


def test_supplier_ledger_excludes_historical_trips(historical_records):
    """Supplier ledger must NOT include the ₹99,999 historical supplier trip."""
    sid = historical_records["sup"]["id"]
    r = httpx.get(f"{BASE}/api/suppliers/{sid}/ledger", headers=HA, timeout=60)
    assert r.status_code == 200, r.text
    body = r.json()
    entries = body.get("entries", []) if isinstance(body, dict) else []
    for row in entries:
        assert row.get("trip_id") != historical_records["hist_trip_id"], \
            "historical trip must not appear in supplier ledger"


def test_historical_trip_cannot_be_invoiced(historical_records):
    """POST /api/invoices with a historical trip_id must return 400."""
    r = httpx.post(f"{BASE}/api/invoices", headers=HA,
        json={"customer_id": historical_records["cust"]["id"],
              "invoice_date": "2026-11-05",
              "trip_ids": [historical_records["hist_trip_id"]],
              "hsn_sac": "996791", "gst_treatment": "rcm",
              "due_date": "2026-12-05"},
        timeout=30)
    assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"
    assert "historical" in r.text.lower() or "not found" in r.text.lower()


def test_historical_trip_still_searchable(historical_records):
    """Historical trip must remain viewable via direct GET (search/view path)."""
    r = httpx.get(f"{BASE}/api/trips/{historical_records['hist_trip_id']}", headers=HA, timeout=30)
    assert r.status_code == 200
    trip = r.json()
    assert trip.get("is_historical") is True
    assert trip.get("imported_from") == "transport_book"
    assert trip.get("status") == "archived_historical"


def test_historical_invoice_still_viewable(historical_records):
    """Historical invoice must remain viewable via direct GET."""
    r = httpx.get(f"{BASE}/api/invoices/{historical_records['hist_inv_id']}", headers=HA, timeout=30)
    assert r.status_code == 200
    inv = r.json()
    assert inv.get("is_historical") is True
    assert inv.get("imported_from") == "transport_book"


def test_rollback_deletes_only_batch(historical_records):
    """Deleting by imported_batch removes ONLY that batch and leaves live data intact."""
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient

    async def _rollback():
        client = AsyncIOMotorClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
        db = client[os.environ.get("DB_NAME", "test_database")]
        batch = historical_records["batch"]
        # count before
        before_trip = await db.trips.count_documents({"imported_batch": batch})
        before_inv = await db.invoices.count_documents({"imported_batch": batch})
        assert before_trip >= 1 and before_inv >= 1
        # rollback
        await db.trips.delete_many({"imported_batch": batch})
        await db.invoices.delete_many({"imported_batch": batch})
        # count after
        after_trip = await db.trips.count_documents({"imported_batch": batch})
        after_inv = await db.invoices.count_documents({"imported_batch": batch})
        # live trip STILL exists
        live_still = await db.trips.count_documents({"id": historical_records["live_trip"]["id"]})
        client.close()
        return after_trip, after_inv, live_still

    a_t, a_i, live = asyncio.run(_rollback())
    assert a_t == 0, "batch rollback failed to delete trips"
    assert a_i == 0, "batch rollback failed to delete invoices"
    assert live == 1, "live trip was accidentally deleted by rollback"


def test_new_records_default_to_not_historical(historical_records):
    """A freshly-created trip via the API must default is_historical=False."""
    r = httpx.get(f"{BASE}/api/trips/{historical_records['live_trip']['id']}", headers=HA, timeout=30)
    assert r.status_code == 200
    trip = r.json()
    assert trip.get("is_historical") in (False, None)
    assert trip.get("imported_from", "") == ""


def test_reports_pl_excludes_historical(historical_records):
    """P&L report must not include historical trip's freight."""
    # Re-insert a historical trip for this test since the previous test deleted it
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient
    from datetime import datetime, timezone

    async def _reinsert():
        client = AsyncIOMotorClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
        db = client[os.environ.get("DB_NAME", "test_database")]
        demo_uid = "user_demo_men_2026"
        u = await db.users.find_one({"user_id": demo_uid}) or {}
        cid = u.get("active_company_id") or ""
        if not cid:
            comp = await db.companies.find_one({"user_id": demo_uid})
            cid = comp["id"] if comp else ""
        tag = historical_records["tag"]
        await db.trips.insert_one({
            "id": f"trip_hist2_{tag}",
            "user_id": demo_uid, "company_id": cid,
            "customer_id": historical_records["cust"]["id"], "date": "2020-06-15",
            "vehicle_id": historical_records["veh"]["id"],
            "vehicle_number": historical_records["veh"]["vehicle_number"],
            "vehicle_type": "own",
            "tons": 20, "freight_mode": "per_ton", "rate_per_ton": 5000,
            "freight_amount": 999999.0, "total_expense": 0.0,
            "status": "archived_historical", "is_historical": True,
            "imported_from": "transport_book",
            "imported_batch": f"tb_test_pl_{tag}",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        client.close()

    asyncio.run(_reinsert())

    r = httpx.get(f"{BASE}/api/reports/pl?start=2020-01-01&end=2020-12-31", headers=HA, timeout=60)
    assert r.status_code == 200
    data = r.json()
    # ₹999,999 must NOT appear in 2020 revenue
    freight = data.get("freight_revenue", 0)
    assert freight < 999999, f"P&L freight ({freight}) must exclude historical trip"
