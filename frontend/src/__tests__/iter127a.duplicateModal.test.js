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
