"""Iter101 · FINAL LR / Goods Consignment Note (Option B — Navy Corporate).

Approved by the customer with three explicit requirements:
  1. Logo + company name on the LEFT of the navy header (only once — no duplicate
     name on the right). GCN title lives on the RIGHT.
  2. Exactly 2 pages on A4 — locked even with long customer / consignee names
     and long material descriptions.
  3. Preserve every business-required LR field and use own T&C wording.

Design language kept from Option B:
  · Full-bleed navy header (`#0F172A`) with emerald underline (`#059669`).
  · Three GCN meta pills (LR # · Date · Time) below header.
  · Consignor & Consignee stacked with left navy rail (magazine dossier feel).
  · Emerald route timeline with waypoint dots and RT-KM caption.
  · Borderless 2-col Consignment Grid + Weights strip with Net Wt in emerald ring.
  · Emerald Unloading Verification header for visual break.
  · Circle-numbered Terms on Page 2 + Consignee Acknowledgment Panel.

If the company has NOT uploaded a logo, a distinctive emerald monogram badge
is rendered from the company initials (e.g. "A. KISHORE BABU & SONS" → "AKBS").
"""
from ._base import _fmt, LR_TERMS_EN, LR_TERMS_TE, _UNI_FONT, _UNI_FONT_BOLD, _TE_FONT
from io import BytesIO
import base64, re
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, Image, PageBreak, KeepInFrame,
)
from reportlab.graphics.shapes import Drawing, Circle, String
from reportlab.graphics.charts.textlabels import Label

# ================== Palette (Option B — production) ==================
_NAVY      = colors.HexColor("#0F172A")
_NAVY2     = colors.HexColor("#1E293B")
_SLATE     = colors.HexColor("#475569")
_MUTED     = colors.HexColor("#64748B")
_LINE      = colors.HexColor("#CBD5E1")
_LINE_L    = colors.HexColor("#E2E8F0")
_EMERALD   = colors.HexColor("#059669")
_EMERALD_D = colors.HexColor("#047857")
_EMERALD_L = colors.HexColor("#D1FAE5")
_BG_SLATE  = colors.HexColor("#F8FAFC")
_WHITE     = colors.white


def _resolve_consignee_site(trip: dict, customer: dict) -> tuple[str, str]:
    manual_loc = (trip.get("consignee_site_location") or "").strip()
    manual_ct = (trip.get("consignee_site_contact") or "").strip()
    ship_site_id = (trip.get("ship_site_id") or "").strip()
    if manual_loc:
        return manual_loc, manual_ct or "—"
    if ship_site_id and isinstance(customer.get("ship_sites"), list):
        site = next((s for s in customer["ship_sites"] if s.get("id") == ship_site_id), None)
        if site:
            name = (site.get("site_name") or "").strip()
            addr = (site.get("address") or "").strip()
            loc = " · ".join(x for x in [name, addr] if x)
            contact = " · ".join(x for x in [(site.get("contact_person") or "").strip(),
                                             (site.get("phone") or "").strip()] if x)
            return (loc or (trip.get("to_location") or "—")), (manual_ct or contact or "—")
    return (trip.get("to_location") or "—"), (manual_ct or "—")


def _initials(name: str, cap: int = 4) -> str:
    """Extract clean initials from a company name (letters only, up to `cap`).
    'A. KISHORE BABU & SONS' → 'AKBS'."""
    words = re.findall(r"[A-Za-z]+", (name or "").upper())
    if not words:
        return "•"
    return "".join(w[0] for w in words if w and w.lower() not in {"and", "of", "the"})[:cap] or "•"


def _monogram_badge(company_name: str, size_mm: float = 18.0):
    """Emerald circular badge with white initials — fallback when no logo uploaded."""
    ini = _initials(company_name)
    d = Drawing(size_mm * mm, size_mm * mm)
    r = size_mm * mm / 2
    d.add(Circle(r, r, r - 1, fillColor=_EMERALD, strokeColor=_EMERALD_D, strokeWidth=0.8))
    # Scale font size to number of chars (smaller circle fits fewer chars comfortably).
    fs = 12 if len(ini) <= 2 else 10 if len(ini) == 3 else 8
    d.add(String(r, r - fs * 0.35, ini,
                 textAnchor="middle",
                 fillColor=_WHITE,
                 fontName="Helvetica-Bold",
                 fontSize=fs))
    return d


def _logo_flowable(company: dict, size_mm: float = 18.0):
    """Return a flowable for the company logo — real image if uploaded, else monogram."""
    logo_data = company.get("logo") or ""
    if logo_data.startswith("data:image"):
        try:
            b64 = logo_data.split(",", 1)[1]
            return Image(BytesIO(base64.b64decode(b64)),
                        width=size_mm * mm, height=size_mm * mm, kind="proportional")
        except Exception:
            pass
    return _monogram_badge(company.get("name") or "", size_mm=size_mm)


def build_lr_pdf(company: dict, customer: dict, trip: dict) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=0, rightMargin=0,        # header band bleeds to edge
        topMargin=0, bottomMargin=6 * mm,
        title=f"GCN {trip.get('lr_number','')}",
    )
    styles = getSampleStyleSheet()
    F, FB = _UNI_FONT, _UNI_FONT_BOLD

    # ---- Styles ----
    styles.add(ParagraphStyle(name="HCoName",  fontName=FB, fontSize=14, leading=16, textColor=_WHITE))
    styles.add(ParagraphStyle(name="HCoAddr",  fontName=F,  fontSize=7.5, leading=10, textColor=colors.HexColor("#94A3B8")))
    styles.add(ParagraphStyle(name="HTitle",   fontName=FB, fontSize=17, leading=19, textColor=_WHITE, alignment=2))
    styles.add(ParagraphStyle(name="HSub",     fontName=FB, fontSize=8,  leading=10, textColor=_EMERALD_L, alignment=2))
    styles.add(ParagraphStyle(name="Label",    fontName=FB, fontSize=7,  leading=9,  textColor=_MUTED))
    styles.add(ParagraphStyle(name="LabelE",   fontName=FB, fontSize=7,  leading=9,  textColor=_EMERALD_D))
    styles.add(ParagraphStyle(name="Body",     fontName=F,  fontSize=8.5, leading=11, textColor=_NAVY))
    styles.add(ParagraphStyle(name="BodyM",    fontName=F,  fontSize=8,  leading=10, textColor=_SLATE))
    styles.add(ParagraphStyle(name="Small",    fontName=F,  fontSize=7.5, leading=10, textColor=_NAVY))
    styles.add(ParagraphStyle(name="SmallM",   fontName=F,  fontSize=7.5, leading=10, textColor=_MUTED))
    styles.add(ParagraphStyle(name="PillW",    fontName=FB, fontSize=11, leading=13, textColor=_WHITE, alignment=1))
    styles.add(ParagraphStyle(name="PillLbl",  fontName=FB, fontSize=6.5, leading=8, textColor=_EMERALD_L, alignment=1))
    styles.add(ParagraphStyle(name="Party",    fontName=FB, fontSize=10.5, leading=12.5, textColor=_NAVY))
    styles.add(ParagraphStyle(name="Route",    fontName=FB, fontSize=10, leading=12, textColor=_NAVY, alignment=1))
    styles.add(ParagraphStyle(name="RouteM",   fontName=F,  fontSize=7,  leading=9,  textColor=_MUTED, alignment=1))

    story = []
    company_name = company.get("name") or "YOUR COMPANY NAME"

    # ================== 1. NAVY HEADER — Logo+Name (L) · Title (R) ==================
    # LEFT: logo/monogram + company name only (no duplicated address in header)
    left_lines = [
        Paragraph(company_name, styles["HCoName"]),
    ]
    if company.get("address"):
        left_lines.append(Paragraph(company["address"], styles["HCoAddr"]))
    logo = _logo_flowable(company, size_mm=17)
    left_col = Table([[logo, left_lines]], colWidths=[22 * mm, 106 * mm])
    left_col.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (0, 0), 8),
    ]))

    # RIGHT: title + subtitle only
    right_col = [
        Paragraph("GOODS CONSIGNMENT NOTE", styles["HTitle"]),
        Paragraph("<font color='#10B981'>LORRY RECEIPT · GCN</font>", styles["HSub"]),
    ]

    hdr = Table([[left_col, right_col]], colWidths=[128 * mm, 82 * mm])
    hdr.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _NAVY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (0, 0), 12),
        ("RIGHTPADDING", (0, 0), (0, 0), 6),
        ("LEFTPADDING", (1, 0), (1, 0), 6),
        ("RIGHTPADDING", (1, 0), (1, 0), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LINEBELOW", (0, 0), (-1, 0), 2.4, _EMERALD),
    ]))
    story.append(hdr)
    story.append(Spacer(1, 5))

    # ================== 2. GCN META PILLS ==================
    def _pill(lbl, val):
        t = Table([[Paragraph(lbl, styles["PillLbl"])],
                   [Paragraph(val, styles["PillW"])]], colWidths=[60 * mm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), _NAVY2),
            ("BOX", (0, 0), (-1, -1), 1.0, _EMERALD),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, 0), 3),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 0),
            ("TOPPADDING", (0, 1), (-1, 1), 0),
            ("BOTTOMPADDING", (0, 1), (-1, 1), 4),
        ]))
        return t

    pills_row = Table([[
        _pill("GCN NUMBER", trip.get("lr_number") or "—"),
        _pill("DATE OF ISSUE", trip.get("date") or "—"),
        _pill("TIME", trip.get("lr_time") or "—"),
    ]], colWidths=[63 * mm, 63 * mm, 63 * mm])
    pills_row.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(pills_row)
    story.append(Spacer(1, 6))

    # Helper — wrap widget in 10mm horizontal margin (doc has 0 side margins).
    def _margined(widget):
        outer = Table([[widget]], colWidths=[210 * mm])
        outer.setStyle(TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ]))
        return outer

    # ================== 3. PARTY BLOCKS (stacked with left navy rail) ==================
    consignor_name = trip.get("consignor_name") or trip.get("from_location") or "—"
    site_loc, site_contact = _resolve_consignee_site(trip, customer)

    def _party_block(role, body_lines):
        body_cell = [Paragraph(role, styles["LabelE"])] + [Spacer(1, 1)] + body_lines
        inner = Table([["", body_cell]], colWidths=[3 * mm, 183 * mm])
        inner.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, 0), _NAVY),   # left navy rail
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (1, 0), (1, 0), 10),
            ("RIGHTPADDING", (1, 0), (1, 0), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("BACKGROUND", (1, 0), (1, 0), _BG_SLATE),
            ("BOX", (0, 0), (-1, -1), 0.4, _LINE),
        ]))
        return inner

    consignor_body = [
        Paragraph(consignor_name, styles["Party"]),
        Paragraph("<font color='#64748B'>Origin loading point</font>", styles["SmallM"]),
    ]
    consignee_body = [Paragraph(customer.get("name", "—") or "—", styles["Party"])]
    if customer.get("address"):
        consignee_body.append(Paragraph(customer["address"], styles["BodyM"]))
    cust_id_bits = []
    if customer.get("gstin"): cust_id_bits.append(f"<b>GSTIN</b> {customer['gstin']}")
    if customer.get("state"): cust_id_bits.append(f"<b>State</b> {customer['state']}")
    if customer.get("pincode"): cust_id_bits.append(f"<b>PIN</b> {customer['pincode']}")
    if cust_id_bits:
        consignee_body.append(Paragraph("   ".join(cust_id_bits), styles["Small"]))
    consignee_body.append(Paragraph(f"<b>Ship-To:</b> {site_loc}", styles["Small"]))
    consignee_body.append(Paragraph(f"<b>Site Contact:</b> {site_contact}", styles["Small"]))

    story.append(_margined(_party_block("CONSIGNOR · FROM", consignor_body)))
    story.append(Spacer(1, 3))
    story.append(_margined(_party_block("CONSIGNEE · TO", consignee_body)))
    story.append(Spacer(1, 6))

    # ================== 4. ROUTE TIMELINE ==================
    from_txt = trip.get("from_location", "—")
    if trip.get("from_pincode"):
        from_txt = f"{from_txt} · {trip['from_pincode']}"
    to_txt = trip.get("to_location", "—")
    if trip.get("to_pincode"):
        to_txt = f"{to_txt} · {trip['to_pincode']}"

    tl = Table([[
        Paragraph(f"<b>{from_txt}</b>", styles["Route"]),
        Paragraph("<font color='#059669' size='13'>●━━━━━━━━━━━━━━━━━━━━●</font>", styles["Route"]),
        Paragraph(f"<b>{to_txt}</b>", styles["Route"]),
    ], [
        Paragraph("ORIGIN", styles["RouteM"]),
        Paragraph("", styles["RouteM"]),
        Paragraph("DESTINATION", styles["RouteM"]),
    ]], colWidths=[60 * mm, 70 * mm, 60 * mm])
    tl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _EMERALD_L),
        ("BOX", (0, 0), (-1, -1), 0.5, _EMERALD),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, 0), 4),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 1),
        ("TOPPADDING", (0, 1), (-1, 1), 0),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 4),
    ]))
    story.append(_margined(tl))
    story.append(Spacer(1, 5))

    # ================== 5. KV GRID (2-col, borderless w/ light rule) ==================
    def _kv(k, v):
        return [Paragraph(k, styles["Label"]),
                Paragraph(str(v) if v not in (None, "", 0) else "—", styles["Body"])]

    net_wt = round(float(trip.get("gross_weight", 0) or 0) - float(trip.get("tare_weight", 0) or 0), 3) or float(trip.get("tons", 0) or 0)

    kv_rows = [
        _kv("Tanker No.",       trip.get("vehicle_number", "")) + _kv("Product / Material", trip.get("load_details", "")),
        _kv("Purchase Invoice", trip.get("external_invoice_no", "")) + _kv("Vehicle Seal No.", trip.get("seal_numbers", "")),
        _kv("Customer Invoice", trip.get("customer_invoice_no", "")) + _kv("Waybill No.", trip.get("waybill_no", "")),
        _kv("Purchased At",     trip.get("customer_purchased_at", "")) + _kv("Invoice Value",
              f"₹ {_fmt(trip.get('invoice_value', 0))}" if trip.get("invoice_value") else ""),
        _kv("Driver Name",      trip.get("lr_driver_name") or trip.get("driver_name") or "")
          + _kv("Driver Mobile", trip.get("lr_driver_mobile") or trip.get("driver_mobile") or ""),
    ]
    kv_tbl = Table(kv_rows, colWidths=[26 * mm, 65 * mm, 26 * mm, 73 * mm])
    kv_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, _LINE_L),
        ("LINEABOVE", (0, 0), (-1, 0), 0.6, _NAVY),
    ]))
    story.append(_margined(kv_tbl))
    story.append(Spacer(1, 5))

    # ================== 6. WEIGHTS STRIP (Net Wt in emerald ring) ==================
    def _wtile(lbl, val, hi=False):
        lbl_style = "LabelE" if hi else "Label"
        inner = [Paragraph(lbl, styles[lbl_style]), Paragraph(f"<b>{val}</b>", styles["Body"])]
        t = Table([[inner]], colWidths=[62 * mm])
        _s = [
            ("BACKGROUND", (0, 0), (-1, -1), _BG_SLATE),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("BOX", (0, 0), (-1, -1), 0.4, _LINE),
        ]
        if hi:
            _s.append(("BOX", (0, 0), (-1, -1), 1.6, _EMERALD))
            _s.append(("BACKGROUND", (0, 0), (-1, -1), _EMERALD_L))
        t.setStyle(TableStyle(_s))
        return t

    wstrip = Table([[
        _wtile("GROSS WT.", f"{_fmt(trip.get('gross_weight',0))} MT"),
        _wtile("TARE WT.",  f"{_fmt(trip.get('tare_weight',0))} MT"),
        _wtile("NET WT.",   f"{_fmt(net_wt)} MT", hi=True),
    ]], colWidths=[63 * mm, 63 * mm, 63 * mm])
    wstrip.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 2)]))
    story.append(_margined(wstrip))
    story.append(Spacer(1, 6))

    # ================== 7. UNLOADING LOG (emerald header) ==================
    story.append(_margined(Paragraph("<font color='#047857'><b>UNLOADING VERIFICATION · BY SITE OFFICIALS</b></font>", styles["Small"])))
    story.append(Spacer(1, 2))
    un_headers = [
        Paragraph("<font color='#FFFFFF'><b>Date of<br/>Arrival</b></font>", styles["Small"]),
        Paragraph("<font color='#FFFFFF'><b>Arrival<br/>Time</b></font>", styles["Small"]),
        Paragraph("<font color='#FFFFFF'><b>Unloading<br/>Start</b></font>", styles["Small"]),
        Paragraph("<font color='#FFFFFF'><b>Unloading<br/>End</b></font>", styles["Small"]),
        Paragraph("<font color='#FFFFFF'><b>Date of<br/>Departure</b></font>", styles["Small"]),
        Paragraph("<font color='#FFFFFF'><b>Shortage /<br/>Excess (MT)</b></font>", styles["Small"]),
        Paragraph("<font color='#FFFFFF'><b>Temp.<br/>(°C)</b></font>", styles["Small"]),
        Paragraph("<font color='#FFFFFF'><b>Seal<br/>Status</b></font>", styles["Small"]),
        Paragraph("<font color='#FFFFFF'><b>Remarks</b></font>", styles["Small"]),
    ]
    col_widths = [20*mm, 17*mm, 20*mm, 20*mm, 22*mm, 25*mm, 15*mm, 18*mm, 33*mm]
    un_tbl = Table([un_headers, [""] * len(un_headers)], colWidths=col_widths)
    un_tbl.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.4, _LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, _LINE_L),
        ("BACKGROUND", (0, 0), (-1, 0), _EMERALD_D),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, 0), 4),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
        ("TOPPADDING", (0, 1), (-1, 1), 12),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 2),
    ]))
    story.append(_margined(un_tbl))
    story.append(Spacer(1, 2))

    sig_headers = [
        Paragraph("<b>Site Officer Name</b>", styles["Small"]),
        Paragraph("<b>Designation</b>", styles["Small"]),
        Paragraph("<b>Mobile</b>", styles["Small"]),
        Paragraph("<b>Signature &amp; Stamp</b>", styles["Small"]),
        Paragraph("<b>Date &amp; Time</b>", styles["Small"]),
    ]
    sig_tbl = Table([sig_headers, [""] * len(sig_headers)], colWidths=[45*mm, 30*mm, 30*mm, 55*mm, 30*mm])
    sig_tbl.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.4, _LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, _LINE_L),
        ("BACKGROUND", (0, 0), (-1, 0), _BG_SLATE),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, 0), 4),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
        ("TOPPADDING", (0, 1), (-1, 1), 14),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 3),
    ]))
    story.append(_margined(sig_tbl))
    story.append(Spacer(1, 4))

    # ================== 8. GST DECLARATION + COMPANY GSTIN ==================
    # Company GSTIN moved here so it appears exactly once (not duplicated in header).
    company_id_bits = []
    if company.get("gstin"): company_id_bits.append(f"<b>GSTIN</b> {company['gstin']}")
    if company.get("pan"):   company_id_bits.append(f"<b>PAN</b> {company['pan']}")
    if company.get("phone"): company_id_bits.append(f"<b>Ph</b> {company['phone']}")
    if company.get("email"): company_id_bits.append(company["email"])
    id_line = "   ·   ".join(company_id_bits) if company_id_bits else ""

    gst_para = Paragraph(
        "<b>GST Reverse Charge Declaration:</b> As a Goods Transport Agency (GTA) under "
        "Notification No. 5/2017 Central Tax dated 19-Jun-2017 (CBEC · GOI), we are exempt "
        "from mandatory GST registration for this service and the GST liability is discharged "
        "by the recipient on Reverse Charge basis under Section 9(3) of the CGST Act, 2017."
        + (f"<br/><font color='#64748B' size='7'>{id_line}</font>" if id_line else ""),
        styles["Small"],
    )
    gst_box = Table([[gst_para]], colWidths=[190 * mm])
    gst_box.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, _NAVY),
        ("BACKGROUND", (0, 0), (-1, -1), _BG_SLATE),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(_margined(gst_box))
    story.append(Spacer(1, 4))

    # ================== 9. FOOTER (signatory + note) ==================
    foot_left = Paragraph(
        "<font color='#64748B' size='7'><b>Note</b> — Computer-generated Goods Consignment Note. "
        "Valid without a manual signature or the Company's seal.<br/>"
        "Terms &amp; Conditions of carriage are on page 2 overleaf.</font>",
        styles["Small"],
    )
    foot_right = Paragraph(
        f"<b>For {company_name}</b><br/><br/><font color='#64748B'>______________________________<br/>"
        "Authorised Signatory</font>",
        styles["Body"],
    )
    foot = Table([[foot_left, foot_right]], colWidths=[120 * mm, 70 * mm])
    foot.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LINEABOVE", (0, 0), (-1, 0), 0.6, _EMERALD),
        ("TOPPADDING", (0, 0), (-1, 0), 4),
    ]))
    story.append(_margined(foot))

    # ══════════════════════════════════════════════════════════════════
    # PAGE 2 — Terms & Conditions (2-page LOCK)
    # Wrapped in a KeepInFrame with mode='shrink' so long content never
    # spills onto a 3rd page — worst case the text scales down by a few pts.
    # ══════════════════════════════════════════════════════════════════
    story.append(PageBreak())

    # Mini navy header (LOGO+NAME left · GCN meta right — same identity, thinner)
    mini_left = Table([[_logo_flowable(company, size_mm=12),
                       Paragraph(company_name, styles["HCoName"])]],
                     colWidths=[16 * mm, 112 * mm])
    mini_left.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (0, 0), 6),
    ]))
    mini_right = Paragraph(
        f"<font color='#94A3B8' size='9'><b>GCN No.</b> {trip.get('lr_number','—')}   ·   "
        f"<b>Date:</b> {trip.get('date','')}</font>",
        styles["HCoAddr"],
    )
    mini_hdr = Table([[mini_left, mini_right]], colWidths=[128 * mm, 82 * mm])
    mini_hdr.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _NAVY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (0, 0), 12),
        ("RIGHTPADDING", (0, 0), (0, 0), 6),
        ("LEFTPADDING", (1, 0), (1, 0), 6),
        ("RIGHTPADDING", (1, 0), (1, 0), 12),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LINEBELOW", (0, 0), (-1, 0), 2.0, _EMERALD),
    ]))
    story.append(mini_hdr)
    story.append(Spacer(1, 4))

    # ================== PAGE 2 BODY — WRAPPED IN ONE KeepInFrame ==================
    # Iter112 · Bilingual T&C doubles the clause block (EN + TE), so we now
    # collect the FULL page-2 body (title, subtitle, Seal callout, numbered
    # T&C table, Consignee-Ack panel) into ONE KeepInFrame(mode='shrink').
    # This lets ReportLab measure and scale the stack as a single unit,
    # guaranteeing the 2-page lock even if a future clause is added.

    tc_title = Paragraph(
        "TERMS &amp; CONDITIONS · TRANSPORT AND SITE UNLOADING PROTOCOL",
        ParagraphStyle(name="TCT", fontName=FB, fontSize=12, leading=14,
                       textColor=_NAVY, alignment=1))
    tc_sub = Paragraph(
        "<font color='#64748B'><i>These conditions govern carriage under this "
        "Goods Consignment Note and are binding on the consignor, consignee and "
        "any authorised representative at the site.</i></font>",
        ParagraphStyle(name="TCS", fontName=F, fontSize=7.5, leading=9,
                       textColor=_MUTED, alignment=1))

    # ---- Highlighted SEAL VERIFICATION callout — compressed for Iter112.
    _AMBER      = colors.HexColor("#B45309")
    _AMBER_L    = colors.HexColor("#FEF3C7")
    seal_body = ParagraphStyle(name="SealBody", fontName=F, fontSize=7.5, leading=9.5,
                                textColor=_NAVY)
    seal_title = ParagraphStyle(name="SealTitle", fontName=FB, fontSize=8.5, leading=10,
                                 textColor=_AMBER)
    seal_lines = [
        Paragraph("⚠  IMPORTANT · SEAL VERIFICATION &amp; UNLOADING PROTOCOL", seal_title),
        Spacer(1, 2),
        Paragraph(
            "Bitumen, CRMB and PMB are dispatched <b>without</b> refinery / supplier seals. "
            "For Emulsion, LDO, FO and other products where an official loading-facility seal "
            "is provided, the seal number <b>must be verified against the loading document / "
            "invoice</b> before unloading commences. Any transporter-applied safety seal is a "
            "transit-security measure only and is <b>not</b> equivalent to an official "
            "refinery / supplier seal — damage, absence or apparent tampering of a "
            "transporter seal alone <b>shall not be grounds to stop or refuse unloading</b>. "
            "Any discrepancy must be recorded in the unloading remarks and immediately "
            "brought to the attention of the concerned site / consignor / consignee "
            "representative.",
            seal_body,
        ),
    ]
    seal_box = Table([[seal_lines]], colWidths=[190 * mm])
    seal_box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _AMBER_L),
        ("BOX", (0, 0), (-1, -1), 0.8, _AMBER),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))

    # T&C table — pill-numbered (wider box to fit 2-digit numbers cleanly).
    tc_body_style = ParagraphStyle(name="TCBody", fontName=F, fontSize=6.6, leading=8.0,
                                    textColor=_NAVY, spaceAfter=0)
    # Iter112 · Use Anek Telugu (same font as the QORVENA web UI `.telugu`
    # class) — DejaVuSans has NO Telugu glyphs and rendered as tofu.
    tc_body_te_style = ParagraphStyle(name="TCBodyTE", fontName=_TE_FONT, fontSize=6.2, leading=7.6,
                                       textColor=colors.HexColor("#334155"),
                                       spaceBefore=0, spaceAfter=0.3)
    circle_style = ParagraphStyle(name="Circle", fontName=FB, fontSize=8, leading=10,
                                   textColor=_WHITE, alignment=1)
    tc_rows = []
    for i, (t_en, t_te) in enumerate(zip(LR_TERMS_EN, LR_TERMS_TE), start=1):
        num = Table([[Paragraph(f"<b>{i}</b>", circle_style)]], colWidths=[9 * mm], rowHeights=[7 * mm])
        num.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), _EMERALD_D),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        clause_block = [
            Paragraph(t_en, tc_body_style),
            Paragraph(t_te, tc_body_te_style),
        ]
        tc_rows.append([num, clause_block])

    tc_tbl = Table(tc_rows, colWidths=[11 * mm, 179 * mm])
    tc_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 0.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0.5),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, _LINE_L),
    ]))

    # Consignee ack strip
    ack_lines = [
        Paragraph("<font color='#047857'><b>CONSIGNEE ACKNOWLEDGMENT</b></font>", styles["LabelE"]),
        Spacer(1, 2),
        Paragraph(
            "I / We hereby confirm that the material described on this Goods Consignment Note has been "
            "received in good condition and quantity, and that any applicable seal condition / "
            "discrepancy has been recorded as required. I / We have read and agree to the Terms "
            "&amp; Conditions above.",
            styles["Body"],
        ),
        Spacer(1, 14),
        Paragraph(
            "<b>Consignee Signature &amp; Stamp:</b> _________________________________ &nbsp;&nbsp; "
            "<b>Name:</b> _____________________ &nbsp;&nbsp; <b>Date:</b> _____________",
            styles["Body"],
        ),
    ]
    ack_tbl = Table([[ack_lines]], colWidths=[190 * mm])
    ack_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _BG_SLATE),
        ("BOX", (0, 0), (-1, -1), 0.5, _NAVY),
        ("LINEBELOW", (0, 0), (-1, -1), 2.4, _EMERALD),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))

    # ---- 2-PAGE LOCK: wrap the ENTIRE page-2 body (title + subtitle + seal
    # callout + T&C table + ack panel) in ONE KeepInFrame(mode='shrink'). This
    # is what fixes the Iter112 page-3 spillover: shrink now measures the full
    # stack as one unit, and maxHeight is set to the true available height on
    # page 2 (A4 297mm - 6mm bottom margin - mini header ~13mm - spacer ~2mm
    # ≈ 275mm). If content ever exceeds this, ReportLab compresses it in-place
    # instead of paginating to a 3rd page.
    page2_body_stack = [
        tc_title,
        Spacer(1, 2),
        tc_sub,
        Spacer(1, 6),
        seal_box,
        Spacer(1, 6),
        tc_tbl,
        Spacer(1, 4),
        ack_tbl,
    ]
    locked = KeepInFrame(
        maxWidth=190 * mm,
        maxHeight=275 * mm,
        content=page2_body_stack,
        mode="shrink",   # shrink to fit — guarantees no page 3.
    )
    story.append(_margined(locked))

    doc.build(story)
    return buf.getvalue()
