"""Iter142 P0 · Vehicle-wise Cost Report — PDF factory.
Pure projection over the authoritative service response. Reads NOTHING
directly from db.expenses / vendor_bills / mechanic_work_orders — only
consumes `cost-summary` and `repair-history` payloads passed in.
"""
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, PageBreak,
)
from ._base import _UNI_FONT, _UNI_FONT_BOLD, _fmt_ind_date, _fmt


def _para(text, style):
    return Paragraph(text if text not in (None, "") else "—", style)


def build_vehicle_cost_pdf(company: dict, vehicle: dict,
                           cost_summary: dict, repair_history: dict,
                           period: dict) -> bytes:
    """period = {"from": <str|None>, "to": <str|None>, "category": <str|None>}"""
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=14*mm, rightMargin=14*mm,
                            topMargin=14*mm, bottomMargin=14*mm)
    ss = getSampleStyleSheet()
    body = ParagraphStyle("b", parent=ss["BodyText"], fontName=_UNI_FONT, fontSize=9, leading=11)
    bold = ParagraphStyle("bb", parent=body, fontName=_UNI_FONT_BOLD)
    small = ParagraphStyle("s", parent=body, fontSize=8, leading=10, textColor=colors.grey)
    h1 = ParagraphStyle("h1", parent=bold, fontSize=16, leading=20)
    h2 = ParagraphStyle("h2", parent=bold, fontSize=11, leading=14)
    right = ParagraphStyle("r", parent=body, alignment=2)
    right_bold = ParagraphStyle("rb", parent=bold, alignment=2)

    story = []
    # ── Header ─────────────────────────────────────────────────────────
    comp_name = (company or {}).get("name") or "Company"
    comp_addr = (company or {}).get("address") or ""
    story.append(Paragraph(comp_name, h1))
    if comp_addr:
        story.append(Paragraph(comp_addr, small))
    story.append(Spacer(1, 6))
    story.append(Paragraph("VEHICLE COST REPORT", h2))
    story.append(Spacer(1, 4))

    is_supplier = (vehicle.get("vehicle_type") or "").lower() == "supplier"
    ident_rows = [
        ["Vehicle", _para(vehicle.get("vehicle_number") or "—", bold)],
        ["Ownership", "Supplier-owned" if is_supplier else "Company-owned"],
    ]
    if is_supplier:
        sup = (vehicle.get("supplier_name") or vehicle.get("supplier_id") or "—")
        if vehicle.get("supplier_mobile"):
            sup = f"{sup} · {vehicle['supplier_mobile']}"
        ident_rows.append(["Supplier", sup])
    else:
        ident_rows.append(["Owner", vehicle.get("owner_name") or "—"])
    if vehicle.get("make_model"):
        ident_rows.append(["Make / Model", vehicle["make_model"]])
    if vehicle.get("capacity_tons"):
        ident_rows.append(["Capacity", f"{vehicle['capacity_tons']} T"])
    p_from = period.get("from") or "All"
    p_to   = period.get("to")   or "All"
    ident_rows.append(["Report Period", f"{p_from} — {p_to}"])
    if period.get("category"):
        ident_rows.append(["Category Filter", period["category"]])
    from datetime import datetime, timezone
    ident_rows.append(["Generated", _fmt_ind_date(datetime.now(timezone.utc).isoformat())])

    t = Table(ident_rows, colWidths=[40*mm, 130*mm])
    t.setStyle(TableStyle([
        ("FONT", (0,0), (-1,-1), _UNI_FONT, 9),
        ("FONT", (0,0), (0,-1), _UNI_FONT_BOLD, 9),
        ("BACKGROUND", (0,0), (0,-1), colors.HexColor("#f4f4f5")),
        ("BOX", (0,0), (-1,-1), 0.4, colors.HexColor("#d4d4d8")),
        ("INNERGRID", (0,0), (-1,-1), 0.3, colors.HexColor("#e4e4e7")),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
        ("RIGHTPADDING", (0,0), (-1,-1), 6),
        ("TOPPADDING", (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
    ]))
    story.append(t)

    # ── Page 2 · Summary ───────────────────────────────────────────────
    story.append(PageBreak())
    story.append(Paragraph("SUMMARY", h2))
    story.append(Spacer(1, 4))

    kpi = [
        ["Total Vehicle Cost", f"₹ {_fmt(cost_summary.get('total_cost', 0))}"],
        ["Repair Cost",         f"₹ {_fmt(cost_summary.get('repair_total', 0))}"],
        ["Operational Expense", f"₹ {_fmt(cost_summary.get('non_trip_total', 0))}"],
        ["Trip-linked Cost",    f"₹ {_fmt(cost_summary.get('trip_linked_total', 0))}"],
    ]
    kt = Table(kpi, colWidths=[85*mm, 85*mm])
    kt.setStyle(TableStyle([
        ("FONT", (0,0), (-1,-1), _UNI_FONT, 10),
        ("FONT", (1,0), (1,-1), _UNI_FONT_BOLD, 11),
        ("ALIGN", (1,0), (1,-1), "RIGHT"),
        ("BACKGROUND", (0,0), (0,-1), colors.HexColor("#fafafa")),
        ("BOX", (0,0), (-1,-1), 0.4, colors.HexColor("#d4d4d8")),
        ("INNERGRID", (0,0), (-1,-1), 0.3, colors.HexColor("#e4e4e7")),
        ("TOPPADDING", (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("LEFTPADDING", (0,0), (-1,-1), 8),
        ("RIGHTPADDING", (0,0), (-1,-1), 8),
    ]))
    story.append(kt)
    story.append(Spacer(1, 10))

    by_cat = cost_summary.get("by_category") or []
    if by_cat:
        story.append(Paragraph("By Category", bold))
        story.append(Spacer(1, 2))
        data = [["Category", "Amount"]] + [[c.get("category") or "—", _para(f"₹ {_fmt(c.get('amount', 0))}", right)] for c in by_cat]
        ct = Table(data, colWidths=[100*mm, 70*mm], repeatRows=1)
        ct.setStyle(_default_table_style())
        story.append(ct)
        story.append(Spacer(1, 8))

    by_mon = cost_summary.get("by_month") or []
    if by_mon:
        story.append(Paragraph("By Month", bold))
        story.append(Spacer(1, 2))
        data = [["Month", "Amount"]] + [[m.get("month") or "—", _para(f"₹ {_fmt(m.get('amount', 0))}", right)] for m in by_mon]
        mt = Table(data, colWidths=[100*mm, 70*mm], repeatRows=1)
        mt.setStyle(_default_table_style())
        story.append(mt)

    # ── Page 3+ · Expense Detail ───────────────────────────────────────
    story.append(PageBreak())
    story.append(Paragraph("EXPENSE DETAIL", h2))
    story.append(Spacer(1, 4))
    rows = cost_summary.get("rows") or []
    head = ["Date", "Category", "Description", "Vendor", "Trip/Repair", "Amount"]
    data = [head]
    for r in rows:
        vendor = r.get("party_name") if r.get("party_type") == "vendor" else "—"
        ref = "repair" if r.get("repair_event_id") else ("trip" if r.get("trip_id") else (r.get("source_type") or ""))
        desc = r.get("narration") or r.get("remarks") or ""
        data.append([
            _fmt_ind_date(r.get("date")),
            r.get("category") or "",
            _para(desc, body),
            _para(vendor or "—", body),
            ref,
            _para(f"₹ {_fmt(r.get('amount', 0))}", right),
        ])
    data.append(["", "", "", "", _para("Total", right_bold),
                 _para(f"₹ {_fmt(cost_summary.get('total_cost', 0))}", right_bold)])
    et = Table(data, colWidths=[22*mm, 22*mm, 55*mm, 30*mm, 20*mm, 28*mm], repeatRows=1)
    et.setStyle(_default_table_style(total_row=True))
    story.append(et)

    events = (repair_history or {}).get("events") or []
    if events:
        story.append(PageBreak())
        story.append(Paragraph("REPAIR DETAIL", h2))
        story.append(Paragraph(
            "Vendor Payable and Mechanic Payable are context columns; only Repair Cost adds to Vehicle Cost.",
            small))
        story.append(Spacer(1, 4))
        rhead = ["Date", "Description", "Workshop", "Vendor Payable", "Mechanic Payable", "Repair Cost", "Status"]
        rdata = [rhead]
        for ev in events:
            rdata.append([
                _fmt_ind_date(ev.get("event_date")),
                _para(ev.get("description") or "—", body),
                _para(ev.get("workshop_name") or "—", body),
                _para(f"₹ {_fmt(ev.get('vendor_payable', 0))}", right),
                _para(f"₹ {_fmt(ev.get('mechanic_payable', 0))}", right),
                _para(f"₹ {_fmt(ev.get('total_repair_cost', 0))}", right),
                (ev.get("status") or "").upper(),
            ])
        rdata.append(["", "", "", "", _para("Total Repair Cost", right_bold),
                      _para(f"₹ {_fmt(repair_history.get('total_repair_cost', 0))}", right_bold), ""])
        rt = Table(rdata, colWidths=[22*mm, 42*mm, 30*mm, 24*mm, 24*mm, 22*mm, 18*mm], repeatRows=1)
        rt.setStyle(_default_table_style(total_row=True))
        story.append(rt)

    doc.build(story)
    return buf.getvalue()


def _default_table_style(total_row: bool = False):
    st = [
        ("FONT", (0,0), (-1,-1), _UNI_FONT, 8.5),
        ("FONT", (0,0), (-1,0), _UNI_FONT_BOLD, 8.5),
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#f4f4f5")),
        ("BOX", (0,0), (-1,-1), 0.4, colors.HexColor("#d4d4d8")),
        ("INNERGRID", (0,0), (-1,-1), 0.25, colors.HexColor("#e4e4e7")),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING", (0,0), (-1,-1), 5),
        ("RIGHTPADDING", (0,0), (-1,-1), 5),
        ("TOPPADDING", (0,0), (-1,-1), 3),
        ("BOTTOMPADDING", (0,0), (-1,-1), 3),
    ]
    if total_row:
        st.append(("BACKGROUND", (0,-1), (-1,-1), colors.HexColor("#fafafa")))
        st.append(("FONT", (0,-1), (-1,-1), _UNI_FONT_BOLD, 9))
    return TableStyle(st)
