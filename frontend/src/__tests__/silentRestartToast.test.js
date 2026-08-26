/**
 * SilentRestartToast · Iter127b-UAT-fix v3 behavioural contract (Feb 2026).
 *
 * Adds the "graceful startup UX" behaviour: within the first STARTUP_GRACE_MS
 * (10 s) of the pill appearing we render "Backend starting…" — after that
 * the copy falls back to "Refreshing…". Pure unit tests over the exported
 * `pillLabel()` helper — no React rendering.
 */
import {
  FAIL_THRESHOLD, PROBE_TIMEOUT, POLL_BASE, POLL_BACKOFF_MS,
  STARTUP_GRACE_MS,
  nextWaitMs, nextState, probeHealth, pillLabel,
} from "../components/SilentRestartToast";

// ── constants ────────────────────────────────────────────────────────────
test("threshold is still 4 (survives normal reload)", () => {
  expect(FAIL_THRESHOLD).toBe(4);
});
test("per-probe timeout is still 4 s", () => { expect(PROBE_TIMEOUT).toBe(4000); });
test("healthy base poll is still 6 s", () => { expect(POLL_BASE).toBe(6000); });
test("backoff ramp unchanged", () => {
  expect(POLL_BACKOFF_MS).toEqual([6000, 8000, 12000, 15000]);
});
test("v3 · startup grace window is 10 s", () => {
  expect(STARTUP_GRACE_MS).toBe(10_000);
});

// ── pillLabel ────────────────────────────────────────────────────────────
test("pillLabel returns Refreshing… when never restarted", () => {
  expect(pillLabel(0, 100_000)).toBe("Refreshing…");
});

test("pillLabel returns 'Backend starting…' just after restarting starts", () => {
  const restartingSince = 1_000_000;
  expect(pillLabel(restartingSince, restartingSince + 100)).toBe("Backend starting…");
  expect(pillLabel(restartingSince, restartingSince + 9_999)).toBe("Backend starting…");
});

test("pillLabel flips to 'Refreshing…' exactly at the 10 s grace boundary", () => {
  const restartingSince = 2_000_000;
  expect(pillLabel(restartingSince, restartingSince + STARTUP_GRACE_MS)).toBe("Refreshing…");
  expect(pillLabel(restartingSince, restartingSince + STARTUP_GRACE_MS + 1_000)).toBe("Refreshing…");
});

test("pillLabel does NOT change with fail-streak (label is time-based only)", () => {
  const restartingSince = 3_000_000;
  const t = restartingSince + 5_000;
  expect(pillLabel(restartingSince, t)).toBe("Backend starting…");
  // Deep failure streaks don't matter for the label — only time.
  // Simulate a probe at t+7s (still within grace):
  expect(pillLabel(restartingSince, t + 2_000)).toBe("Backend starting…");
});

// ── nextWaitMs (regression) ─────────────────────────────────────────────
test("nextWaitMs unchanged after v3", () => {
  expect(nextWaitMs(0, 100)).toBe(POLL_BASE + 100);
  expect(nextWaitMs(1)).toBe(POLL_BACKOFF_MS[1]);
  expect(nextWaitMs(10)).toBe(POLL_BACKOFF_MS[3]);
});

// ── nextState (regression) ───────────────────────────────────────────────
test("nextState still trips at exactly 4", () => {
  expect(nextState(3, false)).toEqual({ failStreak: 4, restarting: true });
});
test("nextState still resets on 200", () => {
  expect(nextState(99, true)).toEqual({ failStreak: 0, restarting: false });
});

// ── probeHealth (regression: still returns structured shape) ─────────────
class FakeAbortCtrl { constructor() { this.aborted = false; this.signal = {}; } abort() { this.aborted = true; } }

test("probeHealth still returns {ok,status,error,durationMs}", async () => {
  const fetchImpl = jest.fn(() => Promise.resolve({ ok: true, status: 200 }));
  const res = await probeHealth("http://x", { fetchImpl, AbortCtrl: FakeAbortCtrl });
  expect(res).toEqual(expect.objectContaining({ ok: true, status: 200, error: null }));
});
