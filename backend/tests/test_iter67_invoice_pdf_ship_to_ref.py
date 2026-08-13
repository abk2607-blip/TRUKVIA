"""Iter67 · Invoice Enhancement Phase D — Invoice PDF redesign.

Verifies:
 - Invoice PDF returns %PDF for supplier vehicle trips (regression sanity)
 - Same-site trips render (no exception)
 - Mixed-site trips render (no exception)
 - Customer Ref No stays blank per-trip when not set (no inheritance)
 - Invoice endpoints still return the trips' data cleanly
"""
import os, uuid, pytest, httpx
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

BASE = os.environ.get("BACKEND_URL_INTERNAL", "http://localhost:8001")
TOKEN = "test_session_bitumen_2026"
HDR = {"Authorization": f"Bearer {TOKEN}"}
UNIQUE = f"IT67_{uuid.uuid4().hex[:6]}"


def _companies():
    return httpx.get(f"{BASE}/api/companies", headers=HDR, timeout=60).json()


def _h(cid=None):
    return {**HDR, "X-Company-Id": cid or _companies()[0]["id"]}


@pytest.fixture(scope="module")
def env():
    cs = _companies()
    ha = _h(cs[0]["id"])
    cust = httpx.post(f"{BASE}/api/customers", headers=ha, json={
        "name": f"IT67_C_{UNIQUE}", "phone": "9110000067", "state": "Andhra Pradesh",
        "gstin": "37ABCDE1234F1Z5", "pincode": "521228",
    }, timeout=60).json()
    veh = httpx.post(f"{BASE}/api/vehicles", headers=ha, json={
        "vehicle_number": f"AP67A{UNIQUE[:5]}", "vehicle_type": "own",
    }, timeout=60).json()
    site_a = httpx.post(f"{BASE}/api/customers/{cust['id']}/ship-sites", headers=ha, json={
        "site_name": "Vijayawada Plant", "address": "NH-16 Kondapalli",
        "state": "Andhra Pradesh", "pincode": "521228",
    }, timeout=60).json()
    site_b = httpx.post(f"{BASE}/api/customers/{cust['id']}/ship-sites", headers=ha, json={
        "site_name": "Guntur Depot", "address": "NH-16 Guntur",
        "state": "Andhra Pradesh", "pincode": "522004",
    }, timeout=60).json()
    return {"ha": ha, "cust": cust, "veh": veh, "site_a": site_a, "site_b": site_b}


def _mk_trip(env, site_id="", ref="", **overrides):
    payload = {
        "customer_id": env["cust"]["id"], "date": overrides.get("date", "2026-08-01"),
        "vehicle_id": env["veh"]["id"], "vehicle_number": env["veh"]["vehicle_number"],
        "tons": 20, "freight_mode": "per_ton", "rate_per_ton": 1500,
        "from_location": "K", "to_location": "V",
        "ship_site_id": site_id,
        "customer_reference_number": ref,
    }
    payload.update(overrides)
    return httpx.post(f"{BASE}/api/trips", headers=env["ha"], json=payload, timeout=60).json()


def _mk_invoice(env, trip_ids, inv_date="2026-08-05"):
    r = httpx.post(f"{BASE}/api/invoices", headers=env["ha"], json={
        "customer_id": env["cust"]["id"],
        "trip_ids": trip_ids,
        "date": inv_date,
        "due_date": "2026-08-25",
    }, timeout=60)
    assert r.status_code == 200, r.text
    return r.json()


def _extract_pdf_text(content: bytes) -> str:
    from pypdf import PdfReader
    from io import BytesIO
    import re
    reader = PdfReader(BytesIO(content))
    raw = "\n".join(p.extract_text() or "" for p in reader.pages)
    # Collapse all whitespace (including PDF-inserted line breaks in wrapped
    # text) so multi-word tokens like "Vijayawada Plant" match reliably.
    return re.sub(r"\s+", " ", raw)


def test_invoice_pdf_same_ship_site_renders(env):
    """All trips share the same site → single SHIP TO block."""
    t1 = _mk_trip(env, site_id=env["site_a"]["id"], ref="CUS-INV-A1", date="2026-08-01")
    t2 = _mk_trip(env, site_id=env["site_a"]["id"], ref="CUS-INV-A2", date="2026-08-02")
    inv = _mk_invoice(env, [t1["id"], t2["id"]])
    r = httpx.get(f"{BASE}/api/invoices/{inv['id']}/pdf", headers=env["ha"], timeout=60)
    assert r.status_code == 200
    assert r.content[:4] == b"%PDF"
    text = _extract_pdf_text(r.content)
    assert "SHIP TO" in text
    assert "BILL TO" in text
    assert "CUS-INV-A1" in text
    assert "CUS-INV-A2" in text
    assert "Vijayawada Plant" in text
    assert "Mixed" not in text


def test_invoice_pdf_mixed_ship_sites_renders(env):
    """Trips have different sites → 'Mixed' header + per-trip Ship-To lines."""
    t1 = _mk_trip(env, site_id=env["site_a"]["id"], ref="MIX-REF-1", date="2026-08-10")
    t2 = _mk_trip(env, site_id=env["site_b"]["id"], ref="MIX-REF-2", date="2026-08-11")
    inv = _mk_invoice(env, [t1["id"], t2["id"]], inv_date="2026-08-12")
    r = httpx.get(f"{BASE}/api/invoices/{inv['id']}/pdf", headers=env["ha"], timeout=60)
    assert r.status_code == 200
    assert r.content[:4] == b"%PDF"
    text = _extract_pdf_text(r.content)
    assert "Mixed" in text
    assert "MIX-REF-1" in text
    assert "MIX-REF-2" in text
    # Both site names visible per-trip
    assert "Vijayawada Plant" in text
    assert "Guntur Depot" in text


def test_invoice_pdf_customer_ref_blank_no_inheritance(env):
    """One trip has ref, another blank — ref must not leak across trips."""
    t1 = _mk_trip(env, site_id=env["site_a"]["id"], ref="ONLY-T1-REF", date="2026-08-20")
    t2 = _mk_trip(env, site_id=env["site_a"]["id"], ref="", date="2026-08-21")
    fresh_t2 = httpx.get(f"{BASE}/api/trips/{t2['id']}", headers=env["ha"], timeout=60).json()
    assert fresh_t2["customer_reference_number"] == ""
    inv = _mk_invoice(env, [t1["id"], t2["id"]], inv_date="2026-08-22")
    r = httpx.get(f"{BASE}/api/invoices/{inv['id']}/pdf", headers=env["ha"], timeout=60)
    assert r.status_code == 200
    assert r.content[:4] == b"%PDF"
    text = _extract_pdf_text(r.content)
    # ONLY-T1-REF should appear exactly ONCE — never inherited by t2
    assert text.count("ONLY-T1-REF") == 1


def test_invoice_pdf_no_ship_site_uses_fallback(env):
    """Trip without ship_site_id falls back to to_location (still renders)."""
    t = _mk_trip(env, site_id="", ref="", date="2026-08-25", to_location="Kadapa Junction")
    inv = _mk_invoice(env, [t["id"]], inv_date="2026-08-26")
    r = httpx.get(f"{BASE}/api/invoices/{inv['id']}/pdf", headers=env["ha"], timeout=60)
    assert r.status_code == 200
    assert r.content[:4] == b"%PDF"
    text = _extract_pdf_text(r.content)
    assert "Kadapa Junction" in text
    assert "SHIP TO" in text
