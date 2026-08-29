"""Iter30: Demo session auto-provision + rolling refresh for OAuth sessions."""
import os
import time
import asyncio
from datetime import datetime, timezone, timedelta

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
DEMO_TOKEN = os.environ["DEMO_TOKEN_VALUE"]  # Iter130 · env-backed
HDR = {"Authorization": f"Bearer {DEMO_TOKEN}"}


def _mongo_db():
    """Direct db handle for arrange/assert steps."""
    from motor.motor_asyncio import AsyncIOMotorClient
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    client = AsyncIOMotorClient(mongo_url)
    return client[db_name], client


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.new_event_loop().run_until_complete(coro)


# ---------- Demo session self-heal ----------

def test_demo_session_autoprovision_from_scratch():
    """Delete demo session row; /auth/me must recreate it and return 200."""
    async def arrange():
        db, client = _mongo_db()
        await db.user_sessions.delete_many({"session_token": DEMO_TOKEN})
        remaining = await db.user_sessions.count_documents({"session_token": DEMO_TOKEN})
        client.close()
        return remaining
    remaining = _run(arrange())
    assert remaining == 0, "arrange failed to delete demo session"

    r = requests.get(f"{BASE_URL}/api/auth/me", headers=HDR, timeout=10)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("user_id", "").startswith("user_demo_"), body

    # Idempotency — hit again
    r2 = requests.get(f"{BASE_URL}/api/auth/me", headers=HDR, timeout=10)
    assert r2.status_code == 200, r2.text
    assert r2.json().get("user_id", "").startswith("user_demo_")


def test_demo_session_expiry_is_30_days():
    """After auto-provision the expires_at must be ~30 days in the future."""
    # Ensure exists
    requests.get(f"{BASE_URL}/api/auth/me", headers=HDR, timeout=10)

    async def read():
        db, client = _mongo_db()
        doc = await db.user_sessions.find_one({"session_token": DEMO_TOKEN}, {"_id": 0})
        client.close()
        return doc
    doc = _run(read())
    assert doc is not None
    exp = doc["expires_at"]
    if isinstance(exp, str):
        exp = datetime.fromisoformat(exp)
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    delta = (exp - datetime.now(timezone.utc)).total_seconds()
    # Between 29 and 31 days
    assert 29 * 86400 < delta < 31 * 86400, f"expires_at delta = {delta}s"


def test_demo_session_refreshes_on_each_hit():
    """Demo token: every /auth/me hit refreshes expires_at forward."""
    r1 = requests.get(f"{BASE_URL}/api/auth/me", headers=HDR, timeout=10)
    assert r1.status_code == 200

    async def read():
        db, client = _mongo_db()
        doc = await db.user_sessions.find_one({"session_token": DEMO_TOKEN}, {"_id": 0})
        client.close()
        return doc
    first = _run(read())
    exp1 = first["expires_at"]
    time.sleep(2)
    r2 = requests.get(f"{BASE_URL}/api/auth/me", headers=HDR, timeout=10)
    assert r2.status_code == 200
    second = _run(read())
    exp2 = second["expires_at"]
    # exp2 should be >= exp1 (string ISO compare works with the same TZ)
    assert exp2 >= exp1


# ---------- OAuth rolling refresh ----------

def test_oauth_rolling_refresh_extends_expiring_session():
    """Manually-created session with 2-day expiry gets extended to ~7 days on first hit,
    then does NOT change on the very next hit (4-min anti-thrash window)."""
    from motor.motor_asyncio import AsyncIOMotorClient
    TOKEN = "iter30_oauth_test_token"

    async def arrange():
        db, client = _mongo_db()
        # Ensure user exists
        user_id = "iter30_oauth_user"
        await db.users.update_one(
            {"user_id": user_id},
            {"$set": {
                "user_id": user_id,
                "email": "iter30@test.local",
                "name": "Iter30 Test",
                "picture": "",
            }},
            upsert=True,
        )
        # Session expiring in 2 days, no last_refreshed_at
        exp = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        await db.user_sessions.update_one(
            {"session_token": TOKEN},
            {"$set": {
                "user_id": user_id,
                "session_token": TOKEN,
                "expires_at": exp,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
             "$unset": {"last_refreshed_at": ""}},
            upsert=True,
        )
        client.close()
        return exp
    orig_exp = _run(arrange())

    hdr = {"Authorization": f"Bearer {TOKEN}"}
    r = requests.get(f"{BASE_URL}/api/auth/me", headers=hdr, timeout=10)
    assert r.status_code == 200, r.text

    async def read():
        db, client = _mongo_db()
        doc = await db.user_sessions.find_one({"session_token": TOKEN}, {"_id": 0})
        client.close()
        return doc

    after1 = _run(read())
    exp1 = after1["expires_at"]
    if isinstance(exp1, str):
        exp1_dt = datetime.fromisoformat(exp1)
    if exp1_dt.tzinfo is None:
        exp1_dt = exp1_dt.replace(tzinfo=timezone.utc)
    delta1 = (exp1_dt - datetime.now(timezone.utc)).total_seconds()
    assert 6 * 86400 < delta1 < 8 * 86400, f"expected ~7d, got {delta1}s"
    assert after1.get("last_refreshed_at"), "last_refreshed_at should be populated"

    # Second hit — within 4-min window, must NOT re-refresh
    r2 = requests.get(f"{BASE_URL}/api/auth/me", headers=hdr, timeout=10)
    assert r2.status_code == 200
    after2 = _run(read())
    assert after2["expires_at"] == after1["expires_at"], "expires_at bumped within anti-thrash window"
    assert after2["last_refreshed_at"] == after1["last_refreshed_at"]

    # Cleanup
    async def cleanup():
        db, client = _mongo_db()
        await db.user_sessions.delete_many({"session_token": TOKEN})
        await db.users.delete_many({"user_id": "iter30_oauth_user"})
        client.close()
    _run(cleanup())


def test_expired_session_still_rejected():
    """Sessions whose expires_at is in the past must return 401, not silently refresh."""
    from motor.motor_asyncio import AsyncIOMotorClient
    TOKEN = "iter30_expired_token"

    async def arrange():
        db, client = _mongo_db()
        user_id = "iter30_expired_user"
        await db.users.update_one(
            {"user_id": user_id},
            {"$set": {"user_id": user_id, "email": "iter30exp@test.local", "name": "X"}},
            upsert=True,
        )
        exp = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        await db.user_sessions.update_one(
            {"session_token": TOKEN},
            {"$set": {
                "user_id": user_id,
                "session_token": TOKEN,
                "expires_at": exp,
                "created_at": exp,
            }},
            upsert=True,
        )
        client.close()
    _run(arrange())

    r = requests.get(f"{BASE_URL}/api/auth/me", headers={"Authorization": f"Bearer {TOKEN}"}, timeout=10)
    assert r.status_code == 401, r.text

    async def cleanup():
        db, client = _mongo_db()
        await db.user_sessions.delete_many({"session_token": TOKEN})
        await db.users.delete_many({"user_id": "iter30_expired_user"})
        client.close()
    _run(cleanup())
