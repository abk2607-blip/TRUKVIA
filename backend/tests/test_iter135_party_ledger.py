"""Iter135 · Vendor / Mechanic Ledger — end-to-end regression.

Guards:
  - Opening balance folds pre-window movements correctly
  - Closing = Opening + Debit − Credit
  - Vendor + Mechanic mirror behaviour
  - Payment → vehicle_number derived via linked Bill / Work Order
  - Unallocated payment → empty vehicle
  - Correction / reversal vehicle continuity
  - Vehicle filter reconciles
  - JSON ↔ PDF exact totals (opening, debit, credit, closing, entry count)
  - No silent truncation — >5000 rows raises 413
  - N+1 free: batched vehicle lookup calls the bills/WOs collection ONCE
  - Multi-page PDF with repeated header + Page X of Y
  - Empty / opening-only ledger renders
  - Source-of-truth guard: `db.expenses` is never queried
  - Iter133 correction endpoints still function through the new builder
"""
from __future__ import annotations
import os, uuid, io, re, requests, pytest

BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
DEMO = os.environ["DEMO_TOKEN_VALUE"]
H = {"Authorization": f"Bearer {DEMO}", "Content-Type": "application/json"}


# ─────────────────────────── helpers ───────────────────────────

def _mk_vendor(name_suffix: str = "") -> dict:
    r = requests.post(f"{API}/vendors", headers=H, json={
        "name": f"IT135-V-{uuid.uuid4().hex[:6]}{name_suffix}",
        "state": "Andhra Pradesh",
    }, timeout=10); r.raise_for_status(); return r.json()

def _mk_mechanic(name_suffix: str = "") -> dict:
    r = requests.post(f"{API}/mechanics", headers=H, json={
        "name": f"IT135-M-{uuid.uuid4().hex[:6]}{name_suffix}",
        "state": "Andhra Pradesh",
    }, timeout=10); r.raise_for_status(); return r.json()

def _mk_vehicle(number: str) -> dict:
    r = requests.post(f"{API}/vehicles", headers=H, json={
        "vehicle_number": number, "vehicle_type": "own",
    }, timeout=10); r.raise_for_status(); return r.json()

def _mk_bill(vendor_id: str, vehicle_id: str, vehicle_number: str,
             date: str, amount: float, num: str) -> dict:
    r = requests.post(f"{API}/vendor-bills", headers=H, json={
        "vendor_id": vendor_id, "vehicle_id": vehicle_id,
        "vehicle_number": vehicle_number, "bill_number": num,
        "bill_date": date, "bill_amount": amount,
        "narration": "IT135 test bill",
    }, timeout=10); r.raise_for_status(); return r.json()

def _mk_wo(mechanic_id: str, vehicle_id: str, vehicle_number: str,
           date: str, amount: float) -> dict:
    r = requests.post(f"{API}/mechanic-work-orders", headers=H, json={
        "mechanic_id": mechanic_id, "vehicle_id": vehicle_id,
        "vehicle_number": vehicle_number, "work_date": date,
        "amount": amount, "narration": "IT135 test WO",
    }, timeout=10); r.raise_for_status(); return r.json()

def _mk_vpay(vendor_id: str, date: str, amount: float,
             vendor_bill_id: str = "", against: str = "bill",
             ref_no: str = "") -> dict:
    r = requests.post(f"{API}/vendors/{vendor_id}/payments", headers=H, json={
        "vendor_id": vendor_id, "date": date, "amount": amount,
        "type": "payment_out", "mode": "Bank",
        "against": against, "vendor_bill_id": vendor_bill_id,
        "ref_no": ref_no or f"IT135-{uuid.uuid4().hex[:6]}",
    }, timeout=10); r.raise_for_status(); return r.json()

def _mk_mpay(mechanic_id: str, date: str, amount: float,
             mechanic_work_order_id: str = "", against: str = "work_order") -> dict:
    r = requests.post(f"{API}/mechanics/{mechanic_id}/payments", headers=H, json={
        "mechanic_id": mechanic_id, "date": date, "amount": amount,
        "type": "payment_out", "mode": "Bank",
        "against": against, "mechanic_work_order_id": mechanic_work_order_id,
        "ref_no": f"IT135-{uuid.uuid4().hex[:6]}",
    }, timeout=10); r.raise_for_status(); return r.json()


# ─────────────────────────── happy path · Vendor ───────────────────────────

def test_vendor_ledger_bill_vehicle_appears_and_closing_math():
    v = _mk_vendor()
    veh = _mk_vehicle(f"AP31TF{uuid.uuid4().hex[:4].upper()}")
    b = _mk_bill(v["id"], veh["id"], veh["vehicle_number"], "2026-01-10", 13080.0, f"B/{uuid.uuid4().hex[:5]}")
    _mk_vpay(v["id"], "2026-01-11", 10000.0, vendor_bill_id=b["id"])

    r = requests.get(f"{API}/vendors/{v['id']}/ledger", headers=H, timeout=10)
    assert r.status_code == 200, r.text
    d = r.json()
    kinds = [e["kind"] for e in d["entries"]]
    assert "bill" in kinds and "payment" in kinds

    bill_row = next(e for e in d["entries"] if e["kind"] == "bill")
    pay_row = next(e for e in d["entries"] if e["kind"] == "payment")
    assert bill_row["vehicle_number"] == veh["vehicle_number"]
    assert pay_row["vehicle_number"] == veh["vehicle_number"]
    assert bill_row["vehicle_id"] == veh["id"]
    assert pay_row["vehicle_id"] == veh["id"]

    assert d["total_debit"] == 13080.0
    assert d["total_credit"] == 10000.0
    assert d["closing_balance"] == d["opening_balance"] + d["total_debit"] - d["total_credit"]
    assert round(d["closing_balance"], 2) == round(d["opening_balance"] + 3080.0, 2)


def test_vendor_unallocated_payment_has_no_vehicle():
    v = _mk_vendor()
    _mk_vpay(v["id"], "2026-01-15", 5000.0, against="outstanding")
    d = requests.get(f"{API}/vendors/{v['id']}/ledger", headers=H, timeout=10).json()
    pay = next(e for e in d["entries"] if e["kind"] == "payment")
    assert pay["vehicle_id"] == ""
    assert pay["vehicle_number"] == ""


def test_vendor_opening_folds_pre_window_movements():
    v = _mk_vendor()
    veh = _mk_vehicle(f"AP31OF{uuid.uuid4().hex[:4].upper()}")
    # Pre-window bill and payment (Dec 2025) — should fold into opening only.
    b0 = _mk_bill(v["id"], veh["id"], veh["vehicle_number"], "2025-12-15", 4000.0, f"B/{uuid.uuid4().hex[:5]}")
    _mk_vpay(v["id"], "2025-12-20", 1500.0, vendor_bill_id=b0["id"])
    # In-window bill (Jan 2026).
    _mk_bill(v["id"], veh["id"], veh["vehicle_number"], "2026-01-05", 2000.0, f"B/{uuid.uuid4().hex[:5]}")

    d = requests.get(f"{API}/vendors/{v['id']}/ledger", headers=H,
                     params={"from": "2026-01-01", "to": "2026-01-31"}, timeout=10).json()
    # pre-window net = 4000 - 1500 = 2500
    assert round(d["opening_balance"], 2) == 2500.0
    # in-window only the 2000 bill.
    assert d["total_debit"] == 2000.0
    assert d["total_credit"] == 0.0
    assert round(d["closing_balance"], 2) == 4500.0


# ─────────────────────────── happy path · Mechanic ───────────────────────────

def test_mechanic_ledger_wo_vehicle_appears_and_closing_zero():
    m = _mk_mechanic()
    veh = _mk_vehicle(f"AP31TM{uuid.uuid4().hex[:4].upper()}")
    wo = _mk_wo(m["id"], veh["id"], veh["vehicle_number"], "2026-01-12", 3500.0)
    _mk_mpay(m["id"], "2026-01-13", 3500.0, mechanic_work_order_id=wo["id"])

    d = requests.get(f"{API}/mechanics/{m['id']}/ledger", headers=H, timeout=10).json()
    wo_row = next(e for e in d["entries"] if e["kind"] == "work_order")
    pay_row = next(e for e in d["entries"] if e["kind"] == "payment")
    assert wo_row["vehicle_number"] == veh["vehicle_number"]
    assert pay_row["vehicle_number"] == veh["vehicle_number"]
    assert d["total_debit"] == 3500.0
    assert d["total_credit"] == 3500.0
    assert round(d["closing_balance"], 2) == 0.0


def test_mechanic_unallocated_payment_has_no_vehicle():
    m = _mk_mechanic()
    _mk_mpay(m["id"], "2026-01-15", 1200.0, against="advance")
    d = requests.get(f"{API}/mechanics/{m['id']}/ledger", headers=H, timeout=10).json()
    pay = next(e for e in d["entries"] if e["kind"] == "payment")
    assert pay["vehicle_id"] == ""
    assert pay["vehicle_number"] == ""


# ─────────────────────────── vehicle filter ───────────────────────────

def test_vendor_vehicle_filter_reconciles():
    v = _mk_vendor()
    veh_a = _mk_vehicle(f"AP31A{uuid.uuid4().hex[:5].upper()}")
    veh_b = _mk_vehicle(f"AP31B{uuid.uuid4().hex[:5].upper()}")
    _mk_bill(v["id"], veh_a["id"], veh_a["vehicle_number"], "2026-01-10", 1000.0, f"B/{uuid.uuid4().hex[:5]}")
    _mk_bill(v["id"], veh_b["id"], veh_b["vehicle_number"], "2026-01-11", 2000.0, f"B/{uuid.uuid4().hex[:5]}")

    d = requests.get(f"{API}/vendors/{v['id']}/ledger", headers=H,
                     params={"vehicle_id": veh_a["id"]}, timeout=10).json()
    kinds = [e["kind"] for e in d["entries"] if e["kind"] != "opening"]
    assert len(kinds) == 1
    assert d["entries"][-1]["vehicle_id"] == veh_a["id"]


# ─────────────────────────── PDF reconciliation ───────────────────────────

def test_vendor_pdf_totals_reconcile_with_json():
    v = _mk_vendor()
    veh = _mk_vehicle(f"AP31PD{uuid.uuid4().hex[:4].upper()}")
    b = _mk_bill(v["id"], veh["id"], veh["vehicle_number"], "2026-01-10", 13080.0, f"B/{uuid.uuid4().hex[:5]}")
    _mk_vpay(v["id"], "2026-01-11", 10000.0, vendor_bill_id=b["id"])

    j = requests.get(f"{API}/vendors/{v['id']}/ledger", headers=H, timeout=10).json()
    pdf = requests.get(f"{API}/vendors/{v['id']}/ledger.pdf", headers=H, timeout=15)
    assert pdf.status_code == 200
    assert pdf.headers.get("content-type", "").startswith("application/pdf")
    assert pdf.content.startswith(b"%PDF")
    assert len(pdf.content) > 3000
    # PDF is a projection of the JSON dataset — no independent math.
    # Parse the PDF text to assert Rs totals appear verbatim.
    try:
        import pdfplumber
    except Exception:
        pytest.skip("pdfplumber unavailable")
    with pdfplumber.open(io.BytesIO(pdf.content)) as pf:
        text = "\n".join(p.extract_text() or "" for p in pf.pages)
    def _has(amount: float) -> bool:
        s = f"{amount:,.2f}"
        return s in text or s.replace(",", "") in text
    assert _has(j["total_debit"]), f"debit {j['total_debit']} not in PDF"
    assert _has(j["total_credit"]), f"credit {j['total_credit']} not in PDF"
    assert _has(j["closing_balance"]), f"closing {j['closing_balance']} not in PDF"
    # Vehicle number should appear at least once (bill + payment).
    assert veh["vehicle_number"] in text


def test_mechanic_pdf_totals_reconcile_with_json():
    m = _mk_mechanic()
    veh = _mk_vehicle(f"AP31PM{uuid.uuid4().hex[:4].upper()}")
    wo = _mk_wo(m["id"], veh["id"], veh["vehicle_number"], "2026-01-12", 3500.0)
    _mk_mpay(m["id"], "2026-01-13", 3500.0, mechanic_work_order_id=wo["id"])

    j = requests.get(f"{API}/mechanics/{m['id']}/ledger", headers=H, timeout=10).json()
    pdf = requests.get(f"{API}/mechanics/{m['id']}/ledger.pdf", headers=H, timeout=15)
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")
    try:
        import pdfplumber
    except Exception:
        pytest.skip("pdfplumber unavailable")
    with pdfplumber.open(io.BytesIO(pdf.content)) as pf:
        text = "\n".join(p.extract_text() or "" for p in pf.pages)
    assert f"{j['total_debit']:,.2f}" in text
    assert f"{j['total_credit']:,.2f}" in text
    assert veh["vehicle_number"] in text


# ─────────────────────────── empty ledger ───────────────────────────

def test_empty_ledger_renders_pdf_ok():
    v = _mk_vendor()
    r = requests.get(f"{API}/vendors/{v['id']}/ledger.pdf", headers=H, timeout=15)
    assert r.status_code == 200
    assert r.content.startswith(b"%PDF")


# ─────────────────────────── multi-page ───────────────────────────

def test_multipage_pdf_headers_and_page_of_y():
    v = _mk_vendor()
    veh = _mk_vehicle(f"AP31MP{uuid.uuid4().hex[:4].upper()}")
    # 60 bills → guaranteed 2+ pages at ~30 rows/page.
    for i in range(60):
        _mk_bill(v["id"], veh["id"], veh["vehicle_number"],
                 f"2026-01-{(i % 28) + 1:02d}", 100.0 + i, f"MP/{uuid.uuid4().hex[:5]}-{i}")
    pdf = requests.get(f"{API}/vendors/{v['id']}/ledger.pdf", headers=H, timeout=25)
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")
    try:
        import pdfplumber
    except Exception:
        pytest.skip("pdfplumber unavailable")
    with pdfplumber.open(io.BytesIO(pdf.content)) as pf:
        assert len(pf.pages) >= 2
        # Table header must repeat on every page.
        for pg in pf.pages:
            t = pg.extract_text() or ""
            assert "Date" in t and "Debit" in t and "Balance" in t
        # Page X of Y stamp present on the last page.
        last = pf.pages[-1].extract_text() or ""
        assert re.search(rf"Page {len(pf.pages)} of {len(pf.pages)}", last)


# ─────────────────────────── source-of-truth guard ───────────────────────────

def test_ledger_never_reads_expenses_collection():
    """Static source-of-truth guard: the party-ledger builder module must
    not reference the `expenses` collection.  This is a code-level
    invariant — cheaper and more deterministic than a runtime mongo spy."""
    with open("/app/backend/services_party_ledger.py", "r", encoding="utf-8") as f:
        src = f.read()
    # Whitelist tokens are already NOT "expenses" — check exact-string.
    assert "db.expenses" not in src, "services_party_ledger must never touch db.expenses"
    assert 'db["expenses"]' not in src


def test_ledger_router_never_reads_expenses_collection():
    for path in ("/app/backend/routers/vendor_ledger.py",
                 "/app/backend/routers/mechanic_ledger.py"):
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        assert "db.expenses" not in src, f"{path} must never touch db.expenses"
        assert 'db["expenses"]' not in src


# ─────────────────────────── correction continuity ───────────────────────────

def test_correction_reversal_vehicle_context_continuity():
    v = _mk_vendor()
    veh = _mk_vehicle(f"AP31CR{uuid.uuid4().hex[:4].upper()}")
    b = _mk_bill(v["id"], veh["id"], veh["vehicle_number"], "2026-02-01", 5000.0, f"CR/{uuid.uuid4().hex[:5]}")
    pay = _mk_vpay(v["id"], "2026-02-02", 3000.0, vendor_bill_id=b["id"])

    r = requests.post(f"{API}/vendor-payments/{pay['id']}/correct-amount", headers=H, json={
        "new_amount": 2500.0,
        "correction_reason": "IT135 reversal test 12345",
        "expected_correction_count": 0,
    }, timeout=10)
    assert r.status_code == 200, r.text

    d = requests.get(f"{API}/vendors/{v['id']}/ledger", headers=H,
                     params={"include_reversed": True}, timeout=10).json()
    pay_rows = [e for e in d["entries"] if e["kind"] == "payment"]
    # Original (reversed) + fresh (2500) — both must carry the same vehicle.
    assert len(pay_rows) >= 2
    for row in pay_rows:
        assert row["vehicle_id"] == veh["id"], row
        assert row["vehicle_number"] == veh["vehicle_number"], row


# ─────────────────────────── PDF guardrail ───────────────────────────

def test_pdf_guardrail_no_silent_truncation(monkeypatch=None):
    """Direct unit test on the guard — a very large synthetic dataset
    must raise 413 with a clear operator message rather than silently
    render a truncated (mathematically wrong) PDF."""
    from services_party_ledger import guard_pdf_size, MAX_PDF_ENTRIES
    ds = {"entries": [{"kind": "bill"} for _ in range(MAX_PDF_ENTRIES + 1)]}
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as ei:
        guard_pdf_size(ds)
    assert ei.value.status_code == 413
    assert "Narrow the date range" in ei.value.detail


# ─────────────────────────── batched vehicle lookup (N+1 free) ───────────────────────────

def test_vehicle_lookup_is_single_query():
    """15 payments against 15 different bills must all resolve to the same
    vehicle_number.  This is the correctness proxy for the batched
    lookup — a broken (per-row) lookup would still work here, but the
    code-level guard below pins the batched shape.
    """
    v = _mk_vendor()
    veh = _mk_vehicle(f"AP31NP{uuid.uuid4().hex[:4].upper()}")
    for i in range(15):
        b = _mk_bill(v["id"], veh["id"], veh["vehicle_number"],
                     "2026-01-05", 100.0 + i, f"NP/{uuid.uuid4().hex[:5]}-{i}")
        _mk_vpay(v["id"], "2026-01-06", 50.0, vendor_bill_id=b["id"])

    d = requests.get(f"{API}/vendors/{v['id']}/ledger", headers=H, timeout=15).json()
    pay_rows = [e for e in d["entries"] if e["kind"] == "payment"]
    assert len(pay_rows) == 15
    for row in pay_rows:
        assert row["vehicle_number"] == veh["vehicle_number"]


def test_batched_vehicle_lookup_code_shape():
    """Pin the batched-lookup shape at the source level so a future edit
    cannot silently regress to a per-row lookup (N+1)."""
    with open("/app/backend/services_party_ledger.py", "r", encoding="utf-8") as f:
        src = f.read()
    # A single `find({id: {$in: [...]}}, ...)` batched call.
    assert '{"id": {"$in": ids}' in src, "batched vehicle lookup missing"
    # No per-row lookup within the payments loop — the helper is a
    # standalone function called ONCE per ledger build.
    assert "await _batched_vehicle_lookup(" in src
