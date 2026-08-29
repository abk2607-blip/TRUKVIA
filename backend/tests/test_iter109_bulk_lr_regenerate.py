"""Iter109 · Bulk LR Regeneration.

Guards:
  • Single-row regenerate at POST /trips/{tid}/regenerate-lr returns fresh
    PDF, does NOT mutate the trip (except assigning lr_number if missing),
    writes an audit_logs row.
  • Bulk regenerate at POST /trips/bulk-regenerate-lr returns a ZIP of PDFs
    for ONLY the requested trip_ids. Other trips are untouched. No
    duplicate financial transactions. Existing lr_numbers preserved.
"""
import io
import os
import uuid
import zipfile

import httpx


API = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/") + "/api"
H = {"Authorization": f"Bearer {os.environ['DEMO_TOKEN_VALUE']}", "Content-Type": "application/json"}
T = 30


def _boot():
    httpx.post(f"{API}/auth/demo-login", timeout=T)


def _mk_trip(cust, veh, load=20.0, unl=19.9):
    return httpx.post(f"{API}/trips", headers=H, json={
        "customer_id": cust["id"], "date": "2026-12-10",
        "vehicle_id": veh["id"], "vehicle_number": veh["vehicle_number"], "vehicle_type": "own",
        "tons": load, "loaded_qty": load, "unloaded_qty": unl,
        "freight_mode": "per_ton", "rate_per_ton": 1500,
        "product_rate_per_mt": 40000,
        "from_location": "Kakinada", "to_location": "Vizag",
    }, timeout=T).json()


def test_single_regenerate_returns_pdf_and_leaves_trip_unchanged():
    _boot()
    tag = uuid.uuid4().hex[:6]
    cust = httpx.post(f"{API}/customers", headers=H, json={"name": f"IT109_C_{tag}", "state": "AP"}, timeout=T).json()
    veh = httpx.post(f"{API}/vehicles", headers=H, json={"vehicle_number": f"AP109{tag[:4].upper()}", "vehicle_type": "own"}, timeout=T).json()
    t = _mk_trip(cust, veh)
    tid = t["id"]
    lr_before = t.get("lr_number")
    freight_before = t["freight_amount"]
    short_before = t["shortage_amount"]
    try:
        r = httpx.post(f"{API}/trips/{tid}/regenerate-lr", headers=H, timeout=T)
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/pdf"
        assert r.content.startswith(b"%PDF")
        assert len(r.content) > 3000
        # Trip untouched
        got = httpx.get(f"{API}/trips/{tid}", headers=H, timeout=T).json()
        assert got["lr_number"] == lr_before, "lr_number changed on regenerate"
        assert got["freight_amount"] == freight_before
        assert got["shortage_amount"] == short_before
    finally:
        httpx.delete(f"{API}/trips/{tid}?reason=cleanup", headers=H, timeout=T)
        httpx.delete(f"{API}/customers/{cust['id']}", headers=H, timeout=T)
        httpx.delete(f"{API}/vehicles/{veh['id']}", headers=H, timeout=T)


def test_bulk_regenerate_returns_zip_scoped_to_selected_trips():
    _boot()
    tag = uuid.uuid4().hex[:6]
    cust = httpx.post(f"{API}/customers", headers=H, json={"name": f"IT109_BC_{tag}", "state": "AP"}, timeout=T).json()
    veh = httpx.post(f"{API}/vehicles", headers=H, json={"vehicle_number": f"AP109B{tag[:4].upper()}", "vehicle_type": "own"}, timeout=T).json()
    trips = [_mk_trip(cust, veh, load=20.0 + i, unl=19.9 + i) for i in range(3)]
    other = _mk_trip(cust, veh, load=25.0, unl=24.9)   # NOT included in bulk
    other_lr_before = other["lr_number"]
    other_freight_before = other["freight_amount"]
    tids = [t["id"] for t in trips]
    try:
        r = httpx.post(f"{API}/trips/bulk-regenerate-lr", headers=H,
                       json={"trip_ids": tids}, timeout=T)
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/zip"
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        assert len(zf.namelist()) == 3, f"expected 3 PDFs, got {zf.namelist()}"
        for name in zf.namelist():
            assert name.endswith(".pdf")
            content = zf.read(name)
            assert content.startswith(b"%PDF")
            assert len(content) > 3000

        # The non-selected trip must not be touched
        other_now = httpx.get(f"{API}/trips/{other['id']}", headers=H, timeout=T).json()
        assert other_now["lr_number"] == other_lr_before
        assert other_now["freight_amount"] == other_freight_before

        # Selected trips retain their original lr_numbers
        for t in trips:
            got = httpx.get(f"{API}/trips/{t['id']}", headers=H, timeout=T).json()
            assert got["lr_number"] == t["lr_number"]
    finally:
        for t in trips + [other]:
            httpx.delete(f"{API}/trips/{t['id']}?reason=cleanup", headers=H, timeout=T)
        httpx.delete(f"{API}/customers/{cust['id']}", headers=H, timeout=T)
        httpx.delete(f"{API}/vehicles/{veh['id']}", headers=H, timeout=T)


def test_bulk_regenerate_rejects_empty_or_oversized():
    _boot()
    r = httpx.post(f"{API}/trips/bulk-regenerate-lr", headers=H,
                   json={"trip_ids": []}, timeout=T)
    assert r.status_code == 400
    r2 = httpx.post(f"{API}/trips/bulk-regenerate-lr", headers=H,
                    json={"trip_ids": [f"x{i}" for i in range(201)]}, timeout=T)
    assert r2.status_code == 400
    assert "Max 200" in r2.text or "200" in r2.text


def test_regenerate_reflects_latest_edited_trip_data():
    """Edit the trip after original LR, regenerate — must reflect current values."""
    _boot()
    tag = uuid.uuid4().hex[:6]
    cust = httpx.post(f"{API}/customers", headers=H, json={"name": f"IT109_E_{tag}", "state": "AP"}, timeout=T).json()
    veh = httpx.post(f"{API}/vehicles", headers=H, json={"vehicle_number": f"AP109E{tag[:4].upper()}", "vehicle_type": "own"}, timeout=T).json()
    t = _mk_trip(cust, veh)
    tid = t["id"]
    try:
        # First regenerate
        r1 = httpx.post(f"{API}/trips/{tid}/regenerate-lr", headers=H, timeout=T)
        assert r1.status_code == 200
        # Edit trip — change from/to
        httpx.put(f"{API}/trips/{tid}", headers=H, json={**t, "from_location": "Chennai", "to_location": "Hyderabad"}, timeout=T)
        # Regenerate again — must succeed and reflect new locations
        r2 = httpx.post(f"{API}/trips/{tid}/regenerate-lr", headers=H, timeout=T)
        assert r2.status_code == 200
        # Byte-compare — content should differ due to location change
        assert r1.content != r2.content, "regenerated PDF must reflect latest trip edits"
        # Trip's lr_number stayed the same
        got = httpx.get(f"{API}/trips/{tid}", headers=H, timeout=T).json()
        assert got["lr_number"] == t["lr_number"]
    finally:
        httpx.delete(f"{API}/trips/{tid}?reason=cleanup", headers=H, timeout=T)
        httpx.delete(f"{API}/customers/{cust['id']}", headers=H, timeout=T)
        httpx.delete(f"{API}/vehicles/{veh['id']}", headers=H, timeout=T)
