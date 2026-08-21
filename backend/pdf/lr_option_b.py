"""Iter101 · LR Design — Option B (Navy + Emerald · Magazine-style stacked).

A completely different visual direction from Option A (Amber + Cream cards).
No visual DNA shared with Option A — different palette, different structure,
different rhythm — so the customer can compare two truly distinct paths.

Distinctive elements of Option B:
  · Full navy header band (letterhead feel) with WHITE title on ink background.
  · Emerald pill badges for GCN No / Date / Time — data reads like a boarding pass.
  · CONSIGNOR and CONSIGNEE stacked vertically (not side-by-side) each with
    a left-side vertical navy rail — gives a magazine / dossier feel.
  · Route shown as a horizontal timeline with dashed line + waypoint dots.
  · Borderless 2-column key/value blocks (only horizontal separators) — airy.
  · Weights strip with Net Wt in an emerald ring.
  · Emerald header on the Unloading Log for a visual break from the navy top.
  · Page 2 Terms: single centred column with big emerald circle-numbered clauses.
"""
from ._base import _fmt, LR_TERMS_EN, _UNI_FONT, _UNI_FONT_BOLD
from io import BytesIO
import base64
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, Image, PageBreak,
)

# ================== Option B Palette ==================
_NAVY      = colors.HexColor("#0F172A")   # deep navy ink
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


def build_lr_pdf_option_b(company: dict, customer: dict, trip: dict) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=0, rightMargin=0,        # header band bleeds to page edge
        topMargin=0, bottomMargin=8 * mm,
        title=f"GCN {trip.get('lr_number','')}",
    )
    styles = getSampleStyleSheet()
    F, FB = _UNI_FONT, _UNI_FONT_BOLD

    # ---- Styles ----
    styles.add(ParagraphStyle(name="HTitle",   fontName=FB, fontSize=20, leading=22, textColor=_WHITE))
    styles.add(ParagraphStyle(name="HSub",     fontName=F,  fontSize=8,  leading=10, textColor=colors.HexColor("#94A3B8")))
    styles.add(ParagraphStyle(name="HCoName",  fontName=FB, fontSize=11, leading=13, textColor=_WHITE, alignment=2))
    styles.add(ParagraphStyle(name="HCoBody",  fontName=F,  fontSize=8,  leading=10, textColor=colors.HexColor("#CBD5E1"), alignment=2))
    styles.add(ParagraphStyle(name="Label",    fontName=FB, fontSize=7,  leading=9,  textColor=_MUTED))
    styles.add(ParagraphStyle(name="LabelE",   fontName=FB, fontSize=7,  leading=9,  textColor=_EMERALD_D))
    styles.add(ParagraphStyle(name="LabelW",   fontName=FB, fontSize=7,  leading=9,  textColor=_WHITE))
    styles.add(ParagraphStyle(name="Body",     fontName=F,  fontSize=8.5, leading=11, textColor=_NAVY))
    styles.add(ParagraphStyle(name="BodyM",    fontName=F,  fontSize=8.5, leading=11, textColor=_SLATE))
    styles.add(ParagraphStyle(name="Small",    fontName=F,  fontSize=7.5, leading=10, textColor=_NAVY))
    styles.add(ParagraphStyle(name="SmallM",   fontName=F,  fontSize=7.5, leading=10, textColor=_MUTED))
    styles.add(ParagraphStyle(name="PillW",    fontName=FB, fontSize=11, leading=13, textColor=_WHITE, alignment=1))
    styles.add(ParagraphStyle(name="PillLbl",  fontName=FB, fontSize=6.5, leading=8, textColor=_EMERALD_L, alignment=1))
    styles.add(ParagraphStyle(name="Party",    fontName=FB, fontSize=11, leading=13, textColor=_NAVY))
    styles.add(ParagraphStyle(name="Route",    fontName=FB, fontSize=10.5, leading=13, textColor=_NAVY, alignment=1))
    styles.add(ParagraphStyle(name="RouteM",   fontName=F,  fontSize=7.5, leading=10, textColor=_MUTED, alignment=1))

    story = []

    # ================== 1. FULL-BLEED NAVY HEADER ==================
    company_name = company.get("name") or "YOUR COMPANY NAME"
    contact_bits = []
    if company.get("phone"): contact_bits.append(company["phone"])
    if company.get("email"): contact_bits.append(company["email"])
    id_bits = []
    if company.get("gstin"): id_bits.append(f"GSTIN {company['gstin']}")
    if company.get("pan"):   id_bits.append(f"PAN {company['pan']}")

    logo_img = None
    logo_data = company.get("logo") or ""
    if logo_data.startswith("data:image"):
        try:
            b64 = logo_data.split(",", 1)[1]
            logo_img = Image(BytesIO(base64.b64decode(b64)), width=16 * mm, height=16 * mm, kind="proportional")
        except Exception:
            logo_img = None

    title_col = [
        Paragraph("GOODS CONSIGNMENT NOTE", styles["HTitle"]),
        Paragraph("<font color='#10B981'><b>LORRY RECEIPT · GCN</b></font>", styles["HSub"]),
    ]
    co_col_lines = [Paragraph(company_name, styles["HCoName"])]
    if company.get("address"):
        co_col_lines.append(Paragraph(company["address"], styles["HCoBody"]))
    if contact_bits:
        co_col_lines.append(Paragraph(" · ".join(contact_bits), styles["HCoBody"]))
    if id_bits:
        co_col_lines.append(Paragraph(" · ".join(id_bits), styles["HCoBody"]))
    if logo_img is not None:
        title_block = Table([[logo_img, title_col]], colWidths=[20 * mm, 90 * mm])
        title_block.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ]))
    else:
        title_block = title_col

    hdr = Table([[title_block, co_col_lines]], colWidths=[110 * mm, 100 * mm])
    hdr.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _NAVY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (0, 0), 12),
        ("RIGHTPADDING", (0, 0), (0, 0), 6),
        ("LEFTPADDING", (1, 0), (1, 0), 6),
        ("RIGHTPADDING", (1, 0), (1, 0), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LINEBELOW", (0, 0), (-1, 0), 2.4, _EMERALD),
    ]))
    story.append(hdr)
    story.append(Spacer(1, 5))

    # ================== 2. GCN META PILLS (boarding-pass style) ==================
    def _pill(lbl, val):
        t = Table([[Paragraph(lbl, styles["PillLbl"])],
                   [Paragraph(val, styles["PillW"])]], colWidths=[60 * mm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), _NAVY2),
            ("BOX", (0, 0), (-1, -1), 1.2, _EMERALD),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, 0), 4),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 0),
            ("TOPPADDING", (0, 1), (-1, 1), 0),
            ("BOTTOMPADDING", (0, 1), (-1, 1), 5),
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

    # ================== 3. PARTY BLOCKS (stacked with left navy rail) ==================
    consignor_name = trip.get("consignor_name") or trip.get("from_location") or "—"
    site_loc, site_contact = _resolve_consignee_site(trip, customer)

    def _party_block(role, body_lines):
        # Left vertical navy rail + body — magazine feel.
        body_cell = [Paragraph(role, styles["LabelE"])] + [Spacer(1, 2)] + body_lines
        t = Table([[Table([["", body_cell]], colWidths=[3 * mm, 183 * mm])]], colWidths=[190 * mm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, 0), _NAVY),  # rail
        ]))
        # Inner
        inner_style = TableStyle([
            ("BACKGROUND", (0, 0), (0, 0), _NAVY),   # left rail
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (1, 0), (1, 0), 10),
            ("RIGHTPADDING", (1, 0), (1, 0), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("BACKGROUND", (1, 0), (1, 0), _BG_SLATE),
            ("BOX", (0, 0), (-1, -1), 0.4, _LINE),
        ])
        inner = Table([["", body_cell]], colWidths=[3 * mm, 183 * mm])
        inner.setStyle(inner_style)
        return inner

    consignor_body = [
        Paragraph(consignor_name, styles["Party"]),
        Paragraph("<font color='#64748B'>Origin loading point</font>", styles["SmallM"]),
    ]
    consignee_body = [
        Paragraph(customer.get("name", "—") or "—", styles["Party"]),
    ]
    if customer.get("address"):
        consignee_body.append(Paragraph(customer["address"], styles["BodyM"]))
    cust_id_bits = []
    if customer.get("gstin"): cust_id_bits.append(f"<b>GSTIN</b> {customer['gstin']}")
    if customer.get("state"): cust_id_bits.append(f"<b>State</b> {customer['state']}")
    if customer.get("pincode"): cust_id_bits.append(f"<b>PIN</b> {customer['pincode']}")
    if cust_id_bits:
        consignee_body.append(Paragraph("   ".join(cust_id_bits), styles["Small"]))
    consignee_body.append(Spacer(1, 2))
    consignee_body.append(Paragraph(f"<b>Ship-To:</b> {site_loc}", styles["Small"]))
    consignee_body.append(Paragraph(f"<b>Site Contact:</b> {site_contact}", styles["Small"]))

    # Wrap in 10mm horizontal margin (since doc has 0 margins)
    def _margined(widget):
        m = Table([[widget]], colWidths=[190 * mm])
        m.setStyle(TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]))
        outer = Table([[m]], colWidths=[210 * mm])
        outer.setStyle(TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ]))
        return outer

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
        Paragraph("<font color='#059669' size='14'>●━━━━━━━━━━━━━━━━━━━━●</font>", styles["Route"]),
        Paragraph(f"<b>{to_txt}</b>", styles["Route"]),
    ], [
        Paragraph("ORIGIN", styles["RouteM"]),
        Paragraph(f"Round Trip · {_fmt(trip.get('round_trip_kms',0))} KM", styles["RouteM"]),
        Paragraph("DESTINATION", styles["RouteM"]),
    ]], colWidths=[60 * mm, 70 * mm, 60 * mm])
    tl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _EMERALD_L),
        ("BOX", (0, 0), (-1, -1), 0.5, _EMERALD),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, 0), 5),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 1),
        ("TOPPADDING", (0, 1), (-1, 1), 0),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 4),
    ]))
    story.append(_margined(tl))
    story.append(Spacer(1, 6))

    # ================== 5. BORDERLESS KV GRID (2-col) ==================
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
    _kv_style = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, _LINE_L),
        ("LINEABOVE", (0, 0), (-1, 0), 0.6, _NAVY),
    ]
    kv_tbl.setStyle(TableStyle(_kv_style))
    story.append(_margined(kv_tbl))
    story.append(Spacer(1, 5))

    # ================== 6. WEIGHTS STRIP (Net Wt highlighted in emerald ring) ==================
    def _wtile(lbl, val, hi=False):
        lbl_style = "LabelE" if hi else "Label"
        val_para = Paragraph(f"<b>{val}</b>", styles["Body"])
        inner = [Paragraph(lbl, styles[lbl_style]), val_para]
        t = Table([[inner]], colWidths=[45 * mm])
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
        _wtile("RT KMs",    _fmt(trip.get("round_trip_kms", 0))),
    ]], colWidths=[47 * mm, 47 * mm, 47 * mm, 47 * mm])
    wstrip.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 2)]))
    story.append(_margined(wstrip))
    story.append(Spacer(1, 6))

    # ================== 7. UNLOADING LOG (Emerald header contrast) ==================
    story.append(_margined(Paragraph("<font color='#047857'><b>UNLOADING VERIFICATION · BY SITE OFFICIALS</b></font>", styles["Small"])))
    story.append(Spacer(1, 3))
    un_headers = [
        Paragraph("<font color='#FFFFFF'><b>Date of<br/>Arrival</b></font>", styles["Small"]),
        Paragraph("<font color='#FFFFFF'><b>Arrival<br/>Time</b></font>", styles["Small"]),
        Paragraph("<font color='#FFFFFF'><b>Unloading<br/>Start</b></font>", styles["Small"]),
        Paragraph("<font color='#FFFFFF'><b>Unloading<br/>End</b></font>", styles["Small"]),
        Paragraph("<font color='#FFFFFF'><b>Date of<br/>Departure</b></font>", styles["Small"]),
        Paragraph("<font color='#FFFFFF'><b>Extra<br/>KM</b></font>", styles["Small"]),
        Paragraph("<font color='#FFFFFF'><b>Shortage /<br/>Excess (MT)</b></font>", styles["Small"]),
        Paragraph("<font color='#FFFFFF'><b>Temp.<br/>(°C)</b></font>", styles["Small"]),
        Paragraph("<font color='#FFFFFF'><b>Seal<br/>Status</b></font>", styles["Small"]),
        Paragraph("<font color='#FFFFFF'><b>Remarks</b></font>", styles["Small"]),
    ]
    col_widths = [18*mm, 15*mm, 18*mm, 18*mm, 20*mm, 14*mm, 22*mm, 14*mm, 16*mm, 35*mm]
    un_tbl = Table([un_headers, [""] * len(un_headers)], colWidths=col_widths)
    un_tbl.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.4, _LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, _LINE_L),
        ("BACKGROUND", (0, 0), (-1, 0), _EMERALD_D),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, 0), 5),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
        ("TOPPADDING", (0, 1), (-1, 1), 14),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 3),
    ]))
    story.append(_margined(un_tbl))
    story.append(Spacer(1, 3))

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
        ("TOPPADDING", (0, 1), (-1, 1), 16),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 3),
    ]))
    story.append(_margined(sig_tbl))
    story.append(Spacer(1, 5))

    # ================== 8. GST DECLARATION (bordered navy card) ==================
    gst_para = Paragraph(
        "<b>Declaration — GST Reverse Charge:</b> As a Goods Transport Agency (GTA) under Notification "
        "No. 5/2017 Central Tax dated 19-Jun-2017 (CBEC · GOI), we are exempt from mandatory GST "
        "registration for this service and GST liability is discharged by the recipient on Reverse "
        "Charge basis under Section 9(3) of the CGST Act, 2017.",
        styles["Small"],
    )
    gst_box = Table([[gst_para]], colWidths=[190 * mm])
    gst_box.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, _NAVY),
        ("BACKGROUND", (0, 0), (-1, -1), _BG_SLATE),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(_margined(gst_box))
    story.append(Spacer(1, 5))

    # ================== 9. FOOTER (signatory + note) ==================
    foot_left = Paragraph(
        "<font color='#64748B' size='7'><b>Note</b> — This is a computer-generated Goods Consignment "
        "Note. It is valid without a manual signature or the Company's seal.<br/>"
        "Terms &amp; Conditions of carriage are on page 2 — overleaf.</font>",
        styles["Small"],
    )
    foot_right = Paragraph(
        f"<b>For {company_name}</b><br/><br/><font color='#64748B'>_______________________________<br/>"
        "Authorised Signatory</font>",
        styles["Body"],
    )
    foot = Table([[foot_left, foot_right]], colWidths=[120 * mm, 70 * mm])
    foot.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LINEABOVE", (0, 0), (-1, 0), 0.6, _EMERALD),
        ("TOPPADDING", (0, 0), (-1, 0), 6),
    ]))
    story.append(_margined(foot))

    # ══════════════════════════════════════════════════════════════════
    # PAGE 2 — Terms & Conditions (single centred column · circle numbers)
    # ══════════════════════════════════════════════════════════════════
    story.append(PageBreak())

    # Mini header band (thinner than page 1)
    mini_hdr = Table([[
        Paragraph(f"<b>{company_name}</b>", styles["HTitle"]),
        Paragraph(
            f"<font color='#94A3B8' size='9'><b>GCN No.</b> {trip.get('lr_number','—')}   ·   "
            f"<b>Date:</b> {trip.get('date','')}</font>",
            styles["HCoBody"],
        ),
    ]], colWidths=[130 * mm, 80 * mm])
    mini_hdr.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _NAVY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (0, 0), 12),
        ("RIGHTPADDING", (0, 0), (0, 0), 6),
        ("LEFTPADDING", (1, 0), (1, 0), 6),
        ("RIGHTPADDING", (1, 0), (1, 0), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LINEBELOW", (0, 0), (-1, 0), 2.4, _EMERALD),
    ]))
    story.append(mini_hdr)
    story.append(Spacer(1, 10))

    story.append(_margined(Paragraph(
        "TERMS &amp; CONDITIONS · TRANSPORT AND SITE UNLOADING PROTOCOL",
        ParagraphStyle(name="TCT", fontName=FB, fontSize=13, leading=15, textColor=_NAVY, alignment=1),
    )))
    story.append(Spacer(1, 3))
    story.append(_margined(Paragraph(
        "<font color='#64748B'><i>These conditions govern carriage under this Goods Consignment Note "
        "and are binding on the consignor, consignee and any authorised representative at the site.</i></font>",
        ParagraphStyle(name="TCS", fontName=F, fontSize=8.5, leading=11, textColor=_MUTED, alignment=1),
    )))
    story.append(Spacer(1, 12))

    # Circle-numbered T&C — a 2-col table [circle, text] per row.
    tc_body_style = ParagraphStyle(name="TCBody", fontName=F, fontSize=8.5, leading=12,
                                    textColor=_NAVY, spaceAfter=4)
    circle_style = ParagraphStyle(name="Circle", fontName=FB, fontSize=10, leading=12,
                                   textColor=_WHITE, alignment=1)
    tc_rows = []
    for i, t in enumerate(LR_TERMS_EN, start=1):
        num_cell = Table([[Paragraph(f"<b>{i}</b>", circle_style)]], colWidths=[8 * mm], rowHeights=[8 * mm])
        num_cell.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), _EMERALD_D),
            ("BOX", (0, 0), (-1, -1), 0.5, _EMERALD_D),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        tc_rows.append([num_cell, Paragraph(t, tc_body_style)])

    tc_tbl = Table(tc_rows, colWidths=[10 * mm, 180 * mm])
    tc_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, _LINE_L),
    ]))
    story.append(_margined(tc_tbl))
    story.append(Spacer(1, 12))

    # Consignee ack — flat single strip, emerald accent bottom
    ack_lines = [
        Paragraph("<font color='#047857'><b>CONSIGNEE ACKNOWLEDGMENT</b></font>", styles["Label"]),
        Spacer(1, 3),
        Paragraph(
            "I / We hereby confirm that the material described on this Goods Consignment Note has been "
            "received in good condition and quantity, all applicable seals were intact, and I / We have "
            "read and agree to the Terms &amp; Conditions above.",
            styles["Body"],
        ),
        Spacer(1, 22),
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
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(_margined(ack_tbl))

    doc.build(story)
    return buf.getvalue()
