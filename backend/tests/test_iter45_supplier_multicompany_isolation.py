"""Iter45 — Multi-company isolation stress test for supplier module."""
import os
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"
TOKEN = os.environ["DEMO_TOKEN_VALUE"]
HEADERS_BASE = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def _hdr(cid=None):
    h = dict(HEADERS_BASE)
    if cid:
        h["X-Company-Id"] = cid
    return h


def _companies():
    r = requests.get(f"{API}/companies", headers=HEADERS_BASE)
    assert r.status_code == 200, r.text
    return r.json()


def _ensure_two_companies():
    comps = _companies()
    if len(comps) >= 2:
        return comps[0]["id"], comps[1]["id"]
    # Create a second
    r = requests.post(f"{API}/companies", headers=HEADERS_BASE, json={
        "name": "PYTEST Iso Co B",
    })
    assert r.status_code == 200, r.text
    comps = _companies()
    return comps[0]["id"], comps[-1]["id"]


def test_supplier_list_isolated_by_company():
    cid_a, cid_b = _ensure_two_companies()
    name = f"PYTEST IsoSup {os.urandom(3).hex().upper()}"
    # Create in A
    r = requests.post(f"{API}/suppliers", headers=_hdr(cid_a), json={"name": name, "opening_balance": 1000, "opening_balance_type": "payable"})
    assert r.status_code == 200, r.text
    sid = r.json()["id"]

    # List in A -> present (direct GET, avoids the 2000-row list cap sorted by name)
    r_get_a = requests.get(f"{API}/suppliers/{sid}", headers=_hdr(cid_a))
    assert r_get_a.status_code == 200, f"Supplier not visible in Company A: {r_get_a.status_code}"
    assert r_get_a.json()["id"] == sid

    # List in B -> absent
    list_b = requests.get(f"{API}/suppliers", headers=_hdr(cid_b)).json()
    assert not any(s["id"] == sid for s in list_b), "Company A supplier leaked into Company B list"

    # Direct GET in B must 404
    r_get_b = requests.get(f"{API}/suppliers/{sid}", headers=_hdr(cid_b))
    assert r_get_b.status_code == 404, f"Supplier GET leaked cross-company: {r_get_b.status_code}"

    # Ledger in B must 404
    r_led_b = requests.get(f"{API}/suppliers/{sid}/ledger", headers=_hdr(cid_b))
    assert r_led_b.status_code == 404

    # Outstanding in B must 404
    r_out_b = requests.get(f"{API}/suppliers/{sid}/outstanding", headers=_hdr(cid_b))
    assert r_out_b.status_code == 404

    # Payments list in B must be empty for this sid
    r_pay_b = requests.get(f"{API}/suppliers/{sid}/payments", headers=_hdr(cid_b))
    assert r_pay_b.status_code == 200
    assert r_pay_b.json() == []

    # Create payment in B for this sid must fail (supplier not found)
    r_pay_create_b = requests.post(f"{API}/suppliers/{sid}/payments", headers=_hdr(cid_b), json={
        "supplier_id": sid, "date": "2028-05-01", "amount": 100, "mode": "Cash", "against": "outstanding",
    })
    assert r_pay_create_b.status_code == 404

    # Dashboard in B: must not contain sid
    dash_b = requests.get(f"{API}/suppliers-dashboard", headers=_hdr(cid_b)).json()
    assert not any(x["supplier_id"] == sid for x in dash_b["suppliers"]), "Supplier leaked into Company B dashboard"


def test_duplicate_name_scoped_per_company():
    """Same supplier name should be allowed in two different companies."""
    cid_a, cid_b = _ensure_two_companies()
    name = f"PYTEST DupCross {os.urandom(3).hex().upper()}"
    r1 = requests.post(f"{API}/suppliers", headers=_hdr(cid_a), json={"name": name})
    assert r1.status_code == 200
    r2 = requests.post(f"{API}/suppliers", headers=_hdr(cid_b), json={"name": name})
    assert r2.status_code == 200, "Duplicate name check should be per company"


def test_soft_delete_keeps_record():
    cid_a, _ = _ensure_two_companies()
    r = requests.post(f"{API}/suppliers", headers=_hdr(cid_a), json={"name": f"PYTEST Soft {os.urandom(3).hex().upper()}"})
    sid = r.json()["id"]
    d = requests.delete(f"{API}/suppliers/{sid}", headers=_hdr(cid_a))
    assert d.status_code == 200
    g = requests.get(f"{API}/suppliers/{sid}", headers=_hdr(cid_a))
    assert g.status_code == 200
    assert g.json()["is_active"] is False


def test_delete_payment_reason_min_length():
    cid_a, _ = _ensure_two_companies()
    sup = requests.post(f"{API}/suppliers", headers=_hdr(cid_a), json={"name": f"PYTEST RsnMin {os.urandom(3).hex().upper()}"}).json()
    sid = sup["id"]
    p = requests.post(f"{API}/suppliers/{sid}/payments", headers=_hdr(cid_a), json={
        "supplier_id": sid, "date": "2028-06-01", "amount": 500, "mode": "Cash", "against": "outstanding",
    }).json()
    pid = p["id"]
    # <3 char reason should be rejected
    r = requests.delete(f"{API}/suppliers/{sid}/payments/{pid}", headers=_hdr(cid_a), params={"reason": "ab"})
    assert r.status_code == 422
    r2 = requests.delete(f"{API}/suppliers/{sid}/payments/{pid}", headers=_hdr(cid_a), params={"reason": "valid reason"})
    assert r2.status_code == 200


def test_dashboard_shape_all_keys():
    r = requests.get(f"{API}/suppliers-dashboard", headers=HEADERS_BASE)
    assert r.status_code == 200
    d = r.json()
    for k in ("total_suppliers", "active_suppliers", "active_vehicles",
              "total_freight", "total_advances", "total_payments", "total_outstanding"):
        assert k in d["totals"]
