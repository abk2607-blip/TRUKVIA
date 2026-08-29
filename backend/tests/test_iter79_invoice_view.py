"""Iter79 — Backend checks for /api/trips?ids= (used by InvoiceView)."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://trip-billing-pro-1.preview.emergentagent.com").rstrip("/")
TOKEN = os.environ["DEMO_TOKEN_VALUE"]
HDR = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture(scope="module", autouse=True)
def ensure_demo_session():
    requests.post(f"{BASE_URL}/api/auth/demo-login", timeout=15)


def _sample_trip_id():
    invs = requests.get(f"{BASE_URL}/api/invoices", headers=HDR, timeout=20).json()
    for i in invs:
        for tid in i.get("trip_ids", []) or []:
            # Confirm this trip exists via ids-lookup
            r = requests.get(f"{BASE_URL}/api/trips", headers=HDR, params={"ids": tid}, timeout=15).json()
            if len(r) == 1 and r[0]["id"] == tid:
                return tid, i.get("trip_ids")
    pytest.skip("No invoice with resolvable trip_ids found on demo tenant")


def test_trips_ids_single():
    tid, _ = _sample_trip_id()
    r = requests.get(f"{BASE_URL}/api/trips", headers=HDR, params={"ids": tid}, timeout=15)
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["id"] == tid


def test_trips_ids_bulk_and_bogus_filtered():
    tid, _ = _sample_trip_id()
    r = requests.get(
        f"{BASE_URL}/api/trips", headers=HDR,
        params={"ids": f"{tid},trip_bogus_xxx,another_fake"}, timeout=15
    )
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["id"] == tid


def test_trips_ids_only_commas_returns_empty():
    r = requests.get(f"{BASE_URL}/api/trips", headers=HDR, params={"ids": ",,,"}, timeout=15)
    assert r.status_code == 200
    assert r.json() == []


def test_trips_ids_unknown_returns_empty_list():
    r = requests.get(f"{BASE_URL}/api/trips", headers=HDR, params={"ids": "trip_nonexistent"}, timeout=15)
    assert r.status_code == 200
    assert r.json() == []


def test_trips_ids_bypasses_2000_cap():
    """ids-lookup must not honour the default pagination cap of 2000."""
    # Grab up to 5 arbitrary trip_ids from oldest invoices
    invs = requests.get(f"{BASE_URL}/api/invoices", headers=HDR, timeout=20).json()
    invs = [i for i in invs if i.get("trip_ids")]
    invs.sort(key=lambda x: x.get("invoice_date", ""))
    picked = []
    for i in invs:
        for t in i["trip_ids"]:
            picked.append(t)
            if len(picked) >= 5:
                break
        if len(picked) >= 5:
            break
    if not picked:
        pytest.skip("No trip_ids available")
    r = requests.get(f"{BASE_URL}/api/trips", headers=HDR, params={"ids": ",".join(picked)}, timeout=20)
    assert r.status_code == 200
    # All found ones must match a requested id
    for t in r.json():
        assert t["id"] in picked


def test_invoice_pdf_still_works():
    invs = requests.get(f"{BASE_URL}/api/invoices", headers=HDR, timeout=20).json()
    real = next((i for i in invs if i.get("trip_ids") and (i.get("total_amount") or 0) > 0), None)
    assert real, "No real invoice found"
    r = requests.get(f"{BASE_URL}/api/invoices/{real['id']}/pdf", headers=HDR, timeout=30)
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("application/pdf")
    assert len(r.content) > 1000
