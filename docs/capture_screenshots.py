"""Capture all QORVENA user-manual screenshots via Playwright and save
them to /app/docs/screenshots/. Uses the demo-login token so no Google
OAuth is required.

Run: /opt/plugins-venv/bin/python /app/docs/capture_screenshots.py
"""
from __future__ import annotations

import asyncio
import os
import sys

from playwright.async_api import async_playwright

BASE = os.environ.get("QORVENA_URL", "https://trip-billing-pro-1.preview.emergentagent.com")
OUT = "/app/docs/screenshots"
os.makedirs(OUT, exist_ok=True)

# (path, filename, wait_ms)
ROUTES = [
    ("/", "01_login.png", 2500),                      # captured before demo click
    ("__demo__", "02_dashboard.png", 4500),            # marker: click demo button, then screenshot
    ("/customers", "03_customers.png", 2500),
    ("/customers", "04_customer_form.png", 2500),      # extra step: open add form
    ("/suppliers", "05_suppliers.png", 2500),
    ("/suppliers/list", "05b_supplier_list.png", 3000),
    ("/parties", "06_parties_consignor.png", 2500),
    ("/vehicles", "07_vehicles.png", 2500),
    ("/drivers", "08_drivers.png", 2500),
    ("/products", "09_products.png", 2500),
    ("/trips", "10_trips.png", 2500),
    ("/trips/new", "11_trip_form.png", 3000),
    ("/trips/trip_04631491c3c74c86/view", "12_trip_view.png", 3200),
    ("/trips/templates", "13_trip_templates.png", 2500),
    ("/trips/import", "14_trip_import.png", 2500),
    ("/invoices", "15_invoices.png", 2500),
    ("/invoices/new", "16_invoice_create.png", 3200),
    ("/invoices/inv_b20e10518faf4dc0", "17_invoice_view.png", 4200),
    ("/fuel", "18_fuel.png", 2500),
    ("/invoices/overdue", "18b_overdue.png", 2500),
    ("/reports", "19_reports.png", 2500),
    ("/team", "20_team.png", 2500),
    ("/settings", "21_settings.png", 2500),
    ("/files", "22_files.png", 2500),
    ("/customers/history", "23_customer_history.png", 2500),
    ("/audit", "24_audit.png", 2500),
]


async def main() -> int:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await ctx.new_page()

        # Load login page
        await page.goto(BASE + "/", wait_until="domcontentloaded", timeout=25000)
        await page.wait_for_timeout(2500)
        await page.screenshot(path=f"{OUT}/01_login.png", full_page=False)
        print("OK 01_login.png")

        # Trigger demo login
        try:
            await page.locator('[data-testid="demo-login-button"]').click(timeout=8000)
            await page.wait_for_timeout(4500)
            await page.screenshot(path=f"{OUT}/02_dashboard.png", full_page=False)
            print(f"OK 02_dashboard.png (URL={page.url})")
        except Exception as e:
            print(f"FAIL demo login: {e!r}")
            await browser.close()
            return 1

        for path, fname, wait in ROUTES[2:]:
            try:
                if fname == "04_customer_form.png":
                    # already on /customers; click Add Customer button if present
                    await page.goto(BASE + "/customers", wait_until="domcontentloaded", timeout=15000)
                    await page.wait_for_timeout(2200)
                    # try to open the add-customer form
                    try:
                        # button may be "+ Add Customer"
                        btn = page.get_by_role("button", name="Add Customer")
                        await btn.first.click(timeout=4000)
                        await page.wait_for_timeout(1500)
                    except Exception:
                        pass
                    await page.screenshot(path=f"{OUT}/{fname}", full_page=False)
                    print(f"OK {fname}")
                    continue

                await page.goto(BASE + path, wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(wait)
                await page.screenshot(path=f"{OUT}/{fname}", full_page=False)
                print(f"OK {fname} <- {path}")
            except Exception as e:
                print(f"FAIL {path}: {type(e).__name__} {str(e)[:120]}")

        await browser.close()
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
