"""Iter150J · Approval Router — Maker-Checker HTTP surface.

Endpoints:
  GET    /api/approvals                 · list (queue) with filters
  GET    /api/approvals/{aid}           · detail (approval + revisions + audits)
  POST   /api/approvals                 · submit (create PENDING or solo-owner auto-execute)
  POST   /api/approvals/{aid}/approve   · checker approve → execute → POSTED
  POST   /api/approvals/{aid}/reject    · checker reject with reason
  POST   /api/approvals/{aid}/withdraw  · maker withdraw
  POST   /api/approvals/{aid}/resubmit  · maker edit REJECTED/WITHDRAWN + resubmit
  GET    /api/approvals/summary/pending · badge count

The router itself never touches FinTxn — it delegates to
`services_approvals` which then calls the frozen domain writers.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from auth import get_current_user
from company import _active_company_id
from db import db
from services_approvals import (
    create_approval, approve, reject, withdraw, edit_and_resubmit,
    list_approvals, get_approval_detail,
)

router = APIRouter(prefix="/api", tags=["approvals"])


@router.get("/approvals")
async def api_list_approvals(
    request: Request,
    status: Optional[str] = Query(None),
    entity_kind: Optional[str] = Query(None),
    include_all: bool = Query(False),
    limit: int = Query(200, ge=1, le=500),
    user=Depends(get_current_user),
):
    cid = await _active_company_id(request, user)
    return await list_approvals(
        user=user, company_id=cid, status=status,
        entity_kind=entity_kind, include_all=include_all, limit=limit,
    )


@router.get("/approvals/summary/pending")
async def api_pending_count(request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    count = await db.approvals.count_documents({
        "user_id": user["user_id"], "company_id": cid,
        "status": "PENDING_APPROVAL",
    })
    return {"count": count}


@router.get("/approvals/{aid}")
async def api_get_approval(aid: str, request: Request,
                            user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    return await get_approval_detail(user=user, company_id=cid, approval_id=aid)


@router.post("/approvals")
async def api_create_approval(request: Request, user=Depends(get_current_user)):
    """Create an approval envelope from the ORIGINAL blocked writer POST.

    Frontend axios interceptor sends:
      {
        "entity_kind": "trip"|"invoice"|"..._payment",
        "party_id":    "<sid|vid|mid|did>" or "",
        "method":      "POST",
        "writer_url":  "/api/...",
        "payload":     <original writer payload object>,
        "idempotency_key": "<original or derived UUID>"
      }
    """
    cid = await _active_company_id(request, user)
    body = await request.json()
    entity_kind = (body or {}).get("entity_kind") or ""
    party_id = (body or {}).get("party_id") or ""
    payload = (body or {}).get("payload") or {}
    method = (body or {}).get("method") or "POST"
    writer_url = (body or {}).get("writer_url") or ""
    idem = (body or {}).get("idempotency_key") or ""
    if not entity_kind:
        raise HTTPException(status_code=400, detail="entity_kind is required")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be an object")
    return await create_approval(
        user=user, company_id=cid, entity_kind=entity_kind, party_id=party_id,
        payload=payload, method=method, writer_url=writer_url,
        idempotency_key=idem, request=request,
    )


@router.post("/approvals/{aid}/approve")
async def api_approve(aid: str, request: Request,
                       user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    note = (body or {}).get("note") or ""
    return await approve(approval_id=aid, user=user, company_id=cid,
                         request=request, note=note)


@router.post("/approvals/{aid}/reject")
async def api_reject(aid: str, request: Request,
                      user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    reason = (body or {}).get("reason") or ""
    if not reason.strip():
        raise HTTPException(status_code=400, detail="reason is required")
    return await reject(approval_id=aid, user=user, company_id=cid, reason=reason)


@router.post("/approvals/{aid}/withdraw")
async def api_withdraw(aid: str, request: Request,
                        user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    reason = (body or {}).get("reason") or ""
    return await withdraw(approval_id=aid, user=user, company_id=cid, reason=reason)


@router.post("/approvals/{aid}/resubmit")
async def api_resubmit(aid: str, request: Request,
                        user=Depends(get_current_user)):
    """Edit a REJECTED or WITHDRAWN approval and resubmit as a new
    revision. Body: {payload: <new writer payload>, note?: "..."}
    """
    cid = await _active_company_id(request, user)
    body = await request.json()
    new_payload = (body or {}).get("payload") or {}
    note = (body or {}).get("note") or ""
    if not isinstance(new_payload, dict) or not new_payload:
        raise HTTPException(status_code=400, detail="payload is required")
    return await edit_and_resubmit(
        approval_id=aid, user=user, company_id=cid,
        new_payload=new_payload, note=note, request=request,
    )
