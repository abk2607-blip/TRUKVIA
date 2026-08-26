/**
 * SilentRestartToast · Iter127b-UAT-fix behavioural contract.
 *
 * These are PURE unit tests against the exported helpers — no React render,
 * no @testing-library. They lock in the hardened polling behaviour that
 * unblocked UAT: 4-fail threshold, 4 s abort per probe, backoff ramp, and
 * instant clear on the next 200.
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
  expect(nextWaitMs(1)).toBe(POLL_BACKOFF_MS[1]);      // 8 s
  expect(nextWaitMs(2)).toBe(POLL_BACKOFF_MS[2]);      // 12 s
  expect(nextWaitMs(3)).toBe(POLL_BACKOFF_MS[3]);      // 15 s
  expect(nextWaitMs(10)).toBe(POLL_BACKOFF_MS[3]);     // still 15 s
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

test("probeHealth returns true on 2xx", async () => {
  const fetchImpl = jest.fn(() => Promise.resolve({ ok: true, status: 200 }));
  const ok = await probeHealth("http://x", { fetchImpl, AbortCtrl: FakeAbortCtrl });
  expect(ok).toBe(true);
  expect(fetchImpl).toHaveBeenCalledWith(
    "http://x",
    expect.objectContaining({ cache: "no-store", signal: expect.anything() }),
  );
});

test("probeHealth returns false on 5xx", async () => {
  const fetchImpl = jest.fn(() => Promise.resolve({ ok: false, status: 503 }));
  const ok = await probeHealth("http://x", { fetchImpl, AbortCtrl: FakeAbortCtrl });
  expect(ok).toBe(false);
});

test("probeHealth returns false on network error", async () => {
  const fetchImpl = jest.fn(() => Promise.reject(new Error("net")));
  const ok = await probeHealth("http://x", { fetchImpl, AbortCtrl: FakeAbortCtrl });
  expect(ok).toBe(false);
});

test("probeHealth aborts a hung fetch after the configured timeout", async () => {
  jest.useFakeTimers();
  let capturedCtrl;
  const fetchImpl = jest.fn((_url, { signal }) => new Promise((_res, rej) => {
    // Never resolves. When aborted, reject like real fetch.
    signal.addEventListener?.("abort", () => rej(new Error("aborted")));
  }));
  const AbortCtrl = class {
    constructor() {
      capturedCtrl = this;
      this.aborted = false;
      const listeners = [];
      this.signal = {
        addEventListener: (_ev, cb) => listeners.push(cb),
      };
      this._listeners = listeners;
    }
    abort() {
      this.aborted = true;
      this._listeners.forEach((cb) => cb());
    }
  };
  const p = probeHealth("http://x", { fetchImpl, AbortCtrl, timeoutMs: 4000 });
  jest.advanceTimersByTime(4001);
  const ok = await p;
  expect(ok).toBe(false);
  expect(capturedCtrl.aborted).toBe(true);
  jest.useRealTimers();
});
