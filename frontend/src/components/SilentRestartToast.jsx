// Iter97 → Iter127b-UAT-fix v3 · Silent Restart Toast + diagnostic beacon +
// graceful startup UX.
//
// The toast itself is unchanged (hardened Feb 2026 / v1 · v2):
//   • 4-fail threshold, 4 s per-probe abort, jittered 6 s poll with backoff
//     ramp 6→8→12→15 s.
// v2 · fire-and-forget beacon + "App update available — reload" nudge.
// v3 · GRACEFUL STARTUP UX (user-approved Option B, Feb 2026):
//   • For the FIRST 10 s after the pill first appears we display
//     "Backend starting…" instead of "REFRESHING…". Cosmetic only. After the
//     10 s grace window elapses (persistent outage), we fall back to
//     "Refreshing…". Business flows are untouched.
//
// The pill remains a passive visibility indicator — never gates Save
// operations.
import React, { useEffect, useState, useRef, useCallback } from "react";
import { Loader2, RefreshCw } from "lucide-react";

const BASE         = process.env.REACT_APP_BACKEND_URL || "";
const HEALTH_URL   = `${BASE}/api/auth/health`;
const BEACON_URL   = `${BASE}/api/diagnostics/silent-restart-probe`;
const BUILD_URL    = `${BASE}/api/diagnostics/build`;
const BUILD_POLL_MS = 60_000;
const BASELINE_KEY  = "silent_restart_baseline_build_id_v1";

export const FAIL_THRESHOLD  = 4;
// Iter127b-UAT-fix v4 (Feb 2026) · PROBE_TIMEOUT raised 4000 → 6000 ms to
// remove false-positive aborts observed during backend load / cold-start
// windows (see beacon evidence: 9 back-to-back 4003-4130 ms aborts on 06:40:24
// UTC when the server itself was slow but reachable — a 6 s ceiling would
// have surfaced the recovering 3 145 ms response as OK instead of aborting).
export const PROBE_TIMEOUT   = 6000;
export const POLL_BASE       = 6000;
export const POLL_BACKOFF_MS = [6000, 8000, 12000, 15000];
// Iter127b-UAT-fix v3 · length of the "Backend starting…" grace window
// (measured from the moment the pill first appears).
export const STARTUP_GRACE_MS = 10_000;
// Iter127b-UAT-fix v4 · after this long of continuous stale-bundle nudge
// visibility we auto-reload. Iter126c drafts + Iter126b Idempotency-Key
// survive the reload via sessionStorage — no data loss, no duplicate Save.
export const BUILD_STALE_AUTORELOAD_MS = 15_000;

export function nextWaitMs(failStreak, jitter = 0) {
  if (failStreak <= 0) return POLL_BASE + jitter;
  const idx = Math.min(failStreak, POLL_BACKOFF_MS.length - 1);
  return POLL_BACKOFF_MS[idx];
}

export async function probeHealth(
  url = HEALTH_URL,
  { fetchImpl = fetch, AbortCtrl = AbortController, timeoutMs = PROBE_TIMEOUT } = {},
) {
  const ctrl = new AbortCtrl();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  const started = (typeof performance !== "undefined" ? performance.now() : Date.now());
  try {
    const r = await fetchImpl(url, { cache: "no-store", signal: ctrl.signal });
    const durationMs = Math.round(
      (typeof performance !== "undefined" ? performance.now() : Date.now()) - started
    );
    return { ok: r && r.ok === true, status: r ? r.status : null, error: null, durationMs };
  } catch (e) {
    const durationMs = Math.round(
      (typeof performance !== "undefined" ? performance.now() : Date.now()) - started
    );
    const isAbort = e && (e.name === "AbortError" || e.message === "aborted");
    return { ok: false, status: null, error: isAbort ? "abort" : "network", durationMs };
  } finally {
    clearTimeout(t);
  }
}

export function nextState(prevStreak, wasOk) {
  if (wasOk) return { failStreak: 0, restarting: false };
  const failStreak = prevStreak + 1;
  return { failStreak, restarting: failStreak >= FAIL_THRESHOLD };
}

/** Iter127b-UAT-fix v3 · Given the moment the pill first appeared and the
 *  current time, return the label the pill should show. Within the grace
 *  window → "Backend starting…"; afterwards → "Refreshing…". Never blocks. */
export function pillLabel(restartingSince, now = Date.now(), graceMs = STARTUP_GRACE_MS) {
  if (!restartingSince) return "Refreshing…";
  return (now - restartingSince) < graceMs ? "Backend starting…" : "Refreshing…";
}

// -------------------------------------------------------------------- beacon
function _resultLabel(status, error) {
  if (error === "abort") return "abort";
  if (error === "network") return "network";
  if (status && status >= 500) return "http_5xx";
  if (status && status >= 400) return "http_4xx";
  if (status && status >= 200 && status < 300) return "ok";
  return "unknown";
}

function sendBeacon(payload) {
  try {
    // eslint-disable-next-line no-undef
    fetch(BEACON_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      keepalive: true,
      cache: "no-store",
    }).catch(() => {});
  } catch {
    /* swallow */
  }
}

// -------------------------------------------------------------------- component
export default function SilentRestartToast() {
  const [restarting, setRestarting]           = useState(false);
  const [restartingSince, setRestartingSince] = useState(0);
  const [nowTs, setNowTs]                     = useState(0);
  const [updateNudge, setUpdateNudge]         = useState(false);
  const [updateNudgeSince, setUpdateNudgeSince] = useState(0);
  const [clientBuildId, setClientBuildId]     = useState(null);
  const failStreak    = useRef(0);
  const timerId       = useRef(null);
  const buildTimerId  = useRef(null);
  const labelTickId   = useRef(null);

  const emit = useCallback((phase, extra) => {
    let visibility = "visible";
    try { visibility = document.visibilityState || "visible"; } catch {}
    let conn = "unknown";
    try {
      const nc = (navigator.connection || navigator.mozConnection || navigator.webkitConnection);
      if (nc && nc.effectiveType) conn = String(nc.effectiveType);
    } catch {}
    let ua = "unknown";
    try { ua = (navigator.userAgent || "").slice(0, 80); } catch {}
    sendBeacon({
      ts: new Date().toISOString(),
      phase,
      fail_streak: failStreak.current,
      restarting: !!(extra && extra.restarting),
      probe_result: (extra && extra.probeResult) || null,
      http_status: (extra && extra.status) != null ? extra.status : null,
      duration_ms: (extra && extra.durationMs) != null ? extra.durationMs : null,
      page_visibility: visibility,
      connection_type: conn,
      ua_ver: ua,
      client_build_id: clientBuildId,
    });
  }, [clientBuildId]);

  // ── Build-drift check ──
  useEffect(() => {
    let alive = true;
    const checkBuild = async () => {
      try {
        const r = await fetch(BUILD_URL, { cache: "no-store" });
        if (!r.ok) return;
        const j = await r.json();
        const serverBuildId = String(j.build_id ?? "");
        if (!alive) return;

        let baseline = null;
        try { baseline = sessionStorage.getItem(BASELINE_KEY); } catch {}
        if (!baseline) {
          try { sessionStorage.setItem(BASELINE_KEY, serverBuildId); } catch {}
          setClientBuildId(serverBuildId);
          return;
        }
        setClientBuildId(baseline);
        if (serverBuildId && serverBuildId !== baseline) {
          if (!updateNudge) {
            setUpdateNudge(true);
            setUpdateNudgeSince(Date.now());
            sendBeacon({
              ts: new Date().toISOString(),
              phase: "build_stale",
              fail_streak: failStreak.current,
              restarting,
              client_build_id: baseline,
            });
          }
        }
      } catch {
        /* swallow */
      }
    };
    checkBuild();
    buildTimerId.current = setInterval(checkBuild, BUILD_POLL_MS);
    return () => {
      alive = false;
      if (buildTimerId.current) clearInterval(buildTimerId.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Iter127b-UAT-fix v4 · Build-stale auto-reload ──
  // If the amber "App update available" nudge has been visible for
  // BUILD_STALE_AUTORELOAD_MS AND the app can't currently reach a healthy
  // backend probe (restarting=true), reload once. Reload preserves:
  //   • Iter126c form drafts (sessionStorage survives location.reload)
  //   • Iter126b Idempotency-Key (persisted alongside each draft)
  //   • Any in-flight Save's replay contract (idempotency middleware
  //     de-dupes retries on the server side)
  // We deliberately require restarting=true so we never reload a tab that's
  // successfully talking to the server — that path is user-initiated only
  // via clicking the amber pill.
  useEffect(() => {
    if (!updateNudge) return () => {};
    if (!updateNudgeSince) return () => {};
    if (!restarting) return () => {};  // no reload if backend is reachable
    const t = setTimeout(() => {
      sendBeacon({
        ts: new Date().toISOString(),
        phase: "auto_reload_build_stale",
        fail_streak: failStreak.current,
        restarting: true,
        client_build_id: clientBuildId,
      });
      // Iter126c drafts + Iter126b Idempotency-Key survive the reload via
      // sessionStorage. No auto-Save is issued, no duplicate request.
      try { window.location.reload(); } catch {}
    }, BUILD_STALE_AUTORELOAD_MS);
    return () => clearTimeout(t);
  }, [updateNudge, updateNudgeSince, restarting, clientBuildId]);

  // ── Health-probe loop ──
  useEffect(() => {
    let alive = true;

    const tick = async () => {
      const res = await probeHealth(HEALTH_URL);
      if (!alive) return;
      const prevRestarting = failStreak.current >= FAIL_THRESHOLD;
      const s = nextState(failStreak.current, res.ok);
      failStreak.current = s.failStreak;
      setRestarting(s.restarting);

      // v3 · track when the pill first appeared so we can render the grace
      // "Backend starting…" copy for the first STARTUP_GRACE_MS.
      if (s.restarting && !prevRestarting) {
        setRestartingSince(Date.now());
      }
      if (!s.restarting && prevRestarting) {
        setRestartingSince(0);
      }

      const probeResult = _resultLabel(res.status, res.error);
      if (!res.ok) {
        emit("streak_bump", { probeResult, status: res.status, durationMs: res.durationMs, restarting: s.restarting });
      }
      if (s.restarting && !prevRestarting) {
        emit("restart_shown", { probeResult, status: res.status, durationMs: res.durationMs, restarting: true });
      }
      if (!s.restarting && prevRestarting) {
        emit("cleared", { probeResult, status: res.status, durationMs: res.durationMs, restarting: false });
      }
    };

    const schedule = () => {
      if (!alive) return;
      const jitter = Math.floor(Math.random() * 500);
      const wait   = nextWaitMs(failStreak.current, jitter);
      timerId.current = setTimeout(async () => {
        await tick();
        schedule();
      }, wait);
    };

    tick().then(schedule);
    return () => {
      alive = false;
      if (timerId.current) clearTimeout(timerId.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [emit]);

  // ── v3 · label ticker · once per 1 s while the pill is on, so the
  // "Backend starting…" ⇒ "Refreshing…" flip re-renders without waiting
  // for the next 6-15 s probe. Cheap; only runs during outages. ──
  useEffect(() => {
    if (!restarting) {
      if (labelTickId.current) clearInterval(labelTickId.current);
      labelTickId.current = null;
      return () => {};
    }
    setNowTs(Date.now());
    labelTickId.current = setInterval(() => setNowTs(Date.now()), 1000);
    return () => {
      if (labelTickId.current) clearInterval(labelTickId.current);
      labelTickId.current = null;
    };
  }, [restarting]);

  const inStartupGrace = restarting && restartingSince > 0 &&
    (nowTs - restartingSince) < STARTUP_GRACE_MS;
  const label = restarting ? pillLabel(restartingSince, nowTs) : "";

  return (
    <>
      {restarting && (
        <div
          data-testid="silent-restart-toast"
          data-startup-grace={inStartupGrace ? "1" : "0"}
          className={
            "pointer-events-none fixed top-3 right-3 z-[60] inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-[11px] uppercase tracking-wider font-semibold shadow-lg " +
            (inStartupGrace
              ? "bg-blue-600/90 text-white"
              : "bg-zinc-950/90 text-white")
          }
          role="status" aria-live="polite"
        >
          <Loader2 size={12} className="animate-spin" />
          {label}
        </div>
      )}
      {updateNudge && (
        <button
          data-testid="app-update-nudge"
          onClick={() => window.location.reload()}
          className="fixed top-3 right-3 z-[59] inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-amber-500 hover:bg-amber-400 text-black text-[11px] uppercase tracking-wider font-semibold shadow-lg"
          style={{ top: restarting ? "3.25rem" : "0.75rem" }}
          title="A newer build of the app is available on the server. Click to reload — your form drafts (Iter126c) are preserved."
        >
          <RefreshCw size={12} />
          App update available — reload
        </button>
      )}
    </>
  );
}
