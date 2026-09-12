const fs = require("fs");
const path = require("path");

const APP = "/app";
const sel = fs.readFileSync(path.join(APP, "frontend/src/components/CompanySourceBankSelector.jsx"), "utf8");
const drawer = fs.readFileSync(path.join(APP, "frontend/src/components/PaymentDrawer.jsx"), "utf8");
const suppliers = fs.readFileSync(path.join(APP, "frontend/src/pages/Suppliers.jsx"), "utf8");

describe("Iter150H · Company Source Bank shell", () => {
  test("Selector data-testid + zero-account fallback + masked-only render", () => {
    expect(sel).toContain('data-testid="company-source-bank-selector"');
    expect(sel).toContain('data-testid="company-source-bank-empty"');
    expect(sel).toContain("— No company bank account —");
    expect(sel).toContain("r.masked_display || r.account_number");
    // must not render raw account_number without masked_display fallback
    expect(sel).not.toMatch(/account_number}\s*<\/option>/);
  });

  test("Selector defaults to primary active company bank", () => {
    expect(sel).toContain("r.is_primary");
    expect(sel).toContain("active.find((r) => r.is_primary)");
  });

  test("Selector filters inactive/replaced accounts", () => {
    expect(sel).toContain("(data || []).filter((r) => r.is_active)");
  });

  test("Selector fetches from Iter150G endpoint /company-bank-accounts", () => {
    expect(sel).toContain("/company-bank-accounts");
  });

  test("PaymentDrawer imports + wires selector into vendor/mechanic flow", () => {
    expect(drawer).toContain('import CompanySourceBankSelector');
    expect(drawer).toContain("<CompanySourceBankSelector");
    expect(drawer).toContain("company_bank_account_id: \"\"");
    expect(drawer).toContain("if (form.company_bank_account_id) body.company_bank_account_id = form.company_bank_account_id");
  });

  test("Suppliers.jsx imports + wires selector into supplier payment flow", () => {
    expect(suppliers).toContain('import CompanySourceBankSelector');
    expect(suppliers).toContain("<CompanySourceBankSelector");
    expect(suppliers).toContain("company_bank_account_id: \"\"");
  });

  test("No provider / adapter / webhook / UTR / Maker-Checker leakage", () => {
    for (const src of [sel, drawer, suppliers]) {
      for (const forbid of ["razorpay", "Razorpay", "webhook", "hmac", "maker_checker", "PaymentInstruction"]) {
        expect(src.toLowerCase().includes(forbid.toLowerCase())).toBe(false);
      }
    }
  });

  test("Palette guard — no forbidden libraries", () => {
    for (const src of [sel]) {
      for (const forbid of ["framer-motion", "react-i18next", "purple-", "violet-", "indigo-"]) {
        expect(src.includes(forbid)).toBe(false);
      }
    }
  });
});
