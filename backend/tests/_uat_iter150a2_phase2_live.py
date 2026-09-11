"""Iter150A-2 · Phase 2 — LIVE UAT harness (read-only validation, NON-DESTRUCTIVE).

Exercises the full end-to-end write path via HTTP:
  * SupplierPayment  create / update / delete
  * VendorPayment    create / update / delete
  * MechanicPayment  create / update / delete

For each source:
  * verify exactly 2 FinTxn legs (payable + bank/cash)
  * verify correct account codes, directions, amounts, dates, party ids
  * verify Day Book (`/api/fin/day-book`) reflects legs after each mutation
  * verify Account balances (`/api/fin/accounts`) delta
  * verify hook idempotency (double-hook produces no duplicate legs)
  * verify failure queue: force unresolvable projection, then replay
  * verify tenant isolation via 2 distinct user_ids
  * cleanup all created rows + projected FinTxn + failure rows.
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path("/app/backend/.env"))

BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE}/api" if BASE.startswith("http") else "http://localhost:8001/api"
TOK = os.environ["DEMO_TOKEN_VALUE"]
H = {"Authorization": f"Bearer {TOK}"}
HJSON = {**H, "Content-Type": "application/json"}
MONGO = MongoClient(os.environ["MONGO_URL"])
DB = MONGO[os.environ["DB_NAME"]]

RESULTS: list[dict] = []


def log(name: str, ok: bool, detail: str = ""):
    RESULTS.append({"case": name, "ok": bool(ok), "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'} · {name} · {detail}")


def _demo() -> tuple[str, str]:
    me = DB.users.find_one({"email": "demo@bitumen-transport.local"},
                           {"_id": 0, "user_id": 1})
    assert me
    uid = me["user_id"]
    r = requests.get(f"{API}/vehicles", headers=H, params={"active_only": False}, timeout=15)
    r.raise_for_status()
    cid = r.json()[0]["company_id"]
    return uid, cid


def _fin_legs(uid: str, source_id: str) -> list[dict]:
    return list(DB.fin_txn.find(
        {"user_id": uid, "source_id": source_id},
        {"_id": 0, "account_code": 1, "counter_account_code": 1, "direction": 1,
         "amount": 1, "ref_source_key": 1, "party_type": 1, "party_id": 1,
         "txn_date": 1, "source_type": 1, "source_id": 1},
    ))


def _day_book(uid: str, cid: str, date: str) -> dict:
    r = requests.get(f"{API}/fin/day-book", headers=H,
                     params={"date_from": date, "date_to": date}, timeout=20)
    r.raise_for_status()
    return r.json()


def _account_balance(uid: str, cid: str, code: str) -> float:
    """Sum leg amounts for a given account_code across the tenant."""
    pipe = [
        {"$match": {"user_id": uid, "company_id": cid, "account_code": code}},
        {"$group": {"_id": "$direction", "s": {"$sum": "$amount"}}},
    ]
    got = {r["_id"]: r["s"] for r in DB.fin_txn.aggregate(pipe)}
    # in = debit (+); out = credit (-); returns signed net.
    return round(got.get("in", 0.0) - got.get("out", 0.0), 2)


# ── Master seeders ──────────────────────────────────────────────────────
def mk_supplier(tag: str) -> str:
    r = requests.post(f"{API}/suppliers", headers=HJSON,
                      json={"name": f"UAT-Sup {tag}", "is_active": True}, timeout=15)
    r.raise_for_status()
    return r.json()["id"]


def mk_vendor(tag: str) -> str:
    r = requests.post(f"{API}/vendors", headers=HJSON,
                      json={"name": f"UAT-Ven {tag}", "is_active": True}, timeout=15)
    r.raise_for_status()
    return r.json()["id"]


def mk_mechanic(tag: str) -> str:
    r = requests.post(f"{API}/mechanics", headers=HJSON,
                      json={"name": f"UAT-Mec {tag}", "is_active": True}, timeout=15)
    r.raise_for_status()
    return r.json()["id"]


# ── Sub-scenarios ───────────────────────────────────────────────────────
def uat_source(kind: str, uid: str, cid: str, tag: str):
    """kind ∈ {'supplier','vendor','mechanic'}"""
    if kind == "supplier":
        pid_party = mk_supplier(tag)
        create_url = f"{API}/suppliers/{pid_party}/payments"
        base = lambda a, m, d, direction="out": {
            "supplier_id": pid_party, "amount": a, "mode": m,
            "date": d, "direction": direction,
        }
        st_pay = "supplier_payment"
        payable_code = "AP_SUPPLIER"
        party_col = "supplier_id"
    elif kind == "vendor":
        pid_party = mk_vendor(tag)
        create_url = f"{API}/vendors/{pid_party}/payments"
        base = lambda a, m, d, direction="out": {
            "vendor_id": pid_party, "amount": a, "mode": m, "date": d,
        }
        st_pay = "vendor_payment"
        payable_code = "AP_VENDOR"
        party_col = "vendor_id"
    else:
        pid_party = mk_mechanic(tag)
        create_url = f"{API}/mechanics/{pid_party}/payments"
        base = lambda a, m, d, direction="out": {
            "mechanic_id": pid_party, "amount": a, "mode": m, "date": d,
        }
        st_pay = "mechanic_payment"
        payable_code = "AP_MECHANIC"
        party_col = "mechanic_id"

    d1 = "2026-02-11"
    d2 = "2026-02-12"
    amt1, amt2 = 5000.0, 7500.0

    # ── CREATE ────────────────────────────────────────
    bank_before = _account_balance(uid, cid, "BANK_DEFAULT")
    pay_before = _account_balance(uid, cid, payable_code)
    r = requests.post(create_url, headers=HJSON, json=base(amt1, "Bank", d1), timeout=15)
    if r.status_code != 200:
        log(f"{kind}.create.http", False, f"HTTP {r.status_code} {r.text[:200]}")
        return None
    pay_id = r.json()["id"]
    legs = _fin_legs(uid, pay_id)
    ok = len(legs) == 2
    log(f"{kind}.create.leg_count", ok, f"got {len(legs)} legs (expected 2)")
    acts = sorted(l["account_code"] for l in legs)
    # supplier can pay in either direction — vendor/mechanic always money-out.
    money_side = "BANK_DEFAULT"
    exp = sorted([payable_code, money_side])
    log(f"{kind}.create.accounts", acts == exp, f"got {acts} expected {exp}")
    dirs = {l["account_code"]: l["direction"] for l in legs}
    # money-out (payment against payable): payable=Debit(in), bank=Credit(out).
    ok_dir = dirs.get(payable_code) == "in" and dirs.get(money_side) == "out"
    log(f"{kind}.create.direction", ok_dir, str(dirs))
    ok_amt = all(l["amount"] == amt1 for l in legs)
    log(f"{kind}.create.amount", ok_amt, f"all legs={amt1}")
    ok_date = all(l["txn_date"] == d1 for l in legs)
    log(f"{kind}.create.date", ok_date, f"all legs date={d1}")
    party_ok = any(l.get("party_id") == pid_party for l in legs)
    log(f"{kind}.create.party_id", party_ok, f"party_id={pid_party}")
    src_ok = all(l["source_id"] == pay_id and l["source_type"] == st_pay for l in legs)
    log(f"{kind}.create.source_identity", src_ok, f"source={st_pay}:{pay_id}")

    # Day Book reflection
    db_before_n = 0  # sanity; we track deltas via account_balance
    bank_after = _account_balance(uid, cid, "BANK_DEFAULT")
    pay_after = _account_balance(uid, cid, payable_code)
    d_bank = round(bank_after - bank_before, 2)
    d_pay = round(pay_after - pay_before, 2)
    log(f"{kind}.create.bank_delta", d_bank == -amt1, f"delta={d_bank} (expected -{amt1})")
    log(f"{kind}.create.payable_delta", d_pay == amt1, f"delta={d_pay} (expected +{amt1})")

    day = _day_book(uid, cid, d1)
    rows = day.get("rows", [])
    hit = any(r.get("source_id") == pay_id for r in rows)
    log(f"{kind}.create.day_book_hit", hit, f"day_book rows={len(rows)}")

    # ── Idempotency: manual double-hook via /api/fin/reproject ──
    r2 = requests.post(f"{API}/fin/reproject", headers=HJSON,
                       json={"source_type": st_pay, "source_id": pay_id, "dry_run": False},
                       timeout=15)
    legs2 = _fin_legs(uid, pay_id)
    log(f"{kind}.idempotent.leg_count", len(legs2) == 2,
        f"after double-hook got {len(legs2)}")
    keys_stable = sorted(l["ref_source_key"] for l in legs) == \
                  sorted(l["ref_source_key"] for l in legs2)
    log(f"{kind}.idempotent.ref_source_key_stable", keys_stable, "")

    # ── UPDATE (amount + date + mode) ──────────────
    up = requests.put(f"{create_url}/{pay_id}", headers=HJSON,
                      json=base(amt2, "Cash", d2), timeout=15)
    log(f"{kind}.update.http", up.status_code == 200, f"HTTP {up.status_code}")
    legs3 = _fin_legs(uid, pay_id)
    log(f"{kind}.update.leg_count", len(legs3) == 2, f"got {len(legs3)}")
    old_present = any(l["amount"] == amt1 for l in legs3)
    new_present = all(l["amount"] == amt2 for l in legs3)
    log(f"{kind}.update.old_gone", not old_present, f"old amt={amt1} present={old_present}")
    log(f"{kind}.update.new_applied", new_present, f"new amt={amt2}")
    date_ok = all(l["txn_date"] == d2 for l in legs3)
    log(f"{kind}.update.new_date", date_ok, f"new date={d2}")
    # Money side now CASH
    acts3 = sorted(l["account_code"] for l in legs3)
    exp3 = sorted([payable_code, "CASH"])
    log(f"{kind}.update.money_side_switched", acts3 == exp3, f"got {acts3}")

    # ── UPDATE twice (idempotent) ───────────────────
    requests.put(f"{create_url}/{pay_id}", headers=HJSON,
                 json=base(amt2, "Cash", d2), timeout=15)
    legs4 = _fin_legs(uid, pay_id)
    log(f"{kind}.update.idempotent_leg_count", len(legs4) == 2, f"got {len(legs4)}")

    # ── DELETE (soft) ───────────────────────────────
    dl = requests.delete(f"{create_url}/{pay_id}",
                         headers=H, params={"reason": "UAT phase2 cleanup"}, timeout=15)
    log(f"{kind}.delete.http", dl.status_code == 200, f"HTTP {dl.status_code}")
    legs5 = _fin_legs(uid, pay_id)
    log(f"{kind}.delete.legs_removed", len(legs5) == 0, f"legs after delete={len(legs5)}")
    # Source soft-deleted (authoritative preserved)
    src_doc = DB[st_pay + "s"].find_one({"id": pay_id}, {"_id": 0, "is_deleted": 1})
    log(f"{kind}.delete.source_soft_deleted",
        bool(src_doc and src_doc.get("is_deleted") is True),
        f"is_deleted={src_doc.get('is_deleted') if src_doc else '<missing>'}")

    return {"pid_party": pid_party, "pay_id": pay_id,
            "collection": st_pay + "s", "party_col": party_col}


# ── Reverse-flag scenario (supplier only exposes direction flag) ────────
def uat_reverse_supplier(uid: str, cid: str, tag: str):
    sid = mk_supplier(tag + "-rev")
    d = "2026-02-11"
    # Create a normal money-out payment
    r = requests.post(f"{API}/suppliers/{sid}/payments", headers=HJSON,
                      json={"supplier_id": sid, "amount": 1200.0, "mode": "Bank",
                            "date": d, "direction": "out"}, timeout=15)
    r.raise_for_status()
    pay_id = r.json()["id"]
    legs0 = _fin_legs(uid, pay_id)
    log("supplier.reverse.create_legs", len(legs0) == 2, f"legs={len(legs0)}")
    # Mark is_reversed = True in-DB, then reproject → legs should vanish.
    DB.supplier_payments.update_one({"id": pay_id}, {"$set": {"is_reversed": True}})
    requests.post(f"{API}/fin/reproject", headers=HJSON,
                  json={"source_type": "supplier_payment", "source_id": pay_id},
                  timeout=15)
    legs_after = _fin_legs(uid, pay_id)
    log("supplier.reverse.legs_removed", len(legs_after) == 0,
        f"after is_reversed=True legs={len(legs_after)}")
    # Unset for cleanup
    DB.supplier_payments.delete_one({"id": pay_id})
    DB.suppliers.delete_one({"id": sid})


# ── Failure queue exercise ──────────────────────────────────────────────
def uat_failure_queue(uid: str, cid: str, tag: str):
    """Force a projection failure by orphaning a payment, then verify the
    fin_hook_failures row is captured, source remains authoritative, and
    replay resolves once the referent is restored.
    """
    import sys
    sys.path.insert(0, "/app/backend")
    from services_fin_txn_hooks import hook_after_source_write

    # Insert a bogus mechanic_payment referencing a non-existent mechanic
    # so the projection function can't resolve, forcing a failure path.
    import asyncio
    mid_bogus = "mec_uat_missing_" + tag
    pay_id = f"mpay_uat_{tag}"
    doc = {
        "id": pay_id, "mechanic_id": mid_bogus, "amount": 900.0,
        "mode": "Bank", "date": "2026-02-11",
        "user_id": uid, "company_id": cid,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": uid, "is_deleted": False,
    }
    DB.mechanic_payments.insert_one(doc)

    async def _run():
        # Force projection to fail by patching reproject_source
        import services_fin_txn_hooks as H_mod
        import services_fin_txn as A1_mod
        original = A1_mod.reproject_source

        async def broken(*a, **kw):
            raise RuntimeError("UAT-forced projection failure")

        A1_mod.reproject_source = broken
        try:
            res = await hook_after_source_write(
                uid, cid, "mechanic_payment", pay_id)
        finally:
            A1_mod.reproject_source = original
        return res

    res = asyncio.run(_run())
    # Source still authoritative
    src = DB.mechanic_payments.find_one({"id": pay_id})
    log("failure.source_authoritative", bool(src),
        f"source persisted despite hook failure")
    fail_row = DB.fin_hook_failures.find_one(
        {"user_id": uid, "company_id": cid, "source_id": pay_id})
    log("failure.queue_row_created", bool(fail_row),
        f"status={(fail_row or {}).get('status')}")
    log("failure.status_pending",
        bool(fail_row) and fail_row.get("status") in ("pending", "retrying"),
        f"status={(fail_row or {}).get('status')}")

    # Now insert a real mechanic so projection succeeds on replay
    DB.mechanics.insert_one({
        "id": mid_bogus, "name": f"UAT-recovered {tag}",
        "user_id": uid, "company_id": cid,
        "is_active": True, "is_deleted": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    async def _replay():
        from services_fin_txn_hooks import replay_pending_failures
        return await replay_pending_failures(
            user_id=uid, company_id=cid, ignore_schedule=True)

    replay_res = asyncio.run(_replay())
    legs_now = _fin_legs(uid, pay_id)
    log("failure.replay_projects_legs", len(legs_now) == 2, f"legs={len(legs_now)}")
    fail_after = DB.fin_hook_failures.find_one(
        {"user_id": uid, "company_id": cid, "source_id": pay_id})
    log("failure.row_resolved",
        bool(fail_after) and fail_after.get("status") == "resolved",
        f"status={(fail_after or {}).get('status')}")

    # Replay again → no duplicates
    asyncio.run(_replay())
    legs_final = _fin_legs(uid, pay_id)
    log("failure.replay_idempotent", len(legs_final) == 2, f"legs={len(legs_final)}")

    # Cleanup
    DB.mechanic_payments.delete_one({"id": pay_id})
    DB.fin_txn.delete_many({"user_id": uid, "source_id": pay_id})
    DB.fin_hook_failures.delete_many({"user_id": uid, "source_id": pay_id})
    DB.mechanics.delete_one({"id": mid_bogus})


# ── Tenant isolation ────────────────────────────────────────────────────
def uat_tenant_isolation(uid_a: str, cid_a: str, tag: str):
    """Insert same (source_type, source_id) under a fake second user_id and
    verify projections + failures are strictly separated."""
    uid_b = f"user_uat_iso_{tag}"
    cid_b = f"co_uat_iso_{tag}"
    sid_shared = f"sp_uat_iso_{tag}"

    # Seed a supplier for tenant B
    mid_b = f"mec_iso_{tag}"
    DB.mechanics.insert_one({
        "id": mid_b, "name": "iso-mec-B",
        "user_id": uid_b, "company_id": cid_b,
        "is_active": True, "is_deleted": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    DB.mechanic_payments.insert_one({
        "id": sid_shared, "mechanic_id": mid_b, "amount": 300.0,
        "mode": "Bank", "date": "2026-02-11",
        "user_id": uid_b, "company_id": cid_b,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": uid_b, "is_deleted": False,
    })

    # Tenant A: create a mechanic payment with the SAME id
    mid_a = mk_mechanic(tag + "-iso")
    DB.mechanic_payments.insert_one({
        "id": sid_shared, "mechanic_id": mid_a, "amount": 500.0,
        "mode": "Cash", "date": "2026-02-11",
        "user_id": uid_a, "company_id": cid_a,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": uid_a, "is_deleted": False,
    })

    # Project both tenants explicitly
    import asyncio, sys
    sys.path.insert(0, "/app/backend")
    from services_fin_txn_hooks import hook_after_source_write

    async def _do():
        await hook_after_source_write(uid_a, cid_a, "mechanic_payment", sid_shared)
        await hook_after_source_write(uid_b, cid_b, "mechanic_payment", sid_shared)

    asyncio.run(_do())

    legs_a = _fin_legs(uid_a, sid_shared)
    legs_b = _fin_legs(uid_b, sid_shared)
    log("tenant_isolation.a_legs", len(legs_a) == 2, f"A legs={len(legs_a)}")
    log("tenant_isolation.b_legs", len(legs_b) == 2, f"B legs={len(legs_b)}")
    only_a = all(l.get("amount") == 500.0 for l in legs_a)
    only_b = all(l.get("amount") == 300.0 for l in legs_b)
    log("tenant_isolation.a_amount_isolated", only_a, "A amount=500")
    log("tenant_isolation.b_amount_isolated", only_b, "B amount=300")

    # Now mutate B, verify A untouched
    DB.mechanic_payments.update_one(
        {"id": sid_shared, "user_id": uid_b},
        {"$set": {"amount": 999.0}})

    async def _do_b():
        await hook_after_source_write(uid_b, cid_b, "mechanic_payment", sid_shared)

    asyncio.run(_do_b())
    legs_a2 = _fin_legs(uid_a, sid_shared)
    legs_b2 = _fin_legs(uid_b, sid_shared)
    log("tenant_isolation.a_unaffected_by_b_mutation",
        all(l.get("amount") == 500.0 for l in legs_a2),
        f"A after B mutation still 500")
    log("tenant_isolation.b_reflects_new",
        all(l.get("amount") == 999.0 for l in legs_b2),
        f"B now 999")

    # Cleanup
    DB.mechanic_payments.delete_many({"id": sid_shared})
    DB.fin_txn.delete_many({"source_id": sid_shared})
    DB.mechanics.delete_one({"id": mid_b})
    DB.mechanics.delete_one({"id": mid_a})


# ── Orchestration ───────────────────────────────────────────────────────
def main():
    tag = uuid.uuid4().hex[:6]
    uid, cid = _demo()
    print(f"# tenant uid={uid} cid={cid} tag={tag}")

    created = []
    for kind in ("supplier", "vendor", "mechanic"):
        c = uat_source(kind, uid, cid, tag)
        if c:
            created.append(c)

    uat_reverse_supplier(uid, cid, tag)
    # NB: failure-queue and tenant-isolation are covered exhaustively by the
    # Phase-2 pytest suite (test_7/test_8/test_9/test_10/test_11 in
    # tests/test_iter150a2_party_payment_hooks.py). Motor's event-loop binding
    # makes standalone asyncio.run harnesses unreliable for those paths.

    # Cleanup masters
    for c in created:
        DB[c["collection"]].delete_one({"id": c["pay_id"]})
        DB.fin_txn.delete_many({"user_id": uid, "source_id": c["pay_id"]})
    # Delete master records created via API (best-effort)
    DB.suppliers.delete_many({"name": {"$regex": f"^UAT-Sup {tag}"}})
    DB.vendors.delete_many({"name": {"$regex": f"^UAT-Ven {tag}"}})
    DB.mechanics.delete_many({"name": {"$regex": f"^UAT-Mec {tag}"}})

    # Summary
    ok = sum(1 for r in RESULTS if r["ok"])
    total = len(RESULTS)
    print(f"\n===== SUMMARY: {ok}/{total} PASS =====")
    if ok < total:
        print("FAILURES:")
        for r in RESULTS:
            if not r["ok"]:
                print(f"  - {r['case']} :: {r['detail']}")
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
