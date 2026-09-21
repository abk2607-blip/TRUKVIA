"""Iter150A-2 · Phase 1 — Reusable post-write hook foundation for FinTxn.

STRICT SCOPE:
  * This module provides the *infrastructure* that Phase 2+ will call
    after every authoritative source write. Phase 1 wires nothing into
    the source write paths. Every locked-band router / service remains
    untouched.
  * The A-1 projection layer (`services_fin_txn.py`) is imported as a
    dependency ONLY. Its logic is never re-implemented, extended, or
    branched. Source of truth for projection semantics stays A-1.
  * FinTxn remains a rebuildable projection. The authoritative source
    document is never rolled back on hook failure. Failure information
    is captured in `fin_hook_failures` (persisted, never TTL-expired)
    and drained by the retry mechanism until either resolved or marked
    `permanently_failed` for human investigation.

DESIGN NOTES (per approved Phase-1 constraints):
  * NO in-memory "duplicate hook cache" — A-1's UNIQUE
    `(user_id, company_id, ref_source_key)` index makes replay
    structurally idempotent.
  * NO Mongo multi-document transactions — current deployment is not a
    replica set. Source ← authoritative; FinTxn ← rebuildable projection.
  * NO TTL on `fin_hook_failures`. Records are retained forever unless
    explicitly resolved. Accounting-repair information cannot silently
    disappear.
  * Retry mechanism is a plain async callable — NOT scheduled at
    startup in Phase 1. Tests and the CLI invoke it directly. Startup
    wiring lands in a later phase once behaviour is validated.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from db import db
from services_fin_txn import reproject_source, SUPPORTED_SOURCE_TYPES

logger = logging.getLogger("iter150a2.hooks")


# ── Phase 6 · slice 2c — reverse bridge to the NestJS projection ─────────
# Per-source-type delegation, DEFAULT OFF. With none of these set the hook
# behaves exactly as before, which is the rollback: unset the env var.
#
#   TRUKVIA_FIN_NODE_URL           NestJS POST /internal/fin/reproject
#   TRUKVIA_INTERNAL_TOKEN         the shared secret (>= 32 chars)
#   TRUKVIA_FIN_NODE_SOURCE_TYPES  comma-separated types to delegate
#
# A TRANSPORT failure (unreachable, timeout, non-200) falls back to the local
# projection, so a NestJS outage can never leave the ledger stale. A well-formed
# ok=false is NOT retried locally: NestJS has already recorded that failure in
# fin_hook_failures, and projecting again here would double-handle it.
_NODE_TIMEOUT_SECONDS = float(os.environ.get("TRUKVIA_FIN_NODE_TIMEOUT", "10"))


def _node_delegate_types() -> frozenset:
    raw = os.environ.get("TRUKVIA_FIN_NODE_SOURCE_TYPES") or ""
    return frozenset(t.strip() for t in raw.split(",") if t.strip())


def _node_bridge_ready(source_type: str) -> bool:
    url = (os.environ.get("TRUKVIA_FIN_NODE_URL") or "").strip()
    token = (os.environ.get("TRUKVIA_INTERNAL_TOKEN") or "").strip()
    return bool(url) and len(token) >= 32 and source_type in _node_delegate_types()


async def _delegate_to_node(uid: str, cid: str, source_type: str,
                            source_id: str) -> Optional[Dict[str, Any]]:
    """Return the NestJS hook report, or None to fall back locally.

    The token travels only in the X-Internal-Token header and is never logged.
    """
    import httpx

    url = (os.environ.get("TRUKVIA_FIN_NODE_URL") or "").strip()
    token = (os.environ.get("TRUKVIA_INTERNAL_TOKEN") or "").strip()
    try:
        async with httpx.AsyncClient(timeout=_NODE_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                url,
                json={"user_id": uid, "company_id": cid,
                      "source_type": source_type, "source_id": source_id},
                headers={"X-Internal-Token": token},
            )
        if resp.status_code != 200:
            logger.warning("node projection bridge returned %s for %s/%s; "
                           "falling back to the local projection",
                           resp.status_code, source_type, source_id)
            return None
        return dict(resp.json())
    except Exception as ex:                              # noqa: BLE001
        logger.warning("node projection bridge unreachable (%s) for %s/%s; "
                       "falling back to the local projection",
                       type(ex).__name__, source_type, source_id)
        return None

# ── Retry policy ─────────────────────────────────────────────────────────
# Base backoff = 60s; doubles per attempt; capped at 24h. After
# MAX_RETRIES exhausted, the row is marked `permanently_failed` and
# retained for human investigation.
MAX_RETRIES: int = 8                    # ~10 days total window
BACKOFF_BASE_SECONDS: int = 60
BACKOFF_CAP_SECONDS: int = 24 * 3600

FAILURE_STATUS_PENDING = "pending"
FAILURE_STATUS_RETRYING = "retrying"
FAILURE_STATUS_RESOLVED = "resolved"
FAILURE_STATUS_PERMANENTLY_FAILED = "permanently_failed"

NON_TERMINAL_STATUSES = {FAILURE_STATUS_PENDING, FAILURE_STATUS_RETRYING}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _compute_next_attempt(retry_count: int) -> datetime:
    delay = min(BACKOFF_BASE_SECONDS * (2 ** retry_count), BACKOFF_CAP_SECONDS)
    return _utc_now() + timedelta(seconds=delay)


def _failure_query(uid: str, cid: str, source_type: str, source_id: str) -> dict:
    return {"user_id": uid, "company_id": cid,
            "source_type": source_type, "source_id": source_id}


# ── Failure-queue accessors ──────────────────────────────────────────────

async def ensure_hook_indexes() -> None:
    """Idempotent index setup for fin_hook_failures.

    Composite index on (user_id, company_id, source_type, source_id)
    keeps upserts O(1) and preserves the "one active row per source"
    invariant. No TTL — records are permanent until resolved.
    """
    await db.fin_hook_failures.create_index(
        [("user_id", 1), ("company_id", 1),
         ("source_type", 1), ("source_id", 1)],
        unique=True, name="fin_hook_fail_source_uniq",
    )
    await db.fin_hook_failures.create_index(
        [("user_id", 1), ("company_id", 1),
         ("status", 1), ("next_attempt_at", 1)],
        name="fin_hook_fail_replay_scan",
    )


async def _record_failure(
    uid: str, cid: str, source_type: str, source_id: str,
    error: str, action: str = "upsert",
) -> Dict[str, Any]:
    """Upsert a failure row for this source. If a resolved or
    permanently_failed row already exists, reopen it (status→pending,
    retry_count=0, next_attempt_at=+base backoff). Existing pending/
    retrying rows are updated in place (error refreshed, no retry_count
    change here — the retry driver increments)."""
    now = _utc_now()
    existing = await db.fin_hook_failures.find_one(
        _failure_query(uid, cid, source_type, source_id), {"_id": 0})

    if existing and existing.get("status") in NON_TERMINAL_STATUSES:
        # Refresh error without touching retry_count / next_attempt_at.
        await db.fin_hook_failures.update_one(
            _failure_query(uid, cid, source_type, source_id),
            {"$set": {"error": (error or "")[:2000],
                      "last_attempt_at": _iso(now)}},
        )
        return {**existing, "error": error, "last_attempt_at": _iso(now)}

    # New failure OR reopening a resolved/permanently_failed row.
    doc = {
        "id": existing["id"] if existing else f"hfail_{uuid.uuid4().hex[:16]}",
        "user_id": uid,
        "company_id": cid,
        "source_type": source_type,
        "source_id": source_id,
        "action": action,
        "error": (error or "")[:2000],
        "retry_count": 0,
        "created_at": existing["created_at"] if existing else _iso(now),
        "last_attempt_at": _iso(now),
        "next_attempt_at": _iso(_compute_next_attempt(0)),
        "status": FAILURE_STATUS_PENDING,
        "resolved_at": "",
        "history": [],
    }
    await db.fin_hook_failures.update_one(
        _failure_query(uid, cid, source_type, source_id),
        {"$set": doc}, upsert=True,
    )
    return doc


async def _resolve_failure(uid: str, cid: str, source_type: str,
                            source_id: str) -> Optional[str]:
    """Mark any pending/retrying failure for this source as resolved.
    Returns the failure_id if one was resolved, else None."""
    now = _utc_now()
    existing = await db.fin_hook_failures.find_one(
        {**_failure_query(uid, cid, source_type, source_id),
         "status": {"$in": list(NON_TERMINAL_STATUSES)}},
        {"_id": 0, "id": 1},
    )
    if not existing:
        return None
    await db.fin_hook_failures.update_one(
        _failure_query(uid, cid, source_type, source_id),
        {"$set": {"status": FAILURE_STATUS_RESOLVED,
                  "resolved_at": _iso(now),
                  "last_attempt_at": _iso(now)}},
    )
    return existing["id"]


# ── Canonical hook helper ────────────────────────────────────────────────

async def hook_after_source_write(
    user_id: str,
    company_id: str,
    source_type: str,
    source_id: str,
    action: str = "upsert",
) -> Dict[str, Any]:
    """Post-write projection hook.

    Contract:
      * Called AFTER an authoritative source-write has committed
        successfully.
      * Delegates entirely to `services_fin_txn.reproject_source(...)`.
      * NEVER raises upstream — a hook failure must not roll back or
        invalidate the source. Failures are persisted in
        `fin_hook_failures` for the retry driver to drain.
      * Returns a compact dict for logging / tests. `ok=False` when the
        projection failed; the caller MUST NOT treat that as a source
        error.

    Parameters:
      user_id / company_id — tenant scope.
      source_type          — must be one of A-1 `SUPPORTED_SOURCE_TYPES`.
      source_id            — id of the authoritative doc that just wrote.
      action               — advisory label ("upsert" | "delete_cascade").
                              Only "upsert" reproject is implemented in
                              Phase 1; delete-cascade is Phase 2+ scope.

    Returns:
      {
        "ok": bool,
        "source_type": str,
        "source_id": str,
        "deleted": int | None,
        "written": int | None,
        "error": str | None,
        "failure_id": str | None,     # set only on ok=False
        "resolved_failure_id": str    # set when a prior failure existed
                                       # and this call cleared it,
                                       # otherwise "".
      }
    """
    if source_type not in SUPPORTED_SOURCE_TYPES:
        # Programming error: caller passed an unsupported type. This is
        # NOT a projection failure (no source-to-project mapping exists)
        # so we do not enqueue a retry. We log + return ok=False so the
        # test / caller can observe the mistake.
        msg = (f"unsupported source_type={source_type!r} — "
               f"allowed: {SUPPORTED_SOURCE_TYPES}")
        logger.error(msg)
        return {"ok": False, "source_type": source_type,
                "source_id": source_id, "deleted": None, "written": None,
                "error": msg, "failure_id": None,
                "resolved_failure_id": ""}

    # Slice 2c: this source type may be owned by NestJS now. Default off.
    if _node_bridge_ready(source_type):
        report = await _delegate_to_node(user_id, company_id, source_type, source_id)
        if report is not None:
            return report

    try:
        deleted, written = await reproject_source(
            user_id, company_id, source_type, source_id)
    except Exception as ex:                              # noqa: BLE001
        err = f"{type(ex).__name__}: {ex}"
        logger.error(
            "fin hook failed uid=%s cid=%s src=%s/%s: %s",
            user_id, company_id, source_type, source_id, err,
        )
        try:
            f_doc = await _record_failure(
                user_id, company_id, source_type, source_id,
                error=err, action=action,
            )
            failure_id = f_doc.get("id", "")
        except Exception as record_ex:                   # noqa: BLE001
            # If we can't even persist the failure, log loud but still
            # don't raise — source stays authoritative.
            logger.critical(
                "fin_hook_failures write failed uid=%s src=%s/%s: %s",
                user_id, source_type, source_id, record_ex,
            )
            failure_id = ""
        return {"ok": False, "source_type": source_type,
                "source_id": source_id, "deleted": None, "written": None,
                "error": err, "failure_id": failure_id,
                "resolved_failure_id": ""}

    # Projection succeeded — auto-resolve any lingering pending failure.
    resolved_id = ""
    try:
        r = await _resolve_failure(user_id, company_id, source_type, source_id)
        resolved_id = r or ""
    except Exception:
        logger.exception("failed to auto-resolve failure row (non-fatal)")

    return {"ok": True, "source_type": source_type,
            "source_id": source_id, "deleted": int(deleted or 0),
            "written": int(written or 0), "error": None,
            "failure_id": None, "resolved_failure_id": resolved_id}


# ── Retry driver ─────────────────────────────────────────────────────────

async def replay_pending_failures(
    *,
    user_id: Optional[str] = None,
    company_id: Optional[str] = None,
    limit: int = 100,
    dry_run: bool = False,
    ignore_schedule: bool = False,
    verbose: bool = False,
) -> Dict[str, Any]:
    """Drain pending / retrying failures whose `next_attempt_at` is due.

    Parameters:
      user_id / company_id — scope the sweep to a tenant (both must be
                              passed together; passing only company_id
                              filters by company across users, which is
                              still tenant-safe because our data model
                              couples uid+cid).
      limit                — max rows to attempt this call.
      dry_run              — report what would be retried; write nothing.
      ignore_schedule      — replay all non-terminal rows regardless of
                              `next_attempt_at`. Used by tests and by
                              the operator when they want to force a
                              full sweep after fixing a systemic issue.
      verbose              — include per-row info in the response.

    Returns:
      {
        "attempted":            int,
        "succeeded":            int,
        "failed":               int,
        "permanently_failed":   int,
        "remaining":            int,   # pending/retrying rows not touched
        "rows":                 [ ... ] if verbose else [],
      }
    """
    now = _utc_now()
    q: Dict[str, Any] = {"status": {"$in": list(NON_TERMINAL_STATUSES)}}
    if user_id:
        q["user_id"] = user_id
    if company_id:
        q["company_id"] = company_id
    if not ignore_schedule:
        q["next_attempt_at"] = {"$lte": _iso(now)}

    cursor = db.fin_hook_failures.find(q, {"_id": 0}) \
        .sort([("next_attempt_at", 1)])
    if limit:
        cursor = cursor.limit(int(max(1, min(limit, 10000))))

    attempted = succeeded = failed = perm = 0
    verbose_rows: List[dict] = []

    async for row in cursor:
        attempted += 1
        if dry_run:
            if verbose:
                verbose_rows.append({
                    "id": row["id"], "source_type": row["source_type"],
                    "source_id": row["source_id"], "retry_count": row["retry_count"],
                    "status": row["status"], "would_retry": True,
                })
            continue

        # Actual retry — call reproject_source directly (not the
        # hook helper) so we can observe the raw outcome without
        # recursively re-recording.
        try:
            deleted, written = await reproject_source(
                row["user_id"], row["company_id"],
                row["source_type"], row["source_id"],
            )
            # Success — mark resolved.
            await db.fin_hook_failures.update_one(
                {"id": row["id"]},
                {"$set": {"status": FAILURE_STATUS_RESOLVED,
                          "resolved_at": _iso(_utc_now()),
                          "last_attempt_at": _iso(_utc_now())}},
            )
            succeeded += 1
            if verbose:
                verbose_rows.append({
                    "id": row["id"], "source_type": row["source_type"],
                    "source_id": row["source_id"], "result": "resolved",
                    "deleted": deleted, "written": written,
                })
        except Exception as ex:                          # noqa: BLE001
            err = f"{type(ex).__name__}: {ex}"
            new_count = int(row.get("retry_count", 0)) + 1
            history = list(row.get("history") or [])[-4:]
            history.append({"attempt": new_count, "at": _iso(_utc_now()),
                            "error": err[:400]})
            if new_count >= MAX_RETRIES:
                new_status = FAILURE_STATUS_PERMANENTLY_FAILED
                perm += 1
                if verbose:
                    verbose_rows.append({
                        "id": row["id"], "source_type": row["source_type"],
                        "source_id": row["source_id"],
                        "result": "permanently_failed",
                        "retry_count": new_count, "error": err,
                    })
            else:
                new_status = FAILURE_STATUS_RETRYING
                failed += 1
                if verbose:
                    verbose_rows.append({
                        "id": row["id"], "source_type": row["source_type"],
                        "source_id": row["source_id"], "result": "will_retry",
                        "retry_count": new_count, "error": err,
                    })
            await db.fin_hook_failures.update_one(
                {"id": row["id"]},
                {"$set": {
                    "status": new_status,
                    "retry_count": new_count,
                    "error": err[:2000],
                    "last_attempt_at": _iso(_utc_now()),
                    "next_attempt_at": _iso(_compute_next_attempt(new_count)),
                    "history": history,
                }},
            )

    remaining_q = dict(q)
    remaining_q["status"] = {"$in": list(NON_TERMINAL_STATUSES)}
    remaining_q.pop("next_attempt_at", None)
    remaining = await db.fin_hook_failures.count_documents(remaining_q)

    return {
        "attempted": attempted,
        "succeeded": succeeded,
        "failed": failed,
        "permanently_failed": perm,
        "remaining": remaining,
        "rows": verbose_rows,
        "dry_run": dry_run,
    }
