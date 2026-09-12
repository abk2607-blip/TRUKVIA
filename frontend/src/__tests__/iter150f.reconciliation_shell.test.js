const fs = require("fs");
const path = require("path");

const APP = "/app";
const layout = fs.readFileSync(path.join(APP, "frontend/src/components/Layout.jsx"), "utf8");
const appJs = fs.readFileSync(path.join(APP, "frontend/src/App.js"), "utf8");
const page = fs.readFileSync(path.join(APP, "frontend/src/pages/FinReconciliation.jsx"), "utf8");

const EXISTING_27 = [
  "nav-dashboard","nav-trips","nav-templates","nav-customers","nav-customer-history",
  "nav-suppliers","nav-parties","nav-vehicles","nav-vendors","nav-mechanics",
  "nav-drivers","nav-shortage-policies","nav-products","nav-fuel","nav-expenses",
  "nav-quick-expense","nav-invoices","nav-overdue","nav-notes","nav-reports",
  "nav-files","nav-team","nav-audit","nav-settings",
  "nav-fin-day-book","nav-fin-accounts","nav-fin-day-closing",
];
const NEW_PAGE_TESTIDS = [
  "recon-page","recon-kpi-a","recon-kpi-b","recon-kpi-c","recon-kpi-d",
  "recon-kpi-e","recon-kpi-f","recon-kpi-g","recon-kpi-h",
  "recon-tab-source-fintxn","recon-tab-balances","recon-tab-wallets",
  "recon-tab-payables","recon-tab-projection-health","recon-tab-day-closings",
  "recon-mismatch-table","recon-mismatch-row","recon-detail-drawer",
  "recon-rebuild-btn","recon-empty-state",
];

describe("Iter150F · Reconciliation shell", () => {
  test("Financials nav item added with correct testid + path", () => {
    expect(layout).toContain('testid: "nav-fin-reconciliation"');
    expect(layout).toContain('to: "/fin/reconciliation"');
  });
  test("All 27 existing Iter150E nav testids preserved verbatim", () => {
    for (const t of EXISTING_27) expect(layout).toContain(`testid: "${t}"`);
  });
  test("Exactly 28 unique nav testids after Iter150F (27 + 1)", () => {
    const matches = layout.match(/testid:\s*"nav-[a-z-]+"/g) || [];
    const unique = new Set(matches);
    expect(unique.size).toBe(EXISTING_27.length + 1);
  });
  test("App.js registers /fin/reconciliation route", () => {
    expect(appJs).toMatch(/path="\/fin\/reconciliation"[\s\S]*FinReconciliation/);
  });
  test("Page declares all 20 authorised testids (dynamic or literal)", () => {
    // KPI and tab testids are built via template strings; assert either literal or template pattern.
    const check = (t) => page.includes(`data-testid="${t}"`)
      || page.includes(`recon-kpi-${'${'}`) && t.startsWith("recon-kpi-")
      || page.includes(`recon-tab-${'${'}`) && t.startsWith("recon-tab-");
    for (const t of NEW_PAGE_TESTIDS) expect(check(t)).toBe(true);
    // The two template roots must exist so the KPI/tab loops render.
    expect(page).toMatch(/data-testid=\{`recon-kpi-\$\{/);
    expect(page).toMatch(/data-testid=\{`recon-tab-\$\{/);
  });
  test("Frozen BD-5 amber banner copy present verbatim", () => {
    expect(page).toContain("Day Closing snapshots do not auto-refresh after late entries. Reopen the day to re-close if you want the snapshot updated.");
  });
  test("Empty-state copy present", () => {
    expect(page).toContain("Everything reconciles cleanly.");
  });
  test("Ember #FD7800 only used, no forbidden palette / motion / i18n", () => {
    for (const forbid of ["framer-motion", "react-i18next", "purple-", "violet-", "indigo-"]) {
      expect(page.includes(forbid)).toBe(false);
    }
    // Rebuild CTA uses ember focus.
    expect(page).toContain("#FD7800");
  });
});
