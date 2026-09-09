"""Iter147 P0 · Fleet-card Fuel Import — parsers + preview/commit engine.

TRUKVIA principle:
  ENTER ONCE → CALCULATE ONCE → REFLECT EVERYWHERE → REPORT READY.

One real-world Diesel transaction produces exactly ONE canonical Expense
(category="Diesel", source_type="fleet_card_import"). No paired db.fuel
row. Vehicle Cost / Expense Register / Trip Cost read canonical only —
so the imported Diesel is reflected everywhere without a second truth.

Supported real-world formats (approved fixtures under
`backend/tests/fixtures/iter147/`):
  • IOCL Customer Transaction Details Report — legacy .xls (BIFF).
      Header row is detected dynamically (row containing "SNo." + "Txn ID").
      Only rows where `Txn Type == "Sale"` AND `Product == "DIESEL"`
      are treated as fuel; Recharge / Loyalty Award / Loyalty Redeem /
      XTRAPoints rows are filtered.
      IOCL prints many cells with a trailing apostrophe (`"08/09/2026 14:11:25'"`);
      the parser strips these.
  • BPCL Sale Transaction history report — .xlsx.
      Header row detected by "Transaction ID" + "Product Name".
      Only rows where `Product Name == "Diesel"` are kept.

XOR-safe duplicate scan (reuses Iter133 canonical/legacy invariants):
  possible-duplicate lanes for (company_id, resolved vehicle_id, date):
    A. canonical Expense{category="Diesel"} within ±1 day
    B. legacy db.fuel within ±1 day (read-only projection)
    C. legacy Trip.expenses.diesel — ONLY for trips where
       `has_canonical_expenses = false` (XOR safe; canonical already
       covers the rest).
Similarity score requires match on litres OR amount OR station in
addition to (date ± 1 day, same resolved vehicle). Date + vehicle
alone is NEVER a duplicate — a truck may refuel multiple times a day.
"""
from __future__ import annotations

import hashlib
import io
import re
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

from db import db

# ── Config ─────────────────────────────────────────────────────────────
MAX_ROWS_P0 = 2000
POSSIBLE_DUP_LITRES_TOL = 0.03     # ±3 %
POSSIBLE_DUP_AMOUNT_TOL = 0.02     # ±2 %
POSSIBLE_DUP_DATE_WINDOW_DAYS = 1  # ±1 day


# ── Utilities ──────────────────────────────────────────────────────────
def _q2(x) -> float:
    try:
        return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    except Exception:
        return 0.0


def _clean(cell) -> str:
    """Strip IOCL trailing/leading apostrophe artefacts + whitespace."""
    if cell is None:
        return ""
    s = str(cell).strip()
    if s.startswith("'"):
        s = s[1:]
    if s.endswith("'"):
        s = s[:-1]
    return s.strip()


def _to_float(cell) -> float:
    """Coerce a cell value to float. Handles BPCL numeric strings with commas."""
    if cell is None:
        return 0.0
    s = _clean(cell).replace(",", "")
    if s in ("", "-", "N/A", "n/a"):
        return 0.0
    try:
        return float(s)
    except Exception:
        return 0.0


def _iocl_date(cell) -> str:
    """`08/09/2026 14:11:25'` → `2026-09-08` (dd/mm/yyyy → ISO). Empty on fail."""
    s = _clean(cell)
    if not s:
        return ""
    part = s.split(" ")[0]
    try:
        return datetime.strptime(part, "%d/%m/%Y").strftime("%Y-%m-%d")
    except Exception:
        return ""


def _bpcl_date(cell) -> str:
    """`08-Sep-2026` (or datetime obj) → `2026-09-08`."""
    if cell is None:
        return ""
    if isinstance(cell, datetime):
        return cell.strftime("%Y-%m-%d")
    s = _clean(cell)
    for fmt in ("%d-%b-%Y", "%d %b %Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except Exception:
            continue
    return ""


def _iso_ok(s: str) -> bool:
    try:
        datetime.strptime(s or "", "%Y-%m-%d")
        return True
    except Exception:
        return False


def _slug(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", s or "").strip("_").upper()


def _content_key(source: str, cid: str, source_vehicle_ref: str, date: str,
                 litres: float, amount: float, station: str) -> str:
    """Fallback exact-duplicate key when the statement lacks a txn ref."""
    raw = f"{source}|{cid}|{source_vehicle_ref}|{date}|{litres:.3f}|{amount:.2f}|{station.upper()}"
    return "sha1:" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]


def make_source_key(source: str, cid: str, source_txn_ref: str,
                    fallback_hash: str) -> str:
    """Deterministic canonical source_key for fleet-card imports."""
    if source_txn_ref:
        return f"fuel:{source}:{cid}:{source_txn_ref}"
    return f"fuel:{source}:{cid}:{fallback_hash}"


# ── Format detection ───────────────────────────────────────────────────
def detect_source(filename: str, blob: bytes) -> Optional[str]:
    """Return "iocl" | "bpcl" | None.

    Content-sniff first (bytes signature), extension is a hint only.
    """
    if not blob:
        return None
    name = (filename or "").lower()
    # BPCL (.xlsx / zip magic PK\x03\x04)
    if blob[:4] == b"PK\x03\x04":
        try:
            from openpyxl import load_workbook
            wb = load_workbook(io.BytesIO(blob), data_only=True, read_only=True)
            ws = wb.active
            # Inspect first ~12 rows for BPCL signature.
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i >= 12:
                    break
                joined = " ".join(str(c or "").lower() for c in row)
                if "sale transaction history report" in joined or "bharat petroleum" in joined:
                    return "bpcl"
            return None
        except Exception:
            return None
    # IOCL (.xls BIFF starts with D0 CF 11 E0 A1 B1 1A E1 — OLE2 CFB)
    if blob[:4] == b"\xd0\xcf\x11\xe0":
        try:
            import xlrd
            book = xlrd.open_workbook(file_contents=blob)
            sh = book.sheet_by_index(0)
            for r in range(min(sh.nrows, 15)):
                joined = " ".join(_clean(sh.cell_value(r, c)).lower()
                                  for c in range(min(sh.ncols, 6)))
                if "customer transaction details report" in joined or \
                   "transaction summary (ccms)" in joined:
                    return "iocl"
            return None
        except Exception:
            return None
    # Extension-based fallback for edge cases (rare)
    if name.endswith(".xls"):
        return "iocl" if _looks_like_iocl(blob) else None
    if name.endswith(".xlsx"):
        return "bpcl" if _looks_like_bpcl(blob) else None
    return None


def _looks_like_iocl(blob: bytes) -> bool:
    try:
        import xlrd
        book = xlrd.open_workbook(file_contents=blob)
        sh = book.sheet_by_index(0)
        return any(
            "iocl" in _clean(sh.cell_value(r, c)).lower() or
            "customer transaction" in _clean(sh.cell_value(r, c)).lower()
            for r in range(min(sh.nrows, 15)) for c in range(min(sh.ncols, 4))
        )
    except Exception:
        return False


def _looks_like_bpcl(blob: bytes) -> bool:
    try:
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(blob), data_only=True, read_only=True)
        ws = wb.active
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i >= 12:
                break
            joined = " ".join(str(c or "").lower() for c in row)
            if "sale transaction history report" in joined:
                return True
        return False
    except Exception:
        return False


# ── Parsers ────────────────────────────────────────────────────────────
def parse_iocl(blob: bytes) -> list[dict]:
    """Return list of normalised fuel rows. Non-Diesel rows filtered.

    Each row: dict with keys — source, source_txn_ref, source_vehicle_ref,
    date, litres, rate, amount, station_name, odometer, row_index, error.
    """
    import xlrd
    rows: list[dict] = []
    book = xlrd.open_workbook(file_contents=blob)
    sh = book.sheet_by_index(0)
    header_row: Optional[int] = None
    for r in range(sh.nrows):
        first = _clean(sh.cell_value(r, 0)).lower()
        if first == "sno." or first == "sno":
            header_row = r
            break
    if header_row is None:
        return rows  # no header — treated as unrecognised upstream

    # Map header labels → column index for resilience against minor drift.
    headers = {_clean(sh.cell_value(header_row, c)).lower(): c
               for c in range(sh.ncols)}
    col_txn_type = headers.get("txn type", 12)
    col_product = headers.get("product", 15)
    col_veh_card = headers.get("vehicle no. (card)", 8)
    col_veh_user = headers.get("vehicleno (user entry)", 30)
    col_txn_id = headers.get("txn id", 9)
    col_txn_date = headers.get("txn date", 10)
    col_rsp = headers.get("rsp", 17)
    col_qty = headers.get("quantity", 18)
    col_amount = headers.get("amount", 20)
    col_odo = headers.get("odometer (user entry)", 22)
    col_merchant = headers.get("merchant name", 3)
    col_location = headers.get("location", 6)

    for r in range(header_row + 1, sh.nrows):
        row_vals = [_clean(sh.cell_value(r, c)) for c in range(sh.ncols)]
        if not any(row_vals):
            continue
        tt = row_vals[col_txn_type].lower() if col_txn_type < sh.ncols else ""
        prod = row_vals[col_product].lower() if col_product < sh.ncols else ""
        if tt != "sale" or "diesel" not in prod:
            continue
        vref = row_vals[col_veh_card] if col_veh_card < sh.ncols else ""
        if not vref or vref in ("-", "N/A"):
            vref = row_vals[col_veh_user] if col_veh_user < sh.ncols else ""
        txn_ref = _clean(sh.cell_value(r, col_txn_id)) if col_txn_id < sh.ncols else ""
        # IOCL prints Txn IDs as floats; normalise "1397005766.0" → "1397005766"
        if txn_ref and txn_ref.endswith(".0"):
            txn_ref = txn_ref[:-2]
        date_iso = _iocl_date(sh.cell_value(r, col_txn_date)) if col_txn_date < sh.ncols else ""
        litres = _to_float(sh.cell_value(r, col_qty)) if col_qty < sh.ncols else 0.0
        rate = _to_float(sh.cell_value(r, col_rsp)) if col_rsp < sh.ncols else 0.0
        amount = _to_float(sh.cell_value(r, col_amount)) if col_amount < sh.ncols else 0.0
        odo = _to_float(sh.cell_value(r, col_odo)) if col_odo < sh.ncols else 0.0
        station_parts = []
        if col_merchant < sh.ncols and row_vals[col_merchant]:
            station_parts.append(row_vals[col_merchant])
        if col_location < sh.ncols and row_vals[col_location]:
            station_parts.append(row_vals[col_location])
        station = " · ".join(station_parts).strip()
        err = None
        if not date_iso:
            err = "Missing or invalid Txn Date"
        elif litres <= 0 or amount <= 0:
            err = "Litres/Amount must be > 0"
        elif not vref:
            err = "Missing Vehicle reference"
        rows.append({
            "source": "iocl",
            "source_txn_ref": txn_ref,
            "source_vehicle_ref": vref,
            "date": date_iso,
            "litres": _q2(litres),
            "rate": _q2(rate),
            "amount": _q2(amount),
            "station_name": station[:200],
            "odometer": _q2(odo),
            "row_index": r + 1,     # 1-based for user display
            "error": err,
        })
    return rows


def parse_bpcl(blob: bytes) -> list[dict]:
    """Return list of normalised fuel rows. Non-Diesel rows filtered."""
    from openpyxl import load_workbook
    rows: list[dict] = []
    wb = load_workbook(io.BytesIO(blob), data_only=True, read_only=True)
    ws = wb.active
    header_row_idx: Optional[int] = None
    header_row_vals: list = []
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        cells = [str(c or "").strip() for c in row]
        joined = " | ".join(cells).lower()
        if "transaction id" in joined and "product name" in joined:
            header_row_idx = i
            header_row_vals = cells
            break
    if header_row_idx is None:
        return rows

    headers = {h.lower(): idx for idx, h in enumerate(header_row_vals) if h}
    col_txn_id = headers.get("transaction id", 1)
    col_date = headers.get("transaction date", 2)
    col_veh = headers.get("vehicle number", 8)
    col_ccn = headers.get("custom card name", 7)
    col_card = headers.get("card number", 6)
    col_station = headers.get("fuel station name (retail outlet name)", 11)
    col_station_city = headers.get("fuel station (retail outlet) city", 15)
    col_product = headers.get("product name", 20)
    col_qty = headers.get("product volume /  quantity (litres)", 21)
    col_rate = headers.get("rate (rs. / litre)", 22)
    col_purchase = headers.get("purchase amount(rs.)", 23)
    col_total = headers.get("total transaction amount (rs.)", 25)

    all_rows = list(ws.iter_rows(values_only=True))
    for r_idx in range(header_row_idx + 1, len(all_rows)):
        row = all_rows[r_idx]
        if not any(row):
            continue
        prod = str(row[col_product] or "").strip().lower() if col_product < len(row) else ""
        if prod != "diesel":
            continue
        txn_ref = str(row[col_txn_id] or "").strip() if col_txn_id < len(row) else ""
        date_iso = _bpcl_date(row[col_date]) if col_date < len(row) else ""
        veh_no = str(row[col_veh] or "").strip() if col_veh < len(row) else ""
        ccn = str(row[col_ccn] or "").strip() if col_ccn < len(row) else ""
        card = str(row[col_card] or "").strip() if col_card < len(row) else ""
        vref = veh_no or ccn or card
        litres = _to_float(row[col_qty]) if col_qty < len(row) else 0.0
        rate = _to_float(row[col_rate]) if col_rate < len(row) else 0.0
        amount = _to_float(row[col_total]) if col_total < len(row) else 0.0
        if amount <= 0 and col_purchase < len(row):
            amount = _to_float(row[col_purchase])
        station_parts = []
        if col_station < len(row) and row[col_station]:
            station_parts.append(str(row[col_station]).strip())
        if col_station_city < len(row) and row[col_station_city]:
            station_parts.append(str(row[col_station_city]).strip())
        station = " · ".join(p for p in station_parts if p)
        err = None
        if not date_iso:
            err = "Missing or invalid Transaction Date"
        elif litres <= 0 or amount <= 0:
            err = "Litres/Amount must be > 0"
        elif not vref:
            err = "Missing Vehicle reference"
        rows.append({
            "source": "bpcl",
            "source_txn_ref": txn_ref,
            "source_vehicle_ref": vref,
            "date": date_iso,
            "litres": _q2(litres),
            "rate": _q2(rate),
            "amount": _q2(amount),
            "station_name": station[:200],
            "odometer": 0.0,
            "row_index": r_idx + 1,
            "error": err,
        })
    return rows


def parse_fuel_file(filename: str, blob: bytes) -> tuple[Optional[str], list[dict]]:
    """Detect + parse. Returns (source, rows). source=None → unrecognised."""
    src = detect_source(filename, blob)
    if src == "iocl":
        return "iocl", parse_iocl(blob)
    if src == "bpcl":
        return "bpcl", parse_bpcl(blob)
    return None, []


# ── Preview orchestrator ───────────────────────────────────────────────
async def build_preview(uid: str, cid: str, source: str, rows: list[dict]) -> dict:
    """Bucket every parsed row into one of:
        ready · vehicle_mapping_required · possible_duplicate ·
        exact_duplicate · error

    Enriches every row with `resolved_vehicle_id` / `resolved_vehicle_number`
    where a mapping exists, and adds a `source_key` for exact-duplicate id.
    """
    # ── 1 · load all mappings for this (company, source) ────────────
    map_docs = await db.fuel_vehicle_maps.find(
        {"user_id": uid, "company_id": cid, "source": source},
        {"_id": 0, "user_id": 0},
    ).to_list(5000)
    mapping = {(m["source"], m["source_vehicle_ref"]): m for m in map_docs}

    unmapped_refs: dict[str, dict] = {}
    processed: list[dict] = []

    # ── 2 · walk rows in one pass ───────────────────────────────────
    seen_source_keys: dict[str, int] = {}   # in-file duplicate detection
    for idx, r in enumerate(rows):
        enriched = dict(r)
        if r.get("error"):
            enriched["bucket"] = "error"
            processed.append(enriched)
            continue
        vref = r["source_vehicle_ref"]
        m = mapping.get((source, vref))
        if not m:
            key = f"{source}::{vref}"
            unmapped_refs.setdefault(key, {
                "source": source, "source_vehicle_ref": vref,
                "sample_row_index": r["row_index"],
                "count": 0,
            })
            unmapped_refs[key]["count"] += 1
            enriched["bucket"] = "vehicle_mapping_required"
            enriched["resolved_vehicle_id"] = ""
            enriched["resolved_vehicle_number"] = ""
            processed.append(enriched)
            continue

        enriched["resolved_vehicle_id"] = m["vehicle_id"]
        enriched["resolved_vehicle_number"] = m.get("vehicle_number", "")

        # Deterministic source_key for exact-duplicate identity.
        fallback = _content_key(source, cid, vref, r["date"],
                                r["litres"], r["amount"], r["station_name"])
        skey = make_source_key(source, cid, r.get("source_txn_ref", ""), fallback)
        enriched["source_key"] = skey

        # ── in-file duplicate → hard exact-dup (last one wins the bucket) ──
        if skey in seen_source_keys:
            enriched["bucket"] = "exact_duplicate"
            enriched["duplicate_reason"] = f"Duplicate within this file (row {seen_source_keys[skey]})"
            processed.append(enriched)
            continue
        seen_source_keys[skey] = r["row_index"]

        # ── existing canonical Expense with the same source_key? ──────
        existing = await db.expenses.find_one(
            {"user_id": uid, "company_id": cid, "source_key": skey,
             "is_deleted": {"$ne": True}, "is_reversed": {"$ne": True}},
            {"_id": 0, "id": 1, "date": 1, "amount": 1, "vehicle_number": 1,
             "source": 1, "source_txn_ref": 1},
        )
        if existing:
            enriched["bucket"] = "exact_duplicate"
            enriched["duplicate_reason"] = (
                f"Already imported (Expense {existing['id']}, "
                f"txn {existing.get('source_txn_ref') or '—'})"
            )
            enriched["existing_expense"] = existing
            processed.append(enriched)
            continue

        # ── Possible-duplicate scan across canonical + legacy + trip ──
        pos = await _scan_possible_duplicates(
            uid, cid,
            vehicle_id=m["vehicle_id"],
            vehicle_number=m.get("vehicle_number", ""),
            date=r["date"],
            litres=r["litres"],
            amount=r["amount"],
            station_name=r["station_name"],
        )
        if pos:
            enriched["bucket"] = "possible_duplicate"
            enriched["possible_matches"] = pos
            processed.append(enriched)
            continue

        enriched["bucket"] = "ready"
        processed.append(enriched)

    counts = {b: 0 for b in ("ready", "vehicle_mapping_required",
                             "possible_duplicate", "exact_duplicate", "error")}
    for p in processed:
        counts[p["bucket"]] += 1
    return {
        "source": source,
        "total_rows": len(processed),
        "counts": counts,
        "rows": processed,
        "unmapped_refs": list(unmapped_refs.values()),
    }


async def _scan_possible_duplicates(uid: str, cid: str, *, vehicle_id: str,
                                    vehicle_number: str, date: str,
                                    litres: float, amount: float,
                                    station_name: str) -> list[dict]:
    """XOR-safe scan.  Returns up to 5 potential matches with source labels."""
    if not vehicle_id or not _iso_ok(date):
        return []
    matches: list[dict] = []
    # Date window
    try:
        d = datetime.strptime(date, "%Y-%m-%d")
    except Exception:
        return []
    d_from = (d - timedelta(days=POSSIBLE_DUP_DATE_WINDOW_DAYS)).strftime("%Y-%m-%d")
    d_to = (d + timedelta(days=POSSIBLE_DUP_DATE_WINDOW_DAYS)).strftime("%Y-%m-%d")

    def _similar(row_litres: float, row_amount: float, row_station: str) -> bool:
        """At LEAST one strong signal beyond (date + vehicle)."""
        if litres > 0 and row_litres > 0 and \
                abs(litres - row_litres) / litres <= POSSIBLE_DUP_LITRES_TOL:
            return True
        if amount > 0 and row_amount > 0 and \
                abs(amount - row_amount) / amount <= POSSIBLE_DUP_AMOUNT_TOL:
            return True
        if station_name and row_station and \
                station_name.strip().upper()[:12] == row_station.strip().upper()[:12] and \
                len(station_name.strip()) >= 4:
            return True
        return False

    # ── Lane A · canonical Diesel Expense ────────────────────────────
    canonical_cursor = db.expenses.find({
        "user_id": uid, "company_id": cid,
        "category": "Diesel", "vehicle_id": vehicle_id,
        "date": {"$gte": d_from, "$lte": d_to},
        "is_deleted": {"$ne": True}, "is_reversed": {"$ne": True},
    }, {"_id": 0, "user_id": 0}).limit(50)
    async for c in canonical_cursor:
        # Extract litres from narration heuristically? Just compare amount + station.
        row_litres = 0.0
        row_amount = float(c.get("amount") or 0)
        row_station = str(c.get("narration") or "")
        if _similar(row_litres, row_amount, row_station):
            matches.append({
                "kind": "canonical_expense",
                "source_label": _canonical_source_label(c),
                "id": c.get("id", ""),
                "date": c.get("date", ""),
                "amount": row_amount,
                "vehicle_number": c.get("vehicle_number", ""),
                "narration": row_station[:120],
            })
            if len(matches) >= 5:
                return matches

    # ── Lane B · legacy db.fuel ──────────────────────────────────────
    fuel_cursor = db.fuel.find({
        "user_id": uid, "company_id": cid,
        "$or": [{"vehicle_id": vehicle_id},
                {"vehicle_number": vehicle_number}] if vehicle_number else [{"vehicle_id": vehicle_id}],
        "date": {"$gte": d_from, "$lte": d_to},
    }, {"_id": 0, "user_id": 0}).limit(50)
    async for f in fuel_cursor:
        row_litres = float(f.get("litres") or 0)
        row_amount = float(f.get("amount") or 0)
        row_station = str(f.get("station_name") or "")
        if _similar(row_litres, row_amount, row_station):
            matches.append({
                "kind": "legacy_fuel",
                "source_label": "Legacy Fuel",
                "id": f.get("id", ""),
                "date": f.get("date", ""),
                "amount": row_amount,
                "litres": row_litres,
                "vehicle_number": f.get("vehicle_number", ""),
                "narration": row_station[:120],
            })
            if len(matches) >= 5:
                return matches

    # ── Lane C · Trip legacy Diesel (XOR: only when has_canonical_expenses=false) ──
    trip_cursor = db.trips.find({
        "user_id": uid, "company_id": cid,
        "vehicle_id": vehicle_id,
        "date": {"$gte": d_from, "$lte": d_to},
        "$or": [
            {"has_canonical_expenses": {"$exists": False}},
            {"has_canonical_expenses": False},
        ],
    }, {"_id": 0, "id": 1, "date": 1, "vehicle_number": 1,
         "expenses": 1, "lr_number": 1}).limit(50)
    async for t in trip_cursor:
        ex = (t.get("expenses") or {})
        diesel_amt = float(ex.get("diesel") or 0)
        if diesel_amt <= 0:
            continue
        # Station and litres unknown at trip level for legacy path.
        if _similar(0.0, diesel_amt, ""):
            matches.append({
                "kind": "trip_legacy_diesel",
                "source_label": "Trip Legacy Diesel",
                "id": t.get("id", ""),
                "date": t.get("date", ""),
                "amount": diesel_amt,
                "vehicle_number": t.get("vehicle_number", ""),
                "narration": f"LR {t.get('lr_number', '—')}"[:120],
            })
            if len(matches) >= 5:
                return matches
    return matches


def _canonical_source_label(exp: dict) -> str:
    st = (exp.get("source_type") or "manual").lower()
    if st == "quick_op":
        return "Quick Op"
    if st == "fleet_card_import":
        sub = (exp.get("source") or "").upper() or "Fleet Card"
        return f"{sub} Import"
    if st == "trip_legacy":
        return "Trip Legacy"
    if st == "trip_other_expenditure":
        return "Trip Other Exp"
    return "Manual"


# ── Commit orchestrator ────────────────────────────────────────────────
from fastapi import HTTPException
from models import Expense, now_utc
from pymongo.errors import DuplicateKeyError


async def commit_rows(uid: str, cid: str, source: str,
                      rows_in: list[dict]) -> dict:
    """Persist each provided row as ONE canonical Expense.

    The caller (frontend) is expected to submit only rows the operator
    approved (i.e. ready + `possible_duplicate` overrides). Rows that
    were flagged `exact_duplicate` MUST NOT be resubmitted; the server
    still enforces the exact-key contract via a unique-index attempt.

    Never raises for a row-level problem — those flow through results[].
    """
    # Lazy import to avoid router↔service cycles.
    from routers.expenses import _validate_and_normalise

    if not isinstance(rows_in, list) or not rows_in:
        raise HTTPException(status_code=400, detail="rows must be a non-empty list")
    if len(rows_in) > MAX_ROWS_P0:
        raise HTTPException(status_code=413,
            detail=f"Too many rows ({len(rows_in)} > {MAX_ROWS_P0}); please split the file.")

    batch_id = "fib_" + hashlib.sha1(
        f"{cid}:{now_utc().isoformat()}:{len(rows_in)}".encode()
    ).hexdigest()[:12]

    created = duplicate = failed = 0
    results: list[dict] = []

    for r in rows_in:
        row_ref = str(r.get("row_index") or r.get("source_txn_ref") or "?")
        base = {"row_index": r.get("row_index"), "source_txn_ref": r.get("source_txn_ref", "")}
        if r.get("error"):
            failed += 1
            results.append({**base, "status": "failed", "error": r["error"]})
            continue
        vid = r.get("resolved_vehicle_id") or ""
        if not vid:
            failed += 1
            results.append({**base, "status": "failed",
                            "error": "Row is missing resolved_vehicle_id (vehicle mapping)"})
            continue

        veh = await db.vehicles.find_one(
            {"id": vid, "user_id": uid, "company_id": cid},
            {"_id": 0, "vehicle_number": 1, "is_active": 1},
        )
        if not veh:
            failed += 1
            results.append({**base, "status": "failed",
                            "error": "Vehicle not found in tenant"})
            continue

        litres = float(r.get("litres") or 0)
        rate = float(r.get("rate") or 0)
        amount = float(r.get("amount") or 0)
        if litres <= 0 or amount <= 0:
            failed += 1
            results.append({**base, "status": "failed",
                            "error": "litres and amount must be > 0"})
            continue

        date_iso = str(r.get("date") or "")
        if not _iso_ok(date_iso):
            failed += 1
            results.append({**base, "status": "failed",
                            "error": "Invalid date; expected YYYY-MM-DD"})
            continue

        station = str(r.get("station_name") or "")
        txn_ref = str(r.get("source_txn_ref") or "").strip()
        fallback = _content_key(source, cid, r.get("source_vehicle_ref", ""),
                                date_iso, litres, amount, station)
        skey = r.get("source_key") or make_source_key(source, cid, txn_ref, fallback)

        # narration = "{L} L @ ₹{rate} · station"
        narration_parts = [f"{litres} L @ ₹{rate:.2f}"]
        if station:
            narration_parts.append(station)
        narration = " · ".join(narration_parts)[:400]
        remarks_parts = []
        if txn_ref:
            remarks_parts.append(f"Txn: {txn_ref}")
        odo = float(r.get("odometer") or 0)
        if odo > 0:
            remarks_parts.append(f"ODO: {odo}")
        remarks = " · ".join(remarks_parts)[:400]

        try:
            payload = Expense(
                date=date_iso, category="Diesel",
                amount=round(amount, 2),
                narration=narration, remarks=remarks,
                vehicle_id=vid, vehicle_number=veh.get("vehicle_number", ""),
                trip_id="", repair_event_id="",
                party_type="cash", party_id="", party_name="",
                vendor_bill_id="", mechanic_work_order_id="",
                supplier_owned_vehicle=False,
                supplier_settlement_mode="n/a",
                settlement_mode="cash_now",
                source_type="fleet_card_import",
                source_key=skey,
                source=source, source_txn_ref=txn_ref,
                source_trip_id="",
                file_ids=[],
            )
            payload = await _validate_and_normalise(uid, cid, payload)
        except HTTPException as ex:
            failed += 1
            results.append({**base, "status": "failed", "error": str(ex.detail)})
            continue

        # Fast-path duplicate check.
        existing = await db.expenses.find_one(
            {"user_id": uid, "company_id": cid, "source_key": skey,
             "is_deleted": {"$ne": True}},
            {"_id": 0, "id": 1},
        )
        if existing:
            duplicate += 1
            results.append({**base, "status": "duplicate",
                            "expense_id": existing["id"]})
            continue

        doc = payload.model_dump()
        doc["user_id"] = uid
        doc["company_id"] = cid
        doc["created_by"] = uid
        doc["created_at"] = now_utc().isoformat()
        doc["is_deleted"] = False
        doc["import_batch_id"] = batch_id
        try:
            await db.expenses.insert_one(doc)
        except DuplicateKeyError:
            duplicate += 1
            results.append({**base, "status": "duplicate"})
            continue
        created += 1
        doc.pop("_id", None); doc.pop("user_id", None)
        results.append({**base, "status": "created", "expense_id": doc["id"]})

    return {
        "batch_id": batch_id,
        "source": source,
        "created": created,
        "duplicate": duplicate,
        "failed": failed,
        "results": results,
    }


# ── Unified Fuel Log projection ────────────────────────────────────────
async def unified_fuel_log(uid: str, cid: str, *,
                           date_from: Optional[str], date_to: Optional[str],
                           vehicle_id: Optional[str],
                           source_filter: Optional[str],
                           limit: int = 5000) -> list[dict]:
    """Union view over all Diesel projections. Never contributes to
    accounting totals — pure operator display."""
    out: list[dict] = []

    # ── Canonical Diesel Expenses (Quick Op + Manual + fleet_card_import
    #    + trip_legacy materialised) ──
    q: dict = {"user_id": uid, "company_id": cid,
               "category": "Diesel",
               "is_deleted": {"$ne": True}, "is_reversed": {"$ne": True}}
    if vehicle_id:
        q["vehicle_id"] = vehicle_id
    if date_from or date_to:
        d = {}
        if date_from: d["$gte"] = date_from
        if date_to: d["$lte"] = date_to
        q["date"] = d
    async for e in db.expenses.find(q, {"_id": 0, "user_id": 0}).sort("date", -1).limit(limit):
        label = _canonical_source_label(e)
        if source_filter and source_filter != label:
            continue
        # Best-effort litres/rate extraction from narration ("70.0 L @ ₹105.09").
        litres, rate = _extract_litres_rate(str(e.get("narration") or ""))
        out.append({
            "id": e.get("id", ""),
            "date": e.get("date", ""),
            "vehicle_id": e.get("vehicle_id", ""),
            "vehicle_number": e.get("vehicle_number", ""),
            "litres": litres,
            "rate": rate,
            "amount": float(e.get("amount") or 0),
            "station_name": str(e.get("narration") or "")[:200],
            "odometer": _extract_odometer(str(e.get("remarks") or "")),
            "source_label": label,
            "source": e.get("source", ""),
            "source_txn_ref": e.get("source_txn_ref", ""),
            "trip_id": e.get("trip_id", ""),
            "kind": "canonical",
            "status": "Active",
        })

    # ── Legacy db.fuel (READ-ONLY projection; never contributes to reports) ──
    lq: dict = {"user_id": uid, "company_id": cid}
    if vehicle_id:
        lq["vehicle_id"] = vehicle_id
    if date_from or date_to:
        d = {}
        if date_from: d["$gte"] = date_from
        if date_to: d["$lte"] = date_to
        lq["date"] = d
    async for f in db.fuel.find(lq, {"_id": 0, "user_id": 0}).sort("date", -1).limit(limit):
        label = "Legacy Fuel"
        if source_filter and source_filter != label:
            continue
        out.append({
            "id": f.get("id", ""),
            "date": f.get("date", ""),
            "vehicle_id": f.get("vehicle_id", ""),
            "vehicle_number": f.get("vehicle_number", ""),
            "litres": float(f.get("litres") or 0),
            "rate": float(f.get("rate_per_litre") or 0),
            "amount": float(f.get("amount") or 0),
            "station_name": f.get("station_name", ""),
            "odometer": float(f.get("odometer") or 0),
            "source_label": label,
            "source": "legacy",
            "source_txn_ref": "",
            "trip_id": "",
            "kind": "legacy_fuel",
            "status": "Active",
        })

    # ── Trip legacy Diesel (only where has_canonical_expenses=false) ──
    tq: dict = {"user_id": uid, "company_id": cid,
                "$or": [
                    {"has_canonical_expenses": {"$exists": False}},
                    {"has_canonical_expenses": False},
                ]}
    if vehicle_id:
        tq["vehicle_id"] = vehicle_id
    if date_from or date_to:
        d = {}
        if date_from: d["$gte"] = date_from
        if date_to: d["$lte"] = date_to
        tq["date"] = d
    async for t in db.trips.find(tq, {"_id": 0, "id": 1, "date": 1,
                                       "vehicle_id": 1, "vehicle_number": 1,
                                       "expenses": 1, "lr_number": 1}
                                  ).sort("date", -1).limit(limit):
        diesel_amt = float((t.get("expenses") or {}).get("diesel") or 0)
        if diesel_amt <= 0:
            continue
        label = "Trip Legacy"
        if source_filter and source_filter != label:
            continue
        out.append({
            "id": t.get("id", ""),
            "date": t.get("date", ""),
            "vehicle_id": t.get("vehicle_id", ""),
            "vehicle_number": t.get("vehicle_number", ""),
            "litres": 0.0,
            "rate": 0.0,
            "amount": diesel_amt,
            "station_name": f"LR {t.get('lr_number', '—')}",
            "odometer": 0.0,
            "source_label": label,
            "source": "trip_legacy",
            "source_txn_ref": "",
            "trip_id": t.get("id", ""),
            "kind": "trip_legacy",
            "status": "Active",
        })

    out.sort(key=lambda r: (r["date"] or "", r["id"] or ""), reverse=True)
    return out[:limit]


_LITRES_RATE_RE = re.compile(r"([\d.]+)\s*L\s*@\s*₹?\s*([\d.]+)", re.I)
_ODO_RE = re.compile(r"ODO\s*:\s*([\d.]+)", re.I)


def _extract_litres_rate(narration: str) -> tuple[float, float]:
    if not narration:
        return 0.0, 0.0
    m = _LITRES_RATE_RE.search(narration)
    if not m:
        return 0.0, 0.0
    try:
        return float(m.group(1)), float(m.group(2))
    except Exception:
        return 0.0, 0.0


def _extract_odometer(remarks: str) -> float:
    if not remarks:
        return 0.0
    m = _ODO_RE.search(remarks)
    try:
        return float(m.group(1)) if m else 0.0
    except Exception:
        return 0.0
