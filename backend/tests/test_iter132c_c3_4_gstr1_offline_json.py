"""Iter132c C3.4 · GSTR-1 §9B Offline Utility JSON — targeted suite (T1-T21+).

Contract:
    LOCKED C3.1 canonical payload
        └── passed verbatim ──→
    C3.4 pure adapter (`_gstr1_9b_offline_json_projection`)
        └── fail-loud validation ──→
    GSTN GSTR-1 Offline Utility V3.2 envelope

No second calculator. No raw-data query in this layer. All seeds are
worker-safe under an isolated test tenant; no reuse of demo, C3.5,
or C4 fixtures.
"""
import os
import io
import json
import uuid
import asyncio
import httpx
import motor.motor_asyncio
import pytest
from datetime import datetime, timezone


BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = BASE + "/api"
HDR = {"Authorization": f"Bearer {os.environ['DEMO_TOKEN_VALUE']}"}


# ─── Helpers ──────────────────────────────────────────────────────────────

def _company_header(*, want_gstin=True):
    """Deterministic company selection for isolated tests.

    - want_gstin=True  → pick the first company whose profile has a
      non-empty `gstin` (required by C3.4 validator).
    - want_gstin=False → pick the first company with an EMPTY gstin
      (used by T17 which asserts the fail-loud 422).
    """
    r = httpx.get(f"{API}/companies", headers=HDR, timeout=15)
    assert r.status_code == 200, r.text
    for c in r.json():
        has_gstin = bool((c.get("gstin") or "").strip())
        if has_gstin is bool(want_gstin):
            return c["id"], {**HDR, "X-Company-Id": c["id"]}
    raise AssertionError(f"no company with want_gstin={want_gstin} on demo tenant")


def _current_uid() -> str:
    r = httpx.get(f"{API}/auth/me", headers=HDR, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["user_id"]


def _mongo():
    client = motor.motor_asyncio.AsyncIOMotorClient(os.environ["MONGO_URL"])
    return client, client[os.environ["DB_NAME"]]


def _tag() -> str:
    return f"c34t_{uuid.uuid4().hex[:8]}"


async def _seed_customer(db, uid, cid, *, name, state="Karnataka", gstin=""):
    d = {
        "id": f"cust_{uuid.uuid4().hex[:12]}",
        "user_id": uid, "company_id": cid,
        "name": name, "state": state, "gstin": (gstin or "").upper(),
        "phone": "", "email": "",
    }
    await db.customers.insert_one(d)
    return d["id"]


async def _seed_invoice(db, uid, cid, cust_id, *, date="2028-05-15",
                        inv_num=None, total=300000.0, gst_type="cgst_sgst"):
    inv_id = f"inv_{uuid.uuid4().hex[:12]}"
    doc = {
        "id": inv_id, "user_id": uid, "company_id": cid,
        "invoice_number": inv_num or f"INV/{uuid.uuid4().hex[:6].upper()}",
        "invoice_date": date, "customer_id": cust_id, "trip_ids": [],
        "subtotal": total, "cgst_amount": 0.0, "sgst_amount": 0.0,
        "igst_amount": 0.0, "total_tax": 0.0,
        "cgst_rate": 2.5, "sgst_rate": 2.5, "igst_rate": 5.0,
        "total_amount": total, "gst_type": gst_type,
        "rcm": False, "status": "issued",
        "amount_paid": 0.0, "balance_due": total, "payments": [],
    }
    await db.invoices.insert_one(doc)
    return inv_id, doc["invoice_number"]


async def _seed_note(db, uid, cid, inv_id, inv_num, cust_id, *,
                     kind="credit", note_date="2028-05-20",
                     total=1000.0, apply_gst=True,
                     reason_code="rate_correction", status="issued",
                     note_number=None, gst_type="cgst_sgst",
                     rcm=False):
    sub = total
    cgst = sgst = igst = 0.0; total_tax = 0.0
    if apply_gst:
        if gst_type == "igst":
            igst = round(sub * 0.05, 2)
        else:
            cgst = round(sub * 0.025, 2); sgst = round(sub * 0.025, 2)
        total_tax = round(cgst + sgst + igst, 2)
    nid = f"cdn_{uuid.uuid4().hex[:12]}"
    doc = {
        "id": nid, "user_id": uid, "company_id": cid,
        "kind": kind,
        "note_number": note_number or (f"C34CN/{uuid.uuid4().hex[:5].upper()}" if kind == "credit" else f"C34DN/{uuid.uuid4().hex[:5].upper()}"),
        "note_date": note_date,
        "invoice_id": inv_id, "invoice_number_snapshot": inv_num,
        "customer_id": cust_id,
        "reason_code": reason_code,
        "reason_text": "C3.4 seed",
        "lines": [{"id": f"cdnl_{uuid.uuid4().hex[:8]}", "description": "test",
                    "hsn_sac": "996791", "quantity": 1.0, "rate": sub,
                    "taxable_value": sub}],
        "subtotal": sub, "gst_type": gst_type,
        "cgst_rate": 2.5, "sgst_rate": 2.5, "igst_rate": 5.0,
        "cgst_amount": cgst, "sgst_amount": sgst, "igst_amount": igst,
        "total_tax": total_tax,
        "total_amount": round(sub + total_tax, 2),
        "round_off": 0.0,
        "rcm": bool(rcm), "apply_gst": bool(apply_gst),
        "status": status,
        "created_by": uid, "approved_by": uid if status == "issued" else None,
        "approved_at": datetime.now(timezone.utc).isoformat() if status == "issued" else None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "is_historical": False, "deadline_override": False,
    }
    await db.credit_debit_notes.insert_one(doc)
    return nid, doc


def _get(h, month, **params):
    return httpx.get(f"{API}/reports/gstr1-9b-offline.json",
                     headers=h, params={"month": month, **params}, timeout=180)


# ─── T1 · B2B credit note → CDNR structure ─────────────────────────────

def test_t1_valid_b2b_credit_note_becomes_cdnr():
    async def _run():
        cid, h = _company_header()
        uid = _current_uid()
        client, db = _mongo()
        try:
            cust = await _seed_customer(db, uid, cid,
                                        name=f"{_tag()}-B2B",
                                        state="Karnataka",
                                        gstin="29AAAAA1234A1Z5")
            iid, inum = await _seed_invoice(db, uid, cid, cust,
                                            date="2028-04-01",
                                            gst_type="cgst_sgst")
            await _seed_note(db, uid, cid, iid, inum, cust,
                             kind="credit", note_date="2028-04-15",
                             total=1000.0, gst_type="cgst_sgst")
            r = _get(h, "2028-04").json()
            u = r["utility_json"]
            assert set(u.keys()) == {"gstin", "fp", "gt", "cur_gt",
                                     "version", "hash", "cdnr", "cdnur"}
            grps = [g for g in u["cdnr"] if g["ctin"] == "29AAAAA1234A1Z5"]
            assert len(grps) == 1, u["cdnr"]
            nt = grps[0]["nt"][0]
            assert nt["ntty"] == "C"
            assert nt["p_gst"] == "N"
            assert nt["inv_typ"] == "R"
            assert nt["rchrg"] == "N"
            assert len(nt["nt_num"]) <= 16
            assert set(nt["itms"][0]["itm_det"].keys()) == \
                {"rt", "txval", "iamt", "camt", "samt", "csamt"}
        finally:
            await db.credit_debit_notes.delete_many({"user_id": uid, "customer_id": cust})
            await db.invoices.delete_many({"user_id": uid, "id": iid})
            await db.customers.delete_many({"user_id": uid, "id": cust})
            client.close()
    asyncio.run(_run())


# ─── T2 · B2B debit note (IGST inter-state) ────────────────────────────

def test_t2_valid_b2b_debit_note_igst():
    async def _run():
        cid, h = _company_header()
        uid = _current_uid()
        client, db = _mongo()
        try:
            cust = await _seed_customer(db, uid, cid,
                                        name=f"{_tag()}-B2B-DN",
                                        state="Maharashtra",
                                        gstin="27AAAAA1234A1Z5")
            iid, inum = await _seed_invoice(db, uid, cid, cust,
                                            date="2028-05-01",
                                            gst_type="igst")
            await _seed_note(db, uid, cid, iid, inum, cust,
                             kind="debit", note_date="2028-05-10",
                             total=2000.0, gst_type="igst")
            u = _get(h, "2028-05").json()["utility_json"]
            grps = [g for g in u["cdnr"] if g["ctin"] == "27AAAAA1234A1Z5"]
            assert len(grps) == 1
            nt = grps[0]["nt"][0]
            assert nt["ntty"] == "D"
            det = nt["itms"][0]["itm_det"]
            assert det["iamt"] > 0
            assert det["camt"] == 0 and det["samt"] == 0
        finally:
            await db.credit_debit_notes.delete_many({"user_id": uid, "customer_id": cust})
            await db.invoices.delete_many({"user_id": uid, "id": iid})
            await db.customers.delete_many({"user_id": uid, "id": cust})
            client.close()
    asyncio.run(_run())


# ─── T3 · mixed CN + DN under same ctin → single group ─────────────────

def test_t3_mixed_cn_dn_same_ctin_single_group_sorted():
    async def _run():
        cid, h = _company_header()
        uid = _current_uid()
        client, db = _mongo()
        try:
            cust = await _seed_customer(db, uid, cid,
                                        name=f"{_tag()}-MIX",
                                        state="Karnataka",
                                        gstin="29BBBBB1234A1Z5")
            iid, inum = await _seed_invoice(db, uid, cid, cust,
                                            date="2028-06-01",
                                            gst_type="cgst_sgst")
            await _seed_note(db, uid, cid, iid, inum, cust,
                             kind="credit", note_date="2028-06-15", total=500.0)
            await _seed_note(db, uid, cid, iid, inum, cust,
                             kind="debit", note_date="2028-06-05", total=800.0)
            u = _get(h, "2028-06").json()["utility_json"]
            grps = [g for g in u["cdnr"] if g["ctin"] == "29BBBBB1234A1Z5"]
            assert len(grps) == 1
            assert len(grps[0]["nt"]) == 2
            # Deterministic sort by (nt_dt, nt_num)
            dates = [nt["nt_dt"] for nt in grps[0]["nt"]]
            assert dates == sorted(dates)
        finally:
            await db.credit_debit_notes.delete_many({"user_id": uid, "customer_id": cust})
            await db.invoices.delete_many({"user_id": uid, "id": iid})
            await db.customers.delete_many({"user_id": uid, "id": cust})
            client.close()
    asyncio.run(_run())


# ─── T4 · filing-period fp=MMYYYY; multi-month notes excluded ──────────

def test_t4_filing_period_fp_mmyyyy_and_out_of_period_excluded():
    async def _run():
        cid, h = _company_header()
        uid = _current_uid()
        client, db = _mongo()
        try:
            cust = await _seed_customer(db, uid, cid, name=f"{_tag()}-FP",
                                        state="Karnataka",
                                        gstin="29CCCCC1234A1Z5")
            iid, inum = await _seed_invoice(db, uid, cid, cust, date="2028-07-01")
            # Note inside July 2028
            await _seed_note(db, uid, cid, iid, inum, cust,
                             note_date="2028-07-05", total=1000.0,
                             note_number="C34JUL/001")
            # Note in August 2028 must NOT appear in July
            await _seed_note(db, uid, cid, iid, inum, cust,
                             note_date="2028-08-05", total=2000.0,
                             note_number="C34AUG/001")
            u = _get(h, "2028-07").json()["utility_json"]
            assert u["fp"] == "072028"
            grps = [g for g in u["cdnr"] if g["ctin"] == "29CCCCC1234A1Z5"]
            nt_nums = [n["nt_num"] for g in grps for n in g["nt"]]
            assert "C34JUL/001" in nt_nums
            assert "C34AUG/001" not in nt_nums
        finally:
            await db.credit_debit_notes.delete_many({"user_id": uid, "customer_id": cust})
            await db.invoices.delete_many({"user_id": uid, "id": iid})
            await db.customers.delete_many({"user_id": uid, "id": cust})
            client.close()
    asyncio.run(_run())


# ─── T5 · CDNR routing (valid GSTIN) ───────────────────────────────────

def test_t5_cdnr_routing_valid_gstin_only():
    async def _run():
        cid, h = _company_header()
        uid = _current_uid()
        client, db = _mongo()
        try:
            cust = await _seed_customer(db, uid, cid, name=f"{_tag()}-CDNR",
                                        state="Karnataka",
                                        gstin="29DDDDD1234A1Z5")
            iid, inum = await _seed_invoice(db, uid, cid, cust, date="2028-08-01")
            await _seed_note(db, uid, cid, iid, inum, cust, note_date="2028-08-05",
                             total=1000.0)
            u = _get(h, "2028-08").json()["utility_json"]
            ctins = [g["ctin"] for g in u["cdnr"]]
            assert "29DDDDD1234A1Z5" in ctins
            assert not any(r for r in u["cdnur"]
                           if r["nt_num"].startswith("C34"))  # not in CDNUR
        finally:
            await db.credit_debit_notes.delete_many({"user_id": uid, "customer_id": cust})
            await db.invoices.delete_many({"user_id": uid, "id": iid})
            await db.customers.delete_many({"user_id": uid, "id": cust})
            client.close()
    asyncio.run(_run())


# ─── T6 · CDNUR routing (no GSTIN + inter-state + > ₹2.5 L) ────────────

def test_t6_cdnur_routing_b2cl_with_2char_pos():
    async def _run():
        cid, h = _company_header()
        uid = _current_uid()
        client, db = _mongo()
        try:
            cust = await _seed_customer(db, uid, cid, name=f"{_tag()}-CDNUR",
                                        state="Maharashtra", gstin="")
            iid, inum = await _seed_invoice(db, uid, cid, cust,
                                            date="2028-09-01",
                                            total=300000.0,  # > 2.5 L
                                            gst_type="igst")
            await _seed_note(db, uid, cid, iid, inum, cust,
                             note_date="2028-09-05",
                             total=1500.0, gst_type="igst",
                             note_number="C34CDNUR/A001")
            u = _get(h, "2028-09").json()["utility_json"]
            match = [r for r in u["cdnur"] if r["nt_num"] == "C34CDNUR/A001"]
            assert len(match) == 1
            r = match[0]
            assert r["typ"] == "B2CL"
            assert len(r["pos"]) == 2 and r["pos"].isdigit()
            assert r["pos"] == "27"  # Maharashtra
        finally:
            await db.credit_debit_notes.delete_many({"user_id": uid, "customer_id": cust})
            await db.invoices.delete_many({"user_id": uid, "id": iid})
            await db.customers.delete_many({"user_id": uid, "id": cust})
            client.close()
    asyncio.run(_run())


# ─── T7 · B2CS excluded from utility, surfaced in advisories ───────────

def test_t7_b2cs_excluded_and_surfaced_in_advisories():
    async def _run():
        cid, h = _company_header()
        uid = _current_uid()
        client, db = _mongo()
        try:
            # No GSTIN, intra-state → B2CS (excluded)
            cust = await _seed_customer(db, uid, cid, name=f"{_tag()}-B2CS",
                                        state="Telangana", gstin="")
            iid, inum = await _seed_invoice(db, uid, cid, cust,
                                            date="2028-10-01",
                                            gst_type="cgst_sgst")
            await _seed_note(db, uid, cid, iid, inum, cust,
                             note_date="2028-10-05", total=500.0,
                             note_number="C34B2CS/A001")
            env = _get(h, "2028-10").json()
            u = env["utility_json"]; a = env["advisories"]
            assert not any(r for r in u["cdnur"] if r["nt_num"] == "C34B2CS/A001")
            for g in u["cdnr"]:
                assert not any(n for n in g["nt"] if n["nt_num"] == "C34B2CS/A001")
            assert a.get("b2cs_report_net_of_in_table_7", 0) >= 1
        finally:
            await db.credit_debit_notes.delete_many({"user_id": uid, "customer_id": cust})
            await db.invoices.delete_many({"user_id": uid, "id": iid})
            await db.customers.delete_many({"user_id": uid, "id": cust})
            client.close()
    asyncio.run(_run())


# ─── T8 · GSTIN + POS field mapping ────────────────────────────────────

def test_t8_gstin_and_pos_mapping():
    async def _run():
        cid, h = _company_header()
        uid = _current_uid()
        client, db = _mongo()
        try:
            cB2B = await _seed_customer(db, uid, cid, name=f"{_tag()}-POS-B2B",
                                        state="Karnataka",
                                        gstin="29EEEEE1234A1Z5")
            iB2B, iB2Bn = await _seed_invoice(db, uid, cid, cB2B,
                                              date="2028-11-01")
            await _seed_note(db, uid, cid, iB2B, iB2Bn, cB2B,
                             note_date="2028-11-05", total=1000.0)

            cCDNUR = await _seed_customer(db, uid, cid,
                                          name=f"{_tag()}-POS-CDNUR",
                                          state="Maharashtra", gstin="")
            iCDNUR, iCDNURn = await _seed_invoice(db, uid, cid, cCDNUR,
                                                  date="2028-11-01",
                                                  total=400000.0,
                                                  gst_type="igst")
            await _seed_note(db, uid, cid, iCDNUR, iCDNURn, cCDNUR,
                             note_date="2028-11-05", total=800.0,
                             gst_type="igst",
                             note_number="C34POSCDNUR/A001")

            u = _get(h, "2028-11").json()["utility_json"]
            grp = [g for g in u["cdnr"] if g["ctin"] == "29EEEEE1234A1Z5"]
            assert len(grp) == 1
            match = [r for r in u["cdnur"] if r["nt_num"] == "C34POSCDNUR/A001"]
            assert len(match) == 1
            assert match[0]["pos"] == "27"
        finally:
            await db.credit_debit_notes.delete_many(
                {"user_id": uid, "customer_id": {"$in": [cB2B, cCDNUR]}})
            await db.invoices.delete_many({"user_id": uid, "id": {"$in": [iB2B, iCDNUR]}})
            await db.customers.delete_many({"user_id": uid, "id": {"$in": [cB2B, cCDNUR]}})
            client.close()
    asyncio.run(_run())


# ─── T9 · RCM Y/N verbatim from persisted rcm flag ─────────────────────

def test_t9_rcm_representation_from_persisted_flag():
    async def _run():
        cid, h = _company_header()
        uid = _current_uid()
        client, db = _mongo()
        try:
            cust = await _seed_customer(db, uid, cid, name=f"{_tag()}-RCM",
                                        state="Karnataka",
                                        gstin="29FFFFF1234A1Z5")
            iid, inum = await _seed_invoice(db, uid, cid, cust,
                                            date="2028-12-01")
            await _seed_note(db, uid, cid, iid, inum, cust,
                             note_date="2028-12-05", total=1000.0,
                             rcm=False, note_number="C34RCMN/A001")
            await _seed_note(db, uid, cid, iid, inum, cust,
                             note_date="2028-12-06", total=1000.0,
                             rcm=True, note_number="C34RCMY/A001")
            u = _get(h, "2028-12").json()["utility_json"]
            g = [x for x in u["cdnr"] if x["ctin"] == "29FFFFF1234A1Z5"][0]
            m = {n["nt_num"]: n for n in g["nt"]}
            assert m["C34RCMN/A001"]["rchrg"] == "N"
            assert m["C34RCMY/A001"]["rchrg"] == "Y"
        finally:
            await db.credit_debit_notes.delete_many({"user_id": uid, "customer_id": cust})
            await db.invoices.delete_many({"user_id": uid, "id": iid})
            await db.customers.delete_many({"user_id": uid, "id": cust})
            client.close()
    asyncio.run(_run())


# ─── T10 · apply_gst=False (commercial) excluded, surfaced in advisories ──

def test_t10_commercial_excluded_and_surfaced():
    async def _run():
        cid, h = _company_header()
        uid = _current_uid()
        client, db = _mongo()
        try:
            cust = await _seed_customer(db, uid, cid, name=f"{_tag()}-COM",
                                        state="Karnataka",
                                        gstin="29GGGGG1234A1Z5")
            iid, inum = await _seed_invoice(db, uid, cid, cust,
                                            date="2029-01-01")
            await _seed_note(db, uid, cid, iid, inum, cust,
                             note_date="2029-01-05", total=500.0,
                             apply_gst=False, note_number="C34COM/A001")
            env = _get(h, "2029-01").json()
            u = env["utility_json"]; a = env["advisories"]
            for g in u["cdnr"]:
                assert not any(n for n in g["nt"] if n["nt_num"] == "C34COM/A001")
            assert not any(r for r in u["cdnur"] if r["nt_num"] == "C34COM/A001")
            assert a.get("commercial_notes_excluded_from_offline_json", 0) >= 1
        finally:
            await db.credit_debit_notes.delete_many({"user_id": uid, "customer_id": cust})
            await db.invoices.delete_many({"user_id": uid, "id": iid})
            await db.customers.delete_many({"user_id": uid, "id": cust})
            client.close()
    asyncio.run(_run())


# ─── T11 · draft note excluded ─────────────────────────────────────────

def test_t11_draft_note_excluded():
    async def _run():
        cid, h = _company_header()
        uid = _current_uid()
        client, db = _mongo()
        try:
            cust = await _seed_customer(db, uid, cid, name=f"{_tag()}-DRAFT",
                                        state="Karnataka",
                                        gstin="29HHHHH1234A1Z5")
            iid, inum = await _seed_invoice(db, uid, cid, cust,
                                            date="2029-02-01")
            await _seed_note(db, uid, cid, iid, inum, cust,
                             note_date="2029-02-05", total=500.0,
                             status="draft", note_number="")
            u = _get(h, "2029-02").json()["utility_json"]
            for g in u["cdnr"]:
                assert g["ctin"] != "29HHHHH1234A1Z5" or len(g["nt"]) == 0
        finally:
            await db.credit_debit_notes.delete_many({"user_id": uid, "customer_id": cust})
            await db.invoices.delete_many({"user_id": uid, "id": iid})
            await db.customers.delete_many({"user_id": uid, "id": cust})
            client.close()
    asyncio.run(_run())


# ─── T12 · cancelled-within-period excluded ─────────────────────────────

def test_t12_cancelled_within_period_excluded():
    async def _run():
        cid, h = _company_header()
        uid = _current_uid()
        client, db = _mongo()
        try:
            cust = await _seed_customer(db, uid, cid, name=f"{_tag()}-CANC",
                                        state="Karnataka",
                                        gstin="29IIIII1234A1Z5")
            iid, inum = await _seed_invoice(db, uid, cid, cust,
                                            date="2029-03-01")
            nid, doc = await _seed_note(db, uid, cid, iid, inum, cust,
                                        note_date="2029-03-05", total=500.0,
                                        note_number="C34CANC/A001")
            await db.credit_debit_notes.update_one(
                {"id": nid},
                {"$set": {
                    "status": "cancelled",
                    "cancelled_at": "2029-03-20T00:00:00+00:00",
                    "cancelled_reason": "test",
                }},
            )
            u = _get(h, "2029-03").json()["utility_json"]
            for g in u["cdnr"]:
                assert not any(n for n in g["nt"] if n["nt_num"] == "C34CANC/A001")
        finally:
            await db.credit_debit_notes.delete_many({"user_id": uid, "customer_id": cust})
            await db.invoices.delete_many({"user_id": uid, "id": iid})
            await db.customers.delete_many({"user_id": uid, "id": cust})
            client.close()
    asyncio.run(_run())


# ─── T13 · duplicate prevention (nt_num) ────────────────────────────────

def test_t13_duplicate_prevention_within_ctin():
    async def _run():
        cid, h = _company_header()
        uid = _current_uid()
        client, db = _mongo()
        try:
            cust = await _seed_customer(db, uid, cid, name=f"{_tag()}-DUP",
                                        state="Karnataka",
                                        gstin="29JJJJJ1234A1Z5")
            iid, inum = await _seed_invoice(db, uid, cid, cust,
                                            date="2029-04-01")
            # Two notes with same note_number under same ctin
            await _seed_note(db, uid, cid, iid, inum, cust,
                             note_date="2029-04-05", total=500.0,
                             note_number="C34DUP/A001")
            await _seed_note(db, uid, cid, iid, inum, cust,
                             note_date="2029-04-06", total=700.0,
                             note_number="C34DUP/A001")
            r = _get(h, "2029-04")
            # The adapter dedupes; validator emits duplicate advisory but the
            # unique set survives — verify no double emission.
            u = r.json()["utility_json"]
            grp = [g for g in u["cdnr"] if g["ctin"] == "29JJJJJ1234A1Z5"]
            nt_nums = [n["nt_num"] for g in grp for n in g["nt"]]
            assert nt_nums.count("C34DUP/A001") == 1
        finally:
            await db.credit_debit_notes.delete_many({"user_id": uid, "customer_id": cust})
            await db.invoices.delete_many({"user_id": uid, "id": iid})
            await db.customers.delete_many({"user_id": uid, "id": cust})
            client.close()
    asyncio.run(_run())


# ─── T14 · canonical parity — utility values = C3.1 fields verbatim ────

def test_t14_canonical_parity_with_c31_payload():
    async def _run():
        cid, h = _company_header()
        uid = _current_uid()
        client, db = _mongo()
        try:
            cust = await _seed_customer(db, uid, cid, name=f"{_tag()}-PAR",
                                        state="Karnataka",
                                        gstin="29KKKKK1234A1Z5")
            iid, inum = await _seed_invoice(db, uid, cid, cust,
                                            date="2029-05-01")
            await _seed_note(db, uid, cid, iid, inum, cust,
                             note_date="2029-05-05", total=1234.56,
                             note_number="C34PAR/A001")
            # C3.1 canonical
            c31 = httpx.get(f"{API}/reports/gstr1-9b",
                            headers=h, params={"month": "2029-05"}, timeout=60).json()
            c31_grp = [g for g in c31["cdnr"] if g["ctin"] == "29KKKKK1234A1Z5"][0]
            c31_nt = c31_grp["nt"][0]

            # C3.4 utility
            u = _get(h, "2029-05").json()["utility_json"]
            u_grp = [g for g in u["cdnr"] if g["ctin"] == "29KKKKK1234A1Z5"][0]
            u_nt = u_grp["nt"][0]

            for k in ("nt_num", "nt_dt", "ntty", "val", "p_gst",
                      "inum", "idt", "rchrg", "inv_typ"):
                assert u_nt[k] == c31_nt[k], f"drift on {k}: c31={c31_nt[k]!r} c34={u_nt[k]!r}"
            assert u_nt["itms"] == c31_nt["itms"]
        finally:
            await db.credit_debit_notes.delete_many({"user_id": uid, "customer_id": cust})
            await db.invoices.delete_many({"user_id": uid, "id": iid})
            await db.customers.delete_many({"user_id": uid, "id": cust})
            client.close()
    asyncio.run(_run())


# ─── T15 · sum of val = C3.1 totals.cdnr.val + totals.cdnur.val ────────

def test_t15_sum_val_matches_c31_totals():
    async def _run():
        cid, h = _company_header()
        uid = _current_uid()
        client, db = _mongo()
        try:
            cust = await _seed_customer(db, uid, cid, name=f"{_tag()}-SUM",
                                        state="Karnataka",
                                        gstin="29LLLLL1234A1Z5")
            iid, inum = await _seed_invoice(db, uid, cid, cust,
                                            date="2029-06-01")
            for i, v in enumerate([100.0, 200.0, 300.0]):
                await _seed_note(db, uid, cid, iid, inum, cust,
                                 note_date="2029-06-05", total=v,
                                 note_number=f"C34SUM/{i:03d}")
            c31 = httpx.get(f"{API}/reports/gstr1-9b", headers=h,
                            params={"month": "2029-06"}, timeout=60).json()
            u = _get(h, "2029-06").json()["utility_json"]

            u_sum = round(
                sum(n["val"] for g in u["cdnr"] for n in g["nt"]) +
                sum(r["val"] for r in u["cdnur"]),
                2,
            )
            expected = round(
                (c31["totals"]["cdnr"]["val"] or 0) +
                (c31["totals"]["cdnur"]["val"] or 0),
                2,
            )
            assert abs(u_sum - expected) < 0.01, (u_sum, expected)
        finally:
            await db.credit_debit_notes.delete_many({"user_id": uid, "customer_id": cust})
            await db.invoices.delete_many({"user_id": uid, "id": iid})
            await db.customers.delete_many({"user_id": uid, "id": cust})
            client.close()
    asyncio.run(_run())


# ─── T16 · required envelope keys, no extras ──────────────────────────

def test_t16_envelope_required_keys_and_no_extras():
    _, h = _company_header()
    r = _get(h, "2029-07").json()
    u = r["utility_json"]
    assert set(u.keys()) == {"gstin", "fp", "gt", "cur_gt",
                             "version", "hash", "cdnr", "cdnur"}
    # Types
    assert isinstance(u["gstin"], str)
    assert isinstance(u["fp"], str) and len(u["fp"]) == 6 and u["fp"].isdigit()
    assert isinstance(u["gt"], int) and u["gt"] == 0
    assert isinstance(u["cur_gt"], int) and u["cur_gt"] == 0
    assert u["hash"] == "hash"
    assert isinstance(u["cdnr"], list) and isinstance(u["cdnur"], list)


# ─── T17 · fail-loud when missing issuer GSTIN ─────────────────────────

def test_t17_missing_issuer_gstin_fails_loud_422():
    async def _run():
        _, h = _company_header(want_gstin=False)
        rr = _get(h, "2029-08")
        assert rr.status_code == 422, rr.text
        body = rr.json()
        assert body["detail"]["error"] == "issuer_gstin_missing_or_invalid"
    asyncio.run(_run())


# ─── T18 · idempotency — two calls, byte-identical utility_json ────────

def test_t18_idempotency_byte_identical_utility_json():
    _, h = _company_header()
    a = _get(h, "2029-09").json()["utility_json"]
    b = _get(h, "2029-09").json()["utility_json"]
    aj = json.dumps(a, separators=(",", ":"), ensure_ascii=False, sort_keys=False)
    bj = json.dumps(b, separators=(",", ":"), ensure_ascii=False, sort_keys=False)
    assert aj == bj


# ─── T19 · High-volume 10 000 notes streaming + byte-size ceiling ──────

@pytest.mark.slow
def test_t19_high_volume_10k_notes_and_byte_size_measured():
    """Prove:
        (A) 10 000 CDNR notes serialise without truncation, AND
        (B) actual UTF-8 byte size is measured and reported.

    A 10 000-note payload is <5 MB by construction (small itms per note);
    this test asserts BOTH the size measurement fires AND the response
    is NOT a silent truncation.
    """
    async def _run():
        cid, h = _company_header()
        uid = _current_uid()
        client, db = _mongo()
        tag = _tag()
        seed_month = "2035-04"
        try:
            # 100 unique registered customers with VALID GSTINs so all
            # notes route to CDNR (matching _GSTIN_RE and intra-state).
            # GSTIN format: 2 digits + 5 letters + 4 digits + letter + alnum + Z + alnum.
            customer_ids = []
            _letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            for i in range(100):
                # Home-state prefix matters only for CGST/SGST vs IGST routing —
                # match issuer state so the notes stay intra-state B2B.
                gstin = f"37AAA{_letters[i % 26]}{_letters[(i // 26) % 26]}{i % 10000:04d}A1Z{i % 10}"
                cust = await _seed_customer(
                    db, uid, cid,
                    name=f"{tag}-c{i:03d}",
                    state="Andhra Pradesh",  # matches issuer state (code 37)
                    gstin=gstin,
                )
                customer_ids.append(cust)
            inv_map = {}
            invoice_ids = []
            for cust in customer_ids:
                iid, inum = await _seed_invoice(db, uid, cid, cust,
                                                date=f"{seed_month}-01")
                inv_map[cust] = (iid, inum)
                invoice_ids.append(iid)

            # 10 000 notes across those customers.
            batch = []
            for i in range(10000):
                cust = customer_ids[i % 100]
                iid, inum = inv_map[cust]
                sub = 100.0
                doc = {
                    "id": f"cdn_{tag}_{i:05d}",
                    "user_id": uid, "company_id": cid,
                    "kind": "credit" if i % 3 == 0 else "debit",
                    "note_number": f"{tag[:8]}/{i:05d}"[:16],
                    "note_date": f"{seed_month}-{(i % 28) + 1:02d}",
                    "invoice_id": iid,
                    "invoice_number_snapshot": inum,
                    "customer_id": cust,
                    "reason_code": "rate_correction",
                    "reason_text": "seed T19",
                    "lines": [],
                    "subtotal": sub, "gst_type": "cgst_sgst",
                    "cgst_rate": 2.5, "sgst_rate": 2.5, "igst_rate": 5.0,
                    "cgst_amount": 2.5, "sgst_amount": 2.5, "igst_amount": 0.0,
                    "total_tax": 5.0, "total_amount": 105.0, "round_off": 0.0,
                    "rcm": False, "apply_gst": True,
                    "status": "issued", "created_by": uid,
                    "approved_by": uid,
                    "approved_at": "2035-04-15T00:00:00+00:00",
                    "created_at": "2035-04-15T00:00:00+00:00",
                    "is_historical": False, "deadline_override": False,
                }
                batch.append(doc)
                if len(batch) >= 500:
                    await db.credit_debit_notes.insert_many(batch)
                    batch = []
            if batch:
                await db.credit_debit_notes.insert_many(batch)

            r = _get(h, seed_month)
            assert r.status_code == 200, r.text[:2000]
            env = r.json()
            u = env["utility_json"]
            m = env["meta"]

            emitted = sum(len(g["nt"]) for g in u["cdnr"]) + len(u["cdnur"])
            assert emitted >= 10000, f"streaming truncated: {emitted}"
            assert m["utility_json_bytes"] > 0
            assert m["utility_json_over_5mb"] in (True, False)  # measured
            # For 10 000 * ~100-byte notes we expect <5 MB.
            assert m["utility_json_over_5mb"] is False, \
                f"unexpected oversize: {m['utility_json_bytes']} bytes"
            # Serialise ourselves and confirm the size matches the endpoint's
            # own measurement byte-for-byte (deterministic).
            local_bytes = len(json.dumps(u, separators=(",", ":"),
                                         ensure_ascii=False).encode("utf-8"))
            assert local_bytes == m["utility_json_bytes"], \
                f"size drift: local={local_bytes} endpoint={m['utility_json_bytes']}"
        finally:
            await db.credit_debit_notes.delete_many(
                {"user_id": uid, "id": {"$regex": f"^cdn_{tag}_"}})
            await db.invoices.delete_many({"user_id": uid, "id": {"$in": invoice_ids}})
            await db.customers.delete_many({"user_id": uid, "id": {"$in": customer_ids}})
            client.close()
    asyncio.run(_run())


# ─── T20 · schema/version compliance ───────────────────────────────────

def test_t20_schema_and_version_compliance():
    _, h = _company_header()
    env = _get(h, "2029-10").json()
    u = env["utility_json"]; m = env["meta"]
    assert list(u.keys()) == ["gstin", "fp", "gt", "cur_gt",
                              "version", "hash", "cdnr", "cdnur"]
    assert u["version"] == m["version_string"]
    assert m["version_default"] == "3.2"
    assert m["version_override_env"] == "GSTN_UTILITY_VERSION_STRING"
    # Each CDNR note must NOT carry rsn / customer_name / _warnings.
    for g in u["cdnr"]:
        for n in g["nt"]:
            assert "rsn" not in n
            assert "customer_name" not in n
            assert "_warnings" not in n
            assert isinstance(n["itms"], list)
            det = n["itms"][0]["itm_det"] if n["itms"] else {}
            for f in ("rt", "txval", "iamt", "camt", "samt", "csamt"):
                assert f in det
    # CDNUR pos must be 2-char state code (digits only).
    for r in u["cdnur"]:
        assert len(r["pos"]) == 2 and r["pos"].isdigit()
        assert r["typ"] in {"B2CL", "EXPWP", "EXPWOP"}


# ─── T21 · cancelled-after-export advisory only, not in utility_json ───

def test_t21_cancelled_after_export_advisory_only():
    async def _run():
        cid, h = _company_header()
        uid = _current_uid()
        client, db = _mongo()
        try:
            cust = await _seed_customer(db, uid, cid, name=f"{_tag()}-9C",
                                        state="Karnataka",
                                        gstin="29MMMMM1234A1Z5")
            iid, inum = await _seed_invoice(db, uid, cid, cust,
                                            date="2029-11-01")
            nid, _ = await _seed_note(db, uid, cid, iid, inum, cust,
                                      note_date="2029-11-05", total=800.0,
                                      note_number="C349C/A001")
            # Cancel AFTER period end → §9C amendment due
            await db.credit_debit_notes.update_one(
                {"id": nid},
                {"$set": {
                    "status": "cancelled",
                    "cancelled_at": "2029-12-15T00:00:00+00:00",
                    "cancelled_reason": "t21",
                }},
            )
            env = _get(h, "2029-11").json()
            u = env["utility_json"]; a = env["advisories"]
            for g in u["cdnr"]:
                assert not any(n for n in g["nt"] if n["nt_num"] == "C349C/A001")
            assert a.get("cancelled_after_export_requires_9c_amendment", 0) >= 1
        finally:
            await db.credit_debit_notes.delete_many({"user_id": uid, "customer_id": cust})
            await db.invoices.delete_many({"user_id": uid, "id": iid})
            await db.customers.delete_many({"user_id": uid, "id": cust})
            client.close()
    asyncio.run(_run())


# ─── T22 · Byte-size measurement is present, non-zero, non-truncating ──

def test_t22_byte_size_field_present_and_matches_local_serialization():
    _, h = _company_header()
    env = _get(h, "2029-12").json()
    m = env["meta"]
    assert "utility_json_bytes" in m
    assert "utility_json_size_limit" in m
    assert "utility_json_over_5mb" in m
    assert m["utility_json_size_limit"] == 5 * 1024 * 1024
    assert m["utility_json_bytes"] > 0
    local = len(json.dumps(env["utility_json"], separators=(",", ":"),
                           ensure_ascii=False).encode("utf-8"))
    assert local == m["utility_json_bytes"]


# ─── T23 · raw=1 returns only utility_json body suitable for utility import ─

def test_t23_raw_download_returns_utility_json_only():
    _, h = _company_header()
    r = httpx.get(f"{API}/reports/gstr1-9b-offline.json",
                  headers=h, params={"month": "2030-01", "raw": 1}, timeout=60)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    cd = r.headers.get("content-disposition", "")
    assert "GSTR1_9B_Offline_" in cd and cd.endswith('.json"')
    d = r.json()
    assert set(d.keys()) == {"gstin", "fp", "gt", "cur_gt",
                             "version", "hash", "cdnr", "cdnur"}


# ─── T24 · GSTN_UTILITY_VERSION_STRING env override honoured ───────────

def test_t24_version_override_env_honoured(monkeypatch=None):
    """We cannot mutate the running server's env; instead exercise the
    pure adapter directly with a synthetic canonical payload to prove the
    override path is honoured. This keeps the test hermetic without a
    server restart."""
    import importlib, sys
    sys.path.insert(0, "/app/backend")
    os.environ["GSTN_UTILITY_VERSION_STRING"] = "GST3.2.6"
    try:
        import routers.gst as gst
        importlib.reload(gst)
        env = gst._gstr1_9b_offline_json_projection({
            "issuer_gstin": "29AAAAA1234A1Z5",
            "month": "2030-02", "period": {"start": "2030-02-01", "end": "2030-02-28"},
            "cdnr": [], "cdnur": [], "totals": {},
            "reconciliation": {"reconciled": True},
        })
        assert env["utility_json"]["version"] == "GST3.2.6"
        assert env["meta"]["version_string"] == "GST3.2.6"
        assert env["meta"]["version_default"] == "3.2"
    finally:
        os.environ.pop("GSTN_UTILITY_VERSION_STRING", None)
        import routers.gst as gst
        importlib.reload(gst)
