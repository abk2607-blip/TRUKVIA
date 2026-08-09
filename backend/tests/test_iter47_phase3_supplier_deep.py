"""Iter47 Phase 3 tests — Deep Monthly Statement + Vehicle→Supplier strict enforcement.

Covers:
1. Supplier statement JSON returns `deep` block with opening/closing balance
2. Opening mode 'master' uses Supplier.opening_balance
3. Opening mode 'carry_forward' computes previous-period closing as opening
4. Trip create with vehicle_type='supplier' and NO supplier_id → 400
5. Trip create with vehicle_type='supplier' + supplier_id → OK
6. Trip create resolves supplier_id from supplier_name when only name provided
7. Supplier statement PDF text-extraction has OPENING BALANCE / CLOSING BALANCE labels
"""
import os
import io
import time
import uuid
import asyncio
import pytest
import httpx
import fitz  # PyMuPDF

BASE = os.environ.get("BACKEND_URL_INTERNAL", "http://localhost:8001")
TOKEN = os.environ.get("TEST_TOKEN", "test_session_bitumen_2026")
HDR = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture(scope="module")
def cid():
    r = httpx.get(f"{BASE}/api/companies", headers=HDR, timeout=15)
    r.raise_for_status()
    companies = r.json()
    assert companies, "No companies for demo user"
    return companies[0]["id"]


@pytest.fixture
def h(cid):
    return {**HDR, "X-Company-Id": cid}


def _mksup(h, name=None, opening=0.0, opening_type="payable"):
    n = name or f"IT47Sup-{uuid.uuid4().hex[:6]}"
    r = httpx.post(
        f"{BASE}/api/suppliers", headers=h,
        json={"name": n, "opening_balance": opening, "opening_balance_type": opening_type},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def _mkcust(h):
    r = httpx.post(f"{BASE}/api/customers", headers=h,
                   json={"name": f"IT47Cust-{uuid.uuid4().hex[:6]}", "state": "Telangana"},
                   timeout=15)
    r.raise_for_status()
    return r.json()


def _mktrip(h, cust_id, sup_id=None, sup_name=None, date="2026-02-15",
            freight=15000, adv=2000, vehicle_type="supplier"):
    payload = {
        "customer_id": cust_id, "date": date,
        "vehicle_number": f"AP99IT47{uuid.uuid4().hex[:2].upper()}",
        "vehicle_type": vehicle_type,
        "tons": 10, "rate_per_ton": 1500, "freight_mode": "per_ton",
        "supplier_freight_mode": "per_ton",
        "supplier_freight": freight, "supplier_advance": adv,
        "supplier_rate_per_ton": freight / 10,
    }
    if sup_id: payload["supplier_id"] = sup_id
    if sup_name: payload["supplier_name"] = sup_name
    return httpx.post(f"{BASE}/api/trips", headers=h, json=payload, timeout=15)


def test_supplier_trip_requires_supplier_id(h):
    cust = _mkcust(h)
    # No supplier_id and no supplier_name → 400
    r = _mktrip(h, cust["id"])
    assert r.status_code == 400, r.text
    assert "supplier" in r.json().get("detail", "").lower()


def test_supplier_trip_with_valid_supplier_id_ok(h):
    cust = _mkcust(h)
    sup = _mksup(h)
    r = _mktrip(h, cust["id"], sup_id=sup["id"])
    assert r.status_code == 200, r.text
    trip = r.json()
    assert trip["supplier_id"] == sup["id"]
    assert trip["supplier_name"] == sup["name"]


def test_supplier_trip_resolves_from_supplier_name(h):
    cust = _mkcust(h)
    sup = _mksup(h)
    # Provide only supplier_name — backend should resolve supplier_id
    r = _mktrip(h, cust["id"], sup_name=sup["name"])
    assert r.status_code == 200, r.text
    trip = r.json()
    assert trip["supplier_id"] == sup["id"], f"Expected auto-resolve; got {trip.get('supplier_id')!r}"


def test_deep_block_master_mode(h):
    cust = _mkcust(h)
    sup = _mksup(h, opening=5000, opening_type="payable")
    _mktrip(h, cust["id"], sup_id=sup["id"], date="2026-03-05", freight=20000, adv=3000)
    r = httpx.get(f"{BASE}/api/reports/supplier-statement",
                  headers=h,
                  params={"supplier_name": sup["name"], "start": "2026-03-01",
                          "end": "2026-03-31", "opening_mode": "master"},
                  timeout=15)
    r.raise_for_status()
    data = r.json()
    deep = data["deep"]
    assert deep["opening_balance"] == 5000.0
    assert deep["opening_source"] == "master"
    # 20000 freight - 3000 advance = 17000 net. Closing = 5000 opening + 17000 = 22000
    assert deep["movements_debit"] == 20000.0
    assert deep["movements_credit"] == 3000.0
    assert deep["closing_balance"] == 22000.0
    assert deep["closing_type"] == "payable"


def test_deep_block_carry_forward_mode(h):
    """Trip in Feb creates 12000 payable. March carry_forward opening should be 12000."""
    cust = _mkcust(h)
    sup = _mksup(h, opening=0)
    # Feb trip: 15000 freight - 3000 adv = 12000 net Dr
    _mktrip(h, cust["id"], sup_id=sup["id"], date="2026-02-10", freight=15000, adv=3000)
    r = httpx.get(f"{BASE}/api/reports/supplier-statement",
                  headers=h,
                  params={"supplier_name": sup["name"], "start": "2026-03-01",
                          "end": "2026-03-31", "opening_mode": "carry_forward"},
                  timeout=15)
    r.raise_for_status()
    deep = r.json()["deep"]
    assert deep["opening_source"] == "carry_forward"
    assert deep["opening_balance"] == 12000.0, f"Expected 12000 carry-forward, got {deep['opening_balance']}"


def test_pdf_has_deep_statement_labels(h):
    cust = _mkcust(h)
    sup = _mksup(h, opening=1000, opening_type="payable")
    _mktrip(h, cust["id"], sup_id=sup["id"], date="2026-04-05", freight=10000, adv=1500)
    r = httpx.get(f"{BASE}/api/reports/supplier-statement.pdf",
                  headers=h,
                  params={"supplier_name": sup["name"], "opening_mode": "master"},
                  timeout=30)
    assert r.status_code == 200, r.text
    pdf = fitz.open(stream=r.content, filetype="pdf")
    txt = "".join(p.get_text() for p in pdf)
    assert "OPENING BALANCE" in txt
    assert "CLOSING BALANCE" in txt
    assert "MOVEMENTS" in txt
    assert "Supplier master" in txt or "Supplier master opening" in txt.lower() or "master" in txt.lower()


def test_update_trip_preserves_supplier_link(h):
    cust = _mkcust(h)
    sup = _mksup(h)
    r = _mktrip(h, cust["id"], sup_id=sup["id"])
    trip = r.json()
    # Update tons
    trip["tons"] = 15
    upd = httpx.put(f"{BASE}/api/trips/{trip['id']}", headers=h, json=trip, timeout=15)
    assert upd.status_code == 200, upd.text
    assert upd.json()["supplier_id"] == sup["id"]


def test_update_supplier_trip_blocks_removing_supplier(h):
    cust = _mkcust(h)
    sup = _mksup(h)
    r = _mktrip(h, cust["id"], sup_id=sup["id"])
    trip = r.json()
    trip["supplier_id"] = ""
    trip["supplier_name"] = ""
    upd = httpx.put(f"{BASE}/api/trips/{trip['id']}", headers=h, json=trip, timeout=15)
    assert upd.status_code == 400, upd.text
