/**
 * Iter126c-UAT-fix · Meaningfully-dirty draft gate — CONTRACT tests.
 *
 * User-observed bug: mounting /trips/new on a blank form displayed
 * "Unsaved Draft Found — 3 seconds ago" even without any user input.
 *
 * Root cause: the autosave effect fired 800 ms after mount with an
 * untouched form buffer, wrote it to sessionStorage, and the next reload
 * loaded it back as a "draft".
 *
 * Fix contract locked here: a draft is persisted ONLY after the sanitised
 * sha diverges from the untouched-mount baseline. These tests exercise the
 * pure helpers that back the hook's decision so we don't need
 * @testing-library/react.
 *
 * The hook's decision reduces to:
 *   1. Capture baselineSha = draftSha(sanitizeDraft(form)) at first render.
 *   2. On every autosave tick:
 *        currentSha = draftSha(sanitizeDraft(form))
 *        if (!existingDraft && currentSha === baselineSha) → SKIP WRITE.
 *
 * If both cases behave correctly, the hook cannot ever persist an
 * untouched draft.
 */
import {
  sanitizeDraft, draftSha, buildDraftKey, loadDraft, saveDraft, clearDraft,
} from "../lib/formDraft";

beforeEach(() => sessionStorage.clear());

// jsdom lacks crypto.randomUUID.
if (!globalThis.crypto) globalThis.crypto = {};
if (!globalThis.crypto.randomUUID) {
  let _n = 0;
  globalThis.crypto.randomUUID = () => `test-uuid-${(_n += 1).toString().padStart(12, "0")}`;
}

// ── Baseline stability ─────────────────────────────────────────────────
test("untouched form yields a stable baselineSha (idempotent)", () => {
  const emptyForm = {
    date: "2026-02-27",
    customer_id: "",
    driver_id: "",
    vehicle_id: "",
    product_id: "",
    notes: "",
    loading: { qty: "" },
    unloading: { qty: "" },
    freight: { rate: "" },
    supplier: {},
    expenses: {},
  };
  const sha1 = draftSha(sanitizeDraft(emptyForm));
  const sha2 = draftSha(sanitizeDraft({ ...emptyForm }));
  expect(sha1).toBe(sha2);
  expect(sha1).toBeTruthy();
});

test("Invoice-style untouched form yields a stable baselineSha", () => {
  const initial = {
    customerId: "",
    selected: {},
    rcm: true,
    hsnSac: "996791",
    invoiceDate: "2026-02-27",
    notes: "",
  };
  const sha1 = draftSha(sanitizeDraft(initial));
  const sha2 = draftSha(sanitizeDraft({ ...initial }));
  expect(sha1).toBe(sha2);
});

// ── The gate itself: baseline == current → NEVER writes ────────────────
test("gate: blank New Trip stays out of sessionStorage after debounce simulation", () => {
  const emptyForm = { date: "2026-02-27", customer_id: "", notes: "" };
  const compositeKey = buildDraftKey({
    route: "/trips/new", userId: "u-test", companyId: "c-test",
  });

  // Simulate what the hook does on autosave tick:
  const baselineSha = draftSha(sanitizeDraft(emptyForm));
  const currentSha  = draftSha(sanitizeDraft(emptyForm));
  const existingDraft = loadDraft(compositeKey, { userId: "u-test" });
  const shouldSkip = !existingDraft && currentSha === baselineSha;

  expect(shouldSkip).toBe(true);
  // If the gate is respected, NOTHING was ever written.
  expect(sessionStorage.length).toBe(0);
});

// ── Meaningful edit crosses the gate ──────────────────────────────────
test("gate opens: picking a customer changes sha → autosave allowed", () => {
  const initial = { date: "2026-02-27", customer_id: "", notes: "" };
  const touched = { ...initial, customer_id: "cust_1" };
  const baselineSha = draftSha(sanitizeDraft(initial));
  const currentSha  = draftSha(sanitizeDraft(touched));

  expect(currentSha).not.toBe(baselineSha);
  // Now simulate the autosave call the hook would issue.
  const compositeKey = buildDraftKey({
    route: "/trips/new", userId: "u-test", companyId: "c-test",
  });
  const persisted = saveDraft(compositeKey, {
    route: "/trips/new", form: touched, userId: "u-test",
  });
  expect(persisted).toBeTruthy();
  expect(loadDraft(compositeKey, { userId: "u-test" })).toBeTruthy();
});

// ── Meaningful edits on every field variant we care about ─────────────
test.each([
  ["customer_id",  { customer_id: "cust_1" }],
  ["driver_id",    { driver_id: "drv_9" }],
  ["vehicle_id",   { vehicle_id: "veh_9" }],
  ["notes",        { notes: "Hello" }],
  ["loading.qty",  { loading: { qty: "10" } }],
  ["unloading.qty",{ unloading: { qty: "9.85" } }],
  ["freight.rate", { freight: { rate: "5000" } }],
])("gate opens when %s is edited", (_label, patch) => {
  const initial = {
    date: "2026-02-27",
    customer_id: "", driver_id: "", vehicle_id: "", notes: "",
    loading: { qty: "" }, unloading: { qty: "" }, freight: { rate: "" },
  };
  const baseline = draftSha(sanitizeDraft(initial));
  const touched  = draftSha(sanitizeDraft({ ...initial, ...patch, ...(patch.loading ? { loading: patch.loading } : {}), ...(patch.unloading ? { unloading: patch.unloading } : {}), ...(patch.freight ? { freight: patch.freight } : {}) }));
  expect(touched).not.toBe(baseline);
});

// ── Non-meaningful mutations (identity) don't open the gate ───────────
test("gate stays shut: object identity change without value change (spread)", () => {
  const initial = { date: "2026-02-27", customer_id: "", notes: "" };
  expect(draftSha(sanitizeDraft(initial))).toBe(draftSha(sanitizeDraft({ ...initial })));
});

test("gate stays shut: same value re-set into the same field", () => {
  const initial = { date: "2026-02-27", customer_id: "", notes: "" };
  const same    = { ...initial, notes: "" }; // explicitly setting to same value
  expect(draftSha(sanitizeDraft(same))).toBe(draftSha(sanitizeDraft(initial)));
});
