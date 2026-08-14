from ._base import (
    _fmt, _num_to_words_inr, LR_TERMS_EN,
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

def _resolve_consignee_site(trip: dict, customer: dict) -> tuple[str, str]:
    """Iter73 — Resolve LR consignee site location + contact.

    Priority (never overwrites what the user manually saved on the trip):
      1. Explicit `consignee_site_location` value on the trip (already-saved manual override)
      2. Selected Ship-To site on the trip → its site_name + address; contact person → site contact
      3. Fallback → trip.to_location

    Returns (site_location, site_contact).
    """
    manual_loc = (trip.get("consignee_site_location") or "").strip()
    manual_ct = (trip.get("consignee_site_contact") or "").strip()
    ship_site_id = (trip.get("ship_site_id") or "").strip()

    # Manual override wins — respect historical / user-entered data.
    if manual_loc:
        return manual_loc, manual_ct or "—"

    # Ship-To selected → use its site name + address
    if ship_site_id and isinstance(customer.get("ship_sites"), list):
        site = next((s for s in customer["ship_sites"] if s.get("id") == ship_site_id), None)
        if site:
            name = (site.get("site_name") or "").strip()
            addr = (site.get("address") or "").strip()
            loc = " · ".join(x for x in [name, addr] if x)
            contact_bits = [
                (site.get("contact_person") or "").strip(),
                (site.get("phone") or "").strip(),
            ]
            contact = " · ".join(x for x in contact_bits if x)
            return (loc or (trip.get("to_location") or "—")), (manual_ct or contact or "—")

    # Fallback — Trip Details "TO"
    return (trip.get("to_location") or "—"), (manual_ct or "—")


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

    title_para = Paragraph("<b>GOODS CONSIGNMENT NOTE</b><br/><font size='7'>(Lorry Receipt)</font>", styles["LRTitle"])
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
    # Iter73 — Consignee location priority: manual override → Ship-To → to_location
    site_loc, site_contact = _resolve_consignee_site(trip, customer)
    party = [
        [Paragraph("<b>Consignor</b>", styles["LRSmallBold"]),
         Paragraph("<b>Consignee (M/s)</b>", styles["LRSmallBold"])],
        [Paragraph(consignor_name, styles["LRBody"]),
         Paragraph(f"<b>{customer.get('name','')}</b><br/>{customer.get('address','')}<br/>GSTIN: {customer.get('gstin','—')} · Pincode: {customer.get('pincode','—')}", styles["LRBody"])],
        [Paragraph(f"<b>Site Location:</b> {site_loc}", styles["LRSmall"]),
         Paragraph(f"<b>Site Contact:</b> {site_contact}", styles["LRSmall"])],
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
        [Paragraph("<b>Tanker No.</b>", styles["LRSmallBold"]), trip.get("vehicle_number", ""),
         Paragraph("<b>Product</b>", styles["LRSmallBold"]), trip.get("load_details", "")],
        [Paragraph("<b>Purchase Invoice</b>", styles["LRSmallBold"]), trip.get("external_invoice_no", "—"),
         Paragraph("<b>Vehicle Seal No.</b>", styles["LRSmallBold"]), trip.get("seal_numbers", "—")],
        [Paragraph("<b>Customer Invoice</b>", styles["LRSmallBold"]), trip.get("customer_invoice_no", "—"),
         Paragraph("<b>Waybill No.</b>", styles["LRSmallBold"]), trip.get("waybill_no", "—")],
        [Paragraph("<b>Purchased At</b>", styles["LRSmallBold"]), trip.get("customer_purchased_at", "—"),
         Paragraph("<b>Invoice Value</b>", styles["LRSmallBold"]), f"₹ {_fmt(trip.get('invoice_value', 0))}" if trip.get("invoice_value") else "—"],
        [Paragraph("<b>Gross Wt.</b>", styles["LRSmallBold"]), f"{_fmt(trip.get('gross_weight',0))} MT",
         Paragraph("<b>Tare Wt.</b>", styles["LRSmallBold"]), f"{_fmt(trip.get('tare_weight',0))} MT"],
        [Paragraph("<b>Net Wt.</b>", styles["LRSmallBold"]), f"{_fmt(net_wt)} MT",
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

    driver_rows = [[Paragraph("<b>Driver Name</b>", styles["LRSmallBold"]), (trip.get("lr_driver_name") or trip.get("driver_name") or "—"),
                    Paragraph("<b>Driver Mobile</b>", styles["LRSmallBold"]), (trip.get("lr_driver_mobile") or trip.get("driver_mobile") or "—")]]
    driver_tbl = Table(driver_rows, colWidths=[40 * mm, 55 * mm, 40 * mm, 55 * mm])
    driver_tbl.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, colors.black),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(driver_tbl)

    # From / To route block (freight amounts intentionally omitted from LR)
    route_rows = [[
        Paragraph("<b>From</b>", styles["LRSmallBold"]),
        trip.get("from_location", "—") + (f" ({trip.get('from_pincode')})" if trip.get("from_pincode") else ""),
        Paragraph("<b>To</b>", styles["LRSmallBold"]),
        trip.get("to_location", "—") + (f" ({trip.get('to_pincode')})" if trip.get("to_pincode") else ""),
    ]]
    route_tbl = Table(route_rows, colWidths=[40 * mm, 55 * mm, 40 * mm, 55 * mm])
    route_tbl.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, colors.black),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(route_tbl)

    # Unloading Details by Site Officials — column-wise (headers row + empty row to fill)
    story.append(Spacer(1, 4))
    story.append(Paragraph("<b>UNLOADING DETAILS BY SITE OFFICIALS</b>", styles["LRSmallBold"]))
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
        ("BOX", (0, 0), (-1, -1), 0.5, colors.black),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F4F4F5")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 1), (-1, 1), 18), ("BOTTOMPADDING", (0, 1), (-1, 1), 4),
    ]))
    story.append(un_tbl)

    # Site officials signature strip (also column-wise)
    sig_headers = [
        Paragraph("<b>Site Officer Name</b>", styles["LRSmall"]),
        Paragraph("<b>Designation</b>", styles["LRSmall"]),
        Paragraph("<b>Mobile</b>", styles["LRSmall"]),
        Paragraph("<b>Signature &amp; Stamp</b>", styles["LRSmall"]),
        Paragraph("<b>Date &amp; Time</b>", styles["LRSmall"]),
    ]
    sig_tbl = Table([sig_headers, [""] * len(sig_headers)], colWidths=[45*mm, 30*mm, 30*mm, 55*mm, 30*mm])
    sig_tbl.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, colors.black),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F4F4F5")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 1), (-1, 1), 22), ("BOTTOMPADDING", (0, 1), (-1, 1), 4),
    ]))
    story.append(sig_tbl)

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
    story.append(Paragraph(f"For <b>{company_name}</b>&nbsp;&nbsp;&nbsp;·&nbsp;&nbsp;&nbsp;Manager Signature &amp; Stamp", styles["LRSmall"]))
    story.append(Paragraph("<i>This document is computer generated and does not require signature or the Company's Seal.</i>", styles["LRSmall"]))

    # ---------------- Page 2: Terms & Conditions ----------------
    story.append(PageBreak())
    tc_header_left = Paragraph(
        f"<b>{company_name}</b><br/><font size='8'>{company.get('address','')}</font>",
        styles["LRBody"],
    )
    tc_header_right = Paragraph(
        f"<b>LR No.:</b> {trip.get('lr_number','—')}<br/><b>Date:</b> {trip.get('date','')}",
        styles["LRBody"],
    )
    tc_header = Table([[tc_header_left, tc_header_right]], colWidths=[126 * mm, 64 * mm])
    tc_header.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(tc_header)
    story.append(Spacer(1, 8))
    tc_title = Paragraph(
        "<b>TERMS &amp; CONDITIONS · TANKER UNLOADING PROCEDURES AT SITE</b>",
        ParagraphStyle(name="TCTitle", fontName="Helvetica-Bold", fontSize=12, leading=15, alignment=1),
    )
    story.append(tc_title)
    story.append(Spacer(1, 8))
    tc_body_style = ParagraphStyle(name="TCBody", fontName="Helvetica", fontSize=10, leading=14, spaceAfter=4)
    tc_rows = [[Paragraph(f"<b>{i+1}.</b> {t}", tc_body_style)] for i, t in enumerate(LR_TERMS_EN)]
    tc_tbl = Table(tc_rows, colWidths=[190 * mm])
    tc_tbl.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, colors.HexColor("#FAFAFA")]),
    ]))
    story.append(tc_tbl)
    story.append(Spacer(1, 14))
    ack_rows = [
        ["Received the material as described above in good condition and agree to the Terms & Conditions overleaf."],
        [""],
        ["Consignee Signature & Stamp: ______________________________     Date: __________________"],
    ]
    ack_tbl = Table(ack_rows, colWidths=[190 * mm])
    ack_tbl.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, colors.black),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(ack_tbl)

    doc.build(story)
    return buf.getvalue()


