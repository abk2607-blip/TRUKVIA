"""Iter132c C3.5 · GSTR-1 §9A (invoice-side) XLSX export.

Pure projection of the C3.5 canonical payload returned by
`_gstr1_payload()`. Never recomputes tax, totals, POS, or GST routing.

Four sheets:
    Summary · B2B · B2C · By_State

Deterministic row order: invoices are already ordered by (invoice_date,
invoice_number) inside the payload builder — this workbook renders them
row-for-row.

The workbook is a WORKING REPORT, not a GST portal upload file. B2CL,
HSN, Docs, and Amendment sheets are deliberately not emitted (see the
Statutory Disclosure banner in the Summary sheet).
"""
from io import BytesIO
from datetime import datetime, timezone
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter


HDR_FONT  = Font(name="Calibri", bold=True, color="FFFFFF")
HDR_FILL  = PatternFill("solid", fgColor="0F172A")
BAND      = PatternFill("solid", fgColor="F1F5F9")
GOOD_FILL = PatternFill("solid", fgColor="D1FAE5")
BAD_FILL  = PatternFill("solid", fgColor="FEE2E2")
INFO_FILL = PatternFill("solid", fgColor="FEF3C7")
DISC_FILL = PatternFill("solid", fgColor="FEF9C3")
_thin     = Side(border_style="thin", color="CBD5E1")
BORDER    = Border(left=_thin, right=_thin, top=_thin, bottom=_thin)

CURRENCY_FMT = '"\u20b9 "#,##0.00'   # ` ₹ ` prefix (unicode escape avoids f-string backslash)
NUM_FMT      = "#,##0.00"

# Unicode literals hoisted to module constants — Python 3.11 forbids
# backslash escapes inside f-string expression parts.
_EMDASH  = "\u2014"
_DOT     = "\u00b7"
_RUPEE   = "\u20b9"
_SECTION = "\u00a7"


# Column headers — LOCKED as of C3.5. Tests reference these lists.
# ₹ appears ONLY in column headers via "(₹)" suffix; data cells carry
# plain numbers formatted via CURRENCY_FMT which prefixes ₹.
B2B_HEADERS = [
    "Invoice", "Date", "Customer", "GSTIN", "State", "State Code", "POS",
    "RCM", "Taxable (\u20b9)", "CGST (\u20b9)", "SGST (\u20b9)", "IGST (\u20b9)",
    "Total (\u20b9)", "GST Type",
]
B2C_HEADERS = [
    "Invoice", "Date", "Customer", "State", "State Code", "POS",
    "RCM", "Taxable (\u20b9)", "CGST (\u20b9)", "SGST (\u20b9)", "IGST (\u20b9)",
    "Total (\u20b9)", "GST Type",
]
BY_STATE_HEADERS = [
    "State", "Code", "Invoices", "Taxable (\u20b9)", "CGST (\u20b9)",
    "SGST (\u20b9)", "IGST (\u20b9)", "Total (\u20b9)",
]


def _write_header(ws, headers: list, row: int = 4):
    for col, h in enumerate(headers, 1):
        c = ws.cell(row=row, column=col, value=h)
        c.font = HDR_FONT; c.fill = HDR_FILL; c.border = BORDER
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[row].height = 32
    ws.freeze_panes = ws.cell(row=row + 1, column=1)


def _write_row(ws, row_idx: int, values: list, *, currency_cols=(), num_cols=()):
    for col, v in enumerate(values, 1):
        c = ws.cell(row=row_idx, column=col, value=v)
        c.border = BORDER
        if row_idx % 2 == 0:
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
    ws.cell(row=2, column=1, value=(
        f"TRUKVIA {_DOT} GSTR-1 {_SECTION}9A {_DOT} Invoice Register (B2B + B2C)  {_DOT}  {payload['month']}  {_DOT}  "
        f"GSTIN {payload.get('issuer_gstin') or _EMDASH}  {_DOT}  "
        f"generated {datetime.now(timezone.utc).strftime('%d-%b-%Y %H:%M UTC')}"
    )).font = Font(italic=True, color="475569")

    _write_header(ws, ["Metric", "Value"], row=4)

    t = payload["totals"]
    rows_out = [
        ("Invoices",             payload.get("invoice_count", 0)),
        (f"Taxable value ({_RUPEE})", t.get("taxable", 0.0)),
        (f"CGST ({_RUPEE})",          t.get("cgst", 0.0)),
        (f"SGST ({_RUPEE})",          t.get("sgst", 0.0)),
        (f"IGST ({_RUPEE})",          t.get("igst", 0.0)),
        (f"Grand total ({_RUPEE})",   t.get("total", 0.0)),
    ]
    for i, r in enumerate(rows_out, start=5):
        c1 = ws.cell(row=i, column=1, value=r[0])
        c2 = ws.cell(row=i, column=2, value=r[1])
        c1.border = BORDER; c2.border = BORDER
        c1.alignment = Alignment(vertical="center")
        c2.alignment = Alignment(vertical="center", horizontal="right")
        if r[0] == "Invoices":
            c2.number_format = "0"
        else:
            c2.number_format = CURRENCY_FMT

    # Reconciliation block
    recon = payload.get("reconciliation") or {}
    r0 = 5 + len(rows_out) + 2
    ws.cell(row=r0, column=1, value="Reconciliation").font = Font(bold=True, size=12)
    ws.cell(row=r0 + 1, column=1, value="Reconciled?")
    rc = ws.cell(row=r0 + 1, column=2, value="YES" if recon.get("reconciled") else "NO")
    rc.fill = GOOD_FILL if recon.get("reconciled") else BAD_FILL
    rc.font = Font(bold=True)

    labels = [
        (f"Endpoint {_DOT} invoice count",     recon.get("endpoint_invoice_count", 0)),
        (f"Ground truth {_DOT} invoice count", recon.get("ground_truth_invoice_count", 0)),
        (f"Endpoint {_DOT} total ({_RUPEE})",       recon.get("endpoint_total", 0.0)),
        (f"Ground truth {_DOT} total ({_RUPEE})",   recon.get("ground_truth_total", 0.0)),
        (f"Endpoint {_DOT} taxable ({_RUPEE})",     recon.get("endpoint_taxable", 0.0)),
        (f"Ground truth {_DOT} taxable ({_RUPEE})", recon.get("ground_truth_taxable", 0.0)),
    ]
    for i, (lbl, val) in enumerate(labels, start=r0 + 2):
        ws.cell(row=i, column=1, value=lbl)
        c = ws.cell(row=i, column=2, value=val)
        c.number_format = "0" if "count" in lbl else CURRENCY_FMT

    # Statutory disclosure banner
    r_disc = r0 + 2 + len(labels) + 2
    disc = ws.cell(row=r_disc, column=1, value="Statutory disclosure")
    disc.font = Font(bold=True, size=12)
    lines = [
        "This is a WORKING REPORT of QORVENA's invoice-side GSTR-1 dataset, not a GST portal upload file.",
        "Not emitted here (out of scope for C3.5): B2CL split, HSN Summary (Table 12), Docs Summary (Table 13), Amendments (9A / 9B / 9C).",
        f"POS = customer.state per IGST {_SECTION}12(9). Ship-To is operational and does not override POS.",
    ]
    for i, ln in enumerate(lines, start=r_disc + 1):
        c = ws.cell(row=i, column=1, value=ln)
        c.fill = DISC_FILL
        c.alignment = Alignment(vertical="center", wrap_text=True)
        ws.merge_cells(start_row=i, start_column=1, end_row=i, end_column=5)

    # Warnings block
    warns = payload.get("warnings", []) or []
    if warns:
        rw = r_disc + 1 + len(lines) + 2
        ws.cell(row=rw, column=1, value="Warnings").font = Font(bold=True, size=12)
        for i, w in enumerate(warns, start=rw + 1):
            c = ws.cell(row=i, column=1, value=w)
            c.fill = INFO_FILL
            ws.merge_cells(start_row=i, start_column=1, end_row=i, end_column=5)

    _apply_widths(ws, [42, 28, 20, 20, 20])


def _b2b_row_values(r: dict) -> list:
    return [
        r.get("invoice_number", ""),
        r.get("invoice_date", ""),
        r.get("customer_name", ""),
        r.get("gstin", ""),
        r.get("state", ""),
        r.get("state_code", ""),
        r.get("place_of_supply", ""),
        r.get("reverse_charge", "N"),
        float(r.get("taxable_value", 0) or 0),
        float(r.get("cgst", 0) or 0),
        float(r.get("sgst", 0) or 0),
        float(r.get("igst", 0) or 0),
        float(r.get("total", 0) or 0),
        r.get("gst_type", ""),
    ]


def _b2c_row_values(r: dict) -> list:
    return [
        r.get("invoice_number", ""),
        r.get("invoice_date", ""),
        r.get("customer_name", ""),
        r.get("state", ""),
        r.get("state_code", ""),
        r.get("place_of_supply", ""),
        r.get("reverse_charge", "N"),
        float(r.get("taxable_value", 0) or 0),
        float(r.get("cgst", 0) or 0),
        float(r.get("sgst", 0) or 0),
        float(r.get("igst", 0) or 0),
        float(r.get("total", 0) or 0),
        r.get("gst_type", ""),
    ]


def _build_b2b(ws, payload: dict):
    ws.cell(row=1, column=1, value=(
        f"B2B Invoices (registered recipients) {_DOT} Period {payload['month']}"
    )).font = Font(bold=True, size=12)
    _write_header(ws, B2B_HEADERS)
    r = 5
    for row in payload.get("b2b", []) or []:
        _write_row(ws, r, _b2b_row_values(row),
                   currency_cols=(9, 10, 11, 12, 13))
        r += 1
    _apply_widths(ws, [22, 14, 32, 20, 20, 8, 12, 6, 18, 14, 14, 14, 18, 14])


def _build_b2c(ws, payload: dict):
    ws.cell(row=1, column=1, value=(
        f"B2C Invoices (unregistered recipients) {_DOT} Period {payload['month']}"
    )).font = Font(bold=True, size=12)
    _write_header(ws, B2C_HEADERS)
    r = 5
    for row in payload.get("b2c", []) or []:
        _write_row(ws, r, _b2c_row_values(row),
                   currency_cols=(8, 9, 10, 11, 12))
        r += 1
    _apply_widths(ws, [22, 14, 32, 20, 8, 12, 6, 18, 14, 14, 14, 18, 14])


def _build_by_state(ws, payload: dict):
    ws.cell(row=1, column=1, value=(
        f"By State (POS) {_DOT} Period {payload['month']}"
    )).font = Font(bold=True, size=12)
    _write_header(ws, BY_STATE_HEADERS)
    r = 5
    for s in payload.get("by_state", []) or []:
        _write_row(ws, r, [
            s.get("state", ""),
            s.get("state_code", ""),
            int(s.get("invoices", 0) or 0),
            float(s.get("taxable", 0) or 0),
            float(s.get("cgst", 0) or 0),
            float(s.get("sgst", 0) or 0),
            float(s.get("igst", 0) or 0),
            float(s.get("total", 0) or 0),
        ], currency_cols=(4, 5, 6, 7, 8))
        r += 1
    _apply_widths(ws, [26, 8, 12, 18, 14, 14, 14, 20])


def build_gstr1_xlsx(company: dict, payload: dict) -> bytes:
    """Build the full 4-sheet workbook and return raw bytes."""
    wb = openpyxl.Workbook()
    ws_summary = wb.active
    ws_summary.title = "Summary"

    _build_summary(ws_summary, company, payload)
    _build_b2b(wb.create_sheet("B2B"), payload)
    _build_b2c(wb.create_sheet("B2C"), payload)
    _build_by_state(wb.create_sheet("By_State"), payload)

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
