"""Iter132c C4 · Credit Note / Debit Note Register PDF export (A4 landscape).

Pure projection of the C4 canonical payload. Uses the L2d v3
fresh-flowable `_make_story()` two-pass pattern to eliminate reportlab
flowable-state pollution across counting + real render passes —
proven on Invoice PDF, §9B PDF, and §9A PDF regression suites.

Contract: CONTENT GROWS -> PAGES GROW -> PDF STILL SUCCEEDS.
Never HTTP 500 by volume.

This document is a HUMAN-READABLE WORKING REPORT (not a GST portal
upload file). Statutory portal feed is §9B (LOCKED C3.1/C3.2).
"""
from io import BytesIO
import base64
from datetime import datetime, timezone
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, Image,
)
from reportlab.pdfgen.canvas import Canvas
from ._base import _UNI_FONT, _UNI_FONT_BOLD


ACCENT       = colors.HexColor("#0F766E")   # teal-700 — distinct from §9A blue / §9B amber
ACCENT_LIGHT = colors.HexColor("#CCFBF1")   # teal-100
INK          = colors.HexColor("#111827")
MUTED        = colors.HexColor("#6B7280")
BORDER       = colors.HexColor("#D1D5DB")
BAND         = colors.HexColor("#F1F5F9")
CN_BG        = colors.HexColor("#FEF2F2")   # red-50 · credit
DN_BG        = colors.HexColor("#EFF6FF")   # blue-50 · debit
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
_CONTENT_W_MM = 273.0


# ── Register table columns (14 cols · sum = 273 mm) ────────────────
# Note# widened to 28 mm to render 16-char statutory nt_num as a
# single visual token (mirrors §9B locked pattern). Invoice# 22 mm
# accommodates `AKB/26-27//26-27/0004` (21 chars) via 7pt DejaVu.
REG_COL_HEADERS = [
    "Note #", "Date", "T", "Recipient", "GSTIN",
    "Invoice #", f"Taxable ({_RUPEE})",
    f"CGST ({_RUPEE})", f"SGST ({_RUPEE})", f"IGST ({_RUPEE})",
    f"Total ({_RUPEE})", f"Signed ({_RUPEE})",
    "Reason", "GST",
]
REG_COL_WIDTHS_MM = [28, 16, 6, 30, 22, 22, 18, 16, 16, 16, 20, 20, 36, 7]

# ── By-Reason table (6 cols · sum = 200 mm) ────────────────────────
BY_REASON_COL_HEADERS = [
    "QORVENA Reason", f"{_SECTION}9B Code", "Count",
    "CN Count", "DN Count", f"Total ({_RUPEE})",
]
BY_REASON_COL_WIDTHS_MM = [50, 20, 24, 24, 24, 44]


def _all_col_widths_mm():
    """Aggregate landscape column-width lists for the C4 static
    regression test enforcing the <=273 mm envelope."""
    return [
        ("REGISTER", REG_COL_WIDTHS_MM),
        ("BY_REASON", BY_REASON_COL_WIDTHS_MM),
    ]


# ── Two-pass canvas · Page X of Y footer ─────────────────────────────

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
            f"CN/DN Register {_DOT} Computer-generated {_DOT} "
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
    tbl.setStyle(TableStyle(ops))
    return tbl


def _tint_ops(row_idx: int, kind: str):
    bg = CN_BG if kind == "credit" else DN_BG
    return [("BACKGROUND", (0, row_idx), (-1, row_idx), bg)]


def build_cndn_register_pdf(company: dict, payload: dict) -> bytes:
    """Build the full multi-page PDF and return raw bytes."""
    buf = BytesIO()

    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=12 * mm, bottomMargin=16 * mm,
        title="CN/DN Register",
    )

    styles = getSampleStyleSheet()
    body   = ParagraphStyle("body",   parent=styles["Normal"], fontName=_UNI_FONT,      fontSize=8,  textColor=INK,   leading=10)
    small  = ParagraphStyle("small",  parent=styles["Normal"], fontName=_UNI_FONT,      fontSize=7,  textColor=INK,   leading=9)
    muted  = ParagraphStyle("muted",  parent=styles["Normal"], fontName=_UNI_FONT,      fontSize=7,  textColor=MUTED, leading=9)
    banner = ParagraphStyle("banner", parent=styles["Normal"], fontName=_UNI_FONT_BOLD, fontSize=8,  textColor=INFO,  leading=11)
    h1     = ParagraphStyle("h1",     parent=styles["Heading1"], fontName=_UNI_FONT_BOLD, fontSize=16, textColor=ACCENT, alignment=2, leading=20)
    h2     = ParagraphStyle("h2",     parent=styles["Heading2"], fontName=_UNI_FONT_BOLD, fontSize=11, textColor=INK,   leading=14, spaceBefore=6, spaceAfter=3)

    def _make_story():
        story = []
        _co = company or {}
        period = payload.get("period", {})

        # ── Header band ────────────────────────────────────────
        header_left = [
            Paragraph(f"<b>{_co.get('name','')}</b>", body),
            Paragraph(_co.get("address", "") or "", small),
            Paragraph(
                f"GSTIN: {payload.get('issuer_gstin') or _EMDASH}  {_DOT}  "
                f"State: {payload.get('company_state') or _EMDASH} ({payload.get('company_state_code') or _EMDASH})",
                muted,
            ),
        ]
        header_right = [Paragraph("CN/DN<br/>REGISTER", h1)]
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

        # ── Period + Reconciliation banner ─────────────────────
        recon = payload.get("reconciliation") or {}
        f = payload.get("filters", {})
        recon_ok = bool(recon.get("reconciled"))

        story.append(Paragraph(
            f"<b>Period:</b> {period.get('start','')} to {period.get('end','')}  "
            f"{_DOT}  <b>Kind:</b> {f.get('kind','all')}  "
            f"{_DOT}  <b>Status:</b> {f.get('status','issued')}  "
            f"{_DOT}  <b>Notes:</b> {payload.get('note_count', 0)}",
            body,
        ))
        story.append(Spacer(1, 2 * mm))
        story.append(Paragraph(
            f"<b>Reconciled:</b> {('YES ' + _CHECK) if recon_ok else ('NO ' + _CROSS)}",
            ParagraphStyle("pill", parent=body, fontName=_UNI_FONT_BOLD,
                           fontSize=9, textColor=GOOD if recon_ok else BAD),
        ))
        story.append(Spacer(1, 3 * mm))

        # ── Summary + Tax cards ────────────────────────────────
        k = payload["kpis"]; t = payload["tax_summary"]
        _r = lambda v: f"{_RUPEE} {_fmt_money(v)}"
        left_rows = [
            ["Metric", "Value"],
            ["Total notes",           str(k["total_count"])],
            ["Credit notes",          f"{k['credit_count']}  {_DOT}  {_r(k['credit_total'])}"],
            ["Debit notes",           f"{k['debit_count']}  {_DOT}  {_r(k['debit_total'])}"],
            ["Net receivable change", _r(k["net_amount"])],
            ["Issued / Draft / Cancelled",
             f"{k['issued_count']} / {k['draft_count']} / {k['cancelled_count']}"],
        ]
        right_rows = [
            ["Tax Metric", "Value"],
            ["Taxable",     _r(t["taxable"])],
            ["CGST",        _r(t["cgst"])],
            ["SGST",        _r(t["sgst"])],
            ["IGST",        _r(t["igst"])],
            ["Total",       _r(t["total_amount"])],
        ]
        _summary_style = TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, -1), _UNI_FONT),
            ("FONTNAME", (0, 0), (-1, 0), _UNI_FONT_BOLD),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
            ("INNERGRID", (0, 0), (-1, -1), 0.3, BORDER),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ])
        left_tbl = Table(left_rows, colWidths=[70 * mm, 60 * mm])
        left_tbl.setStyle(_summary_style)
        right_tbl = Table(right_rows, colWidths=[45 * mm, 60 * mm])
        right_tbl.setStyle(_summary_style)
        combo = Table([[left_tbl, right_tbl]], colWidths=[135 * mm, 110 * mm])
        combo.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(combo)
        story.append(Spacer(1, 4 * mm))

        # ── Disclosure banner ──────────────────────────────────
        story.append(Paragraph(
            f"WORKING REPORT of QORVENA's CN/DN dataset. "
            f"NOT a GST portal upload file. Statutory feed is GSTR-1 {_SECTION}9B. "
            f"All values are read verbatim from persisted credit_debit_notes {_DOT} "
            f"NO recompute in this export.",
            banner,
        ))
        story.append(Spacer(1, 4 * mm))

        # ── By-Reason section ──────────────────────────────────
        story.append(Paragraph("By Reason", h2))
        by_reason = payload.get("by_reason", []) or []
        if by_reason:
            rows = [BY_REASON_COL_HEADERS]
            for br in by_reason:
                rows.append([
                    _para(br.get("reason_code", ""), small),
                    _para(br.get("gstr1_9b_reason_code", ""), small),
                    _para(str(int(br.get("count", 0) or 0)), small),
                    _para(str(int(br.get("credit_count", 0) or 0)), small),
                    _para(str(int(br.get("debit_count", 0) or 0)), small),
                    _para(_fmt_money(br.get("total_amount", 0)), small),
                ])
            tbl = _tbl(rows, BY_REASON_COL_WIDTHS_MM)
            for i in (2, 3, 4, 5):
                tbl.setStyle(TableStyle([("ALIGN", (i, 0), (i, -1), "RIGHT")]))
            story.append(tbl)
        else:
            story.append(_empty_placeholder("By Reason", small))

        # ── Register section ───────────────────────────────────
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph(f"Register ({payload.get('note_count', 0)})", h2))
        rows_src = payload.get("rows", []) or []
        if not rows_src:
            story.append(_empty_placeholder("Register", small))
        else:
            rows = [REG_COL_HEADERS]
            row_kinds = []
            for r in rows_src:
                rows.append([
                    _para(r.get("note_number", ""), small),
                    _para(r.get("note_date", ""), small),
                    _para(r.get("ntty", ""), small),
                    _para(r.get("customer_name", ""), small),
                    _para(r.get("customer_gstin", "") or _EMDASH, small),
                    _para(r.get("invoice_number", ""), small),
                    _para(_fmt_money(r.get("subtotal", 0)), small),
                    _para(_fmt_money(r.get("cgst_amount", 0)), small),
                    _para(_fmt_money(r.get("sgst_amount", 0)), small),
                    _para(_fmt_money(r.get("igst_amount", 0)), small),
                    _para(_fmt_money(r.get("total_amount", 0)), small),
                    _para(_fmt_money(r.get("signed_amount", 0)), small),
                    _para(
                        f"{r.get('reason_code','') or ''} "
                        f"{_DOT} {_SECTION}9B {r.get('reason_code_gstr1_9b','') or ''}",
                        small,
                    ),
                    _para("Y" if r.get("apply_gst") else "N", small),
                ])
                row_kinds.append(r.get("kind"))
            tbl = _tbl(rows, REG_COL_WIDTHS_MM)
            for i, k_ in enumerate(row_kinds, start=1):
                tbl.setStyle(TableStyle(_tint_ops(i, k_)))
            for i in (6, 7, 8, 9, 10, 11):
                tbl.setStyle(TableStyle([("ALIGN", (i, 0), (i, -1), "RIGHT")]))
            story.append(tbl)

        # ── Warnings ───────────────────────────────────────────
        warns = payload.get("warnings", []) or []
        if warns:
            story.append(Spacer(1, 4 * mm))
            story.append(Paragraph("Warnings", h2))
            for w in warns:
                story.append(Paragraph(f"{_BULLET} {w}", small))

        return story

    doc.build(_make_story(), canvasmaker=NumberedCanvas)
    return buf.getvalue()
