"""Iter150F · Reconciliation Center — READ-ONLY router.

Three GET endpoints. Tenant-scoped. Business-date filtered. No writes.
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from auth import get_current_user
from company import _active_company_id
from services_reconciliation import summary, domain, mismatch

router = APIRouter(prefix="/api", tags=["Reconciliation"])


@router.get("/fin/reconciliation/summary")
async def get_summary(
    request: Request,
    from_: str = Query("", alias="from"),
    to: str = Query(""),
    user=Depends(get_current_user),
):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    return await summary(uid, cid, from_, to)


@router.get("/fin/reconciliation/domain/{domain_name}")
async def get_domain(
    domain_name: str,
    request: Request,
    from_: str = Query("", alias="from"),
    to: str = Query(""),
    page: int = Query(1, ge=1),
    size: int = Query(100, ge=1, le=500),
    user=Depends(get_current_user),
):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    try:
        return await domain(uid, cid, domain_name, from_, to,
                             page=page, size=size)
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))


@router.get("/fin/reconciliation/mismatch/{domain_name}/{key:path}")
async def get_mismatch(
    domain_name: str,
    key: str,
    request: Request,
    user=Depends(get_current_user),
):
    uid = user["user_id"]
    cid = await _active_company_id(request, user)
    try:
        return await mismatch(uid, cid, domain_name, key)
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex))
