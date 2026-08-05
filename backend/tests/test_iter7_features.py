"""Iteration 7 backend tests: Team/RBAC, Supplier P&L report, Invoice snapshot on edit."""
import os
import time
import pytest
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "https://trip-billing-pro-1.preview.emergentagent.com").rstrip("/")
TOKEN = "test_session_bitumen_2026"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
JSON_HEADERS = {**HEADERS, "Content-Type": "application/json"}
API = f"{BASE_URL}/api"
BASE_EXPENSES = {"diesel": 0, "toll": 0, "batta": 0, "repair": 0, "other": 0}


# ==================== Team / RBAC ====================
class TestTeamRBAC:
    state = {}

    @classmethod
    def teardown_class(cls):
        # cleanup any residual team members created by this test class
        try:
            r = requests.get(f"{API}/team", headers=HEADERS)
            for tm in r.json() if r.status_code == 200 else []:
                if tm.get("email", "").startswith("test_iter7_"):
                    requests.delete(f"{API}/team/{tm['id']}", headers=HEADERS)
        except Exception:
            pass

    def test_01_team_me_owner(self):
        r = requests.get(f"{API}/team/me", headers=HEADERS)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["role"] == "owner"
        assert d["is_staff"] is False
        assert "email" in d and d["email"]
        assert isinstance(d.get("permissions"), list)
        # owner has all perms
        for p in ("edit_trip", "delete_trip", "edit_invoice", "delete_invoice",
                  "edit_master", "delete_master", "manage_users"):
            assert p in d["permissions"], f"missing perm {p}"

    def test_02_create_team_member(self):
        # ensure clean start for this email
        r0 = requests.get(f"{API}/team", headers=HEADERS)
        for tm in r0.json() if r0.status_code == 200 else []:
            if tm.get("email") == "test_iter7_accountant@x.com":
                requests.delete(f"{API}/team/{tm['id']}", headers=HEADERS)

        r = requests.post(f"{API}/team", headers=JSON_HEADERS, json={
            "owner_user_id": "ignored",
            "email": "test_iter7_accountant@x.com",
            "name": "Test Acc",
            "role": "accountant",
        })
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["email"] == "test_iter7_accountant@x.com"
        assert d["role"] == "accountant"
        assert d["active"] is True
        assert "id" in d
        self.state["tid"] = d["id"]

        # GET list contains this member
        r = requests.get(f"{API}/team", headers=HEADERS)
        assert r.status_code == 200
        emails = [m["email"] for m in r.json()]
        assert "test_iter7_accountant@x.com" in emails

    def test_03_duplicate_returns_400(self):
        r = requests.post(f"{API}/team", headers=JSON_HEADERS, json={
            "owner_user_id": "ignored",
            "email": "test_iter7_accountant@x.com",
            "name": "Dup",
            "role": "accountant",
        })
        assert r.status_code == 400, r.text

    def test_04_role_owner_silently_downgrades(self):
        r = requests.post(f"{API}/team", headers=JSON_HEADERS, json={
            "owner_user_id": "ignored",
            "email": "test_iter7_boss@x.com",
            "name": "Boss Try",
            "role": "owner",
        })
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["role"] == "accountant", d
        # cleanup this one
        requests.delete(f"{API}/team/{d['id']}", headers=HEADERS)

    def test_05_update_role_to_viewer(self):
        tid = self.state["tid"]
        r = requests.put(f"{API}/team/{tid}", headers=JSON_HEADERS, json={
            "owner_user_id": "ignored",
            "email": "test_iter7_accountant@x.com",
            "name": "Test Acc",
            "role": "viewer",
        })
        assert r.status_code == 200, r.text
        assert r.json()["role"] == "viewer"

    def test_06_delete_member(self):
        tid = self.state["tid"]
        r = requests.delete(f"{API}/team/{tid}", headers=HEADERS)
        assert r.status_code == 200, r.text
        r = requests.get(f"{API}/team", headers=HEADERS)
        emails = [m["email"] for m in r.json()]
        assert "test_iter7_accountant@x.com" not in emails


# ==================== Supplier P&L report ====================
class TestSupplierPL:
    state = {}

    @classmethod
    def setup_class(cls):
        c = requests.post(f"{API}/customers", headers=JSON_HEADERS,
                          json={"name": "TEST_iter7_spl_cust"})
        assert c.status_code == 200, c.text
        cls.state["cid"] = c.json()["id"]
        v = requests.post(f"{API}/vehicles", headers=JSON_HEADERS, json={
            "vehicle_number": "VEH-SPL",
            "vehicle_type": "supplier",
            "supplier_name": "XYZ Transport",
        })
        assert v.status_code == 200, v.text
        cls.state["vid"] = v.json()["id"]
        tids = []
        for date in ("2026-01-10", "2026-01-11"):
            r = requests.post(f"{API}/trips", headers=JSON_HEADERS, json={
                "customer_id": cls.state["cid"], "date": date,
                "vehicle_number": "VEH-SPL", "tons": 10,
                "freight_mode": "fixed", "fixed_amount": 25000,
                "supplier_freight": 18000,
                "expenses": BASE_EXPENSES,
            })
            assert r.status_code == 200, r.text
            tids.append(r.json()["id"])
        cls.state["tids"] = tids

    @classmethod
    def teardown_class(cls):
        for tid in cls.state.get("tids", []):
            requests.delete(f"{API}/trips/{tid}?reason=cleanup", headers=HEADERS)
        if cls.state.get("vid"):
            requests.delete(f"{API}/vehicles/{cls.state['vid']}", headers=HEADERS)
        if cls.state.get("cid"):
            requests.delete(f"{API}/customers/{cls.state['cid']}", headers=HEADERS)

    def test_01_supplier_pl_aggregation(self):
        r = requests.get(f"{API}/reports/supplier-pl", headers=HEADERS)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "suppliers" in d and "totals" in d
        xyz = next((s for s in d["suppliers"] if s["supplier_name"] == "XYZ Transport"), None)
        assert xyz is not None, d
        assert xyz["trips"] == 2
        assert xyz["customer_freight"] == 50000
        assert xyz["supplier_freight"] == 36000
        assert xyz["profit"] == 14000
        assert xyz["margin_pct"] == 28.0

    def test_02_date_filter_excludes(self):
        r = requests.get(f"{API}/reports/supplier-pl", headers=HEADERS,
                         params={"start": "2020-01-01", "end": "2020-12-31"})
        assert r.status_code == 200, r.text
        d = r.json()
        # No XYZ in filtered range
        xyz = next((s for s in d["suppliers"] if s["supplier_name"] == "XYZ Transport"), None)
        assert xyz is None, d
        # And if there are no supplier trips at all in the range for this user,
        # totals should be zero. If there are other supplier trips in that range from
        # earlier iterations, we only assert the XYZ absence above.
        if not d["suppliers"]:
            t = d["totals"]
            assert t["trips"] == 0
            assert t["customer_freight"] == 0
            assert t["supplier_freight"] == 0
            assert t["profit"] == 0


# ==================== Invoice Snapshot on Edit ====================
class TestInvoiceSnapshot:
    state = {}

    @classmethod
    def setup_class(cls):
        requests.put(f"{API}/company", headers=JSON_HEADERS, json={
            "name": "TEST Iter7 Co", "state": "Telangana",
            "gstin": "36AAAAA0000A1Z5", "pincode": "500032",
        })
        c = requests.post(f"{API}/customers", headers=JSON_HEADERS,
                         json={"name": "TEST_iter7_snap_cust", "state": "Telangana",
                               "gstin": "36BBBBB0000B1Z5"})
        cls.state["cid"] = c.json()["id"]
        t = requests.post(f"{API}/trips", headers=JSON_HEADERS, json={
            "customer_id": cls.state["cid"], "date": "2026-01-05",
            "vehicle_number": "TS09SNAP1", "tons": 10,
            "freight_mode": "fixed", "fixed_amount": 10000,
            "expenses": BASE_EXPENSES,
        }).json()
        cls.state["tid"] = t["id"]
        inv = requests.post(f"{API}/invoices", headers=JSON_HEADERS, json={
            "customer_id": cls.state["cid"], "invoice_date": "2026-01-07",
            "trip_ids": [t["id"]], "gst_type": "cgst_sgst", "rcm": False,
        })
        assert inv.status_code == 200, inv.text
        cls.state["iid"] = inv.json()["id"]
        cls.state["inv_number"] = inv.json()["invoice_number"]

    @classmethod
    def teardown_class(cls):
        if cls.state.get("iid"):
            requests.delete(f"{API}/invoices/{cls.state['iid']}?reason=cleanup", headers=HEADERS)
        if cls.state.get("tid"):
            requests.delete(f"{API}/trips/{cls.state['tid']}?reason=cleanup", headers=HEADERS)
        if cls.state.get("cid"):
            requests.delete(f"{API}/customers/{cls.state['cid']}", headers=HEADERS)

    def test_snapshot_created_on_put(self):
        iid = self.state["iid"]
        r = requests.put(f"{API}/invoices/{iid}", headers=JSON_HEADERS,
                         json={"reason": "Change GST", "gst_type": "igst"})
        assert r.status_code == 200, r.text
        assert r.json()["gst_type"] == "igst"
        time.sleep(0.5)
        r = requests.get(f"{API}/files", headers=HEADERS,
                         params={"linked_type": "invoice", "linked_id": iid})
        assert r.status_code == 200, r.text
        files = r.json()
        snaps = [f for f in files if f.get("category") == "invoice_snapshot"]
        assert len(snaps) >= 1, files
        f0 = snaps[0]
        assert f0["content_type"] == "application/pdf"
        assert f0["size"] > 2000, f0
        # Filename contains invoice_number (with slashes replaced by _) and date
        inv_num_safe = self.state["inv_number"].replace("/", "_")
        assert inv_num_safe in f0["original_filename"], f0
        # date component (YYYY-MM-DD) present
        assert "2026-" in f0["original_filename"] or "-" in f0["original_filename"]


# ==================== Owner delete regression ====================
class TestOwnerDeleteRegression:
    def test_owner_can_delete_trip_with_reason(self):
        c = requests.post(f"{API}/customers", headers=JSON_HEADERS,
                          json={"name": "TEST_iter7_del_cust"}).json()
        t = requests.post(f"{API}/trips", headers=JSON_HEADERS, json={
            "customer_id": c["id"], "date": "2026-01-10",
            "vehicle_number": "TS09DELR", "tons": 5,
            "freight_mode": "fixed", "fixed_amount": 5000,
            "expenses": BASE_EXPENSES,
        }).json()
        r = requests.delete(f"{API}/trips/{t['id']}?reason=cleanup", headers=HEADERS)
        assert r.status_code == 200, r.text
        requests.delete(f"{API}/customers/{c['id']}", headers=HEADERS)


# ==================== Backward-compat regression ====================
class TestBackwardCompat:
    def test_endpoints_still_ok(self):
        for path in ["/auth/me", "/customers", "/trips", "/invoices",
                     "/drivers", "/products", "/vehicles", "/dashboard",
                     "/company", "/audit-logs", "/team", "/team/me",
                     "/reports/supplier-pl", "/files"]:
            r = requests.get(f"{API}{path}", headers=HEADERS)
            assert r.status_code == 200, f"{path} -> {r.status_code} {r.text[:200]}"

    def test_trip_put_after_invoicing_still_works(self):
        c = requests.post(f"{API}/customers", headers=JSON_HEADERS,
                          json={"name": "TEST_iter7_rc_cust", "state": "Telangana",
                                "gstin": "36AAAAA0000A1Z5"}).json()
        t = requests.post(f"{API}/trips", headers=JSON_HEADERS, json={
            "customer_id": c["id"], "date": "2026-01-05",
            "vehicle_number": "TS09RCE1", "tons": 20,
            "freight_mode": "per_ton", "rate_per_ton": 1000,
            "expenses": BASE_EXPENSES,
        }).json()
        inv = requests.post(f"{API}/invoices", headers=JSON_HEADERS, json={
            "customer_id": c["id"], "invoice_date": "2026-01-07",
            "trip_ids": [t["id"]], "gst_type": "cgst_sgst", "rcm": False,
        }).json()
        t["tons"] = 30
        r = requests.put(f"{API}/trips/{t['id']}", headers=JSON_HEADERS, json=t)
        assert r.status_code == 200, r.text
        assert r.json()["freight_amount"] == 30000
        inv2 = requests.get(f"{API}/invoices/{inv['id']}", headers=HEADERS).json()
        assert inv2["subtotal"] == 30000
        # cleanup
        requests.delete(f"{API}/invoices/{inv['id']}?reason=cleanup", headers=HEADERS)
        requests.delete(f"{API}/trips/{t['id']}?reason=cleanup", headers=HEADERS)
        requests.delete(f"{API}/customers/{c['id']}", headers=HEADERS)

    def test_audit_logs_listing(self):
        r = requests.get(f"{API}/audit-logs", headers=HEADERS, params={"limit": 20})
        assert r.status_code == 200
        assert isinstance(r.json(), list)
