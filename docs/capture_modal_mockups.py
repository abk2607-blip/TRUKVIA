"""Capture pixel-perfect modal screenshots from /app/docs/modals.html.

The HTML replicates DuplicateMasterModal.jsx styling 1:1 (Tailwind classes
copied verbatim) so each screenshot matches the live modal exactly. Runs
locally against the file:// URL for full reliability.

Run: /opt/plugins-venv/bin/python /app/docs/capture_modal_mockups.py
"""
from __future__ import annotations
import asyncio
import os
import sys
from playwright.async_api import async_playwright

HTML = "file:///app/docs/modals.html"
OUT = "/app/docs/screenshots"
os.makedirs(OUT, exist_ok=True)

SHOTS = [
    ("mock1", "25_customer_duplicate_gstin.png"),
    ("mock2", "25b_customer_duplicate_name.png"),
    ("mock3", "05c_supplier_duplicate_modal.png"),
    ("mock4", "07b_vehicle_duplicate_modal.png"),
    ("mock5", "05d_supplier_deactivate_modal.png"),
]


async def main() -> int:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1000, "height": 700},
                                        device_scale_factor=2)
        page = await ctx.new_page()
        await page.goto(HTML, wait_until="load", timeout=15000)
        await page.wait_for_timeout(1200)
        for sel_id, fname in SHOTS:
            el = page.locator(f"#{sel_id}")
            await el.screenshot(path=f"{OUT}/{fname}")
            print(f"OK {fname}")
        await browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
