"""Capture extra modal / detail screenshots that require driving the UI:

* customer duplicate modal (soft-name block)
* supplier duplicate modal
* vehicle duplicate modal (idempotent)
* supplier deactivate confirmation modal
* invoice PDF page (rendered via /invoices/{id}/pdf)
* customer form filled state
* trip form focused on Unloading section
* invoice preview / view

These require live UI interaction, so we script the demo login and drive
each flow. Files land in /app/docs/screenshots/.

Run: /opt/plugins-venv/bin/python /app/docs/capture_modals.py
"""
from __future__ import annotations
import asyncio
import os
import sys
import time

from playwright.async_api import async_playwright

BASE = os.environ.get("QORVENA_URL", "https://trip-billing-pro-1.preview.emergentagent.com")
OUT = "/app/docs/screenshots"
os.makedirs(OUT, exist_ok=True)


async def _demo_login(page):
    await page.goto(BASE + "/", wait_until="domcontentloaded", timeout=25000)
    await page.wait_for_timeout(2000)
    await page.locator('[data-testid="demo-login-button"]').click(timeout=8000)
    await page.wait_for_timeout(4500)


async def _capture_customer_duplicate(page):
    """Fill Add Customer form with a name that already exists → capture the
    soft-name modal (which shows 3 buttons)."""
    try:
        await page.goto(BASE + "/customers", wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(2000)
        # Read the first existing customer's name from the table
        first_name_locator = page.locator("table tbody tr").first.locator("td").nth(0)
        existing_name = (await first_name_locator.inner_text()).strip().split("\n")[0][:60]
        print(f"[cust-dup] using existing name: {existing_name!r}")

        # Open Add Customer form
        try:
            await page.get_by_role("button", name="Add Customer").first.click(timeout=4000)
        except Exception:
            await page.get_by_text("Add Customer", exact=False).first.click(timeout=4000)
        await page.wait_for_timeout(1200)

        # Type the existing name in the Name field
        # Try multiple selectors
        name_field = None
        for sel in ['input[placeholder*="Name" i]', 'input[data-testid="customer-name"]',
                    'input[name="name"]', 'form input:nth-of-type(1)']:
            try:
                loc = page.locator(sel).first
                if await loc.count():
                    name_field = loc
                    break
            except Exception:
                continue
        if not name_field:
            print("[cust-dup] name field not found")
            return
        await name_field.fill(existing_name)
        await page.wait_for_timeout(300)
        # Submit
        try:
            await page.get_by_role("button", name="Save", exact=False).first.click(timeout=4000)
        except Exception:
            await page.locator('button[type="submit"]').first.click(timeout=4000)
        # Wait for the modal
        try:
            await page.wait_for_selector('[data-testid*="iter127a-duplicate-modal"]', timeout=6000)
            await page.wait_for_timeout(600)
            await page.screenshot(path=f"{OUT}/25_customer_duplicate_modal.png", full_page=False)
            # Also crop just the modal for a tight visual
            modal = page.locator('[data-testid*="iter127a-duplicate-modal"]').first
            box = await modal.bounding_box()
            if box:
                await page.screenshot(path=f"{OUT}/25b_customer_duplicate_modal_crop.png",
                                      clip={"x": max(0, box["x"] - 20), "y": max(0, box["y"] - 20),
                                            "width": min(1440, box["width"] + 40),
                                            "height": min(900, box["height"] + 40)})
            print("OK 25_customer_duplicate_modal.png")
            # dismiss
            try:
                await page.locator('[data-testid="iter127a-duplicate-cancel"]').first.click(timeout=3000)
            except Exception:
                pass
            await page.wait_for_timeout(500)
        except Exception as e:
            print(f"[cust-dup] modal didn't appear: {e!r}")
    except Exception as e:
        print(f"[cust-dup] FAIL: {e!r}")


async def _capture_supplier_deactivate_modal(page):
    """On Suppliers > List tab, click Deactivate on the first active row to
    capture the confirmation dialog."""
    try:
        await page.goto(BASE + "/suppliers/list", wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(2500)
        # Snap the list itself as-is
        await page.screenshot(path=f"{OUT}/05b_supplier_list.png", full_page=False)

        # Try to click the first "Deactivate" button
        try:
            btn = page.get_by_role("button", name="Deactivate").first
            await btn.click(timeout=4000)
            await page.wait_for_timeout(1200)
            await page.screenshot(path=f"{OUT}/26_supplier_deactivate_modal.png", full_page=False)
            print("OK 26_supplier_deactivate_modal.png")
            # Dismiss
            try:
                await page.get_by_role("button", name="Cancel").first.click(timeout=3000)
            except Exception:
                pass
            await page.wait_for_timeout(400)
        except Exception as e:
            print(f"[sup-deact] no Deactivate button: {e!r}")
    except Exception as e:
        print(f"[sup-deact] FAIL: {e!r}")


async def _capture_vehicle_duplicate(page):
    """Add a vehicle number that already exists → capture the modal."""
    try:
        await page.goto(BASE + "/vehicles", wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(2200)
        # Get an existing vehicle number
        first_veh = page.locator("table tbody tr").first.locator("td").nth(0)
        existing_veh = (await first_veh.inner_text()).strip().split("\n")[0][:20]
        print(f"[veh-dup] using existing vehicle: {existing_veh!r}")

        try:
            await page.get_by_role("button", name="Add Vehicle").first.click(timeout=4000)
        except Exception:
            try:
                await page.get_by_role("button", name="+ Add").first.click(timeout=4000)
            except Exception:
                pass
        await page.wait_for_timeout(1000)
        # Fill Vehicle Number
        for sel in ['input[placeholder*="Vehicle" i]', 'input[data-testid*="vehicle-number"]',
                    'input[name="vehicle_number"]', 'form input:nth-of-type(1)']:
            try:
                loc = page.locator(sel).first
                if await loc.count():
                    await loc.fill(existing_veh)
                    break
            except Exception:
                continue
        await page.wait_for_timeout(300)
        try:
            await page.get_by_role("button", name="Save", exact=False).first.click(timeout=4000)
        except Exception:
            await page.locator('button[type="submit"]').first.click(timeout=4000)
        try:
            await page.wait_for_selector('[data-testid*="iter127a-duplicate-modal"]', timeout=6000)
            await page.wait_for_timeout(500)
            await page.screenshot(path=f"{OUT}/27_vehicle_duplicate_modal.png", full_page=False)
            modal = page.locator('[data-testid*="iter127a-duplicate-modal"]').first
            box = await modal.bounding_box()
            if box:
                await page.screenshot(path=f"{OUT}/27b_vehicle_duplicate_modal_crop.png",
                                      clip={"x": max(0, box["x"] - 20), "y": max(0, box["y"] - 20),
                                            "width": min(1440, box["width"] + 40),
                                            "height": min(900, box["height"] + 40)})
            print("OK 27_vehicle_duplicate_modal.png")
        except Exception as e:
            print(f"[veh-dup] modal didn't appear: {e!r}")
    except Exception as e:
        print(f"[veh-dup] FAIL: {e!r}")


async def _capture_invoice_pdf_render(page):
    """Fetch the invoice PDF via the frontend so it renders — instead we open
    the invoice VIEW page and screenshot the on-screen preview."""
    try:
        # Use an existing invoice id
        await page.goto(BASE + "/invoices/inv_b20e10518faf4dc0",
                        wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(4500)
        # Full-page (long) shot for the preview
        await page.screenshot(path=f"{OUT}/17_invoice_view.png", full_page=False)
        await page.screenshot(path=f"{OUT}/17b_invoice_view_full.png", full_page=True)
        print("OK 17 / 17b invoice preview")
    except Exception as e:
        print(f"[inv-view] FAIL: {e!r}")


async def _capture_trip_form_sections(page):
    """Trip create form — full page and unload section closeup."""
    try:
        await page.goto(BASE + "/trips/new", wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(3500)
        await page.screenshot(path=f"{OUT}/11_trip_form.png", full_page=False)
        await page.screenshot(path=f"{OUT}/11b_trip_form_full.png", full_page=True)
        print("OK 11 / 11b trip form")
    except Exception as e:
        print(f"[trip-form] FAIL: {e!r}")


async def main() -> int:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await ctx.new_page()

        await _demo_login(page)
        # Capture each artefact — errors in one don't stop the next
        await _capture_customer_duplicate(page)
        await _capture_supplier_deactivate_modal(page)
        await _capture_vehicle_duplicate(page)
        await _capture_invoice_pdf_render(page)
        await _capture_trip_form_sections(page)

        await browser.close()
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
