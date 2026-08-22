"""Iter107 · Shortage Allowance % caption on Invoice PDF.

Guards the new inline caption that renders below each Trip-wise shortage
sub-row on the Invoice PDF. Reads ONLY from the frozen policy snapshot on
the Trip, so historical invoices always print the allowance that was
applied at the time of that trip, even if the current master has since
been changed.

Wording expected (rendered inside the shortage sub-row):
  Allowance: 0.5% of Loaded Qty · Product Master (≈ 0.100 MT)
  Method:    Net Shortage · Actual 0.150 MT − Allowed 0.100 MT

  Allowance: 0.3% of Loaded Qty · Custom Customer Allowance (≈ 0.060 MT)
  Method:    Net Shortage · Actual 0.150 MT − Allowed 0.060 MT

Calc engine is NOT changed — this is a pure display enhancement.
"""
import io
import os
import uuid

import httpx
from pypdf import PdfReader


API = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/") + "/api"
H = {"Authorization": "Bearer test_session_bitumen_2026", "Content-Type": "application/json"}
T = 30


def _boot():
    httpx.post(f"{API}/auth/demo-login", timeout=T)


def _pdf_text(content: bytes) -> str:
    return " ".join(
        (" ".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(content)).pages)).split()
    )


def test_product_master_allowance_caption_on_invoice_pdf():
    """Customer with NO custom allowance + Product with 0.5 % default →
    Invoice PDF must show `Allowance: 0.5% of Loaded Qty · Product Master`."""
    _boot()
    tag = uuid.uuid4().hex[:6]
    prod = httpx.post(f"{API}/products", headers=H, json={
        "name": f"IT107_ProdA_{tag}", "default_shortage_allowance_pct": 0.5,
    }, timeout=T).json()
    cust = httpx.post(f"{API}/customers", headers=H, json={
        "name": f"IT107_CustA_{tag}", "state": "AP", "gstin": "37ABCDE1234F1Z5",
        "shortage_config": {"limit": 0, "limit_type": "pct",
                             "method": "net_shortage", "active": True},
    }, timeout=T).json()
    veh = httpx.post(f"{API}/vehicles", headers=H, json={
        "vehicle_number": f"AP107A{tag[:4].upper()}", "vehicle_type": "own",
    }, timeout=T).json()
    tid = None
    inv_id = None
    try:
        t = httpx.post(f"{API}/trips", headers=H, json={
            "customer_id": cust["id"], "product_id": prod["id"],
            "date": "2026-12-01", "vehicle_id": veh["id"],
            "vehicle_number": veh["vehicle_number"], "vehicle_type": "own",
            "tons": 20.0, "loaded_qty": 20.0, "unloaded_qty": 19.85,
            "freight_mode": "per_ton", "rate_per_ton": 1500,
            "product_rate_per_mt": 40000,
        }, timeout=T).json()
        tid = t["id"]
        assert t["applied_product_shortage_pct"] == 0.5
        assert t["applied_customer_shortage_limit"] == 0.0

        inv = httpx.post(f"{API}/invoices", headers=H, json={
            "customer_id": cust["id"], "invoice_date": "2026-12-02",
            "trip_ids": [tid], "hsn_sac": "996791", "gst_treatment": "rcm",
        }, timeout=T).json()
        inv_id = inv["id"]
        pdf = httpx.get(f"{API}/invoices/{inv['id']}/pdf", headers=H, timeout=T).content
        text = _pdf_text(pdf)
        assert "Allowance:" in text, "Allowance caption missing"
        assert "0.5% of Loaded Qty" in text
        assert "Product Master" in text, "Product Master source label missing"
        assert "Net Shortage" in text
    finally:
        if inv_id:
            httpx.delete(f"{API}/invoices/{inv_id}", headers=H, timeout=T)
        if tid:
            httpx.delete(f"{API}/trips/{tid}?reason=cleanup", headers=H, timeout=T)
        httpx.delete(f"{API}/customers/{cust['id']}", headers=H, timeout=T)
        httpx.delete(f"{API}/vehicles/{veh['id']}", headers=H, timeout=T)
        httpx.delete(f"{API}/products/{prod['id']}", headers=H, timeout=T)


def test_custom_customer_allowance_caption_on_invoice_pdf():
    """Customer WITH 0.3% custom + Product with 0.5% → Invoice PDF must show
    `Allowance: 0.3% of Loaded Qty · Custom Customer Allowance` (customer wins)."""
    _boot()
    tag = uuid.uuid4().hex[:6]
    prod = httpx.post(f"{API}/products", headers=H, json={
        "name": f"IT107_ProdB_{tag}", "default_shortage_allowance_pct": 0.5,
    }, timeout=T).json()
    cust = httpx.post(f"{API}/customers", headers=H, json={
        "name": f"IT107_CustB_{tag}", "state": "AP",
        "shortage_config": {"limit": 0.3, "limit_type": "pct",
                             "method": "full_after_limit", "active": True},
    }, timeout=T).json()
    veh = httpx.post(f"{API}/vehicles", headers=H, json={
        "vehicle_number": f"AP107B{tag[:4].upper()}", "vehicle_type": "own",
    }, timeout=T).json()
    tid = None; inv_id = None
    try:
        t = httpx.post(f"{API}/trips", headers=H, json={
            "customer_id": cust["id"], "product_id": prod["id"],
            "date": "2026-12-01", "vehicle_id": veh["id"],
            "vehicle_number": veh["vehicle_number"], "vehicle_type": "own",
            "tons": 20.0, "loaded_qty": 20.0, "unloaded_qty": 19.85,
            "freight_mode": "per_ton", "rate_per_ton": 1500,
            "product_rate_per_mt": 40000,
        }, timeout=T).json()
        tid = t["id"]
        assert t["applied_customer_shortage_limit"] == 0.3
        inv = httpx.post(f"{API}/invoices", headers=H, json={
            "customer_id": cust["id"], "invoice_date": "2026-12-02",
            "trip_ids": [tid], "hsn_sac": "996791", "gst_treatment": "rcm",
        }, timeout=T).json()
        inv_id = inv["id"]
        pdf = httpx.get(f"{API}/invoices/{inv['id']}/pdf", headers=H, timeout=T).content
        text = _pdf_text(pdf)
        assert "Allowance:" in text
        assert "0.3% of Loaded Qty" in text
        assert "Custom Customer Allowance" in text
        # Method wording for full_after_limit
        assert "Full Shortage after Limit Exceeded" in text
        # Sanity — must NOT print the Product Master label for this trip
        # (it was overridden). The token 'Product Master' should not appear
        # inside the invoice's shortage caption.
        # (Rest of PDF may mention Product elsewhere in T&C — narrow check.)
        assert "0.5% of Loaded Qty · Product Master" not in text
    finally:
        if inv_id:
            httpx.delete(f"{API}/invoices/{inv_id}", headers=H, timeout=T)
        if tid:
            httpx.delete(f"{API}/trips/{tid}?reason=cleanup", headers=H, timeout=T)
        httpx.delete(f"{API}/customers/{cust['id']}", headers=H, timeout=T)
        httpx.delete(f"{API}/vehicles/{veh['id']}", headers=H, timeout=T)
        httpx.delete(f"{API}/products/{prod['id']}", headers=H, timeout=T)


def test_caption_reflects_frozen_snapshot_not_current_master():
    """The caption must render whatever was FROZEN onto the trip, even after
    the master is later changed."""
    _boot()
    tag = uuid.uuid4().hex[:6]
    prod = httpx.post(f"{API}/products", headers=H, json={
        "name": f"IT107_ProdC_{tag}", "default_shortage_allowance_pct": 0.5,
    }, timeout=T).json()
    cust = httpx.post(f"{API}/customers", headers=H, json={
        "name": f"IT107_CustC_{tag}", "state": "AP",
    }, timeout=T).json()
    veh = httpx.post(f"{API}/vehicles", headers=H, json={
        "vehicle_number": f"AP107C{tag[:4].upper()}", "vehicle_type": "own",
    }, timeout=T).json()
    tid = None; inv_id = None
    try:
        t = httpx.post(f"{API}/trips", headers=H, json={
            "customer_id": cust["id"], "product_id": prod["id"],
            "date": "2026-12-01", "vehicle_id": veh["id"],
            "vehicle_number": veh["vehicle_number"], "vehicle_type": "own",
            "tons": 20.0, "loaded_qty": 20.0, "unloaded_qty": 19.85,
            "freight_mode": "per_ton", "rate_per_ton": 1500,
            "product_rate_per_mt": 40000,
        }, timeout=T).json()
        tid = t["id"]
        # Now change the product master → allowance is now 1.5 %
        httpx.put(f"{API}/products/{prod['id']}", headers=H, json={
            **prod, "default_shortage_allowance_pct": 1.5,
        }, timeout=T)
        # Invoice PDF must still show the ORIGINAL 0.5% snapshot
        inv = httpx.post(f"{API}/invoices", headers=H, json={
            "customer_id": cust["id"], "invoice_date": "2026-12-02",
            "trip_ids": [tid], "hsn_sac": "996791", "gst_treatment": "rcm",
        }, timeout=T).json()
        inv_id = inv["id"]
        pdf = httpx.get(f"{API}/invoices/{inv['id']}/pdf", headers=H, timeout=T).content
        text = _pdf_text(pdf)
        assert "0.5% of Loaded Qty" in text, "trip snapshot leaked to current master"
        assert "1.5%" not in text, "current master value must not appear on historical trip"
    finally:
        if inv_id:
            httpx.delete(f"{API}/invoices/{inv_id}", headers=H, timeout=T)
        if tid:
            httpx.delete(f"{API}/trips/{tid}?reason=cleanup", headers=H, timeout=T)
        httpx.delete(f"{API}/customers/{cust['id']}", headers=H, timeout=T)
        httpx.delete(f"{API}/vehicles/{veh['id']}", headers=H, timeout=T)
        httpx.delete(f"{API}/products/{prod['id']}", headers=H, timeout=T)


def test_shortage_amount_still_correct_after_caption_addition():
    """Sanity — the caption change is purely cosmetic; the printed shortage
    amount + net-deductible-MT × rate math still holds paisa-accurate."""
    _boot()
    tag = uuid.uuid4().hex[:6]
    prod = httpx.post(f"{API}/products", headers=H, json={
        "name": f"IT107_ProdD_{tag}", "default_shortage_allowance_pct": 0.5,
    }, timeout=T).json()
    cust = httpx.post(f"{API}/customers", headers=H, json={
        "name": f"IT107_CustD_{tag}", "state": "AP",
    }, timeout=T).json()
    veh = httpx.post(f"{API}/vehicles", headers=H, json={
        "vehicle_number": f"AP107D{tag[:4].upper()}", "vehicle_type": "own",
    }, timeout=T).json()
    tid = None; inv_id = None
    try:
        t = httpx.post(f"{API}/trips", headers=H, json={
            "customer_id": cust["id"], "product_id": prod["id"],
            "date": "2026-12-01", "vehicle_id": veh["id"],
            "vehicle_number": veh["vehicle_number"], "vehicle_type": "own",
            "tons": 20.0, "loaded_qty": 20.0, "unloaded_qty": 19.85,
            "freight_mode": "per_ton", "rate_per_ton": 1500,
            "product_rate_per_mt": 40000,
        }, timeout=T).json()
        tid = t["id"]
        # Product allowance 0.5% of 20 = 0.1 MT. Actual short 0.15. Net = 0.05 × 40k = 2000.
        assert abs(t["shortage_amount"] - 2000.0) < 0.02
        inv = httpx.post(f"{API}/invoices", headers=H, json={
            "customer_id": cust["id"], "invoice_date": "2026-12-02",
            "trip_ids": [tid], "hsn_sac": "996791", "gst_treatment": "rcm",
        }, timeout=T).json()
        inv_id = inv["id"]
        assert abs(float(inv["shortage_total"]) - 2000.0) < 0.02
    finally:
        if inv_id:
            httpx.delete(f"{API}/invoices/{inv_id}", headers=H, timeout=T)
        if tid:
            httpx.delete(f"{API}/trips/{tid}?reason=cleanup", headers=H, timeout=T)
        httpx.delete(f"{API}/customers/{cust['id']}", headers=H, timeout=T)
        httpx.delete(f"{API}/vehicles/{veh['id']}", headers=H, timeout=T)
        httpx.delete(f"{API}/products/{prod['id']}", headers=H, timeout=T)
