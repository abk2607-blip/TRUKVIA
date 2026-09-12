"""Iter150J · Approval Service — sole trusted delegation to domain writers.

Responsibilities:
  * create / submit approvals (PENDING_APPROVAL)
  * approve (checker) / reject (checker) / withdraw (maker) / edit-resubmit
  * solo-owner auto-approval through the same common path
  * direct Python delegation into the frozen domain writers
  * append-only revision + immutable audit
  * status-transition CAS protection
  * duplicate-approval guard via (user_id, company_id, idempotency_key)
  * execution-failure containment (EXECUTION_FAILED, execution_error)

Trust boundary:
  This module is the ONLY approval-authorised call-site for the six domain
  writer functions. The static test `test_iter150j_trust_boundary_static`
  enforces this at CI time. Writer functions are invoked as plain
  Python coroutines — HTTP middleware is bypassed by construction.

Nothing here mutates FinTxn. Ledger projection remains the exclusive
responsibility of the frozen `hook_after_source_write` invoked by each
writer.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, Request

from db import db
from models import (
    Approval, ApprovalRevision, ApprovalAudit,
    APPROVAL_ENTITY_KINDS, ROLE_PERMISSIONS,
    new_id, now_utc,
)

# Domain-writer imports — authorised delegation targets. NO OTHER MODULE
# outside this one and the router-definition sites is permitted to call
# these functions; enforced by test_iter150j_trust_boundary_static.
from routers import trips as _trips_router
from routers import invoices as _invoices_router
from routers import suppliers as _suppliers_router
from routers import vendors as _vendors_router
from routers import mechanics as _mechanics_router
from routers import driver_payments as _driver_payments_router
from models import Trip, InvoiceCreateRequest, SupplierPayment, VendorPayment, MechanicPayment, DriverPayment

logger = logging.getLogger(__name__)

SOLO_OWNER_CHECKER = "__solo_owner__"


# ---------------------------------------------------------------------------
# Index setup (idempotent — called once at startup).
# ---------------------------------------------------------------------------
async def ensure_approval_indexes():
    """Idempotent index setup for the three approval collections.

    Uniqueness key: (user_id, company_id, idempotency_key) with a partial
    filter that excludes blank keys — safe under NULL / missing party_id
    because the key is client-generated per-request UUID, never a
    party-composite. Mirrors Iter134 invoices + Iter133 expenses.source_key.
    """
    try:
        await db.approvals.create_index(
            [("user_id", 1), ("company_id", 1), ("idempotency_key", 1)],
            name="uniq_approval_idempotency",
            unique=True,
            partialFilterExpression={"idempotency_key": {"$type": "string", "$gt": ""}},
        )
        await db.approvals.create_index(
            [("user_id", 1), ("company_id", 1), ("status", 1), ("created_at", -1)],
            name="approvals_scope_status_date",
        )
        await db.approvals.create_index(
            [("user_id", 1), ("company_id", 1), ("entity_kind", 1), ("created_at", -1)],
            name="approvals_scope_kind_date",
        )
        await db.approval_revisions.create_index(
            [("approval_id", 1), ("revision_index", 1)],
            unique=True,
            name="uniq_approval_revision",
        )
        await db.approval_audits.create_index(
            [("approval_id", 1), ("at", 1)],
            name="approval_audits_lookup",
        )
    except Exception as e:
        logger.warning(f"Iter150J approval index setup failed: {e}")


# ---------------------------------------------------------------------------
# Permissions.
# ---------------------------------------------------------------------------
def _has(user: dict, perm: str) -> bool:
    role = (user.get("effective_role") or user.get("role") or "").lower()
    return perm in ROLE_PERMISSIONS.get(role, set())


def _can_submit(user: dict) -> bool:
    # Owners and accountants may submit (owner via approve_transactions
    # implicitly permitted; accountant via submit_approval).
    return _has(user, "approve_transactions") or _has(user, "submit_approval")


def _can_approve(user: dict) -> bool:
    return _has(user, "approve_transactions")


async def _is_solo_owner(user: dict) -> bool:
    """A tenant is solo-owned when there is no OTHER active user with
    checker capability. Team members typically live under
    `parent_user_id == owner.user_id` in the users collection.
    """
    if (user.get("effective_role") or user.get("role") or "").lower() != "owner":
        return False
    uid = user["user_id"]
    try:
        others = await db.users.count_documents({
            "parent_user_id": uid,
            "user_id": {"$ne": uid},
            "role": {"$in": ["owner", "accountant"]},
            "is_active": {"$ne": False},
        })
        return others == 0
    except Exception:
        # If in doubt, force the full approval path (fail-secure).
        return False


# ---------------------------------------------------------------------------
# Audit / revision helpers.
# ---------------------------------------------------------------------------
async def _audit(approval_id: str, uid: str, cid: str, action: str,
                 actor_user_id: str, actor_role: str, note: str = "",
                 metadata: Optional[dict] = None) -> str:
    row = ApprovalAudit(
        approval_id=approval_id, action=action,
        actor_user_id=actor_user_id, actor_role=actor_role,
        note=note, metadata=metadata or {},
    ).model_dump()
    row["user_id"] = uid
    row["company_id"] = cid
    await db.approval_audits.insert_one(row)
    return row["id"]


def _diff_payloads(before: dict, after: dict) -> dict:
    diff = {}
    keys = set(before.keys()) | set(after.keys())
    for k in keys:
        b, a = before.get(k), after.get(k)
        if b != a:
            diff[k] = [b, a]
    return diff


# ---------------------------------------------------------------------------
# Payload → Pydantic dispatch (needed because writers accept typed models).
# ---------------------------------------------------------------------------
_WRITER_PAYLOAD_MODEL = {
    "trip": Trip,
    "invoice": InvoiceCreateRequest,
    "supplier_payment": SupplierPayment,
    "vendor_payment": VendorPayment,
    "mechanic_payment": MechanicPayment,
    "driver_payment": DriverPayment,
}


def _load_payload_model(entity_kind: str, payload: dict):
    Model = _WRITER_PAYLOAD_MODEL[entity_kind]
    return Model(**payload)


async def _delegate_writer(entity_kind: str, party_id: str, payload_dict: dict,
                            request: Request, user: dict) -> dict:
    """Direct Python delegation to the frozen domain writer.

    Bypasses HTTP middleware by construction. Passes the approver's
    Request (carries the same X-Company-Id as the tenant we operate on).
    """
    typed = _load_payload_model(entity_kind, payload_dict)
    if entity_kind == "trip":
        return await _trips_router.create_trip(typed, request, user)
    if entity_kind == "invoice":
        return await _invoices_router.create_invoice(typed, request, user)
    if entity_kind == "supplier_payment":
        return await _suppliers_router.create_payment(party_id, typed, request, user)
    if entity_kind == "vendor_payment":
        return await _vendors_router.create_vendor_payment(party_id, typed, request, user)
    if entity_kind == "mechanic_payment":
        return await _mechanics_router.create_mechanic_payment(party_id, typed, request, user)
    if entity_kind == "driver_payment":
        return await _driver_payments_router.create_driver_payment(party_id, typed, request, user)
    raise HTTPException(status_code=400, detail=f"Unknown entity_kind: {entity_kind}")


# ---------------------------------------------------------------------------
# Public lifecycle API — called only from routers/approvals.py.
# ---------------------------------------------------------------------------
async def create_approval(*, user: dict, company_id: str, entity_kind: str,
                           party_id: str, payload: dict, method: str,
                           writer_url: str, idempotency_key: str,
                           request: Request) -> dict:
    """Create a PENDING_APPROVAL row. If the tenant is solo-owned, the
    approval is auto-approved and executed atomically through the same
    common path (checker_user_id = '__solo_owner__').
    """
    if entity_kind not in APPROVAL_ENTITY_KINDS:
        raise HTTPException(status_code=400, detail="Invalid entity_kind")
    if not _can_submit(user):
        raise HTTPException(status_code=403, detail="Not permitted to submit approvals")

    uid = user["user_id"]
    # Duplicate-approval guard via idempotency key. Blank keys fall outside
    # the partial-unique index; treat as always-unique.
    if idempotency_key:
        existing = await db.approvals.find_one(
            {"user_id": uid, "company_id": company_id, "idempotency_key": idempotency_key},
            {"_id": 0},
        )
        if existing:
            return existing

    solo = await _is_solo_owner(user)
    role = (user.get("effective_role") or user.get("role") or "").lower()

    apr = Approval(
        entity_kind=entity_kind, party_id=party_id or "",
        payload=payload or {}, method=method or "POST",
        writer_url=writer_url or "", idempotency_key=idempotency_key or "",
        maker_user_id=uid, maker_role=role,
        status="PENDING_APPROVAL",
    ).model_dump()
    apr["user_id"] = uid
    apr["company_id"] = company_id
    try:
        await db.approvals.insert_one(dict(apr))
    except Exception as e:
        # Race on the unique idempotency index — return the existing row.
        if idempotency_key:
            existing = await db.approvals.find_one(
                {"user_id": uid, "company_id": company_id, "idempotency_key": idempotency_key},
                {"_id": 0},
            )
            if existing:
                return existing
        raise HTTPException(status_code=500, detail=f"Approval creation failed: {e}")

    await _audit(apr["id"], uid, company_id, "submit", uid, role,
                 note=f"Submitted {entity_kind}")

    if solo:
        return await _solo_owner_auto_execute(
            approval=apr, user=user, company_id=company_id, request=request,
        )
    apr.pop("_id", None)
    return apr


async def _solo_owner_auto_execute(*, approval: dict, user: dict,
                                    company_id: str, request: Request) -> dict:
    """One-shot solo-owner path: auto_approve + execute atomically."""
    aid = approval["id"]
    uid = user["user_id"]
    role = (user.get("effective_role") or "owner").lower()

    # CAS: PENDING_APPROVAL -> APPROVED (auto).
    now = now_utc().isoformat()
    upd = await db.approvals.find_one_and_update(
        {"id": aid, "user_id": uid, "company_id": company_id, "status": "PENDING_APPROVAL"},
        {"$set": {
            "status": "APPROVED",
            "checker_user_id": SOLO_OWNER_CHECKER,
            "checker_role": "owner",
            "checker_at": now,
            "auto_approved": True,
            "modified_at": now,
        }},
        return_document=True,
    )
    if not upd:
        # Race — someone else already advanced. Return current state.
        return await db.approvals.find_one({"id": aid}, {"_id": 0}) or approval

    await _audit(aid, uid, company_id, "auto_approve", uid, role,
                 note="Solo-owner auto-approval", metadata={"solo_owner": True})
    return await _execute_approved(approval_id=aid, user=user,
                                    company_id=company_id, request=request)


async def approve(*, approval_id: str, user: dict, company_id: str,
                   request: Request, note: str = "") -> dict:
    if not _can_approve(user):
        raise HTTPException(status_code=403, detail="Not permitted to approve")
    uid = user["user_id"]
    role = (user.get("effective_role") or user.get("role") or "").lower()
    apr = await db.approvals.find_one(
        {"id": approval_id, "user_id": uid, "company_id": company_id}, {"_id": 0}
    )
    if not apr:
        raise HTTPException(status_code=404, detail="Approval not found")
    if apr["status"] != "PENDING_APPROVAL":
        raise HTTPException(status_code=409,
                             detail=f"Cannot approve from status {apr['status']}")
    # Maker/checker separation (unless solo-owner, which uses auto-approve
    # via create_approval and never reaches this endpoint).
    if apr.get("maker_user_id") == uid:
        raise HTTPException(status_code=403, detail="Maker cannot approve own submission")

    now = now_utc().isoformat()
    upd = await db.approvals.find_one_and_update(
        {"id": approval_id, "user_id": uid, "company_id": company_id, "status": "PENDING_APPROVAL"},
        {"$set": {
            "status": "APPROVED",
            "checker_user_id": uid,
            "checker_role": role,
            "checker_at": now,
            "auto_approved": False,
            "modified_at": now,
        }},
        return_document=True,
    )
    if not upd:
        raise HTTPException(status_code=409, detail="Approval already advanced")
    await _audit(approval_id, uid, company_id, "approve", uid, role, note=note)
    return await _execute_approved(approval_id=approval_id, user=user,
                                    company_id=company_id, request=request)


async def reject(*, approval_id: str, user: dict, company_id: str,
                  reason: str) -> dict:
    if not _can_approve(user):
        raise HTTPException(status_code=403, detail="Not permitted to approve")
    if not (reason or "").strip():
        raise HTTPException(status_code=400, detail="Rejection reason is required")
    uid = user["user_id"]
    role = (user.get("effective_role") or "").lower()
    apr = await db.approvals.find_one(
        {"id": approval_id, "user_id": uid, "company_id": company_id}, {"_id": 0}
    )
    if not apr:
        raise HTTPException(status_code=404, detail="Approval not found")
    if apr["status"] != "PENDING_APPROVAL":
        raise HTTPException(status_code=409,
                             detail=f"Cannot reject from status {apr['status']}")
    if apr.get("maker_user_id") == uid:
        raise HTTPException(status_code=403, detail="Maker cannot reject own submission")
    now = now_utc().isoformat()
    upd = await db.approvals.find_one_and_update(
        {"id": approval_id, "user_id": uid, "company_id": company_id, "status": "PENDING_APPROVAL"},
        {"$set": {
            "status": "REJECTED", "checker_user_id": uid, "checker_role": role,
            "checker_at": now, "reject_reason": reason.strip(),
            "modified_at": now,
        }},
        return_document=True,
    )
    if not upd:
        raise HTTPException(status_code=409, detail="Approval already advanced")
    await _audit(approval_id, uid, company_id, "reject", uid, role, note=reason.strip())
    upd.pop("_id", None)
    return upd


async def withdraw(*, approval_id: str, user: dict, company_id: str,
                    reason: str = "") -> dict:
    uid = user["user_id"]
    role = (user.get("effective_role") or "").lower()
    apr = await db.approvals.find_one(
        {"id": approval_id, "user_id": uid, "company_id": company_id}, {"_id": 0}
    )
    if not apr:
        raise HTTPException(status_code=404, detail="Approval not found")
    if apr["status"] != "PENDING_APPROVAL":
        raise HTTPException(status_code=409,
                             detail=f"Cannot withdraw from status {apr['status']}")
    # Only the maker (or an owner with approve permission) may withdraw.
    if apr.get("maker_user_id") != uid and not _can_approve(user):
        raise HTTPException(status_code=403, detail="Only the maker (or an owner) may withdraw")
    now = now_utc().isoformat()
    upd = await db.approvals.find_one_and_update(
        {"id": approval_id, "user_id": uid, "company_id": company_id, "status": "PENDING_APPROVAL"},
        {"$set": {
            "status": "WITHDRAWN", "withdraw_reason": (reason or "").strip(),
            "modified_at": now,
        }},
        return_document=True,
    )
    if not upd:
        raise HTTPException(status_code=409, detail="Approval already advanced")
    await _audit(approval_id, uid, company_id, "withdraw", uid, role, note=(reason or "").strip())
    upd.pop("_id", None)
    return upd


async def edit_and_resubmit(*, approval_id: str, user: dict, company_id: str,
                             new_payload: dict, note: str = "",
                             request: Request) -> dict:
    """Edit a REJECTED or WITHDRAWN approval and resubmit as a new
    revision. Previous revisions are immutable — a new ApprovalRevision
    row is appended and status resets to PENDING_APPROVAL with
    revision_index incremented.
    """
    if not _can_submit(user):
        raise HTTPException(status_code=403, detail="Not permitted to submit approvals")
    uid = user["user_id"]
    role = (user.get("effective_role") or "").lower()
    apr = await db.approvals.find_one(
        {"id": approval_id, "user_id": uid, "company_id": company_id}, {"_id": 0}
    )
    if not apr:
        raise HTTPException(status_code=404, detail="Approval not found")
    if apr["status"] not in ("REJECTED", "WITHDRAWN"):
        raise HTTPException(status_code=409,
                             detail=f"Cannot edit-and-resubmit from status {apr['status']}")
    if apr.get("maker_user_id") != uid:
        raise HTTPException(status_code=403, detail="Only the original maker may edit-and-resubmit")

    new_index = int(apr.get("revision_index", 0)) + 1
    before = apr.get("payload") or {}
    rev = ApprovalRevision(
        approval_id=approval_id, revision_index=new_index,
        payload_before=before, payload_after=new_payload or {},
        diff=_diff_payloads(before, new_payload or {}),
        edited_by=uid, note=note or "",
    ).model_dump()
    rev["user_id"] = uid
    rev["company_id"] = company_id
    await db.approval_revisions.insert_one(rev)

    now = now_utc().isoformat()
    upd = await db.approvals.find_one_and_update(
        {"id": approval_id, "user_id": uid, "company_id": company_id,
         "status": {"$in": ["REJECTED", "WITHDRAWN"]}},
        {"$set": {
            "payload": new_payload or {},
            "status": "PENDING_APPROVAL",
            "revision_index": new_index,
            "latest_revision_id": rev["id"],
            "reject_reason": "", "withdraw_reason": "",
            "checker_user_id": "", "checker_role": "", "checker_at": "",
            "modified_at": now,
        }},
        return_document=True,
    )
    if not upd:
        raise HTTPException(status_code=409, detail="Approval already advanced")
    await _audit(approval_id, uid, company_id, "edit", uid, role,
                 note=note or "", metadata={"revision_index": new_index})

    # Solo-owner short-circuit still applies on resubmit.
    if await _is_solo_owner(user):
        return await _solo_owner_auto_execute(
            approval=upd, user=user, company_id=company_id, request=request,
        )
    upd.pop("_id", None)
    return upd


async def _execute_approved(*, approval_id: str, user: dict,
                             company_id: str, request: Request) -> dict:
    """Delegate to the domain writer. CAS guards against double-execution.
    On writer failure the approval transitions to EXECUTION_FAILED and
    the error text is preserved; the writer's own hook (if it ever fired)
    remains authoritative via its `ref_source_key` UNIQUE index.
    """
    uid = user["user_id"]
    role = (user.get("effective_role") or "").lower()
    apr = await db.approvals.find_one(
        {"id": approval_id, "user_id": uid, "company_id": company_id}, {"_id": 0}
    )
    if not apr:
        raise HTTPException(status_code=404, detail="Approval not found")
    if apr["status"] != "APPROVED":
        # Idempotent replay: return current state.
        apr.pop("_id", None)
        return apr

    try:
        result = await _delegate_writer(
            entity_kind=apr["entity_kind"], party_id=apr.get("party_id") or "",
            payload_dict=apr.get("payload") or {}, request=request, user=user,
        )
        entity_id = ""
        if isinstance(result, dict):
            entity_id = result.get("id") or result.get("invoice_id") or result.get("trip_id") or ""
        now = now_utc().isoformat()
        upd = await db.approvals.find_one_and_update(
            {"id": approval_id, "user_id": uid, "company_id": company_id, "status": "APPROVED"},
            {"$set": {"status": "POSTED", "entity_id": entity_id, "modified_at": now}},
            return_document=True,
        )
        await _audit(approval_id, uid, company_id, "execute", uid, role,
                     metadata={"entity_id": entity_id})
        out = upd or apr
        out.pop("_id", None)
        out["transaction"] = result if isinstance(result, dict) else {}
        return out
    except HTTPException as he:
        now = now_utc().isoformat()
        await db.approvals.update_one(
            {"id": approval_id, "user_id": uid, "company_id": company_id},
            {"$set": {"status": "EXECUTION_FAILED",
                       "execution_error": f"{he.status_code}: {he.detail}",
                       "modified_at": now}},
        )
        await _audit(approval_id, uid, company_id, "execute_fail", uid, role,
                     note=str(he.detail), metadata={"http_status": he.status_code})
        raise
    except Exception as e:
        now = now_utc().isoformat()
        await db.approvals.update_one(
            {"id": approval_id, "user_id": uid, "company_id": company_id},
            {"$set": {"status": "EXECUTION_FAILED", "execution_error": str(e),
                       "modified_at": now}},
        )
        await _audit(approval_id, uid, company_id, "execute_fail", uid, role, note=str(e))
        raise HTTPException(status_code=500, detail=f"Writer execution failed: {e}")


# ---------------------------------------------------------------------------
# Read helpers (used by the router).
# ---------------------------------------------------------------------------
async def list_approvals(*, user: dict, company_id: str,
                          status: Optional[str] = None,
                          entity_kind: Optional[str] = None,
                          include_all: bool = False,
                          limit: int = 200) -> list:
    uid = user["user_id"]
    q: dict = {"user_id": uid, "company_id": company_id}
    if status:
        q["status"] = status
    elif not include_all:
        q["status"] = {"$in": ["PENDING_APPROVAL", "REJECTED", "WITHDRAWN"]}
    if entity_kind:
        q["entity_kind"] = entity_kind
    cur = db.approvals.find(q, {"_id": 0}).sort("created_at", -1).limit(min(500, limit))
    return [d async for d in cur]


async def get_approval_detail(*, user: dict, company_id: str,
                               approval_id: str) -> dict:
    uid = user["user_id"]
    apr = await db.approvals.find_one(
        {"id": approval_id, "user_id": uid, "company_id": company_id}, {"_id": 0}
    )
    if not apr:
        raise HTTPException(status_code=404, detail="Approval not found")
    revisions = await db.approval_revisions.find(
        {"approval_id": approval_id, "user_id": uid, "company_id": company_id},
        {"_id": 0},
    ).sort("revision_index", 1).to_list(200)
    audits = await db.approval_audits.find(
        {"approval_id": approval_id, "user_id": uid, "company_id": company_id},
        {"_id": 0},
    ).sort("at", 1).to_list(500)
    return {"approval": apr, "revisions": revisions, "audits": audits}
