"""Iter132c-agg-fix · H1 · `/reports/ledger` streaming rewrite regression.

Verifies that the streaming `async for` rewrite (replacing the pre-existing
`to_list(2000)` truncation) returns the correct ledger for customers with
more than 2,000 invoices, while preserving byte-identical response contract
and existing opening-balance semantics.

Test isolation strategy:
  * Every test uses a fresh customer created via `POST /api/customers`.
  * T2 additionally seeds ~2,100 invoice documents directly into Mongo
    into a unique test namespace so it can prove the >2000 truncation is
    gone. The seed is a test-only shortcut — the ledger API itself is
    still exercised end-to-end. Cleanup is guaranteed via `finally`, and
    a post-cleanup assertion confirms zero orphan test docs remain.

Scope discipline:
  * No CN/DN rows are added to the ledger in this slice (explicit user
    directive). Ledger continues to show only raw invoice/payment rows.
"""
import os
import uuid
import asyncio
import httpx
import motor.motor_asyncio

BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = BASE + "/api"
HDR = {"Authorization": f"Bearer {os.environ['DEMO_TOKEN_VALUE']}"}


# ─── Helpers ────────────────────────────────────────────────────────────

def _company_header():
    companies = httpx.get(f"{API}/companies", headers=HDR, timeout=15).json()
    cid = companies[0]["id"]
    return cid, {**HDR, "X-Company-Id": cid}


def _fresh_customer(h) -> str:
    tag = uuid.uuid4().hex[:8]
    r = httpx.post(f"{API}/customers", headers=h, json={
        "name": f"H1-Ledger-Test-{tag}",
        "phone": f"9{tag[:9]}",
        "email": f"{tag}@iter132c-aggfix.test",
        "state": "Andhra Pradesh",
    }, timeout=15)
    assert r.status_code == 200, f"customer create failed: {r.text[:200]}"
    return r.json()["id"]


def _create_invoice_via_api(h, cust_id, date="2026-06-01", tag_suffix=""):
    """End-to-end invoice creation through the real API."""
    tag = uuid.uuid4().hex[:6] + tag_suffix
    tr = httpx.post(f"{API}/trips", headers=h, json={
        "customer_id": cust_id, "date": date,
        "vehicle_number": f"H1{tag[:4].upper()}",
        "tons": 20, "loaded_qty": 20, "unloaded_qty": 20,
        "freight_mode": "per_ton", "rate_per_ton": 900,
        "product_rate_per_mt": 40000,
        "from_location": "A", "to_location": "B",
        "loading_date": date, "unloading_date": date,
    }, timeout=15)
    assert tr.status_code == 200, tr.text
    inv = httpx.post(f"{API}/invoices", headers=h, json={
        "customer_id": cust_id, "trip_ids": [tr.json()["id"]],
        "invoice_date": date, "rcm": True,
    }, timeout=15)
    assert inv.status_code == 200, inv.text
    return inv.json()


def _current_uid() -> str:
    """Fetch the authenticated user_id via /api/auth/me (the `GET /api/companies`
    response does NOT carry `user_id`)."""
    r = httpx.get(f"{API}/auth/me", headers=HDR, timeout=15)
    assert r.status_code == 200, f"/auth/me failed: {r.status_code} {r.text[:200]}"
    return r.json()["user_id"]


def _add_payment_via_api(h, invoice_id, amount, date):
    r = httpx.post(f"{API}/invoices/{invoice_id}/payments", headers=h, json={
        "amount": amount, "date": date, "mode": "Bank", "note": "H1 test payment",
    }, timeout=15)
    assert r.status_code == 200, r.text


# ─── T1 · Ground-truth semantic parity (small dataset) ──────────────────

def test_t1_ledger_matches_mongo_ground_truth_for_small_customer():
    """Small dataset — endpoint totals must match a Mongo $group aggregation
    over the same customer's invoices/payments. Proves streaming rewrite is
    semantic-equivalent to the old to_list-based code for datasets ≤ 2000."""
    cid, h = _company_header()
    cust_id = _fresh_customer(h)

    invoices = []
    for i, date in enumerate([
        "2026-01-05", "2026-02-10", "2026-03-15", "2026-04-20", "2026-05-25",
    ]):
        invoices.append(_create_invoice_via_api(h, cust_id, date=date, tag_suffix=str(i)))

    # Add a payment on one invoice
    _add_payment_via_api(h, invoices[0]["id"], 500.0, "2026-02-01")

    # Ledger endpoint (no date range → full history)
    r = httpx.get(f"{API}/reports/ledger", headers=h,
                  params={"customer_id": cust_id}, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()

    # Ground truth via Mongo $group over the same customer_id
    async def _gt():
        c = motor.motor_asyncio.AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = c[os.environ["DB_NAME"]]
        gt_billed = 0.0
        gt_paid = 0.0
        gt_inv_count = 0
        gt_pay_count = 0
        async for inv in db.invoices.find({"customer_id": cust_id, "company_id": cid}):
            gt_billed += float(inv.get("total_amount", 0))
            gt_inv_count += 1
            for p in inv.get("payments", []):
                gt_paid += float(p.get("amount", 0))
                gt_pay_count += 1
        c.close()
        return gt_billed, gt_paid, gt_inv_count, gt_pay_count
    gt_billed, gt_paid, gt_inv_count, gt_pay_count = asyncio.run(_gt())

    assert abs(body["total_debit"] - gt_billed) < 0.01, \
        f"total_debit mismatch: endpoint={body['total_debit']} mongo={gt_billed}"
    assert abs(body["total_credit"] - gt_paid) < 0.01, \
        f"total_credit mismatch: endpoint={body['total_credit']} mongo={gt_paid}"
    assert abs(body["closing_balance"] - (gt_billed - gt_paid)) < 0.01, \
        f"closing_balance mismatch"
    # Entry count must equal invoices + payments
    assert len(body["entries"]) == gt_inv_count + gt_pay_count, \
        f"entries count mismatch: {len(body['entries'])} vs {gt_inv_count + gt_pay_count}"


# ─── T2 · Core H1 regression — >2000 invoices, direct Mongo seed ────────

def test_t2_ledger_handles_customer_with_over_2000_invoices():
    """Seeds 2100 invoice docs directly into Mongo for a fresh customer, then
    exercises the REAL ledger endpoint and asserts no truncation.

    Direct-seed rationale: creating 2100 invoices through the API would take
    ~35 minutes because each invoice requires a preceding trip and multiple
    computations. Direct Mongo insert is a test-only shortcut that mimics
    the invoice schema exactly. Guaranteed cleanup via finally.
    """
    cid, h = _company_header()
    cust_id = _fresh_customer(h)
    # Fetch uid so seeded docs pass the endpoint's user_id filter
    uid = _current_uid()

    SEED_COUNT = 2100
    seed_tag = f"H1TEST-{uuid.uuid4().hex[:10]}"

    async def _seed():
        c = motor.motor_asyncio.AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = c[os.environ["DB_NAME"]]
        docs = []
        for i in range(SEED_COUNT):
            docs.append({
                "id": f"{seed_tag}-inv-{i:04d}",
                "user_id": uid,
                "company_id": cid,
                "customer_id": cust_id,
                "invoice_number": f"{seed_tag}/{i:04d}",
                "invoice_date": "2026-01-15",  # keep in-range for a broad query
                "total_amount": 100.0,
                "amount_paid": 0.0,
                "balance_due": 100.0,
                "trip_ids": [],
                "payments": [],
                "is_historical": False,
                "seed_tag": seed_tag,  # for guaranteed cleanup query
            })
        # Insert in reasonable batches to keep memory low
        for i in range(0, len(docs), 500):
            await db.invoices.insert_many(docs[i:i + 500])
        c.close()

    async def _cleanup_and_verify():
        c = motor.motor_asyncio.AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = c[os.environ["DB_NAME"]]
        res = await db.invoices.delete_many({"seed_tag": seed_tag})
        remaining = await db.invoices.count_documents({"seed_tag": seed_tag})
        c.close()
        return res.deleted_count, remaining

    try:
        asyncio.run(_seed())

        r = httpx.get(f"{API}/reports/ledger", headers=h,
                      params={"customer_id": cust_id}, timeout=60)
        assert r.status_code == 200, r.text
        body = r.json()

        # NO truncation: every seeded invoice must appear as an entry.
        assert len(body["entries"]) == SEED_COUNT, \
            f"ledger truncated: got {len(body['entries'])} entries, expected {SEED_COUNT}"
        # Aggregate correctness
        expected_debit = round(SEED_COUNT * 100.0, 2)
        assert abs(body["total_debit"] - expected_debit) < 0.01, \
            f"total_debit={body['total_debit']} expected={expected_debit}"
        assert abs(body["total_credit"] - 0.0) < 0.01
        assert abs(body["closing_balance"] - expected_debit) < 0.01, \
            f"closing_balance={body['closing_balance']} expected={expected_debit}"
        # Running balance on the last entry must equal grand total
        assert abs(body["entries"][-1]["balance"] - expected_debit) < 0.01
    finally:
        deleted, remaining = asyncio.run(_cleanup_and_verify())
        assert remaining == 0, \
            f"CLEANUP FAILED: {remaining} test docs still in DB (deleted {deleted})"


# ─── T3 · Opening-balance semantic preservation ─────────────────────────

def test_t3_ledger_opening_balance_correct_with_pre_start_invoices_and_payments():
    """Pre-start invoices contribute +total to opening; pre-start payments
    contribute -amount to opening — regardless of parent-invoice date. This
    is the exact semantic the pre-Iter132c-agg-fix code implemented; the
    streaming rewrite MUST preserve it."""
    cid, h = _company_header()
    cust_id = _fresh_customer(h)
    uid = _current_uid()

    seed_tag = f"H1T3-{uuid.uuid4().hex[:8]}"

    async def _seed():
        c = motor.motor_asyncio.AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = c[os.environ["DB_NAME"]]
        docs = []
        # 3 pre-start invoices (dated 2025-12-*) + 2 in-range invoices (dated 2026-01-*)
        for i, (date, total) in enumerate([
            ("2025-12-05", 1000.0),
            ("2025-12-15", 500.0),
            ("2025-12-25", 2000.0),
            ("2026-01-05", 800.0),
            ("2026-01-20", 1200.0),
        ]):
            payments = []
            # Attach a pre-start payment to the FIRST invoice
            if i == 0:
                payments.append({"amount": 400.0, "date": "2025-12-20", "mode": "Cash", "note": "pre-start"})
            # Attach an in-range payment to the LAST invoice
            if i == 4:
                payments.append({"amount": 100.0, "date": "2026-01-25", "mode": "Bank", "note": "in-range"})
            docs.append({
                "id": f"{seed_tag}-inv-{i}",
                "user_id": uid,
                "company_id": cid,
                "customer_id": cust_id,
                "invoice_number": f"{seed_tag}/{i:02d}",
                "invoice_date": date,
                "total_amount": total,
                "amount_paid": sum(p["amount"] for p in payments),
                "balance_due": total - sum(p["amount"] for p in payments),
                "trip_ids": [],
                "payments": payments,
                "is_historical": False,
                "seed_tag": seed_tag,
            })
        await db.invoices.insert_many(docs)
        c.close()

    async def _cleanup_and_verify():
        c = motor.motor_asyncio.AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = c[os.environ["DB_NAME"]]
        res = await db.invoices.delete_many({"seed_tag": seed_tag})
        remaining = await db.invoices.count_documents({"seed_tag": seed_tag})
        c.close()
        return res.deleted_count, remaining

    try:
        asyncio.run(_seed())

        r = httpx.get(f"{API}/reports/ledger", headers=h, params={
            "customer_id": cust_id,
            "start": "2026-01-01", "end": "2026-01-31",
        }, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()

        # Opening = Σ pre-start invoices (1000+500+2000=3500) − Σ pre-start payments (400)
        expected_opening = 3500.0 - 400.0
        assert abs(body["opening_balance"] - expected_opening) < 0.01, \
            f"opening_balance={body['opening_balance']} expected={expected_opening}"

        # Entries = 2 in-range invoices + 1 in-range payment = 3
        assert len(body["entries"]) == 3, \
            f"entries count={len(body['entries'])} expected 3"
        # Totals in-range: debit = 800+1200 = 2000; credit = 100
        assert abs(body["total_debit"] - 2000.0) < 0.01
        assert abs(body["total_credit"] - 100.0) < 0.01
        # Closing = opening + in-range debit - in-range credit = 3100 + 2000 - 100 = 5000
        assert abs(body["closing_balance"] - 5000.0) < 0.01, \
            f"closing_balance={body['closing_balance']} expected=5000"
    finally:
        deleted, remaining = asyncio.run(_cleanup_and_verify())
        assert remaining == 0, f"CLEANUP FAILED: {remaining} docs left"


# ─── T4 · PDF consumer still works after JSON streaming rewrite ─────────

def test_t4_ledger_pdf_reuse_works_after_streaming_rewrite():
    """The PDF endpoint re-calls report_ledger() and passes its dict to
    build_ledger_pdf(). This proves that consumer still produces a valid PDF."""
    cid, h = _company_header()
    cust_id = _fresh_customer(h)
    _create_invoice_via_api(h, cust_id, date="2026-06-01", tag_suffix="pdfA")
    _create_invoice_via_api(h, cust_id, date="2026-06-10", tag_suffix="pdfB")
    _create_invoice_via_api(h, cust_id, date="2026-06-20", tag_suffix="pdfC")

    r = httpx.get(f"{API}/reports/ledger/pdf", headers=h,
                  params={"customer_id": cust_id}, timeout=30)
    assert r.status_code == 200, r.text
    assert r.headers.get("content-type", "").startswith("application/pdf")
    assert len(r.content) > 2000, f"PDF suspiciously small: {len(r.content)} bytes"
