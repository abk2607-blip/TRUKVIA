"""Server-side PDF generator for the GST transport invoice.
Uses reportlab platypus to build a professional bilingual-friendly invoice
similar to the VBK Logistics reference format.
"""
from io import BytesIO
import os
import base64
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, KeepTogether, Image, PageBreak,
)

# Fonts directory (kept for the DejaVuSans body font used by invoice/LR/report).
_FONTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fonts")

# DejaVu Sans is used across invoice/LR/report bodies because it supports the
# Indian Rupee sign (₹, U+20B9) which the built-in Helvetica lacks.
_UNI_FONT = "DejaVuSans"
_UNI_FONT_BOLD = "DejaVuSans-Bold"
_UNI_PATHS = [
    os.path.join(_FONTS_DIR, "DejaVuSans.ttf"),
    os.path.join(_FONTS_DIR, "DejaVuSans-Bold.ttf"),
]
try:
    if _UNI_FONT not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(_UNI_FONT, _UNI_PATHS[0]))
        pdfmetrics.registerFont(TTFont(_UNI_FONT_BOLD, _UNI_PATHS[1]))
        from reportlab.pdfbase.pdfmetrics import registerFontFamily
        registerFontFamily(_UNI_FONT, normal=_UNI_FONT, bold=_UNI_FONT_BOLD, italic=_UNI_FONT, boldItalic=_UNI_FONT_BOLD)
except Exception:
    _UNI_FONT = "Helvetica"
    _UNI_FONT_BOLD = "Helvetica-Bold"


def _fmt(n):
    try:
        return f"{float(n):,.2f}"
    except Exception:
        return "0.00"


def _num_to_words_inr(n: float) -> str:
    """Very simple Indian numbering system to words for rupees."""
    n = int(round(n))
    if n == 0:
        return "Zero Rupees Only"
    units = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
             "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
             "Seventeen", "Eighteen", "Nineteen"]
    tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]

    def two(x):
        if x < 20:
            return units[x]
        return tens[x // 10] + (" " + units[x % 10] if x % 10 else "")

    def three(x):
        s = ""
        if x >= 100:
            s += units[x // 100] + " Hundred"
            x %= 100
            if x:
                s += " " + two(x)
        else:
            s = two(x)
        return s

    parts = []
    crore = n // 10000000
    n %= 10000000
    lakh = n // 100000
    n %= 100000
    thousand = n // 1000
    n %= 1000
    hundred = n
    if crore:
        parts.append(three(crore) + " Crore")
    if lakh:
        parts.append(two(lakh) + " Lakh")
    if thousand:
        parts.append(two(thousand) + " Thousand")
    if hundred:
        parts.append(three(hundred))
    return " ".join(parts).strip() + " Rupees Only"

LR_TERMS_EN = [
    # Iter101 — Rewritten in original wording for QORVENA / A. Kishore Babu & Sons.
    # Business intent and commercial protection are preserved; language is fresh
    # (no clause copies existing industry templates verbatim).
    "Where an official loading-facility seal is applicable, verify the seal number against the relevant loading document / invoice before unloading. Any transporter-applied safety seal discrepancy shall be recorded in the unloading remarks and handled as per the Seal Verification &amp; Unloading Protocol above.",
    "Physically inspect the driver cabin, tool compartment and the full chassis underside for any foreign objects or concealed material prior to commencing weighment.",
    "Instruct the driver and crew to remove all non-consignment items — firewood, jerry cans, spare drums, drinking-water containers, personal cargo — from the vehicle before the empty-weight reading is taken.",
    "Examine the diesel tank, cabin interior and any accessible cavities for modifications or hidden compartments that could be exploited to manipulate the tare or gross weight.",
    "Confirm that every wheel of the tanker rests fully within the weighbridge platform boundary; partial contact renders the reading invalid and must not be accepted.",
    "Request the driver and helper to step off the vehicle for both loaded and empty weighments, and obtain the driver's signature against each recorded weight in the site register.",
    "Follow the standard sampling and quality-testing protocol for the delivered product before opening the discharge valve or dip-checking the compartments.",
    "After unloading and the empty weighment, open the tank manhole and physically confirm complete evacuation — no residual product may remain inside the compartment.",
    "Where the tank cannot be fully gravity-drained, deploy the loading ramp and drain-drum method to achieve zero residual product before releasing the vehicle.",
    "Complete every field of the 'Unloading Details by Site Officials' section on this GCN — with signature, seal and stamp — and retain a duplicate record of the same information at the site for the vehicle's file.",
    "The driver's signature is mandatory on both the loading slip at the origin location and the unloading slip at the destination site.",
    "Once the vehicle has been unloaded and released, the carrier accepts no further responsibility for the quality or quantity of the delivered product; the consignee's acknowledgement is deemed final acceptance.",
    "Where a joint coordination WhatsApp / Signal group has been established, site officials shall upload clear photographs and short videos of the tanker manholes immediately after unloading, to build an audit-safe visual record and to deter any malpractice.",
    "Insurance for the goods in transit is the responsibility of the consignor or consignee as applicable under the underlying commercial contract; the carrier is not liable for risks properly covered by such insurance (fire, accident, theft or acts of God).",
    "This Goods Consignment Note is issued subject to the standard conditions of carriage of A. Kishore Babu & Sons. Any dispute arising out of this consignment shall be subject to the exclusive jurisdiction of the competent courts at the carrier's principal place of business.",
]

