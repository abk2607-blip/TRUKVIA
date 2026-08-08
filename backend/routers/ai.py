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
