"""Post-process key operational screenshots: crop the left sidebar so the
useful content fills more of the page. Also creates a slightly zoomed-in
variant of the invoice-preview screenshot.

Produces filenames like `10_trips_crop.png` alongside the originals; the
manual references these `_crop` variants for the busiest pages.

Run: /opt/plugins-venv/bin/python /app/docs/crop_screenshots.py
"""
from __future__ import annotations
import os
import sys

from PIL import Image

OUT = "/app/docs/screenshots"

# 2× DPI captures ⇒ 2880 × 1800 pixels. Left sidebar spans roughly 0..~460 px
# on the standard app layout at 1440-wide viewport.
SIDEBAR_PX_2X = 500   # crop this many px from the left on 2× shots
SIDEBAR_PX_1X = 250   # if any 1× shot slips through
TOP_TRIM_2X   = 0     # keep the top header

TARGETS = [
    "02_dashboard.png",
    "03_customers.png",
    "05_suppliers.png",
    "05b_supplier_list.png",
    "06_parties_consignor.png",
    "07_vehicles.png",
    "08_drivers.png",
    "09_products.png",
    "10_trips.png",
    "11_trip_form.png",
    "12_trip_view.png",
    "13_trip_templates.png",
    "14_trip_import.png",
    "15_invoices.png",
    "16_invoice_create.png",
    "17_invoice_view.png",
    "18_fuel.png",
    "18b_overdue.png",
    "19_reports.png",
    "19b_reports_halting.png",
    "20_team.png",
    "21_settings.png",
    "22_files.png",
    "23_customer_history.png",
    "24_audit.png",
]


def crop_and_save(fname: str) -> None:
    src = f"{OUT}/{fname}"
    if not os.path.exists(src):
        print(f"[skip] {fname} not found")
        return
    img = Image.open(src)
    w, h = img.size
    # 2× device_scale_factor gives ~2880 wide
    is_2x = w >= 2500
    left = SIDEBAR_PX_2X if is_2x else SIDEBAR_PX_1X
    if w - left < 400:
        print(f"[skip] {fname} too narrow to crop ({w}px)")
        return
    top = TOP_TRIM_2X if is_2x else 0
    cropped = img.crop((left, top, w, h))
    out_name = fname.replace(".png", "_crop.png")
    cropped.save(f"{OUT}/{out_name}", optimize=True)
    print(f"OK {out_name}  (from {w}x{h}  ->  {cropped.size[0]}x{cropped.size[1]})")


def main() -> int:
    for f in TARGETS:
        crop_and_save(f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
