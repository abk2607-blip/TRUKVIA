"""Iter100 · Phase 5 — Modern Landscape Tax Invoice PDF.

Complete redesign in Landscape A4 to match the polish of the Supplier
Settlement Statement (iter93). Financial logic is UNCHANGED — all numbers
still come from the invoice document / trip list. Only presentation moved.

Layout (Landscape A4 · 297mm × 210mm · inner 273mm × 190mm):
  1. Header band (canvas): logo + company details on left, big "TAX INVOICE"
     + invoice meta card on right, thin divider.
  2. BILL TO | SHIP TO | INVOICE META three-column band.
  3. Trip line-items table (10 cols):
        # · Date · Vehicle · Cust Ref · Load · Route · Basis · Tons · Rate · Amount
     Sub-rows for Halting / Diesel-from-Customer / Advance / Shortage / Excess.
  4. Right-side totals card (Freight → Halting → Excess → Shortage → Diesel
     → Advance → Subtotal → CGST/SGST or IGST → Gross → RoundOff → FINAL).
  5. Amount in Words + Bank Details block on left.
  6. Terms & Conditions band + Signatory row.
Supports multi-trip consolidated invoices out-of-the-box (trips is a list).
"""
from ._base import (
    _fmt, _num_to_words_inr,
    _UNI_FONT, _UNI_FONT_BOLD,
)
from io import BytesIO
import base64
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, Image, KeepTogether,
)


# -------------------- Freight Basis label resolver --------------------
_FREIGHT_BASIS_LABELS = {
    "per_ton_loading": "Per Ton (Loading)",
    "per_ton_unloading": "Per Ton (Unloading)",
    "per_ton_higher_of": "Per Ton (Higher of)",
    "fixed": "Fixed",
}


def _resolve_freight_basis(t: dict) -> str:
    """Return human-friendly freight basis for the trip.

    Iter100 · Fix — `freight_mode='fixed'` always wins over an
    `applied_freight_method` snapshot (the snapshot may say per_ton_* because
    it's the customer's default, but the trip itself was booked at a fixed
    amount and the freight math ignores the snapshot for fixed trips)."""
    fm = (t.get("freight_mode") or "").strip().lower()
    if fm == "fixed":
        km = t.get("round_trip_kms", 0) or 0
        rkm = t.get("rate_per_km_per_ton", 0) or 0
        return "Round Trip" if km > 0 and rkm > 0 else "Fixed"
    method = (t.get("applied_freight_method") or "").strip().lower()
    if method in _FREIGHT_BASIS_LABELS:
        return _FREIGHT_BASIS_LABELS[method]
    if fm == "per_ton":
        return "Per Ton"
    return "—"


def build_invoice_pdf(company: dict, customer: dict, invoice: dict, trips: list) -> bytes:
    buf = BytesIO()
    PAGE = landscape(A4)                            # 297 × 210 mm
    doc = SimpleDocTemplate(
        buf, pagesize=PAGE,
        leftMargin=10 * mm, rightMargin=10 * mm,
        topMargin=8 * mm, bottomMargin=8 * mm,
        title=f"Invoice {invoice.get('invoice_number','')}",
    )
    inner_w = PAGE[0] - 20 * mm                     # ≈ 277 mm

    styles = getSampleStyleSheet()
    _F, _FB = _UNI_FONT, _UNI_FONT_BOLD

    # -------- Palette --------
    C_INK    = colors.HexColor("#0F172A")
    C_INK2   = colors.HexColor("#334155")
    C_MUTED  = colors.HexColor("#64748B")
    C_LINE   = colors.HexColor("#E2E8F0")
    C_LINE_D = colors.HexColor("#CBD5E1")
    C_HEAD   = colors.HexColor("#0F172A")
    C_HEAD_T = colors.HexColor("#FFFFFF")
    C_ROW_B  = colors.HexColor("#F8FAFC")
    C_SUB_BG = colors.HexColor("#FFF7ED")
    C_SUB_TX = colors.HexColor("#7C2D12")
    C_ACCENT = colors.HexColor("#F59E0B")
    C_ACC_BG = colors.HexColor("#FEF3C7")
    C_META   = colors.HexColor("#F1F5F9")
    C_BILL   = colors.HexColor("#F8FAFC")

    # -------- Styles --------
    styles.add(ParagraphStyle(name="Small",    fontName=_F,  fontSize=8,   leading=11, textColor=C_INK))
    styles.add(ParagraphStyle(name="SmallB",   fontName=_FB, fontSize=8,   leading=11, textColor=C_INK))
    styles.add(ParagraphStyle(name="Tiny",     fontName=_F,  fontSize=7,   leading=9,  textColor=C_MUTED))
    styles.add(ParagraphStyle(name="TinyB",    fontName=_FB, fontSize=7,   leading=9,  textColor=C_MUTED))
    styles.add(ParagraphStyle(name="TitleXL",  fontName=_FB, fontSize=22,  leading=26, textColor=C_INK, alignment=2))
    styles.add(ParagraphStyle(name="TagLine",  fontName=_F,  fontSize=8,   leading=10, textColor=C_MUTED, alignment=2))
    styles.add(ParagraphStyle(name="H2",       fontName=_FB, fontSize=11,  leading=14, textColor=C_INK))
    styles.add(ParagraphStyle(name="Body",     fontName=_F,  fontSize=9,   leading=12, textColor=C_INK))
    styles.add(ParagraphStyle(name="BodyMut",  fontName=_F,  fontSize=9,   leading=12, textColor=C_INK2))
    styles.add(ParagraphStyle(name="BillName", fontName=_FB, fontSize=11,  leading=13, textColor=C_INK))
    styles.add(ParagraphStyle(name="SectLbl",  fontName=_FB, fontSize=7,   leading=9,  textColor=C_MUTED))
    styles.add(ParagraphStyle(name="RowTxt",   fontName=_F,  fontSize=8,   leading=10, textColor=C_INK))
    styles.add(ParagraphStyle(name="RowTxtB",  fontName=_FB, fontSize=8,   leading=10, textColor=C_INK))
    styles.add(ParagraphStyle(name="RowNum",   fontName=_F,  fontSize=8,   leading=10, textColor=C_INK, alignment=1))
    styles.add(ParagraphStyle(name="RowAmt",   fontName=_FB, fontSize=8.5, leading=10, textColor=C_INK, alignment=2))
    styles.add(ParagraphStyle(name="RowRate",  fontName=_FB, fontSize=7.5, leading=9,  textColor=C_INK))
    styles.add(ParagraphStyle(name="TotalBig", fontName=_FB, fontSize=11,  leading=14, textColor=C_INK))
    styles.add(ParagraphStyle(name="Amount",   fontName=_FB, fontSize=9,   leading=11, textColor=C_INK, alignment=2))
    styles.add(ParagraphStyle(name="AmtSub",   fontName=_F,  fontSize=8,   leading=10, textColor=C_SUB_TX, alignment=2))
    styles.add(ParagraphStyle(name="SubLbl",   fontName=_F,  fontSize=8,   leading=10, textColor=C_SUB_TX))

    story = []

    # ================== 1. HEADER — brand + TAX INVOICE ==================
    company_name = company.get("name") or "YOUR COMPANY NAME"
    contact_bits = []
    if company.get("phone"):   contact_bits.append(f"Ph: {company['phone']}")
    if company.get("email"):   contact_bits.append(company["email"])
    contact_line = "  •  ".join(contact_bits)

    company_left = [Paragraph(f"<font size='14'><b>{company_name}</b></font>", styles["Body"])]
    if company.get("address"):
        company_left.append(Paragraph(company["address"], styles["BodyMut"]))
    if contact_line:
        company_left.append(Paragraph(contact_line, styles["BodyMut"]))
    id_bits = []
    if company.get("gstin"): id_bits.append(f"<b>GSTIN</b> {company['gstin']}")
    if company.get("pan"):   id_bits.append(f"<b>PAN</b> {company['pan']}")
    if company.get("state"): id_bits.append(f"<b>State</b> {company['state']}")
    if id_bits:
        company_left.append(Paragraph("   ".join(id_bits), styles["Body"]))

    # Logo (data URL if present)
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
        logo_img = Image(BytesIO(base64.b64decode(logo_data.split(",", 1)[1])), width=18 * mm, height=18 * mm, kind="proportional") if False else logo_img
        left_block = Table([[logo_img, company_left]], colWidths=[22 * mm, 152 * mm])
        left_block.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (0, 0), 4),
        ]))
    else:
        left_block = company_left

    right_block = [
        Paragraph("TAX INVOICE", styles["TitleXL"]),
        Paragraph(
            f"<font color='#64748B'>Reverse Charge:</font> <b>{'YES' if invoice.get('rcm') else 'NO'}</b>",
            styles["TagLine"],
        ),
    ]
    header_tbl = Table([[left_block, right_block]], colWidths=[178 * mm, 99 * mm])
    header_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
        ("LINEBELOW", (0, 0), (-1, 0), 1.0, C_INK),
    ]))
    story.append(header_tbl)
    story.append(Spacer(1, 4))

    # ================== 2. BILL TO · SHIP TO · META ==================
    ship_sites_by_id = {s.get("id"): s for s in (customer.get("ship_sites") or [])}

    def _resolve_ship_to(trip):
        sid = trip.get("ship_site_id") or ""
        s = ship_sites_by_id.get(sid) if sid else None
        if s:
            return {"site_name": s.get("site_name") or "", "address": s.get("address") or "",
                    "gstin": s.get("gstin") or "", "state": s.get("state") or "",
                    "pincode": s.get("pincode") or "", "phone": s.get("phone") or "",
                    "linked": True}
        return {"site_name": trip.get("to_location") or "", "address": "",
                "gstin": "", "state": "", "pincode": "", "phone": "", "linked": False}

    per_trip_ship = [_resolve_ship_to(t) for t in trips]
    _st_keys = {(s["site_name"], s["address"], s["gstin"], s["state"], s["pincode"])
                for s in per_trip_ship} if per_trip_ship else set()
    _ship_mixed = len(_st_keys) > 1
    _common_ship = per_trip_ship[0] if per_trip_ship and not _ship_mixed else None

    bill_lines = [
        Paragraph("BILL TO", styles["SectLbl"]),
        Spacer(1, 2),
        Paragraph(customer.get("name", "") or "—", styles["BillName"]),
    ]
    if customer.get("address"):
        bill_lines.append(Paragraph(customer["address"], styles["BodyMut"]))
    cust_id_bits = []
    if customer.get("gstin"): cust_id_bits.append(f"<b>GSTIN</b> {customer['gstin']}")
    if customer.get("state"): cust_id_bits.append(f"<b>State</b> {customer['state']}")
    if cust_id_bits:
        bill_lines.append(Paragraph("   ".join(cust_id_bits), styles["Body"]))
    if customer.get("phone"):
        bill_lines.append(Paragraph(f"Ph: {customer['phone']}", styles["BodyMut"]))

    ship_lines = [Paragraph("SHIP TO", styles["SectLbl"]), Spacer(1, 2)]
    if _ship_mixed:
        ship_lines.append(Paragraph("<b>Mixed — see per-trip below</b>", styles["BillName"]))
        ship_lines.append(Paragraph("Multiple sites in this invoice. Each Trip row shows its own Ship-To.", styles["BodyMut"]))
    elif _common_ship and (_common_ship["site_name"] or _common_ship["address"]):
        ship_lines.append(Paragraph(_common_ship["site_name"] or "—", styles["BillName"]))
        if _common_ship["address"]:
            ship_lines.append(Paragraph(_common_ship["address"], styles["BodyMut"]))
        _ship_id_bits = []
        if _common_ship["gstin"]:   _ship_id_bits.append(f"<b>GSTIN</b> {_common_ship['gstin']}")
        if _common_ship["state"]:   _ship_id_bits.append(f"<b>State</b> {_common_ship['state']}")
        if _common_ship["pincode"]: _ship_id_bits.append(f"<b>PIN</b> {_common_ship['pincode']}")
        if _ship_id_bits:
            ship_lines.append(Paragraph("   ".join(_ship_id_bits), styles["Body"]))
        if _common_ship["phone"]:
            ship_lines.append(Paragraph(f"Ph: {_common_ship['phone']}", styles["BodyMut"]))
    else:
        ship_lines.append(Paragraph("—", styles["BillName"]))

    meta_rows = [
        [Paragraph("Our Invoice No", styles["SectLbl"]), Paragraph(invoice.get("invoice_number", "—"), styles["SmallB"])],
        [Paragraph("Invoice Date", styles["SectLbl"]), Paragraph(invoice.get("invoice_date", "—"), styles["SmallB"])],
        [Paragraph("HSN/SAC", styles["SectLbl"]), Paragraph(invoice.get("hsn_sac") or company.get("hsn_sac", "996791"), styles["SmallB"])],
        [Paragraph("GST Type", styles["SectLbl"]), Paragraph("CGST+SGST" if invoice.get("gst_type") == "cgst_sgst" else "IGST", styles["SmallB"])],
        [Paragraph("Trips in Invoice", styles["SectLbl"]), Paragraph(str(len(trips)), styles["SmallB"])],
    ]
    meta_tbl = Table(meta_rows, colWidths=[26 * mm, 34 * mm])
    meta_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), C_META),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, C_LINE),
    ]))

    def _card(lines, w):
        t = Table([[lines]], colWidths=[w])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), C_BILL),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        return t

    bill_tbl = _card(bill_lines, 107 * mm)
    ship_tbl = _card(ship_lines, 102 * mm)
    party_tbl = Table([[bill_tbl, ship_tbl, meta_tbl]],
                     colWidths=[107 * mm, 102 * mm, 60 * mm])
    party_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(party_tbl)
    story.append(Spacer(1, 5))

    # ================== 3. TRIP LINE ITEMS (10 cols) ==================
    # #  ·  Date  ·  Vehicle  ·  Cust Ref  ·  Load  ·  Route  ·  Basis  ·  Tons  ·  Rate  ·  Amount
    hdr = [Paragraph(f"<font color='#FFFFFF'><b>{txt}</b></font>", styles["Body"]) for txt in
           ["#", "Date", "Vehicle No", "Cust Ref", "Load", "Route", "Basis", "Tons", "Rate", "Amount (₹)"]]

    rows = [hdr]
    sub_row_indices = []
    for idx, t in enumerate(trips, start=1):
        route = f"{t.get('from_location','')} → {t.get('to_location','')}"
        cust_ref = t.get("customer_reference_number") or ""
        if not cust_ref:
            cust_ref = t.get("customer_invoice_no") or t.get("waybill_no") or ""
        route_parts = [route]
        if _ship_mixed:
            _st = per_trip_ship[idx - 1]
            _site_str = _st["site_name"] or "—"
            if _st["address"]:
                _site_str = f"{_site_str} · {_st['address']}"
            route_parts.append(f"<font size='6.5' color='#64748B'><b>Ship-To:</b> {_site_str}</font>")
        route_html = "<br/>".join(route_parts)

        basis_label = _resolve_freight_basis(t)
        qty_used = t.get("freight_qty_used") or 0
        basis_html = basis_label
        if qty_used and qty_used > 0:
            basis_html = f"{basis_label}<br/><font size='6.5' color='#64748B'>Qty {_fmt(qty_used)} MT</font>"

        if (t.get("freight_mode") or "").lower() == "per_ton":
            rate_html = f"₹ {_fmt(t.get('rate_per_ton', 0))} / MT"
        else:
            km = t.get("round_trip_kms", 0) or 0
            rkm = t.get("rate_per_km_per_ton", 0) or 0
            if km > 0 and rkm > 0:
                rate_html = f"{_fmt(km)} km × ₹ {_fmt(rkm)}"
            else:
                rate_html = f"₹ {_fmt(t.get('fixed_amount', 0))}"

        rows.append([
            Paragraph(str(idx), styles["RowNum"]),
            Paragraph(t.get("date", ""), styles["RowNum"]),
            Paragraph(t.get("vehicle_number", "") or "—", styles["RowTxtB"]),
            Paragraph(cust_ref or "—", styles["RowTxt"]),
            Paragraph(t.get("load_details", "") or "—", styles["RowTxt"]),
            Paragraph(route_html, styles["RowTxt"]),
            Paragraph(basis_html, styles["RowTxt"]),
            Paragraph(_fmt(t.get("tons", 0)), styles["RowNum"]),
            Paragraph(rate_html, styles["RowRate"]),
            Paragraph(f"₹ {_fmt(t.get('freight_amount', 0))}", styles["RowAmt"]),
        ])

        # ---- Sub-rows (Halting / Diesel / Advance / Shortage / Excess) ----
        def _add_sub(label, amt_str, remark=""):
            if remark:
                from xml.sax.saxutils import escape as _xesc
                lbl = Paragraph(
                    f"↳ {label}<br/><font color='#94A3B8' size='6.5'><i>{_xesc(remark)}</i></font>",
                    styles["SubLbl"])
            else:
                lbl = Paragraph(f"↳ {label}", styles["SubLbl"])
            rows.append(["", lbl, "", "", "", "", "", "", "", Paragraph(amt_str, styles["AmtSub"])])
            sub_row_indices.append(len(rows) - 1)

        if float(t.get("halting_amount", 0) or 0) > 0:
            hdays = t.get("chargeable_halting_days", 0) or 0
            hrate = t.get("halting_rate_per_day", 0) or 0
            _add_sub(
                f"Halting — {hdays} day(s) × ₹ {_fmt(hrate)} / day",
                f"₹ {_fmt(t.get('halting_amount', 0))}",
                remark=t.get("halting_remarks", "") or "",
            )

        receipts = t.get("customer_receipts") or []
        if receipts:
            for r in receipts:
                rtype = (r.get("type") or "").lower()
                amt = float(r.get("amount") or 0)
                if amt <= 0:
                    continue
                rem = r.get("remarks") or ""
                if rtype == "diesel":
                    q = r.get("litres") or r.get("quantity") or 0
                    rt = r.get("rate") or 0
                    lbl = (f"Less: Diesel from Customer — {_fmt(q)} L × ₹ {_fmt(rt)} / L"
                           if q and rt else "Less: Diesel from Customer")
                    _add_sub(lbl, f"(₹ {_fmt(amt)})", remark=rem)
                elif rtype == "advance":
                    mode = r.get("mode") or ""
                    refno = r.get("ref_no") or ""
                    extra = " · ".join([x for x in [mode, refno] if x])
                    lbl = f"Less: Customer Advance{(' — ' + extra) if extra else ''}"
                    _add_sub(lbl, f"(₹ {_fmt(amt)})", remark=rem)
        else:
            diesel_amt = float((t.get("expenses") or {}).get("diesel_from_customer_amount", 0) or 0)
            if diesel_amt > 0:
                dq = (t.get("expenses") or {}).get("diesel_from_customer_qty", 0) or 0
                dr = (t.get("expenses") or {}).get("diesel_from_customer_rate", 0) or 0
                lbl = (f"Less: Diesel from Customer — {_fmt(dq)} L × ₹ {_fmt(dr)} / L"
                       if dq and dr else "Less: Diesel from Customer")
                _add_sub(lbl, f"(₹ {_fmt(diesel_amt)})")
            adv_amt = float((t.get("expenses") or {}).get("cash_advance_received", 0) or 0)
            if adv_amt > 0:
                _add_sub("Less: Customer Advance Received", f"(₹ {_fmt(adv_amt)})")

        shortage_qty = float(t.get("shortage_qty", 0) or 0)
        expenses = t.get("expenses") or {}
        expense_shortage_amt = float(expenses.get("shortage_amount", 0) or 0)
        trip_shortage_amt = float(t.get("shortage_amount", 0) or 0)
        total_shortage_amt = round(trip_shortage_amt + expense_shortage_amt, 2)
        if total_shortage_amt > 0:
            prod_rate = t.get("product_rate_per_mt", 0) or 0
            # Iter101 · Invoice sign-off — reconcile the sub-row math with the
            # NET deductible MT (what services._compute_trip actually charged),
            # NOT the raw shortage_qty. This mirrors the Trip UI's Net Shortage
            # chain so the printed amount = printed MT × printed Rate exactly.
            deductible_mt = round(total_shortage_amt / prod_rate, 3) if prod_rate > 0 else shortage_qty
            # Inline policy note so the customer understands WHY only net is charged.
            policy_note = ""
            lim = float(t.get("applied_customer_shortage_limit") or 0)
            lim_type = (t.get("applied_customer_shortage_limit_type") or "").lower()
            method = (t.get("applied_customer_shortage_method") or "").lower()
            if lim > 0 and lim_type in ("pct", "kg") and method in ("net_shortage", "full_after_limit"):
                loaded = float(t.get("tons") or 0)
                allowed_mt = (lim / 1000.0) if lim_type == "kg" else (loaded * lim / 100.0)
                allow_txt = f"{lim} KG" if lim_type == "kg" else f"{lim}% of Loading"
                if method == "full_after_limit":
                    policy_note = f" <font color='#94A3B8' size='6.5'>Full Actual after {allow_txt} limit ({allowed_mt:.3f} MT) exceeded</font>"
                else:
                    policy_note = f" <font color='#94A3B8' size='6.5'>Net — Actual {shortage_qty:.3f} MT less {allow_txt} allowance ({allowed_mt:.3f} MT)</font>"
            if deductible_mt > 0 and prod_rate > 0:
                lbl = f"Less: Shortage — {deductible_mt:.3f} MT × ₹ {_fmt(prod_rate)} / MT{policy_note}"
            elif shortage_qty > 0:
                lbl = f"Less: Shortage — {shortage_qty:.3f} MT{policy_note}"
            else:
                lbl = "Less: Shortage Deduction"
            _add_sub(lbl, f"(₹ {_fmt(total_shortage_amt)})", remark=t.get("shortage_remarks", "") or "")

        excess_amt = float(t.get("excess_amount", 0) or 0)
        if excess_amt > 0:
            excess_qty = float(t.get("excess_qty", 0) or 0)
            prod_rate = t.get("product_rate_per_mt", 0) or 0
            if excess_qty > 0 and prod_rate > 0:
                lbl = f"Add: Excess — {excess_qty:.3f} MT × ₹ {_fmt(prod_rate)} / MT"
            else:
                lbl = "Add: Excess"
            _add_sub(lbl, f"₹ {_fmt(excess_amt)}", remark=t.get("excess_remarks", "") or "")

    # Column widths (total ~273mm landscape inner width)
    #             #    Date   Veh    Cust   Load   Route  Basis  Tons   Rate   Amt
    col_widths = [8*mm, 22*mm, 26*mm, 30*mm, 32*mm, 48*mm, 34*mm, 15*mm, 26*mm, 36*mm]
    items_tbl = Table(rows, colWidths=col_widths, repeatRows=1)
    _style = [
        ("BACKGROUND", (0, 0), (-1, 0), C_HEAD),
        ("TEXTCOLOR",  (0, 0), (-1, 0), C_HEAD_T),
        ("TOPPADDING",    (0, 0), (-1, 0), 5),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 4),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
        ("TOPPADDING",    (0, 1), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, C_LINE),
        ("LINEABOVE", (0, 0), (-1, 0), 0.4, C_LINE),
        ("BOX",       (0, 0), (-1, -1), 0.6, C_LINE_D),
        ("ALIGN", (0, 1), (0, -1), "CENTER"),   # #
        ("ALIGN", (1, 1), (1, -1), "CENTER"),   # Date
        ("ALIGN", (7, 1), (7, -1), "CENTER"),   # Tons
        ("ALIGN", (9, 1), (9, -1), "RIGHT"),    # Amount
    ]
    for r in range(1, len(rows)):
        if r in sub_row_indices:
            continue
        if (r % 2) == 0:
            _style.append(("BACKGROUND", (0, r), (-1, r), C_ROW_B))
    for r in sub_row_indices:
        _style.append(("SPAN", (1, r), (8, r)))
        _style.append(("BACKGROUND", (0, r), (-1, r), C_SUB_BG))
        _style.append(("TEXTCOLOR", (0, r), (-1, r), C_SUB_TX))
        _style.append(("TOPPADDING", (0, r), (-1, r), 3))
        _style.append(("BOTTOMPADDING", (0, r), (-1, r), 3))
    items_tbl.setStyle(TableStyle(_style))
    story.append(items_tbl)
    story.append(Spacer(1, 5))

    # ================== 4. TOTALS + BANK block ==================
    freight_total = invoice.get("freight_total") or round(sum(float(t.get("freight_amount", 0)) for t in trips), 2)
    halting_total = invoice.get("halting_total") or round(sum(float(t.get("halting_amount", 0)) for t in trips), 2)
    excess_total = invoice.get("excess_total") or round(sum(float(t.get("excess_amount", 0)) for t in trips), 2)
    shortage_total = invoice.get("shortage_total") or round(
        sum(float(t.get("shortage_amount", 0)) + float((t.get("expenses") or {}).get("shortage_amount", 0)) for t in trips), 2,
    )
    diesel_total = invoice.get("diesel_deduction_total") or round(
        sum((sum(float(r.get("amount") or 0) for r in (t.get("customer_receipts") or []) if (r.get("type") or "").lower() == "diesel")
             if (t.get("customer_receipts") or []) else float((t.get("expenses") or {}).get("diesel_from_customer_amount", 0)))
            for t in trips), 2)
    advance_total = invoice.get("advance_deduction_total") or round(
        sum((sum(float(r.get("amount") or 0) for r in (t.get("customer_receipts") or []) if (r.get("type") or "").lower() == "advance")
             if (t.get("customer_receipts") or []) else float((t.get("expenses") or {}).get("cash_advance_received", 0)))
            for t in trips), 2)
    subtotal = invoice.get("subtotal", 0)
    gst_type = invoice.get("gst_type", "cgst_sgst")
    cgst = invoice.get("cgst_amount", 0)
    sgst = invoice.get("sgst_amount", 0)
    igst = invoice.get("igst_amount", 0)
    gross_total = invoice.get("gross_total", invoice.get("total_amount", 0))
    round_off = invoice.get("round_off", 0)
    total = invoice.get("total_amount", 0)
    paid = invoice.get("amount_paid", 0)
    balance = invoice.get("balance_due", 0)

    def _tr(label, val, *, bold=False, muted=False, big=False):
        style = styles["Body"] if not bold else styles["SmallB"]
        val_style = styles["Amount"] if not muted else styles["AmtSub"]
        if big:
            style = styles["TotalBig"]
            val_style = styles["TotalBig"]
        return [Paragraph(label, style), Paragraph(val, val_style)]

    tot_rows = [_tr("Freight Amount", f"₹ {_fmt(freight_total)}")]
    if halting_total > 0:
        tot_rows.append(_tr("Halting Charges", f"₹ {_fmt(halting_total)}"))
    if excess_total > 0:
        tot_rows.append(_tr("Excess Quantity", f"₹ {_fmt(excess_total)}"))
    if shortage_total > 0:
        tot_rows.append(_tr("Less: Shortage Deduction", f"(₹ {_fmt(shortage_total)})", muted=True))
    if diesel_total > 0:
        tot_rows.append(_tr("Less: Diesel from Customer", f"(₹ {_fmt(diesel_total)})", muted=True))
    if advance_total > 0:
        tot_rows.append(_tr("Less: Customer Advance", f"(₹ {_fmt(advance_total)})", muted=True))
    tot_rows.append(_tr("Net Freight (Taxable)", f"₹ {_fmt(subtotal)}", bold=True))
    if gst_type == "cgst_sgst":
        tot_rows.append(_tr("CGST @ 2.5%", f"₹ {_fmt(cgst)}"))
        tot_rows.append(_tr("SGST @ 2.5%", f"₹ {_fmt(sgst)}"))
    else:
        tot_rows.append(_tr("IGST @ 5%", f"₹ {_fmt(igst)}"))
    if invoice.get("rcm"):
        tot_rows.append(_tr("Tax under RCM (not collected)", "—"))
    else:
        tot_rows.append(_tr("Total Tax", f"₹ {_fmt(invoice.get('total_tax', 0))}"))
    tot_rows.append(_tr("Gross Total", f"₹ {_fmt(gross_total)}"))
    if abs(round_off) >= 0.005:
        sign = "+" if round_off > 0 else "−"
        tot_rows.append(_tr("Round Off", f"{sign} ₹ {_fmt(abs(round_off))}", muted=True))
    tot_rows.append(_tr("FINAL PAYABLE", f"₹ {_fmt(total)}", big=True))
    tot_rows.append(_tr("Amount Received", f"₹ {_fmt(paid)}", muted=True))
    tot_rows.append(_tr("Balance Due", f"₹ {_fmt(balance)}", bold=True))

    totals_tbl = Table(tot_rows, colWidths=[52 * mm, 48 * mm])
    _tot_style = [
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, C_LINE),
        ("BOX", (0, 0), (-1, -1), 0.8, C_LINE_D),
    ]
    final_idx = len(tot_rows) - 3
    _tot_style.append(("BACKGROUND", (0, final_idx), (-1, final_idx), C_ACC_BG))
    _tot_style.append(("LINEABOVE", (0, final_idx), (-1, final_idx), 1.2, C_ACCENT))
    _tot_style.append(("LINEBELOW", (0, final_idx), (-1, final_idx), 1.2, C_ACCENT))
    _tot_style.append(("TOPPADDING", (0, final_idx), (-1, final_idx), 5))
    _tot_style.append(("BOTTOMPADDING", (0, final_idx), (-1, final_idx), 5))
    totals_tbl.setStyle(TableStyle(_tot_style))

    words = _num_to_words_inr(total)
    bank_lines = [
        Paragraph("AMOUNT IN WORDS", styles["SectLbl"]),
        Paragraph(f"<b>{words}</b>", styles["Body"]),
        Spacer(1, 4),
        Paragraph("BANK DETAILS (RTGS / NEFT)", styles["SectLbl"]),
        Paragraph(f"<b>Bank:</b> {company.get('bank_name','—')}<br/>"
                  f"<b>A/c No:</b> {company.get('account_number','—')}<br/>"
                  f"<b>IFSC:</b> {company.get('ifsc','—')}   <b>Branch:</b> {company.get('branch','—')}",
                  styles["Small"]),
    ]
    left_bank_tbl = Table([[bank_lines]], colWidths=[167 * mm])
    left_bank_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), C_BILL),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.6, C_LINE_D),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))

    bottom_tbl = Table([[left_bank_tbl, totals_tbl]], colWidths=[167 * mm, 110 * mm])
    bottom_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(bottom_tbl)
    story.append(Spacer(1, 5))

    # ================== 5. TERMS & CONDITIONS ==================
    terms = [
        ("GST shall be paid by the service recipient under the Reverse Charge Mechanism as per Notification No. 08/2017 (if RCM = YES)."
         if invoice.get("rcm") else "GST is charged under forward charge and included in the total payable."),
        "Shortage or excess in quantity will be accounted for only beyond a permissible variation of 0.5% for Bitumen, Emulsion, and Other Products, and 1% for CRMB / PMB.",
        "Halting Charges applicable after 48 hours from arrival at the site.",
        "Responsibility for product insurance lies with the consignor or consignee, as applicable.",
    ]
    udyam = (company.get("udyam_registration") or "").strip()
    if udyam:
        from xml.sax.saxutils import escape as _xml_escape
        terms.append(f"MSME / Udyam Registration No: {_xml_escape(udyam)}")
    if invoice.get("notes"):
        from xml.sax.saxutils import escape as _xml_escape
        terms.append(f"Notes: {_xml_escape(invoice.get('notes'))}")

    terms_html = "<br/>".join([f"<b>{i}.</b> {t}" for i, t in enumerate(terms, start=1)])
    tc_tbl = Table([
        [Paragraph("TERMS &amp; CONDITIONS", styles["SectLbl"])],
        [Paragraph(terms_html, styles["Small"])],
    ], colWidths=[277 * mm])
    tc_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFFBEB")),
        ("BOX", (0, 0), (-1, -1), 0.6, C_ACCENT),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (0, 0), 5),
        ("BOTTOMPADDING", (0, 0), (0, 0), 2),
        ("TOPPADDING", (0, 1), (0, 1), 2),
        ("BOTTOMPADDING", (0, 1), (0, 1), 5),
    ]))

    # ================== 6. SIGNATURE ==================
    sig_tbl = Table(
        [[Paragraph("<font color='#94A3B8'>Received in good condition</font>", styles["Small"]),
          Paragraph(f"<b>For {company_name}</b>", styles["SmallB"])],
         [Paragraph("<font color='#94A3B8'>Customer Signature &amp; Stamp</font>", styles["Tiny"]),
          Paragraph("Authorised Signatory", styles["Tiny"])]],
        colWidths=[165 * mm, 112 * mm],
    )
    sig_tbl.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("LINEABOVE", (0, 1), (0, 1), 0.4, C_LINE_D),
        ("LINEABOVE", (1, 1), (1, 1), 0.4, C_LINE_D),
    ]))
    story.append(KeepTogether([tc_tbl, Spacer(1, 10), sig_tbl]))

    doc.build(story)
    return buf.getvalue()
