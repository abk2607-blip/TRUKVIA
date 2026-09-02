"""Iter133 · Turn 2C · Vendor Ledger + Mechanic Ledger + Payment Correction tests."""
from __future__ import annotations

import os
import uuid

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"
DEMO_TOKEN = os.environ["DEMO_TOKEN_VALUE"]

TAG = f"IT133T2C-{uuid.uuid4().hex[:6].upper()}"


def _hdr(key=None, company_id=None, token=None):
    h = {"Authorization": f"Bearer {token or DEMO_TOKEN}",
         "Content-Type": "application/json"}
    if key: h["Idempotency-Key"] = key
    if company_id: h["X-Company-Id"] = company_id
    return h


def _idem():
    return f"iter133t2c-{uuid.uuid4().hex[:24]}"


# ---------------------- fixtures ----------------------

@pytest.fixture(scope="module")
def party():
    v = requests.post(f"{API}/vendors", headers=_hdr(_idem()),
                      json={"name": f"{TAG} V-Main"}, timeout=15).json()
    m = requests.post(f"{API}/mechanics", headers=_hdr(_idem()),
                      json={"name": f"{TAG} M-Main"}, timeout=15).json()
    v2 = requests.post(f"{API}/vendors", headers=_hdr(_idem()),
                       json={"name": f"{TAG} V-Alt"}, timeout=15).json()
    m2 = requests.post(f"{API}/mechanics", headers=_hdr(_idem()),
                       json={"name": f"{TAG} M-Alt"}, timeout=15).json()
    b = requests.post(f"{API}/vendor-bills", headers=_hdr(_idem()), json={
        "vendor_id": v["id"], "bill_number": f"{TAG}-B",
        "bill_date": "2029-08-31", "bill_amount": 5000}, timeout=15).json()
    w = requests.post(f"{API}/mechanic-work-orders", headers=_hdr(_idem()), json={
        "mechanic_id": m["id"], "work_date": "2029-08-31",
        "amount": 3000}, timeout=15).json()
    return {"v": v, "v2": v2, "m": m, "m2": m2, "b": b, "w": w}


def _post_vp(payload):
    return requests.post(f"{API}/vendors/{payload['vendor_id']}/payments",
                         headers=_hdr(_idem()), json=payload, timeout=15).json()


def _post_mp(payload):
    return requests.post(f"{API}/mechanics/{payload['mechanic_id']}/payments",
                         headers=_hdr(_idem()), json=payload, timeout=15).json()


# ---------------------- ledger derivation ----------------------

def test_vendor_ledger_reads_bills_and_payments_only(party):
    v = party["v"]; b = party["b"]
    _post_vp({"vendor_id": v["id"], "date": "2029-09-05", "amount": 2000,
              "against": "bill", "vendor_bill_id": b["id"]})
    r = requests.get(f"{API}/vendors/{v['id']}/ledger", headers=_hdr(), timeout=15)
    assert r.status_code == 200, r.text
    L = r.json()
    assert L["total_debit"] == 5000
    assert L["total_credit"] == 2000
    assert L["outstanding"] == 3000
    kinds = [e["kind"] for e in L["entries"]]
    assert "bill" in kinds and "payment" in kinds
    # No expense/other kinds leak in
    assert not any(k in {"expense", "repair"} for k in kinds)


def test_mechanic_ledger_reads_wo_and_payments_only(party):
    m = party["m"]; w = party["w"]
    _post_mp({"mechanic_id": m["id"], "date": "2029-09-05", "amount": 1000,
              "against": "work_order", "mechanic_work_order_id": w["id"]})
    L = requests.get(f"{API}/mechanics/{m['id']}/ledger", headers=_hdr(), timeout=15).json()
    assert L["total_debit"] == 3000
    assert L["total_credit"] == 1000
    assert L["outstanding"] == 2000


# ---------------------- PC-2 mandatory reason ----------------------

def test_pc2_correction_reason_min_length(party):
    v = party["v"]; b = party["b"]
    p = _post_vp({"vendor_id": v["id"], "date": "2029-09-06", "amount": 100,
                  "against": "bill", "vendor_bill_id": b["id"]})
    r = requests.post(f"{API}/vendor-payments/{p['id']}/correct", headers=_hdr(_idem()),
                      json={"changes": {"remarks": "x"}, "correction_reason": "short"}, timeout=15)
    assert r.status_code == 400


# ---------------------- PC-3 attribute reassignment ----------------------

def test_pc3_attribute_reassignment_reflects_in_both_ledgers(party):
    v = party["v"]; v2 = party["v2"]; b = party["b"]
    p = _post_vp({"vendor_id": v["id"], "date": "2029-09-07", "amount": 500,
                  "against": "bill", "vendor_bill_id": b["id"]})
    # Bill on v2 to move to
    b2 = requests.post(f"{API}/vendor-bills", headers=_hdr(_idem()), json={
        "vendor_id": v2["id"], "bill_number": f"{TAG}-B2",
        "bill_date": "2029-08-31", "bill_amount": 500}, timeout=15).json()
    r = requests.post(f"{API}/vendor-payments/{p['id']}/correct", headers=_hdr(_idem()),
                      json={"changes": {"vendor_id": v2["id"], "vendor_bill_id": b2["id"]},
                            "correction_reason": "typed wrong vendor by mistake"}, timeout=15)
    assert r.status_code == 200, r.text
    updated = r.json()["payment"]
    assert updated["vendor_id"] == v2["id"]
    assert updated["correction_count"] == 1
    # Ledgers reflect
    ledger_v = requests.get(f"{API}/vendors/{v['id']}/ledger", headers=_hdr(), timeout=15).json()
    ledger_v2 = requests.get(f"{API}/vendors/{v2['id']}/ledger", headers=_hdr(), timeout=15).json()
    v_payment_refs = [e for e in ledger_v["entries"] if e.get("id") == p["id"]]
    v2_payment_refs = [e for e in ledger_v2["entries"] if e.get("id") == p["id"]]
    assert v_payment_refs == [], "payment should have moved off old vendor"
    assert len(v2_payment_refs) == 1, "payment should appear on new vendor"


# ---------------------- PC-4 amount via /correct rejected ----------------------

def test_pc4_amount_change_via_attribute_endpoint_rejected(party):
    v = party["v"]; b = party["b"]
    p = _post_vp({"vendor_id": v["id"], "date": "2029-09-08", "amount": 100,
                  "against": "bill", "vendor_bill_id": b["id"]})
    r = requests.post(f"{API}/vendor-payments/{p['id']}/correct", headers=_hdr(_idem()),
                      json={"changes": {"amount": 200},
                            "correction_reason": "amount was wrong at typing time"}, timeout=15)
    assert r.status_code == 400
    assert "/correct-amount" in r.text


# ---------------------- PC-5 amount reversal + new ----------------------

def test_pc5_amount_reversal_creates_two_visible_rows(party):
    v = party["v"]; b = party["b"]
    p = _post_vp({"vendor_id": v["id"], "date": "2029-09-09", "amount": 800,
                  "against": "bill", "vendor_bill_id": b["id"]})
    r = requests.post(f"{API}/vendor-payments/{p['id']}/correct-amount",
                      headers=_hdr(_idem()),
                      json={"new_amount": 1200,
                            "correction_reason": "amount typed 800 instead of 1200"}, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["original"]["is_reversed"] is True
    assert body["fresh"]["amount"] == 1200
    assert body["fresh"]["reversal_of"] == p["id"]
    assert body["correction"]["kind"] == "amount_reversal_new"
    # Ledger with include_reversed=true shows BOTH
    L = requests.get(f"{API}/vendors/{v['id']}/ledger",
                     headers=_hdr(), params={"include_reversed": True}, timeout=15).json()
    pay_entries = [e for e in L["entries"] if e["kind"] == "payment" and
                   e["id"] in (p["id"], body["fresh"]["id"])]
    assert len(pay_entries) == 2
    # Default (exclude reversed) shows only the fresh one
    L2 = requests.get(f"{API}/vendors/{v['id']}/ledger", headers=_hdr(), timeout=15).json()
    active = [e for e in L2["entries"] if e["kind"] == "payment" and e["id"] == body["fresh"]["id"]]
    assert len(active) == 1
    reversed_visible = [e for e in L2["entries"] if e["kind"] == "payment" and e["id"] == p["id"]]
    assert reversed_visible == []


# ---------------------- PC-6 reconciled guard ----------------------

def test_pc6_reconciled_requires_override(party):
    v = party["v"]; b = party["b"]
    p = _post_vp({"vendor_id": v["id"], "date": "2029-09-10", "amount": 300,
                  "against": "bill", "vendor_bill_id": b["id"]})
    # Simulate reconciliation by directly writing (no reconciliation endpoint yet)
    import pymongo
    dbm = pymongo.MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    dbm.vendor_payments.update_one({"id": p["id"]},
                                   {"$set": {"reconciled_at": "2029-09-11",
                                             "reconciled_ref": "BANK-STMT-123"}})
    r = requests.post(f"{API}/vendor-payments/{p['id']}/correct", headers=_hdr(_idem()),
                      json={"changes": {"ref_no": "UTR-CORRECTED-001"},
                            "correction_reason": "UTR was captured wrong at posting"}, timeout=15)
    assert r.status_code == 409, r.text
    # With override → ok
    r = requests.post(f"{API}/vendor-payments/{p['id']}/correct", headers=_hdr(_idem()),
                      json={"changes": {"ref_no": "UTR-CORRECTED-001"},
                            "correction_reason": "UTR was captured wrong at posting",
                            "force_reconciled_override": True}, timeout=15)
    assert r.status_code == 200


# ---------------------- PC-7 idempotency ----------------------

def test_pc7_idempotency_no_duplicate_correction(party):
    v = party["v"]; b = party["b"]
    p = _post_vp({"vendor_id": v["id"], "date": "2029-09-11", "amount": 400,
                  "against": "bill", "vendor_bill_id": b["id"]})
    key = _idem()
    r1 = requests.post(f"{API}/vendor-payments/{p['id']}/correct", headers=_hdr(key),
                       json={"changes": {"remarks": "typed as remark now"},
                             "correction_reason": "correcting the remark line"}, timeout=15)
    assert r1.status_code == 200
    r2 = requests.post(f"{API}/vendor-payments/{p['id']}/correct", headers=_hdr(key),
                       json={"changes": {"remarks": "typed as remark now"},
                             "correction_reason": "correcting the remark line"}, timeout=15)
    assert r2.status_code == 200
    assert r2.headers.get("x-idempotent-replay") == "1"
    corrections = requests.get(f"{API}/vendor-payments/{p['id']}/corrections",
                               headers=_hdr(), timeout=15).json()
    assert len(corrections) == 1


# ---------------------- PC-8 cross-tenant ----------------------

def test_pc8_cross_tenant_correction_blocked(party):
    companies = requests.get(f"{API}/companies", headers=_hdr(), timeout=15).json()
    if len(companies) < 2:
        pytest.skip("need ≥2 companies")
    a, b = companies[0]["id"], companies[1]["id"]
    v = requests.post(f"{API}/vendors", headers=_hdr(_idem(), company_id=a),
                      json={"name": f"{TAG} PC8 V"}, timeout=15).json()
    p = requests.post(f"{API}/vendors/{v['id']}/payments",
                      headers=_hdr(_idem(), company_id=a),
                      json={"vendor_id": v["id"], "date": "2029-09-12",
                            "amount": 100}, timeout=15).json()
    r = requests.post(f"{API}/vendor-payments/{p['id']}/correct",
                      headers=_hdr(_idem(), company_id=b),
                      json={"changes": {"remarks": "x"},
                            "correction_reason": "cross tenant attempt"}, timeout=15)
    assert r.status_code == 404


# ---------------------- PC-9 concurrency guard ----------------------

def test_pc9_correction_count_race_guard(party):
    v = party["v"]; b = party["b"]
    p = _post_vp({"vendor_id": v["id"], "date": "2029-09-13", "amount": 100,
                  "against": "bill", "vendor_bill_id": b["id"]})
    r1 = requests.post(f"{API}/vendor-payments/{p['id']}/correct", headers=_hdr(_idem()),
                       json={"changes": {"remarks": "first correction"},
                             "correction_reason": "expected count 0",
                             "expected_correction_count": 0}, timeout=15)
    assert r1.status_code == 200
    # Same expected count now stale → 409
    r2 = requests.post(f"{API}/vendor-payments/{p['id']}/correct", headers=_hdr(_idem()),
                       json={"changes": {"remarks": "second correction"},
                             "correction_reason": "stale expected count",
                             "expected_correction_count": 0}, timeout=15)
    assert r2.status_code == 409


# ---------------------- PC-10 history endpoint ----------------------

def test_pc10_correction_history_endpoint(party):
    v = party["v"]; b = party["b"]
    p = _post_vp({"vendor_id": v["id"], "date": "2029-09-14", "amount": 100,
                  "against": "bill", "vendor_bill_id": b["id"]})
    for i in range(3):
        r = requests.post(f"{API}/vendor-payments/{p['id']}/correct", headers=_hdr(_idem()),
                          json={"changes": {"remarks": f"note {i}"},
                                "correction_reason": f"correction number {i}"}, timeout=15)
        assert r.status_code == 200
    hist = requests.get(f"{API}/vendor-payments/{p['id']}/corrections",
                        headers=_hdr(), timeout=15).json()
    assert len(hist) == 3
    assert [h["correction_index"] for h in hist] == [1, 2, 3]


# ---------------------- PC-11 no double payment for attribute ----------------------

def test_pc11_attribute_corrections_do_not_create_new_payment(party):
    v = party["v"]; b = party["b"]
    p = _post_vp({"vendor_id": v["id"], "date": "2029-09-15", "amount": 100,
                  "against": "bill", "vendor_bill_id": b["id"]})
    for i in range(2):
        requests.post(f"{API}/vendor-payments/{p['id']}/correct", headers=_hdr(_idem()),
                      json={"changes": {"remarks": f"iter {i}"},
                            "correction_reason": f"correcting iter {i} note"}, timeout=15)
    pays = requests.get(f"{API}/vendors/{v['id']}/payments", headers=_hdr(), timeout=15).json()
    matching = [x for x in pays if x["id"] == p["id"]]
    assert len(matching) == 1


# ---------------------- PC-12 ledger auto-reflects (attribute) ----------------------

def test_pc12_ledger_reflects_corrected_linkage(party):
    v = party["v"]; v2 = party["v2"]
    b_v = requests.post(f"{API}/vendor-bills", headers=_hdr(_idem()), json={
        "vendor_id": v["id"], "bill_number": f"{TAG}-PC12",
        "bill_date": "2029-08-31", "bill_amount": 900}, timeout=15).json()
    p = _post_vp({"vendor_id": v["id"], "date": "2029-09-16", "amount": 900,
                  "against": "bill", "vendor_bill_id": b_v["id"]})
    before_v = requests.get(f"{API}/vendors/{v['id']}/ledger", headers=_hdr(), timeout=15).json()
    before_v_credit = before_v["total_credit"]
    # Correct: move payment to v2 + create a v2 bill target
    b_v2 = requests.post(f"{API}/vendor-bills", headers=_hdr(_idem()), json={
        "vendor_id": v2["id"], "bill_number": f"{TAG}-PC12-v2",
        "bill_date": "2029-08-31", "bill_amount": 900}, timeout=15).json()
    requests.post(f"{API}/vendor-payments/{p['id']}/correct", headers=_hdr(_idem()),
                  json={"changes": {"vendor_id": v2["id"], "vendor_bill_id": b_v2["id"]},
                        "correction_reason": "moved to correct vendor payment"}, timeout=15)
    after_v = requests.get(f"{API}/vendors/{v['id']}/ledger", headers=_hdr(), timeout=15).json()
    after_v2 = requests.get(f"{API}/vendors/{v2['id']}/ledger", headers=_hdr(), timeout=15).json()
    assert after_v["total_credit"] == before_v_credit - 900
    assert any(e.get("id") == p["id"] for e in after_v2["entries"])


# ---------------------- PC-13 mechanic mirror ----------------------

def test_pc13_mechanic_correction_mirror(party):
    m = party["m"]; m2 = party["m2"]; w = party["w"]
    p = _post_mp({"mechanic_id": m["id"], "date": "2029-09-17", "amount": 200,
                  "against": "work_order", "mechanic_work_order_id": w["id"]})
    # attribute correct: move to m2 (and clear the WO to avoid cross-mismatch)
    r = requests.post(f"{API}/mechanic-payments/{p['id']}/correct", headers=_hdr(_idem()),
                      json={"changes": {"mechanic_id": m2["id"],
                                        "mechanic_work_order_id": ""},
                            "correction_reason": "moved to correct mechanic ledger"}, timeout=15)
    assert r.status_code == 200
    hist = requests.get(f"{API}/mechanic-payments/{p['id']}/corrections",
                        headers=_hdr(), timeout=15).json()
    assert len(hist) == 1
    L2 = requests.get(f"{API}/mechanics/{m2['id']}/ledger", headers=_hdr(), timeout=15).json()
    assert any(e.get("id") == p["id"] for e in L2["entries"])
    # amount reversal on mechanic side
    r = requests.post(f"{API}/mechanic-payments/{p['id']}/correct-amount",
                      headers=_hdr(_idem()),
                      json={"new_amount": 250,
                            "correction_reason": "amount typed wrong (short) at posting"}, timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert body["original"]["is_reversed"] is True
    assert body["fresh"]["amount"] == 250


# ---------------------- Amount-correction on reversed original blocked -------

def test_correction_on_reversed_payment_blocked(party):
    v = party["v"]; b = party["b"]
    p = _post_vp({"vendor_id": v["id"], "date": "2029-09-18", "amount": 400,
                  "against": "bill", "vendor_bill_id": b["id"]})
    requests.post(f"{API}/vendor-payments/{p['id']}/correct-amount",
                  headers=_hdr(_idem()),
                  json={"new_amount": 500,
                        "correction_reason": "amount typed wrong reversal path"}, timeout=15)
    # Further correction on the reversed original should fail
    r = requests.post(f"{API}/vendor-payments/{p['id']}/correct", headers=_hdr(_idem()),
                      json={"changes": {"remarks": "trying to edit reversed"},
                            "correction_reason": "trying to edit reversed payment"}, timeout=15)
    assert r.status_code == 400
    assert "reversed" in r.text.lower()
