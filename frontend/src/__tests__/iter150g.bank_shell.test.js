const fs = require("fs");
const path = require("path");

const APP = "/app";
const layout = fs.readFileSync(path.join(APP, "frontend/src/components/Layout.jsx"), "utf8");
const appJs = fs.readFileSync(path.join(APP, "frontend/src/App.js"), "utf8");
const cba = fs.readFileSync(path.join(APP, "frontend/src/pages/CompanyBankAccounts.jsx"), "utf8");
const pba = fs.readFileSync(path.join(APP, "frontend/src/pages/PartyBankAccounts.jsx"), "utf8");
const sel = fs.readFileSync(path.join(APP, "frontend/src/components/BankAccountSelector.jsx"), "utf8");

const EXISTING_28 = [
  "nav-dashboard","nav-trips","nav-templates","nav-customers","nav-customer-history",
  "nav-suppliers","nav-parties","nav-vehicles","nav-vendors","nav-mechanics",
  "nav-drivers","nav-shortage-policies","nav-products","nav-fuel","nav-expenses",
  "nav-quick-expense","nav-invoices","nav-overdue","nav-notes","nav-reports",
  "nav-files","nav-team","nav-audit","nav-settings",
  "nav-fin-day-book","nav-fin-accounts","nav-fin-day-closing","nav-fin-reconciliation",
];

describe("Iter150G · Bank Account shell", () => {
  test("nav-fin-company-bank-accounts added with correct path", () => {
    expect(layout).toContain('testid: "nav-fin-company-bank-accounts"');
    expect(layout).toContain('to: "/fin/company-bank-accounts"');
  });
  test("All 28 Iter150F nav testids preserved verbatim", () => {
    for (const t of EXISTING_28) expect(layout).toContain(`testid: "${t}"`);
  });
  test("Exactly 29 unique nav testids after Iter150G (28 + 1)", () => {
    const matches = layout.match(/testid:\s*"nav-[a-z-]+"/g) || [];
    expect(new Set(matches).size).toBe(EXISTING_28.length + 1);
  });
  test("App.js registers Iter150G routes + imports", () => {
    expect(appJs).toContain('import CompanyBankAccounts');
    expect(appJs).toContain('import PartyBankAccounts');
    expect(appJs).toMatch(/path="\/fin\/company-bank-accounts"/);
    expect(appJs).toMatch(/path="\/party-bank-accounts\/:partyType\/:partyId"/);
  });
  test("Company page carries authorised testids", () => {
    for (const t of ["company-bank-accounts-page", "add-bank-btn", "masked-account-number"]) {
      expect(cba).toContain(`data-testid="${t}"`);
    }
  });
  test("Party page carries authorised testids", () => {
    for (const t of ["party-bank-accounts-page", "add-party-bank-btn",
                     "add-party-bank-form", "save-party-bank-btn",
                     "party-bank-row", "masked-account-number"]) {
      expect(pba).toContain(`data-testid="${t}"`);
    }
  });
  test("Bank selector renders masked-only + primary default hook", () => {
    expect(sel).toContain('data-testid="bank-account-selector"');
    expect(sel).toContain('r.masked_display || r.account_number');
    expect(sel).toContain('r.is_primary');
    // No display of raw account number without mask
    expect(sel).not.toMatch(/account_number}\s*<\/option>/);
  });
  test("Palette guard — ember #FD7800 only, no forbidden libraries", () => {
    for (const src of [cba, pba, sel]) {
      for (const forbid of ["framer-motion", "react-i18next", "purple-", "violet-", "indigo-"]) {
        expect(src.includes(forbid)).toBe(false);
      }
    }
    expect(cba).toContain("#FD7800");
    expect(pba).toContain("#FD7800");
  });
});
