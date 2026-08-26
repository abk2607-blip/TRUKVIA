/**
 * SilentRestartToast · Iter127b-UAT-fix behavioural contract.
 *
 * Pure unit tests — no React render / no @testing-library.
 * Locks in: 4-fail threshold, 4 s per-probe abort, backoff ramp, and
 * probeHealth returning a structured `{ok,status,error,durationMs}` object
 * (Iter127b-UAT-fix v2 · added for the diagnostic beacon).
 */
import {
  FAIL_THRESHOLD, PROBE_TIMEOUT, POLL_BASE, POLL_BACKOFF_MS,
  nextWaitMs, nextState, probeHealth,
} from "../components/SilentRestartToast";

// ── constants ────────────────────────────────────────────────────────────
test("threshold is 4 (raised from 2 to survive normal reload windows)", () => {
  expect(FAIL_THRESHOLD).toBe(4);
});

test("per-probe timeout is 4 s", () => {
  expect(PROBE_TIMEOUT).toBe(4000);
});

test("healthy base poll is 6 s", () => {
  expect(POLL_BASE).toBe(6000);
});

test("failure backoff ramps 6 → 8 → 12 → 15 s (never > 15)", () => {
  expect(POLL_BACKOFF_MS).toEqual([6000, 8000, 12000, 15000]);
  expect(Math.max(...POLL_BACKOFF_MS)).toBeLessThanOrEqual(15000);
});

// ── nextWaitMs ───────────────────────────────────────────────────────────
test("nextWaitMs uses base + jitter when healthy", () => {
  expect(nextWaitMs(0, 200)).toBe(POLL_BASE + 200);
});

test("nextWaitMs ramps through the backoff schedule and caps at last entry", () => {
  expect(nextWaitMs(1)).toBe(POLL_BACKOFF_MS[1]);
  expect(nextWaitMs(2)).toBe(POLL_BACKOFF_MS[2]);
  expect(nextWaitMs(3)).toBe(POLL_BACKOFF_MS[3]);
  expect(nextWaitMs(10)).toBe(POLL_BACKOFF_MS[3]);
});

// ── nextState ────────────────────────────────────────────────────────────
test("nextState resets on a successful probe", () => {
  expect(nextState(3, true)).toEqual({ failStreak: 0, restarting: false });
  expect(nextState(99, true)).toEqual({ failStreak: 0, restarting: false });
});

test("nextState does NOT show pill after 1, 2, or 3 consecutive failures", () => {
  expect(nextState(0, false)).toEqual({ failStreak: 1, restarting: false });
  expect(nextState(1, false)).toEqual({ failStreak: 2, restarting: false });
  expect(nextState(2, false)).toEqual({ failStreak: 3, restarting: false });
});

test("nextState SHOWS pill after exactly 4 consecutive failures", () => {
  expect(nextState(3, false)).toEqual({ failStreak: 4, restarting: true });
});

test("nextState keeps pill on while streak continues", () => {
  expect(nextState(5, false)).toEqual({ failStreak: 6, restarting: true });
});

test("a single 200 clears the pill immediately no matter how deep the streak", () => {
  expect(nextState(20, true)).toEqual({ failStreak: 0, restarting: false });
});

// ── probeHealth ──────────────────────────────────────────────────────────
class FakeAbortCtrl { constructor() { this.aborted = false; this.signal = {}; } abort() { this.aborted = true; } }

test("probeHealth returns ok=true and status on 2xx", async () => {
  const fetchImpl = jest.fn(() => Promise.resolve({ ok: true, status: 200 }));
  const res = await probeHealth("http://x", { fetchImpl, AbortCtrl: FakeAbortCtrl });
  expect(res.ok).toBe(true);
  expect(res.status).toBe(200);
  expect(res.error).toBeNull();
  expect(typeof res.durationMs).toBe("number");
  expect(fetchImpl).toHaveBeenCalledWith(
    "http://x",
    expect.objectContaining({ cache: "no-store", signal: expect.anything() }),
  );
});

test("probeHealth returns ok=false with status=503 on 5xx", async () => {
  const fetchImpl = jest.fn(() => Promise.resolve({ ok: false, status: 503 }));
  const res = await probeHealth("http://x", { fetchImpl, AbortCtrl: FakeAbortCtrl });
  expect(res.ok).toBe(false);
  expect(res.status).toBe(503);
  expect(res.error).toBeNull();
});

test("probeHealth returns ok=false with error='network' on fetch reject", async () => {
  const fetchImpl = jest.fn(() => Promise.reject(new Error("boom")));
  const res = await probeHealth("http://x", { fetchImpl, AbortCtrl: FakeAbortCtrl });
  expect(res.ok).toBe(false);
  expect(res.status).toBeNull();
  expect(res.error).toBe("network");
});

test("probeHealth aborts a hung fetch after the configured timeout (returns error='abort')", async () => {
  jest.useFakeTimers();
  let capturedCtrl;
  const fetchImpl = jest.fn((_url, { signal }) => new Promise((_res, rej) => {
    signal.addEventListener?.("abort", () => {
      const e = new Error("aborted");
      e.name = "AbortError";
      rej(e);
    });
  }));
  const AbortCtrl = class {
    constructor() {
      capturedCtrl = this;
      this.aborted = false;
      const listeners = [];
      this.signal = { addEventListener: (_ev, cb) => listeners.push(cb) };
      this._listeners = listeners;
    }
    abort() {
      this.aborted = true;
      this._listeners.forEach((cb) => cb());
    }
  };
  const p = probeHealth("http://x", { fetchImpl, AbortCtrl, timeoutMs: 4000 });
  jest.advanceTimersByTime(4001);
  const res = await p;
  expect(res.ok).toBe(false);
  expect(res.error).toBe("abort");
  expect(capturedCtrl.aborted).toBe(true);
  jest.useRealTimers();
});
