"""Iter132a · Credit Note foundation tests.

Covers:
  - Numbering: per-company, per-FY (derived from note_date), 31-Mar/1-Apr boundary
  - Rate/GST-type inheritance from invoice; RCM parity
  - Over-credit guard (422)
  - Historical invoices rejected
  - Cancelled notes excluded from effective_balance and outstanding
  - Cancelled notes don't reuse the number
  - Invoice delete blocked while non-cancelled notes reference it
  - Auto-issue when require_cdn_approval=false
  - Feature flag: 404 when ENABLE_CDN unset

Everything runs against the live preview backend with the demo token."""
import os
import uuid
import httpx
import pytest

BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = BASE + "/api"
HDR = {"Authorization": f"Bearer {os.environ['DEMO_TOKEN_VALUE']}"}


def _pick_active_company_and_customer():
    companies = httpx.get(f"{API}/companies", headers=HDR, timeout=15).json()
    assert companies, "no companies for demo tenant"
    cid = companies[0]["id"]
    h = {**HDR, "X-Company-Id": cid}
    custs = httpx.get(f"{API}/customers", headers=h, timeout=15).json()
    if isinstance(custs, dict):
        custs = custs.get("items", custs.get("customers", []))
    assert custs, "no customers for demo tenant"
    return cid, custs[0]["id"], h


def _create_invoice_with_trip():
    """Create a fresh single-trip invoice and return (invoice, company_id, header)."""
    cid, cust_id, h = _pick_active_company_and_customer()
    tag = uuid.uuid4().hex[:8]
    trip = httpx.post(
        f"{API}/trips",
        headers=h,
        json={
            "date": "2026-06-01", "vehicle_number": f"TCN{tag[:4].upper()}",
            "customer_id": cust_id, "product_id": None,
            "from_location": "FromCity", "to_location": "ToCity",
            "tons": 10.0, "rate": 500.0, "freight_amount": 5000.0,
            "basis": "per_ton",
        },
        timeout=15,
    )
    assert trip.status_code == 200, trip.text
    tid = trip.json()["id"]
    inv = httpx.post(
        f"{API}/invoices",
        headers=h,
        json={"customer_id": cust_id, "trip_ids": [tid], "invoice_date": "2026-06-15", "rcm": True},
        timeout=15,
    )
    assert inv.status_code == 200, inv.text
    return inv.json(), cid, h


# ─── Feature flag ────────────────────────────────────────────────────────

def test_feature_flag_gates_endpoints(monkeypatch):
    """When ENABLE_CDN is not '1', the create endpoint must return 404."""
    from routers import notes as _notes
    monkeypatch.setattr(_notes, "_is_cdn_enabled", lambda: False)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        _notes._require_flag()
    assert e.value.status_code == 404


# ─── Numbering & FY handling ─────────────────────────────────────────────

def test_fy_derivation_from_note_date():
    """31-March lands in outgoing FY; 1-April lands in new FY."""
    from services import _derive_fy_from_iso
    assert _derive_fy_from_iso("2027-03-31") == "26-27"
    assert _derive_fy_from_iso("2027-04-01") == "27-28"
    assert _derive_fy_from_iso("2027-01-15") == "26-27"
    assert _derive_fy_from_iso("2027-12-01") == "27-28"


def test_create_credit_note_auto_issues_and_numbers_correctly():
    inv, cid, h = _create_invoice_with_trip()
    r = httpx.post(
        f"{API}/credit-notes",
        headers=h,
        json={
            "invoice_id": inv["id"],
            "note_date": "2026-07-01",
            "reason_code": "short_delivery",
            "reason_text": "Short delivery on trip — 500 kg short at destination weighbridge",
            "lines": [{"description": "Short delivery adjustment", "quantity": 0.5, "rate": 500.0}],
        },
        timeout=15,
    )
    assert r.status_code == 200, r.text
    n = r.json()
    assert n["kind"] == "credit"
    assert n["status"] == "issued"  # require_cdn_approval defaults to False
    assert n["note_number"].startswith(("CN/", ))
    assert "/26-27/" in n["note_number"]
    assert n["subtotal"] == 250.0
    assert n["gst_type"] == inv["gst_type"]
    assert n["cgst_rate"] == inv["cgst_rate"]
    assert n["sgst_rate"] == inv["sgst_rate"]
    assert n["rcm"] == inv["rcm"]


# ─── Over-credit guard ───────────────────────────────────────────────────

def test_over_credit_returns_422():
    inv, cid, h = _create_invoice_with_trip()
    huge = inv["total_amount"] + 1000
    r = httpx.post(
        f"{API}/credit-notes",
        headers=h,
        json={
            "invoice_id": inv["id"],
            "note_date": "2026-07-01",
            "reason_code": "rate_correction",
            "reason_text": "Rate correction test — over-credit guard should reject",
            "lines": [{"description": "Rate over-adjustment", "quantity": 1.0, "rate": huge}],
        },
        timeout=15,
    )
    assert r.status_code == 422, r.text
    assert "negative" in r.text.lower()


# ─── Historical invoices rejected ────────────────────────────────────────

def test_historical_invoice_rejected():
    """Iter86 imported invoices must not accept CNs."""
    inv, cid, h = _create_invoice_with_trip()
    # Mark this invoice historical directly in Mongo
    import asyncio, motor.motor_asyncio
    async def _mark():
        c = motor.motor_asyncio.AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = c[os.environ["DB_NAME"]]
        await db.invoices.update_one({"id": inv["id"]}, {"$set": {"is_historical": True}})
        c.close()
    asyncio.run(_mark())
    r = httpx.post(
        f"{API}/credit-notes",
        headers=h,
        json={
            "invoice_id": inv["id"], "note_date": "2026-07-01",
            "reason_code": "other",
            "reason_text": "Historical invoice — should be rejected",
            "lines": [{"description": "test", "quantity": 1.0, "rate": 100.0}],
        },
        timeout=15,
    )
    assert r.status_code == 422, r.text


# ─── Cancellation semantics ──────────────────────────────────────────────

def test_cancelled_note_excluded_from_effective_balance():
    inv, cid, h = _create_invoice_with_trip()
    r = httpx.post(
        f"{API}/credit-notes", headers=h,
        json={
            "invoice_id": inv["id"], "note_date": "2026-07-01",
            "reason_code": "post_invoice_discount",
            "reason_text": "Discount for prompt payment — cancellation flow test",
            "lines": [{"description": "Discount", "quantity": 1.0, "rate": 500.0}],
        }, timeout=15,
    )
    assert r.status_code == 200
    n = r.json()
    # Cancel it (owner via demo effective_role)
    c = httpx.post(
        f"{API}/credit-notes/{n['id']}/cancel", headers=h,
        json={"reason": "Test cancellation flow — verify exclusion from effective balance"},
        timeout=15,
    )
    assert c.status_code == 200, c.text
    assert c.json()["status"] == "cancelled"
    # Now the invoice's effective_balance_due must equal its raw balance_due.
    from services import _apply_effective_balance
    import asyncio
    async def _check():
        import motor.motor_asyncio
        conn = motor.motor_asyncio.AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = conn[os.environ["DB_NAME"]]
        inv_doc = await db.invoices.find_one({"id": inv["id"]}, {"_id": 0})
        uid = inv_doc.get("user_id")
        del inv_doc["user_id"]
        await _apply_effective_balance([inv_doc], uid, cid)
        conn.close()
        return inv_doc
    doc = asyncio.run(_check())
    assert abs(doc["effective_balance_due"] - doc["balance_due"]) < 0.01


def test_cancelled_note_number_not_reused():
    inv, cid, h = _create_invoice_with_trip()
    r1 = httpx.post(f"{API}/credit-notes", headers=h, json={
        "invoice_id": inv["id"], "note_date": "2026-07-01",
        "reason_code": "other",
        "reason_text": "First CN — will be cancelled",
        "lines": [{"description": "x", "quantity": 1.0, "rate": 100.0}],
    }, timeout=15).json()
    number_first = r1["note_number"]
    httpx.post(f"{API}/credit-notes/{r1['id']}/cancel", headers=h,
               json={"reason": "cancelling to verify no number reuse"}, timeout=15)
    r2 = httpx.post(f"{API}/credit-notes", headers=h, json={
        "invoice_id": inv["id"], "note_date": "2026-07-02",
        "reason_code": "other",
        "reason_text": "Second CN — should get a NEW number, not the cancelled one",
        "lines": [{"description": "y", "quantity": 1.0, "rate": 100.0}],
    }, timeout=15).json()
    assert r2["note_number"] != number_first


# ─── Invoice delete blocked ──────────────────────────────────────────────

def test_invoice_delete_blocked_with_active_note():
    inv, cid, h = _create_invoice_with_trip()
    httpx.post(f"{API}/credit-notes", headers=h, json={
        "invoice_id": inv["id"], "note_date": "2026-07-01",
        "reason_code": "other",
        "reason_text": "Blocking invoice delete for active-note test",
        "lines": [{"description": "x", "quantity": 1.0, "rate": 100.0}],
    }, timeout=15)
    r = httpx.request("DELETE", f"{API}/invoices/{inv['id']}",
                      headers=h, params={"reason": "test delete block"}, timeout=15)
    assert r.status_code == 409, r.text
    assert "credit/debit" in r.text.lower() or "cancel" in r.text.lower()


# ─── Related-notes endpoint ──────────────────────────────────────────────

def test_invoice_related_notes_endpoint():
    inv, cid, h = _create_invoice_with_trip()
    httpx.post(f"{API}/credit-notes", headers=h, json={
        "invoice_id": inv["id"], "note_date": "2026-07-01",
        "reason_code": "quality_claim",
        "reason_text": "Quality claim for product batch — related notes endpoint test",
        "lines": [{"description": "claim", "quantity": 1.0, "rate": 100.0}],
    }, timeout=15)
    r = httpx.get(f"{API}/invoices/{inv['id']}/notes", headers=h, timeout=15)
    assert r.status_code == 200
    notes = r.json()
    assert len(notes) >= 1
    assert notes[0]["invoice_id"] == inv["id"]


# ─── Additive RBAC (locked scope guarantee) ─────────────────────────────

def test_role_permissions_still_intact():
    from models import ROLE_PERMISSIONS
    # Existing entries unchanged
    for perm in ("edit_trip", "delete_trip", "edit_invoice", "delete_invoice",
                 "edit_master", "delete_master", "manage_users"):
        assert perm in ROLE_PERMISSIONS["owner"], f"owner lost pre-existing perm {perm}"
    for perm in ("edit_trip", "edit_invoice", "edit_master"):
        assert perm in ROLE_PERMISSIONS["accountant"], f"accountant lost pre-existing perm {perm}"
    assert ROLE_PERMISSIONS["viewer"] == set()
    # Additive CN/DN entries
    for perm in ("create_note", "issue_note", "cancel_note", "edit_note_settings"):
        assert perm in ROLE_PERMISSIONS["owner"]
    for perm in ("create_note", "issue_note"):
        assert perm in ROLE_PERMISSIONS["accountant"]
