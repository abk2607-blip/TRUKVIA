/**
 * Iter126c · Frontend jest tests for the form-draft library.
 * Focus: sanitisation, storage lifecycle, key rotation. NO React rendering
 * (Playwright covers the browser-level flow).
 */
import {
  sanitizeDraft,
  buildDraftKey,
  loadDraft,
  saveDraft,
  clearDraft,
  wipeAllDrafts,
  chooseSaveKey,
  humanAge,
  DRAFT_KEY_PREFIX,
  STALE_MS,
} from "../lib/formDraft";

// jsdom lacks crypto.randomUUID.
let _n = 0;
if (!globalThis.crypto) globalThis.crypto = {};
if (!globalThis.crypto.randomUUID) {
  globalThis.crypto.randomUUID = () => `test-uuid-${(_n += 1).toString().padStart(12, "0")}`;
}

beforeEach(() => sessionStorage.clear());

describe("Iter126c · sanitizeDraft strips sensitive fields", () => {
  test.each([
    "password", "PASSWORD", "otp", "user_otp", "session_token",
    "session", "api_key", "apiKey", "secret", "photo", "photo_data_url",
    "signature_data_url", "cvv", "card_number", "bank_account_no",
    "upi_id", "cheque_no", "ref_no", "ifsc", "account_no",
  ])("drops key %s", (k) => {
    const out = sanitizeDraft({ [k]: "leak", customer_id: "cust_1" });
    expect(out).not.toHaveProperty(k);
    expect(out.customer_id).toBe("cust_1");
  });

  test("strips base64 data:image previews from ANY key", () => {
    const out = sanitizeDraft({
      customer_id: "cust_1",
      logo_preview: "data:image/png;base64,iVBOR…",
    });
    expect(out.logo_preview).toBe("");
    expect(out.customer_id).toBe("cust_1");
  });

  test("truncates long strings > 2 KB", () => {
    const long = "x".repeat(5000);
    const out = sanitizeDraft({ notes: long });
    expect(out.notes.length).toBe(2048);
  });

  test("handles nested objects, arrays, cycles", () => {
    const cyclic = { a: 1 };
    cyclic.self = cyclic;
    const out = sanitizeDraft({
      customer_id: "c",
      lines: [{ id: 1, password: "x", amt: 500 }],
      cyclic,
    });
    expect(out.lines[0]).toEqual({ id: 1, amt: 500 });
    expect(out.customer_id).toBe("c");
    expect(out.cyclic.a).toBe(1);
  });

  test("File/Blob replaced with placeholder", () => {
    const f = new File(["hi"], "report.pdf");
    const out = sanitizeDraft({ upload: f });
    expect(out.upload).toBe("<file: report.pdf>");
  });
});

describe("Iter126c · buildDraftKey composition", () => {
  test("stable across identical inputs", () => {
    const k1 = buildDraftKey({ route: "/trips/new", userId: "u1", companyId: "c1" });
    const k2 = buildDraftKey({ route: "/trips/new", userId: "u1", companyId: "c1" });
    expect(k1).toBe(k2);
    expect(k1.startsWith(DRAFT_KEY_PREFIX)).toBe(true);
  });
  test("edit route embeds recordId", () => {
    const k = buildDraftKey({ route: "/trips/:id/edit", recordId: "trp_1", userId: "u1", companyId: "c1" });
    expect(k).toContain("trp_1");
  });
  test("different company → different key", () => {
    const k1 = buildDraftKey({ route: "/trips/new", userId: "u1", companyId: "c1" });
    const k2 = buildDraftKey({ route: "/trips/new", userId: "u1", companyId: "c2" });
    expect(k1).not.toBe(k2);
  });
  test("different user → different key", () => {
    const k1 = buildDraftKey({ route: "/trips/new", userId: "u1", companyId: "c1" });
    const k2 = buildDraftKey({ route: "/trips/new", userId: "u2", companyId: "c1" });
    expect(k1).not.toBe(k2);
  });
});

describe("Iter126c · save/load/clear lifecycle", () => {
  const KEY = buildDraftKey({ route: "/trips/new", userId: "u1", companyId: "c1" });

  test("save then load returns the same buffer", () => {
    saveDraft(KEY, { route: "/trips/new", form: { customer_id: "cust_x", tons: 15 }, userId: "u1" });
    const d = loadDraft(KEY, { userId: "u1" });
    expect(d.form.customer_id).toBe("cust_x");
    expect(d.form.tons).toBe(15);
  });

  test("load returns null for other user (isolation)", () => {
    saveDraft(KEY, { route: "/trips/new", form: { customer_id: "x" }, userId: "u1" });
    const d = loadDraft(KEY, { userId: "u2" });
    expect(d).toBeNull();
  });

  test("clearDraft removes the entry", () => {
    saveDraft(KEY, { route: "/trips/new", form: { x: 1 }, userId: "u1" });
    clearDraft(KEY);
    expect(loadDraft(KEY, { userId: "u1" })).toBeNull();
  });

  test("stale draft (>24h) returns null and is treated as absent", () => {
    saveDraft(KEY, { route: "/trips/new", form: { x: 1 }, userId: "u1" });
    const raw = JSON.parse(sessionStorage.getItem(KEY));
    raw.updated_at = Date.now() - STALE_MS - 1000;
    sessionStorage.setItem(KEY, JSON.stringify(raw));
    expect(loadDraft(KEY, { userId: "u1" })).toBeNull();
  });

  test("wipeAllDrafts removes every iter126c: key and only those", () => {
    saveDraft(buildDraftKey({ route: "/trips/new", userId: "u1", companyId: "c1" }),
      { route: "/trips/new", form: { a: 1 }, userId: "u1" });
    saveDraft(buildDraftKey({ route: "/invoices/new", userId: "u1", companyId: "c1" }),
      { route: "/invoices/new", form: { a: 2 }, userId: "u1" });
    sessionStorage.setItem("some-other-key", "keep-me");
    const wiped = wipeAllDrafts();
    expect(wiped).toBe(2);
    expect(sessionStorage.getItem("some-other-key")).toBe("keep-me");
  });
});

describe("Iter126c · chooseSaveKey rotates on material change, reuses on retry", () => {
  test("no prior save → mint fresh key", () => {
    const r = chooseSaveKey(null, { customer_id: "x" });
    expect(r.minted).toBe(true);
    expect(r.key).toEqual(expect.any(String));
  });

  test("same form as last save → reuse key (retry)", () => {
    const first = chooseSaveKey({ saved_sha: null, idempotency_key: "old" }, { customer_id: "x" });
    const persisted = { saved_sha: first.sha, idempotency_key: first.key };
    const retry = chooseSaveKey(persisted, { customer_id: "x" });
    expect(retry.minted).toBe(false);
    expect(retry.key).toBe(first.key);
  });

  test("material change → mint new key", () => {
    const first = chooseSaveKey(null, { customer_id: "x", tons: 10 });
    const persisted = { saved_sha: first.sha, idempotency_key: first.key };
    const changed = chooseSaveKey(persisted, { customer_id: "x", tons: 11 });
    expect(changed.minted).toBe(true);
    expect(changed.key).not.toBe(first.key);
  });
});

test("Iter126c · humanAge produces friendly relative strings", () => {
  const now = 1_700_000_000_000;
  expect(humanAge(now - 5 * 1000, now)).toBe("5 seconds ago");
  expect(humanAge(now - 60 * 1000, now)).toBe("1 minute ago");
  expect(humanAge(now - 3 * 3600 * 1000, now)).toBe("3 hours ago");
  expect(humanAge(now - 3 * 86400 * 1000, now)).toBe("3 days ago");
});
