"""Iter31: Auto LR number generation on POST /api/trips + LR column visibility.

Tests:
- POST /api/trips without lr_number => auto-assigns sequential LR
- Custom lr_number preserved and does NOT consume sequence
- Per-company scoped sequence (multi-company isolation)
- GET /api/trips returns lr_number
- POST /api/trips/{id}/duplicate resets lr_number to blank
- GET /api/trips/{id}/lr backward-compat auto-assign still works
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://trip-billing-pro-1.preview.emergentagent.com").rstrip("/")
TOKEN = "test_session_bitumen_2026"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.headers.update(AUTH)
    return sess


def _ensure_company(s, name):
    r = s.get(f"{BASE_URL}/api/companies")
    assert r.status_code == 200, r.text
    for c in r.json():
        if c["name"] == name:
            return c
    r = s.post(f"{BASE_URL}/api/companies", json={"name": name, "state": "Andhra Pradesh", "lr_prefix": "LR"})
    assert r.status_code in (200, 201), r.text
    return r.json()


def _ensure_customer(s, company_id, name):
    hdrs = {"X-Company-Id": company_id}
    r = s.get(f"{BASE_URL}/api/customers", headers=hdrs)
    for c in r.json():
        if c["name"] == name:
            return c
    r = s.post(f"{BASE_URL}/api/customers", headers=hdrs, json={"name": name, "state": "Andhra Pradesh"})
    assert r.status_code in (200, 201), r.text
    return r.json()


def _reset_company_lr(s, company_id, seq=1):
    # Update company via PUT to reset next_lr_number for deterministic test
    r = s.get(f"{BASE_URL}/api/companies")
    for c in r.json():
        if c["id"] == company_id:
            c["next_lr_number"] = seq
            c["lr_prefix"] = "LR"
            r2 = s.put(f"{BASE_URL}/api/companies/{company_id}", json=c)
            assert r2.status_code in (200, 204), r2.text
            return


def _new_trip_payload(customer_id, lr_number=None):
    p = {
        "customer_id": customer_id,
        "date": "2026-01-15",
        "vehicle_number": "AP16TT9999",
        "load_details": "Bitumen VG40",
        "tons": 20,
        "from_location": "Vij",
        "to_location": "Hyd",
        "freight_mode": "per_ton",
        "rate_per_ton": 1000,
    }
    if lr_number is not None:
        p["lr_number"] = lr_number
    return p


# --- Health first ---
def test_auth_ok(s):
    r = s.get(f"{BASE_URL}/api/auth/me")
    assert r.status_code == 200, r.text


# --- Setup companies ---
@pytest.fixture(scope="module")
def companies(s):
    a = _ensure_company(s, "TEST_LR_CO_A")
    b = _ensure_company(s, "TEST_LR_CO_B")
    _reset_company_lr(s, a["id"], seq=1)
    _reset_company_lr(s, b["id"], seq=1)
    cust_a = _ensure_customer(s, a["id"], "TEST_LR_Cust_A")
    cust_b = _ensure_customer(s, b["id"], "TEST_LR_Cust_B")
    return {"a": a, "b": b, "cust_a": cust_a, "cust_b": cust_b}


def test_auto_lr_sequential_same_company(s, companies):
    a = companies["a"]
    cust = companies["cust_a"]
    _reset_company_lr(s, a["id"], seq=1)
    hdrs = {"X-Company-Id": a["id"]}

    r1 = s.post(f"{BASE_URL}/api/trips", headers=hdrs, json=_new_trip_payload(cust["id"]))
    assert r1.status_code in (200, 201), r1.text
    t1 = r1.json()
    assert t1.get("lr_number", ""), f"lr_number should be auto-assigned, got: {t1}"
    assert t1["lr_number"].endswith("/00001"), f"expected /00001 suffix, got {t1['lr_number']}"

    r2 = s.post(f"{BASE_URL}/api/trips", headers=hdrs, json=_new_trip_payload(cust["id"]))
    assert r2.status_code in (200, 201), r2.text
    t2 = r2.json()
    assert t2["lr_number"].endswith("/00002"), f"expected /00002 suffix, got {t2['lr_number']}"

    # Cleanup
    s.delete(f"{BASE_URL}/api/trips/{t1['id']}", headers=hdrs, params={"reason": "cleanup"})
    s.delete(f"{BASE_URL}/api/trips/{t2['id']}", headers=hdrs, params={"reason": "cleanup"})


def test_custom_lr_preserved_no_seq_increment(s, companies):
    a = companies["a"]
    cust = companies["cust_a"]
    _reset_company_lr(s, a["id"], seq=10)
    hdrs = {"X-Company-Id": a["id"]}

    r = s.post(f"{BASE_URL}/api/trips", headers=hdrs,
               json=_new_trip_payload(cust["id"], lr_number="CUSTOM-999"))
    assert r.status_code in (200, 201), r.text
    t = r.json()
    assert t["lr_number"] == "CUSTOM-999"

    # Verify sequence NOT consumed - next auto still gives 00010
    r2 = s.post(f"{BASE_URL}/api/trips", headers=hdrs, json=_new_trip_payload(cust["id"]))
    t2 = r2.json()
    assert t2["lr_number"].endswith("/00010"), f"expected seq 10 preserved, got {t2['lr_number']}"

    s.delete(f"{BASE_URL}/api/trips/{t['id']}", headers=hdrs, params={"reason": "cleanup"})
    s.delete(f"{BASE_URL}/api/trips/{t2['id']}", headers=hdrs, params={"reason": "cleanup"})


def test_per_company_scope(s, companies):
    a = companies["a"]; b = companies["b"]
    _reset_company_lr(s, a["id"], seq=1)
    _reset_company_lr(s, b["id"], seq=1)

    # Create 2 trips under A
    hA = {"X-Company-Id": a["id"]}
    hB = {"X-Company-Id": b["id"]}
    ta1 = s.post(f"{BASE_URL}/api/trips", headers=hA, json=_new_trip_payload(companies["cust_a"]["id"])).json()
    ta2 = s.post(f"{BASE_URL}/api/trips", headers=hA, json=_new_trip_payload(companies["cust_a"]["id"])).json()
    assert ta1["lr_number"].endswith("/00001")
    assert ta2["lr_number"].endswith("/00002")

    # Company B should still start at 00001 (unaffected)
    tb1 = s.post(f"{BASE_URL}/api/trips", headers=hB, json=_new_trip_payload(companies["cust_b"]["id"])).json()
    assert tb1["lr_number"].endswith("/00001"), f"company B seq should be independent, got {tb1['lr_number']}"

    for t, h in [(ta1, hA), (ta2, hA), (tb1, hB)]:
        s.delete(f"{BASE_URL}/api/trips/{t['id']}", headers=h, params={"reason": "cleanup"})


def test_get_trips_includes_lr_number(s, companies):
    a = companies["a"]
    hdrs = {"X-Company-Id": a["id"]}
    _reset_company_lr(s, a["id"], seq=50)
    created = s.post(f"{BASE_URL}/api/trips", headers=hdrs, json=_new_trip_payload(companies["cust_a"]["id"])).json()

    r = s.get(f"{BASE_URL}/api/trips", headers=hdrs)
    assert r.status_code == 200
    trips = r.json()
    match = [t for t in trips if t["id"] == created["id"]]
    assert match, "created trip not in list"
    assert "lr_number" in match[0]
    assert match[0]["lr_number"] == created["lr_number"]

    s.delete(f"{BASE_URL}/api/trips/{created['id']}", headers=hdrs, params={"reason": "cleanup"})


def test_duplicate_resets_lr(s, companies):
    a = companies["a"]
    hdrs = {"X-Company-Id": a["id"]}
    _reset_company_lr(s, a["id"], seq=100)
    src = s.post(f"{BASE_URL}/api/trips", headers=hdrs, json=_new_trip_payload(companies["cust_a"]["id"])).json()
    assert src["lr_number"].endswith("/00100")

    r = s.post(f"{BASE_URL}/api/trips/{src['id']}/duplicate", headers=hdrs)
    assert r.status_code in (200, 201), r.text
    dup = r.json()
    assert dup.get("lr_number", "") == "", f"duplicate should have blank lr_number, got {dup.get('lr_number')!r}"

    s.delete(f"{BASE_URL}/api/trips/{src['id']}", headers=hdrs, params={"reason": "cleanup"})
    s.delete(f"{BASE_URL}/api/trips/{dup['id']}", headers=hdrs, params={"reason": "cleanup"})


def test_lr_pdf_backward_compat_autoassign(s, companies):
    """If a trip somehow has blank lr_number, GET /trips/{id}/lr should still auto-assign."""
    a = companies["a"]
    hdrs = {"X-Company-Id": a["id"]}
    _reset_company_lr(s, a["id"], seq=200)

    # Create with blank explicit lr and then wipe it via update
    src = s.post(f"{BASE_URL}/api/trips", headers=hdrs, json=_new_trip_payload(companies["cust_a"]["id"])).json()
    # Duplicate produces a trip with blank lr - use that
    dup = s.post(f"{BASE_URL}/api/trips/{src['id']}/duplicate", headers=hdrs).json()
    assert dup["lr_number"] == ""

    r = s.get(f"{BASE_URL}/api/trips/{dup['id']}/lr", headers=hdrs)
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("application/pdf")

    # Verify lr_number now populated
    r2 = s.get(f"{BASE_URL}/api/trips", headers=hdrs)
    dup_after = [t for t in r2.json() if t["id"] == dup["id"]][0]
    assert dup_after["lr_number"], "lr should have been assigned by LR PDF endpoint"

    s.delete(f"{BASE_URL}/api/trips/{src['id']}", headers=hdrs, params={"reason": "cleanup"})
    s.delete(f"{BASE_URL}/api/trips/{dup['id']}", headers=hdrs, params={"reason": "cleanup"})
