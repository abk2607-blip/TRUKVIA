"""Iter150E · Shared TRUKVIA PDF brand chrome (raster-only, non-invoice).

PURPOSE
-------
Presentation-only helper that stamps the approved TRUKVIA raster
lock-up + the final ember (#FD7800) accent rule onto authorised
non-invoice PDF surfaces.  Font-agnostic.  Never touches financial
values, ordering, sorting, GSTINs or totals.  Never mutates any
locked-band writer, service or route.  Never imports the Invoice
PDF (Path P1).

CONTRACT
--------
- Purely visual chrome.
- Reads the owner-supplied raster derivative at
  `backend/assets/brand/trukvia-pdf-header.png`.
- Graceful no-op if the raster is missing.
- Zero financial mutation.  Zero locked-file amendment.
- No new backend endpoint.

EXPORTED HELPERS
----------------
- `BRAND_EMBER_HEX = "#FD7800"`
- `BRAND_EMBER = colors.HexColor(BRAND_EMBER_HEX)`
- `brand_header_flowable(target_h_mm=15)` -> Image | None
- `brand_accent_divider(width_mm, thickness_pt=0.75)` -> Table
- `stamp_brand_footer(canvas, page_num, total_pages, report_label)` -> None
- `BRAND_NAME`, `BRAND_TAGLINE` (module-level copy constants)
"""
from __future__ import annotations
import os
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Image, Table, TableStyle

# ── Frozen tokens (Iter150E authorisation) ──────────────────────────
BRAND_NAME = "TRUKVIA"
BRAND_TAGLINE = "Financial Control"
BRAND_EMBER_HEX = "#FD7800"          # HSL 28° 100% 50%
BRAND_EMBER = colors.HexColor(BRAND_EMBER_HEX)
BRAND_INK = colors.HexColor("#09090B")  # zinc-950
BRAND_MUTED = colors.HexColor("#6B7280")

_BRAND_RASTER_PATH = os.path.join(
    os.path.dirname(__file__), "assets", "brand", "trukvia-pdf-header.png"
)


def brand_header_flowable(target_h_mm: float = 15.0,
                          max_w_mm: float = 55.0) -> Optional[Image]:
    """Return a proportionally-scaled ReportLab Image of the TRUKVIA
    raster header derivative, sized for header lock-up placements.
    Returns None if the raster is missing so callers can fall back
    to their existing text lockup without failing."""
    if not os.path.exists(_BRAND_RASTER_PATH):
        return None
    try:
        img = Image(_BRAND_RASTER_PATH)
        iw, ih = img.imageWidth, img.imageHeight
        h_pt = target_h_mm * mm
        w_pt = h_pt * iw / max(ih, 1)
        img.drawHeight = h_pt
        img.drawWidth = min(w_pt, max_w_mm * mm)
        return img
    except Exception:
        return None


def brand_accent_divider(width_mm: float, thickness_pt: float = 0.75) -> Table:
    """0.75 pt ember accent horizontal rule used beneath the branded
    header on all authorised non-invoice surfaces."""
    t = Table([[""]], colWidths=[width_mm * mm],
              rowHeights=[thickness_pt])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BRAND_EMBER),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


def stamp_brand_footer(canvas, page_num: int, total_pages: int,
                       report_label: str,
                       font_name: str = "Helvetica",
                       page_width_mm: float = 210.0) -> None:
    """Draws the authorised TRUKVIA · <report> · Page X of Y footer
    on the current canvas.  Presentation-only — never invoked from
    the Invoice PDF path."""
    try:
        canvas.setFont(font_name, 7)
    except Exception:
        canvas.setFont("Helvetica", 7)
    canvas.setFillColor(BRAND_MUTED)
    label = f"{BRAND_NAME}  ·  {report_label}  ·  Page {page_num} of {total_pages}"
    canvas.drawCentredString(page_width_mm * mm / 2.0, 5.5 * mm, label)


__all__ = [
    "BRAND_NAME",
    "BRAND_TAGLINE",
    "BRAND_EMBER_HEX",
    "BRAND_EMBER",
    "BRAND_INK",
    "BRAND_MUTED",
    "brand_header_flowable",
    "brand_accent_divider",
    "stamp_brand_footer",
]
