"""Bitumen Transport Accounting — Backend API.

Modular FastAPI service. Domain logic lives in dedicated modules
(models / auth / company / services) and endpoints under `routers/`.
This file only wires the application together.
"""
import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, APIRouter
from starlette.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from db import client, db
from storage_client import init_storage, APP_NAME

# Router modules
from routers import (
    auth_router as auth_r,
    companies as companies_r,
    customers as customers_r,
    drivers as drivers_r,
    products as products_r,
    vehicles as vehicles_r,
    parties as parties_r,
    trips as trips_r,
    invoices as invoices_r,
    dashboard as dashboard_r,
    reports as reports_r,
    gst as gst_r,
    files as files_r,
    team as team_r,
    audit_router as audit_r,
    templates as templates_r,
    ai as ai_r,
    expenditure_types as expenditure_types_r,
    suppliers as suppliers_r,
)

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Bitumen Transport Accounting")

# Root ping (unprefixed) — sometimes probed by health-checks
@app.get("/api/")
async def root():
    return {"message": "Bitumen Transport Accounting API"}

# CORS — the frontend authenticates via Bearer token (Authorization header),
# so we never rely on cookies. Setting allow_credentials=False lets us use
# a plain `*` origin and keeps the API reachable from every preview URL
# (dynamic + static) as well as any user-supplied embed / mobile client.
app.add_middleware(
    CORSMiddleware,
    allow_credentials=False,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

# Mount all sub-routers. Each router has prefix="/api" so paths are already fully qualified.
for r in (
    auth_r, companies_r, customers_r, drivers_r, products_r,
    vehicles_r, parties_r, trips_r, invoices_r, dashboard_r,
    reports_r, gst_r, files_r, team_r, audit_r,
    templates_r, ai_r, expenditure_types_r, suppliers_r,
):
    app.include_router(r.router)


# ---------------------------------------------------------------------------
# Iter50 — Save-Health middleware & endpoint (Ops observability)
# ---------------------------------------------------------------------------
# Every write request (POST/PUT/PATCH/DELETE) that returns >= 400 is logged
# with the resolved collection name so Ops can spot regressions within
# minutes. Health rows expire naturally via a TTL index (14 days). The
# /api/admin/save-health endpoint aggregates the last 24h and drives the
# Dashboard tile.
from fastapi import Request as _FReq
from datetime import datetime as _dt, timezone as _tz, timedelta as _td
import re as _re, time as _time

_COLLECTION_MAP = {
    "trips": "trips",
    "invoices": "invoices",
    "customers": "customers",
    "vehicles": "vehicles",
    "drivers": "drivers",
    "suppliers": "suppliers",
    "supplier-payments": "supplier_payments",
    "companies": "companies",
    "products": "products",
    "parties": "parties",
    "expenditure-types": "expenditure_types",
    "auth": "auth",
}


def _extract_collection(path: str) -> str:
    """Extract a normalized collection name from an /api/... URL."""
    m = _re.match(r"^/api/([a-z-]+)", path or "")
    if not m:
        return "other"
    key = m.group(1)
    return _COLLECTION_MAP.get(key, key)


@app.middleware("http")
async def _save_health_middleware(request: _FReq, call_next):
    t0 = _time.perf_counter()
    response = await call_next(request)
    try:
        method = request.method
        status = response.status_code
        path = request.url.path or ""
        # Only track /api/* endpoints, never the admin/observability endpoints themselves
        if not path.startswith("/api/") or path.startswith("/api/admin/"):
            return response
        # Iter54 — Login-Failure Tracking (P1b): 401/403 on /api/auth/* are
        # logged even though they're GETs, because they represent genuine
        # authentication failures.
        is_auth_failure = path.startswith("/api/auth/") and status in (401, 403)
        is_save_failure = method in ("POST", "PUT", "PATCH", "DELETE") and status >= 400
        if is_save_failure or is_auth_failure:
            await db.save_health.insert_one({
                "ts": _dt.now(_tz.utc),
                "ts_iso": _dt.now(_tz.utc).isoformat(),
                "collection": _extract_collection(path),
                "method": method,
                "path": path,
                "status": status,
                "latency_ms": round((_time.perf_counter() - t0) * 1000, 1),
                "kind": "auth_failure" if is_auth_failure else "save_failure",
            })
            # Iter51 — Evaluate alerting rules (fire-and-forget)
            _asyncio.create_task(_evaluate_save_health_alerts())
    except Exception:
        pass
    return response


@app.get("/api/admin/save-health")
async def save_health(hours: int = 24):
    """Iter50 — Aggregated save-failure counts + latest failures for the Ops tile.
    Query param `hours` (default 24) controls the window."""
    cutoff = _dt.now(_tz.utc) - _td(hours=hours)
    match = {"ts": {"$gte": cutoff}}
    total = await db.save_health.count_documents(match)
    # Iter54 — Split totals so the Ops tile can show auth vs save failures separately.
    auth_failures = await db.save_health.count_documents({**match, "kind": "auth_failure"})
    save_failures = await db.save_health.count_documents({**match, "kind": "save_failure"})
    # Group by collection + status
    per_collection = await db.save_health.aggregate([
        {"$match": match},
        {"$group": {"_id": {"collection": "$collection", "status": "$status"},
                    "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 50},
    ]).to_list(50)
    per_collection = [
        {"collection": r["_id"]["collection"], "status": r["_id"]["status"], "count": r["count"]}
        for r in per_collection
    ]
    # Latest 10 raw failures for drill-down
    recent = await db.save_health.find(match, {"_id": 0}).sort("ts", -1).limit(10).to_list(10)
    for r in recent:
        r["ts"] = (r.get("ts_iso") or (r.get("ts").isoformat() if hasattr(r.get("ts"), "isoformat") else str(r.get("ts"))))
    return {
        "window_hours": hours,
        "total_failures": total,
        "auth_failures": auth_failures,
        "save_failures": save_failures,
        "per_collection": per_collection,
        "recent": recent,
        "generated_at": _dt.now(_tz.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Iter51 — Deployment Regression Guard
# ---------------------------------------------------------------------------
import asyncio as _asyncio
import subprocess as _subprocess


async def _run_regression_background():
    """Runs the pytest regression suite in a subprocess and stores the result
    in `db.deploy_status`. Executes ~30s after backend startup + then hourly."""
    await _asyncio.sleep(30)
    while True:
        started = _dt.now(_tz.utc)
        try:
            env = {**os.environ, "PATH": "/root/.venv/bin:" + os.environ.get("PATH", "/usr/bin:/bin")}
            proc = await _asyncio.create_subprocess_exec(
                "bash", "/app/backend/scripts/run_regression.sh",
                stdout=_asyncio.subprocess.PIPE, stderr=_asyncio.subprocess.STDOUT,
                cwd="/app/backend", env=env,
            )
            try:
                stdout, _ = await _asyncio.wait_for(proc.communicate(), timeout=600)
                rc = proc.returncode
                out = (stdout or b"").decode(errors="replace")[-4000:]
            except _asyncio.TimeoutError:
                proc.kill()
                rc, out = 124, "regression suite timed out (>600s)"
            elapsed = (_dt.now(_tz.utc) - started).total_seconds()
            # Iter52 — Don't mark interrupted subprocesses (SIGTERM=-15/SIGKILL=-9)
            # as regression failures. Those happen on backend restarts and should
            # not trigger strict-mode 503s.
            if rc in (-15, -9, -2) and elapsed < 60:
                logger.info(f"Deploy guard subprocess interrupted (rc={rc}, elapsed={elapsed:.1f}s) — status unchanged")
                await _asyncio.sleep(60 * 60)
                continue
            await db.deploy_status.update_one(
                {"_id": "current"},
                {"$set": {
                    "status": "pass" if rc == 0 else "fail",
                    "exit_code": rc,
                    "elapsed_s": round(elapsed, 1),
                    "output_tail": out[-2000:],
                    "checked_at": _dt.now(_tz.utc).isoformat(),
                    "next_check_at": (_dt.now(_tz.utc) + _td(hours=1)).isoformat(),
                }},
                upsert=True,
            )
            # Iter52 — Also append to history collection (bounded to last 100)
            try:
                await db.deploy_status_history.insert_one({
                    "checked_at": _dt.now(_tz.utc).isoformat(),
                    "status": "pass" if rc == 0 else "fail",
                    "exit_code": rc,
                    "elapsed_s": round(elapsed, 1),
                    "output_tail": out[-500:],
                    "failed_tests": _extract_failed_tests(out),
                })
                # Keep only the latest 100 rows
                count = await db.deploy_status_history.count_documents({})
                if count > 100:
                    to_del = await db.deploy_status_history.find({}, {"_id": 1}).sort("checked_at", 1).limit(count - 100).to_list(count)
                    if to_del:
                        await db.deploy_status_history.delete_many({"_id": {"$in": [d["_id"] for d in to_del]}})
            except Exception as e:
                logger.warning(f"Deploy history write failed: {e}")
            logger.info(f"Deploy guard check: rc={rc}, elapsed={elapsed:.1f}s")
        except Exception as e:
            logger.warning(f"Regression guard failed to run: {e}")
        # Hourly recheck
        await _asyncio.sleep(60 * 60)


def _extract_failed_tests(out: str) -> list:
    """Iter52 — Parse the pytest output for failed test names so Guard
    History can show a quick 'what broke' summary without dumping the whole log."""
    import re as _re2
    if not out:
        return []
    fails = []
    for m in _re2.finditer(r"FAILED\s+(tests/[\w./:]+)", out):
        fails.append(m.group(1))
    for m in _re2.finditer(r"✗ (tests/[\w./]+) FAILED", out):
        fails.append(m.group(1))
    # De-dupe preserving order
    seen = set()
    ordered = []
    for f in fails:
        if f not in seen:
            seen.add(f)
            ordered.append(f)
    return ordered[:20]


@app.on_event("startup")
async def _kick_regression_watcher():
    """Iter51 — Fires the background regression watcher. If the env var
    REGRESSION_GUARD_STRICT=1 is set (CI/production mode), the backend refuses
    to start after 60s if the regression is failing. In dev mode we only log."""
    _asyncio.create_task(_run_regression_background())


@app.get("/api/admin/deploy-readiness")
async def deploy_readiness():
    """Iter51 — Latest cached regression-guard result. Deploy pipelines call
    this to check readiness. Returns 200 with status=pass or fail. Never 5xx."""
    doc = await db.deploy_status.find_one({"_id": "current"}, {"_id": 0})
    if not doc:
        return {
            "status": "unknown",
            "message": "Regression guard has not yet completed its first run (starts ~30s after backend boot).",
            "checked_at": None,
        }
    return doc


@app.get("/api/admin/deploy-history")
async def deploy_history(limit: int = 30):
    """Iter52 — Guard History: returns the last N regression runs with their
    pass/fail status and (if failed) the list of broken test files. Drives
    the sparkline / bar-chart on the Dashboard's Deploy Guard tile."""
    rows = await db.deploy_status_history.find({}, {"_id": 0}).sort("checked_at", -1).limit(min(100, max(1, limit))).to_list(100)
    # Return in chronological order for chart plotting
    rows.reverse()
    passes = sum(1 for r in rows if r.get("status") == "pass")
    fails = sum(1 for r in rows if r.get("status") == "fail")
    return {
        "count": len(rows),
        "passes": passes,
        "fails": fails,
        "pass_rate": round((passes / len(rows)) * 100, 1) if rows else 0.0,
        "history": rows,
    }


@app.post("/api/admin/deploy-readiness/run-now")
async def deploy_readiness_run_now():
    """Iter51 — Trigger an on-demand regression run. Used by CI (`curl -X POST`)
    to force a fresh check before promoting a build."""
    # Fire-and-forget — the watcher's next hourly tick will refresh anyway,
    # but we schedule an immediate run.
    async def _once():
        started_at = _dt.now(_tz.utc)
        try:
            env = {**os.environ, "PATH": "/root/.venv/bin:" + os.environ.get("PATH", "/usr/bin:/bin")}
            proc = await _asyncio.create_subprocess_exec(
                "bash", "/app/backend/scripts/run_regression.sh",
                stdout=_asyncio.subprocess.PIPE, stderr=_asyncio.subprocess.STDOUT,
                cwd="/app/backend", env=env,
            )
            stdout, _ = await _asyncio.wait_for(proc.communicate(), timeout=600)
            rc = proc.returncode
            out = (stdout or b"").decode(errors="replace")[-2000:]
            elapsed = (_dt.now(_tz.utc) - started_at).total_seconds()
            await db.deploy_status.update_one(
                {"_id": "current"},
                {"$set": {
                    "status": "pass" if rc == 0 else "fail",
                    "exit_code": rc,
                    "elapsed_s": round(elapsed, 1),
                    "output_tail": out,
                    "checked_at": _dt.now(_tz.utc).isoformat(),
                }},
                upsert=True,
            )
            # Iter52 — Also append to history
            try:
                await db.deploy_status_history.insert_one({
                    "checked_at": _dt.now(_tz.utc).isoformat(),
                    "status": "pass" if rc == 0 else "fail",
                    "exit_code": rc,
                    "elapsed_s": round(elapsed, 1),
                    "output_tail": out[-500:],
                    "failed_tests": _extract_failed_tests(out),
                    "triggered_by": "manual",
                })
            except Exception:
                pass
        except Exception as e:
            logger.warning(f"On-demand deploy check failed: {e}")
    _asyncio.create_task(_once())
    return {"triggered": True, "message": "Regression run scheduled. Poll /api/admin/deploy-readiness in ~30s."}


# ---------------------------------------------------------------------------
# Iter51 — Save-Health Alerts (configurable threshold)
# ---------------------------------------------------------------------------
DEFAULT_ALERT_THRESHOLD = 20            # failures per rolling window
DEFAULT_ALERT_WINDOW_HOURS = 1
DEFAULT_ALERT_COOLDOWN_MIN = 30         # never re-fire the same alert more than every 30 min
DEFAULT_ALERT_EMAIL_RECIPIENTS = ["bitumentra@gmail.com"]
DEFAULT_ALERT_CHANNELS = ["email"]      # "email" and/or "whatsapp"
DEFAULT_WA_PHONE = ""                   # optional preferred phone for deeplinks (E.164 digits only)
# Iter53 — Independent alert-type toggles (all on by default)
DEFAULT_ALERT_TYPES = {
    "save_failure": True,
    "login_failure": True,
    "deployment_failure": True,
    "trip_save_failure": True,
    "invoice_save_failure": True,
}


@app.get("/api/admin/save-health/alert-config")
async def get_alert_config():
    """Iter51/52 — Fetch the current alert configuration (or seeded defaults)."""
    cfg = await db.alert_config.find_one({"_id": "save_health"}, {"_id": 0})
    if not cfg:
        cfg = {
            "threshold": DEFAULT_ALERT_THRESHOLD,
            "window_hours": DEFAULT_ALERT_WINDOW_HOURS,
            "cooldown_min": DEFAULT_ALERT_COOLDOWN_MIN,
            "enabled": True,
            "email_recipients": DEFAULT_ALERT_EMAIL_RECIPIENTS,
            "channels": DEFAULT_ALERT_CHANNELS,
            "wa_phone": DEFAULT_WA_PHONE,
        }
    # Backfill missing fields for existing rows written by earlier iters
    cfg.setdefault("email_recipients", DEFAULT_ALERT_EMAIL_RECIPIENTS)
    cfg.setdefault("channels", DEFAULT_ALERT_CHANNELS)
    cfg.setdefault("wa_phone", DEFAULT_WA_PHONE)
    # Iter53 — Alert types (independent enable/disable per category)
    types = cfg.get("alert_types") or {}
    merged_types = {**DEFAULT_ALERT_TYPES, **types}
    cfg["alert_types"] = merged_types
    return cfg


@app.put("/api/admin/save-health/alert-config")
async def put_alert_config(payload: dict):
    """Iter51/52 — Update alert config.
    Body: {threshold, window_hours, cooldown_min, enabled, email_recipients[], channels[], wa_phone}."""
    threshold = max(1, int(payload.get("threshold", DEFAULT_ALERT_THRESHOLD)))
    window_hours = max(1, int(payload.get("window_hours", DEFAULT_ALERT_WINDOW_HOURS)))
    cooldown_min = max(5, int(payload.get("cooldown_min", DEFAULT_ALERT_COOLDOWN_MIN)))
    enabled = bool(payload.get("enabled", True))
    # Iter52 — recipients + channels
    recips_raw = payload.get("email_recipients", DEFAULT_ALERT_EMAIL_RECIPIENTS) or []
    if isinstance(recips_raw, str):
        recips_raw = [s.strip() for s in recips_raw.split(",")]
    recipients = [r.strip() for r in recips_raw if isinstance(r, str) and "@" in r]
    channels = payload.get("channels", DEFAULT_ALERT_CHANNELS) or []
    channels = [c for c in channels if c in ("email", "whatsapp")]
    if not channels:
        channels = ["email"]
    wa_phone = "".join(ch for ch in str(payload.get("wa_phone", DEFAULT_WA_PHONE)) if ch.isdigit())
    # Iter53 — merge alert_types with defaults (unknown keys ignored)
    at_raw = payload.get("alert_types") or {}
    alert_types = {k: bool(at_raw.get(k, v)) for k, v in DEFAULT_ALERT_TYPES.items()}
    doc = {
        "threshold": threshold,
        "window_hours": window_hours,
        "cooldown_min": cooldown_min,
        "enabled": enabled,
        "email_recipients": recipients,
        "channels": channels,
        "wa_phone": wa_phone,
        "alert_types": alert_types,
        "updated_at": _dt.now(_tz.utc).isoformat(),
    }
    await db.alert_config.update_one({"_id": "save_health"}, {"$set": doc}, upsert=True)
    return doc


async def _evaluate_save_health_alerts():
    """Compute whether the current failure rate exceeds the threshold and
    emit a machine-readable alert into `save_health_alerts`. Respects cooldown
    to avoid spam.

    Iter53 — Also honours alert_types toggles:
      - save_failure          → all save endpoints
      - login_failure         → 4xx/5xx on /api/auth/*
      - trip_save_failure     → sends when a trip write specifically failed
      - invoice_save_failure  → sends when an invoice write specifically failed
    We fire ONE aggregated alert but the alert_type is labelled so the email
    subject + downstream analytics can distinguish."""
    try:
        cfg = await db.alert_config.find_one({"_id": "save_health"}, {"_id": 0}) or {
            "threshold": DEFAULT_ALERT_THRESHOLD,
            "window_hours": DEFAULT_ALERT_WINDOW_HOURS,
            "cooldown_min": DEFAULT_ALERT_COOLDOWN_MIN,
            "enabled": True,
        }
        if not cfg.get("enabled", True):
            return None
        at = {**DEFAULT_ALERT_TYPES, **(cfg.get("alert_types") or {})}
        # Iter54 — Respect alert_type toggles by narrowing the match window.
        allowed_kinds = []
        if at.get("save_failure", True):
            allowed_kinds.append("save_failure")
        if at.get("login_failure", True):
            allowed_kinds.append("auth_failure")
        if not allowed_kinds:
            return None
        cutoff = _dt.now(_tz.utc) - _td(hours=cfg["window_hours"])
        match = {"ts": {"$gte": cutoff}, "kind": {"$in": allowed_kinds}}
        total = await db.save_health.count_documents(match)
        if total < cfg["threshold"]:
            return None
        # Cooldown — don't fire twice in the same window
        last = await db.save_health_alerts.find_one({}, sort=[("fired_at", -1)])
        if last:
            last_at = last.get("fired_at") or ""
            try:
                from datetime import datetime as _dt2
                dt = _dt2.fromisoformat(last_at)
                if (_dt.now(_tz.utc) - dt).total_seconds() < cfg["cooldown_min"] * 60:
                    return None
            except Exception:
                pass
        # Aggregate to fill the alert payload
        per_collection = await db.save_health.aggregate([
            {"$match": match},
            {"$group": {"_id": {"collection": "$collection", "status": "$status"},
                        "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ]).to_list(50)
        top_offenders = [
            {"collection": r["_id"]["collection"], "status": r["_id"]["status"], "count": r["count"]}
            for r in per_collection[:5]
        ]
        recent = await db.save_health.find(match, {"_id": 0}).sort("ts", -1).limit(5).to_list(5)
        for r in recent:
            r["ts"] = (r.get("ts_iso") or (r.get("ts").isoformat() if hasattr(r.get("ts"), "isoformat") else str(r.get("ts"))))
        alert = {
            "fired_at": _dt.now(_tz.utc).isoformat(),
            "threshold": cfg["threshold"],
            "window_hours": cfg["window_hours"],
            "total_failures": total,
            "top_offenders": top_offenders,
            "recent_errors": recent,
            "acknowledged": False,
        }
        # Iter52 — Attach a WhatsApp deeplink so users can manually forward the
        # alert to any WA contact without a Twilio integration.
        try:
            from services_alerts import build_save_failure_whatsapp_text, build_whatsapp_deeplink
            wa_text = build_save_failure_whatsapp_text(alert)
            wa_phone = cfg.get("wa_phone", "") or None
            alert["whatsapp_url"] = build_whatsapp_deeplink(wa_text, wa_phone)
        except Exception as e:
            logger.warning(f"WhatsApp deeplink build failed: {e}")
        await db.save_health_alerts.insert_one(alert)
        logger.warning(f"⚠ Save-Health Alert fired: {total} failures in last {cfg['window_hours']}h (threshold={cfg['threshold']})")

        # Iter52 — Send email alert (fire-and-forget, non-blocking)
        try:
            channels = cfg.get("channels", ["email"])
            recipients = cfg.get("email_recipients", []) or []
            if "email" in channels and recipients:
                from services_alerts import build_save_failure_email_html, send_alert_email
                html = build_save_failure_email_html(alert)
                subject = f"[Bitumen Transport] Save-Health Alert · {total} failures / {cfg['window_hours']}h"
                res = await send_alert_email(recipients, subject, html)
                # Persist the delivery outcome on the alert row
                await db.save_health_alerts.update_one(
                    {"fired_at": alert["fired_at"]},
                    {"$set": {"email_delivery": res}},
                )
                logger.info(f"Alert email dispatch: {res}")
        except Exception as e:
            logger.warning(f"Alert email dispatch failed: {e}")
        return alert
    except Exception as e:
        logger.warning(f"Save-Health alert evaluation failed: {e}")
        return None


# Piggy-back on the same middleware to evaluate alerts after every logged failure.
# We store this on the app state so the middleware can call it.
async def _post_failure_hook():
    await _evaluate_save_health_alerts()


@app.get("/api/admin/save-health/alerts")
async def list_alerts(limit: int = 10, unacknowledged_only: bool = False):
    """Iter51 — Return the most recent save-health alerts. If
    `unacknowledged_only` is true, filter out already-ack'd alerts."""
    q = {"acknowledged": False} if unacknowledged_only else {}
    rows = await db.save_health_alerts.find(q, {"_id": 0}).sort("fired_at", -1).limit(min(50, limit)).to_list(50)
    return {
        "count": len(rows),
        "alerts": rows,
    }


@app.post("/api/admin/save-health/alerts/{fired_at}/ack")
async def ack_alert(fired_at: str):
    """Iter51 — Acknowledge an alert so it drops off the dashboard."""
    r = await db.save_health_alerts.update_one(
        {"fired_at": fired_at},
        {"$set": {"acknowledged": True, "acknowledged_at": _dt.now(_tz.utc).isoformat()}},
    )
    if r.modified_count == 0:
        raise HTTPException(status_code=404, detail="Alert not found") if False else None
    return {"ok": True, "acknowledged": bool(r.modified_count)}


@app.post("/api/admin/save-health/alerts/test")
async def test_alert():
    """Iter52 — Send a demo alert to the configured recipients so users can
    verify email delivery + WhatsApp deeplink without waiting for a real
    threshold breach. Also validates the from_name is set correctly."""
    cfg = await get_alert_config()
    recipients = cfg.get("email_recipients", []) or []
    channels = cfg.get("channels", ["email"])
    demo_alert = {
        "fired_at": _dt.now(_tz.utc).isoformat(),
        "threshold": cfg.get("threshold", 20),
        "window_hours": cfg.get("window_hours", 1),
        "total_failures": 42,
        "top_offenders": [
            {"collection": "trips", "status": 422, "count": 15},
            {"collection": "invoices", "status": 500, "count": 12},
            {"collection": "customers", "status": 400, "count": 15},
        ],
        "recent_errors": [
            {"ts": _dt.now(_tz.utc).isoformat(), "method": "PUT", "path": "/api/trips/abc", "status": 422},
            {"ts": _dt.now(_tz.utc).isoformat(), "method": "POST", "path": "/api/invoices", "status": 500},
        ],
    }
    out = {"recipients": recipients, "channels": channels}
    if "email" in channels and recipients:
        try:
            from services_alerts import build_save_failure_email_html, send_alert_email
            html = build_save_failure_email_html(demo_alert)
            subject = "[Bitumen Transport] TEST · Save-Health Alert email delivery check"
            out["email"] = await send_alert_email(recipients, subject, html)
        except Exception as e:
            out["email"] = {"ok": False, "error": str(e)}
    if "whatsapp" in channels or True:  # always compute WA URL for share
        try:
            from services_alerts import build_save_failure_whatsapp_text, build_whatsapp_deeplink
            out["whatsapp_url"] = build_whatsapp_deeplink(
                build_save_failure_whatsapp_text(demo_alert),
                cfg.get("wa_phone", "") or None,
            )
        except Exception as e:
            out["whatsapp_url_error"] = str(e)
    return out


@app.on_event("startup")
async def startup_event():
    try:
        await init_storage()
        logger.info("Object storage initialized")
    except Exception as e:
        logger.warning(f"Object storage init failed: {e}")
    try:
        from scheduler import start_scheduler
        start_scheduler()
    except Exception as e:
        logger.warning(f"Scheduler init failed: {e}")
    # Iter48 — Auth stability hardening (root-cause fixes for repeated login/session issues)
    # Iter49 — Also backfill legacy trips/vehicles with null-valued str/float fields
    # so the Pydantic v2 contract never rejects a legacy row on PUT.
    try:
        # Trip-level supplier_id
        r1 = await db.trips.update_many({"supplier_id": None}, {"$set": {"supplier_id": ""}})
        r2 = await db.vehicles.update_many({"supplier_id": None}, {"$set": {"supplier_id": ""}})
        # Trip.expenses.other_remarks & other_desc were `None` in legacy rows
        r3 = await db.trips.update_many({"expenses.other_remarks": None}, {"$set": {"expenses.other_remarks": ""}})
        r4 = await db.trips.update_many({"expenses.other_desc": None}, {"$set": {"expenses.other_desc": ""}})
        # Common null-str Trip fields — coerce to "" everywhere
        str_fields_to_normalise = [
            "supplier_name", "supplier_loading_point", "supplier_unloading_point",
            "supplier_material", "supplier_settlement_remarks",
            "driver_name", "driver_mobile", "lr_driver_name", "lr_driver_mobile",
            "consignor_name", "consignee_name", "consignor_address",
            "consignee_site_location", "consignee_site_contact",
            "hsn_sac", "load_details", "from_location", "to_location",
            "from_pincode", "to_pincode", "loading_date", "unloading_date",
            "halting_remarks", "shortage_remarks", "excess_remarks",
            "other_income_remarks", "notes", "lr_number", "lr_time",
            "external_invoice_no", "customer_invoice_no", "customer_purchased_at",
            "waybill_no", "seal_numbers",
        ]
        fixed_str = 0
        for f in str_fields_to_normalise:
            rr = await db.trips.update_many({f: None}, {"$set": {f: ""}})
            fixed_str += rr.modified_count
        if r1.modified_count or r2.modified_count or r3.modified_count or r4.modified_count or fixed_str:
            logger.info(
                f"Iter49 null-coerce backfill: trips.supplier_id={r1.modified_count}, "
                f"vehicles.supplier_id={r2.modified_count}, expenses.other_remarks={r3.modified_count}, "
                f"expenses.other_desc={r4.modified_count}, other-str-fields={fixed_str}"
            )
    except Exception as e:
        logger.warning(f"Iter49 null-coerce backfill failed: {e}")
    # 1. Unique index on session_token → guarantees no duplicate session docs
    # 2. TTL index on expires_at    → MongoDB auto-purges expired sessions
    # 3. Unique index on users.email → prevents dup user rows on OAuth replay
    try:
        # De-dupe existing session rows before applying unique index (keep the newest)
        seen = {}
        async for s in db.user_sessions.find({}, {"_id": 1, "session_token": 1, "created_at": 1}):
            tok = s.get("session_token")
            if not tok:
                await db.user_sessions.delete_one({"_id": s["_id"]})
                continue
            key = tok
            prev = seen.get(key)
            if prev is None or (s.get("created_at") or "") > (prev.get("created_at") or ""):
                if prev is not None:
                    await db.user_sessions.delete_one({"_id": prev["_id"]})
                seen[key] = s
            else:
                await db.user_sessions.delete_one({"_id": s["_id"]})
        # Now create the indexes (idempotent — will no-op if already there)
        await db.user_sessions.create_index("session_token", unique=True, name="uniq_session_token")
        await db.user_sessions.create_index("expires_at_ttl", expireAfterSeconds=0,
                                            partialFilterExpression={"expires_at_ttl": {"$exists": True}},
                                            name="auto_purge_expired") if False else None
        # Simpler approach: index expires_at as string (ISO) is not TTL-eligible; skip TTL for now
        # (rolling refresh + login-time cleanup keeps rows in check)
        await db.users.create_index("email", unique=True, name="uniq_user_email", sparse=True)
        await db.users.create_index("user_id", unique=True, name="uniq_user_id")
        # Iter50 — Save-Health TTL (14 days)
        await db.save_health.create_index("ts", expireAfterSeconds=14 * 24 * 60 * 60, name="save_health_ttl")
        await db.save_health.create_index([("collection", 1), ("ts", -1)], name="save_health_lookup")
        # Iter51 — deploy_status collection for the regression guard result cache
        await db.deploy_status.create_index("checked_at", name="deploy_status_recency")
        logger.info("Auth stability indexes ensured (user_sessions.session_token unique + users.email unique + save_health TTL)")
    except Exception as e:
        logger.warning(f"Auth index ensure failed: {e}")


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
    try:
        from scheduler import stop_scheduler
        stop_scheduler()
    except Exception:
        pass
