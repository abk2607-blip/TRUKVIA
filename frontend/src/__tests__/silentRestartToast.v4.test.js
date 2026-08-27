/**
 * Iter127b-UAT-fix v4 · Constant + timeout regression coverage.
 *
 * Locks the two constants the user approved (Option C):
 *   A. BUILD_STALE_AUTORELOAD_MS = 15_000
 *   B. PROBE_TIMEOUT              = 6_000 (was 4_000)
 *
 * We keep the existing behaviour tests in `silentRestartToast.test.js`
 * green — this file only asserts the new v4 constants and that the
 * `probeHealth` helper honours a caller-supplied timeout.
 */
import {
  FAIL_THRESHOLD, PROBE_TIMEOUT, POLL_BASE, POLL_BACKOFF_MS,
  STARTUP_GRACE_MS, BUILD_STALE_AUTORELOAD_MS,
  probeHealth,
} from "../components/SilentRestartToast";

test("v4 · PROBE_TIMEOUT raised to 6 000 ms", () => {
  expect(PROBE_TIMEOUT).toBe(6_000);
});

test("v4 · BUILD_STALE_AUTORELOAD_MS is 15 s", () => {
  expect(BUILD_STALE_AUTORELOAD_MS).toBe(15_000);
});

test("v3 constants unchanged (regression)", () => {
  expect(FAIL_THRESHOLD).toBe(4);
  expect(POLL_BASE).toBe(6_000);
  expect(POLL_BACKOFF_MS).toEqual([6_000, 8_000, 12_000, 15_000]);
  expect(STARTUP_GRACE_MS).toBe(10_000);
});

class FakeAbortCtrl { constructor() { this.aborted = false; this.signal = {}; } abort() { this.aborted = true; } }

test("v4 · probeHealth honours caller-provided timeout (6 s)", async () => {
  jest.useFakeTimers();
  let ctrl;
  const fetchImpl = jest.fn((_url, { signal }) => new Promise((_res, rej) => {
    signal.addEventListener?.("abort", () => {
      const e = new Error("aborted"); e.name = "AbortError"; rej(e);
    });
  }));
  const AbortCtrl = class {
    constructor() {
      ctrl = this; this.aborted = false;
      const listeners = [];
      this.signal = { addEventListener: (_e, cb) => listeners.push(cb) };
      this._listeners = listeners;
    }
    abort() { this.aborted = true; this._listeners.forEach((cb) => cb()); }
  };

  // At t = PROBE_TIMEOUT - 1 the request is NOT yet aborted.
  const p = probeHealth("http://x", { fetchImpl, AbortCtrl });
  jest.advanceTimersByTime(PROBE_TIMEOUT - 1);
  expect(ctrl.aborted).toBe(false);
  // At t = PROBE_TIMEOUT + 1 the abort has fired.
  jest.advanceTimersByTime(2);
  const res = await p;
  expect(res.ok).toBe(false);
  expect(res.error).toBe("abort");
  expect(res.durationMs).toBeGreaterThanOrEqual(PROBE_TIMEOUT - 100);

  jest.useRealTimers();
});

test("v4 · a slow-but-reachable backend response under 6 s now counts as OK", async () => {
  jest.useFakeTimers();
  // Simulate a response arriving at 5 500 ms (was aborted under v3's 4 s limit).
  const fetchImpl = jest.fn(() => new Promise((res) => {
    setTimeout(() => res({ ok: true, status: 200 }), 5_500);
  }));
  const p = probeHealth("http://x", { fetchImpl, AbortCtrl: FakeAbortCtrl });
  jest.advanceTimersByTime(5_600);
  const res = await p;
  expect(res.ok).toBe(true);
  expect(res.status).toBe(200);
  expect(res.error).toBeNull();
  jest.useRealTimers();
});
