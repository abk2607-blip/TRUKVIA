"""
End-to-end multi-company data isolation test.

Creates two companies (A, B) for the same test user, then:
- Creates masters (customer, vehicle, driver, product, party) in each
- Creates a trip + invoice in each
- Verifies that when active company = A, only A's data is visible everywhere.
- Verifies the reverse for B.
- Cleans up all created data at the end.
"""
import requests, sys, json

BASE = "https://trip-billing-pro-1.preview.emergentagent.com/api"
TOKEN = "test_session_bitumen_2026"

def call(method, path, cid=None, **kw):
    h = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
    if cid:
        h["X-Company-Id"] = cid
    r = requests.request(method, f"{BASE}{path}", headers=h, **kw)
    return r

def json_or_die(r, label):
    if r.status_code >= 300:
        print(f"[FAIL] {label}: {r.status_code} {r.text[:400]}")
        sys.exit(1)
    return r.json()

# ---- Setup 2 companies ----
print("=== Creating Company A ===")
coA = json_or_die(call("POST", "/companies", json={"name": "ISO-TEST-A", "state": "Andhra Pradesh", "gst_in": ""}), "co A")
cidA = coA.get("id")
print(f"  Company A id = {cidA}")

print("=== Creating Company B ===")
coB = json_or_die(call("POST", "/companies", json={"name": "ISO-TEST-B", "state": "Telangana", "gst_in": ""}), "co B")
cidB = coB.get("id")
print(f"  Company B id = {cidB}")

# ---- Create masters in Company A ----
print("\n=== Seed masters in Company A ===")
custA = json_or_die(call("POST", "/customers", cid=cidA, json={"name": "CustA-ISO", "state": "Andhra Pradesh"}), "custA")
vehA  = json_or_die(call("POST", "/vehicles", cid=cidA, json={"vehicle_number": "AP01ISO0001", "ownership": "own"}), "vehA")
drvA  = json_or_die(call("POST", "/drivers", cid=cidA, json={"name": "DrvA-ISO", "phone": "9990000001"}), "drvA")
prdA  = json_or_die(call("POST", "/products", cid=cidA, json={"name": "ProdA-ISO", "hsn_sac": "996511"}), "prdA")
ptyA  = json_or_die(call("POST", "/parties", cid=cidA, json={"name": "PtyA-ISO", "party_type": "consignor"}), "ptyA")

# ---- Create masters in Company B ----
print("=== Seed masters in Company B ===")
custB = json_or_die(call("POST", "/customers", cid=cidB, json={"name": "CustB-ISO", "state": "Telangana"}), "custB")
vehB  = json_or_die(call("POST", "/vehicles", cid=cidB, json={"vehicle_number": "TS01ISO0002", "ownership": "own"}), "vehB")
drvB  = json_or_die(call("POST", "/drivers", cid=cidB, json={"name": "DrvB-ISO", "phone": "9990000002"}), "drvB")
prdB  = json_or_die(call("POST", "/products", cid=cidB, json={"name": "ProdB-ISO", "hsn_sac": "996791"}), "prdB")
ptyB  = json_or_die(call("POST", "/parties", cid=cidB, json={"name": "PtyB-ISO", "party_type": "consignee"}), "ptyB")

# ---- ISOLATION CHECK: switch to A, must NOT see B's masters ----
print("\n=== Isolation check: active=A ===")
def names(items):
    return sorted([x.get("name") or x.get("vehicle_number") for x in items])
listA_c = json_or_die(call("GET", "/customers", cid=cidA), "listA c")
listA_v = json_or_die(call("GET", "/vehicles", cid=cidA), "listA v")
listA_d = json_or_die(call("GET", "/drivers", cid=cidA), "listA d")
listA_p = json_or_die(call("GET", "/products", cid=cidA), "listA p")
listA_pa = json_or_die(call("GET", "/parties", cid=cidA), "listA pa")

failures = []
def check_only_in(items, wanted_names, forbidden_names, label):
    n = names(items)
    for w in wanted_names:
        if w not in n:
            failures.append(f"{label}: expected '{w}' but got {n}")
    for f in forbidden_names:
        if f in n:
            failures.append(f"{label}: LEAKED '{f}' from other company; got {n}")

check_only_in(listA_c, ["CustA-ISO"], ["CustB-ISO"], "A customers")
check_only_in(listA_v, ["AP01ISO0001"], ["TS01ISO0002"], "A vehicles")
check_only_in(listA_d, ["DrvA-ISO"], ["DrvB-ISO"], "A drivers")
check_only_in(listA_p, ["ProdA-ISO"], ["ProdB-ISO"], "A products")
check_only_in(listA_pa, ["PtyA-ISO"], ["PtyB-ISO"], "A parties")

print("\n=== Isolation check: active=B ===")
listB_c = json_or_die(call("GET", "/customers", cid=cidB), "listB c")
listB_v = json_or_die(call("GET", "/vehicles", cid=cidB), "listB v")
listB_d = json_or_die(call("GET", "/drivers", cid=cidB), "listB d")
listB_p = json_or_die(call("GET", "/products", cid=cidB), "listB p")
listB_pa = json_or_die(call("GET", "/parties", cid=cidB), "listB pa")
check_only_in(listB_c, ["CustB-ISO"], ["CustA-ISO"], "B customers")
check_only_in(listB_v, ["TS01ISO0002"], ["AP01ISO0001"], "B vehicles")
check_only_in(listB_d, ["DrvB-ISO"], ["DrvA-ISO"], "B drivers")
check_only_in(listB_p, ["ProdB-ISO"], ["ProdA-ISO"], "B products")
check_only_in(listB_pa, ["PtyB-ISO"], ["PtyA-ISO"], "B parties")

# ---- Trip + Invoice per company ----
print("\n=== Trip + Invoice in each company ===")
tripA_body = {
  "date": "2026-02-11", "trip_no": "ISO-A-1",
  "customer_id": custA["id"], "vehicle_number": "AP01ISO0001", "driver_id": drvA["id"],
  "tons": 10, "freight_mode": "per_ton", "rate_per_ton": 1000,
  "load_details": "Bitumen VG 40",
}
trA = json_or_die(call("POST", "/trips", cid=cidA, json=tripA_body), "tripA")
tripB_body = {
  "date": "2026-02-11", "trip_no": "ISO-B-1",
  "customer_id": custB["id"], "vehicle_number": "TS01ISO0002", "driver_id": drvB["id"],
  "tons": 5, "freight_mode": "per_ton", "rate_per_ton": 2000,
  "load_details": "Bitumen VG 40",
}
trB = json_or_die(call("POST", "/trips", cid=cidB, json=tripB_body), "tripB")

invA = json_or_die(call("POST", "/invoices", cid=cidA, json={"date": "2026-02-11", "customer_id": custA["id"], "trip_ids": [trA["id"]]}), "invA")
invB = json_or_die(call("POST", "/invoices", cid=cidB, json={"date": "2026-02-11", "customer_id": custB["id"], "trip_ids": [trB["id"]]}), "invB")

print(f"  Trip A freight = {trA.get('freight_amount')}  invoice = {invA.get('invoice_number')} total = {invA.get('total_amount')}")
print(f"  Trip B freight = {trB.get('freight_amount')}  invoice = {invB.get('invoice_number')} total = {invB.get('total_amount')}")

# List trips per company
listA_t = json_or_die(call("GET", "/trips", cid=cidA), "listA t")
listB_t = json_or_die(call("GET", "/trips", cid=cidB), "listB t")
a_trip_nos = [t.get("trip_no") for t in listA_t]
b_trip_nos = [t.get("trip_no") for t in listB_t]
if "ISO-B-1" in a_trip_nos: failures.append(f"A trips LEAKED ISO-B-1: {a_trip_nos}")
if "ISO-A-1" in b_trip_nos: failures.append(f"B trips LEAKED ISO-A-1: {b_trip_nos}")

# Dashboard
dashA = json_or_die(call("GET", "/dashboard", cid=cidA), "dashA")
dashB = json_or_die(call("GET", "/dashboard", cid=cidB), "dashB")
print(f"\n  Dashboard A: revenue={dashA['total_revenue']}, trips={dashA['trip_count']}, customers={dashA['customer_count']}")
print(f"  Dashboard B: revenue={dashB['total_revenue']}, trips={dashB['trip_count']}, customers={dashB['customer_count']}")
if dashA["total_revenue"] != 10*1000: failures.append(f"Dashboard A revenue wrong: {dashA['total_revenue']} (expected 10000)")
if dashB["total_revenue"] != 5*2000:  failures.append(f"Dashboard B revenue wrong: {dashB['total_revenue']} (expected 10000)")

# Reports GST summary
gstA = json_or_die(call("GET", "/reports/gst-summary", cid=cidA), "gstA")
gstB = json_or_die(call("GET", "/reports/gst-summary", cid=cidB), "gstB")
print(f"  GST A fy invoices={gstA['current_fy']['invoices']}, taxable={gstA['current_fy']['taxable']}")
print(f"  GST B fy invoices={gstB['current_fy']['invoices']}, taxable={gstB['current_fy']['taxable']}")

# ---- Cleanup ----
print("\n=== Cleanup ===")
call("DELETE", f"/invoices/{invA['id']}", cid=cidA, params={"reason": "test cleanup"})
call("DELETE", f"/invoices/{invB['id']}", cid=cidB, params={"reason": "test cleanup"})
call("DELETE", f"/trips/{trA['id']}", cid=cidA, params={"reason": "test cleanup"})
call("DELETE", f"/trips/{trB['id']}", cid=cidB, params={"reason": "test cleanup"})
for m,cid in [(custA,cidA),(vehA,cidA),(drvA,cidA),(prdA,cidA),(ptyA,cidA),(custB,cidB),(vehB,cidB),(drvB,cidB),(prdB,cidB),(ptyB,cidB)]:
    mid = m.get("id")
    for path in ("customers","vehicles","drivers","products","parties"):
        r = call("DELETE", f"/{path}/{mid}", cid=cid)
        if r.status_code == 200:
            break
call("DELETE", f"/companies/{cidA}")
call("DELETE", f"/companies/{cidB}")

print("\n" + "="*40)
if failures:
    print(f"FAILURES ({len(failures)}):")
    for f in failures: print(" -", f)
    sys.exit(1)
else:
    print("ALL PASS — Multi-company data isolation verified")
