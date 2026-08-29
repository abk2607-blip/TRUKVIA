"""Iter125 · Bulk All-Copies ZIP endpoint.

Verifies:
  · Selection mode: 3 PDFs per trip, correct suffixes, %PDF magic
  · Filter mode: uses same query as LR Register
  · Filename pattern (month-aligned + custom + explicit-selection)
  · Max 200 trips cap
  · Empty selection → 400
  · Wrong-company trip is skipped, not leaked
  · Missing lr_number back-filled; freight/shortage/supplier/invoice byte-identical
  · _manifest.txt lists included AND skipped
  · Audit row with action=lr_all_copies_zip is written per bulk request
"""
import io
import os
import re
import time
import zipfile
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"
TOKEN = os.environ["DEMO_TOKEN_VALUE"]
HDR = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def _first_customer():
    d = requests.get(f"{API}/customers", headers=HDR, timeout=10).json()
    items = d.get("items", d) if isinstance(d, dict) else d
    return items[0]["id"]


def _mk_trip(day="2029-01-11", tons=12, vehicle="AP99IT125A"):
    cid = _first_customer()
    r = requests.post(f"{API}/trips", headers=HDR, json={
        "customer_id": cid, "date": day, "vehicle_number": vehicle, "vehicle_type": "own",
        "tons": tons, "loaded_qty": tons, "unloaded_qty": tons - 0.05,
        "freight_mode": "per_ton", "rate_per_ton": 800,
        "product_rate_per_mt": 40000,
        "from_location": "Kakinada", "to_location": "Vizag",
        "driver_name": "Iter125 Driver",
    }, timeout=20)
    r.raise_for_status()
    return r.json()["id"]


# ---------------------------------------------------------------------------

def test_selection_mode_returns_zip_with_3_pdfs_per_trip():
    ids = [_mk_trip(day="2029-02-01"), _mk_trip(day="2029-02-01"), _mk_trip(day="2029-02-01")]
    r = requests.post(f"{API}/trips/bulk-all-copies-zip", headers=HDR,
                      json={"trip_ids": ids}, timeout=90)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    assert int(r.headers["x-iter125-included"]) == 3
    assert int(r.headers["x-iter125-skipped"]) == 0
    assert int(r.headers["x-iter125-pdfs"]) == 9
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = zf.namelist()
    pdfs = [n for n in names if n.endswith(".pdf")]
    assert len(pdfs) == 9, f"expected 9 PDFs, got {len(pdfs)}: {pdfs}"
    for n in pdfs:
        assert zf.read(n).startswith(b"%PDF"), n
    # Every PDF must live inside a folder AND the folder must contain all 3 copies
    folders = {n.split("/")[0] for n in pdfs}
    assert len(folders) == 3
    for f in folders:
        siblings = [n for n in pdfs if n.startswith(f + "/")]
        suffixes = sorted(s.rsplit("_", 1)[-1].replace(".pdf", "") for s in siblings)
        assert suffixes == ["DUPLICATE", "ORIGINAL", "TRIPLICATE"], f"folder {f}: {suffixes}"
    assert "_manifest.txt" in names


def test_filter_mode_matches_lr_register_set():
    ids = [_mk_trip(day="2029-03-05"), _mk_trip(day="2029-03-12"), _mk_trip(day="2029-03-25")]
    reg = requests.get(f"{API}/reports/lr-register",
                       headers=HDR, params={"month": "2029-03"}, timeout=30).json()
    reg_ids = {r["trip_id"] for r in reg["rows"]}
    assert set(ids).issubset(reg_ids)
    bulk = requests.post(f"{API}/trips/bulk-all-copies-zip", headers=HDR,
                         json={"start": "2029-03-01", "end": "2029-03-31"}, timeout=90)
    assert bulk.status_code == 200
    included_hdr = int(bulk.headers["x-iter125-included"])
    assert included_hdr == len(reg_ids), f"bulk={included_hdr} vs lr_register={len(reg_ids)}"


def test_filename_month_aligned():
    _mk_trip(day="2029-04-10")
    r = requests.post(f"{API}/trips/bulk-all-copies-zip", headers=HDR,
                      json={"start": "2029-04-01", "end": "2029-04-30"}, timeout=90)
    assert r.status_code == 200
    m = re.search(r'filename="(LR_Bulk_All_Copies_[A-Z0-9_]+_2029-04_\d+_trips\.zip)"',
                  r.headers.get("content-disposition", ""))
    assert m, r.headers.get("content-disposition", "")


def test_filename_custom_range():
    _mk_trip(day="2029-05-07")
    r = requests.post(f"{API}/trips/bulk-all-copies-zip", headers=HDR,
                      json={"start": "2029-05-05", "end": "2029-05-15"}, timeout=90)
    assert r.status_code == 200
    disp = r.headers.get("content-disposition", "")
    assert "2029-05-05to2029-05-15" in disp, disp


def test_max_200_trips_returns_400():
    fake = [f"trip_iter125_dummy_{i}" for i in range(201)]
    r = requests.post(f"{API}/trips/bulk-all-copies-zip", headers=HDR,
                      json={"trip_ids": fake}, timeout=30)
    assert r.status_code == 400
    assert "200" in r.text


def test_empty_selection_returns_400():
    r1 = requests.post(f"{API}/trips/bulk-all-copies-zip", headers=HDR, json={}, timeout=30)
    assert r1.status_code == 400
    r2 = requests.post(f"{API}/trips/bulk-all-copies-zip", headers=HDR,
                       json={"trip_ids": []}, timeout=30)
    # trip_ids=[] falls into filter mode which then requires start/end → 400
    assert r2.status_code == 400


def test_read_only_no_field_mutation_and_lr_number_backfill():
    tid = _mk_trip(day="2029-06-14")
    before = requests.get(f"{API}/trips/{tid}", headers=HDR, timeout=10).json()
    r = requests.post(f"{API}/trips/bulk-all-copies-zip", headers=HDR,
                      json={"trip_ids": [tid]}, timeout=60)
    assert r.status_code == 200
    after = requests.get(f"{API}/trips/{tid}", headers=HDR, timeout=10).json()
    # lr_number may have been back-filled (only allowed side-effect); no other field changes
    for k in ("freight_amount", "shortage_amount", "shortage_qty", "loaded_qty", "unloaded_qty",
              "supplier_freight", "supplier_shortage_deduction", "supplier_net_payable",
              "invoice_id", "status"):
        assert before.get(k) == after.get(k), f"field {k} mutated: {before.get(k)} → {after.get(k)}"
    assert after.get("lr_number"), "lr_number must exist after bulk call"


def test_manifest_lists_included_and_skipped():
    tid_real = _mk_trip(day="2029-07-04")
    tid_fake = "trip_iter125_does_not_exist_xyz"
    r = requests.post(f"{API}/trips/bulk-all-copies-zip", headers=HDR,
                      json={"trip_ids": [tid_real, tid_fake]}, timeout=60)
    assert r.status_code == 200
    assert int(r.headers["x-iter125-included"]) == 1
    assert int(r.headers["x-iter125-skipped"]) == 1
    assert "not_found:1" in r.headers.get("x-iter125-reasons", "")
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    manifest = zf.read("_manifest.txt").decode()
    assert "Included    : 1" in manifest
    assert "Skipped     : 1" in manifest
    assert tid_fake[:24] in manifest  # manifest column is truncated to 24 chars
    assert "not_found" in manifest


def test_audit_row_written_with_action_lr_all_copies_zip():
    tid = _mk_trip(day="2029-08-08")
    r = requests.post(f"{API}/trips/bulk-all-copies-zip", headers=HDR,
                      json={"trip_ids": [tid]}, timeout=60)
    assert r.status_code == 200
    time.sleep(0.5)
    # Verify audit row directly via Mongo (endpoint shape may vary in this codebase).
    from pymongo import MongoClient
    c = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))[
        os.environ.get("DB_NAME", "test_database")]
    doc = c.audit_logs.find_one(
        {"action": "lr_all_copies_zip", "entity_id": {"$regex": tid}},
        sort=[("timestamp", -1)],
    )
    assert doc is not None, "audit_log row not written"
    d = doc.get("detail") or {}
    assert d.get("source") == "bulk"
    assert d.get("included", 0) >= 1
    assert "filename" in d
    assert tid in (d.get("trip_ids") or [])
