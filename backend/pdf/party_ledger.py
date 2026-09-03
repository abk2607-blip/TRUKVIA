"""Iter135A · Vendor / Mechanic Ledger PDF — ERP presentation polish.

Consumes the authoritative LedgerDataset produced by
`services_party_ledger.build_party_ledger` verbatim — NO independent
accounting math anywhere in this module.

Presentation upgrades over Iter135:
  · Company logo (base64 data URL, `company.logo`) rendered in the
    header with graceful fallback when missing/invalid.
  · Two-column branded header (logo + name + address + GSTIN on the
    left, document title + party card on the right).
  · Statement-info strip with subtle typography.
  · Ledger table with tighter proportions, tabular numerals, right-
    aligned money, colored Closing Balance strip.
  · Reversed rows retained with strike-through / muted grey.
  · Two-pass `NumberedCanvas` for `Page X of Y` (unchanged).
  · Vehicle number rendered as a hyperlink to
    `<CANONICAL_APP_URL>/vehicles/<vehicle_id>/repair-history` when
    the app-url env var is present. PDF generation never fails if the
    hyperlink URL cannot be constructed.
"""
from __future__ import annotations
import base64, os
from io import BytesIO
from datetime import datetime, timezone

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, Image,
)
from reportlab.pdfgen.canvas import Canvas

from ._base import _UNI_FONT, _UNI_FONT_BOLD, _fmt_ind_date

INK          = colors.HexColor("#0F172A")
INK_MID      = colors.HexColor("#334155")
MUTED        = colors.HexColor("#6B7280")
BORDER       = colors.HexColor("#E2E8F0")
BORDER_STRONG= colors.HexColor("#94A3B8")
STRIPE       = colors.HexColor("#F8FAFC")
HEAD_BG      = colors.HexColor("#0F172A")
HEAD_FG      = colors.white
ACCENT       = colors.HexColor("#1E293B")
CLOSE_HL     = colors.HexColor("#EEF2FF")   # Closing strip highlight
LINK_BLUE    = colors.HexColor("#1D4ED8")
REV_MUTED    = colors.HexColor("#9CA3AF")


class _NumberedCanvas(Canvas):
    """Two-pass canvas — stamps `Page X of Y` on every page (unchanged
    from Iter135). Performs NO accounting math."""

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
        self.setStrokeColor(BORDER)
        self.setLineWidth(0.3)
        self.line(10 * mm, 10 * mm, A4[0] - 10 * mm, 10 * mm)
        self.setFont(_UNI_FONT, 7.5)
        self.setFillColor(MUTED)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.drawString(
            10 * mm, 6.5 * mm,
            "Computer-generated accounting statement · This is not a demand notice.",
        )
        self.drawRightString(
            A4[0] - 10 * mm, 6.5 * mm,
            f"Page {self._pageNumber} of {total}  ·  Printed {stamp}",
        )


def _inr(x, zero_dash: bool = True) -> str:
    """Money format — accounting-friendly. Zero renders as '—' by default
    (for the Debit/Credit columns to visually declutter); Closing / totals
    call with zero_dash=False so ₹0.00 renders explicitly."""
    try:
        n = float(x or 0)
    except Exception:
        return "—"
    if n == 0 and zero_dash:
        return "—"
    sign = "-" if n < 0 else ""
    return f"{sign}₹{abs(n):,.2f}"


def _para(txt: str, size: float = 8.5, bold: bool = False,
          color=INK, align: str = "LEFT") -> Paragraph:
    return Paragraph(
        str(txt or "").replace("\n", "<br/>"),
        ParagraphStyle(
            "p", fontName=_UNI_FONT_BOLD if bold else _UNI_FONT,
            fontSize=size, leading=size + 2.5, textColor=color,
            alignment={"LEFT": 0, "CENTER": 1, "RIGHT": 2}[align],
        ),
    )


def _logo_image(company: dict) -> Image | None:
    """Decode the canonical base64 data-URL logo into a print-safe Image.
    Never raises — returns None on any decoding issue so PDF renders
    with a text-only fallback."""
    raw = (company or {}).get("logo") or ""
    if not raw.startswith("data:image"):
        return None
    try:
        b64 = raw.split(",", 1)[1]
        data = base64.b64decode(b64)
        img = Image(BytesIO(data), width=22 * mm, height=22 * mm,
                    kind="proportional")
        return img
    except Exception:
        return None


def _company_block(dataset: dict) -> Table:
    company = dataset.get("company") or {}
    logo = _logo_image(company)
    lines = [
        _para(company.get("name") or "Company", size=13, bold=True, color=INK),
    ]
    addr = company.get("address") or ""
    if addr:
        lines.append(_para(addr, size=8, color=MUTED))
    misc: list[str] = []
    if company.get("gstin"):
        misc.append(f"GSTIN {company['gstin']}")
    if company.get("phone"):
        misc.append(str(company["phone"]))
    if company.get("email"):
        misc.append(str(company["email"]))
    if misc:
        lines.append(_para("  ·  ".join(misc), size=8, color=MUTED))

    if logo is not None:
        left = Table([[logo, lines]], colWidths=[26 * mm, 84 * mm])
        left.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]))
    else:
        left = Table([[lines]], colWidths=[110 * mm])
        left.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0),
                                  ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))

    title = "VENDOR LEDGER" if dataset.get("party_type") == "vendor" else "MECHANIC LEDGER"
    right = [
        _para(title, size=15, bold=True, align="RIGHT", color=ACCENT),
        Spacer(1, 2 * mm),
        _para(f"Party  ·  {dataset.get('party_name') or '—'}", size=10, bold=True,
              align="RIGHT", color=INK_MID),
    ]
    if dataset.get("party_gstin"):
        right.append(_para(f"GSTIN  ·  {dataset['party_gstin']}", size=8,
                           align="RIGHT", color=MUTED))

    outer = Table([[left, right]], colWidths=[110 * mm, 80 * mm])
    outer.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("LINEBELOW", (0, 0), (-1, -1), 0.8, INK),
    ]))
    return outer


def _statement_info(dataset: dict) -> Table:
    df = _fmt_ind_date(dataset.get("from")) if dataset.get("from") else "All"
    dt = _fmt_ind_date(dataset.get("to")) if dataset.get("to") else "Today"
    ob = float(dataset.get("opening_balance") or 0)
    ob_type = (dataset.get("opening_balance_type") or "payable").title()
    rev = "Yes" if dataset.get("include_reversed") else "No"
    printed = datetime.now(timezone.utc).strftime("%d-%b-%Y")

    def _pair(label: str, value: str, bold: bool = False, color=INK):
        return [_para(label.upper(), size=6.5, color=MUTED, bold=True),
                _para(value, size=9.5 if bold else 9, bold=bold, color=color)]

    row1 = [
        _pair("Statement Period", f"{df} — {dt}", bold=True),
        _pair("Account Type", ob_type),
        _pair("Opening Balance", _inr(ob, zero_dash=False), bold=True),
        _pair("Include Reversed", rev),
        _pair("Printed", printed),
    ]
    # Flatten into two rows (label row + value row).
    labels = [c[0] for c in row1]
    values = [c[1] for c in row1]
    t = Table([labels, values],
              colWidths=[42 * mm, 30 * mm, 40 * mm, 30 * mm, 48 * mm])
    t.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, 0), 4),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 1),
        ("TOPPADDING", (0, 1), (-1, 1), 0),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 4),
        ("BACKGROUND", (0, 0), (-1, -1), STRIPE),
        ("BOX", (0, 0), (-1, -1), 0.4, BORDER),
    ]))
    return t


def _vehicle_display(entry: dict) -> str:
    veh = entry.get("vehicle_number") or ""
    if veh:
        return veh
    if entry.get("kind") == "payment" and (entry.get("against") in
                                           ("outstanding", "advance", "other", "")):
        return "— Unallocated"
    return "—"


def _vehicle_hyperlink(entry: dict, base_url: str) -> str | None:
    if not base_url:
        return None
    vid = entry.get("vehicle_id") or ""
    if not vid or not entry.get("vehicle_number"):
        return None
    return f"{base_url.rstrip('/')}/vehicles/{vid}/repair-history"


def _entries_table(dataset: dict, base_url: str) -> Table:
    header = [
        _para("Date",        size=8.5, bold=True, color=HEAD_FG),
        _para("Type",        size=8.5, bold=True, color=HEAD_FG),
        _para("Ref",         size=8.5, bold=True, color=HEAD_FG),
        _para("Vehicle",     size=8.5, bold=True, color=HEAD_FG),
        _para("Description", size=8.5, bold=True, color=HEAD_FG),
        _para("Debit",       size=8.5, bold=True, color=HEAD_FG, align="RIGHT"),
        _para("Credit",      size=8.5, bold=True, color=HEAD_FG, align="RIGHT"),
        _para("Balance",     size=8.5, bold=True, color=HEAD_FG, align="RIGHT"),
    ]

    rows: list[list] = [header]
    reversed_rows: list[int] = []
    for idx, e in enumerate(dataset.get("entries") or [], start=1):
        text_color = REV_MUTED if e.get("is_reversed") else INK
        veh_text = _vehicle_display(e)
        veh_url = _vehicle_hyperlink(e, base_url)
        if veh_url:
            veh_cell = _para(
                f'<link href="{veh_url}"><font color="#1D4ED8">{veh_text}</font></link>',
                size=8, color=LINK_BLUE)
        else:
            veh_cell = _para(veh_text, size=8,
                             color=MUTED if veh_text in ("— Unallocated", "—") else text_color)
        rows.append([
            _para(_fmt_ind_date(e.get("date")), size=8, color=text_color),
            _para(e.get("type_label") or (e.get("kind") or "").title(),
                  size=8, color=text_color, bold=e.get("kind") == "opening"),
            _para(e.get("ref") or "", size=7.5, color=text_color),
            veh_cell,
            _para(e.get("narration") or "", size=7.5, color=text_color),
            _para(_inr(e.get("debit")),   size=8, color=text_color, align="RIGHT"),
            _para(_inr(e.get("credit")),  size=8, color=text_color, align="RIGHT"),
            _para(_inr(e.get("balance"), zero_dash=False), size=8,
                  color=text_color, bold=True, align="RIGHT"),
        ])
        if e.get("is_reversed"):
            reversed_rows.append(idx)

    if len(rows) == 1:
        rows.append([_para("No transactions in the selected range.",
                           size=9.5, color=MUTED, align="CENTER")] + [""] * 7)

    col_widths = [
        20 * mm,  # Date
        22 * mm,  # Type
        26 * mm,  # Ref
        26 * mm,  # Vehicle
        36 * mm,  # Description
        20 * mm,  # Debit
        20 * mm,  # Credit
        20 * mm,  # Balance
    ]
    t = Table(rows, colWidths=col_widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
        ("TEXTCOLOR",  (0, 0), (-1, 0), HEAD_FG),
        ("LINEABOVE",  (0, 0), (-1, 0), 0.6, HEAD_BG),
        ("LINEBELOW",  (0, 0), (-1, 0), 0.6, HEAD_BG),
        ("BOX",         (0, 0), (-1, -1), 0.4, BORDER_STRONG),
        ("INNERGRID",   (0, 0), (-1, -1), 0.2, BORDER),
        ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING",(0, 0), (-1, -1), 5),
        ("TOPPADDING",  (0, 0), (-1, 0), 5),
        ("BOTTOMPADDING",(0, 0), (-1, 0), 5),
        ("TOPPADDING",  (0, 1), (-1, -1), 4),
        ("BOTTOMPADDING",(0, 1), (-1, -1), 4),
    ]
    # Zebra striping on body rows.
    for i in range(1, len(rows)):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), STRIPE))
    for r in reversed_rows:
        style.append(("LINEABOVE", (0, r), (-1, r), 0.3, REV_MUTED))
        style.append(("LINEBELOW", (0, r), (-1, r), 0.3, REV_MUTED))
    t.setStyle(TableStyle(style))
    return t


def _accounting_summary(dataset: dict) -> Table:
    closing = float(dataset.get("closing_balance") or 0)
    outstanding = float(dataset.get("outstanding") or 0)
    advance = float(dataset.get("advance") or 0)
    # Payable-side or advance emphasis.
    summary_line = f"{_inr(outstanding, zero_dash=False)} payable" if outstanding > 0 \
                   else f"{_inr(advance, zero_dash=False)} in advance" if advance > 0 \
                   else "Nil balance"

    left = [
        [_para("Opening Balance", size=7, color=MUTED, bold=True),
         _para(_inr(dataset.get("opening_balance"), zero_dash=False),
               size=10, bold=True)],
        [_para("Total Debit", size=7, color=MUTED, bold=True),
         _para(_inr(dataset.get("total_debit"), zero_dash=False),
               size=10, bold=True)],
        [_para("Total Credit", size=7, color=MUTED, bold=True),
         _para(_inr(dataset.get("total_credit"), zero_dash=False),
               size=10, bold=True)],
    ]
    left_t = Table(left, colWidths=[35 * mm, 40 * mm])
    left_t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.4, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.2, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))

    right_top = _para("CLOSING BALANCE", size=8, bold=True, color=MUTED, align="RIGHT")
    right_amount = _para(_inr(closing, zero_dash=False), size=18, bold=True,
                         color=ACCENT, align="RIGHT")
    right_note = _para(summary_line, size=9, color=INK_MID, align="RIGHT")
    right = Table([[right_top], [right_amount], [right_note]],
                  colWidths=[95 * mm])
    right.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CLOSE_HL),
        ("BOX", (0, 0), (-1, -1), 0.6, ACCENT),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, 0), 6),
        ("TOPPADDING", (0, 1), (-1, 1), 0),
        ("BOTTOMPADDING", (0, 2), (-1, 2), 6),
    ]))

    outer = Table([[left_t, right]], colWidths=[75 * mm, 115 * mm])
    outer.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return outer


def build_party_ledger_pdf(dataset: dict) -> bytes:
    """Render a printable A4 party ledger from the authoritative dataset.

    Zero recomputation: every displayed figure is a projection of a
    dataset value.  Guaranteed reconciliation with the JSON endpoint.
    """
    base_url = (os.environ.get("APP_PUBLIC_URL")
                or os.environ.get("REACT_APP_BACKEND_URL")
                or "").strip()
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=10 * mm, rightMargin=10 * mm,
        topMargin=10 * mm, bottomMargin=14 * mm,
        title=(f"{'Vendor' if dataset.get('party_type') == 'vendor' else 'Mechanic'} "
               f"Ledger · {dataset.get('party_name') or ''}"),
    )
    story = [
        _company_block(dataset),
        Spacer(1, 4 * mm),
        _statement_info(dataset),
        Spacer(1, 4 * mm),
        _entries_table(dataset, base_url),
        Spacer(1, 5 * mm),
        _accounting_summary(dataset),
    ]
    doc.build(story, canvasmaker=_NumberedCanvas)
    return buf.getvalue()
