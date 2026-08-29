"""Seeds a trip for the iter100 frontend override-dialog test and prints its id."""
import os
import uuid

import httpx

BASE = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
HA = {"Authorization": f"Bearer {os.environ['DEMO_TOKEN_VALUE']}"}
T = 60

httpx.post(f"{BASE}/api/auth/demo-login", timeout=T)
tag = uuid.uuid4().hex[:6]
cust = httpx.post(f"{BASE}/api/customers", headers=HA,
                  json={"name": f"TEST_IT100FE_{tag}", "state": "AP"}, timeout=T).json()
veh = httpx.post(f"{BASE}/api/vehicles", headers=HA,
                 json={"vehicle_number": f"AP100E{tag[:4].upper()}", "vehicle_type": "own"},
                 timeout=T).json()
trip = httpx.post(f"{BASE}/api/trips", headers=HA, json={
    "customer_id": cust["id"], "date": "2026-09-05",
    "vehicle_id": veh["id"], "vehicle_number": veh["vehicle_number"],
    "tons": 20, "loaded_qty": 20, "unloaded_qty": 19,
    "freight_mode": "per_ton", "rate_per_ton": 900,
    "product_rate_per_mt": 40000,
    "from_location": "Kakinada", "to_location": "Vizag",
    "loading_date": "2026-09-05", "unloading_date": "2026-09-12",
    "grace_days": 2, "halting_rate_per_day": 1000,
}, timeout=T).json()
print("TRIP_ID=" + trip["id"])
print("shortage_amount=", trip.get("shortage_amount"))
print("halting_amount=", trip.get("halting_amount"))
print("field_overrides=", trip.get("field_overrides"))
