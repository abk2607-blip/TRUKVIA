"""Iter132b · Debit Note PDF renderer.

Self-contained — mirrors Iter132a Credit Note structure but with a blue
"DEBIT NOTE" banner. Does NOT share helpers with pdf/invoice.py so
Iter127b page-of-pages logic is untouched.
"""
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer

from pdf._base import _fmt, _num_to_words_inr, _UNI_FONT, _UNI_FONT_BOLD, _fmt_ind_date


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont(_UNI_FONT, 7.5)
    canvas.setFillColor(colors.HexColor("#64748B"))
    canvas.drawRightString(A4[0] - 10 * mm, 5 * mm, f"Page {canvas.getPageNumber()} · Debit Note")
    canvas.drawString(10 * mm, 5 * mm, "This is a computer-generated document.")
    canvas.restoreState()


def build_debit_note_pdf(company: dict, customer: dict, invoice: dict, note: dict) -> bytes:
    """Iter132b · Debit-note PDF. Portrait A4 with blue banner."""
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=12 * mm, bottomMargin=15 * mm,
        title=f"Debit Note {note.get('note_number','')}",
    )
    styles = getSampleStyleSheet()
    story = []
    company_name = company.get("name", "")
    company_addr = "\n".join(x for x in [
        company.get("address", ""),
        f"GSTIN: {company.get('gstin','')}",
        f"State: {company.get('state','')}",
    ] if x)
    header_left = Paragraph(
        f"<b><font size=13>{company_name}</font></b><br/>"
        f"<font size=8>{company_addr.replace(chr(10), '<br/>')}</font>",
        styles["Normal"],
    )
    header_right = Paragraph(
        "<b><font color='#1D4ED8' size=22>DEBIT NOTE</font></b><br/>"
        f"<font size=9>Note No: <b>{note.get('note_number','—')}</b><br/>"
        f"Date: {_fmt_ind_date(note.get('note_date',''))}<br/>"
        f"<font color='#64748B'>Ref Invoice: {note.get('invoice_number_snapshot','')}"
        f" ({_fmt_ind_date(invoice.get('invoice_date',''))})</font></font>",
        styles["Normal"],
    )
    hdr = Table([[header_left, header_right]], colWidths=[110 * mm, 76 * mm])
    hdr.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#1D4ED8")),
        ("INNERGRID", (0, 0), (-1, -1), 0.2, colors.HexColor("#E5E7EB")),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(hdr); story.append(Spacer(1, 6))

    reason_labels = {
        "rate_correction": "Rate Correction", "short_delivery": "Short Delivery",
        "quality_claim": "Quality Claim", "post_invoice_discount": "Post-Invoice Discount",
        "under_charge": "Under Charge", "missed_halting": "Missed Halting",
        "freight_escalation": "Freight Escalation", "sales_return": "Sales Return",
        "other": "Other",
    }
    bill_to = Paragraph(
        f"<b>Debit To:</b><br/><font size=9>{customer.get('name','')}<br/>"
        f"{customer.get('address','')}<br/>"
        f"GSTIN: {customer.get('gstin','')}<br/>State: {customer.get('state','')}</font>",
        styles["Normal"],
    )
    reason_block = Paragraph(
        f"<b>Reason:</b> {reason_labels.get(note.get('reason_code','other'),'Other')}<br/>"
        f"<font size=8>{(note.get('reason_text') or '').replace(chr(10),'<br/>')}</font>",
        styles["Normal"],
    )
    btbl = Table([[bill_to, reason_block]], colWidths=[95 * mm, 91 * mm])
    btbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.3, colors.HexColor("#D1D5DB")),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(btbl); story.append(Spacer(1, 8))

    line_rows = [["#", "Description", "HSN/SAC", "Qty", "Rate", "Taxable Value"]]
    for i, l in enumerate(note.get("lines", []), start=1):
        line_rows.append([str(i), l.get("description", ""), l.get("hsn_sac", ""),
                          _fmt(l.get("quantity", 0)), _fmt(l.get("rate", 0)),
                          _fmt(l.get("taxable_value", 0))])
    ltbl = Table(line_rows, colWidths=[10 * mm, 78 * mm, 20 * mm, 20 * mm, 25 * mm, 33 * mm])
    ltbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DBEAFE")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
        ("FONTNAME", (0, 0), (-1, 0), _UNI_FONT_BOLD),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.2, colors.HexColor("#E5E7EB")),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(ltbl); story.append(Spacer(1, 6))

    if note.get("gst_type") == "cgst_sgst":
        tax_rows = [
            [f"CGST @ {note.get('cgst_rate',2.5)}%", _fmt(note.get("cgst_amount", 0))],
            [f"SGST @ {note.get('sgst_rate',2.5)}%", _fmt(note.get("sgst_amount", 0))],
        ]
    else:
        tax_rows = [[f"IGST @ {note.get('igst_rate',5)}%", _fmt(note.get("igst_amount", 0))]]
    tot_rows = [
        ["Subtotal", _fmt(note.get("subtotal", 0))], *tax_rows,
        ["Total Tax", _fmt(note.get("total_tax", 0))],
        ["Round Off", _fmt(note.get("round_off", 0))],
        ["Total (Debit Note)", _fmt(note.get("total_amount", 0))],
    ]
    ttbl = Table(tot_rows, colWidths=[60 * mm, 40 * mm], hAlign="RIGHT")
    ttbl.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#DBEAFE")),
        ("FONTNAME", (0, -1), (-1, -1), _UNI_FONT_BOLD),
        ("BOX", (0, 0), (-1, -1), 0.2, colors.HexColor("#D1D5DB")),
        ("INNERGRID", (0, 0), (-1, -1), 0.2, colors.HexColor("#E5E7EB")),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(ttbl); story.append(Spacer(1, 6))
    story.append(Paragraph(
        f"<font size=8><b>Amount in words:</b> {_num_to_words_inr(note.get('total_amount', 0))}</font>",
        styles["Normal"]))
    if note.get("rcm"):
        story.append(Spacer(1, 4))
        story.append(Paragraph(
            "<font size=8 color='#1D4ED8'><b>Tax on Reverse Charge Basis — not collected.</b></font>",
            styles["Normal"]))
    story.append(Spacer(1, 12))
    story.append(Paragraph(
        "<font size=8 color='#64748B'>This is a computer-generated Debit Note "
        "issued under §34 of the CGST Act, 2017. Please retain for GST records.</font>",
        styles["Normal"]))
    story.append(Spacer(1, 22))
    story.append(Paragraph(
        f"<div align='right'><font size=8>For <b>{company_name}</b><br/><br/><br/>"
        "Authorised Signatory</font></div>", styles["Normal"]))
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()
