"""Fetch a real invoice PDF via Playwright (uses demo cookie/token) and
render the first & last pages to PNG for embedding in the manual.

Run: /opt/plugins-venv/bin/python /app/docs/capture_invoice_pdf.py
"""
from __future__ import annotations
import asyncio
import os
import subprocess
import sys
from playwright.async_api import async_playwright

BASE = "https://trip-billing-pro-1.preview.emergentagent.com"
INV_ID = "inv_b20e10518faf4dc0"
OUT = "/app/docs/screenshots"
TMP = "/tmp/inv_pdf"
os.makedirs(TMP, exist_ok=True)


async def main() -> int:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context()
        page = await ctx.new_page()
        # login via demo button so cookies + token are set
        await page.goto(BASE + "/", wait_until="domcontentloaded", timeout=25000)
        await page.wait_for_timeout(2000)
        try:
            await page.locator('[data-testid="demo-login-button"]').click(timeout=8000)
            await page.wait_for_timeout(4000)
        except Exception as e:
            print("[login] FAIL:", e)
            await browser.close()
            return 1

        # Use fetch inside the browser (carries cookies + Authorization header)
        pdf_b64 = await page.evaluate(f"""
            async () => {{
              const t = localStorage.getItem('token') || sessionStorage.getItem('token') || '';
              const r = await fetch('{BASE}/api/invoices/{INV_ID}/pdf', {{
                headers: t ? {{ 'Authorization': 'Bearer ' + t }} : {{}},
                credentials: 'include',
              }});
              if (!r.ok) return null;
              const buf = new Uint8Array(await r.arrayBuffer());
              let s = ''; for (const b of buf) s += String.fromCharCode(b);
              return btoa(s);
            }}
        """)
        await browser.close()

        if not pdf_b64:
            print("[fetch] no pdf returned")
            return 1
        import base64
        pdf_bytes = base64.b64decode(pdf_b64)
        pdf_path = f"{TMP}/invoice.pdf"
        with open(pdf_path, "wb") as f:
            f.write(pdf_bytes)
        print(f"[fetch] saved {len(pdf_bytes)} bytes to {pdf_path}")

    # Render to PNG
    subprocess.check_call(
        ["pdftoppm", "-r", "140", "-png", pdf_path, f"{TMP}/page"],
    )
    pages = sorted(os.listdir(TMP))
    print("pages:", pages)
    if any(p.endswith("-1.png") for p in pages):
        first = next(p for p in pages if "-1.png" in p or p.endswith("page-1.png"))
    else:
        first = pages[1] if len(pages) > 1 else pages[0]
    # Copy first page to screenshots/
    import shutil
    src = f"{TMP}/{first}"
    dst = f"{OUT}/17c_invoice_pdf_page.png"
    shutil.copy(src, dst)
    print(f"[out] {dst}")

    # last page (has signature + Page X of Y)
    last = pages[-1]
    shutil.copy(f"{TMP}/{last}", f"{OUT}/17d_invoice_pdf_last_page.png")
    print(f"[out] {OUT}/17d_invoice_pdf_last_page.png")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
