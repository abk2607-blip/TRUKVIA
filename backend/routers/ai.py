"""AI Business Assistant — Gemini 3.5 Flash with tool calling.

Provides an AI chat that can read live business data for the CURRENTLY ACTIVE
company only.  Every tool function receives the resolved `user_id` + `company_id`
and enforces the standard multi-tenant filter — the model has NO way to bypass
company scoping because it never sees or supplies these IDs.

Tools exposed to the model (each returns concise JSON):
  - get_dashboard           overall revenue / profit / receivables snapshot
  - list_customers          all customers with pending balance
  - list_overdue_invoices   >X days overdue
  - list_recent_trips       trips in a date range (default last 30 days)
  - vehicle_profit_summary  per-vehicle profit for a period
  - route_profit_summary    per-route profit for a period
  - customer_ledger         detailed ledger of one customer
  - gst_summary             GST summary for the active FY
"""
import json
import io
import logging
import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from db import db
from models import ChatSession, ChatMessage, now_utc
from auth import get_current_user
from company import _active_company_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")

# ============================================================================
# Tool implementations (private — never expose IDs to the model directly)
# ============================================================================

async def _tool_get_dashboard(user_id: str, cid: str) -> dict:
    trips = await db.trips.find({"user_id": user_id, "company_id": cid}, {"_id": 0}).to_list(5000)
    invoices = await db.invoices.find({"user_id": user_id, "company_id": cid}, {"_id": 0}).to_list(2000)
    revenue = round(sum(float(t.get("freight_amount", 0)) for t in trips), 2)
    expense = round(sum(float(t.get("total_expense", 0)) for t in trips), 2)
    profit = round(revenue - expense, 2)
    billed = round(sum(float(i.get("total_amount", 0)) for i in invoices), 2)
    received = round(sum(float(i.get("amount_paid", 0)) for i in invoices), 2)
    return {
        "total_revenue": revenue, "total_expense": expense, "total_profit": profit,
        "total_billed": billed, "total_received": received,
        "outstanding_receivable": round(billed - received, 2),
        "trip_count": len(trips), "invoice_count": len(invoices),
    }


async def _tool_list_overdue_invoices(user_id: str, cid: str, min_days: int = 0) -> list:
    from datetime import datetime, timezone
    invs = await db.invoices.find({"user_id": user_id, "company_id": cid, "balance_due": {"$gt": 0}}, {"_id": 0}).to_list(500)
    customers = {c["id"]: c for c in await db.customers.find({"user_id": user_id, "company_id": cid}, {"_id": 0}).to_list(2000)}
    today = datetime.now(timezone.utc).date()
    out = []
    for inv in invs:
        try:
            age = (today - datetime.fromisoformat(inv.get("invoice_date", "")).date()).days
        except Exception:
            age = 0
        if age < min_days:
            continue
        c = customers.get(inv.get("customer_id"), {})
        out.append({
            "invoice_number": inv.get("invoice_number"), "date": inv.get("invoice_date"),
            "customer": c.get("name", "Unknown"), "customer_phone": c.get("phone", ""),
            "balance_due": inv.get("balance_due"), "total": inv.get("total_amount"),
            "age_days": age,
        })
    return sorted(out, key=lambda x: -x["age_days"])[:50]


async def _tool_list_recent_trips(user_id: str, cid: str, days: int = 30, customer_name: Optional[str] = None) -> list:
    from datetime import datetime, timezone, timedelta
    since = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()
    q = {"user_id": user_id, "company_id": cid, "date": {"$gte": since}}
    trips = await db.trips.find(q, {"_id": 0}).sort("date", -1).to_list(200)
    customers = {c["id"]: c for c in await db.customers.find({"user_id": user_id, "company_id": cid}, {"_id": 0}).to_list(2000)}
    out = []
    for t in trips:
        c = customers.get(t.get("customer_id"), {})
        if customer_name and customer_name.lower() not in c.get("name", "").lower():
            continue
        out.append({
            "date": t.get("date"), "customer": c.get("name"),
            "vehicle": t.get("vehicle_number"),
            "route": f"{t.get('from_location','')} → {t.get('to_location','')}",
            "load": t.get("load_details"), "tons": t.get("tons"),
            "freight": t.get("freight_amount"), "profit": t.get("profit"),
            "status": t.get("status"), "invoiced": bool(t.get("invoice_id")),
        })
    return out[:50]


async def _tool_vehicle_profit_summary(user_id: str, cid: str, days: int = 30) -> list:
    from datetime import datetime, timezone, timedelta
    since = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()
    trips = await db.trips.find({"user_id": user_id, "company_id": cid, "date": {"$gte": since}}, {"_id": 0}).to_list(5000)
    agg = {}
    for t in trips:
        v = t.get("vehicle_number") or "—"
        a = agg.setdefault(v, {"vehicle": v, "trips": 0, "revenue": 0.0, "expense": 0.0, "profit": 0.0})
        a["trips"] += 1
        a["revenue"] = round(a["revenue"] + float(t.get("freight_amount", 0)), 2)
        a["expense"] = round(a["expense"] + float(t.get("total_expense", 0)), 2)
        a["profit"] = round(a["profit"] + float(t.get("profit", 0)), 2)
    return sorted(agg.values(), key=lambda x: -x["profit"])[:20]


async def _tool_route_profit_summary(user_id: str, cid: str, days: int = 30) -> list:
    from datetime import datetime, timezone, timedelta
    since = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()
    trips = await db.trips.find({"user_id": user_id, "company_id": cid, "date": {"$gte": since}}, {"_id": 0}).to_list(5000)
    agg = {}
    for t in trips:
        r = f"{t.get('from_location','?')} → {t.get('to_location','?')}"
        a = agg.setdefault(r, {"route": r, "trips": 0, "revenue": 0.0, "profit": 0.0, "tons": 0.0})
        a["trips"] += 1
        a["revenue"] = round(a["revenue"] + float(t.get("freight_amount", 0)), 2)
        a["profit"] = round(a["profit"] + float(t.get("profit", 0)), 2)
        a["tons"] = round(a["tons"] + float(t.get("tons", 0)), 2)
    return sorted(agg.values(), key=lambda x: -x["profit"])[:20]


async def _tool_customer_ledger(user_id: str, cid: str, customer_name: str) -> dict:
    customers = await db.customers.find({"user_id": user_id, "company_id": cid}, {"_id": 0}).to_list(2000)
    match = next((c for c in customers if customer_name.lower() in c.get("name", "").lower()), None)
    if not match:
        return {"error": f"No customer matching '{customer_name}' in the active company."}
    invs = await db.invoices.find({"user_id": user_id, "company_id": cid, "customer_id": match["id"]}, {"_id": 0}).to_list(500)
    total_billed = round(sum(float(i.get("total_amount", 0)) for i in invs), 2)
    total_paid = round(sum(float(i.get("amount_paid", 0)) for i in invs), 2)
    return {
        "customer": match.get("name"), "phone": match.get("phone", ""), "gstin": match.get("gstin", ""),
        "invoices": len(invs), "total_billed": total_billed, "total_paid": total_paid,
        "balance": round(total_billed - total_paid, 2),
        "recent_invoices": [
            {"number": i.get("invoice_number"), "date": i.get("invoice_date"),
             "total": i.get("total_amount"), "paid": i.get("amount_paid"),
             "balance": i.get("balance_due")}
            for i in sorted(invs, key=lambda x: x.get("invoice_date", ""), reverse=True)[:10]
        ],
    }


async def _tool_list_customers(user_id: str, cid: str) -> list:
    customers = await db.customers.find({"user_id": user_id, "company_id": cid}, {"_id": 0}).to_list(2000)
    invs = await db.invoices.find({"user_id": user_id, "company_id": cid}, {"_id": 0}).to_list(2000)
    balances = {}
    for i in invs:
        balances[i.get("customer_id")] = balances.get(i.get("customer_id"), 0) + float(i.get("balance_due", 0))
    return [
        {"name": c.get("name"), "phone": c.get("phone", ""), "state": c.get("state", ""),
         "outstanding": round(balances.get(c["id"], 0), 2)}
        for c in customers
    ]


async def _tool_gst_summary(user_id: str, cid: str) -> dict:
    from datetime import datetime, timezone
    invs = await db.invoices.find({"user_id": user_id, "company_id": cid}, {"_id": 0}).to_list(2000)
    now = datetime.now(timezone.utc)
    fy_start = f"{now.year - (1 if now.month < 4 else 0)}-04-01"
    fy_invs = [i for i in invs if i.get("invoice_date", "") >= fy_start]
    return {
        "current_fy_start": fy_start,
        "invoices": len(fy_invs),
        "taxable": round(sum(float(i.get("subtotal", 0)) for i in fy_invs), 2),
        "cgst": round(sum(float(i.get("cgst_amount", 0)) for i in fy_invs), 2),
        "sgst": round(sum(float(i.get("sgst_amount", 0)) for i in fy_invs), 2),
        "igst": round(sum(float(i.get("igst_amount", 0)) for i in fy_invs), 2),
        "total": round(sum(float(i.get("total_amount", 0)) for i in fy_invs), 2),
    }


TOOL_FN_MAP = {
    "get_dashboard":           _tool_get_dashboard,
    "list_customers":          _tool_list_customers,
    "list_overdue_invoices":   _tool_list_overdue_invoices,
    "list_recent_trips":       _tool_list_recent_trips,
    "vehicle_profit_summary":  _tool_vehicle_profit_summary,
    "route_profit_summary":    _tool_route_profit_summary,
    "customer_ledger":         _tool_customer_ledger,
    "gst_summary":             _tool_gst_summary,
}

TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "get_dashboard", "description": "Overall business snapshot for the currently active company — total revenue, total expense, net profit, total billed, total received, outstanding receivable, trip count, invoice count.",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "list_customers", "description": "All customers for the active company plus their pending outstanding balance.",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "list_overdue_invoices", "description": "Overdue invoices with balance > 0, sorted oldest first. Pass min_days to filter by age.",
        "parameters": {"type": "object", "properties": {"min_days": {"type": "integer", "description": "Only invoices older than N days"}}, "required": []}}},
    {"type": "function", "function": {
        "name": "list_recent_trips", "description": "Recent trips in the active company. days=30 by default; optional customer_name filter (substring match).",
        "parameters": {"type": "object", "properties": {"days": {"type": "integer"}, "customer_name": {"type": "string"}}, "required": []}}},
    {"type": "function", "function": {
        "name": "vehicle_profit_summary", "description": "Per-vehicle profit for the last N days (default 30). Returns vehicle, trips, revenue, expense, profit.",
        "parameters": {"type": "object", "properties": {"days": {"type": "integer"}}, "required": []}}},
    {"type": "function", "function": {
        "name": "route_profit_summary", "description": "Per-route profit ranking for the last N days.",
        "parameters": {"type": "object", "properties": {"days": {"type": "integer"}}, "required": []}}},
    {"type": "function", "function": {
        "name": "customer_ledger", "description": "Detailed ledger + outstanding balance for a customer (fuzzy substring match on name).",
        "parameters": {"type": "object", "properties": {"customer_name": {"type": "string"}}, "required": ["customer_name"]}}},
    {"type": "function", "function": {
        "name": "gst_summary", "description": "GST summary for the current financial year — taxable value, CGST, SGST, IGST, total.",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
]


# ============================================================================
# API
# ============================================================================

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


@router.get("/ai/sessions")
async def list_sessions(request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    docs = await db.chat_sessions.find(
        {"user_id": user["user_id"], "company_id": cid},
        {"_id": 0, "user_id": 0},
    ).sort("created_at", -1).to_list(50)
    return docs


@router.get("/ai/sessions/{sid}/messages")
async def get_session_messages(sid: str, request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    sess = await db.chat_sessions.find_one({"id": sid, "user_id": user["user_id"], "company_id": cid}, {"_id": 0})
    if not sess:
        raise HTTPException(status_code=404, detail="Chat session not found")
    msgs = await db.chat_messages.find({"session_id": sid}, {"_id": 0}).sort("created_at", 1).to_list(500)
    return msgs


@router.delete("/ai/sessions/{sid}")
async def delete_session(sid: str, request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    await db.chat_sessions.delete_one({"id": sid, "user_id": user["user_id"], "company_id": cid})
    await db.chat_messages.delete_many({"session_id": sid})
    return {"ok": True}


@router.post("/ai/chat")
async def ai_chat(payload: ChatRequest, request: Request, user=Depends(get_current_user)):
    """Streaming chat with Gemini 3.5 Flash. Returns SSE with text deltas."""
    if not EMERGENT_LLM_KEY:
        raise HTTPException(status_code=503, detail="AI is not configured (missing EMERGENT_LLM_KEY)")

    cid = await _active_company_id(request, user)
    company = await db.companies.find_one({"id": cid, "user_id": user["user_id"]}, {"_id": 0}) or {}

    # Persist / create session
    sid = payload.session_id
    if not sid:
        sess = ChatSession(title=payload.message[:60])
        sd = sess.model_dump()
        sd["user_id"] = user["user_id"]
        sd["company_id"] = cid
        await db.chat_sessions.insert_one(sd)
        sid = sess.id

    await db.chat_messages.insert_one({
        **ChatMessage(session_id=sid, role="user", content=payload.message).model_dump(),
        "user_id": user["user_id"], "company_id": cid,
    })

    # Audit
    try:
        await db.audit_logs.insert_one({
            "user_id": user["user_id"], "company_id": cid,
            "user_email": user.get("email", ""), "user_name": user.get("name", ""),
            "module": "ai", "action": "chat",
            "entity_id": sid, "entity_ref": payload.message[:80],
            "changes": {}, "reason": "",
            "timestamp": now_utc().isoformat(),
        })
    except Exception:
        pass

    system_prompt = (
        f"You are the AI business assistant for **{company.get('name', 'the transport company')}**. "
        f"You answer questions about live transport-accounting data. "
        f"The active company is **{company.get('name','')}** in state **{company.get('state','')}**. "
        f"NEVER discuss data from other companies. If a question isn't about this company's "
        f"trips / invoices / customers / vehicles, answer generally without inventing numbers. "
        f"Prefer to call one of the provided tools to fetch live figures rather than guessing. "
        f"Format answers concisely in short bullet points; use ₹ prefix on money values. "
        f"You can respond in the user's language (English/Telugu). Today's date: {now_utc().date().isoformat()}."
    )

    # Load recent messages (last 12) to preserve short-term context.
    prev = await db.chat_messages.find({"session_id": sid}, {"_id": 0}).sort("created_at", 1).to_list(24)

    from emergentintegrations.llm.chat import LlmChat, UserMessage
    chat = (LlmChat(api_key=EMERGENT_LLM_KEY, session_id=sid, system_message=system_prompt)
            .with_model("gemini", "gemini-3-flash-preview")
            .with_tools(TOOL_SCHEMAS, tool_choice="auto"))

    async def event_stream():
        assistant_buf = []
        try:
            # Bootstrap prior context: replay stored user/assistant messages before the latest one.
            for m in prev[:-1]:
                if m["role"] == "user":
                    _ = await chat.send_message_with_tools(UserMessage(text=m["content"]))
            # Non-streaming loop for tool chaining, then stream final content back.
            response = await chat.send_message_with_tools(UserMessage(text=payload.message))
            while response.tool_calls:
                for tc in response.tool_calls:
                    fn = TOOL_FN_MAP.get(tc.name)
                    if not fn:
                        result = {"error": f"unknown tool: {tc.name}"}
                    else:
                        try:
                            result = await fn(user["user_id"], cid, **(tc.arguments or {}))
                        except Exception as e:
                            result = {"error": str(e)}
                    chat.add_tool_result(tc.id, json.dumps(result, default=str))
                response = await chat.send_message_with_tools()
            text = getattr(response, "content", None) or getattr(response, "text", "") or ""
            # Stream in ~40-char chunks so it feels live to the user.
            step = 40
            for i in range(0, len(text), step):
                chunk = text[i:i + step]
                assistant_buf.append(chunk)
                yield f"data: {json.dumps({'type':'text','delta':chunk})}\n\n"
            yield f"data: {json.dumps({'type':'done','session_id':sid})}\n\n"
        except Exception as e:
            logger.exception("AI chat failed")
            yield f"data: {json.dumps({'type':'error','message':str(e)})}\n\n"
            yield f"data: {json.dumps({'type':'done','session_id':sid})}\n\n"
        finally:
            final = "".join(assistant_buf).strip()
            if final:
                try:
                    await db.chat_messages.insert_one({
                        **ChatMessage(session_id=sid, role="assistant", content=final).model_dump(),
                        "user_id": user["user_id"], "company_id": cid,
                    })
                except Exception:
                    pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


# ============================================================================
# Voice-to-Trip parser (Iter33)
# ============================================================================

class ParseTripRequest(BaseModel):
    transcript: str


@router.post("/ai/parse-trip")
async def parse_trip_from_voice(payload: ParseTripRequest, request: Request, user=Depends(get_current_user)):
    """Parse a spoken (Telugu/English) trip description into structured trip fields."""
    if not EMERGENT_LLM_KEY:
        raise HTTPException(status_code=503, detail="AI is not configured (missing EMERGENT_LLM_KEY)")
    cid = await _active_company_id(request, user)
    text = (payload.transcript or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Empty transcript")

    # Load master data lookups so LLM can match names → IDs
    customers = await db.customers.find({"user_id": user["user_id"], "company_id": cid}, {"_id": 0, "id": 1, "name": 1}).to_list(500)
    vehicles = await db.vehicles.find({"user_id": user["user_id"], "company_id": cid}, {"_id": 0, "id": 1, "vehicle_number": 1, "supplier_name": 1, "vehicle_type": 1}).to_list(500)
    drivers = await db.drivers.find({"user_id": user["user_id"], "company_id": cid}, {"_id": 0, "id": 1, "name": 1}).to_list(500)
    products = await db.products.find({"user_id": user["user_id"], "company_id": cid}, {"_id": 0, "id": 1, "name": 1, "default_rate": 1}).to_list(500)

    system = (
        "You are a Telugu/English speech-to-JSON parser for a Bitumen transport accounting app. "
        "The user dictated details of ONE trip. Extract only the fields that were clearly mentioned. "
        "Return STRICT JSON with these optional keys (omit ones not spoken):\n"
        '{"date":"YYYY-MM-DD","customer_name":"","vehicle_number":"","driver_name":"","load_details":"",'
        '"tons":0,"from_location":"","to_location":"","rate_per_ton":0,"round_trip_kms":0,'
        '"rate_per_km_per_ton":0,"freight_mode":"per_ton|fixed","notes":""}\n'
        "Rules: "
        "- Numbers spoken in Telugu (ఇరవై టన్నులు = 20 tons) must be converted to digits. "
        "- Vehicle registration numbers must be uppercase, no spaces (AP16TA1234). "
        '- Freight mode: if user says "per ton / తనుకు" pick per_ton; if "round trip / రౌండ్ ట్రిప్" pick fixed. '
        "- If a customer/vehicle/driver/product name is spoken, use the closest match from these lists (case-insensitive substring):\n"
        f"Customers: {[c['name'] for c in customers][:40]}\n"
        f"Vehicles: {[v['vehicle_number'] for v in vehicles][:40]}\n"
        f"Drivers: {[d['name'] for d in drivers][:40]}\n"
        f"Products: {[p['name'] for p in products][:20]}\n"
        f"Today: {now_utc().date().isoformat()}. If user says 'today', 'ఈరోజు' use today. 'yesterday' = today-1.\n"
        "Return ONLY the JSON object, no prose, no markdown code fence."
    )

    from emergentintegrations.llm.chat import LlmChat, UserMessage
    chat = LlmChat(api_key=EMERGENT_LLM_KEY, session_id=f"parse-{user['user_id']}", system_message=system).with_model("gemini", "gemini-3-flash-preview")
    try:
        response = await chat.send_message(UserMessage(text=text))
        raw = response if isinstance(response, str) else (getattr(response, "content", None) or getattr(response, "text", "") or str(response))
    except Exception as e:
        logger.exception("parse-trip failed")
        raise HTTPException(status_code=502, detail=f"AI parse failed: {e}")

    # Strip markdown fences if any
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`").split("\n", 1)[-1]
        if raw.endswith("```"):
            raw = raw.rsplit("```", 1)[0]
    try:
        data = json.loads(raw)
    except Exception:
        # find first { ... }
        i, j = raw.find("{"), raw.rfind("}")
        if i >= 0 and j > i:
            try:
                data = json.loads(raw[i:j + 1])
            except Exception:
                data = {}
        else:
            data = {}

    # Resolve names → IDs
    resolved = dict(data)
    if data.get("customer_name"):
        c = next((c for c in customers if data["customer_name"].lower() in c["name"].lower() or c["name"].lower() in data["customer_name"].lower()), None)
        if c:
            resolved["customer_id"] = c["id"]
    if data.get("vehicle_number"):
        vn = data["vehicle_number"].upper().replace(" ", "")
        v = next((v for v in vehicles if v["vehicle_number"].upper().replace(" ", "") == vn), None)
        if v:
            resolved["vehicle_id"] = v["id"]
            resolved["vehicle_type"] = v.get("vehicle_type", "own")
        resolved["vehicle_number"] = vn
    if data.get("driver_name"):
        d = next((d for d in drivers if data["driver_name"].lower() in d["name"].lower() or d["name"].lower() in data["driver_name"].lower()), None)
        if d:
            resolved["driver_id"] = d["id"]
            resolved["driver_name"] = d["name"]
    if data.get("load_details"):
        p = next((p for p in products if data["load_details"].lower() in p["name"].lower() or p["name"].lower() in data["load_details"].lower()), None)
        if p:
            resolved["product_id"] = p["id"]
            resolved["load_details"] = p["name"]
    return {"parsed": resolved, "transcript": text}


# ============================================================================
# Smart Dashboard Insights (Iter33)
# ============================================================================

@router.get("/ai/insights")
async def dashboard_insights(request: Request, user=Depends(get_current_user)):
    if not EMERGENT_LLM_KEY:
        raise HTTPException(status_code=503, detail="AI is not configured (missing EMERGENT_LLM_KEY)")
    cid = await _active_company_id(request, user)
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    thirty_ago = (now - timedelta(days=30)).date().isoformat()

    # Cache: keep the last insight per company for 6 hours
    cache = await db.ai_insight_cache.find_one({"user_id": user["user_id"], "company_id": cid}, {"_id": 0})
    if cache and cache.get("generated_at"):
        try:
            gen = datetime.fromisoformat(cache["generated_at"])
            if (now - gen).total_seconds() < 6 * 3600:
                return {
                    "insights": cache["insights"],
                    "generated_at": cache["generated_at"],
                    "stats_snapshot": cache.get("stats_snapshot") or {},
                    "cached": True,
                }
        except Exception:
            pass

    # Gather live stats
    dash = await _tool_get_dashboard(user["user_id"], cid)
    overdue = await _tool_list_overdue_invoices(user["user_id"], cid, min_days=15)
    veh_perf = await _tool_vehicle_profit_summary(user["user_id"], cid, days=30)
    routes = await _tool_route_profit_summary(user["user_id"], cid, days=30)

    # Compute low-profit trips (< 10% margin)
    trips = await db.trips.find({"user_id": user["user_id"], "company_id": cid, "date": {"$gte": thirty_ago}}, {"_id": 0}).to_list(500)
    low_profit = []
    for t in trips:
        f = float(t.get("freight_amount", 0))
        p = float(t.get("profit", 0))
        margin = (p / f * 100) if f > 0 else 0
        if 0 < f and margin < 10:
            low_profit.append({"date": t.get("date"), "vehicle": t.get("vehicle_number"), "freight": f, "profit": p, "margin_pct": round(margin, 1)})
    low_profit = sorted(low_profit, key=lambda x: x["margin_pct"])[:5]

    # Month-over-month comparison — prior 30 days
    sixty_ago = (now - timedelta(days=60)).date().isoformat()
    prev_trips = await db.trips.find(
        {"user_id": user["user_id"], "company_id": cid, "date": {"$gte": sixty_ago, "$lt": thirty_ago}},
        {"_id": 0}
    ).to_list(500)

    def _delta(cur: float, prev: float):
        if prev == 0:
            return {"prev": prev, "curr": cur, "delta_pct": None, "direction": "up" if cur > 0 else "flat"}
        d = round((cur - prev) / prev * 100, 1)
        return {"prev": round(prev, 2), "curr": round(cur, 2), "delta_pct": d, "direction": "up" if d >= 0 else "down"}

    cur_revenue = sum(float(t.get("freight_amount", 0)) for t in trips)
    prev_revenue = sum(float(t.get("freight_amount", 0)) for t in prev_trips)
    cur_profit = sum(float(t.get("profit", 0)) for t in trips)
    prev_profit = sum(float(t.get("profit", 0)) for t in prev_trips)
    cur_expense = sum(float(t.get("total_expense", 0)) for t in trips)
    prev_expense = sum(float(t.get("total_expense", 0)) for t in prev_trips)
    mom = {
        "revenue": _delta(cur_revenue, prev_revenue),
        "profit": _delta(cur_profit, prev_profit),
        "expense": _delta(cur_expense, prev_expense),
        "trip_count": _delta(len(trips), len(prev_trips)),
    }

    system = (
        "You are a business advisor for a Bitumen transport company. Given the JSON stats below, "
        "produce 4-6 SHORT bullet insights in mixed Telugu+English (short, action-oriented). "
        "Each bullet MUST be one line, prefixed with a status icon (🟢 good / 🟡 warn / 🔴 urgent). "
        "IMPORTANT: For every applicable bullet include a Month-over-Month delta like '↑ +12% vs last 30d' or '↓ -8% vs last 30d' using the `month_over_month` block. "
        "Focus on: cash flow, receivables, low-profit vehicles/trips, stuck payments, growth opportunities. "
        "Include ₹ figures where relevant. Do NOT invent numbers. Return only the bullets, one per line."
    )
    ctx = {
        "overall": dash,
        "month_over_month": mom,
        "overdue_invoices_15d+": overdue[:8],
        "vehicle_performance_30d": veh_perf[:8],
        "route_performance_30d": routes[:5],
        "low_margin_trips_30d": low_profit,
    }
    from emergentintegrations.llm.chat import LlmChat, UserMessage
    chat = LlmChat(api_key=EMERGENT_LLM_KEY, session_id=f"insights-{cid}", system_message=system).with_model("gemini", "gemini-3-flash-preview")
    try:
        response = await chat.send_message(UserMessage(text=json.dumps(ctx, default=str)))
        text = response if isinstance(response, str) else (getattr(response, "content", None) or getattr(response, "text", "") or str(response))
        text = (text or "").strip()
    except Exception as e:
        logger.exception("insights gen failed")
        raise HTTPException(status_code=502, detail=f"Insight gen failed: {e}")

    bullets = [ln.strip("•- \t") for ln in text.splitlines() if ln.strip() and any(ln.strip().startswith(ic) for ic in ("🟢", "🟡", "🔴", "•", "-", "*"))]
    if not bullets:
        bullets = [ln.strip() for ln in text.splitlines() if ln.strip()][:6]

    result = {
        "insights": bullets,
        "generated_at": now.isoformat(),
        "stats_snapshot": {
            "outstanding": dash["outstanding_receivable"],
            "profit_30d": sum(float(t.get("profit", 0)) for t in trips),
            "low_margin_count": len(low_profit),
            "overdue_15d_count": len(overdue),
            "mom": mom,
        },
    }
    await db.ai_insight_cache.replace_one(
        {"user_id": user["user_id"], "company_id": cid},
        {"user_id": user["user_id"], "company_id": cid, **result},
        upsert=True,
    )
    return {**result, "cached": False}


@router.post("/ai/insights/refresh")
async def insights_refresh(request: Request, user=Depends(get_current_user)):
    cid = await _active_company_id(request, user)
    await db.ai_insight_cache.delete_many({"user_id": user["user_id"], "company_id": cid})
    return await dashboard_insights(request, user)


# ============================================================================
# Report by Chat (Iter33) — NL query → structured spec → PDF
# ============================================================================

class ReportQuery(BaseModel):
    query: str


@router.post("/ai/report")
async def natural_language_report(payload: ReportQuery, request: Request, user=Depends(get_current_user)):
    if not EMERGENT_LLM_KEY:
        raise HTTPException(status_code=503, detail="AI is not configured (missing EMERGENT_LLM_KEY)")
    cid = await _active_company_id(request, user)
    q = (payload.query or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="Empty query")

    from datetime import datetime, timezone, timedelta
    today = datetime.now(timezone.utc).date()

    system = (
        "Convert the user's report request into STRICT JSON. Keys:\n"
        '{"title":"", "start":"YYYY-MM-DD", "end":"YYYY-MM-DD", '
        '"metric":"diesel|freight|profit|expense|shortage|advance|receivable", '
        '"group_by":"vehicle|customer|driver|route|day|month|none", '
        '"filter_customer":"", "filter_vehicle":""}\n'
        f"Today: {today.isoformat()}. If date not given, use last 30 days (start=today-30, end=today). "
        "If 'last month': start=first day of last month, end=last day of last month. "
        "Return ONLY the JSON object, no prose."
    )
    from emergentintegrations.llm.chat import LlmChat, UserMessage
    chat = LlmChat(api_key=EMERGENT_LLM_KEY, session_id=f"report-{user['user_id']}", system_message=system).with_model("gemini", "gemini-3-flash-preview")
    response = await chat.send_message(UserMessage(text=q))
    raw = response if isinstance(response, str) else (getattr(response, "content", None) or getattr(response, "text", "") or str(response))
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`").split("\n", 1)[-1]
        if raw.endswith("```"):
            raw = raw.rsplit("```", 1)[0]
    try:
        spec = json.loads(raw)
    except Exception:
        i, j = raw.find("{"), raw.rfind("}")
        spec = json.loads(raw[i:j + 1]) if i >= 0 else {}

    # Defaults
    spec.setdefault("start", (today - timedelta(days=30)).isoformat())
    spec.setdefault("end", today.isoformat())
    spec.setdefault("metric", "profit")
    spec.setdefault("group_by", "vehicle")
    spec.setdefault("title", f"{spec['metric'].title()} Report ({spec['group_by']} view)")

    # Execute the query
    match = {"user_id": user["user_id"], "company_id": cid, "date": {"$gte": spec["start"], "$lte": spec["end"]}}
    if spec.get("filter_customer"):
        c = await db.customers.find_one({"user_id": user["user_id"], "company_id": cid, "name": {"$regex": spec["filter_customer"], "$options": "i"}}, {"_id": 0})
        if c:
            match["customer_id"] = c["id"]
    if spec.get("filter_vehicle"):
        match["vehicle_number"] = spec["filter_vehicle"].upper()

    trips = await db.trips.find(match, {"_id": 0}).to_list(5000)
    customer_names = {c["id"]: c["name"] for c in await db.customers.find({"user_id": user["user_id"], "company_id": cid}, {"_id": 0, "id": 1, "name": 1}).to_list(2000)}

    def _val(t: dict, metric: str) -> float:
        if metric == "diesel":
            return float((t.get("expenses") or {}).get("diesel", 0)) + float(t.get("supplier_diesel", 0))
        if metric == "freight":
            return float(t.get("freight_amount", 0))
        if metric == "expense":
            return float(t.get("total_expense", 0))
        if metric == "shortage":
            return float(t.get("shortage_amount", 0)) + float(t.get("supplier_shortage_deduction", 0))
        if metric == "advance":
            return float((t.get("expenses") or {}).get("cash_advance_received", 0)) + float(t.get("supplier_advance", 0))
        if metric == "receivable":
            return float(t.get("freight_amount", 0)) - float(t.get("amount_received", 0))
        # profit default
        return float(t.get("profit", 0))

    def _key(t: dict, gb: str) -> str:
        if gb == "vehicle":
            return t.get("vehicle_number") or "—"
        if gb == "customer":
            return customer_names.get(t.get("customer_id"), "—")
        if gb == "driver":
            return t.get("driver_name") or "—"
        if gb == "route":
            return f"{t.get('from_location', '') or '?'} → {t.get('to_location', '') or '?'}"
        if gb == "day":
            return t.get("date", "—")
        if gb == "month":
            return (t.get("date") or "")[:7] or "—"
        return "All"

    buckets: dict = {}
    total = 0.0
    for t in trips:
        k = _key(t, spec["group_by"])
        v = _val(t, spec["metric"])
        buckets[k] = buckets.get(k, 0.0) + v
        total += v
    rows = sorted(buckets.items(), key=lambda x: -x[1])

    # Generate a simple PDF using ReportLab
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    buf = io.BytesIO()
    styles = getSampleStyleSheet()
    title_st = ParagraphStyle("t", parent=styles["Title"], fontSize=16, leading=20)
    small_st = ParagraphStyle("s", parent=styles["Normal"], fontSize=9, textColor=colors.grey)
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm, bottomMargin=18 * mm)
    story = [Paragraph(spec["title"], title_st)]
    company = await db.companies.find_one({"id": cid, "user_id": user["user_id"]}, {"_id": 0}) or {}
    story.append(Paragraph(f"{company.get('name', '')} — Period: {spec['start']} to {spec['end']} — Metric: {spec['metric'].title()} · Group by: {spec['group_by'].title()} · Query: \"{q}\"", small_st))
    story.append(Spacer(1, 8))
    data = [[spec["group_by"].title(), "Trips", f"{spec['metric'].title()} (₹)"]]
    tcount: dict = {}
    for t in trips:
        k = _key(t, spec["group_by"])
        tcount[k] = tcount.get(k, 0) + 1
    for k, v in rows:
        data.append([str(k), str(tcount.get(k, 0)), f"{v:,.2f}"])
    data.append(["TOTAL", str(len(trips)), f"{total:,.2f}"])
    tbl = Table(data, hAlign="LEFT", repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("TOPPADDING", (0, 0), (-1, 0), 6),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f3f4f6")),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d1d5db")),
    ]))
    story.append(tbl)
    doc.build(story)
    buf.seek(0)
    filename = f"report_{spec['metric']}_{spec['group_by']}_{today.isoformat()}.pdf"
    return StreamingResponse(
        buf, media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"', "X-Report-Spec": json.dumps(spec)},
    )


# ============================================================================
# Voice on Any Screen (Iter34) — extend parse to invoice / payment / expense
# ============================================================================

class ParseAnyRequest(BaseModel):
    transcript: str
    context: str = "trip"  # trip | invoice | payment | expense


@router.post("/ai/parse")
async def parse_any_from_voice(payload: ParseAnyRequest, request: Request, user=Depends(get_current_user)):
    if not EMERGENT_LLM_KEY:
        raise HTTPException(status_code=503, detail="AI not configured")
    cid = await _active_company_id(request, user)
    text = (payload.transcript or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Empty transcript")

    ctx = payload.context.lower().strip()
    if ctx == "invoice":
        customers = await db.customers.find({"user_id": user["user_id"], "company_id": cid}, {"_id": 0, "id": 1, "name": 1}).to_list(500)
        schema = (
            '{"customer_name":"","invoice_date":"YYYY-MM-DD","due_date":"YYYY-MM-DD",'
            '"tax_mode":"cgst_sgst|igst|no_tax","gst_rate":0,"notes":"","reference_no":""}'
        )
        hints = f"Customers: {[c['name'] for c in customers][:40]}\n"
    elif ctx == "payment":
        customers = await db.customers.find({"user_id": user["user_id"], "company_id": cid}, {"_id": 0, "id": 1, "name": 1}).to_list(500)
        schema = (
            '{"customer_name":"","invoice_ref":"","amount":0,"date":"YYYY-MM-DD",'
            '"mode":"Cash|UPI|Bank Transfer|Cheque","note":""}'
        )
        hints = f"Customers: {[c['name'] for c in customers][:40]}\n"
    elif ctx == "expense":
        schema = (
            '{"diesel":0,"toll":0,"batta":0,"repair":0,"firewood":0,"other":0,"other_desc":"",'
            '"notes":""}'
        )
        hints = ""
    else:
        # trip context — reuse existing parse-trip
        return await parse_trip_from_voice(ParseTripRequest(transcript=text), request, user)

    system = (
        "You are a Telugu/English speech-to-JSON parser for a Bitumen transport accounting app. "
        f"Extract only fields clearly mentioned for a {ctx} entry. Return STRICT JSON:\n{schema}\n"
        "Rules: Numbers in Telugu are converted to digits. Customer names should be matched (case-insensitive substring) "
        f"from these master data:\n{hints}"
        f"Today: {now_utc().date().isoformat()}. Return ONLY the JSON object."
    )
    from emergentintegrations.llm.chat import LlmChat, UserMessage
    chat = LlmChat(api_key=EMERGENT_LLM_KEY, session_id=f"parse-{ctx}-{user['user_id']}", system_message=system).with_model("gemini", "gemini-3-flash-preview")
    response = await chat.send_message(UserMessage(text=text))
    raw = response if isinstance(response, str) else (getattr(response, "content", None) or getattr(response, "text", "") or str(response))
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`").split("\n", 1)[-1]
        if raw.endswith("```"):
            raw = raw.rsplit("```", 1)[0]
    try:
        data = json.loads(raw)
    except Exception:
        i, j = raw.find("{"), raw.rfind("}")
        data = json.loads(raw[i:j + 1]) if i >= 0 else {}

    # Resolve customer_name → customer_id for invoice/payment contexts
    if ctx in ("invoice", "payment") and data.get("customer_name"):
        c = next((c for c in customers if data["customer_name"].lower() in c["name"].lower() or c["name"].lower() in data["customer_name"].lower()), None)
        if c:
            data["customer_id"] = c["id"]
    return {"parsed": data, "transcript": text, "context": ctx}


# ============================================================================
# WhatsApp Daily Digest (Iter34)
# ============================================================================

@router.get("/ai/daily-digest")
async def daily_digest(request: Request, user=Depends(get_current_user)):
    from datetime import datetime, timezone, timedelta
    import urllib.parse
    cid = await _active_company_id(request, user)
    today = datetime.now(timezone.utc).date()
    yday = today - timedelta(days=1)
    company = await db.companies.find_one({"id": cid, "user_id": user["user_id"]}, {"_id": 0}) or {}

    # Today's stats
    today_trips = await db.trips.find({"user_id": user["user_id"], "company_id": cid, "date": today.isoformat()}, {"_id": 0}).to_list(500)
    yday_trips = await db.trips.find({"user_id": user["user_id"], "company_id": cid, "date": yday.isoformat()}, {"_id": 0}).to_list(500)
    today_freight = sum(float(t.get("freight_amount", 0)) for t in today_trips)
    today_profit = sum(float(t.get("profit", 0)) for t in today_trips)
    yday_freight = sum(float(t.get("freight_amount", 0)) for t in yday_trips)
    yday_profit = sum(float(t.get("profit", 0)) for t in yday_trips)

    # Overdue receivables — top 3
    overdue = await _tool_list_overdue_invoices(user["user_id"], cid, min_days=1)
    top_overdue = overdue[:3]
    total_outstanding = sum(float(i.get("balance_due", 0)) for i in overdue)

    # Low-margin trips last 7 days
    seven_ago = (today - timedelta(days=7)).isoformat()
    recent_trips = await db.trips.find({"user_id": user["user_id"], "company_id": cid, "date": {"$gte": seven_ago}}, {"_id": 0}).to_list(500)
    low_margin = []
    for t in recent_trips:
        f = float(t.get("freight_amount", 0))
        p = float(t.get("profit", 0))
        if f > 0 and (p / f * 100) < 10:
            low_margin.append({"vehicle": t.get("vehicle_number"), "profit": p, "date": t.get("date"), "margin": round(p / f * 100, 1)})
    low_margin = sorted(low_margin, key=lambda x: x["margin"])[:3]

    lines = [
        f"*📊 Daily Digest — {company.get('name', 'Business')}*",
        f"Date: {today.isoformat()}",
        "",
        f"*💰 Today:* Trips {len(today_trips)}  |  Freight ₹{today_freight:,.0f}  |  Profit ₹{today_profit:,.0f}",
        f"*📅 Yesterday:* Trips {len(yday_trips)}  |  Freight ₹{yday_freight:,.0f}  |  Profit ₹{yday_profit:,.0f}",
        "",
        f"*🔴 Outstanding:* ₹{total_outstanding:,.0f} across {len(overdue)} invoices",
    ]
    if top_overdue:
        lines.append("Top 3:")
        for i in top_overdue:
            lines.append(f"  · {i.get('customer_name', '')} — ₹{float(i.get('balance_due', 0)):,.0f} ({i.get('invoice_number', '')})")
    if low_margin:
        lines.append("")
        lines.append("*⚠ Low-margin trips (7d):*")
        for lm in low_margin:
            lines.append(f"  · {lm['vehicle']} — margin {lm['margin']}% ({lm['date']})")
    lines.append("")
    lines.append(f"— Sent by {company.get('name', 'Bitumen Accounting App')}")
    text = "\n".join(lines)

    return {
        "text": text,
        "whatsapp_url": f"https://wa.me/?text={urllib.parse.quote(text)}",
        "stats": {
            "today_trips": len(today_trips), "today_profit": today_profit,
            "yesterday_profit": yday_profit,
            "outstanding": total_outstanding,
            "overdue_count": len(overdue),
            "low_margin_count": len(low_margin),
        },
    }

