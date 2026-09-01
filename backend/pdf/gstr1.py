"""Iter132c C3.5 · GSTR-1 §9A (invoice-side) PDF export (A4 landscape).

Pure projection of the C3.5 canonical payload. Uses the L2d v3
fresh-flowable `_make_story()` two-pass pattern to eliminate reportlab
flowable-state pollution across the counting + real render passes —
proven on Invoice PDF and §9B PDF regression suites.

Contract: CONTENT GROWS → PAGES GROW → PDF STILL SUCCEEDS.
Never HTTP 500 by volume.

This is a HUMAN-READABLE WORKING REPORT, not a GST portal upload file.
B2CL / HSN / Docs / Amendments are out of scope for C3.5 (see the
Statutory Disclosure banner on page 1).
"""
from io import BytesIO
import base64
from datetime import datetime, timezone
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, Image, PageBreak,
)
from reportlab.pdfgen.canvas import Canvas
from ._base import _UNI_FONT, _UNI_FONT_BOLD


ACCENT       = colors.HexColor("#1D4ED8")   # blue-700 — distinct from §9B amber
ACCENT_LIGHT = colors.HexColor("#DBEAFE")   # blue-100
INK          = colors.HexColor("#111827")
MUTED        = colors.HexColor("#6B7280")
BORDER       = colors.HexColor("#D1D5DB")
BAND         = colors.HexColor("#F1F5F9")
BAD          = colors.HexColor("#B91C1C")
GOOD         = colors.HexColor("#059669")
INFO         = colors.HexColor("#B45309")

# Unicode literals hoisted to module constants — Python 3.11 forbids
# backslash escapes inside f-string expression parts.
_EMDASH  = "\u2014"
_DOT     = "\u00b7"
_RUPEE   = "\u20b9"
_SECTION = "\u00a7"
_CHECK   = "\u2713"
_CROSS   = "\u2717"
_BULLET  = "\u2022"


# Landscape A4 content width envelope. 297 mm page - 12 mm L - 12 mm R
# = 273 mm. All table column-width lists below MUST sum to <= 273 mm.
# Enforced by the C3.5 static-width regression test.
_CONTENT_W_MM = 273.0


# 13 columns · sum = 273 mm. Invoice # widened 28 → 34 mm so long numbers
# like `AKB/26-27//26-27/0004` (21 chars) stay on ONE visual line (mirrors
# the LOCKED §9B Note # 28 mm fix pattern). Date widened 16 → 18 mm so
# ISO `YYYY-MM-DD` stays on ONE line at 7pt DejaVu. Width reclaimed from
# Customer (36 → 34 mm) and GST Type (26 → 21 mm) — both remain readable.
B2B_COL_HEADERS = [
    "Invoice #", "Date", "Customer", "GSTIN", "State", "POS",
    "RCM", f"Taxable ({_RUPEE})", f"CGST ({_RUPEE})", f"SGST ({_RUPEE})",
    f"IGST ({_RUPEE})", f"Total ({_RUPEE})", "GST Type",
]
B2B_COL_WIDTHS_MM = [34, 18, 32, 28, 22, 12, 8, 22, 18, 18, 18, 22, 21]

# 12 columns · sum = 268 mm.
B2C_COL_HEADERS = [
    "Invoice #", "Date", "Customer", "State", "POS",
    "RCM", f"Taxable ({_RUPEE})", f"CGST ({_RUPEE})", f"SGST ({_RUPEE})",
    f"IGST ({_RUPEE})", f"Total ({_RUPEE})", "GST Type",
]
B2C_COL_WIDTHS_MM = [34, 18, 40, 24, 12, 8, 24, 18, 18, 18, 24, 30]

BY_STATE_COL_HEADERS = [
    "State", "Code", "Invoices", f"Taxable ({_RUPEE})",
    f"CGST ({_RUPEE})", f"SGST ({_RUPEE})", f"IGST ({_RUPEE})", f"Total ({_RUPEE})",
]
BY_STATE_COL_WIDTHS_MM = [50, 14, 20, 40, 30, 30, 30, 40]


def _all_col_widths_mm():
    """Aggregate all landscape column-width lists for the static
    regression test that enforces the <=273 mm envelope."""
    return [
        ("B2B", B2B_COL_WIDTHS_MM),
        ("B2C", B2C_COL_WIDTHS_MM),
        ("BY_STATE", BY_STATE_COL_WIDTHS_MM),
    ]


# ── Two-pass canvas · Page X of Y footer ─────────────────────────────────

class NumberedCanvas(Canvas):
    def __init__(self, *a, **kw):
        Canvas.__init__(self, *a, **kw)
        self._saved = []

    def showPage(self):
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved)
        for state in self._saved:
            self.__dict__.update(state)
            self._draw_footer(total)
            Canvas.showPage(self)
        Canvas.save(self)

    def _draw_footer(self, total):
        self.setFont(_UNI_FONT, 7)
        self.setFillColor(MUTED)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        pw, _ = landscape(A4)
        self.drawCentredString(
            pw / 2, 8 * mm,
            f"GSTR-1 {_SECTION}9A {_DOT} Invoice Register {_DOT} Computer-generated {_DOT} "
            f"Page {self._pageNumber} of {total} {_DOT} Printed {stamp} UTC {_DOT} "
            f"NOT a GST portal upload file",
        )


def _logo_flowable(company: dict, target_h_mm=15):
    logo_b64 = (company or {}).get("logo") or ""
    if not logo_b64:
        return Spacer(1, 1)
    try:
        raw = base64.b64decode(logo_b64.split(",", 1)[-1])
        buf = BytesIO(raw); buf.seek(0)
        img = Image(buf)
        iw, ih = img.imageWidth, img.imageHeight
        h_pt = target_h_mm * mm
        w_pt = h_pt * iw / max(ih, 1)
        img.drawHeight = h_pt
        img.drawWidth = min(w_pt, 40 * mm)
        return img
    except Exception:
        return Spacer(1, 1)


def _fmt_money(v) -> str:
    try:
        n = float(v or 0)
    except Exception:
        return str(v or "")
    s = f"{abs(n):,.2f}"
    return f"({s})" if n < 0 else s


def _para(text, style):
    return Paragraph(str(text if text is not None else ""), style)


def _empty_placeholder(section_name: str, small):
    return _para(f"<i>No {section_name} records for this period.</i>", small)


def _tbl(rows, widths_mm, header_bg=ACCENT):
    """Build a striped repeat-header table."""
    col_widths = [w * mm for w in widths_mm]
    tbl = Table(rows, colWidths=col_widths, repeatRows=1)
    ops = [
        ("BACKGROUND", (0, 0), (-1, 0), header_bg),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), _UNI_FONT_BOLD),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.4, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.2, BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    # Zebra bands on odd data rows.
    for i in range(1, len(rows)):
        if i % 2 == 0:
            ops.append(("BACKGROUND", (0, i), (-1, i), BAND))
    tbl.setStyle(TableStyle(ops))
    return tbl


def build_gstr1_pdf(company: dict, payload: dict) -> bytes:
    """Build the full multi-page PDF and return raw bytes."""
    buf = BytesIO()

    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=12 * mm, bottomMargin=16 * mm,
        title=f"GSTR-1 9A {payload.get('month','')}",
    )

    styles = getSampleStyleSheet()
    body     = ParagraphStyle("body",   parent=styles["Normal"], fontName=_UNI_FONT,      fontSize=8,  textColor=INK,   leading=10)
    small    = ParagraphStyle("small",  parent=styles["Normal"], fontName=_UNI_FONT,      fontSize=7,  textColor=INK,   leading=9)
    muted    = ParagraphStyle("muted",  parent=styles["Normal"], fontName=_UNI_FONT,      fontSize=7,  textColor=MUTED, leading=9)
    banner   = ParagraphStyle("banner", parent=styles["Normal"], fontName=_UNI_FONT_BOLD, fontSize=8,  textColor=INFO,  leading=11)
    h1       = ParagraphStyle("h1",     parent=styles["Heading1"], fontName=_UNI_FONT_BOLD, fontSize=16, textColor=ACCENT, alignment=2, leading=20)
    h2       = ParagraphStyle("h2",     parent=styles["Heading2"], fontName=_UNI_FONT_BOLD, fontSize=11, textColor=INK,   leading=14, spaceBefore=6, spaceAfter=3)

    def _make_story():
        """Fresh Flowables per pass (L2d v3 pattern)."""
        story = []
        _co = company or {}

        # ── Header band ────────────────────────────────────────────
        header_left = [
            Paragraph(f"<b>{_co.get('name','')}</b>", body),
            Paragraph(_co.get("address", "") or "", small),
            Paragraph(
                f"GSTIN: {payload.get('issuer_gstin') or _EMDASH}  {_DOT}  "
                f"State: {payload.get('company_state') or _EMDASH} ({payload.get('company_state_code') or _EMDASH})",
                muted,
            ),
        ]
        header_right = [Paragraph("GSTR-1 &#167;9A<br/>INVOICE REGISTER", h1)]
        header_tbl = Table(
            [[_logo_flowable(_co), header_left, header_right]],
            colWidths=[45 * mm, 158 * mm, 70 * mm],
        )
        header_tbl.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]))
        story.append(header_tbl)
        story.append(Spacer(1, 3 * mm))

        # Accent divider
        div = Table([[""]], colWidths=[_CONTENT_W_MM * mm], rowHeights=[3])
        div.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), ACCENT)]))
        story.append(div)
        story.append(Spacer(1, 3 * mm))

        # ── Period + Reconciliation banner ────────────────────────
        recon = payload.get("reconciliation") or {}
        period = payload.get("period", {})
        recon_ok = bool(recon.get("reconciled"))
        story.append(Paragraph(
            f"<b>Period:</b> {period.get('start','')} to {period.get('end','')}  "
            f"{_DOT}  <b>Month:</b> {payload.get('month','')}  "
            f"{_DOT}  <b>Invoice count:</b> {payload.get('invoice_count', 0)}",
            body,
        ))
        story.append(Spacer(1, 2 * mm))
        story.append(Paragraph(
            f"<b>Reconciled:</b> {'YES ' + _CHECK if recon_ok else 'NO ' + _CROSS}",
            ParagraphStyle("pill", parent=body, fontName=_UNI_FONT_BOLD,
                           fontSize=9, textColor=GOOD if recon_ok else BAD),
        ))
        story.append(Spacer(1, 3 * mm))

        # ── Summary totals card ───────────────────────────────────
        t = payload["totals"]
        # Summary rows: ₹ prefixed values (data cells use _UNI_FONT via
        # TableStyle below so the ₹ glyph renders correctly — otherwise
        # reportlab's default Helvetica emits a missing-glyph square).
        _rupee_val = lambda v: f"{_RUPEE} {_fmt_money(v)}"
        summary_rows = [
            ["Metric", "Value"],
            ["Invoices",       str(payload.get("invoice_count", 0))],
            ["Taxable",        _rupee_val(t.get("taxable", 0))],
            ["CGST",           _rupee_val(t.get("cgst", 0))],
            ["SGST",           _rupee_val(t.get("sgst", 0))],
            ["IGST",           _rupee_val(t.get("igst", 0))],
            ["Grand Total",    _rupee_val(t.get("total", 0))],
        ]
        summary_tbl = Table(summary_rows, colWidths=[80 * mm, 60 * mm])
        summary_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            # DejaVu on EVERY cell so the ₹ glyph in value column renders
            # (reportlab's default Helvetica has no U+20B9 → tofu box).
            ("FONTNAME", (0, 0), (-1, -1), _UNI_FONT),
            ("FONTNAME", (0, 0), (-1, 0), _UNI_FONT_BOLD),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
            ("INNERGRID", (0, 0), (-1, -1), 0.3, BORDER),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(summary_tbl)
        story.append(Spacer(1, 4 * mm))

        # ── Statutory disclosure banner (page 1) ──────────────────
        story.append(Paragraph(
            f"WORKING REPORT of QORVENA's invoice-side GSTR-1 dataset. "
            f"NOT a GST portal upload file. Not emitted here (out of scope): "
            f"B2CL split, HSN Summary (Table 12), Docs Summary (Table 13), "
            f"Amendments (9A / 9B / 9C). POS = customer.state per IGST {_SECTION}12(9).",
            banner,
        ))
        story.append(Spacer(1, 4 * mm))

        # ── By State (POS) ────────────────────────────────────────
        story.append(Paragraph("By State (POS)", h2))
        by_state = payload.get("by_state", []) or []
        if by_state:
            rows = [BY_STATE_COL_HEADERS]
            for s in by_state:
                rows.append([
                    _para(s.get("state", ""), small),
                    _para(s.get("state_code", ""), small),
                    _para(str(int(s.get("invoices", 0) or 0)), small),
                    _para(_fmt_money(s.get("taxable", 0)), small),
                    _para(_fmt_money(s.get("cgst", 0)), small),
                    _para(_fmt_money(s.get("sgst", 0)), small),
                    _para(_fmt_money(s.get("igst", 0)), small),
                    _para(_fmt_money(s.get("total", 0)), small),
                ])
            tbl = _tbl(rows, BY_STATE_COL_WIDTHS_MM)
            for i in (2, 3, 4, 5, 6, 7):
                tbl.setStyle(TableStyle([("ALIGN", (i, 0), (i, -1), "RIGHT")]))
            story.append(tbl)
        else:
            story.append(_empty_placeholder("By State", small))

        # ── B2B section ──────────────────────────────────────────
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph(f"B2B Invoices ({len(payload.get('b2b', []) or [])})", h2))
        b2b = payload.get("b2b", []) or []
        if b2b:
            rows = [B2B_COL_HEADERS]
            for r in b2b:
                rows.append([
                    _para(r.get("invoice_number", ""), small),
                    _para(r.get("invoice_date", ""), small),
                    _para(r.get("customer_name", ""), small),
                    _para(r.get("gstin", ""), small),
                    _para(r.get("state", ""), small),
                    _para(r.get("state_code", ""), small),
                    _para(r.get("reverse_charge", "N"), small),
                    _para(_fmt_money(r.get("taxable_value", 0)), small),
                    _para(_fmt_money(r.get("cgst", 0)), small),
                    _para(_fmt_money(r.get("sgst", 0)), small),
                    _para(_fmt_money(r.get("igst", 0)), small),
                    _para(_fmt_money(r.get("total", 0)), small),
                    _para(r.get("gst_type", ""), small),
                ])
            tbl = _tbl(rows, B2B_COL_WIDTHS_MM)
            for i in (7, 8, 9, 10, 11):
                tbl.setStyle(TableStyle([("ALIGN", (i, 0), (i, -1), "RIGHT")]))
            story.append(tbl)
        else:
            story.append(_empty_placeholder("B2B", small))

        # ── B2C section ──────────────────────────────────────────
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph(f"B2C Invoices ({len(payload.get('b2c', []) or [])})", h2))
        b2c = payload.get("b2c", []) or []
        if b2c:
            rows = [B2C_COL_HEADERS]
            for r in b2c:
                rows.append([
                    _para(r.get("invoice_number", ""), small),
                    _para(r.get("invoice_date", ""), small),
                    _para(r.get("customer_name", ""), small),
                    _para(r.get("state", ""), small),
                    _para(r.get("state_code", ""), small),
                    _para(r.get("reverse_charge", "N"), small),
                    _para(_fmt_money(r.get("taxable_value", 0)), small),
                    _para(_fmt_money(r.get("cgst", 0)), small),
                    _para(_fmt_money(r.get("sgst", 0)), small),
                    _para(_fmt_money(r.get("igst", 0)), small),
                    _para(_fmt_money(r.get("total", 0)), small),
                    _para(r.get("gst_type", ""), small),
                ])
            tbl = _tbl(rows, B2C_COL_WIDTHS_MM)
            for i in (6, 7, 8, 9, 10):
                tbl.setStyle(TableStyle([("ALIGN", (i, 0), (i, -1), "RIGHT")]))
            story.append(tbl)
        else:
            story.append(_empty_placeholder("B2C", small))

        # ── Warnings ─────────────────────────────────────────────
        warns = payload.get("warnings", []) or []
        if warns:
            story.append(Spacer(1, 4 * mm))
            story.append(Paragraph("Warnings", h2))
            for w in warns:
                story.append(Paragraph(f"{_BULLET} {w}", small))

        return story

    doc.build(_make_story(), canvasmaker=NumberedCanvas)
    return buf.getvalue()
