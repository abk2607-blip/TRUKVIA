const fs = require("fs");
const path = require("path");

const DRAWER = fs.readFileSync(
  path.join(__dirname, "..", "components", "DriverPaymentDrawer.jsx"), "utf8");
const DRIVERS = fs.readFileSync(
  path.join(__dirname, "..", "pages", "Drivers.jsx"), "utf8");
const PAYMENT_DRAWER = fs.readFileSync(
  path.join(__dirname, "..", "components", "PaymentDrawer.jsx"), "utf8");

describe("Iter150I · DriverPaymentDrawer shell", () => {
  test("component file present with required testids", () => {
    for (const t of ["driver-payment-drawer","dpd-close","dpd-date","dpd-amount",
                     "dpd-mode","dpd-against","dpd-ref","dpd-remarks",
                     "dpd-beneficiary-bank","dpd-source-bank",
                     "dpd-record-btn"]) {
      expect(DRAWER).toContain(`data-testid="${t}"`);
    }
  });

  test("against enum exactly the confirmed 4 values", () => {
    expect(DRAWER).toMatch(/const AGAINST = \["advance", "salary_settlement", "reimbursement", "other"\]/);
  });

  test("mode enum has all 8 confirmed values", () => {
    expect(DRAWER).toMatch(/const MODES = \["Cash", "Bank", "UPI", "IMPS", "NEFT", "RTGS", "Cheque", "Other"\]/);
  });

  test("cash mode suppresses bank selectors", () => {
    expect(DRAWER).toMatch(/isCash\s*&&/);
    expect(DRAWER).toMatch(/!isCash\s*&&/);
  });

  test("salary-settlement advisory testid present (warning only)", () => {
    expect(DRAWER).toContain(`data-testid="dpd-salary-advisory"`);
  });

  test("posts to /drivers/{did}/payments (Iter150I contract)", () => {
    expect(DRAWER).toMatch(/\/drivers\/\$\{driverId\}\/payments/);
  });

  test("reuses existing CompanySourceBankSelector (Iter150H component)", () => {
    expect(DRAWER).toMatch(/import CompanySourceBankSelector from ["']\.\/CompanySourceBankSelector["']/);
  });

  test("does NOT duplicate shared PaymentDrawer logic", () => {
    expect(DRAWER).not.toMatch(/partyType:.*"vendor".*"mechanic"/);
    // PaymentDrawer itself is untouched (0-diff invariant)
    expect(PAYMENT_DRAWER).toMatch(/partyType:\s*"vendor"\s*\|\s*"mechanic"/);
  });

  test("invalidates driver-payments + driver-ledger queries on success", () => {
    expect(DRAWER).toMatch(/queryKey:\s*\["driver-payments"/);
    expect(DRAWER).toMatch(/queryKey:\s*\["driver-ledger"/);
  });

  test("Driver master page mounts the drawer via a Payments action", () => {
    expect(DRIVERS).toContain("DriverPaymentDrawer");
    expect(DRIVERS).toMatch(/data-testid=\{`payments-driver-\$\{[^}]+\}`\}|data-testid="driver-payments-btn"/);
  });
});
