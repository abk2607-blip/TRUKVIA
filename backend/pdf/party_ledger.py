"""Iter135 · Vendor / Mechanic Ledger PDF renderer.

Consumes the authoritative LedgerDataset produced by
`services_party_ledger.build_party_ledger` verbatim — this module
performs NO independent accounting math.  It only projects the dataset
into a printable A4 statement.

Layout (A4 portrait · 210 × 297 mm · inner 190 × 277 mm):
  · Company header (name / GSTIN / address if present)
  · Party header (Vendor Ledger / Mechanic Ledger · Party name · GSTIN)
  · Date-range + Opening Balance strip
  · Transaction table:
       Date | Type | Ref | Vehicle | Description | Debit | Credit | Balance
       — table header repeats on every page
  · Totals summary strip (Debit / Credit / Closing / Outstanding · Advance)
  · Two-pass canvas footer with `Page X of Y · Printed YYYY-MM-DD`
"""
from __future__ import annotations
from io import BytesIO
from datetime import datetime, timezone

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer,
)
from reportlab.pdfgen.canvas import Canvas

from ._base import _UNI_FONT, _UNI_FONT_BOLD, _fmt_ind_date

INK        = colors.HexColor("#111827")
MUTED      = colors.HexColor("#6B7280")
BORDER     = colors.HexColor("#D1D5DB")
STRIPE     = colors.HexColor("#F9FAFB")
ACCENT     = colors.HexColor("#1F2937")
REV_MUTED  = colors.HexColor("#9CA3AF")


class _NumberedCanvas(Canvas):
    """Two-pass canvas — draws 'Page X of Y · Printed …' footer.

    IMPORTANT: this canvas does NOT recompute any ledger figures. It only
    stamps the page footer during the second pass so `X of Y` is correct.
    """

    def __init__(self, *a, **kw):
        Canvas.__init__(self, *a, **kw)
        self._saved: list[dict] = []

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

    def _draw_footer(self, total: int) -> None:
        self.setFont(_UNI_FONT, 7)
        self.setFillColor(MUTED)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.drawCentredString(
            A4[0] / 2, 8 * mm,
            f"Computer-generated statement · Page {self._pageNumber} of {total} · Printed {stamp}",
        )


def _inr(x) -> str:
    try:
        n = float(x or 0)
    except Exception:
        return "—"
    if n == 0:
        return "—"
    sign = "-" if n < 0 else ""
    return f"{sign}₹{abs(n):,.2f}"


def _para(txt: str, size: int = 8.5, bold: bool = False,
          color=INK, align="LEFT") -> Paragraph:
    return Paragraph(
        str(txt or "").replace("\n", "<br/>"),
        ParagraphStyle(
            "p", fontName=_UNI_FONT_BOLD if bold else _UNI_FONT,
            fontSize=size, leading=size + 2, textColor=color,
            alignment={"LEFT": 0, "CENTER": 1, "RIGHT": 2}[align],
        ),
    )


def _company_header_table(dataset: dict) -> Table:
    company = dataset.get("company") or {}
    left = [
        _para(company.get("name") or "Company", size=12, bold=True),
        _para(company.get("address") or "", size=8, color=MUTED),
        _para((f"GSTIN: {company.get('gstin')}" if company.get("gstin") else ""),
              size=8, color=MUTED),
    ]
    title = "Vendor Ledger" if dataset.get("party_type") == "vendor" else "Mechanic Ledger"
    right = [
        _para(title, size=13, bold=True, align="RIGHT", color=ACCENT),
        _para(f"Party: {dataset.get('party_name') or '—'}", size=9, align="RIGHT"),
        _para((f"GSTIN: {dataset.get('party_gstin')}" if dataset.get('party_gstin') else ""),
              size=8, color=MUTED, align="RIGHT"),
    ]
    t = Table([[left, right]], colWidths=[110 * mm, 80 * mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


def _period_strip(dataset: dict) -> Table:
    df = _fmt_ind_date(dataset.get("from")) if dataset.get("from") else "All"
    dt = _fmt_ind_date(dataset.get("to")) if dataset.get("to") else "Today"
    period = f"{df} — {dt}"

    reversed_label = "Yes" if dataset.get("include_reversed") else "No"
    ob_type = (dataset.get("opening_balance_type") or "payable").title()
    ob = float(dataset.get("opening_balance") or 0)

    cells = [
        [_para("Period", size=7, color=MUTED, bold=True),
         _para("Include Reversed", size=7, color=MUTED, bold=True),
         _para("Opening Balance Type", size=7, color=MUTED, bold=True),
         _para("Opening Balance", size=7, color=MUTED, bold=True)],
        [_para(period, size=9, bold=True),
         _para(reversed_label, size=9),
         _para(ob_type, size=9),
         _para(_inr(ob) if ob else "—", size=9, bold=True)],
    ]
    t = Table(cells, colWidths=[60 * mm, 35 * mm, 45 * mm, 50 * mm])
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.4, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, BORDER),
        ("BACKGROUND", (0, 0), (-1, 0), STRIPE),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def _entries_table(dataset: dict) -> Table:
    """The transaction table.  Header repeats on every page via `repeatRows=1`.
    All numbers come STRAIGHT from the dataset — no recomputation."""
    header = [
        _para("Date", size=8.5, bold=True, color=INK),
        _para("Type", size=8.5, bold=True, color=INK),
        _para("Ref", size=8.5, bold=True, color=INK),
        _para("Vehicle", size=8.5, bold=True, color=INK),
        _para("Description", size=8.5, bold=True, color=INK),
        _para("Debit", size=8.5, bold=True, color=INK, align="RIGHT"),
        _para("Credit", size=8.5, bold=True, color=INK, align="RIGHT"),
        _para("Balance", size=8.5, bold=True, color=INK, align="RIGHT"),
    ]

    rows: list[list] = [header]
    reversed_rows: list[int] = []
    for idx, e in enumerate(dataset.get("entries") or [], start=1):
        vehicle = e.get("vehicle_number") or ""
        if not vehicle and e.get("kind") == "payment" and (e.get("against") in
                                                           ("outstanding", "advance", "other", "")):
            vehicle = "— Unallocated"
        elif not vehicle:
            vehicle = "—"
        # Style hint for reversed rows.
        text_color = REV_MUTED if e.get("is_reversed") else INK
        rows.append([
            _para(_fmt_ind_date(e.get("date")), size=8, color=text_color),
            _para(e.get("type_label") or (e.get("kind") or "").title(), size=8, color=text_color),
            _para(e.get("ref") or "", size=7.5, color=text_color),
            _para(vehicle, size=8, color=text_color),
            _para(e.get("narration") or "", size=7.5, color=text_color),
            _para(_inr(e.get("debit")), size=8, color=text_color, align="RIGHT"),
            _para(_inr(e.get("credit")), size=8, color=text_color, align="RIGHT"),
            _para(_inr(e.get("balance")), size=8, color=text_color, bold=True, align="RIGHT"),
        ])
        if e.get("is_reversed"):
            reversed_rows.append(idx)

    if len(rows) == 1:  # no entries
        rows.append([_para("No transactions in the selected range.",
                           size=9, color=MUTED, align="CENTER")] + [""] * 7)

    col_widths = [
        20 * mm,   # Date
        22 * mm,   # Type
        26 * mm,   # Ref
        24 * mm,   # Vehicle
        38 * mm,   # Description
        20 * mm,   # Debit
        20 * mm,   # Credit
        20 * mm,   # Balance
    ]
    t = Table(rows, colWidths=col_widths, repeatRows=1)
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F3F4F6")),
        ("BOX", (0, 0), (-1, -1), 0.4, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    for r in reversed_rows:
        style_cmds.append(("LINEABOVE", (0, r), (-1, r), 0.3, REV_MUTED))
        style_cmds.append(("LINEBELOW", (0, r), (-1, r), 0.3, REV_MUTED))
    t.setStyle(TableStyle(style_cmds))
    return t


def _totals_strip(dataset: dict) -> Table:
    """Totals card — reads directly from the dataset (no recomputation)."""
    cells = [[
        _para("Total Debit", size=7, color=MUTED, bold=True),
        _para("Total Credit", size=7, color=MUTED, bold=True),
        _para("Closing Balance", size=7, color=MUTED, bold=True),
        _para("Outstanding · Advance", size=7, color=MUTED, bold=True),
    ], [
        _para(_inr(dataset.get("total_debit")), size=10, bold=True),
        _para(_inr(dataset.get("total_credit")), size=10, bold=True),
        _para(_inr(dataset.get("closing_balance")), size=11, bold=True, color=ACCENT),
        _para(
            f"{_inr(dataset.get('outstanding'))}  ·  {_inr(dataset.get('advance'))}",
            size=9, bold=True,
        ),
    ]]
    t = Table(cells, colWidths=[45 * mm, 45 * mm, 50 * mm, 50 * mm])
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.4, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, BORDER),
        ("BACKGROUND", (0, 0), (-1, 0), STRIPE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def build_party_ledger_pdf(dataset: dict) -> bytes:
    """Render a printable A4 party ledger from the authoritative dataset.

    Zero recomputation: every displayed figure is a projection of a
    dataset value.  Guaranteed reconciliation with the JSON endpoint.
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=10 * mm, rightMargin=10 * mm,
        topMargin=10 * mm, bottomMargin=14 * mm,
        title=(f"{'Vendor' if dataset.get('party_type') == 'vendor' else 'Mechanic'} "
               f"Ledger · {dataset.get('party_name') or ''}"),
    )
    story = [
        _company_header_table(dataset),
        Spacer(1, 4 * mm),
        _period_strip(dataset),
        Spacer(1, 4 * mm),
        _entries_table(dataset),
        Spacer(1, 4 * mm),
        _totals_strip(dataset),
    ]
    doc.build(story, canvasmaker=_NumberedCanvas)
    return buf.getvalue()
