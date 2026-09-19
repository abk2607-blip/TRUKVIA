"""Production-safety · destructive startup cleanup runs in Preview only.

server.py startup performs four destructive `delete_many()` calls:
  • Iter70/72 fixture purge (background migrations): customers, suppliers,
    vehicles of the demo tenant whose names look like pytest fixtures;
  • Iter130 legacy demo-session purge (startup_event): user_sessions.
They must execute only when IS_PREVIEW_ENV == "1" (the same signal auth.py
uses). Absent or any other value is production → zero such calls.

Each scenario boots the REAL app startup (all @app.on_event("startup")
handlers + the scheduled background migrations) in a fresh subprocess against
a throwaway database that the test creates and drops. It never touches the
configured DB_NAME. Motor binds to one event loop and auth.py reads
IS_PREVIEW_ENV at import time, hence one process per scenario.
"""
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
MONGO_URL = os.environ.get("MONGO_URL") or "mongodb://127.0.0.1:27017"

_DRIVER = r'''
import asyncio, json, os, sys, time
from motor.motor_asyncio import AsyncIOMotorCollection

CALLS = []
_orig = AsyncIOMotorCollection.delete_many
def _spy(self, filter, *a, **kw):
    CALLS.append(self.name)
    return _orig(self, filter, *a, **kw)
AsyncIOMotorCollection.delete_many = _spy

UID = "user_demo_men_2026"
LEGACY = "test_session_" + "bitumen_2026"

async def main():
    import server
    db = server.db
    await db.customers.insert_many([
        {"user_id": UID, "id": "c-fix", "name": "TEST_fixture customer"},
        {"user_id": UID, "id": "c-real", "name": "Real Customer Ltd"},
    ])
    await db.suppliers.insert_many([
        {"user_id": UID, "id": "s-fix", "name": "IT72 fixture supplier"},
        {"user_id": UID, "id": "s-real", "name": "Real Supplier"},
    ])
    await db.vehicles.insert_many([
        {"user_id": UID, "id": "v-fix", "vehicle_number": "AA1FIX", "supplier_id": None},
        {"user_id": UID, "id": "v-real", "vehicle_number": "KA01AB1234", "supplier_id": ""},
    ])
    await db.user_sessions.insert_many([
        {"session_token": LEGACY, "user_id": UID, "created_at": "2026-01-01"},
        {"session_token": "real-session", "user_id": UID, "created_at": "2026-01-01"},
    ])
    await db.trips.insert_one({"user_id": UID, "id": "t1", "supplier_id": None})
    await db.companies.insert_one({"id": "co1", "user_id": UID})
    CALLS.clear()

    await server.app.router.startup()
    deadline = time.monotonic() + 120
    while not server._background_migrations_ran and time.monotonic() < deadline:
        await asyncio.sleep(0.1)

    idx = {}
    for coll in ("users", "user_sessions", "credit_debit_notes", "invoices", "expenses", "idempotency_keys"):
        idx[coll] = sorted((await db[coll].index_information()).keys())
    out = {
        "background_ran": server._background_migrations_ran,
        "delete_many": CALLS,
        "customers": sorted([d["id"] async for d in db.customers.find({}, {"id": 1})]),
        "suppliers": sorted([d["id"] async for d in db.suppliers.find({}, {"id": 1})]),
        "vehicles": sorted([d["id"] async for d in db.vehicles.find({}, {"id": 1})]),
        "sessions": sorted([d["session_token"] async for d in db.user_sessions.find({}, {"session_token": 1})]),
        "trip_supplier_id": (await db.trips.find_one({"id": "t1"}))["supplier_id"],
        "company_cn_prefix": (await db.companies.find_one({"id": "co1"})).get("credit_note_prefix"),
        "indexes": idx,
    }
    await server.client.drop_database(os.environ["DB_NAME"])
    await server.app.router.shutdown()
    print("RESULT " + json.dumps(out))

asyncio.run(main())
'''

DESTRUCTIVE = {"customers", "suppliers", "vehicles", "user_sessions"}


def _mongo_available() -> bool:
    try:
        from pymongo import MongoClient
        MongoClient(MONGO_URL, serverSelectionTimeoutMS=2000).admin.command("ping")
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _mongo_available(), reason="MongoDB not reachable")


def _boot(preview_value):
    env = {k: v for k, v in os.environ.items()
           if k not in ("IS_PREVIEW_ENV", "DB_NAME", "NODE_ROUTING_MODE")}
    env.update({
        "MONGO_URL": MONGO_URL,
        "DB_NAME": "trk_startup_guard_" + uuid.uuid4().hex[:12],   # throwaway
        "DISABLE_SCHEDULER": "1",
        "EMERGENT_LLM_KEY": "",                                    # no storage network call
        "REGRESSION_GUARD_PERIODIC": "0",
        "PYTHONIOENCODING": "utf-8",
    })
    if preview_value is not None:
        env["IS_PREVIEW_ENV"] = preview_value
    proc = subprocess.run([sys.executable, "-c", _DRIVER], cwd=str(BACKEND), env=env,
                          capture_output=True, text=True, encoding="utf-8", timeout=300)
    line = next((ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT ")), None)
    assert proc.returncode == 0 and line, f"startup failed:\n{proc.stdout[-3000:]}\n{proc.stderr[-3000:]}"
    return json.loads(line[len("RESULT "):])


def _assert_normal_startup(r):
    assert r["background_ran"] is True
    # non-destructive startup work unchanged in every mode
    assert r["trip_supplier_id"] == ""                       # Iter49 null-coerce backfill
    assert r["company_cn_prefix"] == "CN"                    # Iter132a CN/DN backfill
    assert "uniq_user_email" in r["indexes"]["users"]        # auth-index housekeeping
    assert "uniq_session_token" in r["indexes"]["user_sessions"]
    assert "uniq_user_invoice_number" in r["indexes"]["invoices"]
    assert "expenses_source_key_uniq" in r["indexes"]["expenses"]
    assert len(r["indexes"]["credit_debit_notes"]) >= 4
    assert len(r["indexes"]["idempotency_keys"]) >= 2


@pytest.mark.parametrize("preview_value", [None, "0", "", "true", "yes", " 1"])
def test_production_performs_zero_destructive_startup_deletes(preview_value):
    r = _boot(preview_value)
    assert DESTRUCTIVE.isdisjoint(r["delete_many"]), r["delete_many"]
    assert r["customers"] == ["c-fix", "c-real"]
    assert r["suppliers"] == ["s-fix", "s-real"]
    assert r["vehicles"] == ["v-fix", "v-real"]
    assert r["sessions"] == ["real-session", "test_session_" + "bitumen_2026"]
    _assert_normal_startup(r)


def test_preview_keeps_existing_cleanup_behaviour():
    r = _boot("1")
    assert sorted(r["delete_many"]) == ["customers", "suppliers", "user_sessions", "vehicles"]
    assert r["customers"] == ["c-real"]
    assert r["suppliers"] == ["s-real"]
    assert r["vehicles"] == ["v-real"]
    assert r["sessions"] == ["real-session"]
    _assert_normal_startup(r)


def test_guard_uses_the_existing_preview_signal():
    src = (BACKEND / "server.py").read_text(encoding="utf-8")
    assert 'return os.environ.get("IS_PREVIEW_ENV") == "1"' in src
    assert "NODE_ENV" not in src
    assert src.count("if not _is_preview_env():") == 2
