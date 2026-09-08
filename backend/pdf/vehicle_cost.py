"""Iter142 P0 · Vehicle-wise Cost Report — PDF factory.
Landscape A4. Uses ACTIVE COMPANY logo (never product/TRUKVIA logo).
Short reports fit on ONE page; medium/large flow automatically without
truncation. Pure projection over the authoritative service payloads.
"""
from io import BytesIO
from datetime import datetime, timezone
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, KeepTogether,
)
from ._base import _UNI_FONT, _UNI_FONT_BOLD, _fmt_ind_date, _fmt
# Reuse the exact company-logo helper + page-footer canvas from the
# existing branded PDFs (Iter133 L2 · Customer Ledger). Same helper, same
# aspect-ratio preservation, same base64→Image pipeline.
from .ledger import _logo_flowable, NumberedCanvas

INK    = colors.HexColor("#111827")
MUTED  = colors.HexColor("#6B7280")
BORDER = colors.HexColor("#D1D5DB")
STRIPE = colors.HexColor("#FAFAFA")
HEAD   = colors.HexColor("#F4F4F5")


def _para(text, style):
    return Paragraph(text if text not in (None, "") else "—", style)


def build_vehicle_cost_pdf(company: dict, vehicle: dict,
                           cost_summary: dict, repair_history: dict,
                           period: dict) -> bytes:
    """Landscape A4. period = {"from": str|None, "to": str|None, "category": str|None}."""
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=10*mm, rightMargin=10*mm,
        topMargin=8*mm, bottomMargin=14*mm,
        title=f"Vehicle Cost Report — {vehicle.get('vehicle_number') or ''}",
    )
    ss = getSampleStyleSheet()
    body   = ParagraphStyle("b",  parent=ss["BodyText"], fontName=_UNI_FONT, fontSize=8.5, leading=10.5, textColor=INK)
    small  = ParagraphStyle("s",  parent=body, fontSize=7.5, leading=9.2, textColor=MUTED)
    bold   = ParagraphStyle("bb", parent=body, fontName=_UNI_FONT_BOLD)
    right  = ParagraphStyle("r",  parent=body, alignment=2)
    rboldy = ParagraphStyle("rb", parent=bold, alignment=2)
    h1     = ParagraphStyle("h1", parent=bold, fontSize=13, leading=15)
    h2     = ParagraphStyle("h2", parent=bold, fontSize=9.5, leading=11.5)
    kpi_l  = ParagraphStyle("kl", parent=small, fontSize=7, leading=8, textColor=MUTED)
    kpi_v  = ParagraphStyle("kv", parent=bold, fontSize=13, leading=15)

    story = []

    # ── HEADER · Active company logo + company identity + title ─────────
    comp_name = (company or {}).get("name") or "Company"
    comp_addr = (company or {}).get("address") or ""
    comp_gst  = (company or {}).get("gstin") or ""
    ident = f"<b>{comp_name}</b>"
    lines2 = [x for x in (comp_addr, comp_gst) if x]
    header_left = [_logo_flowable(company, target_h_mm=15)]
    header_mid  = [Paragraph(ident, h1)]
    for ln in lines2:
        header_mid.append(Paragraph(ln, small))
    header_right = [
        Paragraph("VEHICLE COST REPORT", h2),
        Paragraph(f"Generated: {_fmt_ind_date(datetime.now(timezone.utc).isoformat())}", small),
    ]
    hdr = Table([[header_left, header_mid, header_right]],
                colWidths=[42*mm, 175*mm, 60*mm])
    hdr.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("ALIGN", (2,0), (2,0), "RIGHT"),
        ("LEFTPADDING", (0,0), (-1,-1), 0),
        ("RIGHTPADDING", (0,0), (-1,-1), 0),
        ("TOPPADDING", (0,0), (-1,-1), 0),
        ("BOTTOMPADDING", (0,0), (-1,-1), 0),
    ]))
    story.append(hdr)
    story.append(Spacer(1, 4))
    story.append(Table([[""]], colWidths=[277*mm], style=[
        ("LINEABOVE", (0,0), (-1,0), 0.6, INK),
    ]))
    story.append(Spacer(1, 4))

    # ── VEHICLE IDENTITY + PERIOD ROW ────────────────────────────────────
    is_supplier = (vehicle.get("vehicle_type") or "").lower() == "supplier"
    owner_or_sup = ("Supplier: " + (vehicle.get("supplier_name") or "—")) if is_supplier \
                   else ("Owner: " + (vehicle.get("owner_name") or "—"))
    if is_supplier and vehicle.get("supplier_mobile"):
        owner_or_sup += f" · {vehicle['supplier_mobile']}"
    make = vehicle.get("make_model") or ""
    cap  = f"{vehicle['capacity_tons']} T" if vehicle.get("capacity_tons") else ""
    p_from = period.get("from") or "All"
    p_to   = period.get("to")   or "All"
    cat_f  = period.get("category") or "All"
    ident_grid = [[
        _para(f"<b>Vehicle:</b> {vehicle.get('vehicle_number') or '—'}", body),
        _para(f"<b>Ownership:</b> {'Supplier-owned' if is_supplier else 'Company-owned'}", body),
        _para(f"<b>{owner_or_sup}</b>", body),
        _para(f"<b>Make/Model:</b> {make or '—'}   <b>Cap:</b> {cap or '—'}", body),
        _para(f"<b>Period:</b> {p_from} → {p_to}   <b>Category:</b> {cat_f}", body),
    ]]
    ig = Table(ident_grid, colWidths=[52*mm, 46*mm, 60*mm, 55*mm, 64*mm])
    ig.setStyle(TableStyle([
        ("BOX", (0,0), (-1,-1), 0.4, BORDER),
        ("INNERGRID", (0,0), (-1,-1), 0.3, BORDER),
        ("BACKGROUND", (0,0), (-1,-1), HEAD),
        ("FONT", (0,0), (-1,-1), _UNI_FONT, 8.5),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
        ("RIGHTPADDING", (0,0), (-1,-1), 6),
        ("TOPPADDING", (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
    ]))
    story.append(ig)
    story.append(Spacer(1, 5))

    # ── KPI BAND · single row of 4 tiles ─────────────────────────────────
    def _kpi(label, val):
        return Table([[Paragraph(label, kpi_l)], [Paragraph(f"₹ {_fmt(val)}", kpi_v)]],
                     colWidths=[65*mm], rowHeights=[6*mm, 10*mm], style=[
            ("BOX", (0,0), (-1,-1), 0.4, BORDER),
            ("BACKGROUND", (0,0), (-1,-1), colors.white),
            ("LEFTPADDING", (0,0), (-1,-1), 6),
            ("RIGHTPADDING", (0,0), (-1,-1), 6),
            ("TOPPADDING", (0,0), (0,0), 3),
            ("TOPPADDING", (0,1), (0,1), 0),
            ("BOTTOMPADDING", (0,0), (-1,-1), 0),
        ])
    kt = Table([[
        _kpi("Total Vehicle Cost",  cost_summary.get("total_cost", 0)),
        _kpi("Repair Cost",         cost_summary.get("repair_total", 0)),
        _kpi("Operational Expense", cost_summary.get("non_trip_total", 0)),
        _kpi("Trip-linked Cost",    cost_summary.get("trip_linked_total", 0)),
    ]], colWidths=[68*mm]*4)
    kt.setStyle(TableStyle([("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),3),
                            ("TOPPADDING",(0,0),(-1,-1),0),("BOTTOMPADDING",(0,0),(-1,-1),0)]))
    story.append(kt)
    story.append(Spacer(1, 6))

    # ── CATEGORY + MONTH · side-by-side ──────────────────────────────────
    by_cat = cost_summary.get("by_category") or []
    by_mon = cost_summary.get("by_month") or []
    def _summary_table(header_label, items, key):
        data = [[header_label, "Amount"]] + [
            [it.get(key) or "—", _para(f"₹ {_fmt(it.get('amount',0))}", right)] for it in items
        ]
        if not items:
            data.append(["—", "—"])
        t = Table(data, colWidths=[75*mm, 55*mm], repeatRows=1)
        t.setStyle(_tbl_style())
        return t
    dual = Table([[_summary_table("Category", by_cat, "category"),
                   _summary_table("Month",    by_mon, "month")]],
                 colWidths=[135*mm, 135*mm])
    dual.setStyle(TableStyle([("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),5),
                              ("VALIGN",(0,0),(-1,-1),"TOP")]))
    story.append(KeepTogether(dual))
    story.append(Spacer(1, 6))

    # ── EXPENSE DETAIL · flows naturally to page 2+ when tall ────────────
    story.append(Paragraph("EXPENSE DETAIL", h2))
    story.append(Spacer(1, 2))
    rows = cost_summary.get("rows") or []
    head = ["Date", "Category", "Description", "Vendor", "Ref", "Amount"]
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
    data.append(["", "", "", "", _para("Total", rboldy),
                 _para(f"₹ {_fmt(cost_summary.get('total_cost', 0))}", rboldy)])
    et = Table(data,
               colWidths=[24*mm, 26*mm, 100*mm, 60*mm, 22*mm, 45*mm],
               repeatRows=1)
    et.setStyle(_tbl_style(total_row=True, striped=True))
    story.append(et)

    # ── REPAIR DETAIL (optional) ─────────────────────────────────────────
    events = (repair_history or {}).get("events") or []
    if events:
        story.append(Spacer(1, 6))
        story.append(Paragraph("REPAIR DETAIL", h2))
        story.append(Paragraph(
            "Vendor Payable and Mechanic Payable are context columns only. Repair Cost = Σ canonical Expense.amount.",
            small))
        story.append(Spacer(1, 2))
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
        rdata.append(["", "", "", "", _para("Total Repair Cost", rboldy),
                      _para(f"₹ {_fmt(repair_history.get('total_repair_cost', 0))}", rboldy), ""])
        rt = Table(rdata,
                   colWidths=[24*mm, 72*mm, 55*mm, 33*mm, 33*mm, 30*mm, 30*mm],
                   repeatRows=1)
        rt.setStyle(_tbl_style(total_row=True, striped=True))
        story.append(rt)

    doc.build(story, canvasmaker=NumberedCanvas)
    return buf.getvalue()


def _tbl_style(total_row: bool = False, striped: bool = False) -> TableStyle:
    st = [
        ("FONT", (0,0), (-1,-1), _UNI_FONT, 8),
        ("FONT", (0,0), (-1,0), _UNI_FONT_BOLD, 8),
        ("BACKGROUND", (0,0), (-1,0), HEAD),
        ("TEXTCOLOR", (0,0), (-1,-1), INK),
        ("BOX", (0,0), (-1,-1), 0.4, BORDER),
        ("INNERGRID", (0,0), (-1,-1), 0.25, BORDER),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING", (0,0), (-1,-1), 5),
        ("RIGHTPADDING", (0,0), (-1,-1), 5),
        ("TOPPADDING", (0,0), (-1,-1), 2.5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 2.5),
    ]
    if striped:
        st.append(("ROWBACKGROUNDS", (0,1), (-1,-2 if total_row else -1),
                   [colors.white, STRIPE]))
    if total_row:
        st.append(("BACKGROUND", (0,-1), (-1,-1), HEAD))
        st.append(("FONT", (0,-1), (-1,-1), _UNI_FONT_BOLD, 8.5))
    return TableStyle(st)
