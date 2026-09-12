"""Iter133 L2 · Redesigned Customer Ledger PDF (A4 portrait).

Professional customer-facing statement:
  · Company logo + branded header
  · Customer info block (GSTIN, phone, state, address)
  · Period + Balance Summary card
  · totals_by_type breakdown pills (from L1 payload)
  · Ledger table with per-row type tint (CN=red, DN=blue)
  · Adjustments summary line (when notes exist)
  · Amount-in-words on closing balance
  · Authorised Signatory + page footer with page numbering

Zero API-contract change: consumes the L1 payload dict as-is.
Zero business-logic change.
"""
from ._base import _fmt, _num_to_words_inr, _UNI_FONT, _UNI_FONT_BOLD
from io import BytesIO
import base64
from datetime import datetime, timezone
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, Image,
)
from reportlab.pdfgen.canvas import Canvas

ACCENT       = colors.HexColor("#B45309")   # amber-700
ACCENT_LIGHT = colors.HexColor("#FEF3C7")   # amber-100
INK          = colors.HexColor("#111827")
MUTED        = colors.HexColor("#6B7280")
BORDER       = colors.HexColor("#D1D5DB")
CN_BG        = colors.HexColor("#FEF2F2")   # red-50
DN_BG        = colors.HexColor("#EFF6FF")   # blue-50


class NumberedCanvas(Canvas):
    """Two-pass canvas — draws 'Page X of Y · Printed …' footer."""
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
        self.drawCentredString(
            105 * mm, 8 * mm,
            f"TRUKVIA · Computer-generated statement · Page {self._pageNumber} of {total} · Printed {stamp}",
        )


def _logo_flowable(company: dict, target_h_mm=18):
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


def build_ledger_pdf(company: dict, ledger: dict) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=12 * mm, bottomMargin=16 * mm,
        title="Customer Statement",
    )
    styles = getSampleStyleSheet()
    small = ParagraphStyle("s", parent=styles["Normal"], fontName=_UNI_FONT,      fontSize=8, textColor=INK,   leading=10)
    muted = ParagraphStyle("m", parent=styles["Normal"], fontName=_UNI_FONT,      fontSize=8, textColor=MUTED, leading=10)
    body  = ParagraphStyle("b", parent=styles["Normal"], fontName=_UNI_FONT,      fontSize=9, textColor=INK,   leading=12)
    title = ParagraphStyle("t", parent=styles["Heading1"], fontName=_UNI_FONT_BOLD, fontSize=16, textColor=ACCENT, alignment=2, leading=20)
    label = ParagraphStyle("l", parent=styles["Normal"], fontName=_UNI_FONT_BOLD, fontSize=7, textColor=MUTED, leading=9, spaceAfter=1)
    story = []

    _co       = company or {}
    _co_gst   = (_co.get("gstin") or "").strip() or "—"
    _co_state = (_co.get("state") or "").strip() or "—"

    # ------------------------ Header ------------------------
    company_lines = [
        Paragraph(f"<b>{_co.get('name','')}</b>", body),
        Paragraph(_co.get("address", ""), small),
        Paragraph(f"GSTIN: {_co_gst} · State: {_co_state}", muted),
    ]
    header = Table(
        [[_logo_flowable(_co), company_lines, [Paragraph("CUSTOMER<br/>STATEMENT", title)]]],
        colWidths=[45 * mm, 90 * mm, 51 * mm],
    )
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(header)
    story.append(Spacer(1, 4 * mm))

    # Accent divider
    div = Table([[""]], colWidths=[186 * mm], rowHeights=[3])
    div.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), ACCENT)]))
    story.append(div)
    story.append(Spacer(1, 3 * mm))

    # ------------------------ Bill-To + Period + Closing ------------------------
    customer = ledger.get("customer", {}) or {}
    period   = ledger.get("period", {}) or {}
    cust_lines = [
        Paragraph("BILL TO", label),
        Paragraph(f"<b>{customer.get('name','')}</b>", body),
        Paragraph(f"GSTIN: {customer.get('gstin') or '—'}", small),
        Paragraph(f"Phone: {customer.get('phone') or '—'} · State: {customer.get('state') or '—'}", small),
        Paragraph(customer.get("address", "") or "", small),
    ]
    period_lines = [
        Paragraph("STATEMENT PERIOD", label),
        Paragraph(f"<b>{period.get('start') or 'Beginning'}</b> to <b>{period.get('end') or 'Today'}</b>", body),
        Spacer(1, 2 * mm),
        Paragraph("CLOSING BALANCE", label),
        Paragraph(
            f"<b>₹ {_fmt(ledger.get('closing_balance', 0))}</b>",
            ParagraphStyle("cb", parent=body, fontName=_UNI_FONT_BOLD, fontSize=13, textColor=ACCENT),
        ),
    ]
    info = Table([[cust_lines, period_lines]], colWidths=[110 * mm, 76 * mm])
    info.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(info)
    story.append(Spacer(1, 4 * mm))

    # ------------------------ totals_by_type pills (L1 payload) ------------------------
    tbt = ledger.get("totals_by_type") or {}
    if tbt:
        def pill(lbl, val):
            return [Paragraph(f"<font color='#6B7280'>{lbl}</font><br/><b>₹ {_fmt(val)}</b>", small)]
        pills = Table([[
            pill("INVOICED",     tbt.get("invoice", 0)),
            pill("DEBIT NOTES",  tbt.get("debit_note", 0)),
            pill("CREDIT NOTES", tbt.get("credit_note", 0)),
            pill("PAYMENTS",     tbt.get("payment", 0)),
        ]], colWidths=[46.5 * mm] * 4)
        pills.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#F3F4F6")),
            ("BACKGROUND", (1, 0), (1, 0), DN_BG),
            ("BACKGROUND", (2, 0), (2, 0), CN_BG),
            ("BACKGROUND", (3, 0), (3, 0), colors.HexColor("#ECFDF5")),
            ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
            ("INNERGRID", (0, 0), (-1, -1), 0.3, BORDER),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(pills)
        story.append(Spacer(1, 3 * mm))

        cn_amt = float(tbt.get("credit_note", 0) or 0)
        dn_amt = float(tbt.get("debit_note", 0) or 0)
        if cn_amt or dn_amt:
            parts = []
            if cn_amt: parts.append(f"<font color='#B91C1C'>−₹{_fmt(cn_amt)} (Credit Notes)</font>")
            if dn_amt: parts.append(f"<font color='#1D4ED8'>+₹{_fmt(dn_amt)} (Debit Notes)</font>")
            story.append(Paragraph("Adjustments this period: " + " · ".join(parts), small))
            story.append(Spacer(1, 3 * mm))

    # ------------------------ Ledger table ------------------------
    rows = [["Date", "Ref", "Particulars", "Debit (₹)", "Credit (₹)", "Balance (₹)"]]
    rows.append(["", "", "Opening Balance", "", "", _fmt(ledger.get("opening_balance", 0))])
    row_types = ["_open"]
    for e in ledger.get("entries", []):
        # Iter133 L2d · Wrap Ref + Particulars in Paragraph so long invoice
        # numbers (e.g., "AKB/26-27//26-27/0004") and long CN/DN narrations
        # wrap gracefully within their column instead of spilling into the
        # adjacent Debit / numeric columns. Numeric columns stay raw for
        # right-alignment fidelity.
        rows.append([
            e.get("date", ""),
            Paragraph(str(e.get("reference", "") or ""), small),
            Paragraph(str(e.get("particulars", "") or ""), small),
            _fmt(e.get("debit", 0)) if e.get("debit", 0) else "",
            _fmt(e.get("credit", 0)) if e.get("credit", 0) else "",
            _fmt(e.get("balance", 0)),
        ])
        row_types.append(e.get("type", ""))
    rows.append(["", "", "TOTAL", _fmt(ledger.get("total_debit", 0)), _fmt(ledger.get("total_credit", 0)), ""])
    rows.append(["", "", "Closing Balance", "", "", _fmt(ledger.get("closing_balance", 0))])
    row_types.extend(["_total", "_close"])

    # Iter133 L2d · Rebalance: give Ref 8mm more (26→34) so long invoice
    # numbers fit; reclaim from Particulars (61→53). Numeric columns and
    # total table width unchanged.
    tbl = Table(rows, colWidths=[19 * mm, 34 * mm, 53 * mm, 24 * mm, 24 * mm, 24 * mm], repeatRows=1)
    tstyle = [
        ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), _UNI_FONT_BOLD),
        ("TOPPADDING", (0, 0), (-1, 0), 6),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("FONTNAME", (0, 1), (-1, -1), _UNI_FONT),
        ("FONTNAME", (0, 1), (-1, 1), _UNI_FONT_BOLD),
        ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#F9FAFB")),
        ("FONTNAME", (0, -2), (-1, -2), _UNI_FONT_BOLD),
        ("BACKGROUND", (0, -2), (-1, -2), colors.HexColor("#F9FAFB")),
        ("LINEABOVE", (0, -2), (-1, -2), 1, BORDER),
        ("FONTNAME", (0, -1), (-1, -1), _UNI_FONT_BOLD),
        ("FONTSIZE", (0, -1), (-1, -1), 10),
        ("BACKGROUND", (0, -1), (-1, -1), ACCENT_LIGHT),
        ("LINEABOVE", (0, -1), (-1, -1), 1.5, ACCENT),
        ("TOPPADDING", (0, -1), (-1, -1), 6),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 6),
        ("FONTSIZE", (0, 0), (-1, -2), 8),
        ("ALIGN", (3, 1), (5, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (3, 0), (5, -1), 6),
        ("TOPPADDING", (0, 1), (-1, -3), 3),
        ("BOTTOMPADDING", (0, 1), (-1, -3), 3),
    ]
    # Per-row background tint for CN/DN entries
    for idx, rt in enumerate(row_types):
        if rt == "credit_note":
            tstyle.append(("BACKGROUND", (0, idx), (-1, idx), CN_BG))
        elif rt == "debit_note":
            tstyle.append(("BACKGROUND", (0, idx), (-1, idx), DN_BG))
    tbl.setStyle(TableStyle(tstyle))
    story.append(tbl)

    # Amount-in-words
    story.append(Spacer(1, 4 * mm))
    cb = float(ledger.get("closing_balance", 0))
    words = _num_to_words_inr(abs(cb))
    story.append(Paragraph(
        f"<b>Amount in Words:</b> {words} ({'Dr' if cb >= 0 else 'Cr'})",
        small,
    ))

    # Signatory
    story.append(Spacer(1, 6 * mm))
    sig = Table([[
        "",
        [Paragraph(f"For <b>{_co.get('name','')}</b>", body),
         Spacer(1, 10 * mm),
         Paragraph("Authorised Signatory", small)],
    ]], colWidths=[110 * mm, 76 * mm])
    sig.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(sig)

    doc.build(story, canvasmaker=NumberedCanvas)
    return buf.getvalue()
