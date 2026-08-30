from ._base import (
    _fmt, _num_to_words_inr,
    _UNI_FONT, _UNI_FONT_BOLD,
)
from io import BytesIO
import base64
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, KeepTogether, Image, PageBreak,
)

def build_ledger_pdf(company: dict, ledger: dict) -> bytes:
    """Ledger statement PDF for a customer with running balance."""
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=10 * mm, bottomMargin=10 * mm,
        title="Customer Ledger",
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="H1L", fontName=_UNI_FONT_BOLD, fontSize=16, leading=20))
    styles.add(ParagraphStyle(name="BodyL", fontName=_UNI_FONT, fontSize=9, leading=12))
    styles.add(ParagraphStyle(name="SmallL", fontName=_UNI_FONT, fontSize=8, leading=10))
    story = []

    company_name = company.get("name") or "YOUR COMPANY NAME"
    customer = ledger.get("customer", {})
    period = ledger.get("period", {})

    header = f"<b>{company_name}</b><br/>{company.get('address','')}<br/>GSTIN: {company.get('gstin','—')}"
    story.append(Paragraph(header, styles["BodyL"]))
    story.append(Spacer(1, 6))
    story.append(Paragraph("<b>Customer Ledger Statement</b>", styles["H1L"]))
    story.append(Paragraph(
        f"Customer: <b>{customer.get('name','')}</b> · GSTIN: {customer.get('gstin','—')}<br/>"
        f"Period: {period.get('start') or 'Beginning'} to {period.get('end') or 'Today'}",
        styles["BodyL"],
    ))
    story.append(Spacer(1, 8))

    rows = [["Date", "Ref", "Particulars", "Debit (₹)", "Credit (₹)", "Balance (₹)"]]
    rows.append(["", "", "Opening Balance", "", "", _fmt(ledger.get("opening_balance", 0))])
    for e in ledger.get("entries", []):
        rows.append([
            e.get("date", ""),
            e.get("reference", ""),
            e.get("particulars", ""),
            _fmt(e.get("debit", 0)) if e.get("debit", 0) else "",
            _fmt(e.get("credit", 0)) if e.get("credit", 0) else "",
            _fmt(e.get("balance", 0)),
        ])
    rows.append(["", "", "TOTAL", _fmt(ledger.get("total_debit", 0)), _fmt(ledger.get("total_credit", 0)), ""])
    rows.append(["", "", "Closing Balance", "", "", _fmt(ledger.get("closing_balance", 0))])

    tbl = Table(rows, colWidths=[22 * mm, 30 * mm, 68 * mm, 22 * mm, 22 * mm, 22 * mm], repeatRows=1)
    tbl.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F4F4F5")),
        ("FONTNAME", (0, 0), (-1, 0), _UNI_FONT_BOLD),
        ("FONTNAME", (0, -1), (-1, -1), _UNI_FONT_BOLD),
        ("FONTNAME", (0, -2), (-1, -2), _UNI_FONT_BOLD),
        ("FONTNAME", (0, 1), (-1, 1), _UNI_FONT_BOLD),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#FEF3C7")),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (3, 1), (5, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(tbl)

    story.append(Spacer(1, 8))
    story.append(Paragraph(
        f"<b>Closing Balance: ₹{_fmt(ledger.get('closing_balance', 0))}</b> "
        f"({'Dr' if ledger.get('closing_balance', 0) >= 0 else 'Cr'})",
        styles["BodyL"],
    ))
    doc.build(story)
    return buf.getvalue()
