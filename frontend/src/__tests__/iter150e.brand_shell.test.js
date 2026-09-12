/**
 * Iter150E · TRUKVIA brand-shell frontend shape tests (Jest static
 * scan — no DOM render).  Assertions:
 *
 *   1. Layout.jsx renders exactly 5 sidebar sections in this order:
 *      Masters / Operations / Financials / Reports / System
 *   2. All 24 existing nav testids are preserved verbatim.
 *   3. Exactly 3 new authorised Financials testids are present:
 *      nav-fin-day-book · nav-fin-accounts · nav-fin-day-closing
 *   4. App.js registers the /fin/accounts → /fin/accounts/BANK_DEFAULT
 *      replace-navigation redirect.
 *   5. index.html contains the frozen TRUKVIA title, ember theme-color
 *      #FD7800, and the favicon chain.
 *   6. manifest.json is the frozen TRUKVIA metadata.
 *   7. Login.jsx carries the login-brand-mark testid and #FD7800
 *      ember accent.
 *   8. index.css declares the frozen brand tokens.
 *   9. Copy hygiene: sidebar brand copy is "TRUKVIA / అకౌంటింగ్ ·
 *      Accounting Suite" (Bitumen Transport removed from the sidebar
 *      lockup; HTML title unchanged).
 */
const fs = require("fs");
const path = require("path");

const APP = "/app";
const layoutPath = path.join(APP, "frontend/src/components/Layout.jsx");
const appJsPath = path.join(APP, "frontend/src/App.js");
const indexHtml = path.join(APP, "frontend/public/index.html");
const manifest = path.join(APP, "frontend/public/manifest.json");
const loginPath = path.join(APP, "frontend/src/pages/Login.jsx");
const indexCss = path.join(APP, "frontend/src/index.css");

const layout = fs.readFileSync(layoutPath, "utf8");
const appJs = fs.readFileSync(appJsPath, "utf8");
const html = fs.readFileSync(indexHtml, "utf8");
const manifestJson = JSON.parse(fs.readFileSync(manifest, "utf8"));
const login = fs.readFileSync(loginPath, "utf8");
const css = fs.readFileSync(indexCss, "utf8");

const EXISTING_TESTIDS = [
  "nav-dashboard",
  "nav-trips",
  "nav-templates",
  "nav-customers",
  "nav-customer-history",
  "nav-suppliers",
  "nav-parties",
  "nav-vehicles",
  "nav-vendors",
  "nav-mechanics",
  "nav-drivers",
  "nav-shortage-policies",
  "nav-products",
  "nav-fuel",
  "nav-expenses",
  "nav-quick-expense",
  "nav-invoices",
  "nav-overdue",
  "nav-notes",
  "nav-reports",
  "nav-files",
  "nav-team",
  "nav-audit",
  "nav-settings",
];
const NEW_FINANCIALS_TESTIDS = [
  "nav-fin-day-book",
  "nav-fin-accounts",
  "nav-fin-day-closing",
];
const SECTION_ORDER = ["Masters", "Operations", "Financials", "Reports", "System"];

describe("Iter150E · TRUKVIA brand shell (frontend shape)", () => {
  test("Sidebar declares exactly the 5 authorised sections in order", () => {
    const labels = SECTION_ORDER.map((s) => layout.indexOf(`label: "${s}"`));
    labels.forEach((idx, i) => {
      expect(idx).toBeGreaterThan(-1);
      if (i > 0) expect(idx).toBeGreaterThan(labels[i - 1]);
    });
    // Section testids present.
    for (const key of ["masters", "operations", "financials", "reports", "system"]) {
      expect(layout).toContain(`sidebar-section-${key}`);
    }
  });

  test("All 24 existing nav testids are preserved verbatim", () => {
    expect(EXISTING_TESTIDS.length).toBe(24);
    for (const tid of EXISTING_TESTIDS) {
      expect(layout).toContain(`testid: "${tid}"`);
    }
  });

  test("Exactly 3 new Financials nav testids are added", () => {
    for (const tid of NEW_FINANCIALS_TESTIDS) {
      expect(layout).toContain(`testid: "${tid}"`);
    }
    // Guard against accidental extra nav additions.
    const allTestidMatches = layout.match(/testid:\s*"nav-[a-z-]+"/g) || [];
    const unique = new Set(allTestidMatches);
    expect(unique.size).toBe(EXISTING_TESTIDS.length + NEW_FINANCIALS_TESTIDS.length);
  });

  test("App.js registers the /fin/accounts → BANK_DEFAULT redirect (replace nav)", () => {
    expect(appJs).toMatch(/path="\/fin\/accounts"[\s\S]*Navigate[\s\S]*BANK_DEFAULT[\s\S]*replace/);
    // Existing :code route retained.
    expect(appJs).toContain('path="/fin/accounts/:code"');
    // Existing 24 route paths preserved (spot-check a few).
    expect(appJs).toContain('path="/dashboard"');
    expect(appJs).toContain('path="/invoices"');
    expect(appJs).toContain('path="/fin/day-book"');
    expect(appJs).toContain('path="/fin/day-closing"');
  });

  test("index.html has TRUKVIA title, ember theme-color and favicon chain", () => {
    expect(html).toContain("<title>TRUKVIA · Bitumen Transport ERP</title>");
    expect(html).toContain('theme-color" content="#FD7800"');
    expect(html).toContain("/brand/favicon.ico");
    expect(html).toContain("/brand/favicon-16.png");
    expect(html).toContain("/brand/favicon-32.png");
    expect(html).toContain("/brand/apple-touch-icon-180.png");
    expect(html).toContain('href="%PUBLIC_URL%/manifest.json"');
    expect(html).toContain("TRUKVIA — bitumen transport ERP");
  });

  test("manifest.json is the frozen TRUKVIA metadata", () => {
    expect(manifestJson.short_name).toBe("TRUKVIA");
    expect(manifestJson.name).toBe("TRUKVIA · Bitumen Transport ERP");
    expect(manifestJson.theme_color).toBe("#FD7800");
    expect(manifestJson.background_color).toBe("#f4f4f5");
    const iconSizes = manifestJson.icons.map((i) => i.sizes).sort();
    expect(iconSizes).toEqual(["16x16", "192x192", "32x32", "512x512"]);
  });

  test("Login.jsx carries the login-brand-mark testid + ember accent", () => {
    expect(login).toContain('data-testid="login-brand-mark"');
    expect(login).toContain("#FD7800");
    expect(login).toContain("/brand/trukvia-login-mark.png");
    // Auth logic sentinel — google-login-button preserved untouched.
    expect(login).toContain('data-testid="google-login-button"');
    expect(login).toContain("auth.emergentagent.com");
  });

  test("index.css declares the frozen brand tokens", () => {
    expect(css).toContain("--brand: 28 100% 50%");
    expect(css).toContain("--brand-foreground: 0 0% 100%");
    expect(css).toContain("--brand-muted: 28 100% 94%");
    expect(css).toContain("--brand-ring: 28 100% 50%");
    expect(css).toContain("--brand-ink: 20 80% 22%");
    expect(css).toContain("--brand-navy: 216 98% 20%");
    // Zinc foundation retained.
    expect(css).toContain("--foreground: 240 6% 6%");
    expect(css).toContain("--background: 0 0% 96%");
  });

  test("Copy hygiene: sidebar lockup uses TRUKVIA + Accounting Suite", () => {
    expect(layout).toContain("TRUKVIA");
    expect(layout).toContain("Accounting Suite");
    // Bitumen Transport lock-up removed from the sidebar/mobile chrome.
    expect(layout).not.toMatch(/>\s*Bitumen Transport\s*</);
    expect(layout).not.toContain('">Bitumen Transport<');
    // HTML title still carries the frozen product descriptor.
    expect(html).toContain("Bitumen Transport ERP");
  });
});
