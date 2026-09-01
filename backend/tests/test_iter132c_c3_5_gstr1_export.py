"""Iter132c C3.5 · GSTR-1 §9A Export Parity — targeted test suite.

Contract (LOCKED before impl):
  * The existing /api/reports/gstr1 endpoint keeps its Iter127a keys and
    row shape (additive-only for new fields).
  * JSON, XLSX, PDF are PURE PROJECTIONS of the same _gstr1_payload().
    UI ≡ JSON ≡ XLSX ≡ PDF for the same month.
  * Streaming Mongo cursor + $in customer preload — NO to_list() caps
    on invoices or customers. 10k invoices must render successfully.
  * Reconciliation is fail-loud: endpoint totals must equal Mongo
    $group ground truth over the same filter.
  * The existing CSV workflow is preserved (frontend-only, not tested
    here directly; the JSON body it consumes is verified to keep the
    same row shape).
  * B2CL / HSN / Docs / Amendments are OUT OF SCOPE — no new statutory
    calculations. Verified via schema check.
  * Bill-To (customer) drives POS. Ship-To must NOT silently replace
    it — verified by seeding a customer with state != trip.to_location.
"""
import os
import io
import uuid
import time
import httpx
import openpyxl
import fitz
from datetime import datetime, timezone

BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = BASE + "/api"
HDR = {"Authorization": f"Bearer {os.environ['DEMO_TOKEN_VALUE']}"}


# ─── Helpers ──────────────────────────────────────────────────────────────

def _company_header():
    r = httpx.get(f"{API}/companies", headers=HDR, timeout=15)
    assert r.status_code == 200, r.text
    cid = r.json()[0]["id"]
    return cid, {**HDR, "X-Company-Id": cid}


def _current_uid() -> str:
    r = httpx.get(f"{API}/auth/me", headers=HDR, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["user_id"]


def _fake_gstin(state_prefix: str) -> str:
    hx = uuid.uuid4().hex.upper()
    letters_pool = "".join(c for c in hx if c.isalpha()) + "AAAAAAAA"
    digits_pool = "".join(c for c in hx if c.isdigit()) + "00000000"
    letters5 = letters_pool[:5]
    digits4 = digits_pool[:4]
    letter1 = letters_pool[5]
    entity = hx[10]
    checksum = hx[11]
    return f"{state_prefix}{letters5}{digits4}{letter1}{entity}Z{checksum}"


def _fresh_customer(h, *, gstin: str = "", state: str = "Telangana"):
    tag = uuid.uuid4().hex[:8]
    body = {
        "name": f"C3.5-Cust-{tag}",
        "phone": f"9{tag[:9]}",
        "email": f"{tag}@iter132c-c3-5.test",
        "state": state,
    }
    if gstin:
        body["gstin"] = gstin
    r = httpx.post(f"{API}/customers", headers=h, json=body, timeout=15)
    assert r.status_code == 200, f"customer create failed: {r.text[:400]}"
    return r.json()["id"]


def _create_invoice_via_api(h, cust_id, *, date, freight_rate=900, tons=20,
                            product_rate=40000, gst_type="cgst_sgst", rcm=True):
    tag = uuid.uuid4().hex[:6]
    tr = httpx.post(f"{API}/trips", headers=h, json={
        "customer_id": cust_id, "date": date,
        "vehicle_number": f"CX{tag[:4].upper()}",
        "tons": tons, "loaded_qty": tons, "unloaded_qty": tons,
        "freight_mode": "per_ton", "rate_per_ton": freight_rate,
        "product_rate_per_mt": product_rate,
        "from_location": "A", "to_location": "B",
        "loading_date": date, "unloading_date": date,
    }, timeout=15)
    assert tr.status_code == 200, tr.text
    inv = httpx.post(f"{API}/invoices", headers=h, json={
        "customer_id": cust_id, "trip_ids": [tr.json()["id"]],
        "invoice_date": date, "rcm": rcm, "gst_type": gst_type,
    }, timeout=15)
    assert inv.status_code == 200, inv.text
    return inv.json()


def _get_ui(h, month):
    return httpx.get(f"{API}/reports/gstr1", headers=h,
                     params={"month": month}, timeout=120)


def _get_json(h, month):
    return httpx.get(f"{API}/reports/gstr1.json", headers=h,
                     params={"month": month}, timeout=120)


def _get_xlsx(h, month):
    return httpx.get(f"{API}/reports/gstr1.xlsx", headers=h,
                     params={"month": month}, timeout=180)


def _get_pdf(h, month):
    return httpx.get(f"{API}/reports/gstr1.pdf", headers=h,
                     params={"month": month}, timeout=180)


# ─── T1-T3 · Existing-shape preservation (additive-only) ────────────────

EXISTING_IT127A_KEYS = {
    "month", "period", "company_state", "company_state_code",
    "b2b", "b2c", "by_state", "totals", "invoice_count",
}


def test_t1_existing_shape_keys_preserved():
    """/reports/gstr1 must still return the 9 Iter127a keys unchanged."""
    _, h = _company_header()
    r = _get_ui(h, "2026-08")
    assert r.status_code == 200, r.text
    d = r.json()
    for k in EXISTING_IT127A_KEYS:
        assert k in d, f"existing key {k} disappeared"
    # Row shape check — every b2b row must carry the Iter127a keys.
    row_keys = {"invoice_number", "invoice_date", "customer_name", "gstin",
                "state", "state_code", "place_of_supply", "reverse_charge",
                "taxable_value", "cgst", "sgst", "igst", "total", "gst_type"}
    for r_ in (d.get("b2b") or [])[:1]:
        assert row_keys.issubset(r_.keys()), \
            f"b2b row missing keys: {row_keys - set(r_.keys())}"


def test_t2_additive_fields_appended():
    """New additive fields exist (issuer_gstin, reconciliation, warnings)."""
    _, h = _company_header()
    d = _get_ui(h, "2026-08").json()
    for k in ("company_id", "company_name", "issuer_gstin",
              "reconciliation", "warnings"):
        assert k in d, f"additive key missing: {k}"
    assert isinstance(d["warnings"], list)
    assert isinstance(d["reconciliation"], dict)
    for rk in ("endpoint_invoice_count", "ground_truth_invoice_count",
               "endpoint_total", "ground_truth_total",
               "endpoint_taxable", "ground_truth_taxable", "reconciled"):
        assert rk in d["reconciliation"], f"reconciliation missing {rk}"


def test_t3_no_out_of_scope_statutory_sections():
    """C3.5 must not silently invent B2CL / HSN / Docs / Amendment
    sheets in the payload — those are backlog items."""
    _, h = _company_header()
    d = _get_ui(h, "2026-08").json()
    for k in ("b2cl", "hsn_summary", "docs_summary", "amendments"):
        assert k not in d, f"out-of-scope key {k} present in payload"


# ─── T4-T6 · JSON endpoint ───────────────────────────────────────────────

def test_t4_json_endpoint_reachable_and_content_type():
    _, h = _company_header()
    r = _get_json(h, "2026-08")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/json")
    assert "attachment" in r.headers["content-disposition"]
    assert ".json" in r.headers["content-disposition"]


def test_t5_json_equals_ui_endpoint_body():
    """Downloadable JSON body must equal the on-screen JSON body."""
    _, h = _company_header()
    ui = _get_ui(h, "2026-08").json()
    dl = _get_json(h, "2026-08").json()
    assert ui == dl, "JSON download drifted from UI JSON"


def test_t6_json_bad_month_400():
    _, h = _company_header()
    r = _get_json(h, "not-a-month")
    assert r.status_code == 400


# ─── T7-T10 · XLSX endpoint & parity ─────────────────────────────────────

def test_t7_xlsx_endpoint_reachable_and_content_type():
    _, h = _company_header()
    r = _get_xlsx(h, "2026-08")
    assert r.status_code == 200
    assert r.headers["content-type"] == \
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert "attachment" in r.headers["content-disposition"]
    assert ".xlsx" in r.headers["content-disposition"]


def test_t8_xlsx_has_four_sheets_named_correctly():
    _, h = _company_header()
    r = _get_xlsx(h, "2026-08")
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["Summary", "B2B", "B2C", "By_State"]


def test_t9_xlsx_row_counts_match_json():
    _, h = _company_header()
    j = _get_json(h, "2026-08").json()
    r = _get_xlsx(h, "2026-08")
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    # header row is 4, data starts at 5 → data rows = max_row - 4 (if data exists)
    b2b_rows = max(wb["B2B"].max_row - 4, 0)
    b2c_rows = max(wb["B2C"].max_row - 4, 0)
    bs_rows  = max(wb["By_State"].max_row - 4, 0)
    assert b2b_rows == len(j["b2b"]), \
        f"XLSX B2B rows {b2b_rows} != JSON {len(j['b2b'])}"
    assert b2c_rows == len(j["b2c"]), \
        f"XLSX B2C rows {b2c_rows} != JSON {len(j['b2c'])}"
    assert bs_rows == len(j["by_state"]), \
        f"XLSX By_State rows {bs_rows} != JSON {len(j['by_state'])}"


def test_t10_xlsx_summary_totals_equal_json_totals():
    """Summary cells must match JSON totals to 2 decimals."""
    _, h = _company_header()
    j = _get_json(h, "2026-08").json()
    r = _get_xlsx(h, "2026-08")
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    ws = wb["Summary"]
    # Rows 5..10: Invoices, Taxable, CGST, SGST, IGST, Grand Total (col 2)
    got_inv = ws.cell(5, 2).value
    got_taxable = ws.cell(6, 2).value
    got_total = ws.cell(10, 2).value
    assert int(got_inv) == int(j["invoice_count"])
    assert abs(float(got_taxable) - float(j["totals"]["taxable"])) < 0.01
    assert abs(float(got_total)   - float(j["totals"]["total"]))   < 0.01


# ─── T11-T13 · PDF endpoint & parity ─────────────────────────────────────

def test_t11_pdf_endpoint_reachable_and_content_type():
    _, h = _company_header()
    r = _get_pdf(h, "2026-08")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert "GSTR1_" in r.headers["content-disposition"]


def test_t12_pdf_multi_page_with_page_x_of_y():
    """Dense month must produce multi-page PDF with 'Page X of Y' on
    every page (fresh-flowable two-pass footer)."""
    _, h = _company_header()
    r = _get_pdf(h, "2026-08")
    d = fitz.open(stream=r.content, filetype="pdf")
    assert d.page_count > 1, f"expected multi-page, got {d.page_count}"
    for i, page in enumerate(d):
        txt = page.get_text()
        assert f"Page {i+1} of {d.page_count}" in txt, \
            f"page {i+1} missing 'Page X of Y' footer"


def test_t13_pdf_totals_match_json():
    """PDF Summary totals must match JSON totals via text extraction."""
    _, h = _company_header()
    j = _get_json(h, "2026-08").json()
    r = _get_pdf(h, "2026-08")
    d = fitz.open(stream=r.content, filetype="pdf")
    first = d[0].get_text()
    # Grand total is rendered as e.g. "327,389,893.00" — search formatted num.
    total_str = f"{float(j['totals']['total']):,.2f}"
    assert total_str in first, \
        f"Grand total {total_str} not found on PDF page 1 (text sample: {first[:400]})"


# ─── T14-T15 · Empty period edge case ───────────────────────────────────

def test_t14_empty_period_all_three_exports_render():
    _, h = _company_header()
    # Pick a far-future month with no data.
    month = "2035-01"
    j = _get_json(h, month)
    x = _get_xlsx(h, month)
    p = _get_pdf(h, month)
    assert j.status_code == 200 and x.status_code == 200 and p.status_code == 200
    jd = j.json()
    assert jd["invoice_count"] == 0
    assert jd["totals"]["total"] == 0.0
    # XLSX still has 4 sheets even when empty.
    wb = openpyxl.load_workbook(io.BytesIO(x.content))
    assert set(wb.sheetnames) == {"Summary", "B2B", "B2C", "By_State"}
    # PDF still opens.
    fitz.open(stream=p.content, filetype="pdf").close()


def test_t15_bad_month_400_across_endpoints():
    _, h = _company_header()
    for kind in ("gstr1", "gstr1.json", "gstr1.xlsx", "gstr1.pdf"):
        r = httpx.get(f"{API}/reports/{kind}", headers=h,
                      params={"month": "invalid"}, timeout=30)
        assert r.status_code == 400, f"{kind}: expected 400, got {r.status_code}"


# ─── T16 · Reconciliation ────────────────────────────────────────────────

def test_t16_reconciliation_is_true_and_matches_ground_truth():
    _, h = _company_header()
    d = _get_ui(h, "2026-08").json()
    rc = d["reconciliation"]
    assert rc["reconciled"] is True
    assert rc["endpoint_invoice_count"] == rc["ground_truth_invoice_count"]
    assert abs(rc["endpoint_total"] - rc["ground_truth_total"]) < 0.01
    assert abs(rc["endpoint_taxable"] - rc["ground_truth_taxable"]) < 0.01
    # Also verify Σ(by_state) == totals.
    bs_taxable = round(sum(s["taxable"] for s in d["by_state"]), 2)
    assert abs(bs_taxable - d["totals"]["taxable"]) < 0.01


# ─── T17 · Bill-To (customer.state) drives POS (not ship-to) ────────────

def test_t17_pos_uses_customer_state_not_ship_to():
    """POS must match customer.state and NOT trip.to_location.

    Seed: customer state=Karnataka; trip to_location='Somewhere-Else'.
    Assert: the emitted b2b/b2c row's `state` == 'Karnataka'.
    """
    _, h = _company_header()
    tag = uuid.uuid4().hex[:6]
    cust = _fresh_customer(h, state="Karnataka", gstin=_fake_gstin("29"))
    date = f"2026-05-15"
    tr = httpx.post(f"{API}/trips", headers=h, json={
        "customer_id": cust, "date": date,
        "vehicle_number": f"C5{tag[:4].upper()}",
        "tons": 10, "loaded_qty": 10, "unloaded_qty": 10,
        "freight_mode": "per_ton", "rate_per_ton": 900,
        "product_rate_per_mt": 40000,
        "from_location": "Origin",
        "to_location": "MAHARASHTRA-Site",       # deliberately different from customer.state
        "loading_date": date, "unloading_date": date,
    }, timeout=15)
    assert tr.status_code == 200, tr.text
    inv = httpx.post(f"{API}/invoices", headers=h, json={
        "customer_id": cust, "trip_ids": [tr.json()["id"]],
        "invoice_date": date, "rcm": True,
    }, timeout=15)
    assert inv.status_code == 200, inv.text
    d = _get_ui(h, "2026-05").json()
    rows = [r for r in (d.get("b2b") or []) if r.get("invoice_number") == inv.json()["invoice_number"]]
    assert rows, "seeded invoice not surfaced in report"
    r = rows[0]
    assert r["state"] == "Karnataka", \
        f"POS state must be customer.state (Karnataka), got {r['state']}"
    assert r["state_code"] == "29"


# ─── T18-T19 · High-volume streaming (no truncation) ────────────────────

def test_t18_streaming_no_to_list_5000_in_payload_builder():
    """Static guardrail — the payload builder source must NOT contain
    the previously-observed truncation calls."""
    src_path = "/app/backend/routers/gst.py"
    with open(src_path) as f:
        src = f.read()
    # Extract the _gstr1_payload function body.
    start = src.index("async def _gstr1_payload")
    end = src.index("async def report_gstr1(", start)
    body = src[start:end]
    assert "to_list(5000)" not in body, \
        "_gstr1_payload still contains to_list(5000) — truncation risk"
    assert "to_list(2000)" not in body, \
        "_gstr1_payload still contains to_list(2000) — truncation risk"


def test_t19_streaming_10k_invoices_and_2500_customers_via_mongo_seed():
    """Seed 10,000 invoices across 2,500 distinct customers directly via
    Motor (bypassing _recompute_invoice for speed) and verify:
      * endpoint returns invoice_count == 10,000,
      * reconciliation.reconciled is True,
      * warnings == [] (no orphan customers),
      * every row has non-empty customer_name/state_code.
    """
    import asyncio
    import motor.motor_asyncio

    async def _seed_and_verify():
        mongo_url = os.environ["MONGO_URL"]
        db_name = os.environ["DB_NAME"]
        client = motor.motor_asyncio.AsyncIOMotorClient(mongo_url)
        db = client[db_name]

        uid = _current_uid()
        cid, h = _company_header()

        # Use a far-future month that will not clash with real data.
        month = "2099-06"
        start = "2099-06-01"; end = "2099-06-30"

        tag = uuid.uuid4().hex[:6]
        seed_prefix = f"C35S-{tag}"

        # Clean up any prior seed data (idempotent re-run).
        await db.invoices.delete_many({"user_id": uid, "company_id": cid,
                                       "invoice_number": {"$regex": f"^{seed_prefix}/"}})
        await db.customers.delete_many({"user_id": uid, "company_id": cid,
                                        "name": {"$regex": f"^{seed_prefix}-"}})

        # ── Bulk insert 2500 customers ──────────────────────────
        customers = []
        cust_ids = []
        for i in range(2500):
            cid_i = f"c35_{tag}_{i:05d}"
            cust_ids.append(cid_i)
            customers.append({
                "id": cid_i, "user_id": uid, "company_id": cid,
                "name": f"{seed_prefix}-Cust-{i:05d}",
                "phone": f"9{i:09d}",
                "state": "Karnataka",
                "state_code": "29",
                "gstin": _fake_gstin("29"),
                "ship_sites": [],
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        await db.customers.insert_many(customers)

        # ── Bulk insert 10 000 invoices ─────────────────────────
        invoices = []
        seq = 0
        for day in range(1, 31):
            date = f"2099-06-{day:02d}"
            per_day = 10000 // 30
            if day == 30:
                per_day = 10000 - seq
            for k in range(per_day):
                cust_id = cust_ids[seq % 2500]
                inv_num = f"{seed_prefix}/26-27/{seq:06d}"
                invoices.append({
                    "id":            f"inv_c35_{tag}_{seq:06d}",
                    "user_id":       uid,
                    "company_id":    cid,
                    "invoice_number": inv_num,
                    "invoice_date":  date,
                    "customer_id":   cust_id,
                    "trip_ids":      [],
                    "subtotal":      1000.0,
                    "cgst_amount":   0.0,
                    "sgst_amount":   0.0,
                    "igst_amount":   50.0,
                    "total_amount":  1050.0,
                    "total_tax":     50.0,
                    "gst_type":      "igst",
                    "rcm":           False,
                    "status":        "issued",
                    "amount_paid":   0.0,
                    "balance_due":   1050.0,
                    "payments":      [],
                })
                seq += 1
        assert seq == 10000
        await db.invoices.insert_many(invoices)

        try:
            # ── Verify streaming picks up every seeded invoice ──
            t0 = time.time()
            r = _get_ui(h, month)
            elapsed = time.time() - t0
            assert r.status_code == 200, r.text
            d = r.json()
            assert d["invoice_count"] == 10000, \
                f"streaming truncated: expected 10000 got {d['invoice_count']}"
            assert d["reconciliation"]["reconciled"] is True
            assert d["reconciliation"]["ground_truth_invoice_count"] == 10000
            # every row has non-empty name/state (2500 customer preload complete)
            sample = (d.get("b2b") or [])[:200]
            assert all(r.get("customer_name") for r in sample), \
                "some rows have empty customer_name — customer preload truncated"
            assert all(r.get("state_code") == "29" for r in sample), \
                "customer.state failed to project into row.state_code"
            # No orphan warnings for a clean 10k / 2.5k seed.
            assert not any("missing customer" in w for w in d.get("warnings") or []), \
                f"unexpected orphan warnings: {d.get('warnings')}"
            # Soft budget: endpoint must respond within 30s at 10k rows.
            assert elapsed < 30, f"endpoint slow: {elapsed:.1f}s"

            # ── XLSX end-to-end at 10k rows ─────────────────────
            xr = _get_xlsx(h, month)
            assert xr.status_code == 200
            wb = openpyxl.load_workbook(io.BytesIO(xr.content))
            b2b_rows = wb["B2B"].max_row - 4
            b2c_rows = max(wb["B2C"].max_row - 4, 0)
            assert b2b_rows + b2c_rows == 10000, \
                f"XLSX row count {b2b_rows + b2c_rows} != 10000"

            # ── PDF end-to-end at 10k rows (multi-page) ─────────
            pr = _get_pdf(h, month)
            assert pr.status_code == 200
            doc = fitz.open(stream=pr.content, filetype="pdf")
            assert doc.page_count > 5, \
                f"expected many-page PDF for 10k rows, got {doc.page_count}"
        finally:
            # Cleanup — always, even on failure.
            await db.invoices.delete_many({"user_id": uid, "company_id": cid,
                                           "invoice_number": {"$regex": f"^{seed_prefix}/"}})
            await db.customers.delete_many({"user_id": uid, "company_id": cid,
                                            "name": {"$regex": f"^{seed_prefix}-"}})
            client.close()

    asyncio.run(_seed_and_verify())


# ─── T20 · Static width envelope guardrail (PDF) ────────────────────────

def test_t20_pdf_col_widths_within_landscape_envelope():
    """Every PDF table column-width list must sum to <=273 mm (landscape
    A4 minus 12 mm L/R margins). Mirrors the C3.2 §9B guardrail."""
    from pdf.gstr1 import _all_col_widths_mm
    for name, widths in _all_col_widths_mm():
        total = sum(widths)
        assert total <= 273.0, f"{name} sum={total}mm exceeds 273mm envelope"


# ─── T21 · CSV shape preservation (frontend consumes /reports/gstr1) ────

def test_t21_csv_row_shape_preserved():
    """The row shape that GSTR1Report.downloadCSV() consumes has NOT
    changed. It relies on: invoice_number, invoice_date, customer_name,
    gstin, state, state_code, place_of_supply, reverse_charge,
    taxable_value, cgst, sgst, igst, total."""
    _, h = _company_header()
    d = _get_ui(h, "2026-08").json()
    required = ["invoice_number", "invoice_date", "customer_name", "gstin",
                "state", "state_code", "place_of_supply", "reverse_charge",
                "taxable_value", "cgst", "sgst", "igst", "total"]
    for row in (d.get("b2b") or [])[:1] + (d.get("b2c") or [])[:1]:
        for k in required:
            assert k in row, f"CSV-consumed key {k} missing from row"


# ─── T22 · Audit log emission ───────────────────────────────────────────

def test_t22_audit_log_row_per_download():
    """Every download must emit one audit_logs.gstr_export/download row."""
    import asyncio
    import motor.motor_asyncio

    async def _check():
        client = motor.motor_asyncio.AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        uid = _current_uid()
        _, h = _company_header()
        # Fingerprint by entity_ref filename which encodes the format.
        stamp = uuid.uuid4().hex[:6]
        # Use a unique unused month per format so we can tell them apart.
        for kind in ("json", "xlsx", "pdf"):
            r = httpx.get(f"{API}/reports/gstr1.{kind}", headers=h,
                          params={"month": "2035-02"}, timeout=60)
            assert r.status_code == 200
        # Recent audit rows for this user, gstr_export module, in the last minute.
        cutoff = (datetime.now(timezone.utc).replace(microsecond=0)).isoformat()
        rows = await db.audit_logs.find(
            {"user_id": uid, "module": "gstr_export", "action": "download",
             "entity_ref": {"$regex": "^GSTR1_.+_2035-02\\.(json|xlsx|pdf)$"}},
        ).sort("timestamp", -1).to_list(20)
        got_formats = set()
        for r in rows:
            fmt = (r.get("changes") or {}).get("format")
            if fmt:
                got_formats.add(fmt)
        assert {"json", "xlsx", "pdf"}.issubset(got_formats), \
            f"audit did not capture all three formats: got {got_formats}"
        client.close()

    asyncio.run(_check())


# ─── C3.5 UAT presentation polish — Feb 2026 ─────────────────────────────

def test_t23_pdf_summary_has_rupee_glyph_and_no_tofu():
    """Summary values must carry a real U+20B9 (₹) followed by the amount.
    reportlab draws a filled square (\ufffd/black box) when a glyph is
    absent — we assert the U+20B9 character *is* present next to a
    formatted numeric string on page 1."""
    _, h = _company_header()
    r = _get_pdf(h, "2026-08")
    assert r.status_code == 200
    import fitz as _fitz
    d = _fitz.open(stream=r.content, filetype="pdf")
    page1 = d[0].get_text()
    assert "\u20b9" in page1, "U+20B9 (₹) glyph missing from PDF Summary"
    # Must not contain the well-known unicode replacement character.
    assert "\ufffd" not in page1, "PDF page 1 contains replacement chars"
    # Numeric line like `₹ 32,75,68,793.00` or `₹ 32,754,368,342.80` must exist.
    j = _get_json(h, "2026-08").json()
    tot = f"{float(j['totals']['total']):,.2f}"
    # Find "₹ <total>" as a substring — tolerates layout spacing collapse.
    normalized = " ".join(page1.split())
    assert f"\u20b9 {tot}" in normalized or f"\u20b9  {tot}" in normalized, \
        f"₹-prefixed grand total not found in normalized text (expected '₹ {tot}')"


def test_t24_pdf_table_headers_use_rupee_suffix_not_prefix_in_cells():
    """Column headers must carry `(₹)` and data cells must NOT repeat ₹.
    Enforced structurally on the module constants."""
    from pdf.gstr1 import B2B_COL_HEADERS, B2C_COL_HEADERS, BY_STATE_COL_HEADERS
    for hdrs in (B2B_COL_HEADERS, B2C_COL_HEADERS, BY_STATE_COL_HEADERS):
        for h_ in hdrs:
            # The four monetary column headers must end with "(₹)".
            if any(word in h_ for word in ("Taxable", "CGST", "SGST", "IGST", "Total")) \
                    and h_ not in ("GST Type", "Grand Total"):
                assert h_.endswith("(\u20b9)"), \
                    f"monetary header {h_!r} does not end with (₹)"


def test_t25_pdf_invoice_number_column_width_at_least_34mm():
    """AKB/26-27//26-27/0004 (21 chars) must fit as a single visual token.
    34 mm is the minimum measured width for 7pt DejaVu."""
    from pdf.gstr1 import B2B_COL_WIDTHS_MM, B2C_COL_WIDTHS_MM
    assert B2B_COL_WIDTHS_MM[0] >= 34, f"B2B Invoice # width {B2B_COL_WIDTHS_MM[0]} < 34mm"
    assert B2C_COL_WIDTHS_MM[0] >= 34, f"B2C Invoice # width {B2C_COL_WIDTHS_MM[0]} < 34mm"


def test_t26_pdf_stays_a4_landscape():
    """A4 landscape = ~842 × 595 pt. Enforced by inspection of page 1."""
    _, h = _company_header()
    r = _get_pdf(h, "2026-08")
    import fitz as _fitz
    d = _fitz.open(stream=r.content, filetype="pdf")
    rect = d[0].rect
    # Landscape ⇒ width > height.
    assert rect.width > rect.height, \
        f"page 1 is not landscape: width={rect.width} height={rect.height}"
    # ±5 pt tolerance around A4 landscape (842 × 595).
    assert abs(rect.width - 842) < 5 and abs(rect.height - 595) < 5, \
        f"page size {rect.width}×{rect.height} not A4 landscape"


def test_t27_pdf_page_x_of_y_still_present_after_polish():
    """Presentation polish must not break the two-pass Page X of Y footer."""
    _, h = _company_header()
    r = _get_pdf(h, "2026-08")
    import fitz as _fitz
    d = _fitz.open(stream=r.content, filetype="pdf")
    for i in range(min(d.page_count, 3)):
        txt = d[i].get_text()
        assert f"Page {i+1} of {d.page_count}" in txt, \
            f"page {i+1} missing 'Page X of Y'"


def test_t28_pdf_disclosure_banner_still_present():
    """`NOT a GST portal upload file` must remain on the PDF."""
    _, h = _company_header()
    r = _get_pdf(h, "2026-08")
    import fitz as _fitz
    d = _fitz.open(stream=r.content, filetype="pdf")
    combined = "\n".join(d[i].get_text() for i in range(min(d.page_count, 2)))
    assert "NOT a GST portal upload file" in combined, \
        "statutory disclosure banner disappeared"


def test_t29_xlsx_currency_format_is_rupee_prefix():
    """Custom number format must render `₹ 12,345.67`, not `12,345.67 ₹`."""
    from xlsx.gstr1 import CURRENCY_FMT
    # Format string must place ₹ BEFORE the number placeholder.
    rupee_pos = CURRENCY_FMT.find("\u20b9")
    hash_pos  = CURRENCY_FMT.find("#")
    assert 0 <= rupee_pos < hash_pos, \
        f"CURRENCY_FMT places ₹ after digits: {CURRENCY_FMT!r}"


def test_t30_xlsx_headers_use_rupee_suffix():
    """Column headers must carry `(₹)` suffix, not raw `₹`."""
    from xlsx.gstr1 import B2B_HEADERS, B2C_HEADERS, BY_STATE_HEADERS
    for hdrs in (B2B_HEADERS, B2C_HEADERS, BY_STATE_HEADERS):
        for h_ in hdrs:
            if h_ in ("Invoice", "Date", "Customer", "GSTIN", "State",
                      "State Code", "POS", "RCM", "GST Type", "Code",
                      "Invoices"):
                continue
            assert h_.endswith("(\u20b9)"), \
                f"XLSX header {h_!r} does not end with (₹)"


def test_t31_xlsx_summary_totals_still_match_json_after_polish():
    """Presentation polish must not disturb summary numeric values."""
    _, h = _company_header()
    j = _get_json(h, "2026-08").json()
    r = _get_xlsx(h, "2026-08")
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    ws = wb["Summary"]
    assert int(ws.cell(5, 2).value) == int(j["invoice_count"])
    assert abs(float(ws.cell(6, 2).value) - float(j["totals"]["taxable"])) < 0.01
    assert abs(float(ws.cell(10, 2).value) - float(j["totals"]["total"])) < 0.01
    # Cell format string must be the ₹-prefix pattern.
    from xlsx.gstr1 import CURRENCY_FMT
    assert ws.cell(6, 2).number_format == CURRENCY_FMT


def test_t32_xlsx_still_four_sheets_and_json_unchanged():
    """Post-polish: JSON values are byte-identical (no business change).
    XLSX still carries the same 4 sheets."""
    _, h = _company_header()
    j1 = _get_ui(h, "2026-08").json()
    j2 = _get_json(h, "2026-08").json()
    # JSON UI ≡ JSON attachment (same values, same keys).
    for k in ("invoice_count", "totals", "b2b", "b2c", "by_state",
              "issuer_gstin", "reconciliation"):
        assert j1.get(k) == j2.get(k), f"JSON drift on {k}"
    r = _get_xlsx(h, "2026-08")
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["Summary", "B2B", "B2C", "By_State"]


def test_t33_pdf_long_invoice_number_stays_single_line():
    """Seed one invoice with an ultra-long number and verify it appears
    intact (no space or line break inserted) in the PDF text stream."""
    import asyncio
    import motor.motor_asyncio

    async def _seed_and_check():
        _, h = _company_header()
        uid = _current_uid()
        client = motor.motor_asyncio.AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        # Pick company from same header.
        cr = httpx.get(f"{API}/companies", headers=HDR, timeout=15).json()
        cid = cr[0]["id"]
        # Seed a customer with GSTIN so it hits the B2B section.
        cust = _fresh_customer(h, state="Karnataka", gstin=_fake_gstin("29"))
        month = "2050-04"
        inv_num = "AKB/26-27//26-27/0004"
        inv_id  = f"inv_c35_longnum_{uuid.uuid4().hex[:8]}"
        # Clean any prior copies for idempotency.
        await db.invoices.delete_many({"user_id": uid, "company_id": cid,
                                       "invoice_number": inv_num})
        await db.invoices.insert_one({
            "id": inv_id, "user_id": uid, "company_id": cid,
            "invoice_number": inv_num,
            "invoice_date": "2050-04-15",
            "customer_id": cust, "trip_ids": [],
            "subtotal": 1000.0, "cgst_amount": 0.0, "sgst_amount": 0.0,
            "igst_amount": 50.0, "total_amount": 1050.0, "total_tax": 50.0,
            "gst_type": "igst", "rcm": False, "status": "issued",
            "amount_paid": 0.0, "balance_due": 1050.0, "payments": [],
        })
        try:
            r = _get_pdf(h, month)
            assert r.status_code == 200
            import fitz as _fitz
            d = _fitz.open(stream=r.content, filetype="pdf")
            all_txt = "".join(d[i].get_text() for i in range(d.page_count))
            # The exact 21-char string must appear (no split by whitespace).
            assert inv_num in all_txt, \
                f"long invoice number split across lines. Sample: {all_txt[-2000:]}"
        finally:
            await db.invoices.delete_many({"user_id": uid, "company_id": cid,
                                           "invoice_number": inv_num})
            client.close()

    asyncio.run(_seed_and_check())
