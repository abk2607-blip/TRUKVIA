/**
 * Iter127a UAT · DuplicateMasterModal + response parsers.
 * Pure JS unit tests — no React rendering (parsers are pure functions and
 * the modal is exercised in the Playwright flow separately).
 */
import {
  parseDuplicateError, parseVehicleDuplicateResponse,
} from "../components/DuplicateMasterModal";

// ── parseDuplicateError ────────────────────────────────────────────────────
test("parseDuplicateError extracts Iter127a 409 payload", () => {
  const err = { response: { status: 409, data: { detail: {
    detail: "Customer already exists.", code: "duplicate_master",
    matched_field: "gstin",
    existing: { id: "cust_1", name: "MEGHA", gstin: "37AB…" },
  } } } };
  const out = parseDuplicateError(err);
  expect(out).toBeTruthy();
  expect(out.matchedField).toBe("gstin");
  expect(out.existing.id).toBe("cust_1");
});

// Iter127a-UAT-fix v2 — critical regression guard for the LIVE bug:
// api.js response interceptor (Iter102) flattens `detail` to a plain string
// and stashes the original dict in `detail_raw`. Parser MUST still see the
// structured payload via `detail_raw` — otherwise the customer form falls
// through to the raw error toast instead of opening DuplicateMasterModal.
test("parseDuplicateError reads detail_raw after Iter102 flattening", () => {
  const err = { response: { status: 409, data: {
    detail: "Customer already exists.",   // ← flattened string
    detail_raw: {                          // ← original dict preserved here
      detail: "Customer already exists.",
      code: "duplicate_master",
      matched_field: "gstin",
      existing: { id: "cust_9", name: "MEGHA ENGINEERING", gstin: "37AABCM1234A1Z9", phone: "9199990001" },
    },
  } } };
  const out = parseDuplicateError(err);
  expect(out).toBeTruthy();
  expect(out.matchedField).toBe("gstin");
  expect(out.existing.id).toBe("cust_9");
  expect(out.existing.name).toBe("MEGHA ENGINEERING");
});

test("parseDuplicateError still ignores real 400/422/500 after flattening", () => {
  // A plain non-duplicate 400 — Iter102 flattens `detail` to a string and
  // does NOT populate `detail_raw` (or leaves it as the same string). The
  // parser must return null so the generic error toast fires.
  const err = { response: { status: 400, data: {
    detail: "Missing required field: name",
    detail_raw: "Missing required field: name",
  } } };
  expect(parseDuplicateError(err)).toBeNull();
});

test.each([
  ["status is 500", { response: { status: 500, data: { detail: {} } } }],
  ["status 409 but not duplicate_master", { response: { status: 409, data: { detail: { code: "other" } } } }],
  ["status 409 but detail is a string", { response: { status: 409, data: { detail: "bad request" } } }],
  ["no response", { message: "network" }],
  ["null / undefined", null],
])("parseDuplicateError returns null when %s", (_label, err) => {
  expect(parseDuplicateError(err)).toBeNull();
});

// ── parseVehicleDuplicateResponse ──────────────────────────────────────────
test("parseVehicleDuplicateResponse extracts Iter72/127a duplicate:true body", () => {
  const body = { id: "veh_1", vehicle_number: "AP27TT6008", duplicate: true, matched_field: "vehicle_number" };
  const out = parseVehicleDuplicateResponse(body);
  expect(out).toBeTruthy();
  expect(out.existing.vehicle_number).toBe("AP27TT6008");
  expect(out.matchedField).toBe("vehicle_number");
});

test("parseVehicleDuplicateResponse returns null when duplicate flag absent", () => {
  expect(parseVehicleDuplicateResponse({ id: "veh_1", vehicle_number: "AP27TT6008" })).toBeNull();
  expect(parseVehicleDuplicateResponse(null)).toBeNull();
});
