"""Master list of Other-Expenditure categories (Driver Food, Parking, Toll, ...).

Company-scoped. Seeded with a default set on first list-call so users can start
picking from the dropdown immediately, and are then free to add / rename / delete
their own categories.
"""
from fastapi import APIRouter, HTTPException, Request, Depends

from db import db
from models import ExpenditureType, DEFAULT_EXPENDITURE_TYPES, now_utc, new_id
from auth import get_current_user
from company import _active_company_id

router = APIRouter(prefix="/api")


async def _seed_defaults(user_id: str, company_id: str):
    """Seed the DEFAULT_EXPENDITURE_TYPES for this (user, company) pair if empty."""
    exists = await db.expenditure_types.count_documents(
        {"user_id": user_id, "company_id": company_id}
    )
    if exists:
        return
    now = now_utc().isoformat()
    bulk = []
    for name in DEFAULT_EXPENDITURE_TYPES:
        bulk.append({
            "id": new_id("etype_"),
            "name": name,
            "is_default": True,
            "user_id": user_id,
            "company_id": company_id,
            "created_at": now,
        })
    if bulk:
        await db.expenditure_types.insert_many(bulk)


@router.get("/expenditure-types")
async def list_expenditure_types(request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    await _seed_defaults(user["user_id"], cid)
    docs = await db.expenditure_types.find(
        {"user_id": user["user_id"], "company_id": cid},
        {"_id": 0, "user_id": 0},
    ).sort("name", 1).to_list(500)
    return docs


@router.post("/expenditure-types")
async def create_expenditure_type(payload: ExpenditureType, request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(400, "Name is required")
    existing = await db.expenditure_types.find_one(
        {"user_id": user["user_id"], "company_id": cid, "name": name},
        {"_id": 0, "user_id": 0},
    )
    if existing:
        return existing
    doc = payload.model_dump()
    doc["name"] = name
    doc["user_id"] = user["user_id"]
    doc["company_id"] = cid
    await db.expenditure_types.insert_one(doc)
    doc.pop("_id", None); doc.pop("user_id", None)
    return doc


@router.delete("/expenditure-types/{tid}")
async def delete_expenditure_type(tid: str, request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    await db.expenditure_types.delete_one(
        {"id": tid, "user_id": user["user_id"], "company_id": cid}
    )
    return {"ok": True}
