// Iter97 → Iter127b-UAT-fix v4 · Silent Restart Toast (P0 CLOSURE cleanup).
//
// After the 24-hour observation window the P0 "REFRESHING…" acceptance
// criterion was formally met — no fail_streak >= 3 event during active
// business use.  The temporary diagnostic beacon has therefore been REMOVED
// in a single controlled commit.  The v4 restart-detection + graceful-
// startup + auto-reload behaviours are RETAINED verbatim:
//
//   • 4-fail threshold, 6 s per-probe abort, jittered 6 s poll with backoff
//     ramp 6 → 8 → 12 → 15 s.
//   • Graceful startup UX (v3): for the FIRST 10 s after the pill appears
//     we display "Backend starting…" instead of "Refreshing…".
//   • Build-drift detection (v2): passive amber "App update available —
//     reload" nudge when a newer server build_id is observed.
//   • Auto-reload (v4): if the amber nudge has been visible for 15 s AND
//     the backend is currently unreachable, reload once.  Iter126c form
//     drafts + Iter126b Idempotency-Key survive the reload via
//     sessionStorage; no duplicate Save is issued.
//
// The pill remains a passive visibility indicator — never gates Save
// operations, never mutates business state.
import React, { useEffect, useState, useRef } from "react";
import { Loader2, RefreshCw } from "lucide-react";

const BASE         = process.env.REACT_APP_BACKEND_URL || "";
const HEALTH_URL   = `${BASE}/api/auth/health`;
const BUILD_URL    = `${BASE}/api/diagnostics/build`;
const BUILD_POLL_MS = 60_000;
const BASELINE_KEY  = "silent_restart_baseline_build_id_v1";

export const FAIL_THRESHOLD  = 4;
export const PROBE_TIMEOUT   = 6000;   // v4 · 6 s to survive backend cold-starts
export const POLL_BASE       = 6000;
export const POLL_BACKOFF_MS = [6000, 8000, 12000, 15000];
export const STARTUP_GRACE_MS = 10_000;
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

/** v3 · Grace-window label. Within the grace window → "Backend starting…";
 *  afterwards → "Refreshing…". Never blocks. */
export function pillLabel(restartingSince, now = Date.now(), graceMs = STARTUP_GRACE_MS) {
  if (!restartingSince) return "Refreshing…";
  return (now - restartingSince) < graceMs ? "Backend starting…" : "Refreshing…";
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
        if (serverBuildId && serverBuildId !== baseline && !updateNudge) {
          setUpdateNudge(true);
          setUpdateNudgeSince(Date.now());
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

  // ── v4 · Build-stale auto-reload ──
  // If the amber "App update available" nudge has been visible for
  // BUILD_STALE_AUTORELOAD_MS AND the app can't currently reach a healthy
  // backend probe, reload once. Reload preserves:
  //   • Iter126c form drafts (sessionStorage survives location.reload)
  //   • Iter126b Idempotency-Key (persisted alongside each draft)
  //   • Any in-flight Save's replay contract (idempotency middleware
  //     de-dupes retries on the server side)
  useEffect(() => {
    if (!updateNudge) return () => {};
    if (!updateNudgeSince) return () => {};
    if (!restarting) return () => {};
    const t = setTimeout(() => {
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

      if (s.restarting && !prevRestarting) {
        setRestartingSince(Date.now());
      }
      if (!s.restarting && prevRestarting) {
        setRestartingSince(0);
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
  }, []);

  // ── v3 · label ticker — flip "Backend starting…" → "Refreshing…" without
  // waiting for the next 6-15 s probe. Cheap; only runs during outages. ──
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
