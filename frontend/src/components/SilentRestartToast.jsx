// Iter97 → Iter127b-fix · Silent Restart Toast.
//
// Shows a small non-blocking "Refreshing…" pill in the top-right whenever the
// backend is temporarily unreachable (5xx / 404 / network error). Disappears
// automatically the moment /api/auth/health returns 200 again.
//
// UAT-blocker hardening (Feb 2026 — RCA of "REFRESHING…" during multi-restart
// windows caused by dev-mode uvicorn --reload cycles):
//   1. Failure threshold raised from 2 → 4 consecutive fails (~24 s window
//      instead of ~12 s) so a normal 5-15 s backend reload no longer trips
//      the toast for staff during UAT.
//   2. Per-request 4 s AbortController timeout so a hung TCP connect during
//      shutdown doesn't stretch a single failure into browser-default 30 s.
//   3. Light exponential backoff on failures (6 s → 8 s → 12 s → cap 15 s)
//      so we're not hammering a restarting backend and don't accumulate
//      false-positive fails from probe-clustering.
//
// The toast remains a passive visibility indicator only — it does NOT gate
// Save operations or block user interaction.
import React, { useEffect, useState, useRef } from "react";
import { Loader2 } from "lucide-react";

const HEALTH_URL   = (process.env.REACT_APP_BACKEND_URL || "") + "/api/auth/health";

// Pure, testable constants + helpers — exported so unit tests can lock the
// contract without needing React rendering / @testing-library.
export const FAIL_THRESHOLD  = 4;      // ~24 s of continuous failure before showing the pill
export const PROBE_TIMEOUT   = 4000;   // 4 s abort per health probe
export const POLL_BASE       = 6000;   // 6 s when backend is healthy
export const POLL_BACKOFF_MS = [6000, 8000, 12000, 15000]; // ramp during failures

/** Returns the next poll delay given a failure streak. 0 → jittered base;
 *  1..3 → ramp; ≥4 → capped at last entry. Never returns < POLL_BASE. */
export function nextWaitMs(failStreak, jitter = 0) {
  if (failStreak <= 0) return POLL_BASE + jitter;
  const idx = Math.min(failStreak, POLL_BACKOFF_MS.length - 1);
  return POLL_BACKOFF_MS[idx];
}

/** Fires a single /api/auth/health probe with a hard 4 s abort. Returns true
 *  if the backend replied 2xx. Any non-2xx, network error, or abort ⇒ false.
 *  Injected `fetchImpl` + `AbortCtrl` make the helper unit-testable. */
export async function probeHealth(
  url = HEALTH_URL,
  { fetchImpl = fetch, AbortCtrl = AbortController, timeoutMs = PROBE_TIMEOUT } = {},
) {
  const ctrl = new AbortCtrl();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const r = await fetchImpl(url, { cache: "no-store", signal: ctrl.signal });
    return !!r && r.ok === true;
  } catch {
    return false;
  } finally {
    clearTimeout(t);
  }
}

/** Given the previous failure streak and the result of this probe, returns
 *  the next `{ failStreak, restarting }` state. Pure — no timers, no fetch. */
export function nextState(prevStreak, wasOk) {
  if (wasOk) return { failStreak: 0, restarting: false };
  const failStreak = prevStreak + 1;
  return { failStreak, restarting: failStreak >= FAIL_THRESHOLD };
}

export default function SilentRestartToast() {
  const [restarting, setRestarting] = useState(false);
  const failStreak = useRef(0);
  const timerId    = useRef(null);

  useEffect(() => {
    let alive = true;

    const tick = async () => {
      const ok = await probeHealth(HEALTH_URL);
      if (!alive) return;
      const s = nextState(failStreak.current, ok);
      failStreak.current = s.failStreak;
      setRestarting(s.restarting);
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

    // Kick immediately then start the loop.
    tick().then(schedule);

    return () => {
      alive = false;
      if (timerId.current) clearTimeout(timerId.current);
    };
  }, []);

  if (!restarting) return null;
  return (
    <div
      data-testid="silent-restart-toast"
      className="pointer-events-none fixed top-3 right-3 z-[60] inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-zinc-950/90 text-white text-[11px] uppercase tracking-wider font-semibold shadow-lg"
      role="status" aria-live="polite"
    >
      <Loader2 size={12} className="animate-spin" />
      Refreshing…
    </div>
  );
}
