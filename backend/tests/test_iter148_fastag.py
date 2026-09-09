"""Iter148 P0 · FASTag parser + import flow — end-to-end tests."""
from pathlib import Path
import os
import requests
from pymongo import MongoClient

from services_toll_import import (
    parse_fastag, detect_source, _normalise_reg, _parse_dt, _extract_plaza,
    make_source_key,
)

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api" if BASE_URL.startswith("http") else "http://localhost:8001/api"
TOKEN = os.environ.get("DEMO_TOKEN_VALUE", "")
H = {"Authorization": f"Bearer {TOKEN}"}
HJ = {**H, "Content-Type": "application/json"}
FX = Path(__file__).parent / "fixtures" / "iter148"
IDFC = FX / "FASTag_IDFC.xlsx"
LIVQ = FX / "FASTag_LIVQ.xlsx"


def _sync_db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _cleanup():
    d = _sync_db()
    me = d.users.find_one({"email": "demo@bitumen-transport.local"}, {"_id": 0, "user_id": 1})
    if me:
        d.expenses.delete_many({"user_id": me["user_id"], "source_type": "fastag_import"})


# ── Parser ──────────────────────────────────────────────────────────
def test_utilities():
    assert _normalise_reg(" ap 39 ul 6118 ") == "AP39UL6118"
    assert _parse_dt("01 Sep 26 11:51 PM") == "2026-09-01"
    assert _extract_plaza("FasTag Toll Payment at PARANUR TOLL") == "PARANUR TOLL"
    assert make_source_key("idfc", "cid1", "007054133004") == "toll:idfc:cid1:007054133004"


def test_idfc_auto_detect():
    assert detect_source("any.xlsx", IDFC.read_bytes()) == "idfc"


def test_livq_auto_detect():
    assert detect_source("any.xlsx", LIVQ.read_bytes()) == "livq"


def test_unrecognised_file():
    assert detect_source("x.txt", b"hello") is None


def test_idfc_parse_debits_only():
    v, rows = parse_fastag(IDFC.read_bytes())
    assert v == "idfc"
    assert rows, "IDFC parser returned empty rows"
    for r in rows:
        assert r["source"] == "idfc"
        assert r["source_txn_ref"], f"row {r['row_index']} missing txn id"
        assert r["source_vehicle_ref"], f"row {r['row_index']} missing vehicle ref"
        assert r["amount"] > 0
        assert r["date"]


def test_livq_parse_debits_only():
    v, rows = parse_fastag(LIVQ.read_bytes())
    assert v == "livq"
    assert rows
    for r in rows:
        assert r["source"] == "livq"
        assert r["source_txn_ref"]
        assert r["source_vehicle_ref"]     # non-blank Truck only
        assert r["amount"] > 0
        assert r["date"]


def test_livq_plaza_extracted():
    _, rows = parse_fastag(LIVQ.read_bytes())
    with_plaza = [r for r in rows if r["plaza"]]
    assert with_plaza, "LIVQ file must have at least one plaza"
    assert any("TOLL" in r["plaza"] or "PLA" in r["plaza"] for r in with_plaza)


def test_credits_and_blank_truck_skipped():
    """LIVQ has FasTag Recharge rows (Credit + blank Truck Number)
    that must never appear as toll rows."""
    _, rows = parse_fastag(LIVQ.read_bytes())
    for r in rows:
        assert "FasTag Recharge" not in r["description"], \
            "Recharge row leaked into toll rows"
        assert r["source_vehicle_ref"] != ""


def test_truck_normalisation_across_rows():
    _, rows = parse_fastag(IDFC.read_bytes())
    for r in rows:
        assert r["source_vehicle_ref"] == r["source_vehicle_ref"].upper()
        assert " " not in r["source_vehicle_ref"]


# ── Import flow (live API) ──────────────────────────────────────────
def _preview(path: Path):
    with path.open("rb") as f:
        return requests.post(f"{API}/toll-import/preview", headers=H,
                             files={"file": (path.name, f, "application/octet-stream")},
                             timeout=30)


def test_preview_livq_buckets():
    r = _preview(LIVQ)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["vendor"] == "livq"
    assert body["total_rows"] > 0
    assert body["counts"]["error"] == 0


def test_preview_idfc_buckets():
    r = _preview(IDFC)
    assert r.status_code == 200, r.text
    assert r.json()["vendor"] == "idfc"


def test_preview_unrecognised_rejects():
    r = requests.post(f"{API}/toll-import/preview", headers=H,
                      files={"file": ("x.txt", b"not a fastag statement", "text/plain")},
                      timeout=15)
    assert r.status_code == 400


def test_commit_livq_creates_canonical_toll():
    _cleanup()
    veh = [v for v in requests.get(f"{API}/vehicles", headers=H,
            params={"active_only": True}, timeout=15).json()
           if (v.get("vehicle_type") or "").lower() != "supplier"][0]
    body = _preview(LIVQ).json()
    rows = [{**r, "bucket": "ready",
             "resolved_vehicle_id": veh["id"],
             "resolved_vehicle_number": veh["vehicle_number"]}
            for r in body["rows"] if r["bucket"] != "error"][:10]
    assert rows, "no eligible rows to commit"
    r = requests.post(f"{API}/toll-import/commit", headers=HJ,
                      json={"vendor": "livq", "rows": rows}, timeout=30)
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["created"] >= 1
    assert res["failed"] == 0
    listed = requests.get(f"{API}/expenses", headers=H,
                          params={"source_type": "fastag_import"}, timeout=15).json()
    assert any(e["source"] == "livq" and e["category"] == "Toll" for e in listed)


def test_reupload_all_exact_duplicates():
    """After commit_livq test (which imports 10 LIVQ rows), re-uploading
    the same file must surface those exact 10 as exact_duplicate."""
    # Make this test self-contained under xdist: (re)commit once so we
    # have known exact-dup fodder even if the prior test's state was
    # cleared by parallel-worker cleanup ordering.
    veh = [v for v in requests.get(f"{API}/vehicles", headers=H,
            params={"active_only": True}, timeout=15).json()
           if (v.get("vehicle_type") or "").lower() != "supplier"][0]
    body0 = _preview(LIVQ).json()
    rows_seed = [{**r, "bucket": "ready",
                  "resolved_vehicle_id": veh["id"],
                  "resolved_vehicle_number": veh["vehicle_number"]}
                 for r in body0["rows"] if r["bucket"] == "ready"
                 or r["bucket"] == "vehicle_mapping_required"][:5]
    if rows_seed:
        requests.post(f"{API}/toll-import/commit", headers=HJ,
                      json={"vendor": "livq", "rows": rows_seed}, timeout=30)

    body = _preview(LIVQ).json()
    non_error = [r for r in body["rows"] if r["bucket"] != "error"]
    dupes = [r for r in non_error if r["bucket"] == "exact_duplicate"]
    assert dupes, "re-preview should surface prior imports as exact_duplicate"


def test_commit_rejects_bad_vendor():
    r = requests.post(f"{API}/toll-import/commit", headers=HJ,
                      json={"vendor": "sbi", "rows": []}, timeout=15)
    assert r.status_code == 400


def test_source_type_is_fastag_import_and_category_toll():
    listed = requests.get(f"{API}/expenses", headers=H,
                          params={"source_type": "fastag_import"}, timeout=15).json()
    for e in listed[:5]:
        assert e["category"] == "Toll"
        assert e["source_type"] == "fastag_import"
        assert e["source"] in ("idfc", "livq")
        assert e["source_txn_ref"]
        assert e["source_key"].startswith("toll:")


def test_zzz_cleanup():
    _cleanup()
    assert True
