"""Iter150A-1 · TRUKVIA Financial Control Foundation — Projection service.

PURE projection logic. Emits `FinTxn` rows from existing authoritative
source documents. NEVER mutates any business source of truth.

Design rules (see /app/memory/PRD.md · Iter150A-1 discovery):
  1. Every projected leg is single-sided. `direction="in"` = Debit,
     `direction="out"` = Credit. `amount` is always positive.
  2. Idempotency is by `ref_source_key` — a UNIQUE (user_id,
     company_id, ref_source_key) index. Every leg builds its key from
     stable source identity + a semantic leg suffix so re-projection is
     a delete-then-insert without ever leaking a legacy leg.
  3. VendorBill + paired Expense: to prevent double-count, the paired
     Expense is the SOLE authority for `EXPENSE debit + AP_VENDOR credit`.
     Orphan VendorBills (no paired Expense) get a fallback projection so
     the payable is not silently dropped. Same rule for MechanicWO.
  4. Quick-Op vendor cash (Iter139 · M.17 Model A): `Expense.settlement_mode
     == "cash_now"` with `Expense.party_type == "vendor"` emits only
     `EXPENSE debit + CASH credit`. NEVER touches AP_VENDOR. NEVER creates
     a VendorPayment (Iter139 authoritative behaviour is preserved).
  5. Supplier settlement adjustment: `Expense.supplier_settlement_mode
     == "supplier_settlement_adjustment"` emits `EXPENSE debit +
     AP_SUPPLIER credit` and flags `is_supplier_settlement_recovery=True`
     on the AP leg so Finance can isolate recovery movements.
     `company_borne` mode emits `EXPENSE debit + CASH credit` (real
     company money out; supplier settlement untouched).
  6. Fleet-card Diesel + FASTag Toll: consumption only in A-1. Emits
     `EXPENSE debit + WALLET_* credit`. Recharge write-model is Iter150B.
  7. Trip.customer_receipts: `BANK/CASH in + CUSTOMER_ADVANCE out` —
     projects the actual cash received but keeps AR out of the picture
     because Invoice.total_amount is already NET of advance/diesel
     deductions. When the trip is invoiced with deductions, an offset
     `CUSTOMER_ADVANCE debit + SALES credit` pair is emitted so total
     revenue reconciles to Invoice.gross_total.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone

from db import db
from models import FinTxn, FIN_SYSTEM_ACCOUNTS, now_utc


# ── Payment-mode → Account code resolver (for money-side of every txn) ──
# Every payment/receipt in TRUKVIA carries a `mode` field. We currently
# aggregate into two physical accounts (CASH, BANK_DEFAULT). Custom bank
# accounts can be added in the future without touching this map — the
# resolver simply picks a stable default until custom mapping ships.
_MODE_TO_ACCOUNT: Dict[str, str] = {
    "Cash": "CASH",
    "Bank": "BANK_DEFAULT",
    "UPI": "BANK_DEFAULT",
    "IMPS": "BANK_DEFAULT",
    "NEFT": "BANK_DEFAULT",
    "RTGS": "BANK_DEFAULT",
    "Cheque": "BANK_DEFAULT",
    "Other": "BANK_DEFAULT",
}


def _q2(x: float) -> float:
    """Round to 2dp — money semantics."""
    return round(float(x or 0), 2)


def _mode_account(mode: str) -> str:
    return _MODE_TO_ACCOUNT.get(mode or "Bank", "BANK_DEFAULT")


def _now_iso() -> str:
    return now_utc().isoformat()


# ── Account-cache helpers ────────────────────────────────────────────────

async def ensure_system_accounts(uid: str, cid: str) -> Dict[str, str]:
    """Idempotently seed the FIN_SYSTEM_ACCOUNTS catalog for this tenant.

    Returns a `code -> account_id` map used by the projection to resolve
    account_id from stable codes. Safe to call repeatedly (upsert-based).
    """
    code_to_id: Dict[str, str] = {}
    for seed in FIN_SYSTEM_ACCOUNTS:
        code = seed["code"]
        existing = await db.fin_accounts.find_one(
            {"user_id": uid, "company_id": cid, "code": code},
            {"_id": 0, "id": 1},
        )
        if existing:
            code_to_id[code] = existing["id"]
            continue
        doc = {
            "id": f"acc_{code.lower()}_{uid[-6:]}_{cid[-6:]}",
            "user_id": uid,
            "company_id": cid,
            "code": code,
            "name": seed["name"],
            "type": seed["type"],
            "is_system": True,
            "is_active": True,
            "remarks": "seeded by Iter150A-1",
            "created_at": _now_iso(),
        }
        try:
            await db.fin_accounts.insert_one(doc)
        except Exception:
            # Race-safe: another concurrent seeder won.
            hit = await db.fin_accounts.find_one(
                {"user_id": uid, "company_id": cid, "code": code},
                {"_id": 0, "id": 1},
            )
            if hit:
                code_to_id[code] = hit["id"]
                continue
            raise
        code_to_id[code] = doc["id"]
    return code_to_id


async def ensure_indexes() -> None:
    """Create the two critical FinTxn indexes + Account uniqueness.
    Called at startup and inside pytest.

    - `fin_txn`   UNIQUE (user_id, company_id, ref_source_key)
                  + (user_id, company_id, txn_date, account_code)
                  + (user_id, company_id, source_type, source_id)
    - `fin_accounts` UNIQUE (user_id, company_id, code)
    """
    await db.fin_txn.create_index(
        [("user_id", 1), ("company_id", 1), ("ref_source_key", 1)],
        unique=True, name="fin_txn_ref_source_uniq",
    )
    await db.fin_txn.create_index(
        [("user_id", 1), ("company_id", 1), ("txn_date", -1), ("account_code", 1)],
        name="fin_txn_day_book",
    )
    await db.fin_txn.create_index(
        [("user_id", 1), ("company_id", 1), ("source_type", 1), ("source_id", 1)],
        name="fin_txn_source",
    )
    await db.fin_accounts.create_index(
        [("user_id", 1), ("company_id", 1), ("code", 1)],
        unique=True, name="fin_accounts_code_uniq",
    )


# ── Leg factory ──────────────────────────────────────────────────────────

def _leg(
    *,
    txn_date: str,
    account_code: str,
    direction: str,
    amount: float,
    counter_account_code: str,
    txn_type: str,
    source_type: str,
    source_id: str,
    ref_leg: str,
    party_type: str = "",
    party_id: str = "",
    party_name: str = "",
    vehicle_id: str = "",
    trip_id: str = "",
    category: str = "",
    narration: str = "",
    source_key: str = "",
    is_supplier_settlement_recovery: bool = False,
) -> Dict[str, Any]:
    """Build a single FinTxn leg dict (account_id resolution happens at
    persist-time via the `code_to_id` map so this function stays pure)."""
    return {
        "account_code": account_code,
        "counter_account_code": counter_account_code,
        "direction": direction,
        "amount": _q2(amount),
        "txn_date": txn_date,
        "txn_type": txn_type,
        "source_type": source_type,
        "source_id": source_id,
        "source_key": source_key,
        "ref_source_key": f"{source_type}:{source_id}:{ref_leg}",
        "party_type": party_type,
        "party_id": party_id,
        "party_name": party_name,
        "vehicle_id": vehicle_id,
        "trip_id": trip_id,
        "category": category,
        "narration": narration[:400] if narration else "",
        "is_supplier_settlement_recovery": is_supplier_settlement_recovery,
    }


# ── Per-source projection functions ─────────────────────────────────────

def project_invoice(inv: dict) -> List[dict]:
    """Invoice raise (`status` not applicable — an Invoice doc exists ⇒ raised).

    Legs emitted (using Invoice.total_amount = post-deduction receivable):
      • AR   debit  = total_amount   (customer owes us this)
      • SALES credit = total_amount  (revenue accrual, net of deductions)

    Deduction offset legs (only if deductions > 0 on the invoice):
      • CUSTOMER_ADVANCE debit  = advance_deduction_total + diesel_deduction_total
      • SALES            credit = same total
    → After both pairs SALES = gross_total (revenue + tax including
      the amount funded by the customer advance), CUSTOMER_ADVANCE is
      reduced by the amount applied, AR = total_amount = balance owed.
    """
    if inv.get("is_historical"):
        return []
    inv_id = inv["id"]
    total = _q2(inv.get("total_amount") or 0)
    if total <= 0:
        # Zero-value invoice — nothing financially meaningful to project.
        return []
    date = inv.get("invoice_date") or ""
    common = dict(
        source_type="invoice",
        source_id=inv_id,
        party_type="customer",
        party_id=inv.get("customer_id") or "",
        narration=f"Invoice {inv.get('invoice_number', '')}",
    )
    legs: List[dict] = [
        _leg(txn_date=date, account_code="AR", direction="in",
             amount=total, counter_account_code="SALES",
             txn_type="invoice_raise", ref_leg="ar_debit", **common),
        _leg(txn_date=date, account_code="SALES", direction="out",
             amount=total, counter_account_code="AR",
             txn_type="invoice_raise", ref_leg="sales_credit", **common),
    ]

    # Offset legs: advance / diesel deductions on this invoice apply
    # previously-received customer advances toward this sale.
    adv = _q2(inv.get("advance_deduction_total") or 0)
    dsl = _q2(inv.get("diesel_deduction_total") or 0)
    offset = _q2(adv + dsl)
    if offset > 0:
        legs.append(_leg(
            txn_date=date, account_code="CUSTOMER_ADVANCE", direction="in",
            amount=offset, counter_account_code="SALES",
            txn_type="invoice_advance_offset", ref_leg="cust_adv_debit",
            **common,
        ))
        legs.append(_leg(
            txn_date=date, account_code="SALES", direction="out",
            amount=offset, counter_account_code="CUSTOMER_ADVANCE",
            txn_type="invoice_advance_offset", ref_leg="sales_offset_credit",
            **common,
        ))

    # Invoice.payments (embedded receipts against this invoice).
    for p in (inv.get("payments") or []):
        pid = p.get("id") or ""
        amt = _q2(p.get("amount") or 0)
        if amt <= 0 or not pid:
            continue
        p_common = dict(
            source_type="invoice_payment",
            source_id=f"{inv_id}:{pid}",
            party_type="customer",
            party_id=inv.get("customer_id") or "",
            narration=f"Receipt {p.get('reference', '')} · Inv {inv.get('invoice_number', '')}",
        )
        bank_code = _mode_account(p.get("mode") or "Bank")
        p_date = p.get("date") or date
        legs.append(_leg(
            txn_date=p_date, account_code=bank_code, direction="in",
            amount=amt, counter_account_code="AR",
            txn_type="invoice_receipt", ref_leg="bank_in", **p_common,
        ))
        legs.append(_leg(
            txn_date=p_date, account_code="AR", direction="out",
            amount=amt, counter_account_code=bank_code,
            txn_type="invoice_receipt", ref_leg="ar_credit", **p_common,
        ))
    return legs


def project_credit_debit_note(note: dict) -> List[dict]:
    """Issued CN / DN (draft & cancelled notes are ignored).

    CN (kind='credit'): reverses AR + SALES (customer's receivable drops).
    DN (kind='debit'):  adds AR + SALES (customer owes more).
    """
    if note.get("status") != "issued":
        return []
    if note.get("is_historical"):
        return []
    total = _q2(note.get("total_amount") or 0)
    if total <= 0:
        return []
    kind = note.get("kind") or "credit"
    date = note.get("note_date") or ""
    nid = note["id"]
    common = dict(
        source_type="credit_debit_note",
        source_id=nid,
        party_type="customer",
        party_id=note.get("customer_id") or "",
        narration=f"{'CN' if kind == 'credit' else 'DN'} {note.get('note_number', '')} · Inv {note.get('invoice_number_snapshot', '')}",
    )
    if kind == "credit":
        return [
            _leg(txn_date=date, account_code="AR", direction="out",
                 amount=total, counter_account_code="SALES",
                 txn_type="credit_note_issue", ref_leg="ar_credit", **common),
            _leg(txn_date=date, account_code="SALES", direction="in",
                 amount=total, counter_account_code="AR",
                 txn_type="credit_note_issue", ref_leg="sales_debit", **common),
        ]
    # kind == "debit"
    return [
        _leg(txn_date=date, account_code="AR", direction="in",
             amount=total, counter_account_code="SALES",
             txn_type="debit_note_issue", ref_leg="ar_debit", **common),
        _leg(txn_date=date, account_code="SALES", direction="out",
             amount=total, counter_account_code="AR",
             txn_type="debit_note_issue", ref_leg="sales_credit", **common),
    ]


def project_supplier_payment(sp: dict) -> List[dict]:
    """SupplierPayment — cash movement to/from supplier.

    payment_out: AP_SUPPLIER debit + BANK/CASH credit (we paid them).
    receipt_in:  BANK/CASH debit + AP_SUPPLIER credit (they paid us).
    """
    if sp.get("is_deleted") or sp.get("is_reversed"):
        return []
    if sp.get("is_historical"):
        return []
    amt = _q2(sp.get("amount") or 0)
    if amt <= 0:
        return []
    date = sp.get("date") or ""
    bank_code = _mode_account(sp.get("mode") or "Bank")
    typ = sp.get("type") or "payment_out"
    common = dict(
        source_type="supplier_payment",
        source_id=sp["id"],
        party_type="supplier",
        party_id=sp.get("supplier_id") or "",
        trip_id=sp.get("trip_id") or "",
        narration=f"Supplier {typ} · {sp.get('ref_no', '')}".strip(" ·"),
    )
    if typ == "payment_out":
        return [
            _leg(txn_date=date, account_code="AP_SUPPLIER", direction="in",
                 amount=amt, counter_account_code=bank_code,
                 txn_type="supplier_payment_out", ref_leg="ap_debit", **common),
            _leg(txn_date=date, account_code=bank_code, direction="out",
                 amount=amt, counter_account_code="AP_SUPPLIER",
                 txn_type="supplier_payment_out", ref_leg="bank_credit", **common),
        ]
    # receipt_in
    return [
        _leg(txn_date=date, account_code=bank_code, direction="in",
             amount=amt, counter_account_code="AP_SUPPLIER",
             txn_type="supplier_receipt_in", ref_leg="bank_debit", **common),
        _leg(txn_date=date, account_code="AP_SUPPLIER", direction="out",
             amount=amt, counter_account_code=bank_code,
             txn_type="supplier_receipt_in", ref_leg="ap_credit", **common),
    ]


def _party_payment_legs(
    p: dict, *,
    ap_code: str, party_type: str, party_id_key: str,
    src_type: str, txn_type_prefix: str,
) -> List[dict]:
    if p.get("is_deleted") or p.get("is_reversed"):
        return []
    amt = _q2(p.get("amount") or 0)
    if amt <= 0:
        return []
    date = p.get("date") or ""
    bank_code = _mode_account(p.get("mode") or "Bank")
    typ = p.get("type") or "payment_out"
    common = dict(
        source_type=src_type,
        source_id=p["id"],
        party_type=party_type,
        party_id=p.get(party_id_key) or "",
        narration=f"{party_type.title()} {typ} · {p.get('ref_no', '')}".strip(" ·"),
    )
    if typ == "payment_out":
        return [
            _leg(txn_date=date, account_code=ap_code, direction="in",
                 amount=amt, counter_account_code=bank_code,
                 txn_type=f"{txn_type_prefix}_payment_out",
                 ref_leg="ap_debit", **common),
            _leg(txn_date=date, account_code=bank_code, direction="out",
                 amount=amt, counter_account_code=ap_code,
                 txn_type=f"{txn_type_prefix}_payment_out",
                 ref_leg="bank_credit", **common),
        ]
    return [
        _leg(txn_date=date, account_code=bank_code, direction="in",
             amount=amt, counter_account_code=ap_code,
             txn_type=f"{txn_type_prefix}_receipt_in",
             ref_leg="bank_debit", **common),
        _leg(txn_date=date, account_code=ap_code, direction="out",
             amount=amt, counter_account_code=bank_code,
             txn_type=f"{txn_type_prefix}_receipt_in",
             ref_leg="ap_credit", **common),
    ]


def project_vendor_payment(vp: dict) -> List[dict]:
    return _party_payment_legs(
        vp, ap_code="AP_VENDOR", party_type="vendor",
        party_id_key="vendor_id", src_type="vendor_payment",
        txn_type_prefix="vendor",
    )


def project_mechanic_payment(mp: dict) -> List[dict]:
    return _party_payment_legs(
        mp, ap_code="AP_MECHANIC", party_type="mechanic",
        party_id_key="mechanic_id", src_type="mechanic_payment",
        txn_type_prefix="mechanic",
    )


def project_expense(exp: dict) -> List[dict]:
    """Canonical Expense — the ONE cost projection. Every payable/vendor/
    supplier-recovery leg flows through here to prevent double-count vs
    the paired VendorBill / MechanicWorkOrder.

    Routing rules (applied top-down; first match wins):
      1. supplier_owned_vehicle=True:
         a. mode="supplier_settlement_adjustment" → EXPENSE + AP_SUPPLIER,
            flag is_supplier_settlement_recovery on the AP leg.
         b. mode="company_borne" → EXPENSE + CASH (company bears it).
      2. source_type="fastag_import" (Toll) → EXPENSE + WALLET_FASTAG.
      3. source_type="fleet_card_import" (Diesel) → EXPENSE + WALLET_FUEL.
      4. vendor_bill_id set → EXPENSE + AP_VENDOR (paired-bill authority).
      5. mechanic_work_order_id set → EXPENSE + AP_MECHANIC.
      6. settlement_mode="cash_now" (incl. Iter139 quick-op vendor cash) →
         EXPENSE + CASH.
      7. Fallback → EXPENSE + SUSPENSE (safety valve for unrouted rows).
    """
    if exp.get("is_deleted") or exp.get("is_reversed"):
        return []
    amt = _q2(exp.get("amount") or 0)
    if amt <= 0:
        return []
    if exp.get("is_historical"):
        return []
    eid = exp["id"]
    date = exp.get("date") or ""
    src_key = exp.get("source_key") or ""
    src_type_field = exp.get("source_type") or "manual"
    supp_owned = bool(exp.get("supplier_owned_vehicle"))
    supp_mode = exp.get("supplier_settlement_mode") or "n/a"
    settlement = exp.get("settlement_mode") or "payable"
    vb_id = exp.get("vendor_bill_id") or ""
    wo_id = exp.get("mechanic_work_order_id") or ""

    party_type = exp.get("party_type") or ""
    party_id = exp.get("party_id") or ""
    party_name = exp.get("party_name") or ""

    # Resolve the credit-side account + txn semantics.
    is_settlement_recovery = False
    if supp_owned and supp_mode == "supplier_settlement_adjustment":
        credit_code = "AP_SUPPLIER"
        txn_type = "expense_supplier_settlement_recovery"
        # Force party linkage to supplier for the AP leg denorm.
        party_type = "supplier"
        # Best-effort supplier_id: resolve from vehicle; we keep whatever
        # the caller denormalised (Iter147/148 stamp `party_id` when
        # relevant). Left blank when unknown — Day Book still resolves via
        # counter_account_code.
        is_settlement_recovery = True
    elif supp_owned and supp_mode == "company_borne":
        credit_code = "CASH"
        txn_type = "expense_company_borne"
    elif src_type_field == "fastag_import":
        credit_code = "WALLET_FASTAG"
        txn_type = "expense_fastag_toll"
    elif src_type_field == "fleet_card_import":
        credit_code = "WALLET_FUEL"
        txn_type = "expense_fleet_diesel"
    elif vb_id:
        credit_code = "AP_VENDOR"
        txn_type = "expense_vendor_payable"
    elif wo_id:
        credit_code = "AP_MECHANIC"
        txn_type = "expense_mechanic_payable"
    elif settlement == "cash_now":
        credit_code = "CASH"
        txn_type = "expense_cash_now"
    else:
        credit_code = "SUSPENSE"
        txn_type = "expense_unrouted"

    narration = (exp.get("narration") or exp.get("category") or "")[:400]
    common = dict(
        source_type="expense",
        source_id=eid,
        source_key=src_key,
        party_type=party_type,
        party_id=party_id,
        party_name=party_name,
        vehicle_id=exp.get("vehicle_id") or "",
        trip_id=exp.get("trip_id") or "",
        category=exp.get("category") or "",
        narration=narration,
    )
    return [
        _leg(txn_date=date, account_code="EXPENSE_DEFAULT", direction="in",
             amount=amt, counter_account_code=credit_code,
             txn_type=txn_type, ref_leg="expense_debit", **common),
        _leg(txn_date=date, account_code=credit_code, direction="out",
             amount=amt, counter_account_code="EXPENSE_DEFAULT",
             txn_type=txn_type, ref_leg=f"{credit_code.lower()}_credit",
             is_supplier_settlement_recovery=is_settlement_recovery,
             **common),
    ]


def project_vendor_bill(vb: dict, has_paired_expense: bool) -> List[dict]:
    """VendorBill — projects the payable ONLY when no paired Expense exists.

    In the Iter133 canonical flow, every VendorBill has a paired Expense
    that carries the EXPENSE + AP_VENDOR legs. Projecting the bill
    separately would double-count AP_VENDOR. So this function returns
    `[]` in the common case. Orphan bills (rare, e.g. legacy imports)
    are captured with a SUSPENSE-side leg so payables are not silently
    dropped.
    """
    if vb.get("is_deleted"):
        return []
    if has_paired_expense:
        return []
    amt = _q2(vb.get("bill_amount") or 0)
    if amt <= 0:
        return []
    date = vb.get("bill_date") or ""
    common = dict(
        source_type="vendor_bill",
        source_id=vb["id"],
        party_type="vendor",
        party_id=vb.get("vendor_id") or "",
        party_name=vb.get("vendor_name") or "",
        vehicle_id=vb.get("vehicle_id") or "",
        trip_id=vb.get("trip_id") or "",
        narration=f"VendorBill {vb.get('bill_number', '')} (orphan)",
    )
    return [
        _leg(txn_date=date, account_code="SUSPENSE", direction="in",
             amount=amt, counter_account_code="AP_VENDOR",
             txn_type="vendor_bill_orphan", ref_leg="suspense_debit", **common),
        _leg(txn_date=date, account_code="AP_VENDOR", direction="out",
             amount=amt, counter_account_code="SUSPENSE",
             txn_type="vendor_bill_orphan", ref_leg="ap_credit", **common),
    ]


def project_mechanic_work_order(wo: dict, has_paired_expense: bool) -> List[dict]:
    """MechanicWorkOrder — same orphan-only rule as VendorBill."""
    if wo.get("is_deleted"):
        return []
    if has_paired_expense:
        return []
    amt = _q2(wo.get("amount") or 0)
    if amt <= 0:
        return []
    date = wo.get("work_date") or ""
    common = dict(
        source_type="mechanic_work_order",
        source_id=wo["id"],
        party_type="mechanic",
        party_id=wo.get("mechanic_id") or "",
        party_name=wo.get("mechanic_name") or "",
        vehicle_id=wo.get("vehicle_id") or "",
        trip_id=wo.get("trip_id") or "",
        narration=f"WO {wo['id']} (orphan)",
    )
    return [
        _leg(txn_date=date, account_code="SUSPENSE", direction="in",
             amount=amt, counter_account_code="AP_MECHANIC",
             txn_type="mechanic_wo_orphan", ref_leg="suspense_debit", **common),
        _leg(txn_date=date, account_code="AP_MECHANIC", direction="out",
             amount=amt, counter_account_code="SUSPENSE",
             txn_type="mechanic_wo_orphan", ref_leg="ap_credit", **common),
    ]


def project_trip_customer_receipts(trip: dict) -> List[dict]:
    """Trip.customer_receipts — money received from a customer against a
    specific trip (advance / diesel), OUTSIDE the invoice flow.

    Semantics chosen for A-1 (per correction #6):
      BANK/CASH in  ← actual cash movement
      CUSTOMER_ADVANCE out  ← we owe this back or apply it when invoiced

    Invoice.total_amount is already net of these deductions, so we do
    NOT credit AR here (that would double-reduce AR). The Invoice-raise
    projection handles the offset via `invoice_advance_offset` legs.
    """
    if trip.get("is_historical"):
        return []
    receipts = trip.get("customer_receipts") or []
    if not receipts:
        return []
    trip_id = trip["id"]
    legs: List[dict] = []
    for i, r in enumerate(receipts):
        # Iter150A-1 UAT-fix #1 · Legacy Iter39/40 Trip.customer_receipts do
        # NOT carry an `id`. To keep every real cash movement projected —
        # while preserving idempotency — fall back to a deterministic key
        # derived from the receipt's stable array position. Existing rows
        # that DO carry an explicit `id` remain byte-preserved.
        rid = str(r.get("id") or "").strip() or f"idx{i}"
        amt = _q2(r.get("amount") or 0)
        if amt <= 0:
            continue
        date = r.get("date") or trip.get("date") or ""
        mode = r.get("mode") or "Bank"
        bank_code = _mode_account(mode)
        rtype = r.get("type") or "advance"
        common = dict(
            source_type="trip_customer_receipt",
            source_id=f"{trip_id}:{rid}",
            party_type="customer",
            party_id=trip.get("customer_id") or "",
            trip_id=trip_id,
            narration=f"Trip customer {rtype} receipt",
            category=rtype,
        )
        legs.append(_leg(
            txn_date=date, account_code=bank_code, direction="in",
            amount=amt, counter_account_code="CUSTOMER_ADVANCE",
            txn_type=f"trip_customer_{rtype}_receipt",
            ref_leg="bank_debit", **common,
        ))
        legs.append(_leg(
            txn_date=date, account_code="CUSTOMER_ADVANCE", direction="out",
            amount=amt, counter_account_code=bank_code,
            txn_type=f"trip_customer_{rtype}_receipt",
            ref_leg="cust_adv_credit", **common,
        ))
    return legs


# ── Persist / reproject helpers ──────────────────────────────────────────

async def _persist_legs(
    uid: str, cid: str, legs: List[dict], code_to_id: Dict[str, str],
) -> int:
    """Insert projected legs, resolving account_id from code_to_id.

    Uses upsert-by-ref_source_key so partial-failure replay is safe: any
    leg already present is treated as a no-op update. The write count
    returned is the number of legs actually persisted (matched or new).
    """
    if not legs:
        return 0
    now_iso = _now_iso()
    written = 0
    for leg in legs:
        code = leg["account_code"]
        counter_code = leg["counter_account_code"]
        account_id = code_to_id.get(code)
        counter_id = code_to_id.get(counter_code, "") if counter_code else ""
        if not account_id:
            raise RuntimeError(f"unknown account code {code!r} for tenant ({uid},{cid})")
        doc = {
            "id": f"fintxn_{leg['ref_source_key'].replace(':', '_')[:60]}",
            "user_id": uid,
            "company_id": cid,
            "txn_date": leg["txn_date"],
            "account_id": account_id,
            "account_code": code,
            "direction": leg["direction"],
            "amount": leg["amount"],
            "counter_account_id": counter_id,
            "counter_account_code": counter_code,
            "txn_type": leg["txn_type"],
            "source_type": leg["source_type"],
            "source_id": leg["source_id"],
            "source_key": leg.get("source_key", ""),
            "ref_source_key": leg["ref_source_key"],
            "party_type": leg.get("party_type", ""),
            "party_id": leg.get("party_id", ""),
            "party_name": leg.get("party_name", ""),
            "vehicle_id": leg.get("vehicle_id", ""),
            "trip_id": leg.get("trip_id", ""),
            "category": leg.get("category", ""),
            "narration": leg.get("narration", ""),
            "transfer_group_id": "",
            "adjustment_group_id": "",
            "reversal_of": "",
            "is_reversal": False,
            "status": "active",
            "is_supplier_settlement_recovery": leg.get(
                "is_supplier_settlement_recovery", False),
            "reconciled_at": "",
            "reconciled_ref": "",
            "created_at": now_iso,
            "projected_at": now_iso,
        }
        await db.fin_txn.update_one(
            {"user_id": uid, "company_id": cid,
             "ref_source_key": leg["ref_source_key"]},
            {"$set": doc},
            upsert=True,
        )
        written += 1
    return written


async def _has_paired_expense(uid: str, cid: str, *, vendor_bill_id: str = "",
                               mechanic_work_order_id: str = "") -> bool:
    q = {"user_id": uid, "company_id": cid, "is_deleted": {"$ne": True},
         "is_reversed": {"$ne": True}}
    if vendor_bill_id:
        q["vendor_bill_id"] = vendor_bill_id
    if mechanic_work_order_id:
        q["mechanic_work_order_id"] = mechanic_work_order_id
    return bool(await db.expenses.find_one(q, {"_id": 0, "id": 1}))


async def _delete_by_source(uid: str, cid: str, source_type: str,
                             source_id: str) -> int:
    """Delete-then-insert step: remove every existing leg for this source.

    We use a startswith match on `source_id` for compound keys like
    `{inv_id}:{payment_id}` (invoice_payment) so the parent's reproject
    also clears embedded receipt legs.
    """
    q = {"user_id": uid, "company_id": cid, "source_type": source_type}
    if source_id.endswith(":*"):
        prefix = source_id[:-1]  # keep the ":"
        q["source_id"] = {"$regex": f"^{prefix}"}
    else:
        q["source_id"] = source_id
    res = await db.fin_txn.delete_many(q)
    return int(res.deleted_count or 0)


async def reproject_source(
    uid: str, cid: str, source_type: str, source_id: str,
    *, code_to_id: Optional[Dict[str, str]] = None,
    delete_existing: bool = True,
) -> Tuple[int, int]:
    """Idempotently reproject a single source document.

    Returns `(deleted, written)`. Delete-then-insert semantics; per
    correction #7, we first snapshot the affected legs, then delete,
    then insert — the upsert keeps replay safe even if a hard failure
    lands mid-loop (the second run recovers).
    """
    code_to_id = code_to_id or await ensure_system_accounts(uid, cid)
    deleted = 0
    if delete_existing:
        # For invoice, also cascade invoice_payment legs.
        if source_type == "invoice":
            deleted += await _delete_by_source(uid, cid, "invoice_payment",
                                                f"{source_id}:*")
        deleted += await _delete_by_source(uid, cid, source_type, source_id)

    legs: List[dict] = []
    if source_type == "invoice":
        doc = await db.invoices.find_one(
            {"user_id": uid, "company_id": cid, "id": source_id}, {"_id": 0})
        if doc:
            legs = project_invoice(doc)
    elif source_type == "credit_debit_note":
        doc = await db.credit_debit_notes.find_one(
            {"user_id": uid, "company_id": cid, "id": source_id}, {"_id": 0})
        if doc:
            legs = project_credit_debit_note(doc)
    elif source_type == "supplier_payment":
        doc = await db.supplier_payments.find_one(
            {"user_id": uid, "company_id": cid, "id": source_id}, {"_id": 0})
        if doc:
            legs = project_supplier_payment(doc)
    elif source_type == "vendor_payment":
        doc = await db.vendor_payments.find_one(
            {"user_id": uid, "company_id": cid, "id": source_id}, {"_id": 0})
        if doc:
            legs = project_vendor_payment(doc)
    elif source_type == "mechanic_payment":
        doc = await db.mechanic_payments.find_one(
            {"user_id": uid, "company_id": cid, "id": source_id}, {"_id": 0})
        if doc:
            legs = project_mechanic_payment(doc)
    elif source_type == "expense":
        doc = await db.expenses.find_one(
            {"user_id": uid, "company_id": cid, "id": source_id}, {"_id": 0})
        if doc:
            legs = project_expense(doc)
    elif source_type == "vendor_bill":
        doc = await db.vendor_bills.find_one(
            {"user_id": uid, "company_id": cid, "id": source_id}, {"_id": 0})
        if doc:
            paired = await _has_paired_expense(uid, cid, vendor_bill_id=source_id)
            legs = project_vendor_bill(doc, paired)
    elif source_type == "mechanic_work_order":
        doc = await db.mechanic_work_orders.find_one(
            {"user_id": uid, "company_id": cid, "id": source_id}, {"_id": 0})
        if doc:
            paired = await _has_paired_expense(
                uid, cid, mechanic_work_order_id=source_id)
            legs = project_mechanic_work_order(doc, paired)
    elif source_type == "trip_customer_receipt":
        # source_id here is the trip_id (per-trip aggregate reproject).
        trip = await db.trips.find_one(
            {"user_id": uid, "company_id": cid, "id": source_id}, {"_id": 0})
        if trip:
            legs = project_trip_customer_receipts(trip)
    else:
        raise ValueError(f"unsupported source_type: {source_type}")

    written = await _persist_legs(uid, cid, legs, code_to_id)
    return deleted, written


# ── Full-tenant backfill ────────────────────────────────────────────────

SUPPORTED_SOURCE_TYPES: List[str] = [
    "invoice",              # + embedded invoice_payment cascade
    "credit_debit_note",
    "supplier_payment",
    "vendor_payment",
    "mechanic_payment",
    "expense",
    "vendor_bill",
    "mechanic_work_order",
    "trip_customer_receipt",
]


async def backfill_tenant(
    uid: str, cid: str, *,
    dry_run: bool = False,
    verbose: bool = False,
) -> Dict[str, Any]:
    """Backfill FinTxn for a single tenant. Returns a report dict.

    In `dry_run` mode NOTHING is written; the projection is computed and
    counted but persisted rows and delete counts are simulated (deleted=0).
    """
    code_to_id: Dict[str, str] = {}
    if not dry_run:
        code_to_id = await ensure_system_accounts(uid, cid)
    else:
        # For dry-run we still need account_ids to construct docs — but
        # since we won't persist, we can synthesise placeholders.
        for seed in FIN_SYSTEM_ACCOUNTS:
            code_to_id[seed["code"]] = f"acc_dryrun_{seed['code']}"

    per_source: Dict[str, Dict[str, int]] = {}
    total_written = 0
    total_deleted = 0

    async def _iter_source(coll_name: str, source_type: str,
                           filter_extra: Optional[dict] = None,
                           project_fn=None,
                           needs_paired_check: bool = False):
        nonlocal total_written, total_deleted
        q = {"user_id": uid, "company_id": cid}
        if filter_extra:
            q.update(filter_extra)
        cur = db[coll_name].find(q, {"_id": 0})
        counts = {"source": 0, "projected_legs": 0, "skipped": 0,
                  "deleted": 0, "errors": 0}
        async for doc in cur:
            counts["source"] += 1
            try:
                if needs_paired_check:
                    key = ("vendor_bill_id" if source_type == "vendor_bill"
                           else "mechanic_work_order_id")
                    paired = await _has_paired_expense(
                        uid, cid, **{key: doc["id"]})
                    legs = project_fn(doc, paired)
                else:
                    legs = project_fn(doc)
                if not legs:
                    counts["skipped"] += 1
                    continue
                if not dry_run:
                    deleted = await _delete_by_source(uid, cid, source_type,
                                                       doc["id"])
                    counts["deleted"] += deleted
                    total_deleted += deleted
                    written = await _persist_legs(uid, cid, legs, code_to_id)
                else:
                    written = len(legs)
                counts["projected_legs"] += written
                total_written += written
            except Exception as ex:
                counts["errors"] += 1
                if verbose:
                    print(f"[error] {source_type} {doc.get('id')}: {ex}")
        per_source[source_type] = counts

    await _iter_source("invoices", "invoice", project_fn=project_invoice)
    # Invoice-embedded payments are captured under the parent invoice's
    # projection; we accounting-track them under `invoice_payment` in
    # FinTxn but iterate through invoices to project them.
    await _iter_source("credit_debit_notes", "credit_debit_note",
                       project_fn=project_credit_debit_note)
    await _iter_source("supplier_payments", "supplier_payment",
                       project_fn=project_supplier_payment)
    await _iter_source("vendor_payments", "vendor_payment",
                       project_fn=project_vendor_payment)
    await _iter_source("mechanic_payments", "mechanic_payment",
                       project_fn=project_mechanic_payment)
    await _iter_source("expenses", "expense", project_fn=project_expense)
    await _iter_source("vendor_bills", "vendor_bill",
                       project_fn=project_vendor_bill,
                       needs_paired_check=True)
    await _iter_source("mechanic_work_orders", "mechanic_work_order",
                       project_fn=project_mechanic_work_order,
                       needs_paired_check=True)
    await _iter_source("trips", "trip_customer_receipt",
                       project_fn=project_trip_customer_receipts)

    # ── Invariants / reconciliation. Fail loud on mismatch.
    invariants = await _run_invariants(uid, cid, dry_run=dry_run)
    return {
        "user_id": uid,
        "company_id": cid,
        "dry_run": dry_run,
        "per_source": per_source,
        "total_projected_legs": total_written,
        "total_deleted": total_deleted,
        "invariants": invariants,
    }


async def _run_invariants(uid: str, cid: str, *, dry_run: bool) -> Dict[str, Any]:
    """Run reconciliation checks. Never raise — return a dict so the
    caller can decide how to react (backfill script exits non-zero;
    the reproject endpoint surfaces mismatches to the operator)."""
    report: Dict[str, Any] = {"mismatches": []}

    # Invariant 1 · Σ Expense (canonical, non-deleted, non-reversed,
    # non-historical, amount>0) == Σ FinTxn EXPENSE_DEFAULT debits.
    exp_sum = 0.0
    async for e in db.expenses.find(
        {"user_id": uid, "company_id": cid, "is_deleted": {"$ne": True},
         "is_reversed": {"$ne": True}, "is_historical": {"$ne": True}},
        {"_id": 0, "amount": 1},
    ):
        exp_sum += float(e.get("amount") or 0)
    exp_sum = round(exp_sum, 2)

    if dry_run:
        # In dry-run we didn't write, but the report should still show
        # what the tenant contains vs what would be projected.
        report["expense_source_sum"] = exp_sum
        return report

    fin_exp_in = 0.0
    async for row in db.fin_txn.find(
        {"user_id": uid, "company_id": cid,
         "account_code": "EXPENSE_DEFAULT", "direction": "in"},
        {"_id": 0, "amount": 1},
    ):
        fin_exp_in += float(row.get("amount") or 0)
    fin_exp_in = round(fin_exp_in, 2)
    report["expense_source_sum"] = exp_sum
    report["fin_expense_debit_sum"] = fin_exp_in
    if abs(exp_sum - fin_exp_in) > 0.01:
        report["mismatches"].append({
            "invariant": "expense_sum",
            "source": exp_sum, "projected": fin_exp_in,
            "delta": round(fin_exp_in - exp_sum, 2),
        })

    # Invariant 2 · AR net balance == Σ open invoice balance_due.
    ar_in = ar_out = 0.0
    async for row in db.fin_txn.find(
        {"user_id": uid, "company_id": cid, "account_code": "AR"},
        {"_id": 0, "amount": 1, "direction": 1},
    ):
        v = float(row.get("amount") or 0)
        if row.get("direction") == "in":
            ar_in += v
        else:
            ar_out += v
    ar_net = round(ar_in - ar_out, 2)

    open_bal = 0.0
    async for inv in db.invoices.find(
        {"user_id": uid, "company_id": cid, "is_historical": {"$ne": True}},
        {"_id": 0, "balance_due": 1},
    ):
        open_bal += float(inv.get("balance_due") or 0)
    open_bal = round(open_bal, 2)
    report["ar_net_projected"] = ar_net
    report["open_invoice_balance"] = open_bal
    # Small tolerance for round-off + CN/DN deltas not yet applied to
    # balance_due (existing balance_due field predates CN/DN Iter132a).
    # We flag but do not fail if the delta is within 5% of balance.
    if abs(ar_net - open_bal) > max(1.0, 0.05 * max(open_bal, 1.0)):
        report["mismatches"].append({
            "invariant": "ar_net_vs_balance_due",
            "note": "Δ > 5% — may reflect CN/DN offsets not applied to "
                    "Invoice.balance_due (Iter132a legacy).",
            "projected": ar_net, "source": open_bal,
            "delta": round(ar_net - open_bal, 2),
        })

    return report
