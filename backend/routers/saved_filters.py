"""Iter57 — Saved Trip Filter Views (P1).

Small CRUD backing the "Save current filter" button on the Trip Log. Records
are strictly scoped to (user_id, company_id) — a saved view created in
Company A is never visible in Company B, even for the same user.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime, timezone

from db import db
from auth import get_current_user
from company import _active_company_id
from models import new_id

router = APIRouter(prefix="/api")


class SavedFilterCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    filter_state: Dict[str, Any] = Field(default_factory=dict)


@router.get("/saved-trip-filters")
async def list_saved_filters(request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    docs = await db.saved_trip_filters.find(
        {"user_id": user["user_id"], "company_id": cid},
        {"_id": 0},
    ).sort("created_at", -1).limit(50).to_list(50)
    return docs


@router.post("/saved-trip-filters")
async def create_saved_filter(payload: SavedFilterCreate, request: Request,
                              user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    doc = {
        "id": new_id("sf"),
        "user_id": user["user_id"],
        "company_id": cid,
        "name": name[:64],
        "filter_state": payload.filter_state or {},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.saved_trip_filters.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.delete("/saved-trip-filters/{fid}")
async def delete_saved_filter(fid: str, request: Request,
                              user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    r = await db.saved_trip_filters.delete_one(
        {"id": fid, "user_id": user["user_id"], "company_id": cid}
    )
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="saved filter not found")
    return {"ok": True}
