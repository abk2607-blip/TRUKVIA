const fs = require("fs");
const path = require("path");

const APP = "/app";
const sec = fs.readFileSync(path.join(APP, "frontend/src/components/BankAccountsSection.jsx"), "utf8");
const settings = fs.readFileSync(path.join(APP, "frontend/src/pages/Settings.jsx"), "utf8");
const suppliers = fs.readFileSync(path.join(APP, "frontend/src/pages/Suppliers.jsx"), "utf8");
const vendors = fs.readFileSync(path.join(APP, "frontend/src/pages/Vendors.jsx"), "utf8");
const customers = fs.readFileSync(path.join(APP, "frontend/src/pages/Customers.jsx"), "utf8");
const mechanics = fs.readFileSync(path.join(APP, "frontend/src/pages/Mechanics.jsx"), "utf8");
const drivers = fs.readFileSync(path.join(APP, "frontend/src/pages/Drivers.jsx"), "utf8");
const drawer = fs.readFileSync(path.join(APP, "frontend/src/components/PaymentDrawer.jsx"), "utf8");

describe("Iter150H2 · master-embedded BankAccountsSection", () => {
  test("Section testids · rows / add / setprimary / edit / replace / deactivate / reveal / form", () => {
    for (const tid of ["-add-btn", "-empty", "-row-", "-setprimary-", "-edit-", "-replace-", "-deactivate-", "-reveal-", "-form-save"]) {
      expect(sec).toContain(tid);
    }
    expect(sec).toContain("+ Add Another Bank Account");
    expect(sec).toContain("Primary");
    expect(sec).toContain("Save this record first");
  });
  test("Zero-account empty state renders", () => {
    expect(sec).toContain("No bank accounts yet");
  });
  test("Masked-only display · never full account_number in row", () => {
    expect(sec).toContain("r.masked_display || r.account_number");
    expect(sec).not.toMatch(/\.account_number\s*}\s*<\/div>/);
  });
  test("Reuses Iter150G endpoints only · no new route", () => {
    for (const ep of [
      "/company-bank-accounts", "/party-bank-accounts",
      "/set-primary", "/deactivate", "/replace", "/reveal",
    ]) expect(sec).toContain(ep);
    // Never a DELETE method
    expect(sec).not.toMatch(/api\.delete/);
  });
  test("Kind gating · disabled when partyId missing for party mode", () => {
    expect(sec).toContain('kind === "company"');
    expect(sec).toContain("bank-section-disabled");
  });

  test("Company master · Settings.jsx mounts <BankAccountsSection kind=\"company\" />", () => {
    expect(settings).toContain('import BankAccountsSection');
    expect(settings).toMatch(/BankAccountsSection\s+kind="company"/);
  });
  test("Supplier master · Suppliers.jsx mounts party section for supplier", () => {
    expect(suppliers).toContain('import BankAccountsSection');
    expect(suppliers).toMatch(/BankAccountsSection[\s\S]{0,80}partyType="supplier"/);
  });
  test("Vendor master · Vendors.jsx mounts party section for vendor", () => {
    expect(vendors).toContain('import BankAccountsSection');
    expect(vendors).toMatch(/BankAccountsSection[\s\S]{0,80}partyType="vendor"/);
  });
  test("Customer master · Customers.jsx mounts party section for customer", () => {
    expect(customers).toContain('import BankAccountsSection');
    expect(customers).toMatch(/BankAccountsSection[\s\S]{0,80}partyType="customer"/);
  });
  test("Mechanic master · Mechanics.jsx mounts party section for mechanic", () => {
    expect(mechanics).toContain('import BankAccountsSection');
    expect(mechanics).toMatch(/BankAccountsSection[\s\S]{0,80}partyType="mechanic"/);
  });
  test("Driver master · Drivers.jsx mounts party section for driver", () => {
    expect(drivers).toContain('import BankAccountsSection');
    expect(drivers).toMatch(/BankAccountsSection[\s\S]{0,80}partyType="driver"/);
  });

  test("Legacy scalar fields preserved on all 3 masters that historically had them", () => {
    expect(settings).toContain('data-testid="setting-bank"');
    expect(settings).toContain('data-testid="setting-account"');
    expect(suppliers).toMatch(/F\("bank_name", "Bank Name"\)/);
    expect(vendors).toContain('data-testid="vendor-bank-name"');
  });

  test("Iter150H payment source-bank preserved · no rollback", () => {
    expect(drawer).toContain('import CompanySourceBankSelector');
    expect(drawer).toContain("<CompanySourceBankSelector");
    expect(suppliers).toContain('import CompanySourceBankSelector');
    expect(suppliers).toContain("<CompanySourceBankSelector");
  });

  test("Forbidden patterns · zero provider / webhook / UTR / Maker-Checker / hard-delete leakage", () => {
    for (const src of [sec, settings, suppliers, vendors, customers, mechanics, drivers]) {
      for (const forbid of ["razorpay", "webhook", "hmac", "maker_checker", "PaymentInstruction"]) {
        expect(src.toLowerCase().includes(forbid.toLowerCase())).toBe(false);
      }
      expect(src).not.toMatch(/api\.delete\(\s*['"`]\/(company|party)-bank-accounts/);
    }
  });
});
