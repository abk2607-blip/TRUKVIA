"""Bitumen Transport Accounting — Backend API.

Modular FastAPI service. Domain logic lives in dedicated modules
(models / auth / company / services) and endpoints under `routers/`.
This file only wires the application together.
"""
import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, APIRouter, Depends
from starlette.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from db import client, db
from auth import get_current_user
from storage_client import init_storage, APP_NAME
from idempotency import idempotency_middleware, ensure_indexes as ensure_idempotency_indexes
from routers.dedup_admin import router as dedup_admin_router, ensure_dedup_indexes_and_backfill
from routers.diagnostics import router as diagnostics_router  # Iter127b-UAT-fix v2 (temporary)

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
    saved_filters as saved_filters_r,
    driver_shortage_policies as driver_shortage_policies_r,
    driver_ledger as driver_ledger_r,
    policy_changes as policy_changes_r,
    # Iter133 · Expense / Vehicle Cost — Turn 1 foundation
    vendors as vendors_r,
    mechanics as mechanics_r,
    repair_events as repair_events_r,
    vendor_bills as vendor_bills_r,
    mechanic_work_orders as mechanic_work_orders_r,
    expenses as expenses_r,
    # Iter133 · Turn 2B — Vehicle Cost + Repair History read-only reports
    vehicle_reports as vehicle_reports_r,
    # Iter133 · Turn 2C — Vendor + Mechanic Ledgers + Payment Corrections
    vendor_ledger as vendor_ledger_r,
    mechanic_ledger as mechanic_ledger_r,
    # Iter133 · Turn 2D — Cost-date / Payment-date / Supplier projection
    expense_date_reports as expense_date_reports_r,
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

# Iter129-sec · CORS is now restricted to origins listed in CORS_ORIGINS
# (backend/.env). If the variable is absent or empty we fall back to "*" so
# preview URLs remain reachable during rollout. Cookies stay disabled
# (allow_credentials=False) — the frontend authenticates via Bearer.
_cors_env = os.environ.get("CORS_ORIGINS", "").strip()
_cors_origins = [o.strip() for o in _cors_env.split(",") if o.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_credentials=False,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

# Iter129-sec · Standard security response headers on every route. CSP is
# intentionally relaxed so Tailwind inline styles, data: images, https:
# fonts, and the AI-chat WebSocket keep working. Can be tightened later.
_SEC_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Permissions-Policy": "camera=(), microphone=(self), geolocation=()",
    "Content-Security-Policy": (
        "default-src 'self' https:; "
        "img-src 'self' data: https:; "
        "style-src 'self' 'unsafe-inline' https:; "
        "script-src 'self' 'unsafe-inline' https:; "
        "connect-src 'self' https: wss:; "
        "font-src 'self' data: https:; "
        "frame-ancestors 'none'"
    ),
}


@app.middleware("http")
async def _add_security_headers(request, call_next):
    resp = await call_next(request)
    for k, v in _SEC_HEADERS.items():
        resp.headers.setdefault(k, v)
    return resp

# Mount all sub-routers. Each router has prefix="/api" so paths are already fully qualified.
for r in (
    auth_r, companies_r, customers_r, drivers_r, products_r,
    vehicles_r, parties_r, trips_r, invoices_r, dashboard_r,
    reports_r, gst_r, files_r, team_r, audit_r,
    templates_r, ai_r, expenditure_types_r, suppliers_r,
    saved_filters_r, driver_shortage_policies_r,
    driver_ledger_r, policy_changes_r,
    # Iter133 · Expense / Vehicle Cost — Turn 1 + Turn 2B + Turn 2C
    vendors_r, mechanics_r, repair_events_r,
    vendor_bills_r, mechanic_work_orders_r, expenses_r,
    vehicle_reports_r,
    vendor_ledger_r, mechanic_ledger_r,
    expense_date_reports_r,
):
    app.include_router(r.router)

# Iter132a · Credit Note router (feature-flagged internally by ENABLE_CDN).
try:
    from routers.notes import router as notes_r
    app.include_router(notes_r)
except Exception as _e:
    import logging as _log
    _log.getLogger(__name__).warning(f"Iter132a notes router not mounted: {_e}")

# Iter127a — Duplicate-master admin listing (read-only).
app.include_router(dedup_admin_router)

# Iter127b-UAT-fix v2 — TEMPORARY diagnostic instrumentation (silent-restart probes).
# Documented in /app/backend/routers/diagnostics.py. Slated for one-commit removal.
app.include_router(diagnostics_router)


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
async def _idempotency_middleware(request: _FReq, call_next):
    # Iter126b — Bucket-B replay protection. Added AFTER save_health so it
    # wraps as the outer middleware: request flows Idempotency → SaveHealth →
    # route; response flows route → SaveHealth → Idempotency. Replays skip
    # the route (no duplicate mutation) but the Idempotency layer returns
    # the ORIGINAL status/body so save_health metrics stay accurate for the
    # ORIGINAL request (already logged the first time).
    return await idempotency_middleware(request, call_next)


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
            # Iter57 — Capture source IP for auth-failure drill-down. Prefer
            # X-Forwarded-For (populated by the Kubernetes ingress) then fall
            # back to the direct client host. NEVER store request headers,
            # tokens or payloads — keep this row PII-safe.
            xff = request.headers.get("x-forwarded-for") or ""
            ip = xff.split(",")[0].strip() if xff else (request.client.host if request.client else "")
            # Iter121 — Exclude loopback (127.0.0.1 / ::1) from Save Health
            # accounting. The on-pod pytest regression suite and the hourly
            # deploy-guard hit /api/auth/me and negative-path POSTs from
            # localhost; those are test telemetry, not real business
            # failures. External (ingress-forwarded) traffic still flows
            # through untouched — XFF-carried public IPs are recorded as
            # before. Applied to NEW events only; historical rows preserved.
            if ip in ("127.0.0.1", "::1", "localhost"):
                return response
            await db.save_health.insert_one({
                "ts": _dt.now(_tz.utc),
                "ts_iso": _dt.now(_tz.utc).isoformat(),
                "collection": _extract_collection(path),
                "method": method,
                "path": path,
                "status": status,
                "latency_ms": round((_time.perf_counter() - t0) * 1000, 1),
                "kind": "auth_failure" if is_auth_failure else "save_failure",
                "ip": ip,
            })
            # Iter51 — Evaluate alerting rules (fire-and-forget)
            _asyncio.create_task(_evaluate_save_health_alerts())
            _asyncio.create_task(_evaluate_auth_ip_burst_alerts())
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


@app.get("/api/admin/save-health/auth-failures")
async def save_health_auth_failures(
    hours: int = 24,
    limit: int = 100,
    since: str = "",
    until: str = "",
):
    """Iter57 P2 — Drill-down for recent authentication failures on /api/auth/*.

    Returns the most recent N rows (default 100, max 500) captured within the
    time window (default 24h, max 168h). Each row is PII-safe: it only exposes
    timestamp, HTTP method, path, status code, latency and source IP. Never
    exposes Authorization headers, tokens, cookies or request payloads.

    Iter58 P3 — When `since` and/or `until` (ISO 8601) are provided, the
    window is narrowed to that exact slice. This backs the "click a bucket
    on the sparkline" deep-dive.
    """
    hours = max(1, min(int(hours or 24), 168))
    limit = max(1, min(int(limit or 100), 500))
    cutoff = _dt.now(_tz.utc) - _td(hours=hours)
    ts_filter = {"$gte": cutoff}
    # Optional narrow window from the sparkline deep-dive
    if since:
        try:
            since_dt = _dt.fromisoformat(since.replace("Z", "+00:00"))
            ts_filter["$gte"] = since_dt
        except Exception:
            pass
    if until:
        try:
            until_dt = _dt.fromisoformat(until.replace("Z", "+00:00"))
            ts_filter["$lte"] = until_dt
        except Exception:
            pass
    docs = await db.save_health.find(
        {"kind": "auth_failure", "ts": ts_filter},
        {"_id": 0, "ts": 0},  # Drop raw datetime; ts_iso is human-readable.
    ).sort("ts", -1).limit(limit).to_list(limit)
    # Group by IP for a quick "top offenders" summary — useful for spotting bots.
    ip_counts: dict = {}
    for d in docs:
        ip = (d.get("ip") or "").strip() or "unknown"
        ip_counts[ip] = ip_counts.get(ip, 0) + 1
    top_ips = sorted(
        [{"ip": k, "count": v} for k, v in ip_counts.items()],
        key=lambda x: x["count"], reverse=True,
    )[:10]
    return {
        "window_hours": hours,
        "count": len(docs),
        "top_ips": top_ips,
        "items": docs,
        "generated_at": _dt.now(_tz.utc).isoformat(),
    }


@app.get("/api/admin/save-health/sparkline")
async def save_health_sparkline(hours: int = 24, buckets: int = 24):
    """Iter57 P3 — Time-bucketed failure counts for the dashboard sparkline.

    Returns `buckets` evenly-spaced counts across the last `hours` window,
    split by kind (auth_failure vs save_failure). Default 24 buckets over 24h.
    """
    hours = max(1, min(int(hours or 24), 168))
    buckets = max(4, min(int(buckets or 24), 96))
    now = _dt.now(_tz.utc)
    cutoff = now - _td(hours=hours)
    bucket_seconds = (hours * 3600) / buckets
    pipeline = [
        {"$match": {"ts": {"$gte": cutoff}}},
        {"$project": {
            "kind": 1,
            "bucket": {"$floor": {
                "$divide": [
                    {"$subtract": ["$ts", cutoff]},
                    bucket_seconds * 1000,
                ]
            }},
        }},
        {"$group": {"_id": {"bucket": "$bucket", "kind": "$kind"},
                    "count": {"$sum": 1}}},
    ]
    rows = await db.save_health.aggregate(pipeline).to_list(1000)
    auth = [0] * buckets
    save = [0] * buckets
    for r in rows:
        b = int(r["_id"].get("bucket") or 0)
        if not (0 <= b < buckets):
            continue
        if r["_id"].get("kind") == "auth_failure":
            auth[b] += r["count"]
        else:
            save[b] += r["count"]
    return {
        "window_hours": hours,
        "buckets": buckets,
        "bucket_minutes": round((hours * 60) / buckets, 1),
        "auth": auth,
        "save": save,
        "cutoff": cutoff.isoformat(),
        "generated_at": now.isoformat(),
    }



# ---------------------------------------------------------------------------
# Iter51 — Deployment Regression Guard
# ---------------------------------------------------------------------------
import asyncio as _asyncio
import subprocess as _subprocess

# Iter116 · Single-flight lock so the hourly background tick and any
# on-demand `_once` trigger cannot spawn parallel pytest instances that
# trample each other's output (previous root cause of the recurring
# 503 "regression suite timed out" chip).
_regression_lock = _asyncio.Lock()


async def _run_regression_background():
    """Runs the pytest regression suite in a subprocess and stores the result
    in `db.deploy_status`. Executes ~30s after backend startup + then hourly.

    Iter116 · Serialised via _regression_lock so only ONE regression run can
    be in flight at any time — earlier the on-demand endpoint could race
    with the hourly background tick, spawning two parallel pytest instances
    that trampled each other's output and marked the guard as timed-out."""
    await _asyncio.sleep(30)
    while True:
        async with _regression_lock:
            started = _dt.now(_tz.utc)
            try:
                env = {**os.environ, "PATH": "/root/.venv/bin:" + os.environ.get("PATH", "/usr/bin:/bin")}
                proc = await _asyncio.create_subprocess_exec(
                    "bash", "/app/backend/scripts/run_regression.sh",
                    stdout=_asyncio.subprocess.PIPE, stderr=_asyncio.subprocess.STDOUT,
                    cwd="/app/backend", env=env,
                )
                try:
                    stdout, _ = await _asyncio.wait_for(proc.communicate(), timeout=1500)
                    rc = proc.returncode
                    out = (stdout or b"").decode(errors="replace")[-4000:]
                except _asyncio.TimeoutError:
                    proc.kill()
                    rc, out = 124, "regression suite timed out (>1500s)"
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
                    }, "$inc": {
                        # Iter88 — Track consecutive failures so strict-mode 503 only trips
                        # after two back-to-back fails (flaky tests self-heal on retry).
                        "consecutive_failures": 1 if rc != 0 else 0,
                    }} if rc != 0 else {"$set": {
                        "status": "pass",
                        "exit_code": rc,
                        "elapsed_s": round(elapsed, 1),
                        "output_tail": out[-2000:],
                        "checked_at": _dt.now(_tz.utc).isoformat(),
                        "next_check_at": (_dt.now(_tz.utc) + _td(hours=1)).isoformat(),
                        "consecutive_failures": 0,
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
    # Periodic regression runs disabled - the hourly full-suite run was
    # colliding with live UAT and gating /auth/health. Set
    # REGRESSION_GUARD_PERIODIC=1 to re-enable.
    if os.environ.get("REGRESSION_GUARD_PERIODIC", "0") == "1":
        _asyncio.create_task(_run_regression_background())
    else:
        logger.info("Periodic regression guard disabled "
                    "(set REGRESSION_GUARD_PERIODIC=1 to re-enable)")


# Iter128 — Deploy-Readiness Badge role-gate. Owner / Admin / Manager only.
# Matches the visibility scope approved for the top-nav badge and prevents
# lower-role users from probing the regression-guard endpoints. Return 403
# with a stable, plain-English message so the frontend can map it cleanly.
_DEPLOY_ROLES = ("owner", "admin", "manager")


def _require_deploy_role(user: dict) -> None:
    if (user.get("effective_role") or "").lower() not in _DEPLOY_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Owner, Admin, or Manager role required.",
        )


@app.get("/api/admin/deploy-readiness")
async def deploy_readiness(user=Depends(get_current_user)):
    """Iter51 — Latest cached regression-guard result. Deploy pipelines call
    this to check readiness. Returns 200 with status=pass or fail. Never 5xx.
    Iter128 — Role-gated to Owner / Admin / Manager (403 otherwise)."""
    _require_deploy_role(user)
    doc = await db.deploy_status.find_one({"_id": "current"}, {"_id": 0})
    if not doc:
        return {
            "status": "unknown",
            "message": "Regression guard has not yet completed its first run (starts ~30s after backend boot).",
            "checked_at": None,
        }
    return doc


@app.get("/api/admin/deploy-history")
async def deploy_history(limit: int = 30, user=Depends(get_current_user)):
    """Iter52 — Guard History: returns the last N regression runs with their
    pass/fail status and (if failed) the list of broken test files. Drives
    the sparkline / bar-chart on the Dashboard's Deploy Guard tile.
    Iter128 — Role-gated to Owner / Admin / Manager (403 otherwise)."""
    _require_deploy_role(user)
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
    to force a fresh check before promoting a build.

    Iter131 · Scheduler cascade fix — Short-circuit when a regression is
    already in flight. Previously the endpoint scheduled an `_asyncio.create_task`
    unconditionally, so any nested call (including the deploy-guard test suite
    itself, which POSTs /run-now inside test_iter51 and test_iter128) queued
    behind the current run's lock and fired the instant it released — creating
    a self-perpetuating ~11-min cascade. We now consult `_regression_lock.locked()`
    first and return `{triggered: False, reason: "already_running"}` instead of
    schedulng a redundant task."""
    if _regression_lock.locked():
        return {
            "triggered": False,
            "reason": "already_running",
            "message": "A regression run is already in flight; poll /api/admin/deploy-readiness for its result.",
        }
    # Fire-and-forget — the watcher's next hourly tick will refresh anyway,
    # but we schedule an immediate run.
    async def _once():
        # Iter116 · Reuse the single-flight lock so on-demand and hourly
        # background runs cannot spawn parallel pytest instances.
        async with _regression_lock:
            started_at = _dt.now(_tz.utc)
            try:
                env = {**os.environ, "PATH": "/root/.venv/bin:" + os.environ.get("PATH", "/usr/bin:/bin")}
                proc = await _asyncio.create_subprocess_exec(
                    "bash", "/app/backend/scripts/run_regression.sh",
                    stdout=_asyncio.subprocess.PIPE, stderr=_asyncio.subprocess.STDOUT,
                    cwd="/app/backend", env=env,
                )
                stdout, _ = await _asyncio.wait_for(proc.communicate(), timeout=1500)
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
                        # Iter131 · Also refresh next_check_at from the on-demand
                        # path so the field never drifts stale when only /run-now
                        # is in use (previously only the periodic loop wrote it).
                        "next_check_at": (_dt.now(_tz.utc) + _td(hours=1)).isoformat(),
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
    "auth_ip_burst": True,  # Iter58 P2 — per-IP auth-failure burst detector
}
# Iter58 P2 — Any single IP crossing this many auth failures inside the
# alert window fires a dedicated alert. Tunable but not user-editable for
# now to keep the settings UI simple.
AUTH_IP_BURST_THRESHOLD = 20


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


async def _evaluate_auth_ip_burst_alerts():
    """Iter58 P2 — Detect when a SINGLE source IP crosses the auth-failure
    burst threshold within the last hour, and fire an alert. This runs
    independently of `_evaluate_save_health_alerts` so it fires even when
    the aggregate threshold hasn't been crossed.

    PII safety: The alert body contains ONLY the IP, count, first/last
    seen timestamps, and up to 3 sample paths. Passwords, tokens,
    Authorization headers and cookies are NEVER stored or exposed.
    """
    try:
        cfg = await db.alert_config.find_one({"_id": "save_health"}, {"_id": 0}) or {}
        if not cfg.get("enabled", True):
            return None
        at = {**DEFAULT_ALERT_TYPES, **(cfg.get("alert_types") or {})}
        if not at.get("auth_ip_burst", True):
            return None
        cutoff = _dt.now(_tz.utc) - _td(hours=1)
        pipeline = [
            {"$match": {"kind": "auth_failure", "ts": {"$gte": cutoff},
                        "ip": {"$exists": True, "$ne": ""}}},
            {"$group": {"_id": "$ip",
                        "count": {"$sum": 1},
                        "first_seen": {"$min": "$ts_iso"},
                        "last_seen": {"$max": "$ts_iso"},
                        "sample_paths": {"$addToSet": "$path"}}},
            {"$match": {"count": {"$gte": AUTH_IP_BURST_THRESHOLD}}},
            {"$sort": {"count": -1}},
            {"$limit": 5},
        ]
        offenders = await db.save_health.aggregate(pipeline).to_list(5)
        if not offenders:
            return None
        # Cooldown per IP so we don't spam. 30 minutes between alerts for the same IP.
        cooldown = int(cfg.get("cooldown_min") or DEFAULT_ALERT_COOLDOWN_MIN) * 60
        now = _dt.now(_tz.utc)
        new_alerts = []
        for o in offenders:
            ip = o["_id"] or "unknown"
            last = await db.save_health_alerts.find_one(
                {"kind": "auth_ip_burst", "ip": ip}, sort=[("fired_at", -1)]
            )
            if last:
                try:
                    from datetime import datetime as _dt2
                    dt = _dt2.fromisoformat(last.get("fired_at", ""))
                    if (now - dt).total_seconds() < cooldown:
                        continue
                except Exception:
                    pass
            alert = {
                "kind": "auth_ip_burst",
                "fired_at": now.isoformat(),
                "ip": ip,
                "count": int(o["count"]),
                "threshold": AUTH_IP_BURST_THRESHOLD,
                "window_minutes": 60,
                "first_seen": o.get("first_seen"),
                "last_seen": o.get("last_seen"),
                # Sample paths (max 3) — no query strings, no headers, no tokens.
                "sample_paths": sorted(list(o.get("sample_paths") or []))[:3],
                "acknowledged": False,
            }
            await db.save_health_alerts.insert_one(alert)
            new_alerts.append(alert)
            logger.warning(
                f"⚠ Auth IP Burst Alert: {ip} produced {o['count']} auth failures in last 60 min "
                f"(threshold={AUTH_IP_BURST_THRESHOLD})"
            )
            # Optional email dispatch — reuse existing channel config
            try:
                channels = cfg.get("channels", ["email"])
                recipients = cfg.get("email_recipients", []) or []
                if "email" in channels and recipients:
                    from services_alerts import send_alert_email
                    subject = f"[Bitumen Transport] Auth Burst · IP {ip} · {o['count']} failures / 60 min"
                    body = (
                        f"<h3>Auth-Failure Burst Detected</h3>"
                        f"<p><b>Source IP:</b> <code>{ip}</code></p>"
                        f"<p><b>Failures in last 60 min:</b> {o['count']} "
                        f"(threshold {AUTH_IP_BURST_THRESHOLD})</p>"
                        f"<p><b>First seen:</b> {o.get('first_seen','')} "
                        f"· <b>Last seen:</b> {o.get('last_seen','')}</p>"
                        f"<p><b>Sample paths:</b> "
                        f"{', '.join(sorted(list(o.get('sample_paths') or []))[:3])}</p>"
                        f"<hr><p style='font-size:11px;color:#666'>"
                        "This alert is generated from server access logs. No passwords, tokens, "
                        "Authorization headers, cookies or request payloads are captured or included.</p>"
                    )
                    res = await send_alert_email(recipients, subject, body)
                    await db.save_health_alerts.update_one(
                        {"fired_at": alert["fired_at"], "ip": ip},
                        {"$set": {"email_delivery": res}},
                    )
            except Exception as e:
                logger.warning(f"Auth-IP-Burst email dispatch failed: {e}")
        return new_alerts
    except Exception as e:
        logger.warning(f"Auth-IP-Burst evaluation failed: {e}")
        return None


# Piggy-back on the same middleware to evaluate alerts after every logged failure.
# We store this on the app state so the middleware can call it.
async def _post_failure_hook():
    await _evaluate_save_health_alerts()
    await _evaluate_auth_ip_burst_alerts()


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


# Iter127b-UAT-fix v3 — Post-startup migration guard.
# A single asyncio.Lock ensures the background migration bundle never runs
# concurrently (e.g. if the worker reloads while a prior run is still
# executing). If the lock is already held, the second attempt exits fast.
_background_migrations_lock = None
_background_migrations_ran = False


async def _run_background_migrations():
    """Iter127b-UAT-fix v3 · Bundle of NON-CRITICAL startup work that used to
    block `/api/auth/health` for 15-30 s after every Preview pod restart.
    Now scheduled after `Application startup complete` so the health endpoint
    is reachable in ~2 s. Business logic and ordering are preserved
    verbatim — nothing here changes what the migrations do, only WHEN.

    Concurrency-safe: guarded by `_background_migrations_lock`. If the task
    is already in flight (rare — only possible if uvicorn was hot-reloaded
    while a previous run hadn't finished), the second invocation returns
    without touching anything. Never raises."""
    global _background_migrations_ran
    import asyncio as _asyncio
    global _background_migrations_lock
    if _background_migrations_lock is None:
        _background_migrations_lock = _asyncio.Lock()
    if _background_migrations_lock.locked():
        logger.info("Background migrations already running — skipping duplicate schedule.")
        return
    async with _background_migrations_lock:
        # ── Iter127a · Backfill *_norm + partial unique indexes on masters ──
        try:
            await ensure_dedup_indexes_and_backfill()
        except Exception as e:
            logger.warning(f"Iter127a dedup backfill failed (background): {e}")

        # ── Iter49 · Null-coerce backfill so the Pydantic v2 contract
        # never rejects a legacy row on PUT. Runs in the background because
        # `update_many` across trips/vehicles is the biggest single item
        # in the startup path (5-15 s on a hot demo tenant). ──
        try:
            r1 = await db.trips.update_many({"supplier_id": None}, {"$set": {"supplier_id": ""}})
            r2 = await db.vehicles.update_many({"supplier_id": None}, {"$set": {"supplier_id": ""}})
            r3 = await db.trips.update_many({"expenses.other_remarks": None}, {"$set": {"expenses.other_remarks": ""}})
            r4 = await db.trips.update_many({"expenses.other_desc": None}, {"$set": {"expenses.other_desc": ""}})
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
                    f"Iter49 null-coerce backfill (background): trips.supplier_id={r1.modified_count}, "
                    f"vehicles.supplier_id={r2.modified_count}, expenses.other_remarks={r3.modified_count}, "
                    f"expenses.other_desc={r4.modified_count}, other-str-fields={fixed_str}"
                )
        except Exception as e:
            logger.warning(f"Iter49 null-coerce backfill failed (background): {e}")

        # ── Auth-index housekeeping (session_token unique + expires_at TTL
        # + users.email unique + save_health TTL + deploy_status recency).
        # The de-dupe loop iterating ALL user_sessions is the slow part,
        # so we defer the whole block. create_index is idempotent — a
        # subsequent runtime insert without the unique index still works
        # (dedup is only about preventing rare race duplicates). ──
        try:
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
            await db.user_sessions.create_index("session_token", unique=True, name="uniq_session_token")
            try:
                await db.user_sessions.create_index("expires_at", expireAfterSeconds=0,
                                                    name="user_sessions_ttl")
            except Exception as _ttl_e:
                logger.warning(f"user_sessions TTL index setup issue: {_ttl_e}")
            await db.users.create_index("email", unique=True, name="uniq_user_email", sparse=True)
            await db.users.create_index("user_id", unique=True, name="uniq_user_id")
            await db.save_health.create_index("ts", expireAfterSeconds=14 * 24 * 60 * 60, name="save_health_ttl")
            await db.save_health.create_index([("collection", 1), ("ts", -1)], name="save_health_lookup")
            await db.deploy_status.create_index("checked_at", name="deploy_status_recency")
            logger.info("Auth stability indexes ensured (background)")
        except Exception as e:
            logger.warning(f"Auth index ensure failed (background): {e}")

        # ── Iter70/72 · Purge orphaned pytest fixture rows ──
        try:
            from routers.customers import FIXTURE_NAME_REGEX
            uid = "user_demo_men_2026"
            candidates = []
            async for c in db.customers.find(
                {"user_id": uid, "name": {"$regex": FIXTURE_NAME_REGEX}},
                {"_id": 0, "id": 1},
            ):
                candidates.append(c["id"])
            if candidates:
                trip_attached = set()
                async for t in db.trips.find({"user_id": uid, "customer_id": {"$in": candidates}}, {"_id": 0, "customer_id": 1}):
                    trip_attached.add(t["customer_id"])
                inv_attached = set()
                async for i in db.invoices.find({"user_id": uid, "customer_id": {"$in": candidates}}, {"_id": 0, "customer_id": 1}):
                    inv_attached.add(i["customer_id"])
                safe = [c for c in candidates if c not in trip_attached and c not in inv_attached]
                if safe:
                    r = await db.customers.delete_many({"user_id": uid, "id": {"$in": safe}})
                    if r.deleted_count:
                        logger.info(f"Iter70 fixture-purge (background): removed {r.deleted_count} orphan fixture customers")

            SUP_REGEX = r"^(IT\d+|TEST[_-]|AAA_|UI\d+|IsoCoB|Iso_|BULK_|Bulk_|Sup_[a-f0-9]{6}|IT72)"
            sup_ids = []
            async for s in db.suppliers.find(
                {"user_id": uid, "name": {"$regex": SUP_REGEX}},
                {"_id": 0, "id": 1},
            ):
                sup_ids.append(s["id"])
            if sup_ids:
                sup_on_veh = set()
                async for v in db.vehicles.find({"user_id": uid, "supplier_id": {"$in": sup_ids}}, {"_id": 0, "supplier_id": 1}):
                    if v.get("supplier_id"):
                        sup_on_veh.add(v["supplier_id"])
                sup_on_trip = set()
                async for t in db.trips.find({"user_id": uid, "supplier_id": {"$in": sup_ids}}, {"_id": 0, "supplier_id": 1}):
                    if t.get("supplier_id"):
                        sup_on_trip.add(t["supplier_id"])
                safe_sup = [x for x in sup_ids if x not in sup_on_veh and x not in sup_on_trip]
                if safe_sup:
                    r = await db.suppliers.delete_many({"user_id": uid, "id": {"$in": safe_sup}})
                    if r.deleted_count:
                        logger.info(f"Iter72 fixture-purge (background): removed {r.deleted_count} orphan fixture suppliers")

            VEH_REGEX = r"^(AA\d|AP16UI|AP16US|IT\d+_?VEH|IT72|UI\d+|AAA_)"
            veh_ids = []
            async for v in db.vehicles.find(
                {"user_id": uid, "vehicle_number": {"$regex": VEH_REGEX}},
                {"_id": 0, "id": 1},
            ):
                veh_ids.append(v["id"])
            if veh_ids:
                veh_on_trip = set()
                async for t in db.trips.find({"user_id": uid, "vehicle_id": {"$in": veh_ids}}, {"_id": 0, "vehicle_id": 1}):
                    if t.get("vehicle_id"):
                        veh_on_trip.add(t["vehicle_id"])
                safe_veh = [x for x in veh_ids if x not in veh_on_trip]
                if safe_veh:
                    r = await db.vehicles.delete_many({"user_id": uid, "id": {"$in": safe_veh}})
                    if r.deleted_count:
                        logger.info(f"Iter72 fixture-purge (background): removed {r.deleted_count} orphan fixture vehicles")
        except Exception as e:
            logger.warning(f"Iter70/72 fixture-purge failed (background): {e}")

        _background_migrations_ran = True
        logger.info("Iter127b-UAT-fix v3 · Background migrations complete.")


@app.on_event("startup")
async def startup_event():
    # Iter130 · Defense-in-depth demo-token rotation.
    # After the one-shot Mongo purge of the legacy demo-session row, this
    # startup hook also deletes any user_sessions document whose token is
    # the pre-rotation literal. Guards against re-seeding (e.g. a rogue
    # migration or a restored backup smuggling the old row back in).
    try:
        LEGACY = "test_session_" + "bitumen_2026"
        result = await db.user_sessions.delete_many({"session_token": LEGACY})
        if result.deleted_count:
            logger.warning(
                f"Iter130 · purged {result.deleted_count} legacy demo-session row(s)"
            )
    except Exception as e:
        logger.warning(f"Iter130 legacy-session cleanup failed: {e}")

    # Iter132a · Backfill CN/DN fields on existing companies (idempotent) +
    # create indexes for credit_debit_notes.
    try:
        r = await db.companies.update_many(
            {"credit_note_prefix": {"$exists": False}},
            {"$set": {
                "credit_note_prefix": "CN",
                "next_credit_note_number": 1,
                "debit_note_prefix": "DN",
                "next_debit_note_number": 1,
                "require_cdn_approval": False,
            }},
        )
        if r.modified_count:
            logger.info(f"Iter132a · backfilled CN/DN fields on {r.modified_count} company docs")
        await db.credit_debit_notes.create_index([("user_id", 1), ("company_id", 1), ("note_date", -1)])
        await db.credit_debit_notes.create_index([("invoice_id", 1), ("status", 1)])
        await db.credit_debit_notes.create_index(
            [("user_id", 1), ("company_id", 1), ("kind", 1), ("note_number", 1)],
            partialFilterExpression={"note_number": {"$type": "string", "$gt": ""}},
        )
        # Iter134 · Unique invoice number per tenant (defends against manual
        # override collisions and any theoretical FY-scoped counter race).
        try:
            await db.invoices.create_index(
                [("user_id", 1), ("invoice_number", 1)],
                unique=True, name="uniq_user_invoice_number",
                partialFilterExpression={"invoice_number": {"$type": "string", "$gt": ""}},
            )
        except Exception as _e_idx:
            logger.warning(f"Iter134 invoice unique index skipped: {_e_idx}")
    except Exception as e:
        logger.warning(f"Iter132a startup backfill failed: {e}")

    # Iter133 · Expense / Vehicle Cost — Turn 1 indexes.
    # Fast lookup for the derived-view projections that follow in later turns
    # (Vehicle Cost / Trip Cost / Vendor & Mechanic Ledgers). All idempotent.
    try:
        # Party masters
        await db.vendors.create_index([("user_id", 1), ("company_id", 1), ("name", 1)],
                                      name="vendors_scope_name")
        await db.mechanics.create_index([("user_id", 1), ("company_id", 1), ("name", 1)],
                                        name="mechanics_scope_name")
        # RepairEvent
        await db.repair_events.create_index([("user_id", 1), ("company_id", 1), ("event_date", -1)],
                                            name="repair_events_scope_date")
        await db.repair_events.create_index([("vehicle_id", 1)], name="repair_events_vehicle")
        await db.repair_events.create_index([("trip_id", 1)], name="repair_events_trip")
        # VendorBill
        await db.vendor_bills.create_index([("user_id", 1), ("company_id", 1), ("bill_date", -1)],
                                           name="vendor_bills_scope_date")
        await db.vendor_bills.create_index([("vendor_id", 1)], name="vendor_bills_vendor")
        await db.vendor_bills.create_index([("repair_event_id", 1)], name="vendor_bills_repair")
        await db.vendor_bills.create_index([("vehicle_id", 1)], name="vendor_bills_vehicle")
        # MechanicWorkOrder
        await db.mechanic_work_orders.create_index([("user_id", 1), ("company_id", 1), ("work_date", -1)],
                                                   name="mwo_scope_date")
        await db.mechanic_work_orders.create_index([("mechanic_id", 1)], name="mwo_mechanic")
        await db.mechanic_work_orders.create_index([("repair_event_id", 1)], name="mwo_repair")
        await db.mechanic_work_orders.create_index([("vehicle_id", 1)], name="mwo_vehicle")
        # Expense — the canonical cost collection; multiple projection indexes.
        await db.expenses.create_index([("user_id", 1), ("company_id", 1), ("date", -1)],
                                       name="expenses_scope_date")
        await db.expenses.create_index([("trip_id", 1)], name="expenses_trip")
        await db.expenses.create_index([("vehicle_id", 1)], name="expenses_vehicle")
        await db.expenses.create_index([("repair_event_id", 1)], name="expenses_repair")
        await db.expenses.create_index([("vendor_bill_id", 1)], name="expenses_vendor_bill")
        await db.expenses.create_index([("mechanic_work_order_id", 1)], name="expenses_mwo")
        await db.expenses.create_index([("party_type", 1), ("party_id", 1)], name="expenses_party")
        await db.expenses.create_index([("category", 1)], name="expenses_category")
        # Iter133 · Turn 2A — deterministic source-line identity.
        # Partial UNIQUE index so a source_key can never map to two Expense
        # rows in the same tenant. Blank source_keys (manual entries) are
        # excluded via partialFilterExpression.
        await db.expenses.create_index(
            [("user_id", 1), ("company_id", 1), ("source_key", 1)],
            name="expenses_source_key_uniq",
            unique=True,
            partialFilterExpression={"source_key": {"$type": "string", "$gt": ""}},
        )
        await db.expenses.create_index([("source_trip_id", 1)], name="expenses_source_trip")
        # Payments
        await db.vendor_payments.create_index([("user_id", 1), ("company_id", 1), ("date", -1)],
                                              name="vendor_payments_scope_date")
        await db.vendor_payments.create_index([("vendor_id", 1)], name="vendor_payments_vendor")
        await db.vendor_payments.create_index([("vendor_bill_id", 1)], name="vendor_payments_bill")
        await db.mechanic_payments.create_index([("user_id", 1), ("company_id", 1), ("date", -1)],
                                                name="mechanic_payments_scope_date")
        await db.mechanic_payments.create_index([("mechanic_id", 1)], name="mechanic_payments_mechanic")
        await db.mechanic_payments.create_index([("mechanic_work_order_id", 1)], name="mechanic_payments_mwo")
        # Iter133 · Turn 2C — payment corrections + reversal support
        await db.payment_corrections.create_index(
            [("user_id", 1), ("company_id", 1), ("payment_type", 1),
             ("payment_id", 1), ("correction_index", 1)],
            name="pcr_scope_payment_index",
        )
        await db.vendor_payments.create_index([("is_reversed", 1)], name="vp_reversed")
        await db.vendor_payments.create_index([("reversal_of", 1)], name="vp_reversal_of")
        await db.mechanic_payments.create_index([("is_reversed", 1)], name="mp_reversed")
        await db.mechanic_payments.create_index([("reversal_of", 1)], name="mp_reversal_of")
        logger.info("Iter133 · Expense/Vehicle-Cost indexes ensured")
    except Exception as e:
        logger.warning(f"Iter133 index setup failed: {e}")

    # Iter127b-UAT-fix v3 — ONLY critical, fast startup work runs synchronously
    # here. Heavy migrations/backfills/index-housekeeping have been moved into
    # `_run_background_migrations()` scheduled below.
    #
    # Iter126a — init_storage() is a synchronous function; run in executor so
    # boot is non-blocking.
    try:
        import asyncio as _asyncio
        loop = _asyncio.get_event_loop()
        await loop.run_in_executor(None, init_storage)
        logger.info("Object storage initialized")
    except Exception as e:
        logger.warning(f"Object storage init failed: {e}")
    # Iter126b — 24h TTL index on idempotency_keys.created_at (small, fast).
    try:
        await ensure_idempotency_indexes()
        logger.info("Idempotency TTL index ensured (24h replay window)")
    except Exception as e:
        logger.warning(f"Idempotency index setup failed: {e}")
    try:
        from scheduler import start_scheduler
        start_scheduler()
    except Exception as e:
        logger.warning(f"Scheduler init failed: {e}")

    # Iter127b-UAT-fix v3 — schedule ALL heavy migrations (dedup backfill,
    # Iter49 null-coerce, auth-index housekeeping, Iter70/72 fixture-purge)
    # in a single background task so this handler returns immediately and
    # `Application startup complete` fires within ~2 s. Health endpoint is
    # then reachable long before the frontend toast's 24 s threshold.
    _asyncio.create_task(_run_background_migrations())
    logger.info("Iter127b-UAT-fix v3 · Startup complete; background migrations scheduled.")


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
    try:
        from scheduler import stop_scheduler
        stop_scheduler()
    except Exception:
        pass
