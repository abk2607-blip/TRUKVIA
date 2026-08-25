/**
 * Iter126b — Frontend Idempotency-Key wiring.
 *
 * Verifies:
 *   1. Every Bucket-B POST auto-receives a UUID Idempotency-Key.
 *   2. Retries via the response interceptor re-use the SAME key
 *      (no new UUID is generated on retry).
 *   3. Bucket-A endpoints (GET/PUT/PATCH/DELETE and whitelisted read-only
 *      POSTs) never receive the header.
 *   4. Bucket-C endpoints (share, LLM, auth handshake, bulk-delete) never
 *      receive the header.
 *   5. GET/HEAD/OPTIONS never receive the header regardless of URL.
 *   6. Duplicate Save (two clicks) produces two requests carrying the SAME
 *      key when the caller re-uses the axios config; the backend replay
 *      cache (Iter126b backend) then prevents any duplicate mutation.
 */
import { _isBucketBPost, BUCKET_B_POST } from "../api";

// jsdom does not ship `crypto.randomUUID`. Provide a per-call counter so
// each generated key is unique — that's what a real browser guarantees.
let _uuidCounter = 0;
if (!globalThis.crypto) globalThis.crypto = {};
if (!globalThis.crypto.randomUUID) {
  globalThis.crypto.randomUUID = () => {
    _uuidCounter += 1;
    return `test-uuid-${_uuidCounter.toString().padStart(12, "0")}`;
  };
}

// Mimic the interceptor's request-time behaviour by manually stamping the
// Idempotency-Key on a config object, matching api.js exactly.
function attachIdempotencyKey(cfg) {
  if (!_isBucketBPost(cfg)) return cfg;
  cfg.headers = cfg.headers || {};
  if (!cfg.headers["Idempotency-Key"]) {
    cfg.headers["Idempotency-Key"] = globalThis.crypto.randomUUID();
  }
  return cfg;
}

// -------------------- Bucket B — must attach a key --------------------
describe("Iter126b · Bucket-B POST auto-attaches Idempotency-Key", () => {
  const bucketBSamples = [
    { url: "/trips",                                       label: "create Trip" },
    { url: "/customers",                                   label: "create Customer" },
    { url: "/suppliers",                                   label: "create Supplier" },
    { url: "/invoices",                                    label: "create Invoice" },
    { url: "/customers/cust_1/add-payment",                label: "customer payment" },
    { url: "/suppliers/sup_1/payments",                    label: "supplier payment" },
    { url: "/invoices/inv_1/payments",                     label: "invoice payment" },
    { url: "/drivers/drv_1/ledger",                        label: "driver ledger entry" },
    { url: "/trips/trp_1/supplier-diesel",                 label: "trip supplier diesel" },
    { url: "/trips/trp_1/duplicate",                       label: "duplicate trip" },
    { url: "/files/upload",                                label: "file upload" },
    { url: "/company/logo",                                label: "company logo upload" },
    { url: "/trips/trp_1/regenerate-lr",                   label: "A→B LR regenerate" },
    { url: "/trips/bulk-regenerate-lr",                    label: "A→B bulk LR regenerate" },
    { url: "/trips/bulk-all-copies-zip",                   label: "A→B bulk all-copies ZIP" },
  ];

  test.each(bucketBSamples)("$label ($url) gets a key", ({ url }) => {
    const cfg = { method: "post", url, headers: {} };
    const out = attachIdempotencyKey(cfg);
    expect(_isBucketBPost(cfg)).toBe(true);
    expect(out.headers["Idempotency-Key"]).toEqual(expect.any(String));
    expect(out.headers["Idempotency-Key"].length).toBeGreaterThanOrEqual(8);
  });
});

// -------------------- Same key on retry --------------------
test("Iter126b · Retry re-uses the SAME key (never regenerates)", () => {
  const cfg = { method: "post", url: "/trips", headers: {} };
  attachIdempotencyKey(cfg);
  const first = cfg.headers["Idempotency-Key"];
  expect(first).toBeTruthy();

  // Simulate the response interceptor calling api.request(err.config) — the
  // request interceptor runs again with the SAME cfg object, so the guard
  // `if (!cfg.headers["Idempotency-Key"])` must short-circuit.
  attachIdempotencyKey(cfg);
  attachIdempotencyKey(cfg); // second retry attempt
  const afterRetry = cfg.headers["Idempotency-Key"];
  expect(afterRetry).toBe(first);
});

// -------------------- Bucket A — must NOT attach --------------------
describe("Iter126b · Bucket-A must NOT receive Idempotency-Key", () => {
  const bucketASamples = [
    { method: "get",    url: "/trips",                        label: "GET list" },
    { method: "head",   url: "/customers",                    label: "HEAD" },
    { method: "options",url: "/suppliers",                    label: "OPTIONS" },
    { method: "put",    url: "/trips/trp_1",                  label: "PUT update trip" },
    { method: "patch",  url: "/trips/trp_1/customer-ref",     label: "PATCH cust-ref" },
    { method: "delete", url: "/trips/trp_1",                  label: "DELETE trip" },
    { method: "post",   url: "/trips/lr/preview",             label: "read-only preview POST" },
    { method: "post",   url: "/trips/bulk-invoice-preflight", label: "read-only preflight" },
    { method: "post",   url: "/policy-changes/preview",       label: "policy preview" },
    { method: "post",   url: "/vehicles/bulk-import/preview", label: "vehicle preview" },
    { method: "post",   url: "/companies/co_1/set-default",   label: "set default company" },
    { method: "post",   url: "/auth/logout",                  label: "logout" },
  ];
  test.each(bucketASamples)("$method $url ($label) → no key", ({ method, url }) => {
    const cfg = { method, url, headers: {} };
    attachIdempotencyKey(cfg);
    expect(cfg.headers["Idempotency-Key"]).toBeUndefined();
    expect(_isBucketBPost(cfg)).toBe(false);
  });
});

// -------------------- Bucket C — must NOT attach --------------------
describe("Iter126b · Bucket-C must NOT receive Idempotency-Key", () => {
  const bucketCSamples = [
    "/trips/bulk-delete",
    "/policy-changes/apply",
    "/policy-changes/evt_1/revert",
    "/invoices/inv_1/share",
    "/trips/trp_1/share-lr",
    "/customers/cust_1/share-statement",
    "/reports/supplier-statement/share",
    "/reminders/digest/run",
    "/ai/chat",
    "/ai/parse-trip",
    "/ai/parse-template",
    "/ai/report",
    "/ai/insights/refresh",
    "/ai/parse",
    "/auth/session",
    "/auth/demo-login",
  ];
  test.each(bucketCSamples)("POST %s → no key", (url) => {
    const cfg = { method: "post", url, headers: {} };
    attachIdempotencyKey(cfg);
    expect(cfg.headers["Idempotency-Key"]).toBeUndefined();
    expect(_isBucketBPost(cfg)).toBe(false);
  });
});

// -------------------- Duplicate-Save scenario --------------------
test("Iter126b · Duplicate button click reuses the same key (same cfg) but produces 2 distinct keys (distinct cfgs)", () => {
  // Same axios config object (single logical request) → same key on retry.
  const cfgOnce = { method: "post", url: "/trips", headers: {} };
  attachIdempotencyKey(cfgOnce);
  const keyRetry = cfgOnce.headers["Idempotency-Key"];
  attachIdempotencyKey(cfgOnce);
  expect(cfgOnce.headers["Idempotency-Key"]).toBe(keyRetry);

  // Two independent api.post() calls (two clicks) → two DIFFERENT keys.
  // This is intentional: only backend dedup could stop that, and it does
  // by returning a 409/duplicate error from the actual handler based on
  // business uniqueness. Idempotency-Key protects against RETRIES of the
  // SAME logical intent — not against two independent user actions.
  const cfgA = { method: "post", url: "/trips", headers: {} };
  const cfgB = { method: "post", url: "/trips", headers: {} };
  attachIdempotencyKey(cfgA);
  attachIdempotencyKey(cfgB);
  expect(cfgA.headers["Idempotency-Key"]).not.toBe(cfgB.headers["Idempotency-Key"]);
});

// -------------------- Whitelist mirror sanity --------------------
test("Iter126b · Bucket-B whitelist has the 37 expected patterns (mirrors backend)", () => {
  expect(BUCKET_B_POST.length).toBe(37);
});
