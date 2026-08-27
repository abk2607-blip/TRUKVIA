/**
 * Iter126c-UAT-fix v2 · Restore-banner behaviour contract.
 *
 * Locks the two behaviours the user asked for in the second UAT round:
 *   1. Existing Trip Edit route (recordId truthy) → NEVER shows the Restore
 *      banner, even if a draft happens to exist on that composite key. It
 *      also never PROBES or writes a draft, so the DB row stays authoritative.
 *   2. New Trip route (recordId empty) →
 *        • Blank mount → no draft written, no banner.
 *        • Meaningful edit → draft silently persisted, banner STILL hidden.
 *        • Simulated "close & reopen" → banner appears.
 *        • Successful save → draft cleared.
 *
 * We test the pure `useFormDraft` behaviour by mounting it under a tiny
 * functional component that exposes the hook's return value via a ref —
 * no `@testing-library/react` dependency needed thanks to `react-dom/test-utils`.
 */
import React from "react";
import ReactDOM from "react-dom/client";
import { act } from "react-dom/test-utils";
import { useFormDraft } from "../hooks/useFormDraft";
import {
  buildDraftKey, saveDraft, loadDraft, DRAFT_KEY_PREFIX,
} from "../lib/formDraft";

// Silence the "current testing environment is not configured to support
// act(...)" warning — jest doesn't set this flag by default but the tests
// wrap every render in act() correctly.
// eslint-disable-next-line no-undef
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

// jsdom lacks crypto.randomUUID.
if (!globalThis.crypto) globalThis.crypto = {};
if (!globalThis.crypto.randomUUID) {
  let _n = 0;
  globalThis.crypto.randomUUID = () => `test-uuid-${(_n += 1).toString().padStart(12, "0")}`;
}

// Small harness component that mounts the hook and exposes its return
// value on a mutable ref so the tests can inspect internals.
function Harness({ form, setForm, recordId = "", route = "/trips/new", capture }) {
  const d = useFormDraft({
    route, recordId,
    form, setForm,
    userId: "u-test",
    companyId: "c-test",
  });
  capture.current = d;
  return null;
}

function mount(props) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = ReactDOM.createRoot(container);
  act(() => { root.render(<Harness {...props} />); });
  return {
    rerender: (nextProps) => act(() => { root.render(<Harness {...nextProps} />); }),
    unmount: () => act(() => { root.unmount(); container.remove(); }),
  };
}

function draftKeyCount() {
  let n = 0;
  for (let i = 0; i < sessionStorage.length; i += 1) {
    const k = sessionStorage.key(i);
    if (k && k.startsWith(DRAFT_KEY_PREFIX)) n += 1;
  }
  return n;
}

function tick(ms = 900) {
  jest.advanceTimersByTime(ms);
}

beforeEach(() => {
  sessionStorage.clear();
  jest.useFakeTimers();
});
afterEach(() => {
  jest.useRealTimers();
});

// ─────────────────────────────────────────────────────────────────────────
// 1. Existing Trip Edit route → NEVER shows the banner
// ─────────────────────────────────────────────────────────────────────────
test("existing Trip edit route: NO banner even when a draft is on disk", () => {
  // Pre-plant a draft under the SAME composite key so we prove the edit
  // route explicitly skips the probe (not just doesn't find one).
  const editKey = buildDraftKey({
    route: "/trips/:id/edit", recordId: "trip_42",
    userId: "u-test", companyId: "c-test",
  });
  saveDraft(editKey, {
    route: "/trips/:id/edit",
    form: { customer_id: "cust_1", notes: "ghost draft" },
    userId: "u-test",
  });
  expect(loadDraft(editKey, { userId: "u-test" })).toBeTruthy();

  const capture = { current: null };
  const initial = { customer_id: "", notes: "" };
  mount({
    form: initial, setForm: () => {}, capture,
    route: "/trips/:id/edit", recordId: "trip_42",
  });
  act(() => { tick(); });

  expect(capture.current.banner).toBe(false);
  expect(capture.current._mountDraft).toBeNull();
  expect(capture.current._isEditRoute).toBe(true);
});

test("edit route: autosave is disabled — a meaningful edit does NOT touch sessionStorage", () => {
  const capture = { current: null };
  const initial = { customer_id: "", notes: "" };
  const { rerender } = mount({
    form: initial, setForm: () => {}, capture,
    route: "/trips/:id/edit", recordId: "trip_42",
  });
  act(() => { tick(); });
  expect(draftKeyCount()).toBe(0);

  // User makes a meaningful edit while editing an existing Trip — no
  // draft should be persisted for this route.
  rerender({
    form: { customer_id: "cust_1", notes: "new note" }, setForm: () => {},
    capture, route: "/trips/:id/edit", recordId: "trip_42",
  });
  act(() => { tick(); });
  expect(draftKeyCount()).toBe(0);
});

// ─────────────────────────────────────────────────────────────────────────
// 2. New Trip route → banner ONLY from mount discovery, never from live autosave
// ─────────────────────────────────────────────────────────────────────────
test("blank New Trip mount: no draft, no banner (meaningfully-dirty gate intact)", () => {
  const capture = { current: null };
  const initial = {
    date: "2026-02-27",
    customer_id: "", driver_id: "", vehicle_id: "", notes: "",
    loading: { qty: "" }, unloading: { qty: "" }, freight: { rate: "" },
  };
  mount({ form: initial, setForm: () => {}, capture });
  act(() => { tick(); });
  expect(draftKeyCount()).toBe(0);
  expect(capture.current.banner).toBe(false);
  expect(capture.current._mountDraft).toBeNull();
});

test("meaningful edit persists a draft SILENTLY — banner stays hidden", () => {
  const capture = { current: null };
  const initial = { customer_id: "", notes: "" };
  const { rerender } = mount({ form: initial, setForm: () => {}, capture });
  act(() => { tick(); });
  expect(draftKeyCount()).toBe(0);
  expect(capture.current.banner).toBe(false);

  // User picks a customer — first meaningful edit
  rerender({
    form: { customer_id: "cust_1", notes: "" }, setForm: () => {}, capture,
  });
  act(() => { tick(); });
  // Draft was silently persisted, but the banner MUST NOT flip on.
  expect(draftKeyCount()).toBe(1);
  expect(capture.current.banner).toBe(false);
  expect(capture.current._draft).toBeTruthy();
  expect(capture.current._mountDraft).toBeNull();
});

test("close & reopen /trips/new: banner appears on the SECOND mount", () => {
  // Session A · user edits and then closes tab
  {
    const capture = { current: null };
    const { rerender, unmount } = mount({ form: { customer_id: "" }, setForm: () => {}, capture });
    act(() => { tick(); });
    rerender({ form: { customer_id: "cust_1" }, setForm: () => {}, capture });
    act(() => { tick(); });
    expect(draftKeyCount()).toBe(1);
    expect(capture.current.banner).toBe(false);
    unmount();
  }
  // Session B · new /trips/new mount — draft found on disk
  {
    const capture = { current: null };
    mount({ form: { customer_id: "" }, setForm: () => {}, capture });
    act(() => { tick(); });
    expect(capture.current.banner).toBe(true);
    expect(capture.current._mountDraft).toBeTruthy();
    expect(capture.current._mountDraft.form.customer_id).toBe("cust_1");
  }
});

test("restore() clears the banner AND merges the draft into the form", () => {
  // Pre-plant a draft on disk
  const key = buildDraftKey({
    route: "/trips/new", recordId: "", userId: "u-test", companyId: "c-test",
  });
  saveDraft(key, {
    route: "/trips/new",
    form: { customer_id: "cust_9", notes: "recovered" },
    userId: "u-test",
  });

  const capture = { current: null };
  let capturedForm = { customer_id: "", notes: "" };
  const setForm = (updater) => {
    capturedForm = typeof updater === "function" ? updater(capturedForm) : updater;
  };
  const { rerender } = mount({ form: capturedForm, setForm, capture });
  act(() => { tick(); });
  expect(capture.current.banner).toBe(true);

  act(() => { capture.current.restore(); });
  rerender({ form: capturedForm, setForm, capture });
  act(() => { tick(); });

  expect(capture.current.banner).toBe(false);
  expect(capturedForm.customer_id).toBe("cust_9");
  expect(capturedForm.notes).toBe("recovered");
});

test("discard() clears the banner AND wipes the draft from disk", () => {
  const key = buildDraftKey({
    route: "/trips/new", recordId: "", userId: "u-test", companyId: "c-test",
  });
  saveDraft(key, {
    route: "/trips/new",
    form: { customer_id: "cust_9" },
    userId: "u-test",
  });

  const capture = { current: null };
  mount({ form: { customer_id: "" }, setForm: () => {}, capture });
  act(() => { tick(); });
  expect(capture.current.banner).toBe(true);

  act(() => { capture.current.discard(); });
  expect(capture.current.banner).toBe(false);
  expect(draftKeyCount()).toBe(0);
});

test("clearOnSuccess() clears the banner AND wipes the draft (successful save)", () => {
  const capture = { current: null };
  const { rerender } = mount({ form: { customer_id: "" }, setForm: () => {}, capture });
  act(() => { tick(); });
  rerender({ form: { customer_id: "cust_1" }, setForm: () => {}, capture });
  act(() => { tick(); });
  expect(draftKeyCount()).toBe(1);

  act(() => { capture.current.clearOnSuccess(); });
  expect(capture.current.banner).toBe(false);
  expect(draftKeyCount()).toBe(0);
});

// ─────────────────────────────────────────────────────────────────────────
// 3. Preserved guarantees (regression coverage)
// ─────────────────────────────────────────────────────────────────────────
test("Invoice-style New form: untouched mount → no draft, meaningful edit → silent persistence", () => {
  const capture = { current: null };
  const initial = {
    customerId: "",
    selected: {},
    rcm: true,
    hsnSac: "996791",
    invoiceDate: "2026-02-27",
    notes: "",
  };
  const { rerender } = mount({
    form: initial, setForm: () => {}, capture,
    route: "/invoices/new",
  });
  act(() => { tick(); });
  expect(draftKeyCount()).toBe(0);
  expect(capture.current.banner).toBe(false);

  rerender({
    form: { ...initial, rcm: false }, setForm: () => {}, capture,
    route: "/invoices/new",
  });
  act(() => { tick(); });
  expect(draftKeyCount()).toBe(1);
  expect(capture.current.banner).toBe(false); // still silent
});

test("Invoice EDIT route: no banner ever, even with a pre-planted draft", () => {
  const editKey = buildDraftKey({
    route: "/invoices/:id/edit", recordId: "inv_7",
    userId: "u-test", companyId: "c-test",
  });
  saveDraft(editKey, {
    route: "/invoices/:id/edit",
    form: { customerId: "cust_x" },
    userId: "u-test",
  });

  const capture = { current: null };
  mount({
    form: { customerId: "" }, setForm: () => {}, capture,
    route: "/invoices/:id/edit", recordId: "inv_7",
  });
  act(() => { tick(); });
  expect(capture.current.banner).toBe(false);
  expect(capture.current._isEditRoute).toBe(true);
});
