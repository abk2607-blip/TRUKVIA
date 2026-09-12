"""Iter150D · Day Closing model + index helper (additive, non-invasive).

Kept in a new file to preserve `backend/models.py` byte-for-byte under the
Iter150B/150C locked-band covenant.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, ConfigDict, Field

from db import db
from models import new_id, now_utc  # reuse existing helpers · no models.py edit


class FinDayClosure(BaseModel):
    """Financial-control checkpoint for one business day per tenant.

    Not a data-entry lock: any past business date remains enterable across
    every canonical source type even after its day has been closed.
    """
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("fdc_"))
    user_id: str = ""
    company_id: str = ""
    close_date: str                       # ISO YYYY-MM-DD (today or past)
    status: Literal["closed", "reopened"] = "closed"
    closed_at: str = Field(default_factory=lambda: now_utc().isoformat())
    closed_by: str = ""
    close_notes: str = ""
    # {account_code: {"in": …, "out": …, "net": …}} — immutable for this close.
    snapshot: Dict[str, Dict[str, float]] = Field(default_factory=dict)
    snapshot_source_count: int = 0
    reopened_at: str = ""
    reopened_by: str = ""
    reopen_reason: str = ""
    # Append-only lifecycle audit. Each closed event carries its own snapshot
    # so history remains reconstructable across reopen → re-close cycles.
    history: List[Dict[str, Any]] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())
    modified_at: str = ""


async def ensure_day_closure_indexes() -> None:
    """Idempotent index creation. Called from server startup."""
    # Primary uniqueness: one closure row per company-day.
    await db.fin_day_closures.create_index(
        [("user_id", 1), ("company_id", 1), ("close_date", 1)],
        unique=True,
    )
    # Fast status lookup (open closures, reopened closures).
    await db.fin_day_closures.create_index(
        [("user_id", 1), ("company_id", 1), ("status", 1)],
    )
    # Chronological listing.
    await db.fin_day_closures.create_index(
        [("user_id", 1), ("company_id", 1), ("closed_at", -1)],
    )
