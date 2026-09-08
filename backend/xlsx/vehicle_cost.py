"""Iter142 P0 · Vehicle-wise Cost Report — Excel factory.
5-sheet workbook: Summary · Expenses · Repairs · By Category · By Month.
Pure projection of cost-summary + repair-history payloads.
"""
from io import BytesIO
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

CURRENCY_FMT = '_-₹* #,##0.00_-;-₹* #,##0.00_-;_-₹* "-"??_-;_-@_-'
BOLD = Font(bold=True)
HDR_FILL = PatternFill("solid", fgColor="F4F4F5")


def _hdr(ws, headers, row=1):
    for i, h in enumerate(headers, start=1):
        c = ws.cell(row=row, column=i, value=h)
        c.font = BOLD
        c.fill = HDR_FILL
        c.alignment = Alignment(horizontal="left", vertical="center")
    ws.freeze_panes = ws.cell(row=row + 1, column=1)


def _widths(ws, widths):
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def _group_trip_costs_xlsx(rows: list) -> list:
    """Iter143 P2 · Mirror of pdf.vehicle_cost._group_trip_costs. Zero-cost
    trips are hidden. Never reads Trip.total_expense / VendorBill /
    MechanicWO / supplier payable."""
    groups = {}
    for r in (rows or []):
        tid = r.get("trip_id")
        if not tid or r.get("repair_event_id"):
            continue
        amt = float(r.get("amount") or 0)
        g = groups.setdefault(tid, {"total": 0.0, "categories": {}})
        g["total"] = round(g["total"] + amt, 2)
        c = r.get("category") or "Other"
        g["categories"][c] = round(g["categories"].get(c, 0.0) + amt, 2)
    out = []
    for tid, g in groups.items():
        if g["total"] <= 0:
            continue
        out.append({"trip_id": tid, "total": g["total"],
                    "categories": sorted(g["categories"].items(),
                                         key=lambda kv: (-kv[1], kv[0]))})
    return out


def build_vehicle_cost_xlsx(company: dict, vehicle: dict,
                             cost_summary: dict, repair_history: dict,
                             period: dict, trip_meta_map: dict = None) -> bytes:
    wb = openpyxl.Workbook()

    # 1 · Summary
    ws = wb.active
    ws.title = "Summary"
    is_supplier = (vehicle.get("vehicle_type") or "").lower() == "supplier"
    rows = [
        ("Company",       (company or {}).get("name") or "—"),
        ("Vehicle",       vehicle.get("vehicle_number") or "—"),
        ("Ownership",     "Supplier-owned" if is_supplier else "Company-owned"),
        ("Supplier" if is_supplier else "Owner",
         (vehicle.get("supplier_name") if is_supplier else vehicle.get("owner_name")) or "—"),
        ("Supplier Mobile", vehicle.get("supplier_mobile") or "—") if is_supplier
            else ("Owner Phone", vehicle.get("owner_phone") or "—"),
        ("Make / Model",  vehicle.get("make_model") or "—"),
        ("Capacity (T)",  vehicle.get("capacity_tons") or "—"),
        ("Report From",   period.get("from") or "All"),
        ("Report To",     period.get("to")   or "All"),
        ("Category Filter", period.get("category") or "All"),
        ("", ""),
        ("Total Vehicle Cost", cost_summary.get("total_cost", 0)),
        ("Repair Cost",         cost_summary.get("repair_total", 0)),
        ("Operational Expense", cost_summary.get("non_trip_total", 0)),
        ("Trip-linked Cost",    cost_summary.get("trip_linked_total", 0)),
        ("Expense Count",       cost_summary.get("expense_count", 0)),
    ]
    for i, (k, v) in enumerate(rows, start=1):
        a = ws.cell(row=i, column=1, value=k); a.font = BOLD
        b = ws.cell(row=i, column=2, value=v)
        if isinstance(v, (int, float)) and k not in ("Expense Count", "Capacity (T)"):
            b.number_format = CURRENCY_FMT
    _widths(ws, [26, 40])

    # 2 · Expenses
    ws = wb.create_sheet("Expenses")
    _hdr(ws, ["Date", "Category", "Description", "Vendor", "Trip/Repair", "Amount"])
    r = 2
    for row in (cost_summary.get("rows") or []):
        vendor = row.get("party_name") if row.get("party_type") == "vendor" else ""
        ref = "repair" if row.get("repair_event_id") else ("trip" if row.get("trip_id") else (row.get("source_type") or ""))
        ws.cell(row=r, column=1, value=row.get("date") or "")
        ws.cell(row=r, column=2, value=row.get("category") or "")
        ws.cell(row=r, column=3, value=row.get("narration") or row.get("remarks") or "")
        ws.cell(row=r, column=4, value=vendor or "")
        ws.cell(row=r, column=5, value=ref)
        c = ws.cell(row=r, column=6, value=float(row.get("amount") or 0))
        c.number_format = CURRENCY_FMT
        r += 1
    # total row
    tl = ws.cell(row=r, column=5, value="Total"); tl.font = BOLD
    tv = ws.cell(row=r, column=6, value=float(cost_summary.get("total_cost") or 0))
    tv.font = BOLD; tv.number_format = CURRENCY_FMT
    _widths(ws, [12, 14, 45, 22, 12, 16])

    # 3 · Repairs
    ws = wb.create_sheet("Repairs")
    _hdr(ws, ["Date", "Description", "Workshop", "Vendor Payable",
              "Mechanic Payable", "Repair Cost", "Status"])
    r = 2
    for ev in ((repair_history or {}).get("events") or []):
        ws.cell(row=r, column=1, value=ev.get("event_date") or "")
        ws.cell(row=r, column=2, value=ev.get("description") or "")
        ws.cell(row=r, column=3, value=ev.get("workshop_name") or "")
        for col, k in [(4, "vendor_payable"), (5, "mechanic_payable"), (6, "total_repair_cost")]:
            c = ws.cell(row=r, column=col, value=float(ev.get(k) or 0))
            c.number_format = CURRENCY_FMT
        ws.cell(row=r, column=7, value=(ev.get("status") or "").upper())
        r += 1
    tl = ws.cell(row=r, column=5, value="Total Repair Cost"); tl.font = BOLD
    tv = ws.cell(row=r, column=6, value=float((repair_history or {}).get("total_repair_cost") or 0))
    tv.font = BOLD; tv.number_format = CURRENCY_FMT
    _widths(ws, [12, 30, 22, 16, 16, 14, 12])

    # 4 · Iter143 P2 · Trip Cost (additive, Iter142 sheets untouched)
    ws = wb.create_sheet("Trip Cost")
    trip_meta_map = trip_meta_map or {}
    trip_groups = _group_trip_costs_xlsx(cost_summary.get("rows") or [])
    trip_sum = round(sum(g["total"] for g in trip_groups), 2)
    trip_linked = round(float(cost_summary.get("trip_linked_total") or 0), 2)
    if abs(trip_sum - trip_linked) > 0.01:
        raise ValueError(
            f"Iter143 P2 reconciliation guard failed (xlsx) — grouped trip total "
            f"₹{trip_sum:.2f} != cost_summary.trip_linked_total ₹{trip_linked:.2f}. "
            f"Refusing to emit an inconsistent workbook."
        )
    _hdr(ws, ["Trip Date", "Trip Ref", "Route", "Customer / Driver",
              "Type", "Categories", "Trip Cost"])
    def _tkey(g):
        m = trip_meta_map.get(g["trip_id"]) or {}
        return (m.get("date") or "", g["trip_id"])
    trip_groups.sort(key=_tkey, reverse=True)
    r = 2
    for g in trip_groups:
        m = trip_meta_map.get(g["trip_id"]) or {}
        is_sup = m.get("vehicle_type") == "supplier"
        party = m.get("supplier_name") if is_sup else m.get("customer") or ""
        drv = m.get("driver_name") or ""
        party_drv = " · ".join(x for x in (party, drv) if x)
        fr, to_ = m.get("from_location") or "", m.get("to_location") or ""
        route = f"{fr} → {to_}" if (fr or to_) else ""
        trip_ref = m.get("lr_number") or g["trip_id"]
        cats = ", ".join(f"{c} ₹{a:,.2f}" for c, a in g["categories"])
        ws.cell(row=r, column=1, value=m.get("date") or "")
        ws.cell(row=r, column=2, value=trip_ref)
        ws.cell(row=r, column=3, value=route)
        ws.cell(row=r, column=4, value=party_drv)
        ws.cell(row=r, column=5, value="SUPPLIER" if is_sup else "OWN")
        ws.cell(row=r, column=6, value=cats)
        c = ws.cell(row=r, column=7, value=float(g["total"]))
        c.number_format = CURRENCY_FMT
        r += 1
    tl = ws.cell(row=r, column=6, value="Total Trip-linked Cost"); tl.font = BOLD
    tv = ws.cell(row=r, column=7, value=float(trip_sum))
    tv.font = BOLD; tv.number_format = CURRENCY_FMT
    _widths(ws, [12, 18, 30, 26, 10, 45, 16])

    # 5 · By Category
    ws = wb.create_sheet("By Category")
    _hdr(ws, ["Category", "Amount"])
    r = 2
    for c in (cost_summary.get("by_category") or []):
        ws.cell(row=r, column=1, value=c.get("category") or "")
        cc = ws.cell(row=r, column=2, value=float(c.get("amount") or 0))
        cc.number_format = CURRENCY_FMT
        r += 1
    _widths(ws, [22, 16])

    # 5 · By Month
    ws = wb.create_sheet("By Month")
    _hdr(ws, ["Month", "Amount"])
    r = 2
    for m in (cost_summary.get("by_month") or []):
        ws.cell(row=r, column=1, value=m.get("month") or "")
        cc = ws.cell(row=r, column=2, value=float(m.get("amount") or 0))
        cc.number_format = CURRENCY_FMT
        r += 1
    _widths(ws, [14, 16])

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
