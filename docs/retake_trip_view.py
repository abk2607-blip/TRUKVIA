"""Re-capture the trip-view screenshot with a longer wait — the previous
capture caught the "Loading trip..." placeholder because the network
hadn't finished when the screenshot fired."""
from __future__ import annotations
import asyncio, sys
from playwright.async_api import async_playwright

BASE = "https://trip-billing-pro-1.preview.emergentagent.com"


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(
            viewport={"width": 1440, "height": 900}, device_scale_factor=2,
        )
        page = await ctx.new_page()
        await page.goto(BASE + "/", wait_until="domcontentloaded", timeout=25000)
        await page.wait_for_timeout(2500)
        await page.locator('[data-testid="demo-login-button"]').click(timeout=8000)
        await page.wait_for_timeout(4500)
        await page.goto(
            BASE + "/trips/trip_04631491c3c74c86/view",
            wait_until="domcontentloaded", timeout=25000,
        )
        await page.wait_for_timeout(9500)
        await page.screenshot(path="/app/docs/screenshots/12_trip_view.png", full_page=False)
        print("OK 12_trip_view.png (retake with longer wait)")
        await browser.close()


asyncio.run(main())
