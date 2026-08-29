"""Seeds a supplier-vehicle trip for the iter100 supplier-side override regression test."""
import os
import uuid

import httpx

BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
HA = {"Authorization": f"Bearer {os.environ['DEMO_TOKEN_VALUE']}"}
T = 60

httpx.post(f"{BASE}/api/auth/demo-login", timeout=T)
tag = uuid.uuid4().hex[:6]
cust = httpx.post(f"{BASE}/api/customers", headers=HA,
                  json={"name": f"TEST_IT100SUP_{tag}", "state": "AP"}, timeout=T).json()
sup = httpx.post(f"{BASE}/api/suppliers", headers=HA,
                 json={"name": f"TEST_IT100S_{tag}", "state": "AP"}, timeout=T).json()
veh = httpx.post(f"{BASE}/api/vehicles", headers=HA, json={
    "vehicle_number": f"AP100S{tag[:4].upper()}", "vehicle_type": "supplier",
    "supplier_id": sup["id"], "supplier_name": sup["name"]}, timeout=T).json()
trip = httpx.post(f"{BASE}/api/trips", headers=HA, json={
    "customer_id": cust["id"], "date": "2026-09-06",
    "vehicle_id": veh["id"], "vehicle_number": veh["vehicle_number"],
    "vehicle_type": "supplier", "supplier_id": sup["id"], "supplier_name": sup["name"],
    "tons": 20, "loaded_qty": 20, "unloaded_qty": 20,
    "freight_mode": "per_ton", "rate_per_ton": 900,
    "supplier_freight_mode": "per_ton", "supplier_rate_per_ton": 800,
    "supplier_qty": 20,
    "from_location": "Kakinada", "to_location": "Vizag",
}, timeout=T).json()
print("SUP_TRIP_ID=" + trip["id"])
print("supplier_freight=", trip.get("supplier_freight"))
print("supplier_halting_amount=", trip.get("supplier_halting_amount"))
print("field_overrides=", trip.get("field_overrides"))
