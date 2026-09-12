"""Iter150F · Reconciliation Center — pure read/compare service.

READ-ONLY. Zero writes. Zero source mutation. Zero index creation.
Zero background jobs. Treats `services_fin_txn` as an immutable API.

Tolerances (frozen · BD-2):
    FIN_ABS_EPS      = 0.01
    AR_REL_TOLERANCE = 0.05
    AR_MIN_ABS       = 1.00

Domains (frozen · BD-1):
    A · Source ↔ FinTxn
    B · Expense total ↔ EXPENSE_DEFAULT
    C · Invoice balance_due ↔ AR net
    D · CN/DN issued totals ↔ AR CN/DN legs
    E · Wallet balances
    F · VendorBill / MechanicWO paired invariant
    G · Projection Health
    H · Day Closing snapshot ↔ live
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from db import db
from services_fin_txn import SUPPORTED_SOURCE_TYPES

FIN_ABS_EPS = 0.01
AR_REL_TOLERANCE = 0.05
AR_MIN_ABS = 1.00

SOURCE_TO_COLL = {
    "invoice": "invoices",
    "credit_debit_note": "credit_debit_notes",
    "supplier_payment": "supplier_payments",
    "vendor_payment": "vendor_payments",
    "mechanic_payment": "mechanic_payments",
    "expense": "expenses",
    "vendor_bill": "vendor_bills",
    "mechanic_work_order": "mechanic_work_orders",
    "trip_customer_receipt": "trips",
    "wallet_recharge": "wallet_recharges",
    "wallet_transfer": "wallet_transfers",
    "wallet_adjustment": "wallet_adjustments",
}
SOURCE_DATE_FIELD = {
    "invoice": "invoice_date",
    "credit_debit_note": "note_date",
    "supplier_payment": "date",
    "vendor_payment": "date",
    "mechanic_payment": "date",
    "expense": "date",
    "vendor_bill": "bill_date",
    "mechanic_work_order": "work_date",
    "trip_customer_receipt": "date",
    "wallet_recharge": "date",
    "wallet_transfer": "date",
    "wallet_adjustment": "date",
}
WALLET_CODES = ["WALLET_FUEL", "WALLET_FASTAG"]

BD5_NOTE = (
    "Day Closing snapshots do not auto-refresh after late entries. "
    "Reopen the day to re-close if you want the snapshot updated."
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _q(uid: str, cid: str) -> Dict[str, Any]:
    return {"user_id": uid, "company_id": cid}


def _date_range(from_: str, to_: str, field: str) -> Dict[str, Any]:
    if not from_ and not to_:
        return {}
    r: Dict[str, Any] = {}
    if from_:
        r["$gte"] = from_
    if to_:
        r["$lte"] = to_
    return {field: r}


def _is_alive(doc: dict) -> bool:
    return not doc.get("is_deleted") and not doc.get("is_reversed")


def _kind_dead(doc: dict) -> bool:
    return bool(doc.get("is_deleted") or doc.get("is_reversed"))


# ── Domain A ──────────────────────────────────────────────────────
async def domain_a(uid: str, cid: str, from_: str, to_: str,
                    page: int = 1, size: int = 100) -> Dict[str, Any]:
    rows: List[dict] = []
    for st in SUPPORTED_SOURCE_TYPES:
        coll = SOURCE_TO_COLL.get(st)
        if not coll:
            continue
        date_field = SOURCE_DATE_FIELD[st]
        q = _q(uid, cid)
        q.update(_date_range(from_, to_, date_field))
        src_docs: Dict[str, dict] = {}
        async for d in db[coll].find(q, {"_id": 0, "id": 1,
                                          "is_deleted": 1, "is_reversed": 1,
                                          "is_historical": 1}):
            if d.get("is_historical"):
                continue
            src_docs[d["id"]] = d
        projected_ids: set = set()
        async for row in db.fin_txn.find(
            {**_q(uid, cid), "source_type": st,
             **_date_range(from_, to_, "txn_date")},
            {"_id": 0, "source_id": 1},
        ):
            sid = row.get("source_id") or ""
            # For trip_customer_receipt legs the source_id is "trip:rid"
            root = sid.split(":", 1)[0] if st == "trip_customer_receipt" else sid
            projected_ids.add(root)
        for sid, d in src_docs.items():
            has_proj = sid in projected_ids
            if _is_alive(d) and not has_proj:
                rows.append({"key": f"{st}:{sid}", "source": 1,
                             "projected": 0, "delta": -1,
                             "status": "rose",
                             "note": "alive source · missing legs",
                             "source_type": st, "source_id": sid,
                             "last_checked": _now_iso()})
            elif _kind_dead(d) and has_proj:
                rows.append({"key": f"{st}:{sid}", "source": 0,
                             "projected": 1, "delta": 1,
                             "status": "rose",
                             "note": "dead source · ghost legs",
                             "source_type": st, "source_id": sid,
                             "last_checked": _now_iso()})
        # Ghost-only detection (source doc completely absent).
        ghosts = projected_ids - set(src_docs.keys())
        for sid in ghosts:
            rows.append({"key": f"{st}:{sid}", "source": 0,
                         "projected": 1, "delta": 1, "status": "rose",
                         "note": "orphan legs · source missing",
                         "source_type": st, "source_id": sid,
                         "last_checked": _now_iso()})
    total = len(rows)
    page = max(1, int(page or 1))
    size = max(1, min(int(size or 100), 500))
    start = (page - 1) * size
    return {"rows": rows[start:start + size], "total": total,
            "page": page, "size": size}


# ── Domain B ──────────────────────────────────────────────────────
async def domain_b(uid: str, cid: str, from_: str, to_: str) -> dict:
    src = 0.0
    q = {**_q(uid, cid),
         "is_deleted": {"$ne": True}, "is_reversed": {"$ne": True},
         "is_historical": {"$ne": True}}
    q.update(_date_range(from_, to_, "date"))
    async for e in db.expenses.find(q, {"_id": 0, "amount": 1}):
        v = float(e.get("amount") or 0)
        if v > 0:
            src += v
    proj = 0.0
    async for r in db.fin_txn.find(
        {**_q(uid, cid), "account_code": "EXPENSE_DEFAULT",
         "direction": "in",
         **_date_range(from_, to_, "txn_date")},
        {"_id": 0, "amount": 1},
    ):
        proj += float(r.get("amount") or 0)
    src, proj = round(src, 2), round(proj, 2)
    delta = round(proj - src, 2)
    status = "rose" if abs(delta) > FIN_ABS_EPS else "emerald"
    return {"key": "expense_total", "source": src, "projected": proj,
            "delta": delta, "status": status,
            "last_checked": _now_iso()}


# ── Domain C ──────────────────────────────────────────────────────
async def domain_c(uid: str, cid: str, from_: str, to_: str) -> dict:
    src = 0.0
    async for inv in db.invoices.find(
        {**_q(uid, cid), "is_historical": {"$ne": True},
         **_date_range(from_, to_, "invoice_date")},
        {"_id": 0, "balance_due": 1},
    ):
        src += float(inv.get("balance_due") or 0)
    ar_in = ar_out = 0.0
    async for r in db.fin_txn.find(
        {**_q(uid, cid), "account_code": "AR",
         **_date_range(from_, to_, "txn_date")},
        {"_id": 0, "amount": 1, "direction": 1},
    ):
        v = float(r.get("amount") or 0)
        if r.get("direction") == "in":
            ar_in += v
        else:
            ar_out += v
    proj = round(ar_in - ar_out, 2)
    src = round(src, 2)
    delta = round(proj - src, 2)
    threshold = max(AR_MIN_ABS, AR_REL_TOLERANCE * max(src, 1.0))
    if abs(delta) <= FIN_ABS_EPS:
        status = "emerald"
    elif abs(delta) <= threshold:
        status = "amber"
    else:
        status = "rose"
    return {"key": "ar_vs_balance_due", "source": src, "projected": proj,
            "delta": delta, "status": status,
            "threshold": round(threshold, 2),
            "note": ("Iter132a legacy: CN/DN offsets not applied to "
                     "Invoice.balance_due — small deltas expected."),
            "last_checked": _now_iso()}


# ── Domain D ──────────────────────────────────────────────────────
async def domain_d(uid: str, cid: str, from_: str, to_: str) -> List[dict]:
    out: List[dict] = []
    for kind, in_dir in (("credit", "out"), ("debit", "in")):
        src = 0.0
        async for n in db.credit_debit_notes.find(
            {**_q(uid, cid), "status": "issued",
             "is_historical": {"$ne": True}, "kind": kind,
             **_date_range(from_, to_, "note_date")},
            {"_id": 0, "total_amount": 1},
        ):
            src += float(n.get("total_amount") or 0)
        proj = 0.0
        async for r in db.fin_txn.find(
            {**_q(uid, cid), "source_type": "credit_debit_note",
             "account_code": "AR", "direction": in_dir,
             **_date_range(from_, to_, "txn_date")},
            {"_id": 0, "amount": 1},
        ):
            proj += float(r.get("amount") or 0)
        src, proj = round(src, 2), round(proj, 2)
        delta = round(proj - src, 2)
        status = "rose" if abs(delta) > FIN_ABS_EPS else "emerald"
        out.append({"key": kind, "source": src, "projected": proj,
                    "delta": delta, "status": status,
                    "last_checked": _now_iso()})
    return out


# ── Domain E ──────────────────────────────────────────────────────
async def domain_e(uid: str, cid: str, from_: str, to_: str) -> List[dict]:
    out: List[dict] = []
    for code in WALLET_CODES:
        in_ = out_ = 0.0
        async for r in db.fin_txn.find(
            {**_q(uid, cid), "account_code": code,
             **_date_range(from_, to_, "txn_date")},
            {"_id": 0, "amount": 1, "direction": 1},
        ):
            v = float(r.get("amount") or 0)
            if r.get("direction") == "in":
                in_ += v
            else:
                out_ += v
        # Live-expected: recharges − consumption(EXPENSE via WALLET_*) ± adjustments ± transfers.
        recharge = consumption = adj_up = adj_down = tr_in = tr_out = 0.0
        async for w in db.wallet_recharges.find(
            {**_q(uid, cid), "is_deleted": {"$ne": True},
             "wallet_code": code, **_date_range(from_, to_, "date")},
            {"_id": 0, "amount": 1},
        ):
            recharge += float(w.get("amount") or 0)
        exp_src = "fastag_import" if code == "WALLET_FASTAG" else "fleet_card_import"
        async for e in db.expenses.find(
            {**_q(uid, cid), "is_deleted": {"$ne": True},
             "is_reversed": {"$ne": True}, "is_historical": {"$ne": True},
             "source_type": exp_src, **_date_range(from_, to_, "date")},
            {"_id": 0, "amount": 1},
        ):
            consumption += float(e.get("amount") or 0)
        async for a in db.wallet_adjustments.find(
            {**_q(uid, cid), "is_deleted": {"$ne": True},
             "wallet_code": code, **_date_range(from_, to_, "date")},
            {"_id": 0, "amount": 1, "direction": 1},
        ):
            v = float(a.get("amount") or 0)
            if a.get("direction") == "increase":
                adj_up += v
            elif a.get("direction") == "decrease":
                adj_down += v
        async for t in db.wallet_transfers.find(
            {**_q(uid, cid), "is_deleted": {"$ne": True},
             **_date_range(from_, to_, "date")},
            {"_id": 0, "amount": 1, "source_wallet_code": 1,
             "destination_wallet_code": 1},
        ):
            v = float(t.get("amount") or 0)
            if t.get("destination_wallet_code") == code:
                tr_in += v
            if t.get("source_wallet_code") == code:
                tr_out += v
        expected = round(recharge - consumption + adj_up - adj_down + tr_in - tr_out, 2)
        live_net = round(in_ - out_, 2)
        delta = round(live_net - expected, 2)
        status = "rose" if abs(delta) > FIN_ABS_EPS else "emerald"
        out.append({"key": code, "source": expected, "projected": live_net,
                    "delta": delta, "status": status,
                    "last_checked": _now_iso()})
    return out


# ── Domain F ──────────────────────────────────────────────────────
async def domain_f(uid: str, cid: str, from_: str, to_: str) -> List[dict]:
    rows: List[dict] = []
    for (coll, id_field, src_type, orphan_type, date_field) in [
        ("vendor_bills", "vendor_bill_id", "vendor_bill",
         "vendor_bill_orphan", "bill_date"),
        ("mechanic_work_orders", "mechanic_work_order_id",
         "mechanic_work_order", "mechanic_wo_orphan", "work_date"),
    ]:
        async for d in db[coll].find(
            {**_q(uid, cid), "is_deleted": {"$ne": True},
             **_date_range(from_, to_, date_field)},
            {"_id": 0, "id": 1},
        ):
            did = d["id"]
            paired = await db.expenses.count_documents(
                {**_q(uid, cid), id_field: did,
                 "is_deleted": {"$ne": True}, "is_reversed": {"$ne": True}})
            has_orphan_leg = bool(await db.fin_txn.find_one(
                {**_q(uid, cid), "source_type": src_type,
                 "source_id": did, "txn_type": orphan_type},
                {"_id": 0, "id": 1}))
            status = None
            note = ""
            if paired == 0 and not has_orphan_leg:
                status, note = "rose", "no paired expense · no orphan legs"
            elif paired >= 2:
                status, note = "rose", f"{paired} paired expenses · double-count risk"
            elif paired >= 1 and has_orphan_leg:
                status, note = "rose", "paired expense + orphan legs coexist"
            if status:
                rows.append({"key": did, "source": paired,
                             "projected": (1 if has_orphan_leg else 0),
                             "delta": 0, "status": status, "note": note,
                             "source_type": src_type, "source_id": did,
                             "last_checked": _now_iso()})
    return rows


# ── Domain G ──────────────────────────────────────────────────────
async def domain_g(uid: str, cid: str, from_: str, to_: str) -> List[dict]:
    rows: List[dict] = []
    async for f in db.fin_hook_failures.find(
        {**_q(uid, cid),
         "status": {"$in": ["pending", "retrying", "permanently_failed"]}},
        {"_id": 0},
    ):
        st = f.get("status")
        status = "rose" if st == "permanently_failed" else "amber"
        rows.append({"key": f.get("id", ""), "source": None,
                     "projected": None, "delta": None, "status": status,
                     "note": f"{st} · retry_count={f.get('retry_count', 0)}",
                     "source_type": f.get("source_type"),
                     "source_id": f.get("source_id"),
                     "hook_status": st,
                     "last_checked": _now_iso()})
    return rows


# ── Domain H ──────────────────────────────────────────────────────
async def domain_h(uid: str, cid: str, from_: str, to_: str) -> List[dict]:
    rows: List[dict] = []
    async for c in db.fin_day_closures.find(
        {**_q(uid, cid),
         **_date_range(from_, to_, "close_date")},
        {"_id": 0, "close_date": 1, "accounts": 1, "status": 1},
    ):
        close_date = c.get("close_date") or ""
        for snap in (c.get("accounts") or []):
            code = snap.get("account_code")
            snap_bal = round(float(snap.get("closing_balance") or 0), 2)
            in_ = out_ = 0.0
            async for r in db.fin_txn.find(
                {**_q(uid, cid), "account_code": code,
                 "txn_date": {"$lte": close_date}},
                {"_id": 0, "amount": 1, "direction": 1},
            ):
                v = float(r.get("amount") or 0)
                if r.get("direction") == "in":
                    in_ += v
                else:
                    out_ += v
            live = round(in_ - out_, 2)
            delta = round(live - snap_bal, 2)
            if abs(delta) <= FIN_ABS_EPS:
                continue
            rows.append({"key": f"{close_date}:{code}",
                         "source": snap_bal, "projected": live,
                         "delta": delta, "status": "amber",
                         "note": BD5_NOTE,
                         "close_date": close_date, "account_code": code,
                         "last_checked": _now_iso()})
    return rows


# ── Summary aggregator ────────────────────────────────────────────
async def summary(uid: str, cid: str, from_: str, to_: str) -> Dict[str, Any]:
    a = await domain_a(uid, cid, from_, to_, page=1, size=500)
    b = await domain_b(uid, cid, from_, to_)
    c = await domain_c(uid, cid, from_, to_)
    d = await domain_d(uid, cid, from_, to_)
    e = await domain_e(uid, cid, from_, to_)
    f = await domain_f(uid, cid, from_, to_)
    g = await domain_g(uid, cid, from_, to_)
    h = await domain_h(uid, cid, from_, to_)

    def _agg(rows: List[dict]) -> Dict[str, Any]:
        if not rows:
            return {"status": "emerald", "count": 0}
        has_rose = any(r["status"] == "rose" for r in rows)
        has_amber = any(r["status"] == "amber" for r in rows)
        return {"status": "rose" if has_rose else ("amber" if has_amber else "emerald"),
                "count": len(rows)}

    def _one(x: dict) -> Dict[str, Any]:
        return {"status": x["status"],
                "count": 0 if x["status"] == "emerald" else 1,
                "delta": x.get("delta")}

    return {
        "period": {"from": from_, "to": to_},
        "company_id": cid,
        "computed_at": _now_iso(),
        "kpis": {
            "A": {"status": _agg(a["rows"])["status"], "count": a["total"]},
            "B": _one(b),
            "C": _one(c),
            "D": _agg(d),
            "E": _agg(e),
            "F": _agg(f),
            "G": _agg(g),
            "H": _agg(h),
        },
        "bd5_note": BD5_NOTE,
        "warnings": [],
    }


async def domain(uid: str, cid: str, name: str, from_: str, to_: str,
                  page: int = 1, size: int = 100) -> Dict[str, Any]:
    name = (name or "").upper()
    dispatch = {"A": None, "B": None, "C": None, "D": None, "E": None,
                "F": None, "G": None, "H": None}
    if name not in dispatch:
        raise ValueError(f"unsupported domain: {name}")
    if name == "A":
        r = await domain_a(uid, cid, from_, to_, page=page, size=size)
        return {"domain": "A", "period": {"from": from_, "to": to_},
                "page": r["page"], "size": r["size"], "total": r["total"],
                "computed_at": _now_iso(), "rows": r["rows"]}
    if name == "B":
        row = await domain_b(uid, cid, from_, to_)
        rows = [row]
    elif name == "C":
        row = await domain_c(uid, cid, from_, to_)
        rows = [row]
    elif name == "D":
        rows = await domain_d(uid, cid, from_, to_)
    elif name == "E":
        rows = await domain_e(uid, cid, from_, to_)
    elif name == "F":
        rows = await domain_f(uid, cid, from_, to_)
    elif name == "G":
        rows = await domain_g(uid, cid, from_, to_)
    else:  # H
        rows = await domain_h(uid, cid, from_, to_)
    page = max(1, int(page or 1))
    size = max(1, min(int(size or 100), 500))
    start = (page - 1) * size
    return {"domain": name, "period": {"from": from_, "to": to_},
            "page": page, "size": size, "total": len(rows),
            "computed_at": _now_iso(), "rows": rows[start:start + size]}


async def mismatch(uid: str, cid: str, name: str, key: str) -> Dict[str, Any]:
    """Return a single-row detail with source drill + leg drill hints.
    key parses to `{source_type}:{source_id}` for A/F/G, else opaque."""
    name = (name or "").upper()
    d = await domain(uid, cid, name, "", "", page=1, size=500)
    matching = next((r for r in d["rows"] if r.get("key") == key), None)
    if not matching:
        return {"domain": name, "key": key, "found": False,
                "computed_at": _now_iso()}
    src_ref = None
    leg_refs: List[dict] = []
    st = matching.get("source_type")
    sid = matching.get("source_id")
    if st and sid:
        src_ref = {"source_type": st, "source_id": sid,
                   "endpoint": f"/api/fin/source/{st}/{sid}"}
        leg_refs.append({"endpoint": f"/api/fin/source-legs/{st}/{sid}"})
    corrective = None
    if name in ("A", "F", "G") and st and sid:
        corrective = {"endpoint": "POST /api/fin/reproject",
                      "owner_only": True,
                      "payload": {"source_type": st, "source_id": sid}}
    return {"domain": name, "key": key, "found": True,
            "source": matching.get("source"),
            "projected": matching.get("projected"),
            "delta": matching.get("delta"),
            "status": matching.get("status"),
            "note": matching.get("note", ""),
            "source_doc_ref": src_ref,
            "fin_txn_leg_refs": leg_refs,
            "corrective_action_hint": corrective,
            "computed_at": _now_iso()}
