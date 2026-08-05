"""Server-side PDF generator for the GST transport invoice.
Uses reportlab platypus to build a professional bilingual-friendly invoice
similar to the VBK Logistics reference format.
"""
from io import BytesIO
import base64
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, KeepTogether, Image,
)


def _fmt(n):
    try:
        return f"{float(n):,.2f}"
    except Exception:
        return "0.00"


def _num_to_words_inr(n: float) -> str:
    """Very simple Indian numbering system to words for rupees."""
    n = int(round(n))
    if n == 0:
        return "Zero Rupees Only"
    units = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
             "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
             "Seventeen", "Eighteen", "Nineteen"]
    tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]

    def two(x):
        if x < 20:
            return units[x]
        return tens[x // 10] + (" " + units[x % 10] if x % 10 else "")

    def three(x):
        s = ""
        if x >= 100:
            s += units[x // 100] + " Hundred"
            x %= 100
            if x:
                s += " " + two(x)
        else:
            s = two(x)
        return s

    parts = []
    crore = n // 10000000
    n %= 10000000
    lakh = n // 100000
    n %= 100000
    thousand = n // 1000
    n %= 1000
    hundred = n
    if crore:
        parts.append(three(crore) + " Crore")
    if lakh:
        parts.append(two(lakh) + " Lakh")
    if thousand:
        parts.append(two(thousand) + " Thousand")
    if hundred:
        parts.append(three(hundred))
    return " ".join(parts).strip() + " Rupees Only"


def build_invoice_pdf(company: dict, customer: dict, invoice: dict, trips: list) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=10 * mm, bottomMargin=10 * mm,
        title=f"Invoice {invoice.get('invoice_number','')}",
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Small", fontName="Helvetica", fontSize=8, leading=10))
    styles.add(ParagraphStyle(name="SmallBold", fontName="Helvetica-Bold", fontSize=8, leading=10))
    styles.add(ParagraphStyle(name="H1", fontName="Helvetica-Bold", fontSize=16, leading=20, alignment=1))
    styles.add(ParagraphStyle(name="H2", fontName="Helvetica-Bold", fontSize=11, leading=14))
    styles.add(ParagraphStyle(name="Body", fontName="Helvetica", fontSize=9, leading=12))
    styles.add(ParagraphStyle(name="BodyRight", fontName="Helvetica", fontSize=9, leading=12, alignment=2))
    styles.add(ParagraphStyle(name="Mono", fontName="Courier", fontSize=8, leading=10))

    story = []

    # --- Header: Company + INVOICE title ---
    company_name = company.get("name") or "YOUR COMPANY NAME"
    company_lines = [
        f"<b>{company_name}</b>",
        company.get("address", ""),
        f"Ph: {company.get('phone','')}" if company.get("phone") else "",
        f"Email: {company.get('email','')}" if company.get("email") else "",
        f"<b>GSTIN:</b> {company.get('gstin','') or '—'}   <b>PAN:</b> {company.get('pan','') or '—'}",
        f"<b>State:</b> {company.get('state','') or '—'}",
    ]
    company_para = Paragraph("<br/>".join([l for l in company_lines if l]), styles["Body"])

    # Logo (if data URL present)
    logo_img = None
    logo_data = company.get("logo") or ""
    if logo_data.startswith("data:image"):
        try:
            b64 = logo_data.split(",", 1)[1]
            raw = base64.b64decode(b64)
            logo_img = Image(BytesIO(raw), width=22 * mm, height=22 * mm, kind="proportional")
        except Exception:
            logo_img = None

    if logo_img is not None:
        left_cell = [[logo_img, company_para]]
        left_tbl = Table(left_cell, colWidths=[26 * mm, 84 * mm])
        left_tbl.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]))
        left_stack_widget = left_tbl
    else:
        left_stack_widget = company_para

    title_para = Paragraph("<b>TAX INVOICE</b>", styles["H1"])
    rcm_para = Paragraph(
        f"Tax Payable on Reverse Charge: <b>{'YES' if invoice.get('rcm') else 'NO'}</b>",
        styles["SmallBold"],
    )
    header_tbl = Table(
        [[left_stack_widget, [title_para, Spacer(1, 4), rcm_para]]],
        colWidths=[110 * mm, 76 * mm],
    )
    header_tbl.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.8, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(header_tbl)

    # --- Invoice meta + Bill To ---
    bill_to = [
        f"<b>Bill To:</b>",
        f"<b>{customer.get('name','')}</b>",
        customer.get("address", ""),
        f"GSTIN: {customer.get('gstin','') or '—'}",
        f"PAN: {customer.get('pan','') or '—'}   State: {customer.get('state','') or '—'}",
        f"Phone: {customer.get('phone','')}" if customer.get("phone") else "",
    ]
    bill_para = Paragraph("<br/>".join([l for l in bill_to if l]), styles["Body"])

    meta = [
        ["Invoice No", invoice.get("invoice_number", "")],
        ["Invoice Date", invoice.get("invoice_date", "")],
        ["HSN/SAC", company.get("hsn_sac", "996791")],
        ["GST Type", "CGST+SGST" if invoice.get("gst_type") == "cgst_sgst" else "IGST"],
    ]
    meta_tbl = Table(meta, colWidths=[30 * mm, 46 * mm])
    meta_tbl.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))

    party_tbl = Table([[bill_para, meta_tbl]], colWidths=[110 * mm, 76 * mm])
    party_tbl.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.8, colors.black),
        ("LINEBEFORE", (1, 0), (1, 0), 0.5, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(party_tbl)

    # --- Trip line items ---
    header = ["#", "Date", "Vehicle No", "Load", "Route", "Tons", "Rate Mode", "Rate/KMs", "Freight (Rs)"]
    rows = [header]
    for idx, t in enumerate(trips, start=1):
        route = f"{t.get('from_location','')} → {t.get('to_location','')}"
        if t.get("freight_mode") == "per_ton":
            mode = "Per Ton"
            rate = f"₹{_fmt(t.get('rate_per_ton', 0))}/T"
        else:
            mode = "Round Trip"
            km = t.get("round_trip_kms", 0) or 0
            rkm = t.get("rate_per_km_per_ton", 0) or 0
            if km > 0 and rkm > 0:
                rate = f"{_fmt(km)}km × ₹{_fmt(rkm)}"
            else:
                rate = f"Lump ₹{_fmt(t.get('fixed_amount', 0))}"
        rows.append([
            str(idx),
            t.get("date", ""),
            t.get("vehicle_number", ""),
            t.get("load_details", ""),
            route,
            _fmt(t.get("tons", 0)),
            mode,
            rate,
            _fmt(t.get("freight_amount", 0)),
        ])

    items_tbl = Table(rows, colWidths=[8*mm, 20*mm, 22*mm, 26*mm, 40*mm, 14*mm, 18*mm, 18*mm, 20*mm], repeatRows=1)
    items_tbl.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F4F4F5")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (5, 1), (5, -1), "RIGHT"),
        ("ALIGN", (7, 1), (8, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(items_tbl)

    # --- Totals ---
    subtotal = invoice.get("subtotal", 0)
    gst_type = invoice.get("gst_type", "cgst_sgst")
    cgst = invoice.get("cgst_amount", 0)
    sgst = invoice.get("sgst_amount", 0)
    igst = invoice.get("igst_amount", 0)
    total = invoice.get("total_amount", 0)
    paid = invoice.get("amount_paid", 0)
    balance = invoice.get("balance_due", 0)

    totals_rows = [["Taxable Amount", _fmt(subtotal)]]
    if gst_type == "cgst_sgst":
        totals_rows.append(["CGST @ 2.5%", _fmt(cgst)])
        totals_rows.append(["SGST @ 2.5%", _fmt(sgst)])
    else:
        totals_rows.append(["IGST @ 5%", _fmt(igst)])
    if invoice.get("rcm"):
        totals_rows.append(["Tax under RCM (not collected)", "—"])
    else:
        totals_rows.append(["Total Tax", _fmt(invoice.get("total_tax", 0))])
    totals_rows.append(["TOTAL PAYABLE", _fmt(total)])
    totals_rows.append(["Amount Received", _fmt(paid)])
    totals_rows.append(["Balance Due", _fmt(balance)])

    totals_tbl = Table(totals_rows, colWidths=[50 * mm, 30 * mm])
    totals_tbl.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTNAME", (0, -3), (-1, -3), "Helvetica-Bold"),
        ("BACKGROUND", (0, -3), (-1, -3), colors.HexColor("#FEF3C7")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))

    # Amount in words + bank details
    words = _num_to_words_inr(total)
    bank_lines = [
        "<b>Bank Details (RTGS/NEFT):</b>",
        f"Bank: {company.get('bank_name','—')}",
        f"A/c No: {company.get('account_number','—')}",
        f"IFSC: {company.get('ifsc','—')}",
        f"Branch: {company.get('branch','—')}",
    ]
    left_stack = [
        Paragraph(f"<b>Amount in Words:</b> {words}", styles["Body"]),
        Spacer(1, 6),
        Paragraph("<br/>".join(bank_lines), styles["Small"]),
    ]

    bottom_tbl = Table([[left_stack, totals_tbl]], colWidths=[106 * mm, 80 * mm])
    bottom_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.8, colors.black),
        ("LINEBEFORE", (1, 0), (1, 0), 0.5, colors.black),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(bottom_tbl)

    # --- Notes / Terms ---
    terms = [
        "1. GST shall be paid by the service recipient under the Reverse Charge Mechanism as per Notification No. 08/2017 (if RCM = YES)." if invoice.get("rcm") else "1. GST is charged under forward charge and included in the total payable.",
        "2. Shortage or excess in Bitumen quantity will be accounted for only beyond a permissible variation of 1%.",
        "3. Halting charges Rs. 2,500 per day applicable after 48 hours from arrival at the site.",
        "4. Responsibility for product insurance lies with the consignor or consignee, as applicable.",
    ]
    if invoice.get("notes"):
        terms.append(f"5. Notes: {invoice.get('notes')}")
    story.append(Spacer(1, 6))
    story.append(Paragraph("<br/>".join(terms), styles["Small"]))

    # --- Signature ---
    story.append(Spacer(1, 20))
    sign_tbl = Table(
        [["", f"For {company_name}"], ["", "Authorised Signatory"]],
        colWidths=[110 * mm, 76 * mm],
    )
    sign_tbl.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTNAME", (1, 0), (1, 0), "Helvetica-Bold"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(sign_tbl)

    doc.build(story)
    return buf.getvalue()


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
    styles.add(ParagraphStyle(name="H1L", fontName="Helvetica-Bold", fontSize=16, leading=20))
    styles.add(ParagraphStyle(name="BodyL", fontName="Helvetica", fontSize=9, leading=12))
    styles.add(ParagraphStyle(name="SmallL", fontName="Helvetica", fontSize=8, leading=10))
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
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("FONTNAME", (0, -2), (-1, -2), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
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
