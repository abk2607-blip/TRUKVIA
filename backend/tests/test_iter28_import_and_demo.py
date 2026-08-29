"""Iter28: Trip import (cid shadow bug regression) + Multi-company isolation + auth/me."""
import os
import io
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
TOKEN = os.environ["DEMO_TOKEN_VALUE"]
HDR = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.headers.update(HDR)
    return sess


def _ensure_company(sess, name):
    # find existing
    r = sess.get(f"{BASE_URL}/api/companies")
    assert r.status_code == 200, r.text
    for c in r.json():
        if c["name"] == name:
            return c["id"]
    r = sess.post(f"{BASE_URL}/api/companies", json={"name": name, "state": "Andhra Pradesh"})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _cleanup(sess, company_id, customer_name):
    # delete trips + customer under this company
    trips = sess.get(f"{BASE_URL}/api/trips", headers={**HDR, "X-Company-Id": company_id}).json()
    for t in trips:
        if t.get("vehicle_number", "").startswith("AP01IMP"):
            sess.delete(
                f"{BASE_URL}/api/trips/{t['id']}?reason=cleanup",
                headers={**HDR, "X-Company-Id": company_id},
            )
    custs = sess.get(f"{BASE_URL}/api/customers", headers={**HDR, "X-Company-Id": company_id}).json()
    for c in custs:
        if c["name"] == customer_name:
            sess.delete(f"{BASE_URL}/api/customers/{c['id']}", headers={**HDR, "X-Company-Id": company_id})


def test_auth_me(s):
    r = s.get(f"{BASE_URL}/api/auth/me")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d.get("email") == "owner@vbklogistics.test"
    assert "user_id" in d or "id" in d


def test_trip_import_stamps_company_id_not_customer_id(s):
    """Core regression for the cid shadow bug."""
    company_id = _ensure_company(s, "TEST_ImportCoA")
    hdr_a = {**HDR, "X-Company-Id": company_id}
    cust_name = "IMPORT_TEST_CUSTOMER"
    _cleanup(s, company_id, cust_name)

    # Create customer
    r = s.post(
        f"{BASE_URL}/api/customers",
        json={"name": cust_name, "state": "Andhra Pradesh"},
        headers=hdr_a,
    )
    assert r.status_code in (200, 201), r.text
    cust_id = r.json()["id"]
    assert cust_id != company_id  # sanity

    # Build CSV
    csv = (
        "date,customer_name,vehicle_number,tons,rate_per_ton,from_location,to_location,load_details\n"
        f"2026-08-08,{cust_name},AP01IMP001,10,1500,A,B,Bitumen\n"
        f"2026-08-08,{cust_name},AP01IMP002,10,1500,A,B,Bitumen\n"
    )
    files = {"file": ("trips.csv", io.BytesIO(csv.encode()), "text/csv")}
    r = s.post(f"{BASE_URL}/api/trips/import", files=files, headers=hdr_a)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["inserted"] == 2, body
    assert body["errors"] == [], body
    assert body["total_rows"] == 2

    # GET /api/trips — MUST show both imported trips
    r = s.get(f"{BASE_URL}/api/trips", headers=hdr_a)
    assert r.status_code == 200
    trips = r.json()
    imp = [t for t in trips if t.get("vehicle_number", "").startswith("AP01IMP")]
    assert len(imp) == 2, f"Expected 2 imported trips, found {len(imp)} — cid shadow bug likely!"

    # freight_amount must equal 15000
    for t in imp:
        assert t["company_id"] == company_id, f"company_id wrong! got {t['company_id']} expected {company_id}"
        assert t["company_id"] != cust_id, "company_id equals customer_id — cid shadow bug!"
        assert abs(float(t.get("freight_amount", 0)) - 15000.0) < 0.01, t

    _cleanup(s, company_id, cust_name)


def test_import_company_isolation(s):
    company_a = _ensure_company(s, "TEST_ImportCoA")
    company_b = _ensure_company(s, "TEST_ImportCoB")
    hdr_a = {**HDR, "X-Company-Id": company_a}
    hdr_b = {**HDR, "X-Company-Id": company_b}
    cust_name = "IMPORT_ISO_CUSTOMER"
    _cleanup(s, company_a, cust_name)
    _cleanup(s, company_b, cust_name)

    # Create cust in A
    r = s.post(f"{BASE_URL}/api/customers", json={"name": cust_name, "state": "AP"}, headers=hdr_a)
    assert r.status_code in (200, 201)

    csv = (
        "date,customer_name,vehicle_number,tons,rate_per_ton,from_location,to_location,load_details\n"
        f"2026-08-08,{cust_name},AP01IMP901,10,1500,A,B,Bitumen\n"
    )
    files = {"file": ("t.csv", io.BytesIO(csv.encode()), "text/csv")}
    r = s.post(f"{BASE_URL}/api/trips/import", files=files, headers=hdr_a)
    assert r.status_code == 200, r.text
    assert r.json()["inserted"] == 1

    # In B — should NOT see them
    trips_b = s.get(f"{BASE_URL}/api/trips", headers=hdr_b).json()
    leak = [t for t in trips_b if t.get("vehicle_number", "").startswith("AP01IMP")]
    assert leak == [], f"Trip leaked to Company B: {leak}"

    _cleanup(s, company_a, cust_name)
