"""Iter132c C3.2 · GSTR-1 §9B PDF export (A4 landscape).

Pure projection of the C3.1 canonical JSON payload. Uses the L2d v3
fresh-flowable `_make_story()` two-pass pattern to eliminate reportlab
flowable-state pollution across the counting + real render passes —
proven at 30-row density on the Invoice PDF regression suite.

Contract: CONTENT GROWS → PAGES GROW → PDF STILL SUCCEEDS.
Never HTTP 500 by volume.

This document is a HUMAN-READABLE STATUTORY WORKING REPORT, not a
GST portal upload file. The offline-utility JSON remains scope for
future C3.4.
"""
from io import BytesIO
import base64
from datetime import datetime, timezone
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, Image, PageBreak, KeepTogether,
)
from reportlab.pdfgen.canvas import Canvas
from ._base import _UNI_FONT, _UNI_FONT_BOLD


ACCENT       = colors.HexColor("#B45309")   # amber-700
ACCENT_LIGHT = colors.HexColor("#FEF3C7")   # amber-100
INK          = colors.HexColor("#111827")
MUTED        = colors.HexColor("#6B7280")
BORDER       = colors.HexColor("#D1D5DB")
CN_BG        = colors.HexColor("#FEF2F2")   # red-50
DN_BG        = colors.HexColor("#EFF6FF")   # blue-50
BAD          = colors.HexColor("#B91C1C")   # red-700
GOOD         = colors.HexColor("#059669")   # emerald-600
INFO         = colors.HexColor("#B45309")


# Landscape A4 content width envelope. 297 mm page - 12 mm L - 12 mm R
# = 273 mm. All table column-width lists below MUST sum to ≤ 273 mm.
# Enforced by the C3.2 static-width regression test.
_CONTENT_W_MM = 273.0


# 12 columns · widths sum = 268 mm ≤ 273
CDNR_COL_HEADERS = [
    "Note #", "Date", "T", "Ctin", "Recipient",
    "Invoice #", "Rate %", "Taxable \u20B9",
    "CGST \u20B9", "SGST \u20B9", "IGST \u20B9",
    "Note Value \u20B9", "Reason",
]
CDNR_COL_WIDTHS_MM = [20, 16, 6, 26, 30, 20, 10, 22, 16, 16, 16, 22, 48]

# 11 columns
CDNUR_COL_HEADERS = [
    "Note #", "Date", "T", "Recipient",
    "Invoice #", "Rate %", "Taxable \u20B9",
    "CGST \u20B9", "SGST \u20B9", "IGST \u20B9",
    "Note Value \u20B9", "Reason",
]
CDNUR_COL_WIDTHS_MM = [20, 16, 6, 38, 22, 10, 22, 16, 16, 16, 22, 66]

# B2CS shares layout with CDNUR
B2CS_COL_HEADERS = CDNUR_COL_HEADERS[:]
B2CS_COL_WIDTHS_MM = CDNUR_COL_WIDTHS_MM[:]

COMMERCIAL_COL_HEADERS = [
    "Note #", "Date", "T", "Recipient",
    "Invoice #", "Subtotal \u20B9", "Total \u20B9",
    "QORVENA Reason", "Info",
]
COMMERCIAL_COL_WIDTHS_MM = [22, 16, 6, 40, 22, 22, 22, 40, 80]

CANCELLED_COL_HEADERS = [
    "Note #", "Date", "T", "Recipient",
    "Invoice #", "Total \u20B9",
    "Cancelled At", "Reason", "Advisory",
]
CANCELLED_COL_WIDTHS_MM = [22, 16, 6, 38, 22, 22, 26, 40, 78]


def _all_col_widths_mm():
    """Aggregate all landscape table column-width lists for the static
    regression test that enforces the ≤273 mm envelope."""
    return [
        ("CDNR", CDNR_COL_WIDTHS_MM),
        ("CDNUR", CDNUR_COL_WIDTHS_MM),
        ("B2CS", B2CS_COL_WIDTHS_MM),
        ("COMMERCIAL", COMMERCIAL_COL_WIDTHS_MM),
        ("CANCELLED", CANCELLED_COL_WIDTHS_MM),
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
            f"GSTR-1 \u00a79B \u00b7 CN/DN Register \u00b7 Computer-generated \u00b7 "
            f"Page {self._pageNumber} of {total} \u00b7 Printed {stamp} UTC",
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


def build_gstr1_9b_pdf(company: dict, payload: dict) -> bytes:
    """Build the full multi-page PDF and return raw bytes."""
    buf = BytesIO()

    # SimpleDocTemplate + two-pass fresh-flowable rendering (L2d v3 pattern).
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=12 * mm, bottomMargin=16 * mm,
        title=f"GSTR-1 9B {payload.get('month','')}",
    )

    styles = getSampleStyleSheet()
    body     = ParagraphStyle("body",   parent=styles["Normal"], fontName=_UNI_FONT,      fontSize=8,  textColor=INK,   leading=10)
    small    = ParagraphStyle("small",  parent=styles["Normal"], fontName=_UNI_FONT,      fontSize=7,  textColor=INK,   leading=9)
    muted    = ParagraphStyle("muted",  parent=styles["Normal"], fontName=_UNI_FONT,      fontSize=7,  textColor=MUTED, leading=9)
    banner   = ParagraphStyle("banner", parent=styles["Normal"], fontName=_UNI_FONT_BOLD, fontSize=8,  textColor=INFO,  leading=11)
    banner_r = ParagraphStyle("bannerR",parent=styles["Normal"], fontName=_UNI_FONT_BOLD, fontSize=8,  textColor=BAD,   leading=11)
    label    = ParagraphStyle("label",  parent=styles["Normal"], fontName=_UNI_FONT_BOLD, fontSize=7,  textColor=MUTED, leading=9)
    h1       = ParagraphStyle("h1",     parent=styles["Heading1"], fontName=_UNI_FONT_BOLD, fontSize=16, textColor=ACCENT, alignment=2, leading=20)
    h2       = ParagraphStyle("h2",     parent=styles["Heading2"], fontName=_UNI_FONT_BOLD, fontSize=11, textColor=INK,   leading=14, spaceBefore=6, spaceAfter=3)
    kv_bold  = ParagraphStyle("kvb",    parent=body, fontName=_UNI_FONT_BOLD)

    def _make_story():
        """Fresh Flowables per pass (L2d v3 pattern)."""
        story = []
        _co = company or {}

        # ── Header band ────────────────────────────────────────────
        header_left = [
            Paragraph(f"<b>{_co.get('name','')}</b>", body),
            Paragraph(_co.get("address", "") or "", small),
            Paragraph(
                f"GSTIN: {payload.get('issuer_gstin') or '\u2014'}  \u00b7  "
                f"State: {payload.get('company_state') or '\u2014'} ({payload.get('company_state_code') or '\u2014'})",
                muted,
            ),
        ]
        header_right = [Paragraph("GSTR-1 &#167;9B<br/>CN/DN REGISTER", h1)]
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

        # ── Summary + Reconciliation card ──────────────────────────
        t = payload["totals"]; recon = payload["reconciliation"]
        period = payload.get("period", {})
        recon_ok = bool(recon.get("reconciled"))
        recon_pill = Paragraph(
            f"<b>Reconciled:</b> {'YES ✓' if recon_ok else 'NO ✗'}",
            ParagraphStyle("pill", parent=body, fontName=_UNI_FONT_BOLD,
                           fontSize=9, textColor=GOOD if recon_ok else BAD),
        )
        period_line = Paragraph(
            f"<b>Period:</b> {period.get('start','')} to {period.get('end','')}  "
            f"\u00b7  <b>Month:</b> {payload.get('month','')}  "
            f"\u00b7  <b>Note count:</b> {payload.get('note_count', 0)}",
            body,
        )
        story.append(period_line)
        story.append(Spacer(1, 2 * mm))
        story.append(recon_pill)
        story.append(Spacer(1, 3 * mm))

        summary_rows = [
            ["Bucket", "Note Count", "Total \u20B9", "Credit \u20B9", "Debit \u20B9"],
            ["CDNR (Registered B2B)",              t["cdnr"]["note_count"],             _fmt_money(t["cdnr"]["val"]),             _fmt_money(t["cdnr"]["cn"]),             _fmt_money(t["cdnr"]["dn"])],
            ["CDNUR (Unregistered B2CL)",          t["cdnur"]["note_count"],            _fmt_money(t["cdnur"]["val"]),            _fmt_money(t["cdnur"]["cn"]),            _fmt_money(t["cdnur"]["dn"])],
            ["B2CS Adjustments (net-of Table 7)",  t["b2cs_adjustments"]["note_count"], _fmt_money(t["b2cs_adjustments"]["val"]), _fmt_money(t["b2cs_adjustments"]["cn"]), _fmt_money(t["b2cs_adjustments"]["dn"])],
            ["Commercial Notes (\u00a734 excluded)", t["commercial_notes"]["note_count"], _fmt_money(t["commercial_notes"]["val"]), _fmt_money(t["commercial_notes"]["cn"]), _fmt_money(t["commercial_notes"]["dn"])],
            ["Cancelled After Export (\u00a79C due)", t["cancelled_after_export"]["note_count"], "", "", ""],
        ]
        summary_tbl = Table(summary_rows,
                            colWidths=[80 * mm, 25 * mm, 55 * mm, 55 * mm, 55 * mm])
        summary_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), _UNI_FONT_BOLD),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("ALIGN", (0, 0), (0, -1), "LEFT"),
            ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
            ("INNERGRID", (0, 0), (-1, -1), 0.3, BORDER),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(summary_tbl)
        story.append(Spacer(1, 5 * mm))

        # ── Sections ────────────────────────────────────────────────
        _append_cdnr_section(story, payload, h2, banner, body, small)
        _append_cdnur_section(story, payload, h2, banner, body, small)
        _append_b2cs_section(story, payload, h2, banner, body, small)
        _append_commercial_section(story, payload, h2, banner, body, small)
        _append_cancelled_section(story, payload, h2, banner_r, body, small)

        # ── Warnings ────────────────────────────────────────────────
        warns = payload.get("warnings", []) or []
        if warns:
            story.append(Spacer(1, 4 * mm))
            story.append(Paragraph("Warnings", h2))
            for w in warns:
                story.append(Paragraph(f"\u2022 {w}", small))

        return story

    doc.build(_make_story(), canvasmaker=NumberedCanvas)
    return buf.getvalue()


# ── Section builders (each returns list of flowables appended to story) ──

def _para(text, style):
    return Paragraph(str(text if text is not None else ""), style)


def _empty_placeholder(section_name: str, small):
    return _para(
        f"<i>No {section_name} records for this period.</i>", small,
    )


def _tint_style_ops(row_idx: int, kind: str):
    """Return TableStyle background ops for a data row."""
    bg = CN_BG if kind == "credit" else DN_BG
    return [("BACKGROUND", (0, row_idx), (-1, row_idx), bg)]


def _cdn_table(rows, widths_mm, cell_style):
    """Build a striped, repeat-header table. `rows[0]` is header."""
    col_widths = [w * mm for w in widths_mm]
    tbl = Table(rows, colWidths=col_widths, repeatRows=1)
    ops = [
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
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
    tbl.setStyle(TableStyle(ops))
    return tbl


def _append_cdnr_section(story, payload, h2, banner, body, small):
    story.append(Paragraph("CDNR \u00b7 Registered Recipients (Table 9B)", h2))
    cdnr = payload.get("cdnr", []) or []
    if not cdnr:
        story.append(_empty_placeholder("CDNR", small))
        return
    rows = [CDNR_COL_HEADERS]
    row_kinds = []
    for grp in cdnr:
        for nt in grp.get("nt", []) or []:
            itm = (nt.get("itms", [{}])[0].get("itm_det") or {})
            rows.append([
                _para(nt.get("nt_num", ""), small),
                _para(nt.get("nt_dt", ""), small),
                _para(nt.get("ntty", ""), small),
                _para(grp.get("ctin", ""), small),
                _para(nt.get("customer_name", ""), small),
                _para(nt.get("inum", ""), small),
                _para(f"{float(itm.get('rt', 0) or 0):.2f}", small),
                _para(_fmt_money(itm.get("txval", 0)), small),
                _para(_fmt_money(itm.get("camt", 0)), small),
                _para(_fmt_money(itm.get("samt", 0)), small),
                _para(_fmt_money(itm.get("iamt", 0)), small),
                _para(_fmt_money(nt.get("val", 0)), small),
                _para(f"{nt.get('rsn','')} \u00b7 {nt.get('reason_code_qorvena','') or ''}", small),
            ])
            row_kinds.append(nt.get("kind"))
    tbl = _cdn_table(rows, CDNR_COL_WIDTHS_MM, small)
    style = tbl.getStyle() if hasattr(tbl, "getStyle") else None
    for i, k in enumerate(row_kinds, start=1):
        tbl.setStyle(TableStyle(_tint_style_ops(i, k)))
    for i in (7, 8, 9, 10, 11):  # right-align numeric cols
        tbl.setStyle(TableStyle([("ALIGN", (i, 0), (i, -1), "RIGHT")]))
    story.append(tbl)


def _append_cdnur_section(story, payload, h2, banner, body, small):
    story.append(Paragraph("CDNUR \u00b7 Unregistered Recipients (Table 9B)", h2))
    rows_src = payload.get("cdnur", []) or []
    if not rows_src:
        story.append(_empty_placeholder("CDNUR", small))
        return
    rows = [CDNUR_COL_HEADERS]
    row_kinds = []
    for nt in rows_src:
        itm = (nt.get("itms", [{}])[0].get("itm_det") or {})
        rows.append([
            _para(nt.get("nt_num", ""), small),
            _para(nt.get("nt_dt", ""), small),
            _para(nt.get("ntty", ""), small),
            _para(nt.get("customer_name", ""), small),
            _para(nt.get("inum", ""), small),
            _para(f"{float(itm.get('rt', 0) or 0):.2f}", small),
            _para(_fmt_money(itm.get("txval", 0)), small),
            _para(_fmt_money(itm.get("camt", 0)), small),
            _para(_fmt_money(itm.get("samt", 0)), small),
            _para(_fmt_money(itm.get("iamt", 0)), small),
            _para(_fmt_money(nt.get("val", 0)), small),
            _para(f"{nt.get('rsn','')} \u00b7 {nt.get('reason_code_qorvena','') or ''}", small),
        ])
        row_kinds.append(nt.get("kind"))
    tbl = _cdn_table(rows, CDNUR_COL_WIDTHS_MM, small)
    for i, k in enumerate(row_kinds, start=1):
        tbl.setStyle(TableStyle(_tint_style_ops(i, k)))
    for i in (6, 7, 8, 9, 10):
        tbl.setStyle(TableStyle([("ALIGN", (i, 0), (i, -1), "RIGHT")]))
    story.append(tbl)


def _append_b2cs_section(story, payload, h2, banner, body, small):
    story.append(Paragraph("B2CS Adjustments \u00b7 Report NET-OF in Table 7", h2))
    story.append(Paragraph(
        "Not statutorily part of \u00a79B \u00b7 surfaced here for audit \u00b7 "
        "accountant must net these into Table 7 of GSTR-1.",
        banner,
    ))
    rows_src = payload.get("b2cs_adjustments", []) or []
    if not rows_src:
        story.append(_empty_placeholder("B2CS Adjustments", small))
        return
    rows = [B2CS_COL_HEADERS]
    row_kinds = []
    for nt in rows_src:
        itm = (nt.get("itms", [{}])[0].get("itm_det") or {})
        rows.append([
            _para(nt.get("nt_num", ""), small),
            _para(nt.get("nt_dt", ""), small),
            _para(nt.get("ntty", ""), small),
            _para(nt.get("customer_name", ""), small),
            _para(nt.get("inum", ""), small),
            _para(f"{float(itm.get('rt', 0) or 0):.2f}", small),
            _para(_fmt_money(itm.get("txval", 0)), small),
            _para(_fmt_money(itm.get("camt", 0)), small),
            _para(_fmt_money(itm.get("samt", 0)), small),
            _para(_fmt_money(itm.get("iamt", 0)), small),
            _para(_fmt_money(nt.get("val", 0)), small),
            _para(f"{nt.get('rsn','')} \u00b7 {nt.get('reason_code_qorvena','') or ''}", small),
        ])
        row_kinds.append(nt.get("kind"))
    tbl = _cdn_table(rows, B2CS_COL_WIDTHS_MM, small)
    for i, k in enumerate(row_kinds, start=1):
        tbl.setStyle(TableStyle(_tint_style_ops(i, k)))
    for i in (6, 7, 8, 9, 10):
        tbl.setStyle(TableStyle([("ALIGN", (i, 0), (i, -1), "RIGHT")]))
    story.append(tbl)


def _append_commercial_section(story, payload, h2, banner, body, small):
    story.append(Paragraph("Commercial / Financial Notes", h2))
    story.append(Paragraph(
        "Excluded from GSTR-1 \u00a79B per CGST \u00a734 / \u00a715(3)(b) \u00b7 "
        "commercial notes do NOT adjust GST liability and are NOT reported.",
        banner,
    ))
    rows_src = payload.get("commercial_notes", []) or []
    if not rows_src:
        story.append(_empty_placeholder("Commercial", small))
        return
    rows = [COMMERCIAL_COL_HEADERS]
    row_kinds = []
    for nt in rows_src:
        rows.append([
            _para(nt.get("note_number", ""), small),
            _para(nt.get("note_date", ""), small),
            _para(nt.get("ntty", ""), small),
            _para(nt.get("customer_name", ""), small),
            _para(nt.get("invoice_number", ""), small),
            _para(_fmt_money(nt.get("subtotal", 0)), small),
            _para(_fmt_money(nt.get("total_amount", 0)), small),
            _para(nt.get("reason_code_qorvena", "") or "", small),
            _para(nt.get("_info", "") or "", small),
        ])
        row_kinds.append(nt.get("kind"))
    tbl = _cdn_table(rows, COMMERCIAL_COL_WIDTHS_MM, small)
    for i, k in enumerate(row_kinds, start=1):
        tbl.setStyle(TableStyle(_tint_style_ops(i, k)))
    for i in (5, 6):
        tbl.setStyle(TableStyle([("ALIGN", (i, 0), (i, -1), "RIGHT")]))
    story.append(tbl)


def _append_cancelled_section(story, payload, h2, banner_r, body, small):
    story.append(Paragraph("Cancelled After Export", h2))
    story.append(Paragraph(
        "Requires GSTR-1 \u00a79C (CDNRA / CDNURA) amendment in a subsequent "
        "filing period \u00b7 \u00a79C emission itself is out of scope for C3.",
        banner_r,
    ))
    rows_src = payload.get("cancelled_after_export", []) or []
    if not rows_src:
        story.append(_empty_placeholder("Cancelled After Export", small))
        return
    rows = [CANCELLED_COL_HEADERS]
    for nt in rows_src:
        rows.append([
            _para(nt.get("note_number", ""), small),
            _para(nt.get("note_date", ""), small),
            _para(nt.get("ntty", ""), small),
            _para(nt.get("customer_name", ""), small),
            _para(nt.get("invoice_number", ""), small),
            _para(_fmt_money(nt.get("total_amount", 0)), small),
            _para((nt.get("cancelled_at", "") or "")[:10], small),
            _para(nt.get("cancelled_reason", "") or "", small),
            _para(nt.get("_advisory", "") or "", small),
        ])
    tbl = _cdn_table(rows, CANCELLED_COL_WIDTHS_MM, small)
    tbl.setStyle(TableStyle([("ALIGN", (5, 0), (5, -1), "RIGHT")]))
    story.append(tbl)
