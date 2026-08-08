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


