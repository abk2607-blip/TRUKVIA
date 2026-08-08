"""Iter38 — Nightly scheduled tasks (cron).

Runs inside the backend FastAPI process using APScheduler AsyncIOScheduler.
Currently schedules:
  - Daily WhatsApp reminder digest at 18:00 IST — writes to db.reminder_digests for the owner to review
    the next morning (does NOT auto-send WhatsApp — that requires each owner to click the deeplink).

Owners can toggle their global reminder preference via /api/reminders/schedule (GET/PUT).
"""
from __future__ import annotations
import logging
import os
from datetime import datetime, timezone, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from db import db

logger = logging.getLogger(__name__)
_scheduler: AsyncIOScheduler | None = None


async def _nightly_reminder_digest():
    """Compute per-owner outstanding-customer reminders and cache them in db.reminder_digests."""
    logger.info("[cron] nightly reminder digest started")
    now = datetime.now(timezone.utc)
    # Iterate over every distinct user with reminders enabled at company-level (default: enabled)
    users = await db.users.find({}, {"_id": 0, "user_id": 1}).to_list(5000)
    total_users = 0
    for u in users:
        uid = u.get("user_id")
        if not uid:
            continue
        # Aggregate outstanding across the owner's companies
        invs = await db.invoices.find(
            {"user_id": uid, "balance_due": {"$gt": 0}},
            {"_id": 0}
        ).to_list(20000)
        if not invs:
            continue
        buckets: dict = {}
        for i in invs:
            k = (i.get("company_id"), i.get("customer_id"))
            if not k[0] or not k[1]:
                continue
            b = buckets.setdefault(k, {"balance": 0.0, "invoices": 0, "oldest_days": 0})
            b["balance"] += float(i.get("balance_due", 0))
            b["invoices"] += 1
            try:
                dt = datetime.fromisoformat(i["date"]).date()
            except Exception:
                dt = now.date()
            b["oldest_days"] = max(b["oldest_days"], (now.date() - dt).days)
        entries = [
            {"company_id": k[0], "customer_id": k[1], **v}
            for k, v in buckets.items()
        ]
        await db.reminder_digests.replace_one(
            {"user_id": uid, "date": now.date().isoformat()},
            {
                "user_id": uid,
                "date": now.date().isoformat(),
                "generated_at": now.isoformat(),
                "entries": entries,
                "total_customers": len(entries),
                "total_outstanding": round(sum(e["balance"] for e in entries), 2),
            },
            upsert=True,
        )
        total_users += 1
    logger.info(f"[cron] nightly reminder digest completed for {total_users} owners")


def start_scheduler():
    """Start the scheduler. Idempotent — safe to call more than once."""
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    if os.environ.get("DISABLE_SCHEDULER") == "1":
        logger.info("[cron] scheduler disabled via DISABLE_SCHEDULER")
        return None
    try:
        # IST-friendly schedule (evening).
        # Store the trigger time in UTC because container timezone may be UTC.
        # 18:00 IST = 12:30 UTC.
        _scheduler = AsyncIOScheduler(timezone="UTC")
        _scheduler.add_job(
            _nightly_reminder_digest,
            CronTrigger(hour=12, minute=30),   # 18:00 IST
            id="nightly_reminder_digest",
            replace_existing=True,
            misfire_grace_time=3600,
        )
        _scheduler.start()
        logger.info("[cron] scheduler started — nightly_reminder_digest @ 18:00 IST")
    except Exception as e:
        logger.exception(f"[cron] scheduler failed to start: {e}")
        _scheduler = None
    return _scheduler


def stop_scheduler():
    global _scheduler
    if _scheduler:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:
            pass
        _scheduler = None
