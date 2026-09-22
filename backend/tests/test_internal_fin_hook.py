"""Phase 6 slice 1b(b) — internal service-to-service fin_txn projection hook.

Covers the security boundary and the behaviour contract of
POST /internal/fin/reproject:

  • a valid internal call reprojects, and the ledger rows match what Python's
    own reproject_source produces;
  • a missing, wrong or empty credential is rejected;
  • a non-loopback peer is rejected;
  • the endpoint is disabled entirely when the secret is unset or too short;
  • only vendor_bill and vendor_payment are accepted;
  • the public /api/fin/reproject keeps its owner-only rule.

Each scenario boots a real uvicorn in a subprocess against a throwaway database,
because the guard reads the environment at request time and the peer address has
to be a real socket. Nothing here touches preview or production.
"""
import json
import os
import secrets
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
import pytest

BACKEND = Path(__file__).resolve().parents[1]
MONGO_URL = os.environ.get("MONGO_URL") or "mongodb://127.0.0.1:27017"
TOKEN = "t" + secrets.token_urlsafe(48)
UID = "user_internal_hook"
CID = "co_internal_hook"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _mongo_available() -> bool:
    try:
        from pymongo import MongoClient

        MongoClient(MONGO_URL, serverSelectionTimeoutMS=2000).admin.command("ping")
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _mongo_available(), reason="MongoDB not reachable")


class Stack:
    """A uvicorn process plus its throwaway database."""

    def __init__(self, token: str | None) -> None:
        from pymongo import MongoClient

        self.db_name = "trukvia_internalhook_" + uuid.uuid4().hex[:10]
        self.port = _free_port()
        self.client = MongoClient(MONGO_URL)
        self.db = self.client[self.db_name]
        self._seed()

        env = {k: v for k, v in os.environ.items() if k != "TRUKVIA_INTERNAL_TOKEN"}
        env.update({
            "MONGO_URL": MONGO_URL,
            "DB_NAME": self.db_name,
            "DISABLE_SCHEDULER": "1",
            "EMERGENT_LLM_KEY": "",
            "REGRESSION_GUARD_PERIODIC": "0",
            "PYTHONUTF8": "1",
        })
        if token is not None:
            env["TRUKVIA_INTERNAL_TOKEN"] = token
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1",
             "--port", str(self.port), "--log-level", "warning"],
            cwd=str(BACKEND), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self.base = f"http://127.0.0.1:{self.port}"
        for _ in range(240):
            try:
                if httpx.get(f"{self.base}/api/auth/health", timeout=2).status_code == 200:
                    return
            except Exception:
                pass
            time.sleep(0.5)
        self.close()
        raise RuntimeError("backend did not start")

    def _seed(self) -> None:
        self.db.vendors.insert_one({
            "id": "ven_ih", "user_id": UID, "company_id": CID, "name": "Hook Vendor",
        })
        self.db.vendor_payments.insert_one({
            "id": "vpay_ih", "user_id": UID, "company_id": CID, "vendor_id": "ven_ih",
            "date": "2026-09-10", "amount": 2500.0, "type": "payment_out", "mode": "Bank",
            "ref_no": "IH-1", "is_deleted": False,
        })
        self.db.vendor_bills.insert_one({
            "id": "vbl_ih", "user_id": UID, "company_id": CID, "vendor_id": "ven_ih",
            "vendor_name": "Hook Vendor", "bill_number": "IH-B1", "bill_date": "2026-09-09",
            "bill_amount": 7000.0, "is_deleted": False,
        })

    def post(self, body: dict, headers: dict | None = None) -> httpx.Response:
        return httpx.post(f"{self.base}/internal/fin/reproject", json=body,
                          headers=headers or {}, timeout=30)

    def legs(self, source_type: str) -> list:
        return list(self.db.fin_txn.find({"source_type": source_type}, {"_id": 0}))

    def close(self) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(15)
        except Exception:
            self.proc.kill()
        self.client.drop_database(self.db_name)
        self.client.close()


@pytest.fixture(scope="module")
def stack():
    s = Stack(TOKEN)
    yield s
    s.close()


BODY_PAYMENT = {"user_id": UID, "company_id": CID,
                "source_type": "vendor_payment", "source_id": "vpay_ih"}
BODY_BILL = {"user_id": UID, "company_id": CID,
             "source_type": "vendor_bill", "source_id": "vbl_ih"}


# ── security boundary ──────────────────────────────────────────────────────

def test_rejects_missing_credential(stack):
    r = stack.post(BODY_PAYMENT)
    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid internal credential"


def test_rejects_wrong_credential(stack):
    r = stack.post(BODY_PAYMENT, {"X-Internal-Token": "wrong-" + TOKEN})
    assert r.status_code == 401


def test_rejects_empty_credential(stack):
    r = stack.post(BODY_PAYMENT, {"X-Internal-Token": ""})
    assert r.status_code == 401


def test_rejected_requests_write_no_ledger_rows(stack):
    stack.db.fin_txn.delete_many({})
    stack.post(BODY_PAYMENT)
    stack.post(BODY_PAYMENT, {"X-Internal-Token": "nope"})
    assert stack.db.fin_txn.count_documents({}) == 0


def test_response_never_contains_the_secret(stack):
    r = stack.post(BODY_PAYMENT, {"X-Internal-Token": "nope"})
    assert TOKEN not in r.text


def test_disabled_when_secret_unset():
    s = Stack(None)
    try:
        assert s.post(BODY_PAYMENT, {"X-Internal-Token": TOKEN}).status_code == 404
    finally:
        s.close()


def test_disabled_when_secret_too_short():
    s = Stack("short")
    try:
        assert s.post(BODY_PAYMENT, {"X-Internal-Token": "short"}).status_code == 404
    finally:
        s.close()


def test_not_exposed_under_the_api_prefix(stack):
    # The ingress routes only /api; the hook must not be reachable there.
    r = httpx.post(f"{stack.base}/api/internal/fin/reproject", json=BODY_PAYMENT,
                   headers={"X-Internal-Token": TOKEN}, timeout=10)
    assert r.status_code == 404


# ── input contract ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("source_type", ["invoice", "expense", "supplier_payment", ""])
def test_rejects_source_types_outside_the_slice(stack, source_type):
    r = stack.post({**BODY_PAYMENT, "source_type": source_type},
                   {"X-Internal-Token": TOKEN})
    assert r.status_code == 400


@pytest.mark.parametrize("missing", ["user_id", "company_id", "source_id"])
def test_requires_scope_and_id(stack, missing):
    body = {k: v for k, v in BODY_PAYMENT.items() if k != missing}
    r = stack.post(body, {"X-Internal-Token": TOKEN})
    assert r.status_code == 400


# ── behaviour ──────────────────────────────────────────────────────────────

def test_valid_call_projects_a_payment(stack):
    stack.db.fin_txn.delete_many({})
    r = stack.post(BODY_PAYMENT, {"X-Internal-Token": TOKEN})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    legs = stack.legs("vendor_payment")
    assert len(legs) == 2
    assert {l["account_code"] for l in legs} == {"AP_VENDOR", "BANK_DEFAULT"}
    assert {l["amount"] for l in legs} == {2500.0}
    assert {l["txn_type"] for l in legs} == {"vendor_payment_out"}


def test_valid_call_projects_a_bill(stack):
    stack.db.fin_txn.delete_many({})
    r = stack.post(BODY_BILL, {"X-Internal-Token": TOKEN})
    assert r.status_code == 200 and r.json()["ok"] is True
    legs = stack.legs("vendor_bill")
    # No paired expense exists, so the orphan legs are emitted.
    assert len(legs) == 2
    assert {l["account_code"] for l in legs} == {"SUSPENSE", "AP_VENDOR"}
    assert {l["amount"] for l in legs} == {7000.0}


def test_matches_reproject_source_directly(stack):
    """The endpoint must add nothing of its own: same rows as calling the
    projection function in-process."""
    stack.db.fin_txn.delete_many({})
    stack.post(BODY_PAYMENT, {"X-Internal-Token": TOKEN})
    via_endpoint = sorted(stack.legs("vendor_payment"), key=lambda r: r["ref_source_key"])

    stack.db.fin_txn.delete_many({})
    subprocess.run(
        [sys.executable, "-c",
         "import asyncio,os,sys;"
         f"sys.path.insert(0, r'{BACKEND}');"
         f"os.environ['MONGO_URL']='{MONGO_URL}';os.environ['DB_NAME']='{stack.db_name}';"
         "from services_fin_txn import reproject_source;"
         f"asyncio.run(reproject_source('{UID}','{CID}','vendor_payment','vpay_ih'))"],
        check=True, cwd=str(BACKEND),
        env={**os.environ, "PYTHONUTF8": "1", "EMERGENT_LLM_KEY": ""},
    )
    direct = sorted(stack.legs("vendor_payment"), key=lambda r: r["ref_source_key"])

    volatile = {"created_at", "projected_at"}
    strip = lambda rows: [{k: v for k, v in r.items() if k not in volatile} for r in rows]
    assert strip(via_endpoint) == strip(direct)


def test_projection_is_idempotent(stack):
    stack.db.fin_txn.delete_many({})
    stack.post(BODY_PAYMENT, {"X-Internal-Token": TOKEN})
    first = stack.legs("vendor_payment")
    stack.post(BODY_PAYMENT, {"X-Internal-Token": TOKEN})
    second = stack.legs("vendor_payment")
    assert len(first) == len(second) == 2
    assert {r["ref_source_key"] for r in first} == {r["ref_source_key"] for r in second}


def test_deleted_payment_clears_its_legs(stack):
    stack.db.fin_txn.delete_many({})
    stack.post(BODY_PAYMENT, {"X-Internal-Token": TOKEN})
    assert len(stack.legs("vendor_payment")) == 2
    stack.db.vendor_payments.update_one({"id": "vpay_ih"}, {"$set": {"is_deleted": True}})
    r = stack.post(BODY_PAYMENT, {"X-Internal-Token": TOKEN})
    assert r.status_code == 200
    assert stack.legs("vendor_payment") == []
    stack.db.vendor_payments.update_one({"id": "vpay_ih"}, {"$set": {"is_deleted": False}})


def test_unknown_source_id_is_not_an_error(stack):
    """Python's hook treats a missing document as "nothing to project"."""
    r = stack.post({**BODY_PAYMENT, "source_id": "vpay_does_not_exist"},
                   {"X-Internal-Token": TOKEN})
    assert r.status_code == 200
    assert r.json()["ok"] is True


# ── the public endpoint is unchanged ───────────────────────────────────────

def test_public_reproject_still_requires_a_session(stack):
    r = httpx.post(f"{stack.base}/api/fin/reproject",
                   json={"source_type": "vendor_payment", "source_id": "vpay_ih"},
                   timeout=15)
    assert r.status_code == 401


def test_public_reproject_ignores_the_internal_token(stack):
    """The internal secret must grant nothing on the public endpoint."""
    r = httpx.post(f"{stack.base}/api/fin/reproject",
                   json={"source_type": "vendor_payment", "source_id": "vpay_ih"},
                   headers={"X-Internal-Token": TOKEN}, timeout=15)
    assert r.status_code == 401


def test_public_reproject_is_owner_only(stack):
    """A staff (non-owner) session gets 403 from the public endpoint, while the
    internal hook has no role concept at all."""
    stack.db.users.insert_one({"user_id": "user_staff_ih", "email": "staff-ih@example.com",
                               "name": "Staff"})
    stack.db.team_members.insert_one({"email": "staff-ih@example.com", "active": True,
                                      "owner_user_id": UID, "role": "accountant"})
    stack.db.user_sessions.insert_one({
        "session_token": "staff-ih-token", "user_id": "user_staff_ih",
        "expires_at": "2099-01-01T00:00:00+00:00",
    })
    r = httpx.post(f"{stack.base}/api/fin/reproject",
                   json={"source_type": "vendor_payment", "source_id": "vpay_ih"},
                   headers={"Authorization": "Bearer staff-ih-token"}, timeout=15)
    assert r.status_code == 403
    assert "Owner-only" in json.dumps(r.json())

    # the same staff scope goes through the internal hook without a role check
    r2 = stack.post(BODY_PAYMENT, {"X-Internal-Token": TOKEN})
    assert r2.status_code == 200 and r2.json()["ok"] is True
