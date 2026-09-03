"""Iter135A · Vendor / Mechanic Ledger — ERP presentation polish tests.

Guards:
  - PDF renders with the canonical company logo (base64 data URL)
  - PDF renders WITHOUT a logo (graceful text-only fallback)
  - PDF data still reconciles with the authoritative dataset
  - Vehicle chip in every ledger row is a link to the canonical
    /vehicles/{vehicle_id}/repair-history route (frontend source)
  - Unallocated payments are NOT linked and remain "— Unallocated"
  - Ledger service AND router never touch db.expenses (guards preserved)
  - Payment models have no vehicle_id / vehicle_number field (source-of-truth)
"""
from __future__ import annotations
import io, os, uuid, requests, pytest

BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
DEMO = os.environ["DEMO_TOKEN_VALUE"]
H = {"Authorization": f"Bearer {DEMO}", "Content-Type": "application/json"}


# ── helpers (mirror Iter135) ─────────────────────────────────────────

def _mk_vendor():
    r = requests.post(f"{API}/vendors", headers=H, json={
        "name": f"IT135A-V-{uuid.uuid4().hex[:6]}", "state": "Andhra Pradesh",
    }, timeout=10); r.raise_for_status(); return r.json()

def _mk_mechanic():
    r = requests.post(f"{API}/mechanics", headers=H, json={
        "name": f"IT135A-M-{uuid.uuid4().hex[:6]}", "state": "Andhra Pradesh",
    }, timeout=10); r.raise_for_status(); return r.json()

def _mk_vehicle(num: str):
    r = requests.post(f"{API}/vehicles", headers=H, json={
        "vehicle_number": num, "vehicle_type": "own",
    }, timeout=10); r.raise_for_status(); return r.json()

def _mk_bill(vid, veh_id, veh_num, date, amt, num):
    r = requests.post(f"{API}/vendor-bills", headers=H, json={
        "vendor_id": vid, "vehicle_id": veh_id, "vehicle_number": veh_num,
        "bill_number": num, "bill_date": date, "bill_amount": amt,
        "narration": "IT135A", }, timeout=10)
    r.raise_for_status(); return r.json()

def _mk_wo(mid, veh_id, veh_num, date, amt):
    r = requests.post(f"{API}/mechanic-work-orders", headers=H, json={
        "mechanic_id": mid, "vehicle_id": veh_id, "vehicle_number": veh_num,
        "work_date": date, "amount": amt, "narration": "IT135A"}, timeout=10)
    r.raise_for_status(); return r.json()

def _mk_vpay(vid, date, amt, bill_id="", against="bill"):
    r = requests.post(f"{API}/vendors/{vid}/payments", headers=H, json={
        "vendor_id": vid, "date": date, "amount": amt, "type": "payment_out",
        "mode": "Bank", "against": against, "vendor_bill_id": bill_id,
        "ref_no": f"IT135A-{uuid.uuid4().hex[:5]}"}, timeout=10)
    r.raise_for_status(); return r.json()

def _mk_mpay(mid, date, amt, wo_id="", against="work_order"):
    r = requests.post(f"{API}/mechanics/{mid}/payments", headers=H, json={
        "mechanic_id": mid, "date": date, "amount": amt, "type": "payment_out",
        "mode": "Bank", "against": against, "mechanic_work_order_id": wo_id,
        "ref_no": f"IT135A-{uuid.uuid4().hex[:5]}"}, timeout=10)
    r.raise_for_status(); return r.json()


# 1×1 red PNG (base64 data URL) — a tiny valid logo used by the test.
_TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4"
    "nGNgAAIAAAUAAeImBZsAAAAASUVORK5CYII="
)
_TINY_DATA_URL = f"data:image/png;base64,{_TINY_PNG_B64}"


def _set_company_logo(data_url: str):
    """Directly write the logo to the current company doc via the same
    field the /company/logo endpoint uses. Returns the previous value
    so tests can restore it."""
    from pymongo import MongoClient
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not (mongo_url and db_name):
        pytest.skip("MONGO_URL/DB_NAME missing")
    cli = MongoClient(mongo_url)
    db = cli[db_name]
    doc = db.companies.find_one({"user_id": "user_demo_men_2026"},
                                sort=[("_id", -1)])
    prev = (doc or {}).get("logo", "") if doc else ""
    if doc:
        db.companies.update_one({"_id": doc["_id"]}, {"$set": {"logo": data_url}})
    cli.close()
    return prev


# ── 1. PDF renders WITH a configured logo ────────────────────────────

def test_vendor_pdf_renders_with_logo():
    prev = _set_company_logo(_TINY_DATA_URL)
    try:
        v = _mk_vendor()
        veh = _mk_vehicle(f"AP31LG{uuid.uuid4().hex[:4].upper()}")
        b = _mk_bill(v["id"], veh["id"], veh["vehicle_number"],
                     "2026-01-10", 13080.0, f"L/{uuid.uuid4().hex[:5]}")
        _mk_vpay(v["id"], "2026-01-11", 10000.0, bill_id=b["id"])
        r = requests.get(f"{API}/vendors/{v['id']}/ledger.pdf", headers=H, timeout=15)
        assert r.status_code == 200
        assert r.content.startswith(b"%PDF")
        assert len(r.content) > 4000
    finally:
        _set_company_logo(prev)


def test_mechanic_pdf_renders_with_logo():
    prev = _set_company_logo(_TINY_DATA_URL)
    try:
        m = _mk_mechanic()
        veh = _mk_vehicle(f"AP31LM{uuid.uuid4().hex[:4].upper()}")
        wo = _mk_wo(m["id"], veh["id"], veh["vehicle_number"], "2026-01-12", 3500.0)
        _mk_mpay(m["id"], "2026-01-13", 3500.0, wo_id=wo["id"])
        r = requests.get(f"{API}/mechanics/{m['id']}/ledger.pdf", headers=H, timeout=15)
        assert r.status_code == 200
        assert r.content.startswith(b"%PDF")
    finally:
        _set_company_logo(prev)


# ── 2. Graceful fallback when logo is missing / invalid ──────────────

def test_pdf_renders_without_logo():
    prev = _set_company_logo("")
    try:
        v = _mk_vendor()
        veh = _mk_vehicle(f"AP31NL{uuid.uuid4().hex[:4].upper()}")
        _mk_bill(v["id"], veh["id"], veh["vehicle_number"],
                 "2026-01-10", 500.0, f"NL/{uuid.uuid4().hex[:5]}")
        r = requests.get(f"{API}/vendors/{v['id']}/ledger.pdf", headers=H, timeout=15)
        assert r.status_code == 200
        assert r.content.startswith(b"%PDF")
    finally:
        _set_company_logo(prev)


def test_pdf_renders_with_broken_logo_string():
    prev = _set_company_logo("data:image/png;base64,NOT_A_VALID_BASE64==")
    try:
        v = _mk_vendor()
        veh = _mk_vehicle(f"AP31BL{uuid.uuid4().hex[:4].upper()}")
        _mk_bill(v["id"], veh["id"], veh["vehicle_number"],
                 "2026-01-10", 500.0, f"BL/{uuid.uuid4().hex[:5]}")
        r = requests.get(f"{API}/vendors/{v['id']}/ledger.pdf", headers=H, timeout=15)
        assert r.status_code == 200, r.text
        assert r.content.startswith(b"%PDF")
    finally:
        _set_company_logo(prev)


# ── 3. PDF still reconciles with the authoritative dataset ───────────

def test_pdf_totals_reconcile_with_json_post_polish():
    v = _mk_vendor()
    veh = _mk_vehicle(f"AP31RC{uuid.uuid4().hex[:4].upper()}")
    b = _mk_bill(v["id"], veh["id"], veh["vehicle_number"],
                 "2026-01-10", 13080.0, f"RC/{uuid.uuid4().hex[:5]}")
    _mk_vpay(v["id"], "2026-01-11", 10000.0, bill_id=b["id"])
    j = requests.get(f"{API}/vendors/{v['id']}/ledger", headers=H, timeout=10).json()
    pdf = requests.get(f"{API}/vendors/{v['id']}/ledger.pdf", headers=H, timeout=15)
    assert pdf.status_code == 200
    try:
        import pdfplumber
    except Exception:
        pytest.skip("pdfplumber missing")
    with pdfplumber.open(io.BytesIO(pdf.content)) as pf:
        text = "\n".join(p.extract_text() or "" for p in pf.pages)
    assert f"{j['total_debit']:,.2f}" in text
    assert f"{j['total_credit']:,.2f}" in text
    assert f"{j['closing_balance']:,.2f}" in text
    assert veh["vehicle_number"] in text
    assert "VENDOR LEDGER" in text
    assert "CLOSING BALANCE" in text


# ── 4. Vehicle chip is a Link in the frontend PartyLedger source ─────

def test_frontend_vehicle_link_uses_canonical_route():
    with open("/app/frontend/src/pages/PartyLedger.jsx", "r", encoding="utf-8") as f:
        src = f.read()
    # Canonical route already used by RepairWorkspace + VehicleCostReport.
    assert "/vehicles/${e.vehicle_id}/repair-history" in src
    # data-testid for the link exists so screen tests can target it.
    assert 'data-testid={`vehicle-link-${e.vehicle_id}`}' in src
    # Unallocated payments render as plain text and are NOT linked.
    assert "— Unallocated" in src


# ── 5. Unallocated payments are not linked and remain unallocated ────

def test_unallocated_payment_stays_unallocated():
    v = _mk_vendor()
    _mk_vpay(v["id"], "2026-01-15", 5000.0, against="outstanding")
    d = requests.get(f"{API}/vendors/{v['id']}/ledger", headers=H, timeout=10).json()
    pay = next(e for e in d["entries"] if e["kind"] == "payment")
    assert pay["vehicle_id"] == ""
    assert pay["vehicle_number"] == ""


# ── 6. Source-of-truth guards (services + routers + models) ──────────

def test_ledger_service_never_reads_expenses():
    with open("/app/backend/services_party_ledger.py", "r", encoding="utf-8") as f:
        src = f.read()
    assert "db.expenses" not in src
    assert 'db["expenses"]' not in src


def test_ledger_routers_never_read_expenses():
    for p in ("/app/backend/routers/vendor_ledger.py",
              "/app/backend/routers/mechanic_ledger.py"):
        with open(p, "r", encoding="utf-8") as f:
            src = f.read()
        assert "db.expenses" not in src
        assert 'db["expenses"]' not in src


def test_payment_models_have_no_vehicle_id_field():
    """VendorPayment / MechanicPayment must NOT gain a vehicle_id field —
    payment vehicle context is derived through the linked bill / WO."""
    with open("/app/backend/models.py", "r", encoding="utf-8") as f:
        src = f.read()
    # Isolate VendorPayment block
    v_start = src.find("class VendorPayment(BaseModel):")
    v_end = src.find("\nclass ", v_start + 1)
    v_block = src[v_start:v_end]
    assert "vehicle_id" not in v_block, "VendorPayment must not carry vehicle_id"
    assert "vehicle_number" not in v_block, "VendorPayment must not carry vehicle_number"
    m_start = src.find("class MechanicPayment(BaseModel):")
    m_end = src.find("\nclass ", m_start + 1)
    m_block = src[m_start:m_end]
    assert "vehicle_id" not in m_block
    assert "vehicle_number" not in m_block


# ── 7. PDF renderer performs NO ledger math (static guard) ───────────

def test_pdf_renderer_has_no_ledger_math():
    with open("/app/backend/pdf/party_ledger.py", "r", encoding="utf-8") as f:
        src = f.read()
    # The renderer must not sum debits/credits or compute closing itself.
    forbidden = [
        "sum(e",
        "sum([e",
        "total_debit =",
        "total_credit =",
        "closing_balance =",
        "opening_balance =",
    ]
    for tok in forbidden:
        assert tok not in src, f"PDF renderer must not compute '{tok}'"


# ── 8. Canonical vehicle-repair-history route lives at /vehicles/{vid}/repair-history ──

def test_canonical_repair_history_route_exists():
    with open("/app/backend/routers/vehicle_reports.py", "r", encoding="utf-8") as f:
        assert '/vehicles/{vid}/repair-history' in f.read(), \
            "Canonical repair-history endpoint changed unexpectedly"
