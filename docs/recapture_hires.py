"""Re-capture operational screenshots at 2x DPI for sharper printing,
then produce cropped variants (left sidebar removed) for the manual.

Run: /opt/plugins-venv/bin/python /app/docs/recapture_hires.py
"""
from __future__ import annotations
import asyncio, os, sys, subprocess
from playwright.async_api import async_playwright

BASE = "https://trip-billing-pro-1.preview.emergentagent.com"
OUT = "/app/docs/screenshots"
os.makedirs(OUT, exist_ok=True)

# Pages to re-capture at 2x DPI. Filenames match what the manual references.
ROUTES = [
    ("/", None, "01_login.png", 2200),
    ("__demo__", None, "02_dashboard.png", 4500),
    ("/customers", None, "03_customers.png", 2500),
    ("/suppliers", None, "05_suppliers.png", 2500),
    ("/suppliers/list", None, "05b_supplier_list.png", 2800),
    ("/parties", None, "06_parties_consignor.png", 2500),
    ("/vehicles", None, "07_vehicles.png", 2500),
    ("/drivers", None, "08_drivers.png", 2500),
    ("/products", None, "09_products.png", 2500),
    ("/trips", None, "10_trips.png", 3000),
    ("/trips/new", None, "11_trip_form.png", 3800),
    ("/trips/trip_04631491c3c74c86/view", None, "12_trip_view.png", 3800),
    ("/trips/templates", None, "13_trip_templates.png", 2500),
    ("/trips/import", None, "14_trip_import.png", 2500),
    ("/invoices", None, "15_invoices.png", 3000),
    ("/invoices/new", None, "16_invoice_create.png", 4000),
    ("/invoices/inv_b20e10518faf4dc0", None, "17_invoice_view.png", 4500),
    ("/fuel", None, "18_fuel.png", 2500),
    ("/invoices/overdue", None, "18b_overdue.png", 2500),
    ("/reports", None, "19_reports.png", 3000),
    ("/reports/halting-verify", None, "19b_reports_halting.png", 2500),
    ("/team", None, "20_team.png", 2500),
    ("/settings", None, "21_settings.png", 2500),
    ("/files", None, "22_files.png", 2500),
    ("/customers/history", None, "23_customer_history.png", 2500),
    ("/audit", None, "24_audit.png", 2500),
]


async def main() -> int:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        # 2x DPI + larger viewport so buttons/fields are readable
        ctx = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            device_scale_factor=2,
        )
        page = await ctx.new_page()
        # Login
        await page.goto(BASE + "/", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2500)
        await page.screenshot(path=f"{OUT}/01_login.png", full_page=False)
        print("OK 01_login.png")
        try:
            await page.locator('[data-testid="demo-login-button"]').click(timeout=10000)
            await page.wait_for_timeout(4800)
            await page.screenshot(path=f"{OUT}/02_dashboard.png", full_page=False)
            print("OK 02_dashboard.png")
        except Exception as e:
            print(f"[login] FAIL {e!r}")
            await browser.close(); return 1

        for path, _crop, fname, wait in ROUTES[2:]:
            try:
                await page.goto(BASE + path, wait_until="domcontentloaded", timeout=20000)
                await page.wait_for_timeout(wait)
                await page.screenshot(path=f"{OUT}/{fname}", full_page=False)
                print(f"OK {fname}")
            except Exception as e:
                print(f"FAIL {path}: {type(e).__name__} {str(e)[:100]}")
        await browser.close()
    print("Recaptured. Now cropping...")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
