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

# Register Noto Sans Telugu for Unicode rendering (LR terms, invoice labels)
_FONTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fonts")
_TE_FONT = "NotoSansTelugu"
_TE_FONT_BOLD = "NotoSansTelugu-Bold"
try:
    if _TE_FONT not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(_TE_FONT, os.path.join(_FONTS_DIR, "NotoSansTelugu-Regular.ttf")))
        pdfmetrics.registerFont(TTFont(_TE_FONT_BOLD, os.path.join(_FONTS_DIR, "NotoSansTelugu-Bold.ttf")))
except Exception:
    _TE_FONT = "Helvetica"  # fallback

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
