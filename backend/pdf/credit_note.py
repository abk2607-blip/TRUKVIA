"""Iter132c C2 refinement · Professional Credit Note PDF (A4 portrait).

Signature unchanged: build_credit_note_pdf(company, customer, invoice, note) -> bytes.
Reuses Company.logo (base64 data-URL) exactly like pdf/invoice.py:187-199.
Zero business-logic change: all values (subtotal, taxes, total, note_number) are
read from the input dicts as-is.
"""
import base64
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, KeepTogether,
)

ACCENT = colors.HexColor("#B91C1C")  # Credit Note red
ACCENT_LIGHT = colors.HexColor("#FEE2E2")
INK = colors.HexColor("#111827")
MUTED = colors.HexColor("#6B7280")
BORDER = colors.HexColor("#D1D5DB")


def _inr(v):
    try:
        return f"₹{float(v):,.2f}"
    except Exception:
        return "₹0.00"


def _amount_in_words(n):
    """Simple integer paise-safe amount-in-words for INR."""
    try:
        n = float(n)
    except Exception:
        return "Zero Only"
    rupees, paise = int(n), round((n - int(n)) * 100)
    def _two(x):
        ones = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
                "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
                "Seventeen", "Eighteen", "Nineteen"]
        tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]
        if x < 20: return ones[x]
        return tens[x // 10] + ("" if x % 10 == 0 else " " + ones[x % 10])
    def _three(x):
        h = x // 100
        r = x % 100
        return (ones_word(h) + " Hundred" + ((" " + _two(r)) if r else "")) if h else _two(r)
    def ones_word(d): return ["", "One","Two","Three","Four","Five","Six","Seven","Eight","Nine"][d]
    if rupees == 0:
        w = "Zero"
    else:
        parts = []
        crore = rupees // 10000000
        if crore: parts.append(_two(crore) + " Crore"); rupees %= 10000000
        lakh = rupees // 100000
        if lakh: parts.append(_two(lakh) + " Lakh"); rupees %= 100000
        thousand = rupees // 1000
        if thousand: parts.append(_two(thousand) + " Thousand"); rupees %= 1000
        if rupees: parts.append(_three(rupees))
        w = " ".join(parts) or "Zero"
    out = w + " Rupees"
    if paise: out += " and " + _two(paise) + " Paise"
    return out + " Only"


def _logo_flowable(company):
    logo_data = (company or {}).get("logo") or ""
    if not logo_data.startswith("data:image"):
        return None
    try:
        raw = base64.b64decode(logo_data.split(",", 1)[1])
        return Image(BytesIO(raw), width=22 * mm, height=22 * mm, kind="proportional")
    except Exception:
        return None


def build_credit_note_pdf(company, customer, invoice, note):
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=12*mm, rightMargin=12*mm,
                            topMargin=10*mm, bottomMargin=12*mm)
    styles = getSampleStyleSheet()
    small = ParagraphStyle("s", parent=styles["Normal"], fontSize=8, textColor=INK, leading=10)
    muted = ParagraphStyle("m", parent=styles["Normal"], fontSize=8, textColor=MUTED, leading=10)
    title = ParagraphStyle("t", parent=styles["Heading1"], fontSize=18, textColor=ACCENT, alignment=2, leading=22)
    label = ParagraphStyle("l", parent=styles["Normal"], fontSize=7, textColor=MUTED, leading=9, spaceAfter=1)
    body = ParagraphStyle("b", parent=styles["Normal"], fontSize=9, textColor=INK, leading=12)

    story = []
    kind_label = "CREDIT NOTE"

    # Top accent bar
    bar = Table([[""]], colWidths=[186*mm], rowHeights=[3*mm])
    bar.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,-1), ACCENT)]))
    story.append(bar); story.append(Spacer(1, 4*mm))

    # Header
    logo = _logo_flowable(company)
    company_lines = [
        Paragraph(f"<b>{(company or {}).get('name','')}</b>", body),
        Paragraph((company or {}).get("address",""), small),
        Paragraph(f"GSTIN: {(company or {}).get('gstin','')} · State: {(company or {}).get('state','')}", muted),
    ]
    left = Table([[logo or "", company_lines]], colWidths=[24*mm, 100*mm]) if logo else Table([[company_lines]], colWidths=[124*mm])
    left.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("BOX",(0,0),(-1,-1),0,colors.white)]))

    right_rows = [
        [Paragraph(kind_label, title)],
        [Paragraph(f"<font color='#6B7280'>Note #</font>  <b>{note.get('note_number','')}</b>", small)],
        [Paragraph(f"<font color='#6B7280'>Date</font>  {note.get('note_date','')}", small)],
        [Paragraph(f"<font color='#6B7280'>Ref Invoice</font>  <b>{invoice.get('invoice_number','')}</b>", small)],
        [Paragraph(f"<font color='#6B7280'>Ref Inv Date</font>  {invoice.get('invoice_date','')}", small)],
    ]
    right = Table(right_rows, colWidths=[60*mm])
    right.setStyle(TableStyle([("ALIGN",(0,0),(-1,-1),"RIGHT")]))

    header = Table([[left, right]], colWidths=[124*mm, 62*mm])
    header.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP")]))
    story.append(header); story.append(Spacer(1, 4*mm))

    # Customer + Reference invoice blocks
    cust = [
        Paragraph("CREDIT TO", label),
        Paragraph(f"<b>{(customer or {}).get('name','')}</b>", body),
        Paragraph(f"GSTIN: {(customer or {}).get('gstin','—')}", small),
        Paragraph(f"State: {(customer or {}).get('state','')}", small),
    ]
    refb = [
        Paragraph("REFERENCE INVOICE", label),
        Paragraph(f"<b>{invoice.get('invoice_number','')}</b>", body),
        Paragraph(f"Invoice Date: {invoice.get('invoice_date','')}", small),
        Paragraph(f"Original Amount: {_inr(invoice.get('total_amount',0))}", small),
    ]
    bx = Table([[cust, refb]], colWidths=[93*mm, 93*mm])
    bx.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"TOP"),
        ("BOX",(0,0),(-1,-1),0.5,BORDER),
        ("INNERGRID",(0,0),(-1,-1),0.5,BORDER),
        ("LEFTPADDING",(0,0),(-1,-1),6), ("RIGHTPADDING",(0,0),(-1,-1),6),
        ("TOPPADDING",(0,0),(-1,-1),6), ("BOTTOMPADDING",(0,0),(-1,-1),6),
    ]))
    story.append(bx); story.append(Spacer(1, 4*mm))

    # Reason
    reason = Table([[Paragraph("REASON", label),
                     Paragraph(f"<b>{note.get('reason_code','')}</b> — {note.get('reason_text','')}", body)]],
                   colWidths=[24*mm, 162*mm])
    reason.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"TOP"),
        ("BACKGROUND",(0,0),(-1,-1),ACCENT_LIGHT),
        ("BOX",(0,0),(-1,-1),0.5,BORDER),
        ("LEFTPADDING",(0,0),(-1,-1),6), ("RIGHTPADDING",(0,0),(-1,-1),6),
        ("TOPPADDING",(0,0),(-1,-1),4), ("BOTTOMPADDING",(0,0),(-1,-1),4),
    ]))
    story.append(reason); story.append(Spacer(1, 4*mm))

    # Iter132c C2b · GST Treatment badge (only when explicitly opted out).
    if note.get("apply_gst", True) is False:
        gst_badge = Table([[Paragraph("<b>GST NOT APPLIED</b> · This Credit Note is issued without GST at the party's election. All statutory validations still apply.", small)]],
                          colWidths=[186*mm])
        gst_badge.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,-1),ACCENT_LIGHT),
            ("BOX",(0,0),(-1,-1),0.8,ACCENT),
            ("TEXTCOLOR",(0,0),(-1,-1),ACCENT),
            ("LEFTPADDING",(0,0),(-1,-1),8), ("RIGHTPADDING",(0,0),(-1,-1),8),
            ("TOPPADDING",(0,0),(-1,-1),5), ("BOTTOMPADDING",(0,0),(-1,-1),5),
        ]))
        story.append(gst_badge); story.append(Spacer(1, 4*mm))

    # Line-item table
    hdr = ["#", "Description", "HSN/SAC", "Qty", "Rate", "Taxable Value"]
    lines_data = [hdr]
    for i, ln in enumerate((note.get("lines") or []), 1):
        lines_data.append([
            str(i),
            Paragraph(ln.get("description",""), small),
            ln.get("hsn_sac","") or "—",
            f"{float(ln.get('quantity',0)):g}",
            _inr(ln.get("rate",0)),
            _inr(ln.get("taxable_value", ln.get("rate",0))),
        ])
    lt = Table(lines_data, colWidths=[10*mm, 80*mm, 22*mm, 15*mm, 28*mm, 31*mm], repeatRows=1)
    lt.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),ACCENT),
        ("TEXTCOLOR",(0,0),(-1,0),colors.white),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("FONTSIZE",(0,0),(-1,-1),8),
        ("ALIGN",(0,0),(0,-1),"CENTER"),
        ("ALIGN",(3,0),(5,-1),"RIGHT"),
        ("VALIGN",(0,0),(-1,-1),"TOP"),
        ("BOX",(0,0),(-1,-1),0.5,BORDER),
        ("INNERGRID",(0,0),(-1,-1),0.3,BORDER),
        ("LEFTPADDING",(0,0),(-1,-1),4), ("RIGHTPADDING",(0,0),(-1,-1),4),
        ("TOPPADDING",(0,0),(-1,-1),3), ("BOTTOMPADDING",(0,0),(-1,-1),3),
    ]))
    story.append(lt); story.append(Spacer(1, 3*mm))

    # Tax summary right-aligned
    apply_gst = note.get("apply_gst", True) is not False
    tot_rows = [
        ["Subtotal", _inr(note.get("subtotal",0))],
    ]
    if apply_gst:
        if float(note.get("cgst_amount",0) or 0) > 0:
            tot_rows.append([f"CGST @ {note.get('cgst_rate',0)}%", _inr(note.get("cgst_amount",0))])
        if float(note.get("sgst_amount",0) or 0) > 0:
            tot_rows.append([f"SGST @ {note.get('sgst_rate',0)}%", _inr(note.get("sgst_amount",0))])
        if float(note.get("igst_amount",0) or 0) > 0:
            tot_rows.append([f"IGST @ {note.get('igst_rate',0)}%", _inr(note.get("igst_amount",0))])
        tot_rows.append(["Total Tax", _inr(note.get("total_tax",0))])
    else:
        tot_rows.append(["GST", "Not Applied"])
    tot_rows.append(["Round Off", _inr(note.get("round_off",0))])
    tot_rows.append(["TOTAL CREDIT NOTE", _inr(note.get("total_amount",0))])
    tot = Table(tot_rows, colWidths=[38*mm, 34*mm])
    tot.setStyle(TableStyle([
        ("ALIGN",(0,0),(-1,-1),"RIGHT"),
        ("FONTSIZE",(0,0),(-1,-1),9),
        ("LINEABOVE",(0,-1),(-1,-1),1,ACCENT),
        ("FONTNAME",(0,-1),(-1,-1),"Helvetica-Bold"),
        ("TEXTCOLOR",(0,-1),(-1,-1),ACCENT),
        ("TOPPADDING",(0,-1),(-1,-1),4),
    ]))
    wrap = Table([["", tot]], colWidths=[114*mm, 72*mm])
    wrap.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP")]))
    story.append(wrap); story.append(Spacer(1, 4*mm))

    # Amount in words + notices
    story.append(Paragraph(f"<b>Amount in Words:</b> {_amount_in_words(note.get('total_amount',0))}", small))
    if note.get("rcm"):
        story.append(Spacer(1, 2*mm))
        story.append(Paragraph("<b>RCM applicable</b> — Tax to be paid by recipient under Reverse Charge Mechanism.", muted))
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph("Computer-generated document · Valid without physical signature.", muted))
    story.append(Spacer(1, 10*mm))

    # Authorised signatory
    sig = Table([["", Paragraph(f"<b>For {(company or {}).get('name','')}</b><br/><br/><br/>Authorised Signatory", small)]],
                colWidths=[114*mm, 72*mm])
    sig.setStyle(TableStyle([("ALIGN",(1,0),(1,-1),"RIGHT"), ("VALIGN",(0,0),(-1,-1),"TOP")]))
    story.append(sig)

    doc.build(story)
    return buf.getvalue()
