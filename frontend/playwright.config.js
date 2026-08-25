// Iter126c · Playwright config.
// Points at the running preview URL. Tests exercise the LIVE preview so the
// full Iter126a retry + Iter126b idempotency + Iter126c form-preservation
// stack is validated end-to-end in a real browser.
const { defineConfig, devices } = require("@playwright/test");

const BASE_URL =
  process.env.PW_BASE_URL ||
  "https://bitumen-books.preview.emergentagent.com";

module.exports = defineConfig({
  testDir: "./playwright",
  fullyParallel: false,        // draft/session tests share sessionStorage
  workers: 1,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [["list"], ["line"]],
  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
    video: "off",
    screenshot: "only-on-failure",
    launchOptions: { args: ["--no-sandbox"] },
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
