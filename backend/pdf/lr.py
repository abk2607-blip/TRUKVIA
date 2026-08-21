"""Iter101 · Original Goods Consignment Note (GCN / Lorry Receipt) PDF.

Complete redesign — no visual similarity to existing industry LR templates.
Distinctive elements:
  · Deep-ink + amber-industrial palette (unique for bitumen transport).
  · Top accent bar with gold underline (own signature).
  · Compact 3-tile GCN header (LR No · Date · Time) fused with the title block.
  · Consignor / Consignee as facing "party cards" with monogram stripe.
  · Full-width Route Strip (FROM → TO arrow) with pincodes as sub-line.
  · 4-column Consignment Grid + separate Driver + Weight tile row.
  · Site-Officials Unloading Log preserved 10-column table (business critical).
  · Signature strip → GST Declaration → Signatory footer.
  · Page 2: 2-column Terms card (16 original clauses) + Consignee Ack Panel.

Financial logic and trip data are UNTOUCHED — this is presentation only.
"""
from ._base import _fmt, LR_TERMS_EN, _UNI_FONT, _UNI_FONT_BOLD, _TE_FONT
from io import BytesIO
import base64
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, Image, PageBreak, KeepTogether,
)

# ================== Palette (original QORVENA identity) ==================
_INK      = colors.HexColor("#0F172A")   # deep slate
_INK2     = colors.HexColor("#334155")
_MUTED    = colors.HexColor("#64748B")
_LINE     = colors.HexColor("#CBD5E1")
_LINE_L   = colors.HexColor("#E2E8F0")
_ACCENT   = colors.HexColor("#B45309")   # amber-800 — industrial gold
_ACCENT_L = colors.HexColor("#FDE68A")   # amber-200
_BG_CREAM = colors.HexColor("#FDFBF7")   # warm off-white for cards
_BG_STRIPE = colors.HexColor("#F8FAFC")


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


def _accent_top_bar():
    """Full-width amber accent bar — own signature element on page 1."""
    bar = Table([[""]], colWidths=[190 * mm], rowHeights=[3 * mm])
    bar.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), _ACCENT)]))
    return bar


def build_lr_pdf(company: dict, customer: dict, trip: dict) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=10 * mm, rightMargin=10 * mm,
        topMargin=8 * mm, bottomMargin=10 * mm,
        title=f"GCN {trip.get('lr_number','')}",
    )
    styles = getSampleStyleSheet()
    F, FB = _UNI_FONT, _UNI_FONT_BOLD

    # ---- Styles ----
    styles.add(ParagraphStyle(name="LRHead",    fontName=FB, fontSize=13, leading=15, textColor=_INK))
    styles.add(ParagraphStyle(name="LRTitle",   fontName=FB, fontSize=18, leading=20, textColor=_INK, alignment=2))
    styles.add(ParagraphStyle(name="LRTitleSub", fontName=F, fontSize=8,  leading=10, textColor=_MUTED, alignment=2))
    styles.add(ParagraphStyle(name="LRBody",    fontName=F,  fontSize=8.5, leading=11, textColor=_INK))
    styles.add(ParagraphStyle(name="LRBodyM",   fontName=F,  fontSize=8.5, leading=11, textColor=_INK2))
    styles.add(ParagraphStyle(name="LRSmall",   fontName=F,  fontSize=7.5, leading=9.5, textColor=_INK))
    styles.add(ParagraphStyle(name="LRSmallB",  fontName=FB, fontSize=7.5, leading=9.5, textColor=_INK))
    styles.add(ParagraphStyle(name="LRLabel",   fontName=FB, fontSize=7,  leading=9,  textColor=_MUTED))
    styles.add(ParagraphStyle(name="LRLabelA",  fontName=FB, fontSize=7,  leading=9,  textColor=_ACCENT))
    styles.add(ParagraphStyle(name="LRMono",    fontName=FB, fontSize=11, leading=13, textColor=_INK))
    styles.add(ParagraphStyle(name="LRParty",   fontName=FB, fontSize=10.5, leading=13, textColor=_INK))
    styles.add(ParagraphStyle(name="LRRoute",   fontName=FB, fontSize=11, leading=14, textColor=_INK, alignment=1))

    story = []

    # ================== 1. TOP ACCENT BAR ==================
    story.append(_accent_top_bar())
    story.append(Spacer(1, 6))

    # ================== 2. HEADER (Logo + Company | Title block) ==================
    company_name = company.get("name") or "YOUR COMPANY NAME"
    company_lines = [Paragraph(f"<b>{company_name}</b>", styles["LRHead"])]
    if company.get("address"):
        company_lines.append(Paragraph(company["address"], styles["LRBodyM"]))
    contact_bits = []
    if company.get("phone"): contact_bits.append(f"<b>Ph</b> {company['phone']}")
    if company.get("email"): contact_bits.append(company["email"])
    if contact_bits:
        company_lines.append(Paragraph("   ".join(contact_bits), styles["LRBodyM"]))
    id_bits = []
    if company.get("gstin"): id_bits.append(f"<b>GSTIN</b> {company['gstin']}")
    if company.get("pan"):   id_bits.append(f"<b>PAN</b> {company['pan']}")
    if company.get("state"): id_bits.append(f"<b>State</b> {company['state']}")
    if id_bits:
        company_lines.append(Paragraph("   ".join(id_bits), styles["LRSmall"]))

    logo_img = None
    logo_data = company.get("logo") or ""
    if logo_data.startswith("data:image"):
        try:
            b64 = logo_data.split(",", 1)[1]
            logo_img = Image(BytesIO(base64.b64decode(b64)), width=20 * mm, height=20 * mm, kind="proportional")
        except Exception:
            logo_img = None

    if logo_img is not None:
        left_block = Table([[logo_img, company_lines]], colWidths=[24 * mm, 106 * mm])
        left_block.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (0, 0), 4),
        ]))
    else:
        left_block = company_lines

    title_block = [
        Paragraph("GOODS CONSIGNMENT NOTE", styles["LRTitle"]),
        Paragraph("<font color='#B45309'><b>LORRY RECEIPT · GCN</b></font>", styles["LRTitleSub"]),
    ]
    header_tbl = Table([[left_block, title_block]], colWidths=[130 * mm, 60 * mm])
    header_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, _ACCENT),
    ]))
    story.append(header_tbl)
    story.append(Spacer(1, 6))

    # ================== 3. GCN META TILES (LR # · Date · Time) ==================
    gc_row = [
        [Paragraph("GCN NUMBER", styles["LRLabelA"]),
         Paragraph("DATE OF ISSUE", styles["LRLabelA"]),
         Paragraph("TIME", styles["LRLabelA"])],
        [Paragraph(f"<font size='11'><b>{trip.get('lr_number','—')}</b></font>", styles["LRMono"]),
         Paragraph(trip.get("date", "—"), styles["LRMono"]),
         Paragraph(trip.get("lr_time", "—") or "—", styles["LRMono"])],
    ]
    gc_tbl = Table(gc_row, colWidths=[80 * mm, 55 * mm, 55 * mm])
    gc_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _BG_CREAM),
        ("BOX", (0, 0), (-1, -1), 0.4, _ACCENT),
        ("LINEAFTER", (0, 0), (0, -1), 0.3, _LINE),
        ("LINEAFTER", (1, 0), (1, -1), 0.3, _LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, 0), 5),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
        ("TOPPADDING", (0, 1), (-1, 1), 0),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 5),
    ]))
    story.append(gc_tbl)
    story.append(Spacer(1, 8))

    # ================== 4. PARTY CARDS (Consignor | Consignee) ==================
    consignor_name = trip.get("consignor_name") or trip.get("from_location") or "—"
    site_loc, site_contact = _resolve_consignee_site(trip, customer)

    def _party_card(role, body_lines):
        stripe = Table([[""]], colWidths=[92 * mm], rowHeights=[1.5 * mm])
        stripe.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), _ACCENT)]))
        inner = [
            stripe,
            Paragraph(role, styles["LRLabelA"]),
            Spacer(1, 2),
        ] + body_lines
        card = Table([[inner]], colWidths=[92 * mm])
        card.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), _BG_CREAM),
            ("BOX", (0, 0), (-1, -1), 0.4, _LINE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        return card

    consignor_lines = [
        Paragraph(consignor_name, styles["LRParty"]),
        Paragraph("<font color='#64748B'>Origin loading point</font>", styles["LRSmall"]),
    ]
    consignee_body = [
        Paragraph(customer.get("name", "—") or "—", styles["LRParty"]),
    ]
    if customer.get("address"):
        consignee_body.append(Paragraph(customer["address"], styles["LRBodyM"]))
    cust_id_bits = []
    if customer.get("gstin"): cust_id_bits.append(f"<b>GSTIN</b> {customer['gstin']}")
    if customer.get("state"): cust_id_bits.append(f"<b>State</b> {customer['state']}")
    if customer.get("pincode"): cust_id_bits.append(f"<b>PIN</b> {customer['pincode']}")
    if cust_id_bits:
        consignee_body.append(Paragraph("   ".join(cust_id_bits), styles["LRSmall"]))
    consignee_body.append(Spacer(1, 2))
    consignee_body.append(Paragraph(f"<b>Ship-To:</b> {site_loc}", styles["LRSmall"]))
    consignee_body.append(Paragraph(f"<b>Site Contact:</b> {site_contact}", styles["LRSmall"]))

    party_tbl = Table([[_party_card("CONSIGNOR · FROM", consignor_lines),
                        _party_card("CONSIGNEE · TO", consignee_body)]],
                     colWidths=[92 * mm, 92 * mm])
    party_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (0, 0), 6),
    ]))
    story.append(party_tbl)
    story.append(Spacer(1, 8))

    # ================== 5. ROUTE STRIP (FROM → TO) ==================
    from_txt = trip.get("from_location", "—")
    if trip.get("from_pincode"):
        from_txt = f"{from_txt} · {trip['from_pincode']}"
    to_txt = trip.get("to_location", "—")
    if trip.get("to_pincode"):
        to_txt = f"{to_txt} · {trip['to_pincode']}"
    route_tbl = Table([[
        Paragraph(f"<font color='#B45309' size='7'><b>ROUTE</b></font>  &nbsp; <b>{from_txt}</b>  <font color='#B45309'>➜</font>  <b>{to_txt}</b>", styles["LRBody"]),
    ]], colWidths=[190 * mm])
    route_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _ACCENT_L),
        ("BOX", (0, 0), (-1, -1), 0.4, _ACCENT),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(route_tbl)
    story.append(Spacer(1, 8))

    # ================== 6. CONSIGNMENT DETAILS GRID ==================
    def _kv(k, v):
        return [Paragraph(k, styles["LRLabel"]),
                Paragraph(str(v) if v not in (None, "", 0) else "—", styles["LRBody"])]

    net_wt = round(float(trip.get("gross_weight", 0) or 0) - float(trip.get("tare_weight", 0) or 0), 3) or float(trip.get("tons", 0) or 0)
    grid = [
        _kv("Tanker No.",         trip.get("vehicle_number", "")) + _kv("Product / Material", trip.get("load_details", "")),
        _kv("Purchase Invoice",   trip.get("external_invoice_no", "")) + _kv("Vehicle Seal No.", trip.get("seal_numbers", "")),
        _kv("Customer Invoice",   trip.get("customer_invoice_no", "")) + _kv("Waybill No.", trip.get("waybill_no", "")),
        _kv("Purchased At",       trip.get("customer_purchased_at", "")) + _kv("Invoice Value",
             f"₹ {_fmt(trip.get('invoice_value', 0))}" if trip.get("invoice_value") else ""),
    ]
    grid_tbl = Table(grid, colWidths=[24 * mm, 66 * mm, 24 * mm, 76 * mm])
    _grid_style = [
        ("BOX", (0, 0), (-1, -1), 0.4, _LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, _LINE_L),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for r in range(len(grid)):
        if r % 2 == 0:
            _grid_style.append(("BACKGROUND", (0, r), (-1, r), _BG_STRIPE))
    grid_tbl.setStyle(TableStyle(_grid_style))
    story.append(grid_tbl)
    story.append(Spacer(1, 4))

    # ================== 7. WEIGHTS ROW (4 tiles) ==================
    def _wtile(label, value, accent=False):
        lbl_style = "LRLabelA" if accent else "LRLabel"
        return [Paragraph(label, styles[lbl_style]), Paragraph(f"<b>{value}</b>", styles["LRBody"])]

    weights = Table([[
        Paragraph("<b>Gross Wt.</b>", styles["LRLabel"]), Paragraph(f"{_fmt(trip.get('gross_weight',0))} MT", styles["LRBody"]),
        Paragraph("<b>Tare Wt.</b>", styles["LRLabel"]),  Paragraph(f"{_fmt(trip.get('tare_weight',0))} MT", styles["LRBody"]),
        Paragraph("<b>Net Wt.</b>", styles["LRLabelA"]),  Paragraph(f"<b>{_fmt(net_wt)} MT</b>", styles["LRBody"]),
        Paragraph("<b>RT KMs</b>", styles["LRLabel"]),    Paragraph(_fmt(trip.get("round_trip_kms", 0)), styles["LRBody"]),
    ]], colWidths=[18*mm, 30*mm, 18*mm, 30*mm, 18*mm, 30*mm, 18*mm, 28*mm])
    weights.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.4, _LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, _LINE_L),
        ("BACKGROUND", (4, 0), (5, -1), _BG_CREAM),
        ("LINEABOVE", (4, 0), (5, 0), 1.0, _ACCENT),
        ("LINEBELOW", (4, 0), (5, -1), 1.0, _ACCENT),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(weights)
    story.append(Spacer(1, 4))

    # ================== 8. DRIVER ROW ==================
    driver_row = Table([[
        Paragraph("<b>Driver Name</b>", styles["LRLabel"]),
        Paragraph(trip.get("lr_driver_name") or trip.get("driver_name") or "—", styles["LRBody"]),
        Paragraph("<b>Driver Mobile</b>", styles["LRLabel"]),
        Paragraph(trip.get("lr_driver_mobile") or trip.get("driver_mobile") or "—", styles["LRBody"]),
    ]], colWidths=[24*mm, 66*mm, 24*mm, 76*mm])
    driver_row.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.4, _LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, _LINE_L),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(driver_row)
    story.append(Spacer(1, 8))

    # ================== 9. UNLOADING LOG (Site Officials) ==================
    story.append(Paragraph("<font color='#B45309'><b>UNLOADING VERIFICATION · BY SITE OFFICIALS</b></font>", styles["LRSmallB"]))
    story.append(Spacer(1, 3))
    un_headers = [
        Paragraph("<b>Date of<br/>Arrival</b>", styles["LRSmall"]),
        Paragraph("<b>Arrival<br/>Time</b>", styles["LRSmall"]),
        Paragraph("<b>Unloading<br/>Start</b>", styles["LRSmall"]),
        Paragraph("<b>Unloading<br/>End</b>", styles["LRSmall"]),
        Paragraph("<b>Date of<br/>Departure</b>", styles["LRSmall"]),
        Paragraph("<b>Extra<br/>KM</b>", styles["LRSmall"]),
        Paragraph("<b>Shortage /<br/>Excess (MT)</b>", styles["LRSmall"]),
        Paragraph("<b>Temp.<br/>(°C)</b>", styles["LRSmall"]),
        Paragraph("<b>Seal<br/>Status</b>", styles["LRSmall"]),
        Paragraph("<b>Remarks</b>", styles["LRSmall"]),
    ]
    col_widths = [18*mm, 15*mm, 18*mm, 18*mm, 20*mm, 14*mm, 22*mm, 14*mm, 16*mm, 35*mm]
    un_tbl = Table([un_headers, [""] * len(un_headers)], colWidths=col_widths)
    un_tbl.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.4, _LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, _LINE_L),
        ("BACKGROUND", (0, 0), (-1, 0), _INK),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, 0), 5),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
        ("TOPPADDING", (0, 1), (-1, 1), 18),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 4),
    ]))
    for r in range(len(un_headers)):
        pass
    story.append(un_tbl)
    story.append(Spacer(1, 4))

    # Signature strip
    sig_headers = [
        Paragraph("<b>Site Officer Name</b>", styles["LRSmall"]),
        Paragraph("<b>Designation</b>", styles["LRSmall"]),
        Paragraph("<b>Mobile</b>", styles["LRSmall"]),
        Paragraph("<b>Signature &amp; Stamp</b>", styles["LRSmall"]),
        Paragraph("<b>Date &amp; Time</b>", styles["LRSmall"]),
    ]
    sig_tbl = Table([sig_headers, [""] * len(sig_headers)], colWidths=[45*mm, 30*mm, 30*mm, 55*mm, 30*mm])
    sig_tbl.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.4, _LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, _LINE_L),
        ("BACKGROUND", (0, 0), (-1, 0), _BG_CREAM),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, 0), 5),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
        ("TOPPADDING", (0, 1), (-1, 1), 22),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 4),
    ]))
    story.append(sig_tbl)
    story.append(Spacer(1, 6))

    # ================== 10. GST DECLARATION ==================
    gst_para = Paragraph(
        "<b>Declaration — GST Reverse Charge:</b> As a Goods Transport Agency (GTA) under Notification "
        "No. 5/2017 Central Tax dated 19-Jun-2017 (CBEC · GOI), we are exempt from mandatory GST "
        "registration for this service and GST liability is discharged by the recipient on Reverse "
        "Charge basis under Section 9(3) of the CGST Act, 2017.",
        styles["LRSmall"],
    )
    gst_box = Table([[gst_para]], colWidths=[190 * mm])
    gst_box.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.4, _INK),
        ("BACKGROUND", (0, 0), (-1, -1), _BG_STRIPE),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(gst_box)

    # ================== 11. FOOTER — signatory + generation note ==================
    story.append(Spacer(1, 10))
    foot_left = Paragraph(
        "<font color='#64748B' size='7'><b>Note</b> — This is a computer-generated Goods "
        "Consignment Note. It is valid without a manual signature or the Company's seal.<br/>"
        "Terms &amp; Conditions of carriage are on page 2 — overleaf.</font>",
        styles["LRSmall"],
    )
    foot_right = Paragraph(
        f"<b>For {company_name}</b><br/><br/><font color='#64748B'>_______________________________<br/>"
        "Authorised Signatory</font>",
        styles["LRBody"],
    )
    foot = Table([[foot_left, foot_right]], colWidths=[120 * mm, 70 * mm])
    foot.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LINEABOVE", (0, 0), (-1, 0), 0.4, _ACCENT),
        ("TOPPADDING", (0, 0), (-1, 0), 6),
    ]))
    story.append(foot)

    # ══════════════════════════════════════════════════════════════════
    # PAGE 2 — TERMS & CONDITIONS (2-column layout, original wording)
    # ══════════════════════════════════════════════════════════════════
    story.append(PageBreak())
    story.append(_accent_top_bar())
    story.append(Spacer(1, 6))

    # TC header
    tc_header_left = Paragraph(f"<b>{company_name}</b><br/><font size='8' color='#64748B'>{company.get('address','')}</font>", styles["LRHead"])
    tc_header_right = Paragraph(
        f"<font color='#B45309'><b>GCN No.</b></font> {trip.get('lr_number','—')}<br/>"
        f"<font color='#B45309'><b>Date:</b></font> {trip.get('date','')}",
        styles["LRBody"],
    )
    tc_header = Table([[tc_header_left, tc_header_right]], colWidths=[130 * mm, 60 * mm])
    tc_header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, _ACCENT),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
    ]))
    story.append(tc_header)
    story.append(Spacer(1, 10))

    story.append(Paragraph(
        "TERMS &amp; CONDITIONS · TRANSPORT AND SITE UNLOADING PROTOCOL",
        ParagraphStyle(name="TCTitle", fontName=FB, fontSize=13, leading=15,
                       textColor=_INK, alignment=1),
    ))
    story.append(Spacer(1, 2))
    story.append(Paragraph(
        "<font color='#64748B'><i>These conditions govern carriage under this Goods Consignment Note "
        "and are binding on the consignor, consignee and any authorised representative at the site.</i></font>",
        ParagraphStyle(name="TCSub", fontName=F, fontSize=8, leading=10, textColor=_MUTED, alignment=1),
    ))
    story.append(Spacer(1, 10))

    # Terms — 2-column layout for compact + modern feel
    tc_body_style = ParagraphStyle(name="TCBody", fontName=F, fontSize=8.2, leading=11, textColor=_INK, spaceAfter=4)
    total = len(LR_TERMS_EN)
    half = (total + 1) // 2
    left_col = [Paragraph(f"<b><font color='#B45309'>{i+1}.</font></b> {t}", tc_body_style) for i, t in enumerate(LR_TERMS_EN[:half])]
    right_col = [Paragraph(f"<b><font color='#B45309'>{half+i+1}.</font></b> {t}", tc_body_style) for i, t in enumerate(LR_TERMS_EN[half:])]

    tc_cols = Table([[left_col, right_col]], colWidths=[92 * mm, 92 * mm])
    tc_cols.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, 0), 8),
        ("RIGHTPADDING", (0, 0), (0, 0), 10),
        ("LEFTPADDING", (1, 0), (1, 0), 10),
        ("RIGHTPADDING", (1, 0), (1, 0), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("BOX", (0, 0), (-1, -1), 0.4, _LINE),
        ("BACKGROUND", (0, 0), (-1, -1), _BG_CREAM),
        ("LINEAFTER", (0, 0), (0, 0), 0.4, _LINE),
    ]))
    story.append(tc_cols)
    story.append(Spacer(1, 14))

    # ================== Consignee Acknowledgment Panel ==================
    ack_lines = [
        Paragraph("<font color='#B45309'><b>CONSIGNEE ACKNOWLEDGMENT</b></font>", styles["LRLabelA"]),
        Spacer(1, 3),
        Paragraph(
            "I / We hereby confirm that the material described on this Goods Consignment Note has been "
            "received in good condition and quantity, all applicable seals were intact, and I / We have "
            "read and agree to the Terms &amp; Conditions above.",
            styles["LRBody"],
        ),
        Spacer(1, 22),
        Paragraph(
            "<b>Consignee Signature &amp; Stamp:</b> _________________________________ &nbsp;&nbsp; "
            "<b>Name:</b> _____________________ &nbsp;&nbsp; <b>Date:</b> _____________",
            styles["LRBody"],
        ),
    ]
    ack_tbl = Table([[ack_lines]], colWidths=[190 * mm])
    ack_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _BG_STRIPE),
        ("BOX", (0, 0), (-1, -1), 0.6, _INK),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(ack_tbl)

    doc.build(story)
    return buf.getvalue()
