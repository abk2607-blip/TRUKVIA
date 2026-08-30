from fastapi import APIRouter, HTTPException, Request, Response, Depends, UploadFile, File
from fastapi.responses import StreamingResponse
from typing import List, Optional
from datetime import datetime, timezone, timedelta
import io, os, uuid, secrets, re, requests, base64, logging

logger = logging.getLogger(__name__)

from db import db
from pydantic import BaseModel
from models import (
    Company, Customer, Expenses, Driver, Trip, Product, Party, Vehicle,
    MaintenanceLog, Fuel, Payment, Invoice, TeamMember, ROLE_PERMISSIONS,
    InvoiceCreateRequest, InvoiceUpdateRequest, PaymentAdd, FileRef, AuditLog,
    now_utc, new_id, LIVE_ONLY_FILTER,
)
from auth import get_current_user, _has_perm, require_perm
from company import (
    _active_company_id, _get_or_create_default_company,
    _backfill_company_id, _backfill_to_default,
)
from audit import _log_audit, _diff_dict
from services import (
    _compute_trip, _trip_billable, _recompute_invoice,
    _next_invoice_number, _next_invoice_number_for_company,
    _next_lr_number, _in_range, _vehicle_expiry_stats,
    _state_code, _gstin_checksum,
)

router = APIRouter(prefix="/api")

# Iter70 — Test-fixture name pattern. Pytest fixtures use these prefixes and
# they pollute the demo tenant. We hide them from paginated browse mode so
# real users see only their real customers. Q-searches still return matches
# (so tests can find their own fixtures).
FIXTURE_NAME_REGEX = r"^(IT\d+|TEST[_-]|IsoCoB|Iso_|BULK_|Bulk_|CUST_IT\d+|Cust_[a-f0-9]{6}|CUST_[a-f0-9]{6})"

# ==================== Customers ====================

@router.get("/customers")
async def list_customers(
    request: Request,
    user=Depends(get_current_user),
    with_balance: bool = False,
    q: Optional[str] = None,
    limit: Optional[int] = None,
    skip: Optional[int] = None,
    ids: Optional[str] = None,
    include_fixtures: bool = False,
):
    """Iter68 — server-side customer search + pagination.
    Iter70 — Test-fixture name filter (see FIXTURE_NAME_REGEX above).

    Backward compatibility contract:
      • When NONE of `q`, `limit`, `skip`, `ids` are provided → return a plain
        list of up to 20000 customers (unchanged legacy shape, so existing
        pages like Trips/Invoices/Reports keep working). Legacy path also
        hides fixture-named customers unless `include_fixtures=true`.
      • When ANY of those params are provided → return a paginated envelope:
          {"items": [...], "total": N, "has_more": bool, "limit": L, "skip": S}
        `q` performs case-insensitive partial match on name, phone, gstin,
        and customer_code. Tenant isolation (user_id + company_id) is always
        enforced. `ids` (comma-separated) forcibly includes those customers
        in the result set (used by pickers to keep the currently-selected
        customer visible even when it is outside the search page).
    """
    cid = await _active_company_id(request, user)
    await _backfill_to_default(user["user_id"])

    paginated_mode = any(v is not None for v in (q, limit, skip, ids))

    base_filter: dict = {"user_id": user["user_id"], "company_id": cid}
    # Iter70 — Hide pytest fixture customers from every listing (browse + q-search)
    # unless the caller explicitly opts in (`include_fixtures=true`) OR is
    # force-including specific ids (tests looking up their own fixture by id
    # need it visible).
    hide_fixtures_filter: dict = {
        **base_filter,
        "name": {"$not": {"$regex": FIXTURE_NAME_REGEX}},
    }
    proj = {"_id": 0, "user_id": 0}

    if not paginated_mode:
        # Legacy path — full list. Iter67 raised cap to 20000.
        # Note: fixture filter is intentionally NOT applied here so existing
        # code (tests, Reports, Invoices, InvoiceCreate, TripView) that
        # scans the full customer list continues to find its records.
        docs = await (
            db.customers.find(base_filter, proj)
            .sort("created_at", -1)
            .to_list(20000)
        )
    else:
        # Iter68 — search / paginated path
        page_limit = max(1, min(int(limit or 50), 200))
        page_skip = max(0, int(skip or 0))

        # Default paginated search filter — apply fixture hide unless opted-in.
        # Iter81 — When the user is actively typing a query (`q`), TRUST it and
        # skip the fixture-hide filter. Real trips can reference customers whose
        # names happen to match the fixture regex (e.g. imported with prefixes
        # like `CUST_IT56_…`); the purge keeps them alive because trips are
        # attached, so search must be able to find them or the user can't invoice.
        if include_fixtures or (q and q.strip()):
            search_filter = dict(base_filter)
        else:
            search_filter = dict(hide_fixtures_filter)
        id_list: list = []
        if ids:
            id_list = [s.strip() for s in ids.split(",") if s.strip()]

        if q:
            # Escape user input so regex metachars can't break the query
            safe = re.escape(q.strip())
            if safe:
                search_filter["$or"] = [
                    {"name":          {"$regex": safe, "$options": "i"}},
                    {"phone":         {"$regex": safe, "$options": "i"}},
                    {"gstin":         {"$regex": safe, "$options": "i"}},
                    {"customer_code": {"$regex": safe, "$options": "i"}},
                    {"id":            {"$regex": f"^{safe}", "$options": "i"}},
                ]
        elif id_list:
            # `ids` without `q` → restrict to just those customers (drop the
            # fixture filter — a picker fetching its selected customer by id
            # must succeed even if that customer's name happens to match a
            # fixture pattern). This is the picker-refresh contract used by
            # the Trip Form to fetch the currently-selected customer + its
            # ship_sites.
            search_filter = {**base_filter, "id": {"$in": id_list}}

        total = await db.customers.count_documents(search_filter)
        docs = await (
            db.customers.find(search_filter, proj)
            .sort("created_at", -1)
            .skip(page_skip)
            .limit(page_limit)
            .to_list(page_limit)
        )

        # Force-include specific IDs when a query is also present (keeps a
        # currently-selected customer visible in the picker even when it isn't
        # in the current search page). Deduped by id.
        if id_list and q:
            seen = {d["id"] for d in docs}
            missing = [x for x in id_list if x not in seen]
            if missing:
                extras = await db.customers.find(
                    {**base_filter, "id": {"$in": missing}}, proj
                ).to_list(len(missing))
                docs = extras + docs  # prepend forced IDs

        # Dedup while preserving order (belt & braces)
        seen: set = set()
        unique_docs: list = []
        for d in docs:
            if d["id"] in seen:
                continue
            seen.add(d["id"])
            unique_docs.append(d)
        docs = unique_docs

    if with_balance:
        # Iter86 — Exclude historical invoices from live balance
        invs = await db.invoices.find({"user_id": user["user_id"], "company_id": cid, **LIVE_ONLY_FILTER}, {"_id": 0, "id": 1, "customer_id": 1, "balance_due": 1, "total_amount": 1, "gross_total": 1, "amount_paid": 1}).to_list(5000)
        # Iter132a — attach effective_balance_due (CN reduces / DN increases).
        try:
            from services import _apply_effective_balance
            await _apply_effective_balance(invs, user["user_id"], cid)
        except Exception:
            pass
        bal_map: dict = {}
        for i in invs:
            k = i.get("customer_id")
            if not k:
                continue
            bal_map[k] = bal_map.get(k, 0.0) + float(i.get("effective_balance_due", i.get("balance_due", 0)))
        for c in docs:
            c["outstanding_balance"] = round(bal_map.get(c["id"], 0.0), 2)

    if paginated_mode:
        page_limit = max(1, min(int(limit or 50), 200))
        page_skip = max(0, int(skip or 0))
        return {
            "items": docs,
            "total": total,
            "has_more": (page_skip + len(docs)) < total,
            "limit": page_limit,
            "skip": page_skip,
        }
    return docs

@router.post("/customers")
async def create_customer(payload: Customer, request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    from dedup import (
        norm_gstin, norm_pan, norm_name, norm_phone,
        hard_conflict_response, soft_match_entry,
        read_override_request, is_override_authorised, ALLOWED_OVERRIDE_ROLES,
    )
    body = payload.model_dump()

    # ---- Iter127a · Duplicate protection ---- #
    override_req, override_reason = read_override_request(request, body)
    if override_req and not is_override_authorised(user):
        raise HTTPException(status_code=403, detail=(
            "Duplicate override requires Owner or Admin role."
        ))

    gstin_n = norm_gstin(body.get("gstin"))
    pan_n   = norm_pan(body.get("pan"))
    name_n  = norm_name(body.get("name"))
    phone_n = norm_phone(body.get("phone"))
    scope = {"user_id": user["user_id"], "company_id": cid, "is_deleted": {"$ne": True}}

    if not override_req:
        # HARD — GSTIN
        if gstin_n:
            hit = await db.customers.find_one({**scope, "gstin_norm": gstin_n}, {"_id": 0, "user_id": 0})
            if hit:
                raise HTTPException(status_code=409, detail=hard_conflict_response("gstin", "Customer", hit))
        # HARD — PAN (only when both sides have no GSTIN)
        if pan_n and not gstin_n:
            hit = await db.customers.find_one(
                {**scope, "pan_norm": pan_n, "$or": [{"gstin_norm": ""}, {"gstin_norm": {"$exists": False}}]},
                {"_id": 0, "user_id": 0},
            )
            if hit:
                raise HTTPException(status_code=409, detail=hard_conflict_response("pan", "Customer", hit))

        # Iter127a UAT · Customer NAME match — SOFT-BLOCK (409 bypassable via
        # `X-Confirm-Name-Match: allow` header, no role gate, no reason). The
        # UI opens the same DuplicateMasterModal with a 3rd button "Continue
        # Creating" that resends the POST with the confirm header, letting
        # legitimate branches / namesakes proceed.
        confirm_name = (request.headers.get("X-Confirm-Name-Match") or "").strip().lower()
        if name_n and confirm_name != "allow":
            hit = await db.customers.find_one({**scope, "name_norm": name_n}, {"_id": 0, "user_id": 0})
            if hit:
                raise HTTPException(status_code=409, detail=hard_conflict_response("name", "Customer", hit))

    # SOFT matches (name / phone) — attached to response, never block.
    soft: list[dict] = []
    if name_n:
        async for hit in db.customers.find({**scope, "name_norm": name_n}, {"_id": 0, "user_id": 0}).limit(3):
            soft.append(soft_match_entry("name", hit))
    if phone_n:
        async for hit in db.customers.find({**scope, "phone_norm": phone_n}, {"_id": 0, "user_id": 0}).limit(3):
            soft.append(soft_match_entry("phone", hit))

    body["user_id"]      = user["user_id"]
    body["company_id"]   = cid
    body["gstin_norm"]   = gstin_n
    body["pan_norm"]     = pan_n
    body["name_norm"]    = name_n
    body["phone_norm"]   = phone_n
    body["is_deleted"]   = False
    body.pop("duplicate_override_reason", None)
    await db.customers.insert_one(body)

    if override_req:
        try:
            await _log_audit(
                {"user_id": user["user_id"], "company_id": cid},
                "customer", "duplicate_override", body.get("id", ""), body.get("name", ""),
                override_reason, {"gstin": gstin_n, "pan": pan_n},
            )
        except Exception:
            pass

    body.pop("user_id", None); body.pop("_id", None)
    if soft:
        body["soft_matches"] = soft
    return body

@router.put("/customers/{cid}")
async def update_customer(cid: str, payload: Customer, request: Request, user=Depends(get_current_user)):
    company_id = await _active_company_id(request, user)
    doc = payload.model_dump()
    doc["id"] = cid
    doc["user_id"] = user["user_id"]
    doc["company_id"] = company_id
    await db.customers.update_one(
        {"id": cid, "user_id": user["user_id"], "company_id": company_id},
        {"$set": doc},
    )
    doc.pop("user_id", None)
    return doc

@router.delete("/customers/{cid}")
async def delete_customer(cid: str, request: Request, user=Depends(get_current_user)):
    company_id = await _active_company_id(request, user)
    await db.customers.delete_one({"id": cid, "user_id": user["user_id"], "company_id": company_id})
    return {"ok": True}


# ============================================================================
# Iter66 · Phase A — Ship-To Sites CRUD (nested under Customer)
# Stored as embedded array `ship_sites: [ShipSite]` on the Customer document.
# ============================================================================
from models import ShipSite as _ShipSite

async def _get_customer_or_404(user_id: str, cid: str, customer_id: str) -> dict:
    doc = await db.customers.find_one(
        {"id": customer_id, "user_id": user_id, "company_id": cid},
        {"_id": 0, "user_id": 0},
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Customer not found")
    return doc


@router.get("/customers/{cid}/ship-sites")
async def list_ship_sites(cid: str, request: Request, user=Depends(get_current_user),
                           active_only: bool = False):
    company_id = await _active_company_id(request, user)
    doc = await _get_customer_or_404(user["user_id"], company_id, cid)
    sites = doc.get("ship_sites") or []
    if active_only:
        sites = [s for s in sites if s.get("is_active") is not False]
    return {"items": sites, "total": len(sites)}


@router.post("/customers/{cid}/ship-sites")
async def create_ship_site(cid: str, payload: _ShipSite, request: Request,
                           user=Depends(get_current_user)):
    """Iter72 — Adds a Ship-To site to a customer.
    * Trims site_name; reject blank.
    * Dedup — if an ACTIVE ship-site with the same site_name (case-insensitive)
      already exists for this customer, return that existing site instead of
      creating a duplicate.
    * If it's the first site → auto-mark default.
    * Enforces single default per customer.
    """
    company_id = await _active_company_id(request, user)
    doc = await _get_customer_or_404(user["user_id"], company_id, cid)
    payload.site_name = (payload.site_name or "").strip()
    if not payload.site_name:
        raise HTTPException(status_code=400, detail="site_name is required")
    # Iter127c-invoice-shipto v3.1 (Feb 2026 · user-approved) — clean GSTIN
    # on save so future edits store the canonical form (no bulk migration).
    from ship_to_resolver import normalize_gstin, apply_gstin_state_derivation
    payload.gstin = normalize_gstin(payload.gstin)
    # Iter127c-invoice-shipto v3.2 (Feb 2026 · user-approved) — when GSTIN
    # is valid, auto-derive State + State Code so users don't have to enter
    # them manually. Never overwrites a manually-entered conflicting value.
    _derived = apply_gstin_state_derivation({
        "gstin": payload.gstin,
        "state_code": payload.state_code,
        "state": payload.state,
    })
    payload.state_code = _derived["state_code"]
    payload.state = _derived["state"]

    existing = doc.get("ship_sites") or []
    key = payload.site_name.casefold()
    dup = next(
        (s for s in existing
         if (s.get("site_name") or "").strip().casefold() == key
         and s.get("is_active") is not False),
        None,
    )
    if dup:
        return dup

    new_site = payload.model_dump()
    # Enforce single default — if this one is default, clear others.
    if new_site.get("is_default"):
        for s in existing:
            s["is_default"] = False
    # If it's the first site, auto-mark default for better UX.
    if not existing:
        new_site["is_default"] = True
    existing.append(new_site)
    await db.customers.update_one(
        {"id": cid, "user_id": user["user_id"], "company_id": company_id},
        {"$set": {"ship_sites": existing}},
    )
    return new_site


@router.put("/customers/{cid}/ship-sites/{sid}")
async def update_ship_site(cid: str, sid: str, payload: _ShipSite, request: Request,
                            user=Depends(get_current_user)):
    company_id = await _active_company_id(request, user)
    doc = await _get_customer_or_404(user["user_id"], company_id, cid)
    sites = doc.get("ship_sites") or []
    idx = next((i for i, s in enumerate(sites) if s.get("id") == sid), -1)
    if idx == -1:
        raise HTTPException(status_code=404, detail="Ship site not found")
    updated = payload.model_dump()
    updated["id"] = sid  # never let the id change
    # Iter127c-invoice-shipto v3.1 (Feb 2026 · user-approved) — clean GSTIN
    # on save so future edits store the canonical form (no bulk migration).
    from ship_to_resolver import normalize_gstin, apply_gstin_state_derivation
    updated["gstin"] = normalize_gstin(updated.get("gstin"))
    # Iter127c-invoice-shipto v3.2 (Feb 2026 · user-approved) — GSTIN-derived
    # State / State Code auto-fill (blank fields only; never overwrites).
    apply_gstin_state_derivation(updated)
    # Enforce single default
    if updated.get("is_default"):
        for i, s in enumerate(sites):
            if i != idx:
                s["is_default"] = False
    sites[idx] = updated
    await db.customers.update_one(
        {"id": cid, "user_id": user["user_id"], "company_id": company_id},
        {"$set": {"ship_sites": sites}},
    )
    return updated


@router.delete("/customers/{cid}/ship-sites/{sid}")
async def delete_ship_site(cid: str, sid: str, request: Request,
                            user=Depends(get_current_user)):
    """Soft-delete a ship site by setting is_active=False.  Never hard-deletes
    because historical Trips may reference it by ship_site_id."""
    company_id = await _active_company_id(request, user)
    doc = await _get_customer_or_404(user["user_id"], company_id, cid)
    sites = doc.get("ship_sites") or []
    idx = next((i for i, s in enumerate(sites) if s.get("id") == sid), -1)
    if idx == -1:
        raise HTTPException(status_code=404, detail="Ship site not found")
    sites[idx]["is_active"] = False
    # If this was the default, pick another active one as default automatically.
    if sites[idx].get("is_default"):
        sites[idx]["is_default"] = False
        for s in sites:
            if s.get("is_active") is not False and not s.get("is_default"):
                s["is_default"] = True
                break
    await db.customers.update_one(
        {"id": cid, "user_id": user["user_id"], "company_id": company_id},
        {"$set": {"ship_sites": sites}},
    )
    return {"ok": True}



# ============================================================================
# Customer Transaction History (Iter36) — myBillBook-style single-screen ledger
# ============================================================================

@router.get("/customers/{cid}/transactions")
async def customer_transactions(
    cid: str,
    request: Request,
    user=Depends(get_current_user),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    invoice_status: Optional[str] = None,        # all | pending | invoiced
    payment_status: Optional[str] = None,        # all | unpaid | partial | paid
    vehicle_number: Optional[str] = None,
    product_id: Optional[str] = None,
    from_location: Optional[str] = None,
    to_location: Optional[str] = None,
    txn_type: Optional[str] = None,              # all | trip | invoice | payment
):
    company_id = await _active_company_id(request, user)
    customer = await db.customers.find_one({"id": cid, "user_id": user["user_id"], "company_id": company_id}, {"_id": 0})
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    # Base trip filter
    trip_q: dict = {"user_id": user["user_id"], "company_id": company_id, "customer_id": cid}
    if date_from:
        trip_q.setdefault("date", {})["$gte"] = date_from
    if date_to:
        trip_q.setdefault("date", {})["$lte"] = date_to
    if invoice_status and invoice_status != "all":
        trip_q["status"] = invoice_status
    if vehicle_number:
        trip_q["vehicle_number"] = vehicle_number.upper()
    if product_id:
        trip_q["product_id"] = product_id
    if from_location:
        trip_q["from_location"] = {"$regex": f"^{from_location}", "$options": "i"}
    if to_location:
        trip_q["to_location"] = {"$regex": f"^{to_location}", "$options": "i"}

    trips = await db.trips.find(trip_q, {"_id": 0, "user_id": 0}).sort([("date", -1), ("created_at", -1)]).to_list(2000)

    # Invoices for this customer
    inv_q: dict = {"user_id": user["user_id"], "company_id": company_id, "customer_id": cid}
    if date_from:
        inv_q.setdefault("date", {})["$gte"] = date_from
    if date_to:
        inv_q.setdefault("date", {})["$lte"] = date_to
    if payment_status and payment_status != "all":
        inv_q["payment_status"] = payment_status
    invoices = await db.invoices.find(inv_q, {"_id": 0, "user_id": 0}).sort("date", -1).to_list(2000)

    # Iter132c C1 · R1 — attach effective totals (CN reduces / DN increases)
    # WITHOUT mutating persisted invoice.balance_due / total_amount. Existing
    # keys stay raw for back-compat; effective siblings are additive.
    try:
        from services import _apply_effective_balance
        await _apply_effective_balance(invoices, user["user_id"], company_id)
    except Exception:
        pass

    # Payments from invoices
    payments = []
    for inv in invoices:
        for p in (inv.get("payments") or []):
            payments.append({
                **p,
                "invoice_id": inv["id"],
                "invoice_number": inv.get("invoice_number", ""),
            })
    payments.sort(key=lambda p: p.get("date", ""), reverse=True)

    # Summary aggregates
    total_qty = sum(float(t.get("tons", 0)) for t in trips)
    total_freight = sum(float(t.get("freight_amount", 0)) for t in trips)
    total_diesel_received = sum(float(t.get("customer_diesel_received", 0)) for t in trips)
    total_advances = sum(float(t.get("customer_advance_received", 0)) for t in trips)
    total_shortage = sum(float(t.get("shortage_amount", 0)) for t in trips)
    total_excess = sum(float(t.get("excess_amount", 0)) for t in trips)
    total_halting = sum(float(t.get("halting_amount", 0)) for t in trips)
    total_billed = sum(float(inv.get("total_amount", inv.get("gross_total", 0))) for inv in invoices)
    total_billed_effective = sum(float(inv.get("effective_total_amount", inv.get("total_amount", inv.get("gross_total", 0)))) for inv in invoices)
    total_received = sum(float(inv.get("amount_paid", 0)) for inv in invoices)
    outstanding = sum(float(inv.get("balance_due", 0)) for inv in invoices)
    outstanding_effective = sum(float(inv.get("effective_balance_due", inv.get("balance_due", 0))) for inv in invoices)
    total_credits = sum(float(inv.get("credits_total", 0)) for inv in invoices)
    total_debits = sum(float(inv.get("debits_total", 0)) for inv in invoices)
    # Uninvoiced billable freight (pending trips)
    total_pending_freight = sum(_trip_billable(t) for t in trips if t.get("status") != "invoiced")

    # Aging buckets (based on invoice date vs today) — raw uses balance_due; effective uses CN/DN-adjusted balance
    today = datetime.now(timezone.utc).date()
    aging = {"0_30": 0.0, "31_60": 0.0, "61_90": 0.0, "90_plus": 0.0}
    aging_effective = {"0_30": 0.0, "31_60": 0.0, "61_90": 0.0, "90_plus": 0.0}
    for inv in invoices:
        bal = float(inv.get("balance_due", 0))
        bal_eff = float(inv.get("effective_balance_due", bal))
        if bal <= 0 and bal_eff <= 0:
            continue
        try:
            dt = datetime.fromisoformat(inv.get("date", ""))
        except Exception:
            try:
                dt = datetime.strptime(inv.get("date", ""), "%Y-%m-%d")
            except Exception:
                continue
        days = (today - dt.date()).days
        if days <= 30:
            bucket = "0_30"
        elif days <= 60:
            bucket = "31_60"
        elif days <= 90:
            bucket = "61_90"
        else:
            bucket = "90_plus"
        if bal > 0:
            aging[bucket] += bal
        if bal_eff > 0:
            aging_effective[bucket] += bal_eff
    aging = {k: round(v, 2) for k, v in aging.items()}
    aging_effective = {k: round(v, 2) for k, v in aging_effective.items()}

    summary = {
        "trip_count": len(trips),
        "total_qty": round(total_qty, 3),
        "total_freight": round(total_freight, 2),
        "total_diesel_received": round(total_diesel_received, 2),
        "total_advances": round(total_advances, 2),
        "total_shortage": round(total_shortage, 2),
        "total_excess": round(total_excess, 2),
        "total_halting": round(total_halting, 2),
        "total_billed": round(total_billed, 2),
        "total_billed_effective": round(total_billed_effective, 2),
        "total_received": round(total_received, 2),
        "outstanding": round(outstanding, 2),
        "outstanding_raw": round(outstanding, 2),
        "outstanding_effective": round(outstanding_effective, 2),
        "credits_total": round(total_credits, 2),
        "debits_total": round(total_debits, 2),
        "total_pending_uninvoiced": round(total_pending_freight, 2),
        "invoice_count": len(invoices),
        "payment_count": len(payments),
        "aging": aging,
        "aging_effective": aging_effective,
    }

    # Unified transaction list (sorted DESC by date)
    txns: list = []
    if not txn_type or txn_type in ("all", "trip"):
        for t in trips:
            txns.append({
                "type": "trip",
                "date": t.get("date"),
                "id": t.get("id"),
                "ref": t.get("lr_number") or "—",
                "vehicle_number": t.get("vehicle_number"),
                "driver_name": t.get("driver_name"),
                "from_location": t.get("from_location"),
                "to_location": t.get("to_location"),
                "load_details": t.get("load_details"),
                "tons": t.get("tons"),
                "amount": t.get("freight_amount"),
                "customer_diesel_received": t.get("customer_diesel_received", 0),
                "customer_advance_received": t.get("customer_advance_received", 0),
                "shortage_amount": t.get("shortage_amount", 0),
                "excess_amount": t.get("excess_amount", 0),
                "halting_amount": t.get("halting_amount", 0),
                "status": t.get("status"),   # pending | invoiced
                "invoice_id": t.get("invoice_id"),
                "created_at": t.get("created_at"),
            })
    if not txn_type or txn_type in ("all", "invoice"):
        for inv in invoices:
            txns.append({
                "type": "invoice",
                "date": inv.get("date"),
                "id": inv.get("id"),
                "ref": inv.get("invoice_number"),
                "amount": inv.get("total_amount") or inv.get("gross_total"),
                "amount_paid": inv.get("amount_paid", 0),
                "balance_due": inv.get("balance_due", 0),
                # Iter132c C1 — additive effective siblings; existing keys unchanged.
                "effective_total_amount": inv.get("effective_total_amount", inv.get("total_amount") or inv.get("gross_total")),
                "effective_balance_due": inv.get("effective_balance_due", inv.get("balance_due", 0)),
                "credits_total": inv.get("credits_total", 0),
                "debits_total": inv.get("debits_total", 0),
                "status": inv.get("payment_status"),   # unpaid | partial | paid
                "due_date": inv.get("due_date"),
                "created_at": inv.get("created_at"),
            })
    if not txn_type or txn_type in ("all", "payment"):
        for p in payments:
            txns.append({
                "type": "payment",
                "date": p.get("date"),
                "id": f"{p.get('invoice_id')}_{p.get('date')}_{p.get('amount')}",
                "ref": p.get("invoice_number"),
                "amount": p.get("amount"),
                "mode": p.get("mode"),
                "note": p.get("note"),
                "invoice_id": p.get("invoice_id"),
                "status": "received",
            })
    txns.sort(key=lambda t: (t.get("date") or "", t.get("created_at") or ""), reverse=True)

    return {
        "customer": customer,
        "summary": summary,
        "transactions": txns,
        "trips": trips,
        "invoices": invoices,
        "payments": payments,
    }


@router.get("/customers/{cid}/statement.pdf")
async def customer_statement_pdf(
    cid: str,
    request: Request,
    user=Depends(get_current_user),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    company_id = await _active_company_id(request, user)
    company = await db.companies.find_one({"id": company_id, "user_id": user["user_id"]}, {"_id": 0}) or {}
    customer = await db.customers.find_one({"id": cid, "user_id": user["user_id"], "company_id": company_id}, {"_id": 0})
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    # Reuse the aggregation
    trip_q: dict = {"user_id": user["user_id"], "company_id": company_id, "customer_id": cid}
    if date_from:
        trip_q.setdefault("date", {})["$gte"] = date_from
    if date_to:
        trip_q.setdefault("date", {})["$lte"] = date_to
    trips = await db.trips.find(trip_q, {"_id": 0, "user_id": 0}).sort("date", -1).to_list(2000)
    invoices = await db.invoices.find({"user_id": user["user_id"], "company_id": company_id, "customer_id": cid, **({"date": trip_q["date"]} if "date" in trip_q else {})}, {"_id": 0, "user_id": 0}).sort("date", -1).to_list(2000)

    # Iter132c C1 · R4 — attach effective note totals for the "Adjustments" line.
    # All existing summary/table cells stay raw (byte-identical output);
    # a single small "Adjustments: −CN ₹X / +DN ₹Y" line is added below.
    try:
        from services import _apply_effective_balance
        await _apply_effective_balance(invoices, user["user_id"], company_id)
    except Exception:
        pass

    total_qty = sum(float(t.get("tons", 0)) for t in trips)
    total_freight = sum(float(t.get("freight_amount", 0)) for t in trips)
    total_billed = sum(float(inv.get("total_amount", inv.get("gross_total", 0))) for inv in invoices)
    total_received = sum(float(inv.get("amount_paid", 0)) for inv in invoices)
    outstanding = sum(float(inv.get("balance_due", 0)) for inv in invoices)
    total_credits = sum(float(inv.get("credits_total", 0)) for inv in invoices)
    total_debits = sum(float(inv.get("debits_total", 0)) for inv in invoices)

    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from pdf._base import _UNI_FONT, _UNI_FONT_BOLD, _num_to_words_inr
    from pdf.ledger import _logo_flowable, NumberedCanvas
    buf = io.BytesIO()
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=12 * mm, bottomMargin=16 * mm)
    story: list = []

    ACCENT = colors.HexColor("#B45309")
    INK    = colors.HexColor("#111827")
    MUTED  = colors.HexColor("#6B7280")
    BORDER = colors.HexColor("#D1D5DB")

    body_st  = ParagraphStyle("sb", parent=styles["Normal"], fontName=_UNI_FONT,      fontSize=9,  textColor=INK,   leading=12)
    small_st = ParagraphStyle("ss", parent=styles["Normal"], fontName=_UNI_FONT,      fontSize=8,  textColor=INK,   leading=10)
    muted_st = ParagraphStyle("sm", parent=styles["Normal"], fontName=_UNI_FONT,      fontSize=8,  textColor=MUTED, leading=10)
    label_st = ParagraphStyle("sl", parent=styles["Normal"], fontName=_UNI_FONT_BOLD, fontSize=7,  textColor=MUTED, leading=9, spaceAfter=1)
    hero_st  = ParagraphStyle("sh", parent=styles["Heading1"], fontName=_UNI_FONT_BOLD, fontSize=16, textColor=ACCENT, alignment=2, leading=20)
    title_st = ParagraphStyle("t", parent=styles["Title"], fontName=_UNI_FONT_BOLD, fontSize=15, leading=18)  # kept for legacy consumers
    hdr_st = ParagraphStyle("h", parent=styles["Normal"], fontName=_UNI_FONT, fontSize=10, textColor=colors.grey)  # kept for legacy consumers

    # Iter133 L2b · Branded header (logo + company info + hero band).
    _co       = company or {}
    _co_gst   = (_co.get("gstin") or "").strip() or "—"
    _co_state = (_co.get("state") or "").strip() or "—"
    company_lines = [
        Paragraph(f"<b>{_co.get('name','')}</b>", body_st),
        Paragraph(_co.get("address", ""), small_st),
        Paragraph(f"GSTIN: {_co_gst} · State: {_co_state}", muted_st),
    ]
    header_tbl = Table(
        [[_logo_flowable(_co), company_lines, [Paragraph("CUSTOMER<br/>STATEMENT", hero_st)]]],
        colWidths=[42 * mm, 90 * mm, 46 * mm],
    )
    header_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(header_tbl)
    story.append(Spacer(1, 4 * mm))

    # Accent divider
    div = Table([[""]], colWidths=[178 * mm], rowHeights=[3])
    div.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), ACCENT)]))
    story.append(div)
    story.append(Spacer(1, 3 * mm))

    # Bill-To + Period card
    cust_lines = [
        Paragraph("BILL TO", label_st),
        Paragraph(f"<b>{customer.get('name','')}</b>", body_st),
        Paragraph(f"GSTIN: {customer.get('gstin') or '—'}", small_st),
        Paragraph(f"Phone: {customer.get('phone') or '—'} · State: {customer.get('state') or '—'}", small_st),
        Paragraph(customer.get("address", "") or "", small_st),
    ]
    period_lines = [
        Paragraph("STATEMENT PERIOD", label_st),
        Paragraph(f"<b>{date_from or 'Beginning'}</b> to <b>{date_to or 'Today'}</b>", body_st),
        Spacer(1, 2 * mm),
        Paragraph("OUTSTANDING", label_st),
        Paragraph(
            f"<b>₹ {outstanding:,.2f}</b>",
            ParagraphStyle("scb", parent=body_st, fontName=_UNI_FONT_BOLD, fontSize=13, textColor=ACCENT),
        ),
    ]
    info_tbl = Table([[cust_lines, period_lines]], colWidths=[110 * mm, 68 * mm])
    info_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(info_tbl)
    story.append(Spacer(1, 4 * mm))

    # Summary block
    smy = [
        ["Trips", str(len(trips)), "Qty (MT)", f"{total_qty:,.3f}"],
        ["Freight Booked", f"₹{total_freight:,.2f}", "Amount Billed", f"₹{total_billed:,.2f}"],
        ["Amount Received", f"₹{total_received:,.2f}", "Outstanding", f"₹{outstanding:,.2f}"],
    ]
    st = Table(smy, hAlign="LEFT", colWidths=[35 * mm, 45 * mm, 35 * mm, 45 * mm])
    st.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), _UNI_FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f3f4f6")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#f3f4f6")),
        ("FONTNAME", (0, 0), (0, -1), _UNI_FONT_BOLD),
        ("FONTNAME", (2, 0), (2, -1), _UNI_FONT_BOLD),
    ]))
    story.append(st)

    # Iter132c C1 · R4 — small "Adjustments" line only when notes exist.
    if total_credits > 0 or total_debits > 0:
        adj_st = ParagraphStyle("adj", parent=styles["Normal"], fontName=_UNI_FONT, fontSize=9, textColor=colors.HexColor("#374151"))
        story.append(Spacer(1, 4))
        story.append(Paragraph(
            f"Adjustments: −CN ₹{total_credits:,.2f} / +DN ₹{total_debits:,.2f}",
            adj_st,
        ))

    story.append(Spacer(1, 12))

    # Trip table
    story.append(Paragraph("<b>Trip Sheets</b>", styles["Heading3"]))
    trip_rows = [["Date", "LR No.", "Vehicle", "Route", "MT", "Freight", "Status"]]
    for t in trips:
        trip_rows.append([
            t.get("date", ""), t.get("lr_number", "") or "—", t.get("vehicle_number", ""),
            f"{t.get('from_location', '') or '?'} → {t.get('to_location', '') or '?'}",
            f"{float(t.get('tons', 0)):.2f}",
            f"₹{float(t.get('freight_amount', 0)):,.2f}",
            t.get("status", "").upper(),
        ])
    tt = Table(trip_rows, hAlign="LEFT", repeatRows=1, colWidths=[22 * mm, 26 * mm, 24 * mm, 44 * mm, 14 * mm, 26 * mm, 18 * mm])
    tt.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), _UNI_FONT_BOLD),
        ("FONTNAME", (0, 1), (-1, -1), _UNI_FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
        ("ALIGN", (4, 0), (5, -1), "RIGHT"),
    ]))
    story.append(tt)
    story.append(Spacer(1, 10))

    # Invoice table
    story.append(Paragraph("<b>Invoices</b>", styles["Heading3"]))
    inv_rows = [["Date", "Invoice #", "Total", "Paid", "Balance", "Status"]]
    for i in invoices:
        inv_rows.append([
            i.get("date", ""), i.get("invoice_number", ""),
            f"₹{float(i.get('total_amount') or i.get('gross_total', 0)):,.2f}", f"₹{float(i.get('amount_paid', 0)):,.2f}",
            f"₹{float(i.get('balance_due', 0)):,.2f}", str(i.get("payment_status", "")).upper(),
        ])
    it = Table(inv_rows, hAlign="LEFT", repeatRows=1, colWidths=[22 * mm, 30 * mm, 28 * mm, 28 * mm, 28 * mm, 22 * mm])
    it.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), _UNI_FONT_BOLD),
        ("FONTNAME", (0, 1), (-1, -1), _UNI_FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
        ("ALIGN", (2, 0), (4, -1), "RIGHT"),
    ]))
    story.append(it)

    # ============================================================
    # Iter133 L2 · Balance Bridge + Adjustments table
    # Presentation-only. Uses one additional read cursor scoped by
    # {user_id, company_id, customer_id, status:"issued"} — mirrors
    # L1 semantics. Cancelled/draft notes excluded.
    # ============================================================
    notes_q = {
        "user_id": user["user_id"], "company_id": company_id,
        "customer_id": cid, "status": "issued",
    }
    if "date" in trip_q:
        # Reuse period filter for consistency with the trips/invoices view.
        _dq = trip_q["date"]
        _nq = {}
        if "$gte" in _dq: _nq["$gte"] = _dq["$gte"]
        if "$lte" in _dq: _nq["$lte"] = _dq["$lte"]
        if _nq: notes_q["note_date"] = _nq
    issued_notes = await db.credit_debit_notes.find(
        notes_q,
        {"_id": 0, "id": 1, "kind": 1, "note_date": 1, "note_number": 1,
         "total_amount": 1, "invoice_number_snapshot": 1, "reason_code": 1},
    ).sort("note_date", 1).to_list(5000)
    cn_notes = [n for n in issued_notes if n.get("kind") == "credit"]
    dn_notes = [n for n in issued_notes if n.get("kind") == "debit"]
    cn_sum = round(sum(float(n.get("total_amount") or 0) for n in cn_notes), 2)
    dn_sum = round(sum(float(n.get("total_amount") or 0) for n in dn_notes), 2)

    if issued_notes:
        story.append(Spacer(1, 12))
        story.append(Paragraph("<b>Balance Bridge</b>", styles["Heading3"]))
        bridge_rows = [
            ["Original Invoiced Total",            f"₹{total_billed:,.2f}"],
            [f"Less: Credit Notes ({len(cn_notes)})", f"− ₹{cn_sum:,.2f}"],
            [f"Add: Debit Notes ({len(dn_notes)})",   f"+ ₹{dn_sum:,.2f}"],
            [f"Less: Payments Received",              f"− ₹{total_received:,.2f}"],
            ["Balance Due",                        f"₹{outstanding:,.2f}"],
        ]
        bt = Table(bridge_rows, hAlign="LEFT", colWidths=[100 * mm, 60 * mm])
        bt.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), _UNI_FONT),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#FEF3C7")),
            ("FONTNAME", (0, -1), (-1, -1), _UNI_FONT_BOLD),
            ("TEXTCOLOR", (0, -1), (-1, -1), colors.HexColor("#B45309")),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ]))
        story.append(bt)
        story.append(Spacer(1, 10))

        story.append(Paragraph("<b>Adjustments (Credit / Debit Notes)</b>", styles["Heading3"]))
        adj_hdr = ["Date", "Note #", "Type", "Ref Invoice", "Reason", "Amount"]
        adj_rows = [adj_hdr]
        for n in issued_notes:
            adj_rows.append([
                n.get("note_date", ""),
                n.get("note_number", ""),
                "CN" if n.get("kind") == "credit" else "DN",
                n.get("invoice_number_snapshot", "") or "—",
                (n.get("reason_code", "") or "").replace("_", " "),
                f"₹{float(n.get('total_amount') or 0):,.2f}",
            ])
        at = Table(adj_rows, hAlign="LEFT", repeatRows=1,
                   colWidths=[22 * mm, 32 * mm, 12 * mm, 34 * mm, 40 * mm, 22 * mm])
        astyle = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), _UNI_FONT_BOLD),
            ("FONTNAME", (0, 1), (-1, -1), _UNI_FONT),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
            ("ALIGN", (5, 0), (5, -1), "RIGHT"),
        ]
        # Row tint by kind
        for i, n in enumerate(issued_notes, start=1):
            if n.get("kind") == "credit":
                astyle.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#FEF2F2")))
            else:
                astyle.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#EFF6FF")))
        at.setStyle(TableStyle(astyle))
        story.append(at)

    # Iter133 L2b · Amount-in-Words + Authorised Signatory before build.
    story.append(Spacer(1, 6 * mm))
    _bal_words = _num_to_words_inr(abs(float(outstanding)))
    story.append(Paragraph(
        f"<b>Amount in Words:</b> {_bal_words} ({'Dr' if float(outstanding) >= 0 else 'Cr'})",
        small_st,
    ))
    story.append(Spacer(1, 10 * mm))
    _sig = Table([[
        "",
        [Paragraph(f"For <b>{_co.get('name','')}</b>", body_st),
         Spacer(1, 10 * mm),
         Paragraph("Authorised Signatory", small_st)],
    ]], colWidths=[110 * mm, 68 * mm])
    _sig.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(_sig)

    # Signatory + footer
    story.append(Spacer(1, 12))
    from pdf.ledger import NumberedCanvas as _NC
    doc.build(story, canvasmaker=_NC)
    buf.seek(0)
    fname = f"statement_{(customer.get('name', 'customer')).replace(' ', '_')}.pdf"
    return StreamingResponse(buf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{fname}"'})


def _public_base_url(request):
    """Return the public HTTPS base URL for building share links. Reads frontend/.env if backend env is missing."""
    url = os.environ.get("REACT_APP_BACKEND_URL") or os.environ.get("PUBLIC_BASE_URL")
    if not url:
        try:
            with open("/app/frontend/.env", "r") as f:
                for line in f:
                    if line.startswith("REACT_APP_BACKEND_URL="):
                        url = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
        except Exception:
            pass
    if not url:
        url = str(request.base_url).rstrip("/")
    if not url.startswith("http"):
        url = f"https://{url}"
    return url.rstrip("/")


@router.post("/customers/{cid}/share-statement")
async def share_customer_statement(
    cid: str,
    request: Request,
    user=Depends(get_current_user),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    """Uploads the customer statement PDF to public storage and returns a WhatsApp deeplink."""
    # Build the PDF using the same route logic then persist to storage.
    resp = await customer_statement_pdf(cid, request, user, date_from, date_to)
    # Read bytes back from the StreamingResponse
    body_bytes = b""
    async for chunk in resp.body_iterator:
        body_bytes += chunk

    company_id = await _active_company_id(request, user)
    company = await db.companies.find_one({"id": company_id, "user_id": user["user_id"]}, {"_id": 0}) or {}
    customer = await db.customers.find_one({"id": cid, "user_id": user["user_id"], "company_id": company_id}, {"_id": 0}) or {}

    obj_path = f"lr_shares/{user['user_id']}/statement_{cid}_{secrets.token_hex(4)}.pdf"
    try:
        from storage_client import put_object
        put_object(obj_path, body_bytes, "application/pdf")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Upload failed: {e}")

    frontend_base = _public_base_url(request)
    public_url = f"{frontend_base}/api/files/public/{obj_path}"

    msg = (
        f"*Customer Statement — {company.get('name', 'Our Company')}*\n"
        f"To: {customer.get('name', '')}\n"
        f"Period: {date_from or 'all'} → {date_to or 'today'}\n\n"
        f"Download statement PDF: {public_url}"
    )
    import urllib.parse
    return {
        "public_url": public_url,
        "whatsapp_url": f"https://wa.me/?text={urllib.parse.quote(msg)}",
        "whatsapp_text": msg,
    }


# ============================================================================
# Iter37 — Bulk WhatsApp Payment Reminders + Monthly Balances + Add Payment
# ============================================================================

@router.get("/customers/bulk-reminder")
async def bulk_reminder_previews(request: Request, user=Depends(get_current_user)):
    """Return one WhatsApp deeplink per customer with an outstanding balance."""
    import urllib.parse
    cid = await _active_company_id(request, user)
    company = await db.companies.find_one({"id": cid, "user_id": user["user_id"]}, {"_id": 0}) or {}

    # Build a customer_id -> {balance, oldest_days} map from unpaid invoices
    # Iter86 — historical invoices don't create live outstanding
    invs = await db.invoices.find(
        {"user_id": user["user_id"], "company_id": cid, "balance_due": {"$gt": 0}, **LIVE_ONLY_FILTER},
        {"_id": 0}
    ).to_list(5000)
    # Iter132c C1 · R3 — enrich with effective balance; drop invoices where a
    # CN has fully offset the outstanding so no reminder goes out.
    try:
        from services import _apply_effective_balance
        await _apply_effective_balance(invs, user["user_id"], cid)
    except Exception:
        pass
    today = datetime.now(timezone.utc).date()
    per_cust: dict = {}
    for i in invs:
        k = i.get("customer_id")
        if not k:
            continue
        eff_bal = float(i.get("effective_balance_due", i.get("balance_due", 0)))
        # Skip fully-credited invoices — nothing to remind about.
        if eff_bal <= 0.01:
            continue
        b = per_cust.setdefault(k, {"balance": 0.0, "invoices": [], "oldest_days": 0})
        b["balance"] += eff_bal
        try:
            dt = datetime.fromisoformat(i["date"]).date()
        except Exception:
            try:
                dt = datetime.strptime(i["date"], "%Y-%m-%d").date()
            except Exception:
                dt = today
        days = (today - dt).days
        b["oldest_days"] = max(b["oldest_days"], days)
        b["invoices"].append({"number": i.get("invoice_number"), "amount": eff_bal, "date": i.get("date"), "days": days})

    customers = await db.customers.find({"user_id": user["user_id"], "company_id": cid}, {"_id": 0}).to_list(2000)
    cust_map = {c["id"]: c for c in customers}

    out = []
    for kid, info in per_cust.items():
        cust = cust_map.get(kid) or {}
        top = sorted(info["invoices"], key=lambda x: -x["days"])[:3]
        msg_lines = [
            f"*Payment Reminder — {company.get('name', 'Our Company')}*",
            f"Dear {cust.get('name', 'Customer')},",
            "",
            f"You have an outstanding balance of *₹{info['balance']:,.2f}*.",
            f"Oldest bill is {info['oldest_days']} days old.",
            "",
            "Pending invoices:",
        ]
        for t in top:
            msg_lines.append(f"  · {t['number']} — ₹{t['amount']:,.2f} ({t['days']}d old)")
        msg_lines.append("")
        msg_lines.append("Please arrange payment at your earliest convenience.")
        msg = "\n".join(msg_lines)
        phone = (cust.get("phone") or "").strip().replace(" ", "").replace("-", "")
        # wa.me format: 91xxxxxxxxxx or empty (opens chat picker)
        wa_target = phone if phone else ""
        # Strip leading + / 0 / country prefix duplicates
        if wa_target.startswith("+"):
            wa_target = wa_target[1:]
        if len(wa_target) == 10:
            wa_target = "91" + wa_target
        out.append({
            "customer_id": kid,
            "customer_name": cust.get("name", ""),
            "phone": cust.get("phone", ""),
            "balance": round(info["balance"], 2),
            "oldest_days": info["oldest_days"],
            "invoice_count": len(info["invoices"]),
            "message": msg,
            "whatsapp_url": f"https://wa.me/{wa_target}?text={urllib.parse.quote(msg)}",
        })
    out.sort(key=lambda x: -x["balance"])
    return {"reminders": out, "total_customers": len(out), "total_outstanding": round(sum(r["balance"] for r in out), 2)}


@router.get("/customers/{cid}/monthly-balances")
async def monthly_balances(cid: str, request: Request, user=Depends(get_current_user)):
    """Aggregate customer transactions by YYYY-MM for the Monthly Balances tab."""
    company_id = await _active_company_id(request, user)
    # Iter86 — monthly balances reflect only live trips + invoices
    trips = await db.trips.find({"user_id": user["user_id"], "company_id": company_id, "customer_id": cid, **LIVE_ONLY_FILTER}, {"_id": 0, "date": 1, "freight_amount": 1, "tons": 1, "status": 1}).to_list(5000)
    invoices = await db.invoices.find({"user_id": user["user_id"], "company_id": company_id, "customer_id": cid, **LIVE_ONLY_FILTER}, {"_id": 0, "id": 1, "invoice_date": 1, "total_amount": 1, "gross_total": 1, "amount_paid": 1, "balance_due": 1, "payments": 1}).to_list(5000)

    # Iter132c C1 · R2 — enrich for sibling effective monthly aggregates.
    try:
        from services import _apply_effective_balance
        await _apply_effective_balance(invoices, user["user_id"], company_id)
    except Exception:
        pass

    months: dict = {}

    def _mkrow(k):
        return {
            "month": k, "trip_count": 0, "quantity": 0.0, "freight": 0.0,
            "billed": 0.0, "received": 0.0, "balance": 0.0,
            "billed_effective": 0.0, "balance_effective": 0.0,
        }

    def _key(dstr):
        return (dstr or "")[:7] or "unknown"

    for t in trips:
        k = _key(t.get("date"))
        m = months.setdefault(k, _mkrow(k))
        m["trip_count"] += 1
        m["quantity"] += float(t.get("tons", 0))
        m["freight"] += float(t.get("freight_amount", 0))
    for inv in invoices:
        k = _key(inv.get("invoice_date"))
        m = months.setdefault(k, _mkrow(k))
        raw_total = float(inv.get("total_amount", inv.get("gross_total", 0)))
        raw_bal = float(inv.get("balance_due", 0))
        m["billed"] += raw_total
        m["received"] += float(inv.get("amount_paid", 0))
        m["balance"] += raw_bal
        m["billed_effective"] += float(inv.get("effective_total_amount", raw_total))
        m["balance_effective"] += float(inv.get("effective_balance_due", raw_bal))
        # count payments in the same month based on payment date
        for p in (inv.get("payments") or []):
            pk = _key(p.get("date"))
            if pk != k:
                pm = months.setdefault(pk, {"month": pk, "trip_count": 0, "quantity": 0.0, "freight": 0.0, "billed": 0.0, "received": 0.0, "balance": 0.0})
                # Don't double count; keep received in invoice-month
                pm.setdefault("_", 0)

    rows = list(months.values())
    for m in rows:
        for k in ("quantity", "freight", "billed", "received", "balance",
                  "billed_effective", "balance_effective"):
            m[k] = round(m.get(k, 0.0), 2)
    rows.sort(key=lambda x: x["month"], reverse=True)
    return {"months": rows}


class AddPaymentRequest(BaseModel):
    amount: float
    date: str = ""
    mode: str = "Cash"                        # Cash | Cheque | UPI | Bank Transfer | Fuel | Others
    note: str = ""
    received_by_driver: bool = False
    driver_id: Optional[str] = None
    allocations: Optional[list] = None        # [{invoice_id, amount}] — optional targeted allocation
    photo_data_url: Optional[str] = None      # base64 data URL (data:image/jpeg;base64,...)


@router.post("/customers/{cid}/add-payment")
async def add_customer_payment(cid: str, payload: AddPaymentRequest, request: Request, user=Depends(get_current_user)):
    """Add a payment against a customer. Allocates to invoices oldest-first (or per user allocations).
    Any surplus (amount > sum of outstanding balances) becomes an on-account advance on the customer.
    Optional photo (data URL) is uploaded to object storage and its public URL attached to each applied payment record."""
    company_id = await _active_company_id(request, user)
    customer = await db.customers.find_one({"id": cid, "user_id": user["user_id"], "company_id": company_id}, {"_id": 0})
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    remaining = float(payload.amount)
    if remaining <= 0:
        raise HTTPException(status_code=400, detail="Amount must be > 0")
    pay_date = payload.date or datetime.now(timezone.utc).date().isoformat()

    # Optional photo upload — one photo shared across all applied invoice payments
    photo_url = None
    if payload.photo_data_url and payload.photo_data_url.startswith("data:"):
        try:
            header, b64 = payload.photo_data_url.split(",", 1)
            mime = header.split(";")[0].replace("data:", "") or "image/jpeg"
            ext = "jpg" if "jpeg" in mime or "jpg" in mime else "png"
            data_bytes = base64.b64decode(b64)
            obj_path = f"public/payment_photos/{user['user_id']}/{cid}_{secrets.token_hex(4)}.{ext}"
            from storage_client import put_object
            put_object(obj_path, data_bytes, mime)
            frontend_base = _public_base_url(request)
            photo_url = f"{frontend_base}/api/files/public/{obj_path}"
        except Exception as e:
            # Non-fatal: log but don't block payment
            logger.warning(f"payment photo upload failed: {e}")

    # Get all invoices with balance, oldest first
    # Iter86 — payment allocation targets only LIVE invoices
    invs = await db.invoices.find(
        {"user_id": user["user_id"], "company_id": company_id, "customer_id": cid, "balance_due": {"$gt": 0}, **LIVE_ONLY_FILTER},
        {"_id": 0}
    ).sort("date", 1).to_list(2000)

    # Build allocation map
    alloc_map: dict = {}
    if payload.allocations:
        for a in payload.allocations:
            if a.get("invoice_id"):
                alloc_map[a["invoice_id"]] = float(a.get("amount", 0))

    applied = []
    for inv in invs:
        if remaining <= 0:
            break
        # Use explicit allocation if provided; else oldest-first fill
        if payload.allocations:
            ask = alloc_map.get(inv["id"], 0)
            if ask <= 0:
                continue
            pay = min(ask, remaining, float(inv["balance_due"]))
        else:
            pay = min(remaining, float(inv["balance_due"]))
        if pay <= 0:
            continue
        note_bits = [payload.note] if payload.note else []
        if payload.received_by_driver and payload.driver_id:
            note_bits.append(f"received-by-driver:{payload.driver_id}")
        elif payload.received_by_driver:
            note_bits.append("received-by-driver")
        new_pay = {"amount": pay, "date": pay_date, "mode": payload.mode, "note": " · ".join(note_bits)}
        if photo_url:
            new_pay["photo_url"] = photo_url
        inv_payments = inv.get("payments") or []
        inv_payments.append(new_pay)
        new_paid = float(inv.get("amount_paid", 0)) + pay
        inv_total = float(inv.get("total_amount") or inv.get("gross_total") or inv.get("total") or 0)
        new_balance = inv_total - new_paid
        new_status = "paid" if new_balance <= 0.01 else ("partial" if new_paid > 0 else "unpaid")
        await db.invoices.update_one(
            {"id": inv["id"], "user_id": user["user_id"]},
            {"$set": {"payments": inv_payments, "amount_paid": round(new_paid, 2), "balance_due": round(max(new_balance, 0), 2), "payment_status": new_status}},
        )
        applied.append({"invoice_id": inv["id"], "invoice_number": inv.get("invoice_number"), "amount": pay})
        remaining -= pay

    await _log_audit(user, "customer_payment", "create", entity_id=cid, entity_ref=f"₹{payload.amount} via {payload.mode}")

    # Surplus → on-account advance
    if remaining > 0.01:
        cur_adv = float(customer.get("advance_balance", 0))
        new_adv = round(cur_adv + remaining, 2)
        await db.customers.update_one(
            {"id": cid, "user_id": user["user_id"]},
            {"$set": {"advance_balance": new_adv}}
        )
        customer["advance_balance"] = new_adv

    return {
        "applied": applied,
        "amount_total": payload.amount,
        "amount_unallocated": round(remaining, 2),
        "advance_balance": float(customer.get("advance_balance", 0)),
        "photo_url": photo_url,
        "date": pay_date,
        "mode": payload.mode,
    }



# ============================================================================
# Iter38 — Reminder Digest (nightly cron output) + manual trigger
# ============================================================================

@router.get("/reminders/digest")
async def get_reminder_digest(request: Request, user=Depends(get_current_user)):
    """Return the most recent nightly digest for this owner (or an empty payload)."""
    doc = await db.reminder_digests.find_one({"user_id": user["user_id"]}, {"_id": 0}, sort=[("generated_at", -1)])
    if not doc:
        return {"digest": None, "message": "No digest yet — cron runs at 18:00 IST daily. Try /reminders/digest/run to generate now."}
    return {"digest": doc}


@router.post("/reminders/digest/run")
async def run_reminder_digest_now(request: Request, user=Depends(get_current_user)):
    """Force-run the nightly digest for the current owner (useful for testing / on-demand)."""
    from scheduler import _nightly_reminder_digest
    await _nightly_reminder_digest()
    doc = await db.reminder_digests.find_one({"user_id": user["user_id"]}, {"_id": 0}, sort=[("generated_at", -1)])
    return {"digest": doc, "message": "Digest regenerated"}


class ReminderPref(BaseModel):
    reminder_enabled: bool


@router.put("/customers/{cid}/reminder-pref")
async def set_reminder_pref(cid: str, payload: ReminderPref, request: Request, user=Depends(get_current_user)):
    """Toggle a customer's reminder inclusion."""
    company_id = await _active_company_id(request, user)
    r = await db.customers.update_one(
        {"id": cid, "user_id": user["user_id"], "company_id": company_id},
        {"$set": {"reminder_enabled": bool(payload.reminder_enabled)}}
    )
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Customer not found")
    return {"ok": True, "reminder_enabled": payload.reminder_enabled}

