"""Multi-company scoping helpers."""
from fastapi import Request
from db import db
from models import Company, new_id


async def _get_or_create_default_company(user_id: str) -> dict:
    """Ensure at least one company exists for the user. Migrate legacy (no id) docs."""
    docs = await db.companies.find({"user_id": user_id}, {"_id": 0}).to_list(50)
    # Backfill missing id / is_default on legacy docs
    for d in docs:
        if not d.get("id"):
            new = new_id("co_")
            await db.companies.update_one({"user_id": user_id, "name": d.get("name", "")}, {"$set": {"id": new}})
            d["id"] = new
    if not docs:
        # Create an empty default
        c = Company(name="My Company", is_default=True).model_dump()
        c["user_id"] = user_id
        await db.companies.insert_one(c)
        return c
    # Ensure exactly one is_default
    if not any(d.get("is_default") for d in docs):
        first_id = docs[0]["id"]
        await db.companies.update_one({"user_id": user_id, "id": first_id}, {"$set": {"is_default": True}})
        docs[0]["is_default"] = True
    return next((d for d in docs if d.get("is_default")), docs[0])

async def _active_company_id(request: Request, user: dict) -> str:
    """Resolve which company the current request is scoped to.
    Priority: X-Company-Id header → user's default company → first company."""
    override = request.headers.get("x-company-id") or request.headers.get("X-Company-Id")
    if override:
        # Verify the company belongs to this user
        doc = await db.companies.find_one({"id": override, "user_id": user["user_id"]}, {"id": 1, "_id": 0})
        if doc:
            return override
    default = await _get_or_create_default_company(user["user_id"])
    return default["id"]

async def _backfill_company_id(user_id: str, company_id: str):
    """Assign the given company_id to any legacy doc lacking one for this user.

    Includes both transaction collections (trips/invoices/files/audit_logs/fuel)
    and master collections (customers/vehicles/drivers/products/parties). Every
    legacy master with no company_id is assigned to the caller's default company
    so multi-company isolation is enforceable going forward."""
    for coll in ("trips", "invoices", "files", "audit_logs", "fuel",
                 "customers", "vehicles", "drivers", "products", "parties"):
        await db[coll].update_many(
            {"user_id": user_id, "$or": [{"company_id": {"$exists": False}}, {"company_id": ""}]},
            {"$set": {"company_id": company_id}},
        )

async def _backfill_to_default(user_id: str):
    """Backfill legacy docs to the user's default company (idempotent, always safe)."""
    default = await _get_or_create_default_company(user_id)
    await _backfill_company_id(user_id, default["id"])
    return default["id"]
