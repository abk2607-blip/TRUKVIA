import requests, sys, time
API = "https://trip-billing-pro-1.preview.emergentagent.com"
H = {"Authorization": "Bearer test_session_bitumen_2026", "Content-Type": "application/json"}
requests.post(f"{API}/api/auth/demo-login", timeout=30)
cid = requests.get(f"{API}/api/companies", headers=H, timeout=30).json()[0]["id"]
H["X-Company-Id"] = cid
# find first supplier that has trips
trips = requests.get(f"{API}/api/trips?limit=1000&vehicle_type=supplier", headers=H, timeout=45).json()
if isinstance(trips, dict): trips = trips.get("items") or trips.get("trips") or []
sn = ""
for t in trips:
    if t.get("supplier_name","").startswith("PEDDINTI"):
        sn = t["supplier_name"]; break
if not sn:
    for t in trips:
        if t.get("supplier_name"): sn = t["supplier_name"]; break
print("SUPPLIER:", sn)
r = requests.get(f"{API}/api/reports/supplier-statement.pdf",
                 params={"supplier_name": sn, "start":"2026-08-01", "end":"2026-08-25"},
                 headers=H, timeout=60)
print("status:", r.status_code, "bytes:", len(r.content))
if r.status_code == 200:
    with open("/app/tmp/it94_final.pdf", "wb") as f: f.write(r.content)
