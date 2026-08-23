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
    SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, KeepTogether, Image, PageBreak,
)

# Register Telugu fonts. Iter112 switched the LR bilingual T&C to Anek Telugu
# (the SAME font family used by the QORVENA web application UI — see
# frontend/src/index.css `.telugu` class + Anek Telugu loaded from Google
# Fonts in index.html). This gives PDF Telugu = App UI Telugu, and correctly
# renders Telugu conjuncts / vowel signs / guninthalu / consonant clusters,
# unlike DejaVuSans (no Telugu block coverage) or Helvetica (Latin-only).
# NotoSansTelugu is retained as a secondary registered face for any legacy
# call site that still references it.
_FONTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fonts")
_TE_FONT = "AnekTelugu"
_TE_FONT_BOLD = "AnekTelugu-Bold"
try:
    if _TE_FONT not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(_TE_FONT, os.path.join(_FONTS_DIR, "AnekTelugu-Regular.ttf")))
        pdfmetrics.registerFont(TTFont(_TE_FONT_BOLD, os.path.join(_FONTS_DIR, "AnekTelugu-Bold.ttf")))
        from reportlab.pdfbase.pdfmetrics import registerFontFamily
        registerFontFamily(_TE_FONT, normal=_TE_FONT, bold=_TE_FONT_BOLD,
                           italic=_TE_FONT, boldItalic=_TE_FONT_BOLD)
    # Also keep NotoSansTelugu registered as a fallback face (backward compat).
    if "NotoSansTelugu" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("NotoSansTelugu",
                                       os.path.join(_FONTS_DIR, "NotoSansTelugu-Regular.ttf")))
        pdfmetrics.registerFont(TTFont("NotoSansTelugu-Bold",
                                       os.path.join(_FONTS_DIR, "NotoSansTelugu-Bold.ttf")))
except Exception:
    _TE_FONT = "Helvetica"  # fallback (Telugu will not render — dev-only)
    _TE_FONT_BOLD = "Helvetica-Bold"

# DejaVu Sans is used across invoice/LR/report bodies because it supports the
# Indian Rupee sign (₹, U+20B9) which the built-in Helvetica lacks.
_UNI_FONT = "DejaVuSans"
_UNI_FONT_BOLD = "DejaVuSans-Bold"
_UNI_PATHS = [
    os.path.join(_FONTS_DIR, "DejaVuSans.ttf"),
    os.path.join(_FONTS_DIR, "DejaVuSans-Bold.ttf"),
]
try:
    if _UNI_FONT not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(_UNI_FONT, _UNI_PATHS[0]))
        pdfmetrics.registerFont(TTFont(_UNI_FONT_BOLD, _UNI_PATHS[1]))
        from reportlab.pdfbase.pdfmetrics import registerFontFamily
        registerFontFamily(_UNI_FONT, normal=_UNI_FONT, bold=_UNI_FONT_BOLD, italic=_UNI_FONT, boldItalic=_UNI_FONT_BOLD)
except Exception:
    _UNI_FONT = "Helvetica"
    _UNI_FONT_BOLD = "Helvetica-Bold"


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

LR_TERMS_EN = [
    # Iter101 — Rewritten in original wording for QORVENA / A. Kishore Babu & Sons.
    # Business intent and commercial protection are preserved; language is fresh
    # (no clause copies existing industry templates verbatim).
    "Where an official loading-facility seal is applicable, verify the seal number against the relevant loading document / invoice before unloading. Any transporter-applied safety seal discrepancy shall be recorded in the unloading remarks and handled as per the Seal Verification &amp; Unloading Protocol above.",
    "Physically inspect the driver cabin, tool compartment and the full chassis underside for any foreign objects or concealed material prior to commencing weighment.",
    "Instruct the driver and crew to remove all non-consignment items — firewood, jerry cans, spare drums, drinking-water containers, personal cargo — from the vehicle before the empty-weight reading is taken.",
    "Examine the diesel tank, cabin interior and any accessible cavities for modifications or hidden compartments that could be exploited to manipulate the tare or gross weight.",
    "Confirm that every wheel of the tanker rests fully within the weighbridge platform boundary; partial contact renders the reading invalid and must not be accepted.",
    "Request the driver and helper to step off the vehicle for both loaded and empty weighments, and obtain the driver's signature against each recorded weight in the site register.",
    "Follow the standard sampling and quality-testing protocol for the delivered product before opening the discharge valve or dip-checking the compartments.",
    "After unloading and the empty weighment, open the tank manhole and physically confirm complete evacuation — no residual product may remain inside the compartment.",
    "Where the tank cannot be fully gravity-drained, deploy the loading ramp and drain-drum method to achieve zero residual product before releasing the vehicle.",
    "Complete every field of the 'Unloading Details by Site Officials' section on this GCN — with signature, seal and stamp — and retain a duplicate record of the same information at the site for the vehicle's file.",
    "The driver's signature is mandatory on both the loading slip at the origin location and the unloading slip at the destination site.",
    "Once the vehicle has been unloaded and released, the carrier accepts no further responsibility for the quality or quantity of the delivered product; the consignee's acknowledgement is deemed final acceptance.",
    "Where a joint coordination WhatsApp / Signal group has been established, site officials shall upload clear photographs and short videos of the tanker manholes immediately after unloading, to build an audit-safe visual record and to deter any malpractice.",
    "Insurance for the goods in transit is the responsibility of the consignor or consignee as applicable under the underlying commercial contract; the carrier is not liable for risks properly covered by such insurance (fire, accident, theft or acts of God).",
    "This Goods Consignment Note is issued subject to the standard conditions of carriage of A. Kishore Babu & Sons. Any dispute arising out of this consignment shall be subject to the exclusive jurisdiction of the competent courts at the carrier's principal place of business.",
]

# Iter112 · Bilingual T&C — Telugu translation of each English clause, in the
# same order. The LR PDF renders each pair together (English on top, Telugu
# below in a slightly smaller size) so drivers and site officials at rural
# unloading points can read the terms in their own language. Any change to
# LR_TERMS_EN must be mirrored here or the regression guard fails.
LR_TERMS_TE = [
    "అధికారిక లోడింగ్ సీల్ ఉన్న సందర్భంలో, అన్‌లోడింగ్‌కు ముందు సంబంధిత లోడింగ్ డాక్యుమెంట్ / ఇన్‌వాయిస్‌తో సీల్ నంబర్‌ను ధృవీకరించండి. రవాణాదారు వర్తించే భద్రతా సీల్ వ్యత్యాసాలను అన్‌లోడింగ్ రిమార్క్స్‌లో నమోదు చేసి, పైన పేర్కొన్న సీల్ వెరిఫికేషన్ &amp; అన్‌లోడింగ్ ప్రోటోకాల్ ప్రకారం నిర్వహించాలి.",
    "బరువు తూయడం ప్రారంభించే ముందు డ్రైవర్ క్యాబిన్, టూల్ కంపార్ట్‌మెంట్ మరియు మొత్తం చాసిస్ కింది భాగంలో ఏవైనా బాహ్య వస్తువులు లేదా దాచిన సామాగ్రి ఉన్నదా అని భౌతికంగా తనిఖీ చేయండి.",
    "ఖాళీ బరువు తీసుకునే ముందు వాహనం నుండి కన్‌సైన్‌మెంట్‌కు సంబంధం లేని అన్ని వస్తువులు — కట్టెలు, జెర్రీ క్యాన్‌లు, స్పేర్ డ్రమ్‌లు, తాగునీటి కంటైనర్లు, వ్యక్తిగత సామాన్లు — తొలగించమని డ్రైవర్ మరియు సిబ్బందికి తెలియజేయండి.",
    "టేర్ లేదా గ్రాస్ బరువును తారుమారు చేసేందుకు ఉపయోగించగల మార్పులు లేదా దాచిన కంపార్ట్‌మెంట్‌ల కోసం డీజిల్ ట్యాంక్, క్యాబిన్ లోపలి భాగం మరియు ప్రవేశయోగ్యమైన అన్ని ఖాళీ స్థలాలను పరిశీలించండి.",
    "ట్యాంకర్ యొక్క ప్రతి చక్రం వేబ్రిడ్జ్ ప్లాట్‌ఫారం సరిహద్దులో పూర్తిగా ఉందని నిర్ధారించండి; పాక్షిక సంపర్కం రీడింగ్‌ను చెల్లనిదిగా చేస్తుంది, దానిని అంగీకరించకూడదు.",
    "లోడెడ్ మరియు ఖాళీ రెండు బరువు తూయడానికి డ్రైవర్ మరియు హెల్పర్‌ను వాహనం నుండి దిగమని అభ్యర్థించండి, మరియు సైట్ రిజిస్టర్‌లో నమోదైన ప్రతి బరువుపై డ్రైవర్ సంతకం పొందండి.",
    "డిశ్చార్జ్ వాల్వ్‌ను తెరవడం లేదా కంపార్ట్‌మెంట్‌లను డిప్-చెక్ చేయడానికి ముందు డెలివరీ చేసిన ఉత్పత్తికి ప్రామాణిక నమూనా మరియు నాణ్యతా పరీక్షా విధానాన్ని అనుసరించండి.",
    "అన్‌లోడింగ్ మరియు ఖాళీ బరువు తీసిన తర్వాత, ట్యాంక్ మ్యాన్‌హోల్‌ను తెరిచి పూర్తిగా ఖాళీ అయిందని భౌతికంగా నిర్ధారించండి — కంపార్ట్‌మెంట్ లోపల ఎలాంటి అవశేష ఉత్పత్తి ఉండకూడదు.",
    "ట్యాంక్ పూర్తిగా గురుత్వాకర్షణ ద్వారా ఖాళీ చేయలేని చోట, వాహనాన్ని విడుదల చేయడానికి ముందు జీరో అవశేష ఉత్పత్తిని సాధించడానికి లోడింగ్ ర్యాంప్ మరియు డ్రెయిన్-డ్రమ్ పద్ధతిని ఉపయోగించండి.",
    "ఈ GCN లోని 'సైట్ అధికారుల ద్వారా అన్‌లోడింగ్ వివరాలు' విభాగంలోని ప్రతి ఫీల్డ్‌ను — సంతకం, సీల్ మరియు స్టాంప్‌తో — పూర్తి చేయండి మరియు వాహన ఫైల్ కోసం అదే సమాచారం యొక్క నకలు రికార్డును సైట్‌లో ఉంచండి.",
    "మూల ప్రాంతంలోని లోడింగ్ స్లిప్‌పై మరియు గమ్యస్థాన సైట్‌లోని అన్‌లోడింగ్ స్లిప్ రెండింటిపై డ్రైవర్ సంతకం తప్పనిసరి.",
    "వాహనం అన్‌లోడ్ చేయబడి విడుదల చేయబడిన తర్వాత, డెలివరీ చేసిన ఉత్పత్తి నాణ్యత లేదా పరిమాణంపై క్యారియర్ మరిన్ని బాధ్యతలు స్వీకరించడు; కన్‌సైనీ యొక్క అంగీకారం తుది ఆమోదంగా పరిగణించబడుతుంది.",
    "ఉమ్మడి సమన్వయ WhatsApp / Signal గ్రూప్ ఏర్పాటు చేయబడిన చోట, ఆడిట్-సురక్షిత దృశ్య రికార్డును నిర్మించడానికి మరియు ఏవైనా అక్రమాలను నిరోధించడానికి, అన్‌లోడింగ్ తర్వాత వెంటనే ట్యాంకర్ మ్యాన్‌హోల్స్ యొక్క స్పష్టమైన ఫోటోలు మరియు షార్ట్ వీడియోలను సైట్ అధికారులు అప్‌లోడ్ చేయాలి.",
    "రవాణాలో ఉన్న వస్తువులకు బీమా అనేది సంబంధిత వాణిజ్య ఒప్పందం క్రింద వర్తించే విధంగా కన్‌సైనర్ లేదా కన్‌సైనీ యొక్క బాధ్యత; అటువంటి బీమా ద్వారా సరిగా కవర్ చేయబడిన నష్టాలకు (అగ్ని, ప్రమాదం, దొంగతనం లేదా దైవ కృతమైన సంఘటనలు) క్యారియర్ బాధ్యత వహించడు.",
    "ఈ గూడ్స్ కన్‌సైన్‌మెంట్ నోట్ ఎ. కిషోర్ బాబు &amp; సన్స్ యొక్క ప్రామాణిక క్యారేజ్ నిబంధనలకు లోబడి జారీ చేయబడింది. ఈ కన్‌సైన్‌మెంట్ నుండి ఉత్పన్నమయ్యే ఏవైనా వివాదాలు క్యారియర్ యొక్క ప్రధాన వ్యాపార ప్రదేశంలోని సమర్థ న్యాయస్థానాల ప్రత్యేక అధికార పరిధికి లోబడి ఉంటాయి.",
]
assert len(LR_TERMS_EN) == len(LR_TERMS_TE), (
    "Iter112 · LR_TERMS_EN and LR_TERMS_TE must stay 1:1. "
    f"EN={len(LR_TERMS_EN)}  TE={len(LR_TERMS_TE)}"
)

