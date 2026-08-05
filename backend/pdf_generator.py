"""Server-side PDF generator for the GST transport invoice.
Uses reportlab platypus to build a professional bilingual-friendly invoice
similar to the VBK Logistics reference format.
"""
from io import BytesIO
import os
import base64
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, KeepTogether, Image,
)

# Register Noto Sans Telugu for Unicode rendering (LR terms, invoice labels)
_FONTS_DIR = os.path.join(os.path.dirname(__file__), "fonts")
_TE_FONT = "NotoSansTelugu"
_TE_FONT_BOLD = "NotoSansTelugu-Bold"
try:
    if _TE_FONT not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(_TE_FONT, os.path.join(_FONTS_DIR, "NotoSansTelugu-Regular.ttf")))
        pdfmetrics.registerFont(TTFont(_TE_FONT_BOLD, os.path.join(_FONTS_DIR, "NotoSansTelugu-Bold.ttf")))
except Exception:
    _TE_FONT = "Helvetica"  # fallback


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


LR_TERMS_EN = [
    "Check all the seals for non-tampering and seal No. mentioned in G.C. copy.",
    "Check cabin, tool box and under chassis of the truck for any unwanted material.",
    "Ask the truck crew to remove all external materials like firewood, diesel and water cans before weighment of the truck.",
    "Check the diesel tank and cabin for any compartments which can be used to store unwanted materials to adjust weight.",
    "Ensure all the wheels of the truck are completely and fully placed well inside the weigh bridge platform.",
    "Ask the truck crew to come out of the truck while weighing the truck for Gross Weight and take the driver's signature for record.",
    "Adopt the standard procedure for testing the product.",
    "After unloading and weighment, vehicle to be physically checked through the manhole opening of the tank to ensure complete unloading of the product.",
    "To ensure complete unloading of the product make use of ramp and drums.",
    "All details in the unloading details sections in the G.C. to be filled without fail, acknowledgement with seal, stamp and signature and a separate detail of the above information to be maintained at the site.",
    "Signature of the driver is mandatory on loading and unloading slip.",
    "We are not responsible for quality and quantity once the vehicle is unloaded.",
    "In the WhatsApp group created for coordination and sharing of loading documents & photos of seals — please ask site officials to take photos/videos of vehicle manholes after unloading and post there to prevent malpractice.",
]
LR_TERMS_TE = [
    "అన్ని సీళ్లు తారుమారు కాకుండా ఉన్నాయా అని పరిశీలించండి, G.C.లోని సీలు నంబర్‌తో సరిపోల్చండి.",
    "ట్రక్ కేబిన్, టూల్‌బాక్స్, ఛాసీ కింద అనవసరమైన సామాన్లు లేకుండా చూడండి.",
    "ట్రక్ తూకం చేయడానికి ముందు క్రూ చే బయటి వస్తువులు — కట్టెలు, డీజిల్, నీటి డబ్బాలు — తీయించండి.",
    "వెయిట్ సర్దుబాటుకు వాడగలిగే ఖాళీలు డీజిల్ ట్యాంక్, కేబిన్‌లో ఉన్నాయా అని పరిశీలించండి.",
    "వెయిబ్రిడ్జ్ ప్లాట్‌ఫారమ్‌పై ట్రక్ చక్రాలు అన్నీ పూర్తిగా లోపల ఉన్నాయా అని నిర్ధారించండి.",
    "గ్రాస్ వెయిట్ తీసేటప్పుడు క్రూ అందరూ ట్రక్ నుండి బయటకు రావాలి, డ్రైవర్ సంతకం రికార్డుకోసం తీసుకోండి.",
    "ప్రొడక్ట్ టెస్టింగ్‌కి ప్రామాణిక విధానాన్ని అనుసరించండి.",
    "అన్‌లోడ్ మరియు తూకం తర్వాత, ట్యాంక్ మ్యాన్‌హోల్ ద్వారా వాహనాన్ని పరిశీలించి ప్రొడక్ట్ మొత్తం అన్‌లోడ్ అయ్యిందని నిర్ధారించండి.",
    "పూర్తి అన్‌లోడింగ్ కోసం ర్యాంప్ మరియు డ్రమ్‌లు ఉపయోగించండి.",
    "G.C.లో అన్‌లోడింగ్ వివరాల విభాగం తప్పకుండా పూరించాలి — సీలు, స్టాంప్, సంతకంతో పావతీ ఇవ్వాలి. అదే వివరం సైట్‌లోనూ ఉంచాలి.",
    "లోడింగ్/అన్‌లోడింగ్ స్లిప్‌పై డ్రైవర్ సంతకం తప్పనిసరి.",
    "వాహనం అన్‌లోడ్ అయిన తర్వాత క్వాలిటీ / క్వాంటిటీకి మేం బాధ్యులం కాదు.",
    "వాట్సాప్ గ్రూప్‌లో అన్‌లోడింగ్ తర్వాత మ్యాన్‌హోల్ ఫోటోలు/వీడియోలు పోస్ట్ చేయమని సైట్ అధికారులను అడగండి — అపరాధాలు జరగకుండా ఉండేందుకు.",
]


def build_lr_pdf(company: dict, customer: dict, trip: dict) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=10 * mm, rightMargin=10 * mm,
        topMargin=8 * mm, bottomMargin=8 * mm,
        title=f"LR {trip.get('lr_number','')}",
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="LRSmall", fontName="Helvetica", fontSize=7.5, leading=9.5))
    styles.add(ParagraphStyle(name="LRSmallBold", fontName="Helvetica-Bold", fontSize=7.5, leading=9.5))
    styles.add(ParagraphStyle(name="LRTitle", fontName="Helvetica-Bold", fontSize=14, leading=17, alignment=1))
    styles.add(ParagraphStyle(name="LRBody", fontName="Helvetica", fontSize=8.5, leading=11))
    styles.add(ParagraphStyle(name="LRTelugu", fontName=_TE_FONT, fontSize=7.5, leading=11))
    story = []

    company_name = company.get("name") or "YOUR COMPANY NAME"
    header_left_lines = [
        f"<b>{company_name}</b>",
        company.get("address", ""),
        f"Ph: {company.get('phone','')} · Email: {company.get('email','')}",
        f"GSTIN: {company.get('gstin','—')} · PAN: {company.get('pan','—')} · Pincode: {company.get('pincode','—')}",
    ]
    header_left = Paragraph("<br/>".join([l for l in header_left_lines if l]), styles["LRBody"])

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
        left_tbl = Table([[logo_img, header_left]], colWidths=[26 * mm, 100 * mm])
        left_tbl.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
        header_left_widget = left_tbl
    else:
        header_left_widget = header_left

    title_para = Paragraph(f"<b>GOODS CONSIGNMENT NOTE</b><br/><font size='7'>Lorry Receipt / <font name='{_TE_FONT}'>సరుకు రవాణా రసీదు</font></font>", styles["LRTitle"])
    header_tbl = Table([[header_left_widget, title_para]], colWidths=[126 * mm, 64 * mm])
    header_tbl.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.8, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(header_tbl)

    gc_tbl = Table([[
        Paragraph(f"<b>GC No.</b> {trip.get('lr_number','—')}", styles["LRBody"]),
        Paragraph(f"<b>Date:</b> {trip.get('date','')}", styles["LRBody"]),
        Paragraph(f"<b>Time:</b> {trip.get('lr_time','')}", styles["LRBody"]),
    ]], colWidths=[70 * mm, 60 * mm, 60 * mm])
    gc_tbl.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, colors.black),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(gc_tbl)

    consignor_name = trip.get("consignor_name") or trip.get("from_location") or "—"
    site_loc = trip.get("consignee_site_location") or trip.get("to_location") or "—"
    party = [
        [Paragraph(f"<b>Consignor</b> / <font name='{_TE_FONT}'>సరుకు పంపేవారు</font>", styles["LRSmallBold"]),
         Paragraph(f"<b>Consignee (M/s)</b> / <font name='{_TE_FONT}'>సరుకు స్వీకర్త</font>", styles["LRSmallBold"])],
        [Paragraph(consignor_name, styles["LRBody"]),
         Paragraph(f"<b>{customer.get('name','')}</b><br/>{customer.get('address','')}<br/>GSTIN: {customer.get('gstin','—')} · Pincode: {customer.get('pincode','—')}", styles["LRBody"])],
        [Paragraph(f"<b>Site Location:</b> {site_loc}", styles["LRSmall"]),
         Paragraph(f"<b>Site Contact:</b> {trip.get('consignee_site_contact','—')}", styles["LRSmall"])],
    ]
    party_tbl = Table(party, colWidths=[95 * mm, 95 * mm])
    party_tbl.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, colors.black),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F4F4F5")),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(party_tbl)

    net_wt = round(float(trip.get("gross_weight", 0) or 0) - float(trip.get("tare_weight", 0) or 0), 3) or float(trip.get("tons", 0) or 0)
    details_rows = [
        [Paragraph(f"<b>Tanker No.</b> / <font name='{_TE_FONT}'>వాహనం</font>", styles["LRSmallBold"]), trip.get("vehicle_number", ""),
         Paragraph(f"<b>Product</b> / <font name='{_TE_FONT}'>సరుకు</font>", styles["LRSmallBold"]), trip.get("load_details", "")],
        [Paragraph(f"<b>Invoice No.</b> / <font name='{_TE_FONT}'>ఇన్వాయిస్</font>", styles["LRSmallBold"]), trip.get("external_invoice_no", "—"),
         Paragraph(f"<b>Vehicle Seal No.</b> / <font name='{_TE_FONT}'>సీలు</font>", styles["LRSmallBold"]), trip.get("seal_numbers", "—")],
        [Paragraph(f"<b>Gross Wt.</b> / <font name='{_TE_FONT}'>గ్రాస్</font>", styles["LRSmallBold"]), f"{_fmt(trip.get('gross_weight',0))} MT",
         Paragraph(f"<b>Tare Wt.</b> / <font name='{_TE_FONT}'>టేర్</font>", styles["LRSmallBold"]), f"{_fmt(trip.get('tare_weight',0))} MT"],
        [Paragraph(f"<b>Net Wt.</b> / <font name='{_TE_FONT}'>నెట్</font>", styles["LRSmallBold"]), f"{_fmt(net_wt)} MT",
         Paragraph("<b>Round Trip KMs</b>", styles["LRSmallBold"]), _fmt(trip.get("round_trip_kms", 0))],
    ]
    details_tbl = Table(details_rows, colWidths=[40 * mm, 55 * mm, 40 * mm, 55 * mm])
    details_tbl.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, colors.black),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(details_tbl)

    driver_rows = [[Paragraph(f"<b>Driver Name</b> / <font name='{_TE_FONT}'>డ్రైవర్</font>", styles["LRSmallBold"]), trip.get("driver_name", "—"),
                    Paragraph(f"<b>Driver Mobile</b> / <font name='{_TE_FONT}'>మొబైల్</font>", styles["LRSmallBold"]), trip.get("driver_mobile", "—")]]
    driver_tbl = Table(driver_rows, colWidths=[40 * mm, 55 * mm, 40 * mm, 55 * mm])
    driver_tbl.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, colors.black),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(driver_tbl)

    un_rows = [
        [Paragraph(f"<b>Unloading Details by Site Officials</b> / <font name='{_TE_FONT}'>అన్‌లోడింగ్ వివరాలు</font>", styles["LRSmallBold"])],
        ["Date of Arrival | Time | Date of Diversion | Date of Unloading | Date of Departure | Extra KM | Shortage/Excess | HSD at Plant | Advance at Plant | Seal Checked By"],
        [""],
        ["Site Entry Gate (Stamp / Date / Time / Signature)"],
        [""],
    ]
    un_tbl = Table(un_rows, colWidths=[190 * mm])
    un_tbl.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, colors.black),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#F4F4F5")),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 2), (-1, 2), 12), ("TOPPADDING", (0, 4), (-1, 4), 12),
    ]))
    story.append(un_tbl)

    gst_decl = Paragraph(
        "<b>Declaration for exempt from registration under GST Act 2017:</b> GST is liable to be paid on reverse charge basis by recipient of such service under section 9(3) of the CGST Act. We are covered under Notification No. 5/2017-Central Tax dated 19.06.2017 issued by CBEC, GOI and hence not required to be registered under GST Law.",
        styles["LRSmall"],
    )
    gst_box = Table([[gst_decl]], colWidths=[190 * mm])
    gst_box.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, colors.black),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(gst_box)

    story.append(Spacer(1, 4))
    story.append(Paragraph(f"<b>TANKER UNLOADING PROCEDURES AT SITE TO BE FOLLOWED</b> / <font name='{_TE_FONT}'>సైట్‌లో పాటించవలసిన విధానాలు</font>", styles["LRSmallBold"]))
    terms_rows = [[Paragraph("<b>English</b>", styles["LRSmallBold"]), Paragraph(f"<font name='{_TE_FONT}'><b>తెలుగు</b></font>", styles["LRSmallBold"])]]
    for en, te in zip(LR_TERMS_EN, LR_TERMS_TE):
        terms_rows.append([Paragraph(en, styles["LRSmall"]), Paragraph(te, styles["LRTelugu"])])
    terms_tbl = Table(terms_rows, colWidths=[95 * mm, 95 * mm])
    terms_tbl.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.4, colors.grey),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E4E4E7")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F4F4F5")),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(terms_tbl)

    story.append(Spacer(1, 4))
    story.append(Paragraph(f"For <b>{company_name}</b>&nbsp;&nbsp;&nbsp;·&nbsp;&nbsp;&nbsp;Manager Signature &amp; Stamp", styles["LRSmall"]))
    story.append(Paragraph("<i>This document is computer generated and does not require signature or the Company's Seal.</i>", styles["LRSmall"]))
    doc.build(story)
    return buf.getvalue()


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

