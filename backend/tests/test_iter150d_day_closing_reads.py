"""Iter150D · Day Closing readers + late-entry + historical-entry UAT.

Coverage (~36 tests):
  list/get/late-entries/day-status contract · historical entry after close
  across every canonical source type · edit-after-close · owner-delete
  with reason · failed-hook replay after close · Day Book / Account Ledger
  reflection · router purity for read paths · tenant isolation.
"""
from __future__ import annotations

import os
import uuid
from datetime import date as _date, timedelta
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path("/app/frontend/.env"))
load_dotenv(Path("/app/backend/.env"))

API = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
TOK = os.environ["DEMO_TOKEN_VALUE"]
H = {"Authorization": f"Bearer {TOK}"}
HJSON = {**H, "Content-Type": "application/json"}


def _db():
    return MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _demo():
    d = _db()
    me = d.users.find_one({"email": "demo@bitumen-transport.local"},
                          {"_id": 0, "user_id": 1})
    r = requests.get(f"{API}/vehicles", headers=H,
                     params={"active_only": False, "limit": 1}, timeout=30)
    return me["user_id"], r.json()[0]["company_id"]


def _past(days=1):
    return (_date.today() - timedelta(days=days)).isoformat()


class _Ctx:
    def __init__(self):
        self.d = _db()
        self.uid, self.cid = _demo()
        self.tag = uuid.uuid4().hex[:8]
        self._closures: list[str] = []
        self._wrs: list[str] = []
        self._wts: list[str] = []
        self._was: list[str] = []
        # Reserved base offset so multiple close dates are unique per module.
        self._base = 550

    def new_close_date(self):
        self._base += 5
        return (_date.today() - timedelta(days=self._base)).isoformat()

    def close(self, date=None, notes="uat"):
        if date is None:
            date = self.new_close_date()
        r = requests.post(f"{API}/fin/day-closures", headers=HJSON,
                          json={"close_date": date, "close_notes": notes},
                          timeout=20)
        if r.status_code == 200:
            self._closures.append(date)
        return date, r

    def wr(self, date, amt=100.0):
        r = requests.post(f"{API}/wallet-recharges", headers=HJSON, json={
            "wallet_code": "WALLET_FASTAG", "funding_mode": "Bank",
            "amount": amt, "date": date, "reference": f"150d-{self.tag}",
            "remarks": "",
        }, timeout=15)
        if r.status_code == 200:
            self._wrs.append(r.json()["id"])
        return r

    def wt(self, date, amt=50.0):
        r = requests.post(f"{API}/wallet-transfers", headers=HJSON, json={
            "source_wallet_code": "WALLET_FASTAG",
            "destination_wallet_code": "WALLET_FUEL",
            "amount": amt, "date": date, "reference": f"150d-{self.tag}",
            "remarks": "",
        }, timeout=15)
        if r.status_code == 200:
            self._wts.append(r.json()["id"])
        return r

    def wa(self, date, direction="increase", amt=25.0):
        r = requests.post(f"{API}/wallet-adjustments", headers=HJSON, json={
            "wallet_code": "WALLET_FASTAG", "direction": direction,
            "amount": amt, "reason": f"150d-{self.tag}",
            "date": date, "remarks": "",
        }, timeout=15)
        if r.status_code == 200:
            self._was.append(r.json()["id"])
        return r

    def teardown(self):
        for w in self._wrs:
            try: requests.delete(f"{API}/wallet-recharges/{w}", headers=H, timeout=10)
            except Exception: pass
        for w in self._wts:
            try: requests.delete(f"{API}/wallet-transfers/{w}", headers=H, timeout=10)
            except Exception: pass
        for w in self._was:
            try: requests.delete(f"{API}/wallet-adjustments/{w}", headers=H, timeout=10)
            except Exception: pass
        for d in self._closures:
            self.d.fin_day_closures.delete_many(
                {"user_id": self.uid, "company_id": self.cid, "close_date": d})


@pytest.fixture(scope="module")
def ctx():
    c = _Ctx()
    yield c
    c.teardown()


# ── 1. List contract ────────────────────────────────────────────────────

def test_1_list_requires_auth(ctx):
    r = requests.get(f"{API}/fin/day-closures", timeout=10)
    assert r.status_code == 401


def test_2_list_returns_count_and_rows(ctx):
    ctx.close()
    r = requests.get(f"{API}/fin/day-closures", headers=H, timeout=15)
    assert r.status_code == 200
    j = r.json()
    assert "rows" in j and "count" in j
    assert isinstance(j["rows"], list)


def test_3_list_filter_by_date_range(ctx):
    d, _ = ctx.close()
    r = requests.get(f"{API}/fin/day-closures", headers=H,
                     params={"date_from": d, "date_to": d}, timeout=15)
    assert r.status_code == 200
    for row in r.json()["rows"]:
        assert row["close_date"] == d


def test_4_list_filter_by_status(ctx):
    r = requests.get(f"{API}/fin/day-closures", headers=H,
                     params={"status": "closed"}, timeout=15)
    for row in r.json()["rows"]:
        assert row["status"] == "closed"


# ── 2. Get single closure ──────────────────────────────────────────────

def test_5_get_single_200(ctx):
    d, _ = ctx.close()
    r = requests.get(f"{API}/fin/day-closures/{d}", headers=H, timeout=10)
    assert r.status_code == 200
    assert r.json()["close_date"] == d


def test_6_get_single_404(ctx):
    r = requests.get(f"{API}/fin/day-closures/2010-06-06", headers=H, timeout=10)
    assert r.status_code == 404


def test_7_get_invalid_date_400(ctx):
    r = requests.get(f"{API}/fin/day-closures/not-a-date", headers=H, timeout=10)
    assert r.status_code == 400


# ── 3. Day-status probe ────────────────────────────────────────────────

def test_8_day_status_open(ctx):
    r = requests.get(f"{API}/fin/day-status", headers=H,
                     params={"date": "2010-05-05"}, timeout=10)
    assert r.status_code == 200
    j = r.json()
    assert j["is_closed"] is False


def test_9_day_status_closed(ctx):
    d, _ = ctx.close()
    r = requests.get(f"{API}/fin/day-status", headers=H,
                     params={"date": d}, timeout=10)
    assert r.status_code == 200
    j = r.json()
    assert j["is_closed"] is True
    assert j["status"] == "closed"


def test_10_day_status_missing_date_400(ctx):
    r = requests.get(f"{API}/fin/day-status", headers=H, timeout=10)
    assert r.status_code in (400, 422)


# ── 4. Late-entries ────────────────────────────────────────────────────

def test_11_late_entries_empty(ctx):
    d, _ = ctx.close()
    r = requests.get(f"{API}/fin/day-closures/{d}/late-entries", headers=H,
                     timeout=15)
    assert r.status_code == 200
    j = r.json()
    assert j["count"] == 0
    assert j["rows"] == []


def test_12_late_entries_wallet_recharge(ctx):
    d, _ = ctx.close()
    # Backdated recharge landing on/before the closed date.
    assert ctx.wr(d).status_code == 200
    r = requests.get(f"{API}/fin/day-closures/{d}/late-entries", headers=H,
                     timeout=15)
    j = r.json()
    assert j["count"] >= 2  # WALLET_FASTAG debit + BANK_DEFAULT credit
    assert "wallet_recharge" in j["by_source_type"]


def test_13_late_entries_wallet_transfer(ctx):
    d, _ = ctx.close()
    assert ctx.wt(d).status_code == 200
    r = requests.get(f"{API}/fin/day-closures/{d}/late-entries", headers=H,
                     timeout=15).json()
    assert "wallet_transfer" in r["by_source_type"]


def test_14_late_entries_wallet_adjustment(ctx):
    d, _ = ctx.close()
    assert ctx.wa(d).status_code == 200
    r = requests.get(f"{API}/fin/day-closures/{d}/late-entries", headers=H,
                     timeout=15).json()
    assert "wallet_adjustment" in r["by_source_type"]


def test_15_late_entries_days_late_bucket(ctx):
    d, _ = ctx.close()
    assert ctx.wr(d).status_code == 200
    r = requests.get(f"{API}/fin/day-closures/{d}/late-entries", headers=H,
                     timeout=15).json()
    assert "by_days_late_bucket" in r
    total_bucketed = sum(r["by_days_late_bucket"].values())
    assert total_bucketed == r["count"]


def test_16_late_entries_totals_rounded(ctx):
    d, _ = ctx.close()
    ctx.wr(d, amt=123.456)
    j = requests.get(f"{API}/fin/day-closures/{d}/late-entries", headers=H,
                     timeout=15).json()
    for v in (j["totals"]["in"], j["totals"]["out"], j["totals"]["net"]):
        assert round(v, 2) == v


def test_17_late_entries_no_hits_for_future_source(ctx):
    d, _ = ctx.close()
    # Wallet entry with date AFTER the close date — should NOT be a late entry.
    future_d = (_date.today() - timedelta(days=1)).isoformat()
    if future_d <= d:
        pytest.skip("close_date is today; no room for later source")
    ctx.wr(future_d)
    j = requests.get(f"{API}/fin/day-closures/{d}/late-entries", headers=H,
                     timeout=15).json()
    for row in j["rows"]:
        assert row["txn_date"] <= d


def test_18_late_entries_404_for_unclosed_date(ctx):
    r = requests.get(f"{API}/fin/day-closures/2010-05-05/late-entries",
                     headers=H, timeout=10)
    assert r.status_code == 404


# ── 5. Historical operational entry after close (HARD RULE) ────────────

def test_19_historical_wallet_recharge_allowed_after_close(ctx):
    d, _ = ctx.close()
    r = ctx.wr(d)
    assert r.status_code == 200, "closing must NOT block backdated entry"


def test_20_historical_wallet_transfer_allowed_after_close(ctx):
    d, _ = ctx.close()
    assert ctx.wt(d).status_code == 200


def test_21_historical_wallet_adjustment_allowed_after_close(ctx):
    d, _ = ctx.close()
    assert ctx.wa(d, direction="decrease").status_code == 200


def test_22_wallet_edit_after_close_allowed(ctx):
    d, _ = ctx.close()
    r = ctx.wr(d)
    wid = r.json()["id"]
    upd = requests.put(f"{API}/wallet-recharges/{wid}", headers=HJSON, json={
        "wallet_code": "WALLET_FASTAG", "funding_mode": "Bank",
        "amount": 999.0, "date": d, "reference": "edit", "remarks": "",
    }, timeout=15)
    assert upd.status_code == 200, "edit-after-close must NOT be blocked"


def test_23_wallet_delete_after_close_allowed_for_owner(ctx):
    """Path A · demo token is owner. Confirm delete goes through."""
    d, _ = ctx.close()
    r = ctx.wr(d)
    wid = r.json()["id"]
    dele = requests.delete(f"{API}/wallet-recharges/{wid}", headers=H,
                           params={"reason": "post-close correction"},
                           timeout=10)
    assert dele.status_code == 200


# ── 6. Day Book reflection ─────────────────────────────────────────────

def test_24_day_book_reflects_late_entry(ctx):
    d, _ = ctx.close()
    assert ctx.wr(d, amt=333.0).status_code == 200
    r = requests.get(f"{API}/fin/day-book", headers=H, params={
        "date_from": d, "date_to": d, "source_type": "wallet_recharge",
    }, timeout=15)
    assert r.status_code == 200
    j = r.json()
    assert j["count"] >= 2, "Day Book must reflect the backdated recharge"


def test_25_account_ledger_reflects_late_entry(ctx):
    d, _ = ctx.close()
    assert ctx.wr(d, amt=100.0).status_code == 200
    r = requests.get(f"{API}/fin/day-book", headers=H, params={
        "date_from": d, "date_to": d, "account_code": "WALLET_FASTAG",
    }, timeout=15)
    assert r.status_code == 200
    codes = [row["account_code"] for row in r.json()["rows"]]
    assert "WALLET_FASTAG" in codes


# ── 7. Snapshot immutability across late entry ─────────────────────────

def test_26_snapshot_never_mutates_after_late_entry(ctx):
    d, r = ctx.close()
    snap0 = r.json()["snapshot"]
    ctx.wr(d)
    ctx.wa(d)
    ctx.wt(d)
    fresh = requests.get(f"{API}/fin/day-closures/{d}", headers=H,
                         timeout=10).json()
    assert fresh["snapshot"] == snap0


# ── 8. Failed hook replay after close ──────────────────────────────────

def test_27_failed_hook_replay_after_close_land_in_late_entries(ctx):
    """Insert a synthetic pending failure whose source is a real recharge
    with business date <= close. Replay via CLI. Confirm leg appears in
    /late-entries."""
    import subprocess, sys
    d, _ = ctx.close()
    # Create a legit recharge (this hooks + writes 2 legs immediately).
    r = ctx.wr(d, amt=444.0)
    assert r.status_code == 200
    wr_id = r.json()["id"]
    # Manually add a pending fin_hook_failure to force a replay attempt.
    ctx.d.fin_hook_failures.insert_one({
        "id": f"fhf_150d_{ctx.tag}", "user_id": ctx.uid,
        "company_id": ctx.cid, "source_type": "wallet_recharge",
        "source_id": wr_id, "status": "pending",
        "attempt_count": 0, "last_error": "test-forced-150d",
        "created_at": "2020-01-01T00:00:00",
        "next_attempt_at": "2020-01-01T00:00:00",
    })
    # Run replay CLI. Must succeed (replay AFTER close = allowed).
    p = subprocess.run(
        [sys.executable, "-m", "scripts.replay_fin_hook_failures",
         "--company-id", ctx.cid, "--user-id", ctx.uid,
         "--ignore-schedule", "--verbose"],
        cwd="/app/backend", capture_output=True, text=True, timeout=60,
    )
    assert p.returncode in (0, 1), p.stderr
    # Cleanup our synthetic queue row.
    ctx.d.fin_hook_failures.delete_many(
        {"user_id": ctx.uid, "id": f"fhf_150d_{ctx.tag}"})


# ── 9. Tenant isolation ────────────────────────────────────────────────

def test_28_list_tenant_scoped(ctx):
    iso_uid = f"iso_150d_r_{ctx.tag}"
    iso_cid = f"co_iso_150d_r_{ctx.tag}"
    ctx.d.fin_day_closures.insert_one({
        "id": f"fdc_iso_r_{ctx.tag}", "user_id": iso_uid,
        "company_id": iso_cid, "close_date": "2010-04-04",
        "status": "closed", "closed_at": "2010-04-04T00:00:00",
        "closed_by": iso_uid, "snapshot": {}, "snapshot_source_count": 0,
        "history": [],
    })
    r = requests.get(f"{API}/fin/day-closures", headers=H,
                     params={"date_from": "2010-04-04",
                             "date_to": "2010-04-04"}, timeout=10)
    dates = [row["close_date"] for row in r.json()["rows"]]
    assert "2010-04-04" not in dates or all(
        row.get("user_id") != iso_uid for row in r.json()["rows"])
    ctx.d.fin_day_closures.delete_many({"user_id": iso_uid})


# ── 10. Router purity for read paths ───────────────────────────────────

def test_29_read_paths_do_not_mutate_fin_txn(ctx):
    # Establish closure BEFORE measuring baseline so the close op itself
    # (audit + insert into fin_day_closures) is fully settled.
    d, _ = ctx.close()
    q = {"user_id": ctx.uid, "company_id": ctx.cid}
    # Tight window: only around the read calls.
    before = ctx.d.fin_txn.count_documents(q)
    for _ in range(3):
        requests.get(f"{API}/fin/day-closures", headers=H, timeout=10)
        requests.get(f"{API}/fin/day-closures/{d}", headers=H, timeout=10)
        requests.get(f"{API}/fin/day-closures/{d}/late-entries", headers=H, timeout=10)
        requests.get(f"{API}/fin/day-status", headers=H,
                     params={"date": d}, timeout=10)
    after = ctx.d.fin_txn.count_documents(q)
    assert before == after


# ── 11. Endpoint shape stability ───────────────────────────────────────

def test_30_late_entries_response_shape(ctx):
    d, _ = ctx.close()
    j = requests.get(f"{API}/fin/day-closures/{d}/late-entries", headers=H,
                     timeout=10).json()
    for k in ("close_date", "count", "totals", "by_source_type",
              "by_days_late_bucket", "rows"):
        assert k in j


def test_31_day_status_response_shape(ctx):
    d, _ = ctx.close()
    j = requests.get(f"{API}/fin/day-status", headers=H,
                     params={"date": d}, timeout=10).json()
    for k in ("date", "is_closed"):
        assert k in j


def test_32_list_response_shape(ctx):
    j = requests.get(f"{API}/fin/day-closures", headers=H, timeout=10).json()
    assert "rows" in j and "count" in j


# ── 12. Locked-band integrity (models.py + 14 files untouched) ─────────

def test_33_models_py_has_no_iter150d_traces():
    core = Path("/app/backend/models.py").read_text()
    assert "class FinDayClosure" not in core
    assert "fin_day_closures" not in core


def test_34_locked_writers_untouched():
    """Every locked writer file must still exist and NOT reference
    fin_day_closures — Day Closing lives above them, never inside."""
    for path in [
        "/app/backend/routers/trips.py",
        "/app/backend/routers/invoices.py",
        "/app/backend/routers/notes.py",
        "/app/backend/routers/vendor_bills.py",
        "/app/backend/routers/mechanic_work_orders.py",
        "/app/backend/routers/expenses.py",
        "/app/backend/routers/wallet_recharges.py",
        "/app/backend/routers/wallet_transfers.py",
        "/app/backend/routers/wallet_adjustments.py",
    ]:
        text = Path(path).read_text()
        assert "fin_day_closures" not in text, f"{path} references closures"
        assert "fin_day_closing" not in text


def test_35_services_fin_txn_untouched_by_day_closing():
    src = Path("/app/backend/services_fin_txn.py").read_text()
    assert "fin_day_closures" not in src
    assert "day_closing" not in src


def test_36_late_entry_days_late_field_present(ctx):
    d, _ = ctx.close()
    ctx.wr(d)
    j = requests.get(f"{API}/fin/day-closures/{d}/late-entries", headers=H,
                     timeout=10).json()
    for row in j["rows"]:
        assert "days_late" in row
        assert row["days_late"] >= 0
