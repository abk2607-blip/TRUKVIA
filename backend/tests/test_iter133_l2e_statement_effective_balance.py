"""Iter133 · L2e — Statement effective-balance parity.

Bug: customer_statement_pdf() called `_apply_effective_balance` but then
read raw `invoice.balance_due` on line 746, causing the Statement's
OUTSTANDING / summary Outstanding / Balance Bridge Balance Due /
Amount-in-Words to disagree with the Ledger closing balance for any
customer with issued CN/DN.

Fix: one-line read-side change — consume `effective_balance_due` with
fallback to raw `balance_due` (same pattern as dashboard, reminders,
customer-list, per-invoice API). Persisted balance_due untouched.

These 6 tests lock the fix and enforce cross-surface parity with the
Ledger PDF's closing balance.
"""
import io
import os
import re
import uuid
import httpx
import pytest
from pdfminer.high_level import extract_text as _pdf_extract


def _api():
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                return line.split("=", 1)[1].strip().strip('"').strip("'") + "/api"
    raise RuntimeError("REACT_APP_BACKEND_URL not found")


API = _api()
TOK = os.environ["DEMO_TOKEN_VALUE"]


def _headers():
    h = {"Authorization": f"Bearer {TOK}", "Content-Type": "application/json"}
    cid = httpx.get(f"{API}/companies", headers=h, timeout=10).json()[0]["id"]
    h["X-Company-Id"] = cid
    return cid, h


def _fresh_customer(h, prefix="L2E"):
    tag = uuid.uuid4().hex[:8]
    r = httpx.post(f"{API}/customers", headers=h,
                   json={"name": f"{prefix}-{tag}", "phone": f"9{tag}",
                         "state": "Andhra Pradesh"}, timeout=10)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _seed_trip_invoice(h, cust_id, tons=25, rate=1000, date="2026-07-15"):
    """Create trip → invoice. RCM=True so total_amount == freight (no GST added)."""
    tag = uuid.uuid4().hex[:5]
    r = httpx.post(
        f"{API}/trips", headers=h,
        json={"customer_id": cust_id, "date": date,
              "vehicle_number": f"L2E{tag}",
              "tons": tons, "loaded_qty": tons, "unloaded_qty": tons,
              "freight_mode": "per_ton", "rate_per_ton": rate,
              "product_rate_per_mt": 40000,
              "from_location": "A", "to_location": "B",
              "loading_date": date, "unloading_date": date},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    trip_id = r.json()["id"]
    r = httpx.post(
        f"{API}/invoices", headers=h,
        json={"customer_id": cust_id, "trip_ids": [trip_id],
              "invoice_date": date, "rcm": True},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _issue_note(h, kind, invoice, amount, note_date="2026-07-25",
                reason_code="other", reason_text=None):
    endpoint = "credit-notes" if kind == "credit" else "debit-notes"
    r = httpx.post(
        f"{API}/{endpoint}", headers=h,
        json={"invoice_id": invoice["id"], "note_date": note_date,
              "reason_code": reason_code,
              "reason_text": reason_text or f"L2E {kind} note",
              "lines": [{"description": f"L2E {kind}",
                         "quantity": 1, "rate": amount}]},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _statement_pdf(h, cust_id):
    r = httpx.get(f"{API}/customers/{cust_id}/statement.pdf",
                  headers=h, timeout=30)
    assert r.status_code == 200, r.text
    return r.content


def _ledger_closing(h, cust_id):
    r = httpx.get(f"{API}/reports/ledger", headers=h,
                  params={"customer_id": cust_id}, timeout=20)
    assert r.status_code == 200, r.text
    return float(r.json()["closing_balance"])


def _extract(pdf_bytes):
    return _pdf_extract(io.BytesIO(pdf_bytes))


_NUM_RE = re.compile(r"([\d,]+\.\d{2})")


def _parse_money(s):
    return float(s.replace(",", ""))


def _parse_bridge(text):
    """Bridge is 5 rows × 2 cols; pdfminer emits col-major:
    5 labels then 5 amounts."""
    m = re.search(
        r"Balance Bridge(.+?)(?:Adjustments|Amount in Words|$)",
        text,
        re.DOTALL,
    )
    assert m, "Balance Bridge section not found in Statement PDF"
    section = m.group(1)
    amounts = re.findall(r"([\d,]+\.\d{2})", section)
    assert len(amounts) >= 5, (
        f"expected ≥5 amounts in Bridge, got {len(amounts)}"
    )
    v = [_parse_money(a) for a in amounts[:5]]
    return {
        "original": v[0],
        "credits": v[1],
        "debits": v[2],
        "payments": v[3],
        "balance_due": v[4],
    }


def _amount_in_words_line(text):
    m = re.search(r"Amount in Words:\s*(.+?)(?:\s*\(([DC]r)\))?\s*\n", text)
    assert m, "Amount-in-Words line not found in Statement PDF"
    return m.group(1).strip()


# =====================================================================
# TEST 1 — CN-only
# =====================================================================

def test_l2e_t1_cn_only_statement_balance_reduces_by_credit():
    _cid, h = _headers()
    cust = _fresh_customer(h)
    inv = _seed_trip_invoice(h, cust, tons=25, rate=1000)  # ₹25,000
    assert float(inv["total_amount"]) == pytest.approx(25000.0)
    _issue_note(h, "credit", inv, 2000.0)

    text = _extract(_statement_pdf(h, cust))
    br = _parse_bridge(text)
    assert br["original"]    == pytest.approx(25000.0)
    assert br["credits"]     == pytest.approx(2000.0)
    assert br["debits"]      == pytest.approx(0.0)
    assert br["payments"]    == pytest.approx(0.0)
    assert br["balance_due"] == pytest.approx(23000.0), \
        f"CN-only statement Balance Due should be 25000-2000=23000, got {br['balance_due']}"
    # Ledger parity
    assert _ledger_closing(h, cust) == pytest.approx(23000.0)


# =====================================================================
# TEST 2 — DN-only
# =====================================================================

def test_l2e_t2_dn_only_statement_balance_increases_by_debit():
    _cid, h = _headers()
    cust = _fresh_customer(h)
    inv = _seed_trip_invoice(h, cust, tons=25, rate=1000)  # ₹25,000
    _issue_note(h, "debit", inv, 1500.0)

    text = _extract(_statement_pdf(h, cust))
    br = _parse_bridge(text)
    assert br["original"]    == pytest.approx(25000.0)
    assert br["credits"]     == pytest.approx(0.0)
    assert br["debits"]      == pytest.approx(1500.0)
    assert br["payments"]    == pytest.approx(0.0)
    assert br["balance_due"] == pytest.approx(26500.0), \
        f"DN-only statement Balance Due should be 25000+1500=26500, got {br['balance_due']}"
    assert _ledger_closing(h, cust) == pytest.approx(26500.0)


# =====================================================================
# TEST 3 — CN + DN → exact Ledger parity
# =====================================================================

def test_l2e_t3_cn_and_dn_statement_matches_ledger_closing_balance():
    _cid, h = _headers()
    cust = _fresh_customer(h)
    inv = _seed_trip_invoice(h, cust, tons=25, rate=1000)  # ₹25,000
    _issue_note(h, "credit", inv, 500.0)   # −500
    _issue_note(h, "debit",  inv, 3000.0)  # +3000

    # Expected effective = 25000 − 500 + 3000 = 27,500
    ledger_closing = _ledger_closing(h, cust)
    assert ledger_closing == pytest.approx(27500.0)

    text = _extract(_statement_pdf(h, cust))
    br = _parse_bridge(text)
    assert br["original"]    == pytest.approx(25000.0)
    assert br["credits"]     == pytest.approx(500.0)
    assert br["debits"]      == pytest.approx(3000.0)
    assert br["payments"]    == pytest.approx(0.0)
    # Critical: Statement Balance Due == Ledger closing balance.
    assert br["balance_due"] == pytest.approx(ledger_closing), (
        f"Statement Balance Due {br['balance_due']} must equal "
        f"Ledger closing_balance {ledger_closing}"
    )
    assert br["balance_due"] == pytest.approx(27500.0)


# =====================================================================
# TEST 4 — No-notes regression
# =====================================================================

def test_l2e_t4_no_notes_regression_statement_matches_ledger():
    _cid, h = _headers()
    cust = _fresh_customer(h)
    inv = _seed_trip_invoice(h, cust, tons=30, rate=800)  # ₹24,000

    ledger_closing = _ledger_closing(h, cust)
    assert ledger_closing == pytest.approx(24000.0)

    text = _extract(_statement_pdf(h, cust))
    br = _parse_bridge(text) if "Balance Bridge" in text else None
    # If no CN/DN issued, the Statement omits the Balance Bridge/Adjustments
    # sections. Verify Outstanding hero + Summary Outstanding value present
    # and equal to Ledger closing.
    m = re.search(r"OUTSTANDING\s+₹\s*([\d,]+\.\d{2})", text)
    assert m, f"Outstanding hero not found. Text tail:\n{text[-1000:]}"
    outstanding_hero = _parse_money(m.group(1))
    assert outstanding_hero == pytest.approx(ledger_closing), \
        f"No-notes statement Outstanding {outstanding_hero} must equal " \
        f"Ledger closing_balance {ledger_closing}"


# =====================================================================
# TEST 5 — Balance Bridge arithmetic is internally self-consistent
# =====================================================================

def test_l2e_t5_bridge_arithmetic_is_self_consistent():
    """For any CN+DN customer: Original − Credits + Debits − Payments must
    equal the printed Balance Due — with cent precision."""
    _cid, h = _headers()
    cust = _fresh_customer(h)
    inv = _seed_trip_invoice(h, cust, tons=40, rate=1250)  # ₹50,000
    _issue_note(h, "credit", inv, 1750.0)
    _issue_note(h, "debit",  inv, 4250.0)

    text = _extract(_statement_pdf(h, cust))
    br = _parse_bridge(text)
    computed = round(
        br["original"] - br["credits"] + br["debits"] - br["payments"], 2
    )
    assert computed == pytest.approx(br["balance_due"]), (
        f"Bridge arithmetic broken: "
        f"{br['original']} − {br['credits']} + {br['debits']} − "
        f"{br['payments']} = {computed}, printed Balance Due = {br['balance_due']}"
    )


# =====================================================================
# TEST 6 — Amount-in-Words matches effective Balance Due
# =====================================================================

def test_l2e_t6_amount_in_words_matches_effective_balance():
    """The 'Amount in Words' line must render the effective outstanding
    (matching Ledger closing) — never the raw persisted balance_due."""
    from pdf._base import _num_to_words_inr

    _cid, h = _headers()
    cust = _fresh_customer(h)
    inv = _seed_trip_invoice(h, cust, tons=20, rate=1500)  # ₹30,000
    _issue_note(h, "credit", inv, 1000.0)   # −1000
    _issue_note(h, "debit",  inv, 6000.0)   # +6000

    expected_effective = 30000.0 - 1000.0 + 6000.0  # 35,000
    ledger_closing = _ledger_closing(h, cust)
    assert ledger_closing == pytest.approx(expected_effective)

    text = _extract(_statement_pdf(h, cust))
    words_line = _amount_in_words_line(text)
    expected_words = _num_to_words_inr(abs(expected_effective))
    # Compare compact (strip whitespace/case) to tolerate soft-wrapping
    def _norm(s):
        return " ".join(s.split()).lower()
    assert _norm(expected_words) in _norm(words_line), (
        f"Amount-in-Words mismatch.\n"
        f"Expected (effective): {expected_words}\n"
        f"Actual line:          {words_line}"
    )
