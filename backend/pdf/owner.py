from ._base import (
    _fmt, _num_to_words_inr,
    _UNI_FONT, _UNI_FONT_BOLD, _TE_FONT, _TE_FONT_BOLD,
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

def build_owner_statement_pdf(company: dict, month: str, pl: dict, receivables: list, vehicle_alerts: list) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=10 * mm, rightMargin=10 * mm,
        topMargin=8 * mm, bottomMargin=8 * mm,
        title=f"Owner Statement {month}",
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="OSTitle", fontName="Helvetica-Bold", fontSize=15, leading=18, alignment=1))
    styles.add(ParagraphStyle(name="OSHead", fontName="Helvetica-Bold", fontSize=9, leading=12))
    story = []

    story.append(Paragraph(f"<b>{company.get('name','YOUR COMPANY')}</b>", styles["OSHead"]))
    story.append(Paragraph(f"OWNER STATEMENT — Month: {month}", styles["OSTitle"]))
    story.append(Spacer(1, 4))

    pl_rows = [
        ["Metric", "Amount (₹)"],
        ["Freight Revenue", _fmt(pl.get("revenue", 0))],
        ["Diesel", _fmt(pl.get("expenses", {}).get("diesel", 0))],
        ["Toll", _fmt(pl.get("expenses", {}).get("toll", 0))],
        ["Driver Batta", _fmt(pl.get("expenses", {}).get("batta", 0))],
        ["Repairs", _fmt(pl.get("expenses", {}).get("repair", 0))],
        ["Other", _fmt(pl.get("expenses", {}).get("other", 0))],
        ["Total Expenses", _fmt(pl.get("expenses", {}).get("total", 0))],
        ["NET PROFIT", _fmt(pl.get("net_profit", 0))],
        [f"Margin {pl.get('margin_pct',0)}%", f"{pl.get('trip_count',0)} trip(s)"],
    ]
    pl_tbl = Table(pl_rows, colWidths=[100 * mm, 40 * mm])
    pl_tbl.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F4F4F5")),
        ("BACKGROUND", (0, -2), (-1, -2), colors.HexColor("#FEF3C7")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, -2), (-1, -2), "Helvetica-Bold"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]))
    story.append(Paragraph("<b>1) Profit &amp; Loss Snapshot</b>", styles["OSHead"]))
    story.append(pl_tbl)
    story.append(Spacer(1, 6))

    story.append(Paragraph("<b>2) Outstanding Receivables (top 8)</b>", styles["OSHead"]))
    rec_rows = [["Customer", "Invoices", "Days", "Balance (₹)"]]
    for r in receivables[:8]:
        rec_rows.append([r.get("customer_name", ""), str(r.get("invoices", 0)), str(r.get("oldest_days", 0)), _fmt(r.get("balance", 0))])
    if len(rec_rows) == 1:
        rec_rows.append(["No pending balances", "", "", ""])
    rec_tbl = Table(rec_rows, colWidths=[100 * mm, 20 * mm, 20 * mm, 40 * mm])
    rec_tbl.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F4F4F5")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ALIGN", (1, 0), (3, -1), "RIGHT"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
    ]))
    story.append(rec_tbl)
    story.append(Spacer(1, 6))

    story.append(Paragraph("<b>3) Vehicle Document Alerts</b>", styles["OSHead"]))
    va_rows = [["Vehicle", "Document", "Expiry Date", "Days", "Status"]]
    for a in vehicle_alerts[:15]:
        va_rows.append([a.get("vehicle_number", ""), a.get("document", ""), a.get("date", ""), str(a.get("days", "")), a.get("status", "").upper()])
    if len(va_rows) == 1:
        va_rows.append(["All documents OK", "", "", "", ""])
    va_tbl = Table(va_rows, colWidths=[50 * mm, 40 * mm, 40 * mm, 25 * mm, 30 * mm])
    va_tbl.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F4F4F5")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
    ]))
    story.append(va_tbl)

    doc.build(story)
    return buf.getvalue()

