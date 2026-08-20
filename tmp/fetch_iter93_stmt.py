"""Iter93 — Seed a demo supplier with 3 trips + payment, then fetch the PDF for visual verification."""
import requests, time

API = "https://trip-billing-pro-1.preview.emergentagent.com"
H = {"Authorization": "Bearer test_session_bitumen_2026", "Content-Type": "application/json"}

requests.post(f"{API}/api/auth/demo-login", timeout=15)
cid = requests.get(f"{API}/api/companies", headers=H, timeout=15).json()[0]["id"]
H["X-Company-Id"] = cid

# Configure the company master so the header shows a full address block
requests.put(f"{API}/api/companies/{cid}", headers=H, json={
    "name": "A. Kishore Babu & Sons",
    "address": "D.No: 12-34/A, Beside HP Petrol Bunk, Governorpet, Vijayawada - 520 002, Andhra Pradesh",
    "phone": "+91 98494 22411",
    "email": "office@akbsonstransport.in",
    "gstin": "37ABCDE1234F1Z5",
    "pan": "ABCDE1234F",
}, timeout=15)

tag = str(int(time.time()))[-4:]
prod = requests.post(f"{API}/api/products", headers=H, json={"name": "VG-40"}).json()
prod_id = prod.get("id") or requests.get(f"{API}/api/products", headers=H).json()[0]["id"]

# Fetch a customer
custs = requests.get(f"{API}/api/customers?limit=5", headers=H).json()["items"]
if len(custs) < 2:
    for i, cn in enumerate(["Kalpataru Infra Projects Ltd", "IRCON Highways (JV)"]):
        requests.post(f"{API}/api/customers", headers=H, json={
            "name": cn, "phone": f"9876543{200+i:03d}",
            "address": "Hyderabad", "state": "Telangana",
        })
    custs = requests.get(f"{API}/api/customers?limit=5", headers=H).json()["items"]

sup = requests.post(f"{API}/api/suppliers", headers=H, json={
    "name": f"PEDDINTI SRINU-{tag}",
    "mobile": "9849422411",
    "opening_balance": 0,
    "opening_balance_type": "payable",
}).json()
sid = sup["id"]

veh = requests.post(f"{API}/api/vehicles", headers=H, json={
    "vehicle_number": f"AP16TE{tag}",
    "vehicle_type": "supplier", "supplier_id": sid,
    "supplier_name": sup["name"],
    "supplier_mobile": "9849422411",
}).json()
vid = veh["id"]

trip_specs = [
    {"date": "2026-08-05", "from": "IOCL Chennai Refinery", "to": "NHAI Package-4 Site, Bapatla",  "cust": 0,
     "tons": 28.900, "unl": 28.550, "rate": 1400, "sup_rate": 1200, "kms": 1580, "adv": 40000, "diesel": 12000, "shortage": 4000, "halt": 4500},
    {"date": "2026-08-10", "from": "HPCL Vishakhapatnam",  "to": "Kalpataru Bypass Road, Guntur",  "cust": 1,
     "tons": 28.860, "unl": 28.750, "rate": 1350, "sup_rate": 1150, "kms": 1220, "adv": 60000, "diesel": 14000, "shortage": 2200, "halt": 6000},
    {"date": "2026-08-15", "from": "IOCL Chennai Refinery", "to": "Vijayawada Ring Road Site — VIL-11 Bapatla-Ongole", "cust": 0,
     "tons": 27.500, "unl": 27.200, "rate": 1450, "sup_rate": 1220, "kms": 1620, "adv": 70000, "diesel": 14600, "shortage": 25400, "halt": 13500},
]
created_ids = []
for spec in trip_specs:
    body = {
        "date": spec["date"], "loading_date": spec["date"],
        "unloading_date": spec["date"],
        "vehicle_number": veh["vehicle_number"], "vehicle_type": "supplier",
        "supplier_id": sid, "vehicle_id": vid,
        "customer_id": custs[spec["cust"]]["id"], "product_id": prod_id,
        "load_details": "Bitumen VG-40",
        "tons": spec["tons"], "loaded_qty": spec["tons"], "unloaded_qty": spec["unl"],
        "freight_mode": "per_ton", "rate_per_ton": spec["rate"],
        "supplier_freight_mode": "per_ton", "supplier_rate_per_ton": spec["sup_rate"],
        "supplier_round_trip_kms": spec["kms"],
        "from_location": spec["from"], "to_location": spec["to"],
        "supplier_advance": spec["adv"], "supplier_diesel": spec["diesel"],
        "supplier_shortage_deduction": spec["shortage"],
        "supplier_halting_amount": spec["halt"],
        "supplier_halting_days": 3, "supplier_halting_rate_per_day": spec["halt"] / 3,
    }
    r = requests.post(f"{API}/api/trips", headers=H, json=body, timeout=20)
    if r.status_code != 200:
        print(f"trip {spec['date']} FAIL {r.status_code}: {r.text[:200]}"); continue
    created_ids.append(r.json()["id"])
print("Created trips:", created_ids)

# One payment out for a partial settlement
requests.post(f"{API}/api/supplier-payments", headers=H, json={
    "supplier_id": sid, "date": "2026-08-19", "amount": 50000,
    "mode": "NEFT", "type": "payment_out", "against": "trip",
    "ref_no": "NEFT-08192026-4471", "remarks": "Part settlement",
    "trip_id": created_ids[0] if created_ids else "",
}, timeout=15)

# Fetch the PDF
r = requests.get(f"{API}/api/reports/supplier-statement.pdf",
                 params={"supplier_name": sup["name"], "start": "2026-08-01", "end": "2026-08-25"},
                 headers=H, timeout=60)
print("PDF status:", r.status_code, "bytes:", len(r.content))
if r.status_code == 200:
    with open("/app/tmp/it93_supplier_stmt.pdf", "wb") as f: f.write(r.content)
    print("SAVED /app/tmp/it93_supplier_stmt.pdf")
else:
    print("BODY", r.text[:300])
