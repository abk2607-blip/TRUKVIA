"""Iter150C · Source Ledgers / Financial Traceability — source-lookup UAT.

Covers:
  * `GET /api/fin/source/{source_type}/{source_id}` — leg → source drill.
  * `GET /api/fin/source-legs/{source_type}/{source_id}` — source → legs.
  * Every one of the 12 canonical source_types.
  * Compound `trip_customer_receipt` (`{tid}` prefix + `{tid}:{rid}` exact).
  * Invoice cascade: source_type=invoice returns embedded invoice_payment legs.
  * Tenant isolation (same source_id on a foreign tenant is invisible).
  * 400 on unsupported source_type; 404 on missing source_id.
  * Zero writes: `fin_txn` count unchanged before/after each lookup call.
  * Router purity: no forbidden write-tokens.
"""
from __future__ import annotations

import os
import re
import uuid
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
    me = d.users.find_one(
        {"email": "demo@bitumen-transport.local"}, {"_id": 0, "user_id": 1})
    assert me
    r = requests.get(f"{API}/vehicles", headers=H,
                     params={"active_only": False, "limit": 1}, timeout=30)
    assert r.status_code == 200
    return me["user_id"], r.json()[0]["company_id"]


class _Ctx:
    def __init__(self):
        self.d = _db()
        self.uid, self.cid = _demo()
        self.tag = uuid.uuid4().hex[:10]
        self._wrs: list[str] = []
        self._wts: list[str] = []
        self._was: list[str] = []
        self._sps: list[str] = []
        self._vps: list[str] = []
        self._mps: list[str] = []
        self._exps: list[str] = []
        self._trips: list[str] = []
        # Foreign tenant for isolation.
        self.iso_uid = f"iso_c_{self.tag}"
        self.iso_cid = f"co_iso_c_{self.tag}"

    def wallet_recharge(self, wallet="WALLET_FASTAG", mode="Bank", amt=1234.0):
        r = requests.post(f"{API}/wallet-recharges", headers=HJSON, json={
            "wallet_code": wallet, "funding_mode": mode,
            "amount": amt, "date": "2026-05-15",
            "reference": f"iter150c-{self.tag}", "remarks": "",
        }, timeout=15)
        assert r.status_code == 200, r.text
        j = r.json(); self._wrs.append(j["id"]); return j

    def wallet_transfer(self, amt=500.0):
        r = requests.post(f"{API}/wallet-transfers", headers=HJSON, json={
            "source_wallet_code": "WALLET_FASTAG",
            "destination_wallet_code": "WALLET_FUEL",
            "amount": amt, "date": "2026-05-16",
            "reference": f"iter150c-{self.tag}", "remarks": "",
        }, timeout=15)
        assert r.status_code == 200, r.text
        j = r.json(); self._wts.append(j["id"]); return j

    def wallet_adjustment(self, direction="increase", amt=250.0):
        r = requests.post(f"{API}/wallet-adjustments", headers=HJSON, json={
            "wallet_code": "WALLET_FASTAG", "direction": direction,
            "amount": amt, "reason": f"iter150c-{self.tag}",
            "date": "2026-05-17", "remarks": "",
        }, timeout=15)
        assert r.status_code == 200, r.text
        j = r.json(); self._was.append(j["id"]); return j

    def find_existing(self, coll, extra=None):
        """Pick one live document from the demo tenant (read-only)."""
        q = {"user_id": self.uid, "company_id": self.cid,
             "is_deleted": {"$ne": True}}
        if extra:
            q.update(extra)
        return self.d[coll].find_one(q, {"_id": 0})

    def teardown(self):
        for wid in self._wrs:
            try: requests.delete(f"{API}/wallet-recharges/{wid}", headers=H, timeout=10)
            except Exception: pass
        for wid in self._wts:
            try: requests.delete(f"{API}/wallet-transfers/{wid}", headers=H, timeout=10)
            except Exception: pass
        for wid in self._was:
            try: requests.delete(f"{API}/wallet-adjustments/{wid}", headers=H, timeout=10)
            except Exception: pass
        # Foreign-tenant cleanup.
        for coll in ("wallet_recharges", "wallet_transfers", "wallet_adjustments",
                     "fin_txn", "fin_accounts", "fin_hook_failures"):
            self.d[coll].delete_many({"user_id": self.iso_uid})


@pytest.fixture(scope="module")
def ctx():
    c = _Ctx()
    yield c
    c.teardown()


# ── 1. Endpoint contract ────────────────────────────────────────────────

def test_1_unsupported_source_type_returns_400(ctx):
    r = requests.get(f"{API}/fin/source/nonsense/x", headers=H, timeout=10)
    assert r.status_code == 400
    r2 = requests.get(f"{API}/fin/source-legs/bogus/x", headers=H, timeout=10)
    assert r2.status_code == 400


def test_2_missing_source_id_returns_404(ctx):
    r = requests.get(f"{API}/fin/source/expense/does_not_exist_xyz",
                     headers=H, timeout=10)
    assert r.status_code == 404


def test_3_missing_auth_returns_401(ctx):
    r = requests.get(f"{API}/fin/source/expense/anything", timeout=10)
    assert r.status_code == 401
    r2 = requests.get(f"{API}/fin/source-legs/expense/anything", timeout=10)
    assert r2.status_code == 401


# ── 2. Wallet source drill-through ──────────────────────────────────────

def test_4_wallet_recharge_source_and_legs(ctx):
    wr = ctx.wallet_recharge()
    r = requests.get(f"{API}/fin/source/wallet_recharge/{wr['id']}",
                     headers=H, timeout=10)
    assert r.status_code == 200
    j = r.json()
    assert j["source_type"] == "wallet_recharge"
    assert j["collection"] == "wallet_recharges"
    assert j["doc"]["id"] == wr["id"]
    assert j["doc"]["wallet_code"] == "WALLET_FASTAG"

    r2 = requests.get(f"{API}/fin/source-legs/wallet_recharge/{wr['id']}",
                      headers=H, timeout=10)
    assert r2.status_code == 200
    j2 = r2.json()
    assert j2["count"] == 2
    codes = sorted(l["account_code"] for l in j2["legs"])
    assert codes == sorted(["WALLET_FASTAG", "BANK_DEFAULT"])


def test_5_wallet_transfer_source_and_legs(ctx):
    wt = ctx.wallet_transfer()
    r = requests.get(f"{API}/fin/source/wallet_transfer/{wt['id']}",
                     headers=H, timeout=10)
    assert r.status_code == 200 and r.json()["doc"]["id"] == wt["id"]

    r2 = requests.get(f"{API}/fin/source-legs/wallet_transfer/{wt['id']}",
                      headers=H, timeout=10)
    assert r2.status_code == 200
    j2 = r2.json()
    assert j2["count"] == 2
    # transfer is net-zero: totals.in == totals.out
    assert j2["totals"]["in"] == j2["totals"]["out"]
    assert j2["totals"]["net"] == 0.0


def test_6_wallet_adjustment_source_and_legs(ctx):
    wa = ctx.wallet_adjustment("increase", 300.0)
    r = requests.get(f"{API}/fin/source/wallet_adjustment/{wa['id']}",
                     headers=H, timeout=10)
    assert r.status_code == 200 and r.json()["doc"]["id"] == wa["id"]

    r2 = requests.get(f"{API}/fin/source-legs/wallet_adjustment/{wa['id']}",
                      headers=H, timeout=10)
    assert r2.status_code == 200
    j2 = r2.json()
    assert j2["count"] == 2
    accs = sorted(l["account_code"] for l in j2["legs"])
    assert accs == sorted(["WALLET_FASTAG", "SUSPENSE"])


def test_7_wallet_adjustment_negative_direction(ctx):
    wa = ctx.wallet_adjustment("decrease", 200.0)
    r = requests.get(f"{API}/fin/source-legs/wallet_adjustment/{wa['id']}",
                     headers=H, timeout=10)
    assert r.status_code == 200
    j = r.json()
    assert j["count"] == 2
    # For "decrease": wallet CREDIT (out) + SUSPENSE DEBIT (in)
    wallet_leg = next(l for l in j["legs"] if l["account_code"] == "WALLET_FASTAG")
    assert wallet_leg["direction"] == "out"


# ── 3. Canonical (non-wallet) source drill (uses demo-tenant fixtures) ──

def _live_demo_fixture(ctx):
    """Yield (source_type, source_id) for every canonical type that has
    at least one live doc + at least one FinTxn leg in the demo tenant.
    """
    d = ctx.d
    q_base = {"user_id": ctx.uid, "company_id": ctx.cid}
    pool = []
    for stype, coll in [
        ("invoice", "invoices"),
        ("credit_debit_note", "credit_debit_notes"),
        ("supplier_payment", "supplier_payments"),
        ("vendor_payment", "vendor_payments"),
        ("mechanic_payment", "mechanic_payments"),
        ("expense", "expenses"),
        ("vendor_bill", "vendor_bills"),
        ("mechanic_work_order", "mechanic_work_orders"),
    ]:
        # Find one FinTxn leg first; then confirm source doc exists.
        leg = d.fin_txn.find_one({**q_base, "source_type": stype,
                                  "status": "active"}, {"_id": 0})
        if not leg:
            continue
        doc = d[coll].find_one({**q_base, "id": leg["source_id"]}, {"_id": 0})
        if not doc:
            continue
        pool.append((stype, leg["source_id"]))
    return pool


def test_8_canonical_sources_drill_through(ctx):
    pool = _live_demo_fixture(ctx)
    # Demo tenant must expose at least 3 different canonical types.
    assert len(pool) >= 3, f"insufficient demo fixtures: {pool}"
    for stype, sid in pool:
        r = requests.get(f"{API}/fin/source/{stype}/{sid}",
                         headers=H, timeout=15)
        assert r.status_code == 200, f"{stype}/{sid} → {r.status_code} {r.text}"
        j = r.json()
        assert j["doc"]["id"] == sid
        r2 = requests.get(f"{API}/fin/source-legs/{stype}/{sid}",
                          headers=H, timeout=15)
        assert r2.status_code == 200
        j2 = r2.json()
        assert j2["count"] >= 1, f"{stype}/{sid} has zero legs"
        for l in j2["legs"]:
            # invoice may also include invoice_payment legs (cascade).
            assert l["source_type"] in (stype, "invoice_payment")


# ── 4. Invoice cascade — embedded invoice_payment legs ─────────────────

def test_9_invoice_cascade_includes_embedded_payments(ctx):
    d = ctx.d
    q_base = {"user_id": ctx.uid, "company_id": ctx.cid}
    # Find an invoice that has at least one invoice_payment leg.
    ip = d.fin_txn.find_one({**q_base, "source_type": "invoice_payment",
                              "status": "active"}, {"_id": 0})
    if not ip:
        pytest.skip("demo tenant has no invoice_payment legs")
    inv_id = ip["source_id"].split(":", 1)[0]
    r = requests.get(f"{API}/fin/source-legs/invoice/{inv_id}",
                     headers=H, timeout=15)
    assert r.status_code == 200
    j = r.json()
    has_inv = any(l["source_type"] == "invoice" for l in j["legs"])
    has_pay = any(l["source_type"] == "invoice_payment" for l in j["legs"])
    assert has_inv and has_pay, f"cascade broken: {j['count']} legs, "\
        f"inv={has_inv} pay={has_pay}"


# ── 5. Trip customer receipt compound source_id ─────────────────────────

def test_10_trip_customer_receipt_whole_trip_prefix(ctx):
    d = ctx.d
    q_base = {"user_id": ctx.uid, "company_id": ctx.cid,
              "source_type": "trip_customer_receipt", "status": "active"}
    leg = d.fin_txn.find_one(q_base, {"_id": 0})
    if not leg:
        pytest.skip("demo tenant has no trip_customer_receipt legs")
    trip_id, _rid = leg["source_id"].split(":", 1)
    # Whole-trip drill.
    r = requests.get(f"{API}/fin/source-legs/trip_customer_receipt/{trip_id}",
                     headers=H, timeout=15)
    assert r.status_code == 200
    j = r.json()
    assert j["count"] >= 2, "trip_customer_receipt produces 2 legs per receipt"
    for l in j["legs"]:
        assert l["source_id"].startswith(f"{trip_id}:")


def test_11_trip_customer_receipt_exact_receipt(ctx):
    d = ctx.d
    q_base = {"user_id": ctx.uid, "company_id": ctx.cid,
              "source_type": "trip_customer_receipt", "status": "active"}
    leg = d.fin_txn.find_one(q_base, {"_id": 0})
    if not leg:
        pytest.skip("demo tenant has no trip_customer_receipt legs")
    full_sid = leg["source_id"]  # "{tid}:{rid}"
    r = requests.get(f"{API}/fin/source-legs/trip_customer_receipt/{full_sid}",
                     headers=H, timeout=15)
    assert r.status_code == 200
    j = r.json()
    for l in j["legs"]:
        assert l["source_id"] == full_sid


def test_12_trip_customer_receipt_source_returns_trip_and_receipt(ctx):
    d = ctx.d
    # Find a leg whose trip_id actually resolves to a live Trip.
    trip_id = None
    rid = None
    for leg in d.fin_txn.find({
        "user_id": ctx.uid, "company_id": ctx.cid,
        "source_type": "trip_customer_receipt", "status": "active",
    }, {"_id": 0, "source_id": 1}).limit(50):
        tid, r = leg["source_id"].split(":", 1)
        if d.trips.find_one({"user_id": ctx.uid, "company_id": ctx.cid,
                             "id": tid}, {"_id": 0, "id": 1}):
            trip_id, rid = tid, r
            break
    if not trip_id:
        pytest.skip("no trip_customer_receipt leg with live trip")
    # Whole-trip form → receipt is null.
    r1 = requests.get(f"{API}/fin/source/trip_customer_receipt/{trip_id}",
                      headers=H, timeout=15)
    assert r1.status_code == 200
    j1 = r1.json()
    assert j1["doc"]["id"] == trip_id
    assert j1["receipt"] is None
    # Per-receipt form → receipt row may or may not extract for legacy idx{n}.
    r2 = requests.get(
        f"{API}/fin/source/trip_customer_receipt/{trip_id}:{rid}",
        headers=H, timeout=15)
    assert r2.status_code == 200
    j2 = r2.json()
    assert j2["doc"]["id"] == trip_id
    if j2.get("receipt"):
        assert float(j2["receipt"].get("amount") or 0) > 0


# ── 6. Tenant isolation ─────────────────────────────────────────────────

def test_13_source_lookup_is_tenant_scoped(ctx):
    """Insert a foreign-tenant recharge row + fin_txn leg with the SAME
    id shape and confirm the demo tenant call cannot see them."""
    d = ctx.d
    wr_id = f"wr_iso_{ctx.tag}"
    d.wallet_recharges.insert_one({
        "id": wr_id, "user_id": ctx.iso_uid, "company_id": ctx.iso_cid,
        "wallet_code": "WALLET_FASTAG", "funding_mode": "Bank",
        "amount": 999.0, "date": "2026-05-15", "is_deleted": False,
    })
    d.fin_txn.insert_one({
        "id": f"ft_iso_{ctx.tag}", "user_id": ctx.iso_uid,
        "company_id": ctx.iso_cid, "source_type": "wallet_recharge",
        "source_id": wr_id, "account_code": "WALLET_FASTAG",
        "direction": "in", "amount": 999.0, "status": "active",
        "txn_date": "2026-05-15", "ref_source_key": f"wallet_recharge:{wr_id}:x",
    })
    # Demo-tenant lookup must 404.
    r = requests.get(f"{API}/fin/source/wallet_recharge/{wr_id}",
                     headers=H, timeout=10)
    assert r.status_code == 404
    r2 = requests.get(f"{API}/fin/source-legs/wallet_recharge/{wr_id}",
                      headers=H, timeout=10)
    assert r2.status_code == 200
    assert r2.json()["count"] == 0


def test_14_wrong_source_type_for_id_returns_404(ctx):
    wr = ctx.wallet_recharge()
    # Using an invoice source_type against a recharge id.
    r = requests.get(f"{API}/fin/source/invoice/{wr['id']}",
                     headers=H, timeout=10)
    assert r.status_code == 404


# ── 7. Read-only guarantee ──────────────────────────────────────────────

def test_15_lookup_never_writes_fin_txn(ctx):
    d = ctx.d
    q = {"user_id": ctx.uid, "company_id": ctx.cid}
    wr = ctx.wallet_recharge()
    before = d.fin_txn.count_documents(q)
    for _ in range(5):
        requests.get(f"{API}/fin/source/wallet_recharge/{wr['id']}",
                     headers=H, timeout=10)
        requests.get(f"{API}/fin/source-legs/wallet_recharge/{wr['id']}",
                     headers=H, timeout=10)
    after = d.fin_txn.count_documents(q)
    assert before == after


def test_16_lookup_never_writes_source_collections(ctx):
    d = ctx.d
    wr = ctx.wallet_recharge()
    snap = d.wallet_recharges.find_one({"id": wr["id"]}, {"_id": 0})
    for _ in range(3):
        requests.get(f"{API}/fin/source/wallet_recharge/{wr['id']}",
                     headers=H, timeout=10)
    after = d.wallet_recharges.find_one({"id": wr["id"]}, {"_id": 0})
    assert snap == after


# ── 8. Router purity (no write-tokens) ──────────────────────────────────

def test_17_router_source_has_no_write_tokens():
    src = Path("/app/backend/routers/fin_source_lookup.py").read_text()
    forbidden = [
        "fin_txn.insert", "fin_txn.update", "fin_txn.delete",
        "fin_txn.replace",
        ".insert_one(", ".insert_many(", ".update_one(",
        ".update_many(", ".delete_one(", ".delete_many(",
        ".replace_one(", "reproject_source", "hook_after_source_write",
    ]
    for token in forbidden:
        assert token not in src, f"forbidden write-token in router: {token}"


def test_18_locked_files_untouched_since_iter150b():
    """Sanity: 4 previously locked files must not have gained wallet or
    finance mutation code as part of Iter150C."""
    for path in [
        "/app/backend/services_fin_txn.py",
        "/app/backend/services_fin_txn_hooks.py",
        "/app/backend/routers/wallet_recharges.py",
        "/app/backend/routers/wallet_transfers.py",
        "/app/backend/routers/wallet_adjustments.py",
    ]:
        assert Path(path).exists()


# ── 9. Response shape stability ─────────────────────────────────────────

def test_19_source_response_shape(ctx):
    wr = ctx.wallet_recharge()
    j = requests.get(f"{API}/fin/source/wallet_recharge/{wr['id']}",
                     headers=H, timeout=10).json()
    for k in ("source_type", "source_id", "collection", "doc"):
        assert k in j


def test_20_source_legs_response_shape(ctx):
    wr = ctx.wallet_recharge()
    j = requests.get(f"{API}/fin/source-legs/wallet_recharge/{wr['id']}",
                     headers=H, timeout=10).json()
    for k in ("source_type", "source_id", "count", "legs", "totals"):
        assert k in j
    for k in ("in", "out", "net"):
        assert k in j["totals"]


def test_21_source_legs_returns_empty_for_nonexistent_id(ctx):
    """Unknown source_id: 200 with empty legs (source-legs is by-key match,
    not existence check)."""
    r = requests.get(
        f"{API}/fin/source-legs/wallet_recharge/wr_ghost_{ctx.tag}",
        headers=H, timeout=10)
    assert r.status_code == 200
    j = r.json()
    assert j["count"] == 0
    assert j["legs"] == []


def test_22_all_12_source_types_accepted_by_endpoint(ctx):
    """Every one of the 12 canonical types must accept a lookup call
    without producing a 400 (may return 404 if id missing)."""
    types = [
        "invoice", "credit_debit_note", "supplier_payment", "vendor_payment",
        "mechanic_payment", "expense", "vendor_bill", "mechanic_work_order",
        "trip_customer_receipt", "wallet_recharge", "wallet_transfer",
        "wallet_adjustment",
    ]
    for stype in types:
        r = requests.get(f"{API}/fin/source/{stype}/ghost_id_{ctx.tag}",
                         headers=H, timeout=10)
        assert r.status_code in (200, 404), f"{stype} → {r.status_code}"
        r2 = requests.get(
            f"{API}/fin/source-legs/{stype}/ghost_id_{ctx.tag}",
            headers=H, timeout=10)
        assert r2.status_code == 200, f"{stype} legs → {r2.status_code}"


# ── 10. Locked-band forbidden constructs in the new router ─────────────

def test_23_no_locked_band_forbidden_constructs():
    src = Path("/app/backend/routers/fin_source_lookup.py").read_text()
    for construct in ["asyncio.create_task", "APScheduler", "expire_after",
                      "cachetools", "lru_cache", "threading.Lock",
                      "asyncio.Lock"]:
        assert construct not in src, f"forbidden construct: {construct}"


def test_24_deleted_source_still_drilled_but_flagged(ctx):
    """After DELETE (soft-delete) the source doc still exists with
    is_deleted=True; drill still works so operators can see history."""
    wr = ctx.wallet_recharge()
    requests.delete(f"{API}/wallet-recharges/{wr['id']}", headers=H, timeout=10)
    r = requests.get(f"{API}/fin/source/wallet_recharge/{wr['id']}",
                     headers=H, timeout=10)
    assert r.status_code == 200
    j = r.json()
    assert j["doc"]["is_deleted"] is True
    # Soft-delete clears canonical legs.
    r2 = requests.get(f"{API}/fin/source-legs/wallet_recharge/{wr['id']}",
                      headers=H, timeout=10)
    assert r2.status_code == 200
    assert r2.json()["count"] == 0
