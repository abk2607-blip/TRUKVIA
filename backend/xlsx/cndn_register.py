"""Iter132c C4 · Credit Note / Debit Note Register XLSX export.

Pure projection of the C4 canonical payload returned by
`_cndn_register_payload()`. Never recomputes tax, totals, sign, or
routing.

Four sheets:
    Summary  ·  Credit_Notes  ·  Debit_Notes  ·  By_Reason

The workbook is a WORKING REPORT, not a GST portal upload file
(§9B is the statutory feed — LOCKED as C3.1/C3.2).
"""
from io import BytesIO
from datetime import datetime, timezone
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter


HDR_FONT  = Font(name="Calibri", bold=True, color="FFFFFF")
HDR_FILL  = PatternFill("solid", fgColor="0F172A")
BAND      = PatternFill("solid", fgColor="F1F5F9")
CN_FILL   = PatternFill("solid", fgColor="FEF2F2")   # red-50
DN_FILL   = PatternFill("solid", fgColor="EFF6FF")   # blue-50
GOOD_FILL = PatternFill("solid", fgColor="D1FAE5")
BAD_FILL  = PatternFill("solid", fgColor="FEE2E2")
INFO_FILL = PatternFill("solid", fgColor="FEF3C7")
DISC_FILL = PatternFill("solid", fgColor="FEF9C3")
_thin     = Side(border_style="thin", color="CBD5E1")
BORDER    = Border(left=_thin, right=_thin, top=_thin, bottom=_thin)

# ` ₹ ` prefix — matches locked C3.5 §9A workbook convention. Unicode
# escape avoids f-string backslash restrictions.
CURRENCY_FMT = '"\u20b9 "#,##0.00'
NUM_FMT      = "#,##0.00"

# Unicode literals hoisted to module constants — Python 3.11 forbids
# backslash escapes inside f-string expression parts.
_EMDASH  = "\u2014"
_DOT     = "\u00b7"
_RUPEE   = "\u20b9"


# Column headers — LOCKED as of C4. Tests reference these lists.
REGISTER_HEADERS = [
    "Note #", "Date", "Type", "Status",
    "Customer", "GSTIN", "State",
    "Invoice #", "Invoice Date",
    "Reason", "\u00a79B Rsn", "Reason Text",
    f"Taxable ({_RUPEE})", "GST Type", "Rate %",
    f"CGST ({_RUPEE})", f"SGST ({_RUPEE})", f"IGST ({_RUPEE})",
    f"Total Tax ({_RUPEE})", f"Total ({_RUPEE})",
    f"Signed ({_RUPEE})", "RCM", "GST Applied",
]

BY_REASON_HEADERS = [
    "QORVENA Reason", "\u00a79B Code", "Count", "CN Count", "DN Count",
    f"Total ({_RUPEE})",
]


def _write_header(ws, headers: list, row: int = 4):
    for col, h in enumerate(headers, 1):
        c = ws.cell(row=row, column=col, value=h)
        c.font = HDR_FONT; c.fill = HDR_FILL; c.border = BORDER
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[row].height = 32
    ws.freeze_panes = ws.cell(row=row + 1, column=1)


def _write_row(ws, row_idx: int, values: list, *,
               tint_fill=None, currency_cols=(), num_cols=()):
    for col, v in enumerate(values, 1):
        c = ws.cell(row=row_idx, column=col, value=v)
        c.border = BORDER
        if tint_fill is not None:
            c.fill = tint_fill
        elif row_idx % 2 == 0:
            c.fill = BAND
        if col in currency_cols:
            c.number_format = CURRENCY_FMT
        elif col in num_cols:
            c.number_format = NUM_FMT
        c.alignment = Alignment(vertical="center", wrap_text=True)


def _apply_widths(ws, widths):
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w


# ─── Sheet builders ─────────────────────────────────────────────────────

def _build_summary(ws, company: dict, payload: dict):
    ws.cell(row=1, column=1, value=company.get("name", "")).font = Font(bold=True, size=14)
    period = payload.get("period", {})
    ws.cell(row=2, column=1, value=(
        f"CN/DN Register  {_DOT}  {period.get('start','')} to {period.get('end','')}  {_DOT}  "
        f"GSTIN {payload.get('issuer_gstin') or _EMDASH}  {_DOT}  "
        f"generated {datetime.now(timezone.utc).strftime('%d-%b-%Y %H:%M UTC')}"
    )).font = Font(italic=True, color="475569")

    # ── KPI block ─────────────────────────────────────────────
    _write_header(ws, ["Metric", "Value"], row=4)
    k = payload["kpis"]
    t = payload["tax_summary"]
    rows_out = [
        ("Total notes",                 k["total_count"]),
        ("Credit notes (count)",        k["credit_count"]),
        (f"Credit total ({_RUPEE})",         k["credit_total"]),
        ("Debit notes (count)",         k["debit_count"]),
        (f"Debit total ({_RUPEE})",          k["debit_total"]),
        (f"Net receivable change ({_RUPEE})",k["net_amount"]),
        ("GST applied (count)",         k["gst_applied_count"]),
        (f"GST applied total ({_RUPEE})",    k["gst_applied_total"]),
        ("GST excluded (count)",        k["gst_excluded_count"]),
        (f"GST excluded total ({_RUPEE})",   k["gst_excluded_total"]),
        ("Issued",                      k["issued_count"]),
        ("Draft",                       k["draft_count"]),
        ("Cancelled",                   k["cancelled_count"]),
    ]
    for i, r in enumerate(rows_out, start=5):
        c1 = ws.cell(row=i, column=1, value=r[0])
        c2 = ws.cell(row=i, column=2, value=r[1])
        c1.border = BORDER; c2.border = BORDER
        c1.alignment = Alignment(vertical="center")
        c2.alignment = Alignment(vertical="center", horizontal="right")
        if "count" in r[0].lower() or r[0] in ("Total notes", "Issued", "Draft", "Cancelled"):
            c2.number_format = "0"
        else:
            c2.number_format = CURRENCY_FMT

    # ── Tax summary block ────────────────────────────────────
    r0 = 5 + len(rows_out) + 2
    ws.cell(row=r0, column=1, value="Tax Summary").font = Font(bold=True, size=12)
    tax_rows = [
        (f"Taxable ({_RUPEE})",   t["taxable"]),
        (f"CGST ({_RUPEE})",      t["cgst"]),
        (f"SGST ({_RUPEE})",      t["sgst"]),
        (f"IGST ({_RUPEE})",      t["igst"]),
        (f"Total Tax ({_RUPEE})", t["total_tax"]),
        (f"Grand Total ({_RUPEE})", t["total_amount"]),
    ]
    for i, r in enumerate(tax_rows, start=r0 + 1):
        c1 = ws.cell(row=i, column=1, value=r[0])
        c2 = ws.cell(row=i, column=2, value=r[1])
        c1.border = BORDER; c2.border = BORDER
        c1.alignment = Alignment(vertical="center")
        c2.alignment = Alignment(vertical="center", horizontal="right")
        c2.number_format = CURRENCY_FMT

    # ── Reconciliation block ─────────────────────────────────
    recon = payload.get("reconciliation") or {}
    r1 = r0 + 1 + len(tax_rows) + 2
    ws.cell(row=r1, column=1, value="Reconciliation").font = Font(bold=True, size=12)
    ws.cell(row=r1 + 1, column=1, value="Reconciled?")
    rc = ws.cell(row=r1 + 1, column=2, value="YES" if recon.get("reconciled") else "NO")
    rc.fill = GOOD_FILL if recon.get("reconciled") else BAD_FILL
    rc.font = Font(bold=True)
    labels = [
        (f"Endpoint {_DOT} row count",     recon.get("endpoint_row_count", 0)),
        (f"Ground truth {_DOT} row count", recon.get("ground_truth_row_count", 0)),
        (f"Endpoint {_DOT} total ({_RUPEE})",     recon.get("endpoint_total", 0.0)),
        (f"Ground truth {_DOT} total ({_RUPEE})", recon.get("ground_truth_total", 0.0)),
    ]
    for i, (lbl, val) in enumerate(labels, start=r1 + 2):
        ws.cell(row=i, column=1, value=lbl)
        c = ws.cell(row=i, column=2, value=val)
        c.number_format = "0" if "count" in lbl else CURRENCY_FMT

    # ── Filters applied ──────────────────────────────────────
    r2 = r1 + 2 + len(labels) + 2
    ws.cell(row=r2, column=1, value="Filters").font = Font(bold=True, size=12)
    f = payload.get("filters", {})
    filter_rows = [
        ("Date range", f"{f.get('from','')} to {f.get('to','')}"),
        ("Kind", f.get("kind", "all")),
        ("Status", f.get("status", "issued")),
        ("Customer ID", f.get("customer_id") or "(all)"),
        ("Reason code", f.get("reason_code") or "(all)"),
    ]
    for i, (lbl, val) in enumerate(filter_rows, start=r2 + 1):
        ws.cell(row=i, column=1, value=lbl)
        ws.cell(row=i, column=2, value=val)

    # ── Disclosure banner ────────────────────────────────────
    r3 = r2 + 1 + len(filter_rows) + 2
    disc = ws.cell(row=r3, column=1, value="Statutory disclosure")
    disc.font = Font(bold=True, size=12)
    lines = [
        "This is a WORKING REPORT (CN/DN Register), not a GST portal upload file.",
        "The statutory feed is GSTR-1 §9B (see /reports/gstr1-9b). §9A invoice-side is in /reports/gstr1.",
        "All values are read verbatim from persisted credit_debit_notes. No recompute in this export.",
    ]
    for i, ln in enumerate(lines, start=r3 + 1):
        c = ws.cell(row=i, column=1, value=ln)
        c.fill = DISC_FILL
        c.alignment = Alignment(vertical="center", wrap_text=True)
        ws.merge_cells(start_row=i, start_column=1, end_row=i, end_column=5)

    # ── Warnings block ───────────────────────────────────────
    warns = payload.get("warnings", []) or []
    if warns:
        rw = r3 + 1 + len(lines) + 2
        ws.cell(row=rw, column=1, value="Warnings").font = Font(bold=True, size=12)
        for i, w in enumerate(warns, start=rw + 1):
            c = ws.cell(row=i, column=1, value=w)
            c.fill = INFO_FILL
            ws.merge_cells(start_row=i, start_column=1, end_row=i, end_column=5)

    _apply_widths(ws, [42, 28, 20, 20, 20])


def _row_values(r: dict) -> list:
    """22-column register row shape — matches REGISTER_HEADERS."""
    rate = 0.0
    if (r.get("gst_type") or "cgst_sgst") == "igst":
        rate = float(r.get("igst_rate", 0) or 0)
    else:
        rate = float(r.get("cgst_rate", 0) or 0) + float(r.get("sgst_rate", 0) or 0)
    return [
        r.get("note_number", ""),
        r.get("note_date", ""),
        r.get("ntty", ""),
        r.get("status", ""),
        r.get("customer_name", ""),
        r.get("customer_gstin", ""),
        r.get("customer_state", ""),
        r.get("invoice_number", ""),
        r.get("invoice_date", ""),
        r.get("reason_code", ""),
        r.get("reason_code_gstr1_9b", ""),
        r.get("reason_text", ""),
        float(r.get("subtotal", 0) or 0),
        r.get("gst_type", ""),
        rate,
        float(r.get("cgst_amount", 0) or 0),
        float(r.get("sgst_amount", 0) or 0),
        float(r.get("igst_amount", 0) or 0),
        float(r.get("total_tax", 0) or 0),
        float(r.get("total_amount", 0) or 0),
        float(r.get("signed_amount", 0) or 0),
        "Y" if r.get("rcm") else "N",
        "Y" if r.get("apply_gst") else "N",
    ]


_REG_WIDTHS = [
    20, 12, 6, 10,      # note#, date, T, status
    30, 18, 16,         # customer, gstin, state
    22, 12,             # invoice#, invoice_date
    18, 8, 30,          # reason, 9b, reason_text
    14, 10, 8,          # taxable, gst_type, rate
    14, 14, 14, 14, 16, # cgst, sgst, igst, total_tax, total
    16, 6, 8,           # signed, rcm, gst_applied
]

_REG_CURRENCY_COLS = (13, 16, 17, 18, 19, 20, 21)   # taxable, cgst, sgst, igst, total_tax, total, signed
_REG_NUM_COLS = (15,)                                # rate %


def _build_register_sheet(ws, payload: dict, kind: str, title_kind: str, fill):
    period = payload.get("period", {})
    ws.cell(row=1, column=1, value=(
        f"{title_kind} {_DOT} Period {period.get('start','')} to {period.get('end','')}"
    )).font = Font(bold=True, size=12)
    _write_header(ws, REGISTER_HEADERS)
    r = 5
    for row in payload.get("rows", []) or []:
        if kind != "all" and row.get("kind") != kind:
            continue
        _write_row(
            ws, r, _row_values(row),
            tint_fill=fill,
            currency_cols=_REG_CURRENCY_COLS,
            num_cols=_REG_NUM_COLS,
        )
        r += 1
    _apply_widths(ws, _REG_WIDTHS)


def _build_by_reason(ws, payload: dict):
    period = payload.get("period", {})
    ws.cell(row=1, column=1, value=(
        f"By Reason {_DOT} Period {period.get('start','')} to {period.get('end','')}"
    )).font = Font(bold=True, size=12)
    _write_header(ws, BY_REASON_HEADERS)
    r = 5
    for br in payload.get("by_reason", []) or []:
        _write_row(ws, r, [
            br.get("reason_code", ""),
            br.get("gstr1_9b_reason_code", ""),
            int(br.get("count", 0) or 0),
            int(br.get("credit_count", 0) or 0),
            int(br.get("debit_count", 0) or 0),
            float(br.get("total_amount", 0) or 0),
        ], currency_cols=(6,))
        r += 1
    _apply_widths(ws, [24, 12, 10, 12, 12, 20])


def build_cndn_register_xlsx(company: dict, payload: dict) -> bytes:
    """Build the full 4-sheet workbook and return raw bytes."""
    wb = openpyxl.Workbook()
    ws_summary = wb.active
    ws_summary.title = "Summary"

    _build_summary(ws_summary, company, payload)
    _build_register_sheet(wb.create_sheet("Credit_Notes"), payload, "credit", "Credit Notes", CN_FILL)
    _build_register_sheet(wb.create_sheet("Debit_Notes"),  payload, "debit",  "Debit Notes",  DN_FILL)
    _build_by_reason(wb.create_sheet("By_Reason"), payload)

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
