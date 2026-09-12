"""Iter150J · Approval Framework — 30 lifecycle tests.

Exercises the full state machine through direct service calls (bypassing
the HTTP middleware). Each test is self-contained: it seeds a fresh
tenant + company + party masters, mints an Approval, drives it through
the lifecycle, and verifies FinTxn projection invariants.
"""
from __future__ import annotations
import asyncio
import uuid
import pytest

from db import db
from models import ROLE_PERMISSIONS, Company
from services_fin_txn import ensure_system_accounts
import services_approvals as svc


# ------------------------- helpers -------------------------
def _run(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError()
    except Exception:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


class _StubReq:
    """Duck-typed Starlette Request stand-in — only the attributes the
    writers actually read: headers.get("X-Company-Id") and cookies.get.
    """
    def __init__(self, cid: str):
        self.headers = {"x-company-id": cid, "X-Company-Id": cid}
        self.cookies = {}

    class _H:
        def __init__(self, d): self._d = d
        def get(self, k, default=None): return self._d.get(k) or self._d.get((k or "").lower()) or default

    def __getattribute__(self, item):
        if item == "headers":
            d = object.__getattribute__(self, "__dict__")["headers"]
            return _StubReq._H(d)
        return object.__getattribute__(self, item)


async def _seed(*, role="owner", solo=True):
    uid = f"u_j_{uuid.uuid4().hex[:8]}"
    cid = f"c_j_{uuid.uuid4().hex[:8]}"
    await ensure_system_accounts(uid, cid)
    await db.companies.insert_one({
        "id": cid, "user_id": uid, "name": "Test Co",
        "require_approval_trip": True, "require_approval_invoice": True,
        "require_approval_payment": True, "is_default": True,
    })
    # Insert self as user
    await db.users.insert_one({
        "user_id": uid, "email": f"{uid}@t.local", "role": role,
        "effective_role": role, "is_active": True, "parent_user_id": uid,
    })
    if not solo:
        # Add a second owner teammate so is_solo_owner() returns False
        peer = f"u_j_{uuid.uuid4().hex[:8]}"
        await db.users.insert_one({
            "user_id": peer, "email": f"{peer}@t.local", "role": "owner",
            "effective_role": "owner", "is_active": True, "parent_user_id": uid,
        })
    # Driver master (needed for driver_payment writer path)
    did = f"drv_{uuid.uuid4().hex[:8]}"
    await db.drivers.insert_one({
        "user_id": uid, "company_id": cid, "id": did, "name": "D",
    })
    return uid, cid, did


def _user(uid, role="owner"):
    return {"user_id": uid, "email": f"{uid}@t.local",
            "role": role, "effective_role": role, "parent_user_id": uid}


async def _cleanup(uid):
    for c in ("approvals", "approval_revisions", "approval_audits",
              "driver_payments", "driver_payment_corrections", "fin_txn",
              "fin_accounts", "drivers", "companies", "users",
              "user_sessions", "supplier_payments", "vendor_payments",
              "mechanic_payments", "trips", "invoices", "suppliers",
              "vendors", "mechanics"):
        await db[c].delete_many({"user_id": uid})


# ------------------------- 30 lifecycle tests -------------------------

def test_01_solo_owner_auto_executes_driver_payment():
    async def go():
        uid, cid, did = await _seed(solo=True)
        try:
            payload = {"driver_id": did, "date": "2026-02-14",
                       "amount": 250, "mode": "Cash", "against": "other"}
            r = await svc.create_approval(
                user=_user(uid), company_id=cid, entity_kind="driver_payment",
                party_id=did, payload=payload, method="POST",
                writer_url=f"/api/drivers/{did}/payments",
                idempotency_key=uuid.uuid4().hex, request=_StubReq(cid))
            assert r["status"] == "POSTED"
            assert r["auto_approved"] is True
            assert r["checker_user_id"] == "__solo_owner__"
            legs = await db.fin_txn.count_documents({
                "user_id": uid, "company_id": cid,
                "source_type": "driver_payment"})
            assert legs == 2
        finally:
            await _cleanup(uid)
    _run(go())


def test_02_multi_owner_leaves_pending():
    async def go():
        uid, cid, did = await _seed(solo=False)
        try:
            r = await svc.create_approval(
                user=_user(uid), company_id=cid, entity_kind="driver_payment",
                party_id=did,
                payload={"driver_id": did, "date": "2026-02-14",
                         "amount": 100, "mode": "Cash", "against": "other"},
                method="POST", writer_url=f"/api/drivers/{did}/payments",
                idempotency_key="", request=_StubReq(cid))
            assert r["status"] == "PENDING_APPROVAL"
            legs = await db.fin_txn.count_documents({
                "user_id": uid, "source_type": "driver_payment"})
            assert legs == 0
        finally:
            await _cleanup(uid)
    _run(go())


def test_03_idempotent_replay_returns_same_row():
    async def go():
        uid, cid, did = await _seed(solo=False)
        try:
            key = uuid.uuid4().hex
            payload = {"driver_id": did, "date": "2026-02-14",
                       "amount": 100, "mode": "Cash", "against": "other"}
            a = await svc.create_approval(
                user=_user(uid), company_id=cid, entity_kind="driver_payment",
                party_id=did, payload=payload, method="POST",
                writer_url=f"/api/drivers/{did}/payments",
                idempotency_key=key, request=_StubReq(cid))
            b = await svc.create_approval(
                user=_user(uid), company_id=cid, entity_kind="driver_payment",
                party_id=did, payload=payload, method="POST",
                writer_url=f"/api/drivers/{did}/payments",
                idempotency_key=key, request=_StubReq(cid))
            assert a["id"] == b["id"]
            count = await db.approvals.count_documents({
                "user_id": uid, "idempotency_key": key})
            assert count == 1
        finally:
            await _cleanup(uid)
    _run(go())


def test_04_pending_has_zero_fintxn():
    async def go():
        uid, cid, did = await _seed(solo=False)
        try:
            await svc.create_approval(
                user=_user(uid), company_id=cid, entity_kind="driver_payment",
                party_id=did,
                payload={"driver_id": did, "date": "2026-02-14",
                         "amount": 500, "mode": "Cash", "against": "other"},
                method="POST", writer_url=f"/api/drivers/{did}/payments",
                idempotency_key="", request=_StubReq(cid))
            assert 0 == await db.fin_txn.count_documents({"user_id": uid})
        finally:
            await _cleanup(uid)
    _run(go())


def test_05_rejected_produces_zero_fintxn():
    async def go():
        uid, cid, did = await _seed(solo=False)
        try:
            a = await svc.create_approval(
                user=_user(uid), company_id=cid, entity_kind="driver_payment",
                party_id=did,
                payload={"driver_id": did, "date": "2026-02-14",
                         "amount": 100, "mode": "Cash", "against": "other"},
                method="POST", writer_url=f"/api/drivers/{did}/payments",
                idempotency_key="", request=_StubReq(cid))
            # Rewrite maker to simulate a distinct submitter; checker is the
            # tenant owner (data scope stays consistent with the tenant uid).
            await db.approvals.update_one({"id": a["id"]},
                                          {"$set": {"maker_user_id": "peer_maker"}})
            r = await svc.reject(approval_id=a["id"], user=_user(uid),
                                  company_id=cid, reason="looks wrong")
            assert r["status"] == "REJECTED"
            assert 0 == await db.fin_txn.count_documents({"user_id": uid})
        finally:
            await _cleanup(uid)
    _run(go())


def test_06_withdrawn_produces_zero_fintxn():
    async def go():
        uid, cid, did = await _seed(solo=False)
        try:
            a = await svc.create_approval(
                user=_user(uid), company_id=cid, entity_kind="driver_payment",
                party_id=did,
                payload={"driver_id": did, "date": "2026-02-14",
                         "amount": 100, "mode": "Cash", "against": "other"},
                method="POST", writer_url=f"/api/drivers/{did}/payments",
                idempotency_key="", request=_StubReq(cid))
            r = await svc.withdraw(approval_id=a["id"], user=_user(uid),
                                    company_id=cid, reason="mistake")
            assert r["status"] == "WITHDRAWN"
            assert 0 == await db.fin_txn.count_documents({"user_id": uid})
        finally:
            await _cleanup(uid)
    _run(go())


def test_07_maker_cannot_approve_own():
    async def go():
        uid, cid, did = await _seed(solo=False)
        try:
            a = await svc.create_approval(
                user=_user(uid), company_id=cid, entity_kind="driver_payment",
                party_id=did,
                payload={"driver_id": did, "date": "2026-02-14",
                         "amount": 100, "mode": "Cash", "against": "other"},
                method="POST", writer_url=f"/api/drivers/{did}/payments",
                idempotency_key="", request=_StubReq(cid))
            with pytest.raises(Exception) as e:
                await svc.approve(approval_id=a["id"], user=_user(uid),
                                   company_id=cid, request=_StubReq(cid))
            # should be 403 maker cannot approve own submission
            assert "Maker" in str(e.value) or "403" in str(e.value)
        finally:
            await _cleanup(uid)
    _run(go())


def test_08_checker_approve_executes_writer():
    async def go():
        uid, cid, did = await _seed(solo=False)
        try:
            a = await svc.create_approval(
                user=_user(uid), company_id=cid, entity_kind="driver_payment",
                party_id=did,
                payload={"driver_id": did, "date": "2026-02-14",
                         "amount": 300, "mode": "Cash", "against": "other"},
                method="POST", writer_url=f"/api/drivers/{did}/payments",
                idempotency_key="", request=_StubReq(cid))
            peer = f"u_j_{uuid.uuid4().hex[:8]}"
            checker = {"user_id": peer, "role": "owner", "effective_role": "owner",
                       "parent_user_id": uid}
            # Peer needs its own tenant scope, but our approvals are filtered
            # by user_id. Approve function reads the approval scoped to the
            # CHECKER's user_id — that means the peer wouldn't see it. In
            # practice, teammates share the same primary user_id via
            # user-session pointing to owner. Simulate this by making the
            # checker share the owner's user_id but a different actor id
            # is tracked via `maker_user_id` field only. Achieve that by
            # setting checker.user_id = uid but "actor" via maker check on
            # apr.maker_user_id (which is the original maker). So the peer
            # checker must present as tenant owner uid.
            # To simulate a real peer with distinct identity: change the
            # maker_user_id on the stored approval directly.
            await db.approvals.update_one(
                {"id": a["id"]}, {"$set": {"maker_user_id": "maker_x"}})
            r = await svc.approve(approval_id=a["id"], user=_user(uid),
                                   company_id=cid, request=_StubReq(cid))
            assert r["status"] == "POSTED"
            legs = await db.fin_txn.count_documents({
                "user_id": uid, "source_type": "driver_payment"})
            assert legs == 2
        finally:
            await _cleanup(uid)
    _run(go())


def test_09_double_approve_is_noop():
    async def go():
        uid, cid, did = await _seed(solo=False)
        try:
            a = await svc.create_approval(
                user=_user(uid), company_id=cid, entity_kind="driver_payment",
                party_id=did,
                payload={"driver_id": did, "date": "2026-02-14",
                         "amount": 300, "mode": "Cash", "against": "other"},
                method="POST", writer_url=f"/api/drivers/{did}/payments",
                idempotency_key="", request=_StubReq(cid))
            await db.approvals.update_one({"id": a["id"]}, {"$set": {"maker_user_id": "someone_else"}})
            await svc.approve(approval_id=a["id"], user=_user(uid),
                               company_id=cid, request=_StubReq(cid))
            with pytest.raises(Exception):
                await svc.approve(approval_id=a["id"], user=_user(uid),
                                   company_id=cid, request=_StubReq(cid))
            legs = await db.fin_txn.count_documents({
                "user_id": uid, "source_type": "driver_payment"})
            assert legs == 2
        finally:
            await _cleanup(uid)
    _run(go())


def test_10_reject_without_reason_400():
    async def go():
        uid, cid, did = await _seed(solo=False)
        try:
            a = await svc.create_approval(
                user=_user(uid), company_id=cid, entity_kind="driver_payment",
                party_id=did,
                payload={"driver_id": did, "date": "2026-02-14",
                         "amount": 100, "mode": "Cash", "against": "other"},
                method="POST", writer_url=f"/api/drivers/{did}/payments",
                idempotency_key="", request=_StubReq(cid))
            await db.approvals.update_one({"id": a["id"]},
                                          {"$set": {"maker_user_id": "peer_x"}})
            with pytest.raises(Exception):
                await svc.reject(approval_id=a["id"], user=_user(uid),
                                  company_id=cid, reason="")
        finally:
            await _cleanup(uid)
    _run(go())


def test_11_resubmit_after_reject_creates_revision():
    async def go():
        uid, cid, did = await _seed(solo=False)
        try:
            payload = {"driver_id": did, "date": "2026-02-14",
                       "amount": 100, "mode": "Cash", "against": "other"}
            a = await svc.create_approval(
                user=_user(uid), company_id=cid, entity_kind="driver_payment",
                party_id=did, payload=payload, method="POST",
                writer_url=f"/api/drivers/{did}/payments",
                idempotency_key="", request=_StubReq(cid))
            # peer rejects (need different maker/checker identity)
            checker = {**_user(uid), "user_id": f"peer_{uid}"}
            # emulate peer by temporarily patching apr.maker_user_id
            await db.approvals.update_one({"id": a["id"]},
                                          {"$set": {"maker_user_id": "peer_maker"}})
            # But then edit-and-resubmit requires apr.maker_user_id == user.
            # Restore for edit path:
            await svc.reject(approval_id=a["id"], user=_user(uid),
                              company_id=cid, reason="please fix amount")
            await db.approvals.update_one({"id": a["id"]},
                                          {"$set": {"maker_user_id": uid}})
            new_payload = {**payload, "amount": 200}
            r = await svc.edit_and_resubmit(
                approval_id=a["id"], user=_user(uid), company_id=cid,
                new_payload=new_payload, note="corrected", request=_StubReq(cid))
            # Solo path may fire since we only have 1 user post-cleanup, but
            # peer users were removed. Either PENDING or POSTED is acceptable
            # provided revision_index bumped and revision row exists.
            assert r["revision_index"] == 1
            revs = await db.approval_revisions.count_documents({
                "approval_id": a["id"]})
            assert revs == 1
        finally:
            await _cleanup(uid)
    _run(go())


def test_12_revision_preserves_previous_payload():
    async def go():
        uid, cid, did = await _seed(solo=False)
        try:
            payload = {"driver_id": did, "date": "2026-02-14",
                       "amount": 100, "mode": "Cash", "against": "other"}
            a = await svc.create_approval(
                user=_user(uid), company_id=cid, entity_kind="driver_payment",
                party_id=did, payload=payload, method="POST",
                writer_url=f"/api/drivers/{did}/payments",
                idempotency_key="", request=_StubReq(cid))
            await db.approvals.update_one({"id": a["id"]},
                                          {"$set": {"maker_user_id": "peer"}})
            await svc.reject(approval_id=a["id"], user=_user(uid),
                              company_id=cid, reason="bad")
            await db.approvals.update_one({"id": a["id"]},
                                          {"$set": {"maker_user_id": uid}})
            await svc.edit_and_resubmit(
                approval_id=a["id"], user=_user(uid), company_id=cid,
                new_payload={**payload, "amount": 999}, note="",
                request=_StubReq(cid))
            rev = await db.approval_revisions.find_one({"approval_id": a["id"]})
            assert rev["payload_before"]["amount"] == 100
            assert rev["payload_after"]["amount"] == 999
        finally:
            await _cleanup(uid)
    _run(go())


def test_13_edit_after_posted_blocked():
    async def go():
        uid, cid, did = await _seed(solo=True)
        try:
            r = await svc.create_approval(
                user=_user(uid), company_id=cid, entity_kind="driver_payment",
                party_id=did,
                payload={"driver_id": did, "date": "2026-02-14",
                         "amount": 100, "mode": "Cash", "against": "other"},
                method="POST", writer_url=f"/api/drivers/{did}/payments",
                idempotency_key="", request=_StubReq(cid))
            assert r["status"] == "POSTED"
            with pytest.raises(Exception):
                await svc.edit_and_resubmit(
                    approval_id=r["id"], user=_user(uid), company_id=cid,
                    new_payload={"driver_id": did, "amount": 200,
                                  "date": "2026-02-14", "mode": "Cash",
                                  "against": "other"},
                    note="", request=_StubReq(cid))
        finally:
            await _cleanup(uid)
    _run(go())


def test_14_withdraw_after_posted_blocked():
    async def go():
        uid, cid, did = await _seed(solo=True)
        try:
            r = await svc.create_approval(
                user=_user(uid), company_id=cid, entity_kind="driver_payment",
                party_id=did,
                payload={"driver_id": did, "date": "2026-02-14",
                         "amount": 100, "mode": "Cash", "against": "other"},
                method="POST", writer_url=f"/api/drivers/{did}/payments",
                idempotency_key="", request=_StubReq(cid))
            with pytest.raises(Exception):
                await svc.withdraw(approval_id=r["id"], user=_user(uid),
                                    company_id=cid, reason="late")
        finally:
            await _cleanup(uid)
    _run(go())


def test_15_reject_after_reject_blocked():
    async def go():
        uid, cid, did = await _seed(solo=False)
        try:
            a = await svc.create_approval(
                user=_user(uid), company_id=cid, entity_kind="driver_payment",
                party_id=did,
                payload={"driver_id": did, "date": "2026-02-14",
                         "amount": 100, "mode": "Cash", "against": "other"},
                method="POST", writer_url=f"/api/drivers/{did}/payments",
                idempotency_key="", request=_StubReq(cid))
            await db.approvals.update_one({"id": a["id"]},
                                          {"$set": {"maker_user_id": "peer"}})
            await svc.reject(approval_id=a["id"], user=_user(uid),
                              company_id=cid, reason="no")
            with pytest.raises(Exception):
                await svc.reject(approval_id=a["id"], user=_user(uid),
                                  company_id=cid, reason="no again")
        finally:
            await _cleanup(uid)
    _run(go())


def test_16_audit_trail_captures_lifecycle():
    async def go():
        uid, cid, did = await _seed(solo=True)
        try:
            r = await svc.create_approval(
                user=_user(uid), company_id=cid, entity_kind="driver_payment",
                party_id=did,
                payload={"driver_id": did, "date": "2026-02-14",
                         "amount": 100, "mode": "Cash", "against": "other"},
                method="POST", writer_url=f"/api/drivers/{did}/payments",
                idempotency_key="", request=_StubReq(cid))
            actions = [a["action"] async for a in db.approval_audits.find(
                {"approval_id": r["id"]}).sort("at", 1)]
            assert "submit" in actions
            assert "auto_approve" in actions
            assert "execute" in actions
        finally:
            await _cleanup(uid)
    _run(go())


def test_17_supplier_payment_solo_owner_flow():
    async def go():
        uid, cid, did = await _seed(solo=True)
        try:
            sid = f"sup_{uuid.uuid4().hex[:8]}"
            await db.suppliers.insert_one({"user_id": uid, "company_id": cid,
                                            "id": sid, "name": "S"})
            r = await svc.create_approval(
                user=_user(uid), company_id=cid, entity_kind="supplier_payment",
                party_id=sid,
                payload={"supplier_id": sid, "date": "2026-02-14",
                         "amount": 100, "mode": "Cash", "type": "payment_out"},
                method="POST", writer_url=f"/api/suppliers/{sid}/payments",
                idempotency_key="", request=_StubReq(cid))
            assert r["status"] == "POSTED"
            assert r["entity_id"]
        finally:
            await _cleanup(uid)
    _run(go())


def test_18_vendor_payment_solo_owner_flow():
    async def go():
        uid, cid, did = await _seed(solo=True)
        try:
            vid = f"ven_{uuid.uuid4().hex[:8]}"
            await db.vendors.insert_one({"user_id": uid, "company_id": cid,
                                          "id": vid, "name": "V"})
            r = await svc.create_approval(
                user=_user(uid), company_id=cid, entity_kind="vendor_payment",
                party_id=vid,
                payload={"vendor_id": vid, "date": "2026-02-14",
                         "amount": 50, "mode": "Cash"},
                method="POST", writer_url=f"/api/vendors/{vid}/payments",
                idempotency_key="", request=_StubReq(cid))
            assert r["status"] == "POSTED"
        finally:
            await _cleanup(uid)
    _run(go())


def test_19_mechanic_payment_solo_owner_flow():
    async def go():
        uid, cid, did = await _seed(solo=True)
        try:
            mid = f"mec_{uuid.uuid4().hex[:8]}"
            await db.mechanics.insert_one({"user_id": uid, "company_id": cid,
                                            "id": mid, "name": "M"})
            r = await svc.create_approval(
                user=_user(uid), company_id=cid, entity_kind="mechanic_payment",
                party_id=mid,
                payload={"mechanic_id": mid, "date": "2026-02-14",
                         "amount": 25, "mode": "Cash"},
                method="POST", writer_url=f"/api/mechanics/{mid}/payments",
                idempotency_key="", request=_StubReq(cid))
            assert r["status"] == "POSTED"
        finally:
            await _cleanup(uid)
    _run(go())


def test_20_execution_failure_marks_status():
    async def go():
        uid, cid, did = await _seed(solo=True)
        try:
            # zero amount → writer returns 400
            with pytest.raises(Exception):
                await svc.create_approval(
                    user=_user(uid), company_id=cid, entity_kind="driver_payment",
                    party_id=did,
                    payload={"driver_id": did, "date": "2026-02-14",
                             "amount": 0, "mode": "Cash", "against": "other"},
                    method="POST", writer_url=f"/api/drivers/{did}/payments",
                    idempotency_key="", request=_StubReq(cid))
            failed = await db.approvals.find_one({
                "user_id": uid, "status": "EXECUTION_FAILED"})
            assert failed is not None
            assert failed.get("execution_error")
        finally:
            await _cleanup(uid)
    _run(go())


def test_21_listing_filters_by_status():
    async def go():
        uid, cid, did = await _seed(solo=False)
        try:
            await svc.create_approval(
                user=_user(uid), company_id=cid, entity_kind="driver_payment",
                party_id=did,
                payload={"driver_id": did, "date": "2026-02-14",
                         "amount": 100, "mode": "Cash", "against": "other"},
                method="POST", writer_url=f"/api/drivers/{did}/payments",
                idempotency_key="", request=_StubReq(cid))
            rows = await svc.list_approvals(user=_user(uid), company_id=cid,
                                              status="PENDING_APPROVAL")
            assert len(rows) == 1
            rows2 = await svc.list_approvals(user=_user(uid), company_id=cid,
                                               status="POSTED")
            assert len(rows2) == 0
        finally:
            await _cleanup(uid)
    _run(go())


def test_22_pending_count_exact():
    async def go():
        uid, cid, did = await _seed(solo=False)
        try:
            for _ in range(3):
                await svc.create_approval(
                    user=_user(uid), company_id=cid, entity_kind="driver_payment",
                    party_id=did,
                    payload={"driver_id": did, "date": "2026-02-14",
                             "amount": 100, "mode": "Cash", "against": "other"},
                    method="POST", writer_url=f"/api/drivers/{did}/payments",
                    idempotency_key="", request=_StubReq(cid))
            n = await db.approvals.count_documents({
                "user_id": uid, "company_id": cid, "status": "PENDING_APPROVAL"})
            assert n == 3
        finally:
            await _cleanup(uid)
    _run(go())


def test_23_cross_tenant_invisible():
    async def go():
        uid, cid, did = await _seed(solo=False)
        try:
            a = await svc.create_approval(
                user=_user(uid), company_id=cid, entity_kind="driver_payment",
                party_id=did,
                payload={"driver_id": did, "date": "2026-02-14",
                         "amount": 100, "mode": "Cash", "against": "other"},
                method="POST", writer_url=f"/api/drivers/{did}/payments",
                idempotency_key="", request=_StubReq(cid))
            outsider = _user("u_outsider")
            with pytest.raises(Exception):
                await svc.get_approval_detail(user=outsider, company_id=cid,
                                                approval_id=a["id"])
        finally:
            await _cleanup(uid)
    _run(go())


def test_24_permission_viewer_cannot_submit():
    async def go():
        uid, cid, did = await _seed(solo=True)
        try:
            viewer = {"user_id": uid, "role": "viewer",
                      "effective_role": "viewer", "parent_user_id": uid}
            with pytest.raises(Exception):
                await svc.create_approval(
                    user=viewer, company_id=cid, entity_kind="driver_payment",
                    party_id=did,
                    payload={"driver_id": did, "date": "2026-02-14",
                             "amount": 100, "mode": "Cash", "against": "other"},
                    method="POST", writer_url=f"/api/drivers/{did}/payments",
                    idempotency_key="", request=_StubReq(cid))
        finally:
            await _cleanup(uid)
    _run(go())


def test_25_solo_owner_marks_auto_approved_true():
    async def go():
        uid, cid, did = await _seed(solo=True)
        try:
            r = await svc.create_approval(
                user=_user(uid), company_id=cid, entity_kind="driver_payment",
                party_id=did,
                payload={"driver_id": did, "date": "2026-02-14",
                         "amount": 100, "mode": "Cash", "against": "other"},
                method="POST", writer_url=f"/api/drivers/{did}/payments",
                idempotency_key="", request=_StubReq(cid))
            assert r["auto_approved"] is True
            assert r["checker_user_id"] == "__solo_owner__"
        finally:
            await _cleanup(uid)
    _run(go())


def test_26_no_double_fintxn_after_replay():
    async def go():
        uid, cid, did = await _seed(solo=True)
        try:
            k = uuid.uuid4().hex
            payload = {"driver_id": did, "date": "2026-02-14",
                       "amount": 100, "mode": "Cash", "against": "other"}
            await svc.create_approval(
                user=_user(uid), company_id=cid, entity_kind="driver_payment",
                party_id=did, payload=payload, method="POST",
                writer_url=f"/api/drivers/{did}/payments",
                idempotency_key=k, request=_StubReq(cid))
            await svc.create_approval(
                user=_user(uid), company_id=cid, entity_kind="driver_payment",
                party_id=did, payload=payload, method="POST",
                writer_url=f"/api/drivers/{did}/payments",
                idempotency_key=k, request=_StubReq(cid))
            legs = await db.fin_txn.count_documents({
                "user_id": uid, "source_type": "driver_payment"})
            assert legs == 2  # not 4
        finally:
            await _cleanup(uid)
    _run(go())


def test_27_posted_approval_has_entity_id():
    async def go():
        uid, cid, did = await _seed(solo=True)
        try:
            r = await svc.create_approval(
                user=_user(uid), company_id=cid, entity_kind="driver_payment",
                party_id=did,
                payload={"driver_id": did, "date": "2026-02-14",
                         "amount": 100, "mode": "Cash", "against": "other"},
                method="POST", writer_url=f"/api/drivers/{did}/payments",
                idempotency_key="", request=_StubReq(cid))
            assert r["entity_id"].startswith("dpay_")
        finally:
            await _cleanup(uid)
    _run(go())


def test_28_status_matrix_frozen():
    from models import APPROVAL_STATUSES
    expected = {"DRAFT", "PENDING_APPROVAL", "APPROVED", "REJECTED",
                "WITHDRAWN", "POSTED", "EXECUTION_FAILED"}
    assert set(APPROVAL_STATUSES) == expected


def test_29_approval_never_stores_full_account_number():
    async def go():
        uid, cid, did = await _seed(solo=False)
        try:
            payload = {"driver_id": did, "date": "2026-02-14",
                       "amount": 100, "mode": "Bank", "against": "other",
                       "bank_account_id": "pba_xyz",
                       "company_bank_account_id": "cba_xyz"}
            await svc.create_approval(
                user=_user(uid), company_id=cid, entity_kind="driver_payment",
                party_id=did, payload=payload, method="POST",
                writer_url=f"/api/drivers/{did}/payments",
                idempotency_key="", request=_StubReq(cid))
            apr = await db.approvals.find_one({"user_id": uid})
            # Only IDs — never the full account number field.
            assert "account_number" not in apr.get("payload", {})
        finally:
            await _cleanup(uid)
    _run(go())


def test_30_solo_owner_leaves_zero_pending():
    async def go():
        uid, cid, did = await _seed(solo=True)
        try:
            await svc.create_approval(
                user=_user(uid), company_id=cid, entity_kind="driver_payment",
                party_id=did,
                payload={"driver_id": did, "date": "2026-02-14",
                         "amount": 100, "mode": "Cash", "against": "other"},
                method="POST", writer_url=f"/api/drivers/{did}/payments",
                idempotency_key="", request=_StubReq(cid))
            pending = await db.approvals.count_documents({
                "user_id": uid, "status": "PENDING_APPROVAL"})
            assert pending == 0
        finally:
            await _cleanup(uid)
    _run(go())
