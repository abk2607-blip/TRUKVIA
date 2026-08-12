"""Iter57 — Login Stability end-to-end verification.

Covers:
1. Auth endpoint availability & stability (x5 each)
2. Post-restart resilience (10x /auth/me + 30s stale-tab)
3. Logout → Login → me
4. Trip form 90s stale flow
5. Trip edit preserves driver_recovery snapshot
6. Multi-Company isolation (customers/trips/drivers)
"""
import os
import time
import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
TOKEN = "test_session_bitumen_2026"
H = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


# --- Flow 1: Auth endpoint availability & stability --------------------------
class TestAuthEndpointsStability:
    def test_health_5x(self):
        for _ in range(5):
            r = requests.get(f"{BASE}/api/auth/health", timeout=10)
            assert r.status_code == 200, r.text

    def test_demo_login_5x(self):
        for _ in range(5):
            r = requests.post(f"{BASE}/api/auth/demo-login", timeout=10)
            assert r.status_code == 200, r.text
            data = r.json()
            assert "session_token" in data or "token" in data or "user" in data

    def test_me_5x(self):
        # ensure session provisioned
        requests.post(f"{BASE}/api/auth/demo-login", timeout=10)
        for _ in range(5):
            r = requests.get(f"{BASE}/api/auth/me", headers=H, timeout=10)
            assert r.status_code == 200, r.text
            assert "email" in r.json() or "id" in r.json()

    def test_session_bogus_5x(self):
        for _ in range(5):
            r = requests.post(
                f"{BASE}/api/auth/session",
                json={"session_id": "bogus_" + str(time.time())},
                timeout=10,
            )
            assert r.status_code == 401, r.text
            body = r.text.lower()
            assert "invalid" in body and "session" in body

    def test_logout_5x(self):
        for _ in range(5):
            requests.post(f"{BASE}/api/auth/demo-login", timeout=10)
            r = requests.post(f"{BASE}/api/auth/logout", headers=H, timeout=10)
            assert r.status_code == 200, r.text


# --- Flow 3: Post-restart resilience -----------------------------------------
class TestPostRestartResilience:
    def test_me_10x(self):
        requests.post(f"{BASE}/api/auth/demo-login", timeout=10)
        for i in range(10):
            r = requests.get(f"{BASE}/api/auth/me", headers=H, timeout=10)
            assert r.status_code == 200, f"iter {i}: {r.text}"

    @pytest.mark.slow
    def test_me_after_30s_stale(self):
        requests.post(f"{BASE}/api/auth/demo-login", timeout=10)
        r0 = requests.get(f"{BASE}/api/auth/me", headers=H, timeout=10)
        assert r0.status_code == 200
        time.sleep(30)
        r1 = requests.get(f"{BASE}/api/auth/me", headers=H, timeout=10)
        assert r1.status_code == 200, r1.text


# --- Flow 4: Logout → Login → me ---------------------------------------------
class TestLogoutLoginRoundTrip:
    def test_full_roundtrip(self):
        requests.post(f"{BASE}/api/auth/demo-login", timeout=10)
        lo = requests.post(f"{BASE}/api/auth/logout", headers=H, timeout=10)
        assert lo.status_code == 200
        li = requests.post(f"{BASE}/api/auth/demo-login", timeout=10)
        assert li.status_code == 200
        me = requests.get(f"{BASE}/api/auth/me", headers=H, timeout=10)
        assert me.status_code == 200, me.text
        data = me.json()
        assert "email" in data or "id" in data


# --- Flow 6: Trip form stale (shortened to 15s to keep suite tolerable) ------
# The 90s stale test is done in the UI test separately to avoid slow pytest.
class TestTripCreationStale:
    def test_create_after_delay(self):
        requests.post(f"{BASE}/api/auth/demo-login", timeout=30)

        # Need company id, vehicle, driver, customer
        cos = requests.get(f"{BASE}/api/companies", headers=H, timeout=30)
        assert cos.status_code == 200
        clist = cos.json()
        assert len(clist) >= 1
        cid = clist[0].get("id") or clist[0].get("_id")
        ch = {**H, "X-Company-Id": cid}

        customers = requests.get(f"{BASE}/api/customers", headers=ch, timeout=30).json()
        vehicles = requests.get(f"{BASE}/api/vehicles", headers=ch, timeout=30).json()
        drivers = requests.get(f"{BASE}/api/drivers", headers=ch, timeout=30).json()
        if not customers or not vehicles or not drivers:
            pytest.skip("Master data not seeded for company")

        payload = {
            "customer_id": customers[0].get("id"),
            "vehicle_id": vehicles[0].get("id"),
            "vehicle_number": vehicles[0].get("vehicle_number") or vehicles[0].get("number") or "TEST-01",
            "driver_id": drivers[0].get("id"),
            "driver_name": drivers[0].get("name") or "Test Driver",
            "customer_name": customers[0].get("name") or "Test Customer",
            "date": "2026-01-15",
            "tons": 20,
            "freight_mode": "fixed",
            "fixed_amount": 1000,
            "from_location": "STABILITY_ORIGIN",
            "to_location": "STABILITY_DEST",
        }

        # Simulate ~15s delay (shortened; 90s is done in UI test)
        time.sleep(15)
        cr = requests.post(f"{BASE}/api/trips", json=payload, headers=ch, timeout=20)
        assert cr.status_code in (200, 201), cr.text
        tid = cr.json().get("id")
        assert tid

        # Verify persistence via direct GET (list may be paginated/sorted)
        got = requests.get(f"{BASE}/api/trips/{tid}", headers=ch, timeout=30)
        assert got.status_code == 200, got.text
        assert got.json().get("id") == tid


# --- Flow 7: Trip edit preserves driver_recovery snapshot --------------------
class TestTripEditPreservesRecovery:
    def test_edit_first_trip(self):
        requests.post(f"{BASE}/api/auth/demo-login", timeout=10)
        cos = requests.get(f"{BASE}/api/companies", headers=H, timeout=10).json()
        cid = cos[0].get("id")
        ch = {**H, "X-Company-Id": cid}

        lst_r = requests.get(f"{BASE}/api/trips", headers=ch, timeout=10)
        assert lst_r.status_code == 200
        lst = lst_r.json()
        items = lst if isinstance(lst, list) else lst.get("items", [])
        if not items:
            pytest.skip("No trips available for company")
        tid = items[0].get("id")

        before = requests.get(f"{BASE}/api/trips/{tid}", headers=ch, timeout=10).json()
        before_recovery = before.get("driver_recovery")

        new_loc = f"STABILITY_TEST_{int(time.time())}"
        upd = {**before, "from_location": new_loc}
        # strip fields that PUT may reject
        for k in ("_id",):
            upd.pop(k, None)

        put = requests.put(f"{BASE}/api/trips/{tid}", json=upd, headers=ch, timeout=15)
        assert put.status_code == 200, put.text

        after = requests.get(f"{BASE}/api/trips/{tid}", headers=ch, timeout=10).json()
        assert after.get("from_location") == new_loc

        after_recovery = after.get("driver_recovery")
        if before_recovery:
            assert after_recovery is not None, "driver_recovery snapshot lost"
            for k in ("policy_id", "allowed_limit_kg"):
                if k in before_recovery:
                    assert after_recovery.get(k) == before_recovery.get(k), (
                        f"driver_recovery.{k} changed: {before_recovery.get(k)} -> {after_recovery.get(k)}"
                    )


# --- Flow 8: Multi-company data isolation ------------------------------------
class TestMultiCompanyIsolation:
    def _ids(self, lst):
        items = lst if isinstance(lst, list) else lst.get("items", [])
        return {i.get("id") for i in items if i.get("id")}

    def test_isolation(self):
        requests.post(f"{BASE}/api/auth/demo-login", timeout=10)
        cos = requests.get(f"{BASE}/api/companies", headers=H, timeout=10).json()
        if len(cos) < 2:
            pytest.skip("Need >=2 companies for isolation test")
        a = cos[0].get("id")
        b = cos[1].get("id")

        for path in ("customers", "trips", "drivers"):
            la = requests.get(f"{BASE}/api/{path}", headers={**H, "X-Company-Id": a}, timeout=10)
            lb = requests.get(f"{BASE}/api/{path}", headers={**H, "X-Company-Id": b}, timeout=10)
            assert la.status_code == 200 and lb.status_code == 200, f"{path}: {la.status_code}/{lb.status_code}"
            sa = self._ids(la.json())
            sb = self._ids(lb.json())
            overlap = sa & sb
            assert not overlap, f"{path} overlap between companies A/B: {overlap}"
