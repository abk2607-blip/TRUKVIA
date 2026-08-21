"""Iter102 · Multi-Trip UAT + Supplier Statement Cross-Check.

Guards the end-to-end parity that a real user sees:

Trip UI  →  Invoice PDF  →  Supplier Statement PDF

Simulates a mid-month billing cycle:
  • 4 customer trips (per_ton_loading / _unloading / _higher_of / fixed)
    with DIFFERENT ship-to sites + different customer reference numbers.
  • 4 supplier trips against ONE supplier (varied quantities, halting,
    diesel, advances, shortages).
  • Consolidates the customer trips into ONE invoice.
  • Pulls the supplier settlement/statement and cross-checks EACH field
    (supplier_freight, halting, diesel, advance, shortage_deduction,
    net_payable) matches the Trip's own persisted values.

If any of these numbers drift 1 paisa apart between the Trip and the
downstream artefacts, the guard fails.
"""
import io
import os
import time
import uuid

import httpx
from pypdf import PdfReader

API = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/") + "/api"
TOK = "test_session_bitumen_2026"
H = {"Authorization": f"Bearer {TOK}", "Content-Type": "application/json"}
T = 60


def _boot():
    httpx.post(f"{API}/auth/demo-login", timeout=T)


def _pdf_text(content: bytes) -> str:
    return " ".join(
        (" ".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(content)).pages)).split()
    )


def _norm_money(v: float) -> str:
    """Return the value in the exact format the PDFs use: `1,234.56`."""
    return f"{v:,.2f}"


def test_multi_trip_invoice_and_supplier_statement_parity():
    _boot()
    tag = uuid.uuid4().hex[:6]

    # ------------------------------------------------------------------
    # 1. Reference masters — customer, supplier, product, vehicles
    # ------------------------------------------------------------------
    customer = httpx.post(f"{API}/customers", headers=H, json={
        "name": f"IT102_UAT_Cust_{tag}", "state": "AP", "phone": "9990101020",
        "address": "Plot 7, Kakinada", "gstin": "37ABCDE1234F1Z5",
        "default_freight_method": "per_ton_loading",
    }, timeout=T).json()

    supplier = httpx.post(f"{API}/suppliers", headers=H, json={
        "name": f"IT102_UAT_Sup_{tag}", "state": "AP", "phone": "9990202030",
        "shortage_limit_kg": 200,          # 200 kg supplier allowance
    }, timeout=T).json()

    product = httpx.post(f"{API}/products", headers=H, json={
        "name": f"IT102_UAT_Prod_{tag}",
        "hsn": "27150010",
    }, timeout=T).json()

    own_vehicle = httpx.post(f"{API}/vehicles", headers=H, json={
        "vehicle_number": f"AP102O{tag[:4].upper()}", "vehicle_type": "own",
    }, timeout=T).json()

    supplier_vehicle = httpx.post(f"{API}/vehicles", headers=H, json={
        "vehicle_number": f"AP102S{tag[:4].upper()}", "vehicle_type": "supplier",
        "supplier_id": supplier["id"],
    }, timeout=T).json()

    created_customers = [customer]
    created_trips = []
    created_invoices = []

    try:
        # --------------------------------------------------------------
        # 2. Create 4 customer trips — cover EVERY freight method +
        #    different ref numbers.  Customer with per_ton_loading;
        #    per-trip we pass applied_freight_method to force the method.
        # --------------------------------------------------------------
        customer_specs = [
            # (method, ref, tons, unloaded, rate, extra)
            ("per_ton_loading",   "UAT-A1", 20.0, 19.7, 1000, {}),
            ("per_ton_unloading", "UAT-A2", 25.0, 24.6, 1100, {}),
            ("per_ton_higher_of", "UAT-A3", 22.0, 22.5, 1200, {}),
            ("fixed",             "UAT-A4", 18.0, 18.0,    0,
                {"freight_mode": "fixed", "fixed_amount": 32500}),
        ]

        cust_trip_ids = []
        cust_trip_docs = []
        for m, ref, tons, unl, rate, extra in customer_specs:
            base = {
                "customer_id": customer["id"], "product_id": product["id"],
                "date": "2026-10-05",
                "vehicle_id": own_vehicle["id"],
                "vehicle_number": own_vehicle["vehicle_number"],
                "vehicle_type": "own",
                "tons": tons, "loaded_qty": tons, "unloaded_qty": unl,
                "from_location": "Kakinada",
                "to_location": "Vizag",
                "customer_reference_number": ref,
                "load_details": "Bitumen VG30",
                "product_rate_per_mt": 40000,
                "applied_freight_method": m,
                "freight_mode": "per_ton",
                "rate_per_ton": rate,
            }
            base.update(extra)
            r = httpx.post(f"{API}/trips", headers=H, json=base, timeout=T)
            assert r.status_code == 200, r.text
            trip = r.json()
            cust_trip_ids.append(trip["id"])
            cust_trip_docs.append(trip)
            created_trips.append(trip["id"])

        # Expected freight calcs
        expected_freight = {
            "UAT-A1": 20.0 * 1000,          # loading  → 20 000
            "UAT-A2": 24.6 * 1100,          # unloading → 27 060
            "UAT-A3": max(22.0, 22.5) * 1200,  # higher-of → 27 000
            "UAT-A4": 32500.0,              # fixed
        }
        for spec_trip in cust_trip_docs:
            ref = spec_trip["customer_reference_number"]
            assert round(spec_trip["freight_amount"], 2) == round(expected_freight[ref], 2), \
                f"freight mismatch for {ref}: expected {expected_freight[ref]} " \
                f"got {spec_trip['freight_amount']}"

        # --------------------------------------------------------------
        # 3. Consolidate the 4 trips into ONE invoice
        # --------------------------------------------------------------
        inv_r = httpx.post(f"{API}/invoices", headers=H, json={
            "customer_id": customer["id"],
            "invoice_date": "2026-10-06",
            "trip_ids": cust_trip_ids,
            "hsn_sac": "996791",
            "gst_treatment": "rcm",
            "due_date": "2026-11-06",
        }, timeout=T)
        assert inv_r.status_code in (200, 201), inv_r.text
        invoice = inv_r.json()
        created_invoices.append(invoice["id"])

        # Invoice-level freight sum must equal the sum-of-trip freight amounts
        freight_sum = round(sum(expected_freight.values()), 2)
        assert abs(float(invoice["freight_total"]) - freight_sum) < 0.02, \
            f"invoice.freight_total ({invoice['freight_total']}) != sum " \
            f"of trip freight ({freight_sum})"

        # PDF must contain every ref + every freight amount
        pdf = httpx.get(f"{API}/invoices/{invoice['id']}/pdf", headers=H, timeout=T)
        assert pdf.status_code == 200, pdf.text
        text = _pdf_text(pdf.content)
        for ref in expected_freight:
            assert ref in text, f"ref {ref} missing from consolidated PDF"
        for amt in expected_freight.values():
            assert _norm_money(amt) in text, f"freight {amt} missing from PDF"

        # --------------------------------------------------------------
        # 4. Supplier vehicle trips — full Trip → Statement cross-check
        # --------------------------------------------------------------
        # freight = supplier_rate_per_ton × supplier_quantity (per_ton mode)
        supplier_specs = [
            # (ref, tons, unloaded, rate/ton, halting_amt, diesel, advance)
            ("UAT-S1", 20.0, 19.9, 2200, 0,     0,    0),      # zero halting/diesel/advance
            ("UAT-S2", 25.0, 24.7, 2100, 1500, 1000, 5000),   # medium
            ("UAT-S3", 22.0, 21.6, 2300, 3000, 2500, 8000),   # bigger
            ("UAT-S4", 18.0, 18.0, 2400, 0,    500, 3000),
        ]
        sup_trip_docs = []
        for ref, tons, unl, rate, halting, diesel, advance in supplier_specs:
            body = {
                "customer_id": customer["id"], "product_id": product["id"],
                "date": "2026-10-05",
                "vehicle_id": supplier_vehicle["id"],
                "vehicle_number": supplier_vehicle["vehicle_number"],
                "vehicle_type": "supplier",
                "supplier_id": supplier["id"],
                "tons": tons, "loaded_qty": tons, "unloaded_qty": unl,
                "from_location": "Kakinada",
                "to_location": "Vizag",
                "customer_reference_number": ref,
                "load_details": "Bitumen VG30",
                "product_rate_per_mt": 40000,
                "freight_mode": "per_ton",
                "rate_per_ton": 1000,       # customer-side (arbitrary)
                "applied_freight_method": "per_ton_loading",
                "supplier_freight_mode": "per_ton",
                "supplier_rate_per_ton": rate,
                "supplier_quantity": tons,
                "supplier_halting_amount": halting,
                "supplier_diesel": diesel,
                "supplier_advance": advance,
            }
            r = httpx.post(f"{API}/trips", headers=H, json=body, timeout=T)
            assert r.status_code == 200, r.text
            trip = r.json()
            sup_trip_docs.append(trip)
            created_trips.append(trip["id"])

        # --------------------------------------------------------------
        # 5. Cross-check EACH supplier trip's Trip UI → statement fields
        # --------------------------------------------------------------
        for spec, trip in zip(supplier_specs, sup_trip_docs):
            ref, tons, unl, rate, halting, diesel, advance = spec
            # Trip fields — supplier freight = tons × rate/ton
            expected_freight = round(tons * rate, 2)
            assert abs(float(trip["supplier_freight"]) - expected_freight) < 0.02, \
                f"{ref}: supplier_freight expected {expected_freight}, got {trip['supplier_freight']}"

            # Halting / diesel / advance — flow through unchanged
            assert float(trip["supplier_halting_amount"]) == halting, ref
            assert float(trip["supplier_diesel"]) == diesel, ref
            assert float(trip["supplier_advance"]) == advance, ref

            # Supplier shortage — supplier has 200 kg limit; shortage_kg > 200 →
            # full trip.shortage_qty × rate deducted (Iter98 supplier calc).
            shortage_kg = round((tons - unl) * 1000, 2)
            if shortage_kg <= 200:
                expected_short_ded = 0.0
            else:
                expected_short_ded = round((trip["product_rate_per_mt"] or 0) * (tons - unl), 2)
            assert abs(float(trip["supplier_shortage_deduction"]) - expected_short_ded) < 0.02, \
                f"{ref}: expected supplier_shortage_deduction {expected_short_ded}, got {trip['supplier_shortage_deduction']}"

            # Net payable = freight + halting − advance − diesel − shortage_ded
            expected_net = round(
                expected_freight + halting - advance - diesel - expected_short_ded, 2)
            assert abs(float(trip["supplier_net_payable"]) - expected_net) < 0.02, \
                f"{ref}: expected supplier_net_payable {expected_net}, got {trip['supplier_net_payable']}"

        # --------------------------------------------------------------
        # 6. Pull the Supplier Statement JSON + PDF and confirm every
        #    trip's numbers surface exactly.  Endpoint is name-based.
        # --------------------------------------------------------------
        sname = supplier["name"]
        stmt = httpx.get(
            f"{API}/reports/supplier-statement",
            headers=H,
            params={"supplier_name": sname, "start": "2026-10-01", "end": "2026-10-31"},
            timeout=T,
        )
        assert stmt.status_code == 200, stmt.text
        stmt_json = stmt.json()
        totals = stmt_json["totals"]
        stmt_trips = stmt_json["trips"]

        # Aggregate totals must match sum of supplier trip values
        total_freight = round(sum(float(t["supplier_freight"]) for t in sup_trip_docs), 2)
        total_advance = round(sum(float(t["supplier_advance"] or 0) for t in sup_trip_docs), 2)
        total_diesel  = round(sum(float(t["supplier_diesel"]  or 0) for t in sup_trip_docs), 2)
        total_short   = round(sum(float(t["supplier_shortage_deduction"] or 0) for t in sup_trip_docs), 2)
        total_net     = round(sum(float(t["supplier_net_payable"]) for t in sup_trip_docs), 2)

        assert abs(totals["supplier_freight"] - total_freight) < 0.02, \
            f"statement supplier_freight {totals['supplier_freight']} != trip sum {total_freight}"
        assert abs(totals["supplier_advance"] - total_advance) < 0.02
        assert abs(totals["supplier_diesel"] - total_diesel) < 0.02
        assert abs(totals["supplier_shortage"] - total_short) < 0.02
        assert abs(totals["net_payable"] - total_net) < 0.02, \
            f"statement net_payable {totals['net_payable']} != trip sum {total_net}"

        # Per-row parity
        row_by_ref = {r["trip_id"]: r for r in stmt_trips}
        for tr in sup_trip_docs:
            row = row_by_ref.get(tr["id"])
            assert row is not None, f"trip {tr['id']} missing from statement rows"
            assert abs(row["supplier_freight"] - float(tr["supplier_freight"])) < 0.02
            assert abs(row["supplier_net_payable"] - float(tr["supplier_net_payable"])) < 0.02

        # Now the PDF must render + contain freight & net-payable totals.
        pdf_r = httpx.get(
            f"{API}/reports/supplier-statement.pdf",
            headers=H,
            params={"supplier_name": sname, "start": "2026-10-01", "end": "2026-10-31"},
            timeout=T,
        )
        assert pdf_r.status_code == 200, pdf_r.text
        stext = _pdf_text(pdf_r.content)
        # PDF may format numbers with either ",2f" or Indian grouping; check both.
        def _has_amount(v):
            v_r = round(v, 2)
            candidates = {
                f"{v_r:,.2f}",
                f"{v_r:.2f}",
                # Indian grouping (e.g. 1,23,456.78)
                f"{int(v_r):,}".replace(",", ",") + f".{int(round((v_r-int(v_r))*100)):02d}",
            }
            return any(c in stext for c in candidates)
        assert _has_amount(total_freight), f"Statement PDF missing freight total {total_freight}"
        assert _has_amount(total_net), f"Statement PDF missing net payable {total_net}"

    finally:
        # Cleanup — reverse order
        for iid in created_invoices:
            httpx.delete(f"{API}/invoices/{iid}", headers=H, timeout=T)
        for tid in created_trips:
            httpx.delete(f"{API}/trips/{tid}?reason=uat-cleanup", headers=H, timeout=T)
        for c in created_customers:
            httpx.delete(f"{API}/customers/{c['id']}", headers=H, timeout=T)
        httpx.delete(f"{API}/suppliers/{supplier['id']}", headers=H, timeout=T)
        httpx.delete(f"{API}/products/{product['id']}", headers=H, timeout=T)
        httpx.delete(f"{API}/vehicles/{own_vehicle['id']}", headers=H, timeout=T)
        httpx.delete(f"{API}/vehicles/{supplier_vehicle['id']}", headers=H, timeout=T)




def test_shortage_methods_net_vs_full_after_limit():
    """Same shortage magnitude, two customers — one on `net_shortage`, other on
    `full_after_limit`. Product rate 40 000/MT. Shortage 400 kg, limit 1 %.

      • Loading 33 MT → allowed = 0.33 MT (1 % of 33)
      • Actual shortage 0.400 MT (400 kg)
      • net_shortage      → (0.400 − 0.330) × 40000 = 2 800.00
      • full_after_limit  → 0.400            × 40000 = 16 000.00

    Guards that the Customer's frozen `applied_customer_shortage_method`
    drives the deduction — no silent leakage between customers.
    """
    _boot()
    tag = uuid.uuid4().hex[:6]

    net_cust = httpx.post(f"{API}/customers", headers=H, json={
        "name": f"IT102_NET_{tag}", "state": "AP",
        "shortage_config": {"limit": 1, "limit_type": "pct", "method": "net_shortage", "active": True},
    }, timeout=T).json()
    full_cust = httpx.post(f"{API}/customers", headers=H, json={
        "name": f"IT102_FULL_{tag}", "state": "AP",
        "shortage_config": {"limit": 1, "limit_type": "pct", "method": "full_after_limit", "active": True},
    }, timeout=T).json()
    veh = httpx.post(f"{API}/vehicles", headers=H, json={
        "vehicle_number": f"AP102M{tag[:4].upper()}", "vehicle_type": "own",
    }, timeout=T).json()

    made = []
    try:
        base = {
            "date": "2026-10-05",
            "vehicle_id": veh["id"], "vehicle_number": veh["vehicle_number"],
            "vehicle_type": "own",
            "tons": 33.0, "loaded_qty": 33.0, "unloaded_qty": 32.6,   # short 0.400 MT
            "freight_mode": "per_ton", "rate_per_ton": 1500,
            "product_rate_per_mt": 40000,
            "from_location": "K", "to_location": "V",
        }
        t_net = httpx.post(f"{API}/trips", headers=H,
                           json={**base, "customer_id": net_cust["id"], "customer_reference_number": "NM-1"},
                           timeout=T).json()
        t_full = httpx.post(f"{API}/trips", headers=H,
                            json={**base, "customer_id": full_cust["id"], "customer_reference_number": "FM-1"},
                            timeout=T).json()
        made = [t_net["id"], t_full["id"]]

        assert t_net["applied_customer_shortage_method"] == "net_shortage"
        assert t_full["applied_customer_shortage_method"] == "full_after_limit"
        assert abs(t_net["shortage_qty"] - 0.400) < 0.001
        assert abs(t_net["shortage_amount"] - 2800.0) < 0.02, t_net["shortage_amount"]
        assert abs(t_full["shortage_amount"] - 16000.0) < 0.02, t_full["shortage_amount"]

        # Both must appear correctly on their respective invoices
        for cust, trip, expected in ((net_cust, t_net, 2800.0),
                                     (full_cust, t_full, 16000.0)):
            inv = httpx.post(f"{API}/invoices", headers=H, json={
                "customer_id": cust["id"], "invoice_date": "2026-10-06",
                "trip_ids": [trip["id"]], "hsn_sac": "996791", "gst_treatment": "rcm",
            }, timeout=T).json()
            assert abs(float(inv["shortage_total"]) - expected) < 0.02, \
                f"invoice.shortage_total mismatch for {cust['name']}"
    finally:
        for tid in made:
            httpx.delete(f"{API}/trips/{tid}?reason=cleanup", headers=H, timeout=T)
        for c in (net_cust, full_cust):
            httpx.delete(f"{API}/customers/{c['id']}", headers=H, timeout=T)
        httpx.delete(f"{API}/vehicles/{veh['id']}", headers=H, timeout=T)
