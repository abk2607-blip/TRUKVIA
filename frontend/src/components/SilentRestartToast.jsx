// Iter97 → Iter127b-UAT-fix v2 · Silent Restart Toast + diagnostic beacon.
//
// The toast itself is unchanged (hardened Feb 2026): 4-fail threshold, 4 s
// per-probe abort, jittered 6 s poll with backoff ramp 6→8→12→15 s. The
// pill remains a passive visibility indicator — never gates Save operations.
//
// TEMPORARY DIAGNOSTIC INSTRUMENTATION (Feb 2026 · slated for revert):
//   • Fire-and-forget beacon to POST /api/diagnostics/silent-restart-probe
//     on every failStreak transition — including 0→1, sustained fails, the
//     0→restarting flip, and the restarting→cleared flip. Uses `fetch()`
//     with `keepalive:true` (NOT axios) so no interceptor / no Idempotency
//     Key / no Authorization header is attached.
//   • Passive "App update available — reload" nudge appears if the server-
//     reported build_id differs from the one we captured on first mount
//     (stored in sessionStorage — clears on hard refresh). No auto reload.
//
// Safety: NO form, PII, token, GSTIN or financial data leaves the browser
// through this module. Beacon payload keys are hard-whitelisted server-side.
import React, { useEffect, useState, useRef, useCallback } from "react";
import { Loader2, RefreshCw } from "lucide-react";

const BASE         = process.env.REACT_APP_BACKEND_URL || "";
const HEALTH_URL   = `${BASE}/api/auth/health`;
const BEACON_URL   = `${BASE}/api/diagnostics/silent-restart-probe`;
const BUILD_URL    = `${BASE}/api/diagnostics/build`;
const BUILD_POLL_MS = 60_000;      // check for stale-bundle once a minute
const BASELINE_KEY  = "silent_restart_baseline_build_id_v1";

// Pure, testable constants + helpers — exported so unit tests can lock the
// contract without needing React rendering / @testing-library.
export const FAIL_THRESHOLD  = 4;      // ~24 s of continuous failure before showing the pill
export const PROBE_TIMEOUT   = 4000;   // 4 s abort per health probe
export const POLL_BASE       = 6000;   // 6 s when backend is healthy
export const POLL_BACKOFF_MS = [6000, 8000, 12000, 15000]; // ramp during failures

/** Returns the next poll delay given a failure streak. */
export function nextWaitMs(failStreak, jitter = 0) {
  if (failStreak <= 0) return POLL_BASE + jitter;
  const idx = Math.min(failStreak, POLL_BACKOFF_MS.length - 1);
  return POLL_BACKOFF_MS[idx];
}

/** Fires a single /api/auth/health probe with a hard 4 s abort.
 *  Returns { ok, status, error, durationMs }. */
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

/** Given the previous failure streak and the result of this probe, returns
 *  the next `{ failStreak, restarting }` state. */
export function nextState(prevStreak, wasOk) {
  if (wasOk) return { failStreak: 0, restarting: false };
  const failStreak = prevStreak + 1;
  return { failStreak, restarting: failStreak >= FAIL_THRESHOLD };
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

/** Fire-and-forget diagnostic beacon. Uses fetch() with keepalive:true so
 *  it survives page unloads. Never throws. Never uses axios / interceptors. */
function sendBeacon(payload) {
  try {
    // eslint-disable-next-line no-undef
    fetch(BEACON_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      keepalive: true,
      cache: "no-store",
      // NO credentials, NO custom auth header — this is a public beacon.
    }).catch(() => {});
  } catch {
    /* swallow */
  }
}

// -------------------------------------------------------------------- component
export default function SilentRestartToast() {
  const [restarting, setRestarting]           = useState(false);
  const [updateNudge, setUpdateNudge]         = useState(false);
  const [clientBuildId, setClientBuildId]     = useState(null);
  const failStreak    = useRef(0);
  const timerId       = useRef(null);
  const buildTimerId  = useRef(null);

  // ── Beacon helper (stable ref) ──
  const emit = useCallback((phase, extra) => {
    let visibility = "visible";
    try { visibility = document.visibilityState || "visible"; } catch {}
    let conn = "unknown";
    try {
      const nc = (navigator.connection || navigator.mozConnection || navigator.webkitConnection);
      if (nc && nc.effectiveType) conn = String(nc.effectiveType);
    } catch {}
    let ua = "unknown";
    try {
      // Only browser family + first version segment — no full UA string.
      const raw = (navigator.userAgent || "").slice(0, 80);
      ua = raw;
    } catch {}
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

  // ── Baseline the build_id once, then poll for drift every 60 s ──
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
            // Emit a one-time beacon so we can correlate stale-bundle events.
            sendBeacon({
              ts: new Date().toISOString(),
              phase: "build_stale",
              fail_streak: failStreak.current,
              restarting,
              client_build_id: baseline,
              // Deliberately not sending server_build_id — the diagnostic
              // schema doesn't include it and we don't want schema drift.
            });
          }
        }
      } catch {
        /* swallow — build check is best-effort */
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

      // Beacon on meaningful transitions only (avoid spam on continuous 200s).
      const probeResult = _resultLabel(res.status, res.error);
      if (!res.ok) {
        emit("streak_bump", {
          probeResult, status: res.status, durationMs: res.durationMs,
          restarting: s.restarting,
        });
      }
      if (s.restarting && !prevRestarting) {
        emit("restart_shown", {
          probeResult, status: res.status, durationMs: res.durationMs,
          restarting: true,
        });
      }
      if (!s.restarting && prevRestarting) {
        emit("cleared", {
          probeResult, status: res.status, durationMs: res.durationMs,
          restarting: false,
        });
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

  return (
    <>
      {restarting && (
        <div
          data-testid="silent-restart-toast"
          className="pointer-events-none fixed top-3 right-3 z-[60] inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-zinc-950/90 text-white text-[11px] uppercase tracking-wider font-semibold shadow-lg"
          role="status" aria-live="polite"
        >
          <Loader2 size={12} className="animate-spin" />
          Refreshing…
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
