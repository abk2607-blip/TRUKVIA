"""Iter134 · Invoice Number Reason Binding — UAT-blocker regression.

Guards the end-to-end contract that produced the live UAT failure:

    Reason field visibly contains "Manual serial correction"
    Create Invoice → server returns "invoice_number_reason must be at
    least 10 characters when overriding"

Root cause hardened here:
  - Frontend now ALWAYS sends `invoice_number` + trimmed
    `invoice_number_reason` when the Owner has touched the field.
    Backend remains the source of truth for override vs no-override
    (via live preview comparison).
  - Reason is trimmed on the wire, so whitespace-only reasons collapse
    to "" and are rejected consistently.
  - Frontend blocks the Create button when the trimmed reason is < 10
    chars during an active override, so an already-valid reason can
    never hit the 400 error.

This suite exercises the backend contract via HTTP and pins the
frontend source shape.  Iter133 remains untouched.
"""
from __future__ import annotations
import os, uuid, re, requests, pytest

BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
DEMO = os.environ["DEMO_TOKEN_VALUE"]
H = {"Authorization": f"Bearer {DEMO}", "Content-Type": "application/json"}
SRC = "/app/frontend/src/pages/InvoiceCreate.jsx"


def _src() -> str:
    with open(SRC, "r", encoding="utf-8") as f:
        return f.read()


# ── frontend shape guards ─────────────────────────────────────────────

def test_reason_is_trimmed_on_wire():
    """Payload must send `trimmedReason`, not the raw state.  Guards against
    whitespace-only reasons that would appear valid in the DOM but collapse
    to empty on the server."""
    src = _src()
    assert "trimmedReason = (overrideReason" in src
    assert "invoice_number_reason: trimmedReason" in src


def test_invoice_number_is_trimmed_on_wire():
    src = _src()
    assert "trimmedNum = (invoiceNumber" in src
    assert "invoice_number: trimmedNum" in src


def test_payload_gate_is_owner_edited_notgated_by_local_suggested():
    """The mutation must NOT gate the outgoing payload on
    `invoiceNumber !== suggestedNumber` (that comparison uses stale local
    state and produced the UAT bug).  Owner + edited + non-empty is the
    only gate; backend is the source of truth for override vs no-override."""
    src = _src()
    # The buggy inline gate must not resurface in the mutation body.
    m = re.search(r"const create = useMutation\(\{[\s\S]+?onError:", src)
    assert m, "mutation body not found"
    body = m.group(0)
    assert "isOwner && invoiceNumberEdited && trimmedNum" in body
    assert "invoiceNumber !== suggestedNumber" not in body


def test_create_button_blocks_short_reason():
    src = _src()
    assert "reasonInvalid" in src
    assert "!reasonInvalid" in src  # feeds into canSubmit


def test_inline_reason_hint_present():
    src = _src()
    assert 'data-testid="invoice-number-reason-hint"' in src
    assert "at least 10 characters" in src


# ── backend contract regression ───────────────────────────────────────

@pytest.fixture(scope="module")
def customer():
    r = requests.post(f"{API}/customers", headers=H, json={
        "name": f"IT134-rb-{uuid.uuid4().hex[:6]}", "state": "Andhra Pradesh",
    }, timeout=10); r.raise_for_status(); return r.json()


def _trip(cid: str, d: str) -> str:
    r = requests.post(f"{API}/trips", headers=H, json={
        "customer_id": cid, "date": d, "vehicle_number": "AP16RB0134",
        "from_location": "A", "to_location": "B", "tons": 10, "unloaded_qty": 10,
        "freight_mode": "per_ton", "rate_per_ton": 500,
        "product_name": "Bitumen", "product_rate_per_mt": 40000,
    }, timeout=10); r.raise_for_status(); return r.json()["id"]


def _post_invoice(customer_id: str, trip_id: str, date: str, **override):
    return requests.post(f"{API}/invoices", headers=H, json={
        "customer_id": customer_id, "trip_ids": [trip_id],
        "invoice_date": date, "hsn_sac": "996791",
        "gst_type": "cgst_sgst", "rcm": True, "notes": "",
        **override,
    }, timeout=10)


def test_valid_24char_reason_accepted(customer):
    """The exact UAT payload — 'Manual serial correction' (24 chars) —
    must succeed with an override number."""
    tid = _trip(customer["id"], "2026-01-24")
    num = f"IT134RB/25-26/{uuid.uuid4().hex[:6].upper()}"
    r = _post_invoice(customer["id"], tid, "2026-01-24",
                      invoice_number=num,
                      invoice_number_reason="Manual serial correction")
    assert r.status_code == 200, r.text
    assert r.json()["invoice_number"] == num


def test_exactly_10char_reason_accepted(customer):
    tid = _trip(customer["id"], "2026-01-25")
    num = f"IT134RB2/25-26/{uuid.uuid4().hex[:6].upper()}"
    r = _post_invoice(customer["id"], tid, "2026-01-25",
                      invoice_number=num,
                      invoice_number_reason="1234567890")  # exactly 10
    assert r.status_code == 200, r.text


def test_9char_reason_rejected(customer):
    tid = _trip(customer["id"], "2026-01-26")
    num = f"IT134RB3/25-26/{uuid.uuid4().hex[:6].upper()}"
    r = _post_invoice(customer["id"], tid, "2026-01-26",
                      invoice_number=num,
                      invoice_number_reason="123456789")  # 9
    assert r.status_code == 400
    assert "10 char" in r.json()["detail"].lower()


def test_whitespace_only_reason_rejected(customer):
    """Frontend trims — backend also trims — so a whitespace-only reason
    must collapse to empty and be rejected."""
    tid = _trip(customer["id"], "2026-01-27")
    num = f"IT134RB4/25-26/{uuid.uuid4().hex[:6].upper()}"
    r = _post_invoice(customer["id"], tid, "2026-01-27",
                      invoice_number=num,
                      invoice_number_reason="              ")  # 14 spaces
    assert r.status_code == 400
    assert "10 char" in r.json()["detail"].lower()


def test_padded_reason_trimmed_and_accepted(customer):
    """Backend trims — a valid reason with surrounding whitespace works."""
    tid = _trip(customer["id"], "2026-01-28")
    num = f"IT134RB5/25-26/{uuid.uuid4().hex[:6].upper()}"
    r = _post_invoice(customer["id"], tid, "2026-01-28",
                      invoice_number=num,
                      invoice_number_reason="   Manual serial correction   ")
    assert r.status_code == 200, r.text


def test_no_override_no_reason_required(customer):
    """No `invoice_number` sent → uses server-suggested → reason not required."""
    tid = _trip(customer["id"], "2026-01-29")
    r = _post_invoice(customer["id"], tid, "2026-01-29")
    assert r.status_code == 200, r.text
    assert "/25-26/" in r.json()["invoice_number"]


def test_matching_suggested_number_no_reason_required(customer):
    """Sending the exact server-suggested number is NOT an override — no
    reason validation, no 400."""
    tid = _trip(customer["id"], "2026-01-30")
    pre = requests.get(f"{API}/invoices/next-preview", headers=H,
                       params={"invoice_date": "2026-01-30"}, timeout=10).json()
    r = _post_invoice(customer["id"], tid, "2026-01-30",
                      invoice_number=pre["suggested_number"])
    assert r.status_code == 200, r.text


def test_duplicate_override_number_returns_409(customer):
    """After a valid override, the same number with a valid reason must be
    rejected as a duplicate — the request reaches uniqueness enforcement,
    NOT the reason-length rejection."""
    tid1 = _trip(customer["id"], "2026-01-31")
    tid2 = _trip(customer["id"], "2026-01-31")
    dup_num = f"IT134DUP/25-26/{uuid.uuid4().hex[:6].upper()}"
    r1 = _post_invoice(customer["id"], tid1, "2026-01-31",
                       invoice_number=dup_num,
                       invoice_number_reason="Manual serial correction")
    assert r1.status_code == 200, r1.text
    r2 = _post_invoice(customer["id"], tid2, "2026-01-31",
                       invoice_number=dup_num,
                       invoice_number_reason="Manual serial correction")
    assert r2.status_code == 409, r2.text
    assert "already exists" in r2.json()["detail"].lower()


def test_override_audit_captures_reason_original_and_final(customer):
    """After a valid override the audit trail records the reason, the
    server-suggested number, and the final invoice number."""
    tid = _trip(customer["id"], "2026-02-01")
    num = f"IT134AUD/25-26/{uuid.uuid4().hex[:6].upper()}"
    pre = requests.get(f"{API}/invoices/next-preview", headers=H,
                       params={"invoice_date": "2026-02-01"}, timeout=10).json()
    r = _post_invoice(customer["id"], tid, "2026-02-01",
                      invoice_number=num,
                      invoice_number_reason="Manual serial correction")
    assert r.status_code == 200, r.text
    inv_id = r.json()["id"]

    # Pull the audit log for this invoice via /audit-logs.
    audit = requests.get(f"{API}/audit-logs", headers=H,
                         params={"module": "invoice", "entity_id": inv_id, "limit": 50},
                         timeout=10).json()
    override_rows = [a for a in audit if "override" in (a.get("action") or "").lower()]
    assert override_rows, f"no override audit row for {inv_id} · rows={audit}"
    top = override_rows[0]
    assert top.get("reason") == "Manual serial correction"
    changes = top.get("changes") or {}
    assert changes.get("new_number") == num
    assert changes.get("suggested_number") == pre["suggested_number"]
