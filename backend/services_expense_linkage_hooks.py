"""Iter150A-2 · Phase 3A — Expense linkage cross-reprojection helper.

Sole purpose: when an Expense write path changes the pairing linkage
between an Expense and its authoritative VendorBill / MechanicWorkOrder,
also refresh the linked source's projection so paired-vs-orphan
transitions cannot leave stale FinTxn legs behind.

Locked A-1 behaviour §3 (paired Expense is the SOLE authority for
EXPENSE + AP_VENDOR/AP_MECHANIC legs; orphan VendorBills /
MechanicWorkOrders get a fallback projection) means:
  * When Expense links to a NEW bill/WO   → the old link's projection
    must recompute (may transition paired → orphan).
  * When Expense unlinks (soft-delete /
    reverses / drops the FK)              → the linked bill/WO must
    recompute (transitions paired → orphan).
  * When Expense linkage is unchanged     → do nothing (no cross-fire,
    no wasted work).

This helper is intentionally minimal:
  * No event bus. No dependency graph. No generic sweep.
  * Reuses the already-locked Phase-1 `hook_after_source_write`.
  * Never raises: failures are queued via the standard hook plumbing.
  * `is_deleted` / `is_reversed` are treated as effective-unlink signals
    because A-1 projects zero legs for those Expense states.
"""
from __future__ import annotations

from typing import Optional

from services_fin_txn_hooks import hook_after_source_write


def _effective_linkage(doc: Optional[dict], field: str) -> str:
    """Return the linkage id from an Expense dict, or empty string when
    the doc is missing / soft-deleted / reversed. A-1 projects zero
    legs in the latter two states, so those are equivalent to no link."""
    if not doc:
        return ""
    if doc.get("is_deleted"):
        return ""
    if doc.get("is_reversed"):
        return ""
    return str(doc.get(field) or "")


async def refresh_linked_paired_sources(
    uid: str, cid: str,
    before: Optional[dict], after: Optional[dict],
) -> None:
    """Reproject the OLD and NEW linked source when an Expense's
    effective pairing changes. No-op when linkage is unchanged."""
    for field, source_type in (
        ("vendor_bill_id", "vendor_bill"),
        ("mechanic_work_order_id", "mechanic_work_order"),
    ):
        old_id = _effective_linkage(before, field)
        new_id = _effective_linkage(after, field)
        if old_id == new_id:
            continue
        if old_id:
            await hook_after_source_write(uid, cid, source_type, old_id)
        if new_id:
            await hook_after_source_write(uid, cid, source_type, new_id)
