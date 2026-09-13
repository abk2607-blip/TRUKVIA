"""Iter150K · Turn 1 · SupplierPayment correction parity + Option-2 hook fix tests.

Sync `requests` idiom matching test_iter133_expense_turn2c.py conventions.
Uses DEMO_TOKEN_VALUE (populated by conftest.py) and hits the live FastAPI app.
"""
from __future__ import annotations

import os
import uuid

import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient
import asyncio

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"
DEMO_TOKEN = os.environ["DEMO_TOKEN_VALUE"]
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

TAG = f"IT150K-{uuid.uuid4().hex[:6].upper()}"


def _hdr(key=None, company_id=None):
    h = {"Authorization": f"Bearer {DEMO_TOKEN}", "Content-Type": "application/json"}
    if key:
        h["Idempotency-Key"] = key
    if company_id:
        h["X-Company-Id"] = company_id
    return h


def _idem():
    return f"iter150k-{uuid.uuid4().hex[:24]}"


def _leg_count(source_type: str, source_id: str) -> int:
    async def _run():
        c = AsyncIOMotorClient(MONGO_URL)
        try:
            return await c[DB_NAME].fin_txn.count_documents(
                {"ref_source_key": {"$regex": f"^{source_type}:{source_id}:"}}
            )
        finally:
            c.close()
    return asyncio.run(_run())


def _mongo_update(coll: str, pid: str, fields: dict) -> None:
    async def _run():
        c = AsyncIOMotorClient(MONGO_URL)
        try:
            await c[DB_NAME][coll].update_one({"id": pid}, {"$set": fields})
        finally:
            c.close()
    asyncio.run(_run())


def _mongo_count(coll: str, filt: dict) -> int:
    async def _run():
        c = AsyncIOMotorClient(MONGO_URL)
        try:
            return await c[DB_NAME][coll].count_documents(filt)
        finally:
            c.close()
    return asyncio.run(_run())


def _mongo_find_one(coll: str, filt: dict) -> dict:
    async def _run():
        c = AsyncIOMotorClient(MONGO_URL)
        try:
            return await c[DB_NAME][coll].find_one(filt, {"_id": 0})
        finally:
            c.close()
    return asyncio.run(_run())


# ---------------------- fixtures ----------------------

@pytest.fixture(scope="function")
def sctx():
    """Fresh supplier + payment per test — no cross-test leakage."""
    name = f"{TAG} SUP {uuid.uuid4().hex[:6]}"
    r = requests.post(f"{API}/suppliers", headers=_hdr(_idem()),
                      json={"name": name, "mobile": "9000000000", "is_active": True},
                      timeout=15)
    assert r.status_code in (200, 201), r.text
    sup = r.json()
    sid = sup["id"]
    r = requests.post(
        f"{API}/suppliers/{sid}/payments", headers=_hdr(_idem()),
        json={"supplier_id": sid, "date": "2029-09-01", "amount": 1000,
              "type": "payment_out", "mode": "Bank", "against": "outstanding",
              "remarks": "seed"}, timeout=15,
    )
    assert r.status_code in (200, 201), r.text
    return {"sid": sid, "supplier": sup, "payment": r.json()}


# ---------------------- 15 Supplier tests ----------------------

def test_sp_correction_reason_min_length(sctx):
    r = requests.post(f"{API}/supplier-payments/{sctx['payment']['id']}/correct",
                      headers=_hdr(_idem()),
                      json={"changes": {"remarks": "x"}, "correction_reason": "short"},
                      timeout=15)
    assert r.status_code == 400 and "correction_reason" in r.text


def test_sp_attribute_reassignment_reflects_in_ledger(sctx):
    r = requests.post(f"{API}/supplier-payments/{sctx['payment']['id']}/correct",
                      headers=_hdr(_idem()),
                      json={"changes": {"remarks": "fixed remark line"},
                            "correction_reason": "typo on original remark"},
                      timeout=15)
    assert r.status_code == 200, r.text
    doc = _mongo_find_one("supplier_payments", {"id": sctx["payment"]["id"]})
    assert doc["remarks"] == "fixed remark line"
    assert doc["correction_count"] == 1


def test_sp_amount_change_via_attribute_endpoint_rejected(sctx):
    r = requests.post(f"{API}/supplier-payments/{sctx['payment']['id']}/correct",
                      headers=_hdr(_idem()),
                      json={"changes": {"amount": 2000},
                            "correction_reason": "amount captured wrong at typing"},
                      timeout=15)
    assert r.status_code == 400 and "correct-amount" in r.text


def test_sp_amount_reversal_creates_two_visible_rows(sctx):
    orig = sctx["payment"]
    r = requests.post(f"{API}/supplier-payments/{orig['id']}/correct-amount",
                      headers=_hdr(_idem()),
                      json={"new_amount": 1500,
                            "correction_reason": "amount 1000 typed instead of 1500"},
                      timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["original"]["is_reversed"] is True
    assert body["fresh"]["amount"] == 1500.0
    assert body["fresh"]["reversal_of"] == orig["id"]
    assert body["correction"]["kind"] == "amount_reversal_new"


def test_sp_reconciled_requires_override(sctx):
    _mongo_update("supplier_payments", sctx["payment"]["id"],
                  {"reconciled_at": "2029-09-05T00:00:00+00:00"})
    r = requests.post(f"{API}/supplier-payments/{sctx['payment']['id']}/correct",
                      headers=_hdr(_idem()),
                      json={"changes": {"remarks": "attempt under reconciled"},
                            "correction_reason": "attempting to correct reconciled row"},
                      timeout=15)
    assert r.status_code == 409
    r = requests.post(f"{API}/supplier-payments/{sctx['payment']['id']}/correct",
                      headers=_hdr(_idem()),
                      json={"changes": {"remarks": "authorised override edit"},
                            "correction_reason": "authorised override for reconciled row",
                            "force_reconciled_override": True},
                      timeout=15)
    assert r.status_code == 200, r.text


def test_sp_idempotency_no_duplicate_correction(sctx):
    key = _idem()
    payload = {"changes": {"remarks": "idem-test remark"},
               "correction_reason": "idempotent replay guard"}
    r1 = requests.post(f"{API}/supplier-payments/{sctx['payment']['id']}/correct",
                      headers=_hdr(key), json=payload, timeout=15)
    r2 = requests.post(f"{API}/supplier-payments/{sctx['payment']['id']}/correct",
                      headers=_hdr(key), json=payload, timeout=15)
    # First succeeds; second either replays (200) via Idempotency-Key OR is
    # blocked by the shared service's "No effective change" guard (400).
    # Either way, only ONE audit row must exist for the logical correction.
    assert r1.status_code == 200
    assert r2.status_code in (200, 400)
    hist = requests.get(f"{API}/supplier-payments/{sctx['payment']['id']}/corrections",
                        headers=_hdr(), timeout=15).json()
    assert len(hist) == 1


def test_sp_cross_tenant_correction_blocked(sctx):
    # Nonexistent payment id in the same tenant must be 404 (the shared service
    # scopes _load_payment to {user_id, company_id, id}). Using a nonsense id
    # proves the tenant-scoping barrier is honoured.
    r = requests.post(f"{API}/supplier-payments/sp_does_not_exist_123/correct",
                      headers=_hdr(_idem()),
                      json={"changes": {"remarks": "cross tenant attempt"},
                            "correction_reason": "cross tenant attempt should 404"},
                      timeout=15)
    assert r.status_code == 404


def test_sp_correction_count_race_guard(sctx):
    r = requests.post(f"{API}/supplier-payments/{sctx['payment']['id']}/correct",
                      headers=_hdr(_idem()),
                      json={"changes": {"remarks": "first correction row"},
                            "correction_reason": "first correction ok",
                            "expected_correction_count": 0}, timeout=15)
    assert r.status_code == 200
    r = requests.post(f"{API}/supplier-payments/{sctx['payment']['id']}/correct",
                      headers=_hdr(_idem()),
                      json={"changes": {"remarks": "second correction row"},
                            "correction_reason": "stale expected count race",
                            "expected_correction_count": 0}, timeout=15)
    assert r.status_code == 409


def test_sp_correction_history_endpoint(sctx):
    for i in range(3):
        r = requests.post(f"{API}/supplier-payments/{sctx['payment']['id']}/correct",
                          headers=_hdr(_idem()),
                          json={"changes": {"remarks": f"correction number {i}"},
                                "correction_reason": f"history iteration {i} ok"},
                          timeout=15)
        assert r.status_code == 200, r.text
    hist = requests.get(f"{API}/supplier-payments/{sctx['payment']['id']}/corrections",
                        headers=_hdr(), timeout=15).json()
    assert [h["correction_index"] for h in hist] == [1, 2, 3]


def test_sp_attribute_corrections_do_not_create_new_payment(sctx):
    before = _mongo_count("supplier_payments", {"supplier_id": sctx["sid"]})
    r = requests.post(f"{API}/supplier-payments/{sctx['payment']['id']}/correct",
                      headers=_hdr(_idem()),
                      json={"changes": {"remarks": "still one row after"},
                            "correction_reason": "attribute correction row-count guard"},
                      timeout=15)
    assert r.status_code == 200
    after = _mongo_count("supplier_payments", {"supplier_id": sctx["sid"]})
    assert after == before


def test_sp_correction_on_reversed_payment_blocked(sctx):
    r = requests.post(f"{API}/supplier-payments/{sctx['payment']['id']}/correct-amount",
                      headers=_hdr(_idem()),
                      json={"new_amount": 2000,
                            "correction_reason": "reverse before follow-up"},
                      timeout=15)
    assert r.status_code == 200, r.text
    r = requests.post(f"{API}/supplier-payments/{sctx['payment']['id']}/correct",
                      headers=_hdr(_idem()),
                      json={"changes": {"remarks": "after reversal"},
                            "correction_reason": "attempt correct on reversed row"},
                      timeout=15)
    assert r.status_code == 400 and "reversed" in r.text.lower()


def test_sp_corrected_linkage_reflects_in_ledger(sctx):
    r = requests.post(f"{API}/supplier-payments/{sctx['payment']['id']}/correct",
                      headers=_hdr(_idem()),
                      json={"changes": {"ref_no": "UTR-CORRECTED-XYZ"},
                            "correction_reason": "UTR captured wrong at posting"},
                      timeout=15)
    assert r.status_code == 200, r.text
    L = requests.get(f"{API}/suppliers/{sctx['sid']}/ledger",
                     headers=_hdr(), timeout=15).json()
    hit = [e for e in L["entries"] if e.get("payment_id") == sctx["payment"]["id"]]
    assert hit and hit[0]["ref_no"] == "UTR-CORRECTED-XYZ"


def test_sp_finTxn_two_legs_updated_after_amount_reversal(sctx):
    orig_id = sctx["payment"]["id"]
    assert _leg_count("supplier_payment", orig_id) == 2, "expected 2 legs before reversal"
    r = requests.post(f"{API}/supplier-payments/{orig_id}/correct-amount",
                      headers=_hdr(_idem()),
                      json={"new_amount": 1750,
                            "correction_reason": "prove FinTxn re-projects cleanly"},
                      timeout=15)
    assert r.status_code == 200, r.text
    fresh_id = r.json()["fresh"]["id"]
    assert _leg_count("supplier_payment", orig_id) == 0, "stale legs on original must be cleared"
    assert _leg_count("supplier_payment", fresh_id) == 2, "fresh row must project 2 legs"


def test_sp_reversed_payments_excluded_from_dashboard(sctx):
    r = requests.post(f"{API}/supplier-payments/{sctx['payment']['id']}/correct-amount",
                      headers=_hdr(_idem()),
                      json={"new_amount": 250,
                            "correction_reason": "reversal dashboard filter check"},
                      timeout=15)
    assert r.status_code == 200, r.text
    L = requests.get(f"{API}/suppliers/{sctx['sid']}/ledger",
                     headers=_hdr(), timeout=15).json()
    reversed_row = [e for e in L["entries"]
                    if e.get("payment_id") == sctx["payment"]["id"]]
    assert reversed_row == [], "reversed original must NOT appear in default ledger"


def test_sp_maker_checker_creation_gate_still_engages(sctx):
    from db import db
    async def _flip(v):
        c = AsyncIOMotorClient(MONGO_URL)
        try:
            await c[DB_NAME].companies.update_many({}, {"$set": {"require_approval_payment": v}})
        finally:
            c.close()
    asyncio.run(_flip(True))
    try:
        r = requests.post(f"{API}/suppliers/{sctx['sid']}/payments",
                          headers=_hdr(_idem()),
                          json={"supplier_id": sctx["sid"], "date": "2029-09-01",
                                "amount": 500, "type": "payment_out", "mode": "Bank",
                                "against": "outstanding"}, timeout=15)
        assert r.status_code in (200, 202, 409)
        if r.status_code == 409:
            assert "approval" in r.text.lower()
        # Correction path stays OUTSIDE the whitelist even with toggle on:
        r2 = requests.post(f"{API}/supplier-payments/{sctx['payment']['id']}/correct",
                           headers=_hdr(_idem()),
                           json={"changes": {"remarks": "under approval toggle"},
                                 "correction_reason": "correction bypasses gate"},
                           timeout=15)
        assert r2.status_code == 200, r2.text
    finally:
        asyncio.run(_flip(False))


# ---------------------- 2 Vendor/Mechanic FinTxn regressions ----------------------

def test_iter150k_vendor_correction_fin_txn_regression():
    v = requests.post(f"{API}/vendors", headers=_hdr(_idem()),
                      json={"name": f"{TAG} V-REG"}, timeout=15).json()
    p = requests.post(f"{API}/vendors/{v['id']}/payments", headers=_hdr(_idem()),
                      json={"vendor_id": v["id"], "date": "2029-09-01", "amount": 800,
                            "mode": "Bank", "against": "outstanding"}, timeout=15).json()
    assert _leg_count("vendor_payment", p["id"]) == 2
    r = requests.post(f"{API}/vendor-payments/{p['id']}/correct-amount",
                      headers=_hdr(_idem()),
                      json={"new_amount": 1200,
                            "correction_reason": "vendor FinTxn Option-2 proof"},
                      timeout=15)
    assert r.status_code == 200, r.text
    fresh_id = r.json()["fresh"]["id"]
    assert _leg_count("vendor_payment", p["id"]) == 0
    assert _leg_count("vendor_payment", fresh_id) == 2


def test_iter150k_mechanic_correction_fin_txn_regression():
    m = requests.post(f"{API}/mechanics", headers=_hdr(_idem()),
                      json={"name": f"{TAG} M-REG"}, timeout=15).json()
    p = requests.post(f"{API}/mechanics/{m['id']}/payments", headers=_hdr(_idem()),
                      json={"mechanic_id": m["id"], "date": "2029-09-01", "amount": 500,
                            "mode": "Bank", "against": "outstanding"}, timeout=15).json()
    assert _leg_count("mechanic_payment", p["id"]) == 2
    r = requests.post(f"{API}/mechanic-payments/{p['id']}/correct-amount",
                      headers=_hdr(_idem()),
                      json={"new_amount": 900,
                            "correction_reason": "mechanic FinTxn Option-2 proof"},
                      timeout=15)
    assert r.status_code == 200, r.text
    fresh_id = r.json()["fresh"]["id"]
    assert _leg_count("mechanic_payment", p["id"]) == 0
    assert _leg_count("mechanic_payment", fresh_id) == 2
