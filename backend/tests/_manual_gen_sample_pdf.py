"""Generate a sample invoice PDF matching the user's reported case for visual QA."""
import os
import requests, sys
BASE = "https://trip-billing-pro-1.preview.emergentagent.com/api"
H = {"Authorization": f"Bearer {os.environ['DEMO_TOKEN_VALUE']}", "Content-Type": "application/json"}

def ok(r, l):
    if r.status_code >= 300:
        print(l, r.status_code, r.text[:300])
        sys.exit(1)
    return r.json()

cur = ok(requests.get(f"{BASE}/company", headers=H), "co")
cur["udyam_registration"] = "UDYAM-AP-01-0012345"
cur["bank_name"] = "State Bank of India"
cur["account_number"] = "00012345678"
cur["ifsc"] = "SBIN0001234"
cur["branch"] = "Vijayawada"
ok(requests.put(f"{BASE}/company", headers=H, json=cur), "put co")

c = ok(requests.post(f"{BASE}/customers", headers=H, json={"name": "Sample Cust", "state": "Andhra Pradesh", "gstin": "37ABCDE1234F1Z5", "address": "Vijayawada, AP", "phone": "9999912345"}), "c")
v = ok(requests.post(f"{BASE}/vehicles", headers=H, json={"vehicle_number": "AP39UK5117", "ownership": "own"}), "v")
d = ok(requests.post(f"{BASE}/drivers", headers=H, json={"name": "Sample Driver", "phone": "9111000000"}), "d")

trip_body = {
    "date": "2026-07-31", "trip_no": "SMP-1", "customer_id": c["id"],
    "vehicle_number": "AP39UK5117", "driver_id": d["id"],
    "load_details": "BITUMEN VG 30", "from_location": "CHENNAI", "to_location": "MEDAK",
    "freight_mode": "fixed", "round_trip_kms": 1650, "rate_per_km_per_ton": 2.45,
    "tons": 32.53, "fixed_amount": 131502.53,
    "product_rate_per_mt": 82000,
    "expenses": {},
    "halting_rate_per_day": 3000, "total_halting_days": 0, "chargeable_halting_days": 0,
}
t = ok(requests.post(f"{BASE}/trips", headers=H, json=trip_body), "t")
inv = ok(requests.post(f"{BASE}/invoices", headers=H, json={"date": "2026-07-31", "customer_id": c["id"], "trip_ids": [t["id"]]}), "inv")
pdf = requests.get(f"{BASE}/invoices/{inv['id']}/pdf", headers=H)
print("PDF", pdf.status_code, len(pdf.content))
open("/tmp/sample_new_invoice.pdf", "wb").write(pdf.content)

requests.delete(f"{BASE}/invoices/{inv['id']}", headers=H, params={"reason": "smoke"})
requests.delete(f"{BASE}/trips/{t['id']}", headers=H, params={"reason": "smoke"})
requests.delete(f"{BASE}/customers/{c['id']}", headers=H)
requests.delete(f"{BASE}/vehicles/{v['id']}", headers=H)
requests.delete(f"{BASE}/drivers/{d['id']}", headers=H)
