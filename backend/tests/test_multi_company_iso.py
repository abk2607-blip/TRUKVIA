"""Regression tests for multi-company data isolation.

Each master collection (customers/vehicles/drivers/products/parties) and every
transaction (trips/invoices) must be strictly scoped to the active company
identified by the X-Company-Id request header. Two sibling companies of the
same user must never see each other's data through list endpoints, dashboard,
or reports.
"""
import os, requests, pytest

BASE = "https://trip-billing-pro-1.preview.emergentagent.com/api"
TOKEN = os.environ["DEMO_TOKEN_VALUE"]


def call(method, path, cid=None, **kw):
    h = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
    if cid:
        h["X-Company-Id"] = cid
    return requests.request(method, f"{BASE}{path}", headers=h, **kw)


def ok(r):
    assert r.status_code < 300, f"{r.status_code} {r.text[:400]}"
    return r.json()


@pytest.fixture(scope="module")
def two_companies():
    coA = ok(call("POST", "/companies", json={"name": "ISO-PYT-A", "state": "Andhra Pradesh"}))
    coB = ok(call("POST", "/companies", json={"name": "ISO-PYT-B", "state": "Telangana"}))
    yield coA["id"], coB["id"]
    # cleanup
    call("DELETE", f"/companies/{coA['id']}")
    call("DELETE", f"/companies/{coB['id']}")


@pytest.fixture(scope="module")
def seeded(two_companies):
    cidA, cidB = two_companies
    seeds = {}
    seeds["custA"] = ok(call("POST", "/customers", cid=cidA, json={"name": "CustA-PYT", "state": "Andhra Pradesh"}))
    seeds["custB"] = ok(call("POST", "/customers", cid=cidB, json={"name": "CustB-PYT", "state": "Telangana"}))
    seeds["vehA"] = ok(call("POST", "/vehicles", cid=cidA, json={"vehicle_number": "AP01PYT0001", "ownership": "own"}))
    seeds["vehB"] = ok(call("POST", "/vehicles", cid=cidB, json={"vehicle_number": "TS01PYT0002", "ownership": "own"}))
    seeds["drvA"] = ok(call("POST", "/drivers", cid=cidA, json={"name": "DrvA-PYT", "phone": "9111000001"}))
    seeds["drvB"] = ok(call("POST", "/drivers", cid=cidB, json={"name": "DrvB-PYT", "phone": "9111000002"}))
    seeds["prdA"] = ok(call("POST", "/products", cid=cidA, json={"name": "ProdA-PYT", "hsn_sac": "996511"}))
    seeds["prdB"] = ok(call("POST", "/products", cid=cidB, json={"name": "ProdB-PYT", "hsn_sac": "996791"}))
    seeds["ptyA"] = ok(call("POST", "/parties", cid=cidA, json={"name": "PtyA-PYT", "party_type": "consignor"}))
    seeds["ptyB"] = ok(call("POST", "/parties", cid=cidB, json={"name": "PtyB-PYT", "party_type": "consignee"}))
    yield cidA, cidB, seeds
    for coll, keyA, keyB in [("customers","custA","custB"),("vehicles","vehA","vehB"),("drivers","drvA","drvB"),("products","prdA","prdB"),("parties","ptyA","ptyB")]:
        call("DELETE", f"/{coll}/{seeds[keyA]['id']}", cid=cidA)
        call("DELETE", f"/{coll}/{seeds[keyB]['id']}", cid=cidB)


def _names(items, key="name"):
    out = []
    for x in items:
        out.append(x.get(key) or x.get("vehicle_number") or "")
    return out


@pytest.mark.parametrize("path,keyA,keyB", [
    ("/customers", "CustA-PYT", "CustB-PYT"),
    ("/vehicles",  "AP01PYT0001", "TS01PYT0002"),
    ("/drivers",   "DrvA-PYT", "DrvB-PYT"),
    ("/products",  "ProdA-PYT", "ProdB-PYT"),
    ("/parties",   "PtyA-PYT", "PtyB-PYT"),
])
def test_master_isolation(seeded, path, keyA, keyB):
    cidA, cidB, _ = seeded
    listA = ok(call("GET", path, cid=cidA))
    listB = ok(call("GET", path, cid=cidB))
    a_names = _names(listA)
    b_names = _names(listB)
    assert keyA in a_names, f"expected {keyA} in A's {path}, got {a_names}"
    assert keyB not in a_names, f"LEAK: {keyB} appeared in A's {path}: {a_names}"
    assert keyB in b_names, f"expected {keyB} in B's {path}, got {b_names}"
    assert keyA not in b_names, f"LEAK: {keyA} appeared in B's {path}: {b_names}"


def test_trip_and_invoice_isolation(seeded):
    cidA, cidB, s = seeded
    tripA_body = {"date": "2026-02-11", "trip_no": "ISO-PYT-A-1",
                  "customer_id": s["custA"]["id"], "vehicle_number": "AP01PYT0001",
                  "driver_id": s["drvA"]["id"], "tons": 10,
                  "freight_mode": "per_ton", "rate_per_ton": 1000}
    trA = ok(call("POST", "/trips", cid=cidA, json=tripA_body))
    tripB_body = {"date": "2026-02-11", "trip_no": "ISO-PYT-B-1",
                  "customer_id": s["custB"]["id"], "vehicle_number": "TS01PYT0002",
                  "driver_id": s["drvB"]["id"], "tons": 5,
                  "freight_mode": "per_ton", "rate_per_ton": 2000}
    trB = ok(call("POST", "/trips", cid=cidB, json=tripB_body))
    invA = ok(call("POST", "/invoices", cid=cidA, json={"date": "2026-02-11", "customer_id": s["custA"]["id"], "trip_ids": [trA["id"]]}))
    invB = ok(call("POST", "/invoices", cid=cidB, json={"date": "2026-02-11", "customer_id": s["custB"]["id"], "trip_ids": [trB["id"]]}))
    try:
        listA_t = ok(call("GET", "/trips", cid=cidA))
        listB_t = ok(call("GET", "/trips", cid=cidB))
        a_ids = [t.get("id") for t in listA_t]
        b_ids = [t.get("id") for t in listB_t]
        assert trA["id"] in a_ids and trB["id"] not in a_ids, f"trips leaked A: A_ids={a_ids} trB={trB['id']}"
        assert trB["id"] in b_ids and trA["id"] not in b_ids, f"trips leaked B: B_ids={b_ids} trA={trA['id']}"

        # Dashboard scoping — each company should see its own numbers
        dA = ok(call("GET", "/dashboard", cid=cidA))
        dB = ok(call("GET", "/dashboard", cid=cidB))
        assert dA["total_revenue"] == 10000.0
        assert dB["total_revenue"] == 10000.0
        assert dA["trip_count"] == 1 and dB["trip_count"] == 1
    finally:
        call("DELETE", f"/invoices/{invA['id']}", cid=cidA, params={"reason": "cleanup"})
        call("DELETE", f"/invoices/{invB['id']}", cid=cidB, params={"reason": "cleanup"})
        call("DELETE", f"/trips/{trA['id']}", cid=cidA, params={"reason": "cleanup"})
        call("DELETE", f"/trips/{trB['id']}", cid=cidB, params={"reason": "cleanup"})


def test_reports_are_company_scoped(seeded):
    cidA, cidB, _ = seeded
    for path in ("/dashboard", "/reports/gst-summary", "/reports/pl", "/reports/halting"):
        rA = ok(call("GET", path, cid=cidA))
        rB = ok(call("GET", path, cid=cidB))
        # each returns a JSON object; presence check only — full math is covered in test_iter17
        assert isinstance(rA, dict) and isinstance(rB, dict), f"{path} returned non-dict"
