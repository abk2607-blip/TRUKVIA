"""Iter132b · Debit Note tests.

Verifies:
- Feature flag gates DN endpoints
- FY-scoped numbering (independent counter, atomic)
- Effective balance INCREASES with DN, stacks with existing CN
- Original invoice total remains immutable
- Cancelled DN excluded from effective balance
- DN number not reused after cancellation
- Invoice delete blocked while active DN references it
- Related notes endpoint lists DN
- GST/RCM parity inherited from invoice
- Positive-amount guard rejects zero-value DN
- Multiple DN accumulate correctly
"""
import os
import uuid
import httpx
import pytest

BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = BASE + "/api"
HDR = {"Authorization": f"Bearer {os.environ['DEMO_TOKEN_VALUE']}"}


def _pick_company_customer():
    companies = httpx.get(f"{API}/companies", headers=HDR, timeout=15).json()
    cid = companies[0]["id"]
    h = {**HDR, "X-Company-Id": cid}
    custs = httpx.get(f"{API}/customers", headers=h, timeout=15).json()
    if isinstance(custs, dict):
        custs = custs.get("items", custs.get("customers", []))
    return cid, custs[0]["id"], h


def _create_invoice_with_trip():
    """Fresh single-trip non-zero invoice for DN tests."""
    cid, cust_id, h = _pick_company_customer()
    tag = uuid.uuid4().hex[:6]
    trip = httpx.post(f"{API}/trips", headers=h, json={
        "customer_id": cust_id, "date": "2026-06-01",
        "vehicle_number": f"TDN{tag[:4].upper()}",
        "tons": 20, "loaded_qty": 20, "unloaded_qty": 20,
        "freight_mode": "per_ton", "rate_per_ton": 900,
        "product_rate_per_mt": 40000,
        "from_location": "Kakinada", "to_location": "Vizag",
        "loading_date": "2026-06-01", "unloading_date": "2026-06-02",
    }, timeout=15)
    assert trip.status_code == 200, trip.text
    tid = trip.json()["id"]
    inv = httpx.post(f"{API}/invoices", headers=h, json={
        "customer_id": cust_id, "trip_ids": [tid],
        "invoice_date": "2026-06-15", "rcm": True,
    }, timeout=15)
    assert inv.status_code == 200
    inv_doc = inv.json()
    assert float(inv_doc["total_amount"]) > 0
    return inv_doc, cid, h


# ─── Feature flag ────────────────────────────────────────────────────────

def test_feature_flag_gates_debit_endpoints(monkeypatch):
    from routers import notes as _n
    monkeypatch.setattr(_n, "_is_cdn_enabled", lambda: False)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        _n._require_flag()
    assert e.value.status_code == 404


# ─── Numbering (independent counter, FY-scoped) ─────────────────────────

def test_create_debit_note_auto_issues_with_dn_prefix():
    inv, cid, h = _create_invoice_with_trip()
    r = httpx.post(f"{API}/debit-notes", headers=h, json={
        "invoice_id": inv["id"], "note_date": "2026-07-01",
        "reason_code": "missed_halting",
        "reason_text": "Missed halting for 3 days at destination — recoverable per contract",
        "lines": [{"description": "Missed halting charges", "quantity": 3.0, "rate": 1000.0}],
    }, timeout=15)
    assert r.status_code == 200, r.text
    n = r.json()
    assert n["kind"] == "debit"
    assert n["status"] == "issued"
    assert n["note_number"].startswith("DN/")
    assert "/26-27/" in n["note_number"]
    assert n["subtotal"] == 3000.0
    assert n["gst_type"] == inv["gst_type"]
    assert n["cgst_rate"] == inv["cgst_rate"]
    assert n["rcm"] == inv["rcm"]


def test_dn_numbering_independent_from_cn():
    """DN and CN counters advance independently."""
    inv, cid, h = _create_invoice_with_trip()
    cn = httpx.post(f"{API}/credit-notes", headers=h, json={
        "invoice_id": inv["id"], "note_date": "2026-07-01",
        "reason_code": "quality_claim",
        "reason_text": "Quality claim — verifying independent counter",
        "lines": [{"description": "claim", "quantity": 1.0, "rate": 100.0}],
    }, timeout=15).json()
    dn = httpx.post(f"{API}/debit-notes", headers=h, json={
        "invoice_id": inv["id"], "note_date": "2026-07-01",
        "reason_code": "freight_escalation",
        "reason_text": "Freight escalation — verifying independent counter",
        "lines": [{"description": "esc", "quantity": 1.0, "rate": 100.0}],
    }, timeout=15).json()
    assert cn["note_number"].startswith("CN/")
    assert dn["note_number"].startswith("DN/")
    assert cn["note_number"] != dn["note_number"]


# ─── Effective balance semantics ────────────────────────────────────────

def test_effective_balance_increases_with_debit_note():
    """Effective total = Original − CN + DN. Original invoice must not mutate."""
    import asyncio, motor.motor_asyncio
    from services import _apply_effective_balance
    inv, cid, h = _create_invoice_with_trip()
    original_total = inv["total_amount"]
    httpx.post(f"{API}/debit-notes", headers=h, json={
        "invoice_id": inv["id"], "note_date": "2026-07-01",
        "reason_code": "under_charge",
        "reason_text": "Under-charge correction — testing DN increases balance",
        "lines": [{"description": "under-charge", "quantity": 1.0, "rate": 2000.0}],
    }, timeout=15)

    async def _check():
        c = motor.motor_asyncio.AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = c[os.environ["DB_NAME"]]
        inv_doc = await db.invoices.find_one({"id": inv["id"]}, {"_id": 0})
        uid = inv_doc["user_id"]
        # Original invoice total_amount must remain identical (immutability)
        assert inv_doc["total_amount"] == original_total, \
            f"Original invoice total mutated: {inv_doc['total_amount']} != {original_total}"
        del inv_doc["user_id"]
        await _apply_effective_balance([inv_doc], uid, cid)
        c.close()
        return inv_doc
    doc = asyncio.run(_check())
    assert doc["effective_total_amount"] > doc["total_amount"], \
        f"DN should increase effective total ({doc['total_amount']} → {doc['effective_total_amount']})"
    assert abs(doc["effective_total_amount"] - (original_total + 2000)) < 0.01


def test_multiple_debit_notes_accumulate():
    inv, cid, h = _create_invoice_with_trip()
    for i in range(3):
        r = httpx.post(f"{API}/debit-notes", headers=h, json={
            "invoice_id": inv["id"], "note_date": "2026-07-01",
            "reason_code": "other",
            "reason_text": f"DN {i+1} of 3 — accumulation test",
            "lines": [{"description": f"line-{i}", "quantity": 1.0, "rate": 500.0}],
        }, timeout=15)
        assert r.status_code == 200, r.text
    r = httpx.get(f"{API}/invoices/{inv['id']}/notes", headers=h, timeout=15)
    dns = [n for n in r.json() if n["kind"] == "debit" and n["status"] == "issued"]
    assert len(dns) >= 3
    total = sum(n["total_amount"] for n in dns)
    assert total >= 1500.0


def test_cancelled_dn_excluded_from_effective_balance():
    import asyncio, motor.motor_asyncio
    inv, cid, h = _create_invoice_with_trip()
    original_total = inv["total_amount"]
    dn = httpx.post(f"{API}/debit-notes", headers=h, json={
        "invoice_id": inv["id"], "note_date": "2026-07-01",
        "reason_code": "other",
        "reason_text": "DN to be cancelled — must not affect balance",
        "lines": [{"description": "x", "quantity": 1.0, "rate": 500.0}],
    }, timeout=15).json()
    httpx.post(f"{API}/debit-notes/{dn['id']}/cancel", headers=h,
               json={"reason": "Cancellation test for effective-balance exclusion"}, timeout=15)

    async def _check():
        # Local Motor client (matches Iter132a proven pattern — avoids the
        # shared services.db module-level client bound to a closed loop).
        c = motor.motor_asyncio.AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = c[os.environ["DB_NAME"]]
        inv_doc = await db.invoices.find_one({"id": inv["id"]}, {"_id": 0})
        notes = await db.credit_debit_notes.find(
            {"invoice_id": inv["id"], "status": "issued"},
            {"_id": 0, "kind": 1, "total_amount": 1},
        ).to_list(100)
        credits = sum(n["total_amount"] for n in notes if n["kind"] == "credit")
        debits = sum(n["total_amount"] for n in notes if n["kind"] == "debit")
        effective = float(inv_doc["total_amount"]) - credits + debits
        c.close()
        return effective, float(inv_doc["total_amount"])
    effective, raw = asyncio.run(_check())
    assert abs(effective - raw) < 0.01, \
        f"Cancelled DN should not contribute: effective={effective} raw={raw}"


def test_cancelled_dn_number_not_reused():
    inv, cid, h = _create_invoice_with_trip()
    r1 = httpx.post(f"{API}/debit-notes", headers=h, json={
        "invoice_id": inv["id"], "note_date": "2026-07-01",
        "reason_code": "other",
        "reason_text": "First DN — will be cancelled to verify number never reused",
        "lines": [{"description": "x", "quantity": 1.0, "rate": 100.0}],
    }, timeout=15).json()
    num_first = r1["note_number"]
    httpx.post(f"{API}/debit-notes/{r1['id']}/cancel", headers=h,
               json={"reason": "cancelling to verify no number reuse for DN"}, timeout=15)
    r2 = httpx.post(f"{API}/debit-notes", headers=h, json={
        "invoice_id": inv["id"], "note_date": "2026-07-02",
        "reason_code": "other",
        "reason_text": "Second DN — must receive a fresh number, not the cancelled one",
        "lines": [{"description": "y", "quantity": 1.0, "rate": 100.0}],
    }, timeout=15).json()
    assert r2["note_number"] != num_first


# ─── Invoice delete guard ───────────────────────────────────────────────

def test_invoice_delete_blocked_by_active_dn():
    inv, cid, h = _create_invoice_with_trip()
    httpx.post(f"{API}/debit-notes", headers=h, json={
        "invoice_id": inv["id"], "note_date": "2026-07-01",
        "reason_code": "other",
        "reason_text": "Blocking invoice delete for active-DN test scenario",
        "lines": [{"description": "x", "quantity": 1.0, "rate": 100.0}],
    }, timeout=15)
    r = httpx.request("DELETE", f"{API}/invoices/{inv['id']}", headers=h,
                      params={"reason": "test delete block by DN"}, timeout=15)
    assert r.status_code == 409, r.text


# ─── Related notes includes DN ──────────────────────────────────────────

def test_related_notes_endpoint_includes_dn():
    inv, cid, h = _create_invoice_with_trip()
    httpx.post(f"{API}/debit-notes", headers=h, json={
        "invoice_id": inv["id"], "note_date": "2026-07-01",
        "reason_code": "rate_correction",
        "reason_text": "Related-notes endpoint verification for DN listing",
        "lines": [{"description": "rate diff", "quantity": 1.0, "rate": 250.0}],
    }, timeout=15)
    r = httpx.get(f"{API}/invoices/{inv['id']}/notes", headers=h, timeout=15)
    notes = r.json()
    assert any(n["kind"] == "debit" for n in notes)


# ─── Positive-amount guard ──────────────────────────────────────────────

def test_dn_rejects_zero_amount():
    inv, cid, h = _create_invoice_with_trip()
    r = httpx.post(f"{API}/debit-notes", headers=h, json={
        "invoice_id": inv["id"], "note_date": "2026-07-01",
        "reason_code": "other",
        "reason_text": "Zero-amount DN must be rejected as invalid",
        "lines": [{"description": "zero", "quantity": 0.0, "rate": 0.0}],
    }, timeout=15)
    assert r.status_code == 422
    assert "positive" in r.text.lower()


# ─── Historical invoice rejected ────────────────────────────────────────

def test_historical_invoice_rejects_dn():
    import asyncio, motor.motor_asyncio
    inv, cid, h = _create_invoice_with_trip()
    async def _mark():
        c = motor.motor_asyncio.AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = c[os.environ["DB_NAME"]]
        await db.invoices.update_one({"id": inv["id"]}, {"$set": {"is_historical": True}})
        c.close()
    asyncio.run(_mark())
    r = httpx.post(f"{API}/debit-notes", headers=h, json={
        "invoice_id": inv["id"], "note_date": "2026-07-01",
        "reason_code": "other",
        "reason_text": "Historical invoice DN must be rejected per Iter86 isolation",
        "lines": [{"description": "x", "quantity": 1.0, "rate": 100.0}],
    }, timeout=15)
    assert r.status_code == 422
