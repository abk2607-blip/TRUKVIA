"""Trip Template CRUD.

Templates are company-shared: every trip template is scoped by `company_id`
and any user with access to that company can read/apply/edit templates.
Creation stamps `created_by` for audit.
"""
from fastapi import APIRouter, HTTPException, Request, Depends
from db import db
from models import TripTemplate, now_utc, new_id
from auth import get_current_user
from company import _active_company_id

router = APIRouter(prefix="/api")


@router.get("/templates")
async def list_templates(request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    docs = await db.templates.find(
        {"company_id": cid, "is_active": True},
        {"_id": 0, "user_id": 0},
    ).sort("name", 1).to_list(500)
    return docs


@router.post("/templates")
async def create_template(payload: TripTemplate, request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    doc = payload.model_dump()
    doc["user_id"] = user["user_id"]
    doc["company_id"] = cid
    doc["created_by"] = user["user_id"]
    await db.templates.insert_one(doc)
    doc.pop("_id", None)
    doc.pop("user_id", None)
    return doc


@router.get("/templates/{tid}")
async def get_template(tid: str, request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    doc = await db.templates.find_one({"id": tid, "company_id": cid}, {"_id": 0, "user_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Template not found")
    return doc


@router.put("/templates/{tid}")
async def update_template(tid: str, payload: TripTemplate, request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    existing = await db.templates.find_one({"id": tid, "company_id": cid}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Template not found")
    upd = payload.model_dump()
    upd["id"] = tid
    upd["company_id"] = cid
    upd["created_by"] = existing.get("created_by", user["user_id"])
    upd["created_at"] = existing.get("created_at")
    await db.templates.update_one({"id": tid, "company_id": cid}, {"$set": upd})
    upd.pop("user_id", None)
    return upd


@router.delete("/templates/{tid}")
async def delete_template(tid: str, request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    r = await db.templates.delete_one({"id": tid, "company_id": cid})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"ok": True}
