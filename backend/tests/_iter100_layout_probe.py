"""Local layout probe: page count for N-trip landscape invoice (no HTTP)."""
import io, sys
sys.path.insert(0, "/app/backend")
from pdf.invoice import build_invoice_pdf
from pypdf import PdfReader

company = {"name": "QORVENA LOGISTICS", "address": "Plot 12, Industrial Estate, Kakinada, AP 533003",
           "phone": "9876543210", "email": "acc@qorvena.in", "gstin": "37AAAAA0000A1Z5",
           "pan": "AAAAA0000A", "state": "Andhra Pradesh", "bank_name": "HDFC Bank",
           "account_number": "50200012345678", "ifsc": "HDFC0001234", "branch": "Kakinada"}
customer = {"name": "TEST Customer Pvt Ltd", "address": "NH-16, Vizag", "state": "AP",
            "gstin": "37BBBBB1111B1Z5", "phone": "9000011111"}


def mk_trip(i, method):
    return {"date": f"2026-10-{i:02d}", "vehicle_number": f"AP39UK51{i:02d}",
            "customer_reference_number": f"CREF-{i}", "load_details": "BITUMEN VG 30",
            "from_location": "Kakinada", "to_location": "Vizag",
            "applied_freight_method": method, "freight_mode": "per_ton",
            "rate_per_ton": 1000, "tons": 20, "freight_qty_used": 20,
            "freight_amount": 20000, "halting_amount": 3000,
            "chargeable_halting_days": 2, "halting_rate_per_day": 1500,
            "shortage_qty": 0.2, "shortage_amount": 8000, "product_rate_per_mt": 40000,
            "expenses": {"diesel_from_customer_amount": 9000, "diesel_from_customer_qty": 100,
                         "diesel_from_customer_rate": 90, "cash_advance_received": 5000}}


for n in (1, 2, 4, 8):
    trips = [mk_trip(i + 1, ["per_ton_higher_of", "per_ton_loading", "fixed", ""][i % 4])
             for i in range(n)]
    inv = {"invoice_number": f"QV/26-27/000{n}", "invoice_date": "2026-10-20",
           "hsn_sac": "996791", "gst_type": "cgst_sgst", "subtotal": 20000 * n,
           "cgst_amount": 500 * n, "sgst_amount": 500 * n, "total_tax": 1000 * n,
           "gross_total": 21000 * n, "round_off": 0, "total_amount": 21000 * n,
           "amount_paid": 0, "balance_due": 21000 * n}
    pdf = build_invoice_pdf(company, customer, inv, trips)
    rd = PdfReader(io.BytesIO(pdf))
    pages = [(p.extract_text() or "").strip() for p in rd.pages]
    print(f"trips={n} pages={len(rd.pages)}")
    for i, txt in enumerate(pages):
        print(f"   page{i+1}: starts {txt[:40]!r} ... ends {txt[-60:]!r}")
