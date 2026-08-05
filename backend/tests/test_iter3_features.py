"""Iteration 3 backend tests: Products CRUD, Company logo upload, Round-trip freight
formula, Ledger / P&L / Balance-Sheet reports."""
import io
import os
import struct
import zlib
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
TOKEN = "test_session_bitumen_2026"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
JSON_HEADERS = {**HEADERS, "Content-Type": "application/json"}
API = f"{BASE_URL}/api"


def _tiny_png(w=2, h=2):
    """Build a valid tiny PNG in memory."""
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff))
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)  # 8-bit RGB
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * w for _ in range(h))
    idat = zlib.compress(raw)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


# ==================== Products CRUD ====================
class TestProducts:
    state = {}

    def test_01_create_product(self):
        r = requests.post(f"{API}/products", headers=JSON_HEADERS, json={
            "name": "TEST_Bitumen VG 40",
            "hsn_sac": "996791",
            "default_rate": 1200,
            "unit": "MT",
        })
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["name"] == "TEST_Bitumen VG 40"
        assert d["hsn_sac"] == "996791"
        assert d["default_rate"] == 1200
        assert d["unit"] == "MT"
        assert "id" in d and "_id" not in d
        self.__class__.state["pid"] = d["id"]

    def test_02_list_products(self):
        r = requests.get(f"{API}/products", headers=HEADERS)
        assert r.status_code == 200
        pid = self.state["pid"]
        assert any(p["id"] == pid for p in r.json())

    def test_03_update_product(self):
        pid = self.state["pid"]
        r = requests.put(f"{API}/products/{pid}", headers=JSON_HEADERS, json={
            "id": pid, "name": "TEST_Bitumen VG 30", "hsn_sac": "996791",
            "default_rate": 1500, "unit": "MT",
        })
        assert r.status_code == 200
        assert r.json()["name"] == "TEST_Bitumen VG 30"
        assert r.json()["default_rate"] == 1500

        # verify persisted
        r = requests.get(f"{API}/products", headers=HEADERS)
        p = next(x for x in r.json() if x["id"] == pid)
        assert p["name"] == "TEST_Bitumen VG 30"
        assert p["default_rate"] == 1500

    def test_04_delete_product(self):
        pid = self.state["pid"]
        r = requests.delete(f"{API}/products/{pid}", headers=HEADERS)
        assert r.status_code == 200
        r = requests.get(f"{API}/products", headers=HEADERS)
        assert not any(p["id"] == pid for p in r.json())


# ==================== Company Logo ====================
class TestCompanyLogo:
    def test_01_upload_valid_png(self):
        png = _tiny_png()
        assert len(png) < 100 * 1024
        files = {"file": ("logo.png", png, "image/png")}
        r = requests.post(f"{API}/company/logo", headers=HEADERS, files=files)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["logo"].startswith("data:image/png;base64,")

        # GET /company should return it
        r = requests.get(f"{API}/company", headers=HEADERS)
        assert r.status_code == 200
        assert r.json().get("logo", "").startswith("data:image/png;base64,")

    def test_02_upload_oversized(self):
        blob = b"\x89PNG\r\n\x1a\n" + os.urandom(1_500_000)  # 1.5MB, has image mime
        files = {"file": ("big.png", blob, "image/png")}
        r = requests.post(f"{API}/company/logo", headers=HEADERS, files=files)
        assert r.status_code == 400, r.text

    def test_03_upload_non_image(self):
        files = {"file": ("notes.txt", b"hello world", "text/plain")}
        r = requests.post(f"{API}/company/logo", headers=HEADERS, files=files)
        assert r.status_code == 400, r.text

    def test_04_delete_logo(self):
        r = requests.delete(f"{API}/company/logo", headers=HEADERS)
        assert r.status_code == 200
        r = requests.get(f"{API}/company", headers=HEADERS)
        assert r.json().get("logo", "") == ""


# ==================== Round-Trip Freight Formula ====================
class TestFreightFormula:
    state = {"trip_ids": [], "cid": None}

    @classmethod
    def setup_class(cls):
        r = requests.post(f"{API}/customers", headers=JSON_HEADERS,
                          json={"name": "TEST_FreightCust"})
        cls.state["cid"] = r.json()["id"]

    @classmethod
    def teardown_class(cls):
        for tid in cls.state["trip_ids"]:
            requests.delete(f"{API}/trips/{tid}", headers=HEADERS)
        if cls.state["cid"]:
            requests.delete(f"{API}/customers/{cls.state['cid']}", headers=HEADERS)

    def test_01_round_trip_formula(self):
        # tons=25.5, round_trip_kms=400, rate_per_km_per_ton=3.5 → 35700
        r = requests.post(f"{API}/trips", headers=JSON_HEADERS, json={
            "customer_id": self.state["cid"], "date": "2026-03-01",
            "vehicle_number": "RT01", "tons": 25.5,
            "freight_mode": "fixed",
            "round_trip_kms": 400, "rate_per_km_per_ton": 3.5,
            "expenses": {"diesel": 0, "toll": 0, "batta": 0, "repair": 0, "other": 0},
        })
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["freight_amount"] == 35700.0, d
        assert d["round_trip_kms"] == 400
        assert d["rate_per_km_per_ton"] == 3.5
        self.state["trip_ids"].append(d["id"])
        self.state["rt_id"] = d["id"]

    def test_02_legacy_fixed_fallback(self):
        # round_trip_kms=0 and rate_per_km_per_ton=0, fixed_amount=50000 → 50000
        r = requests.post(f"{API}/trips", headers=JSON_HEADERS, json={
            "customer_id": self.state["cid"], "date": "2026-03-02",
            "vehicle_number": "RT02", "tons": 20,
            "freight_mode": "fixed",
            "round_trip_kms": 0, "rate_per_km_per_ton": 0,
            "fixed_amount": 50000,
            "expenses": {"diesel": 0, "toll": 0, "batta": 0, "repair": 0, "other": 0},
        })
        assert r.status_code == 200
        d = r.json()
        assert d["freight_amount"] == 50000.0, d
        self.state["trip_ids"].append(d["id"])

    def test_03_per_ton_mode(self):
        # tons=20, rate_per_ton=1000 → 20000
        r = requests.post(f"{API}/trips", headers=JSON_HEADERS, json={
            "customer_id": self.state["cid"], "date": "2026-03-03",
            "vehicle_number": "RT03", "tons": 20,
            "freight_mode": "per_ton", "rate_per_ton": 1000,
            "expenses": {"diesel": 0, "toll": 0, "batta": 0, "repair": 0, "other": 0},
        })
        assert r.status_code == 200
        d = r.json()
        assert d["freight_amount"] == 20000.0
        self.state["trip_ids"].append(d["id"])

    def test_04_put_recomputes_round_trip(self):
        tid = self.state["rt_id"]
        r = requests.put(f"{API}/trips/{tid}", headers=JSON_HEADERS, json={
            "id": tid,
            "customer_id": self.state["cid"], "date": "2026-03-01",
            "vehicle_number": "RT01", "tons": 30,
            "freight_mode": "fixed",
            "round_trip_kms": 500, "rate_per_km_per_ton": 4.0,
            "expenses": {"diesel": 0, "toll": 0, "batta": 0, "repair": 0, "other": 0},
        })
        assert r.status_code == 200, r.text
        d = r.json()
        # 30 * 500 * 4 = 60000
        assert d["freight_amount"] == 60000.0, d


# ==================== Ledger / P&L / Balance Sheet ====================
class TestReports:
    state = {}

    @classmethod
    def setup_class(cls):
        # Fresh customer
        r = requests.post(f"{API}/customers", headers=JSON_HEADERS,
                          json={"name": "TEST_LedgerCo", "phone": "9000000123"})
        assert r.status_code == 200
        cls.state["cid"] = r.json()["id"]

        # Trip 1: revenue 20000, expense 3000
        r = requests.post(f"{API}/trips", headers=JSON_HEADERS, json={
            "customer_id": cls.state["cid"], "date": "2026-04-01",
            "vehicle_number": "LG01", "tons": 20,
            "freight_mode": "per_ton", "rate_per_ton": 1000,
            "expenses": {"diesel": 3000, "toll": 0, "batta": 0, "repair": 0, "other": 0},
        })
        t1 = r.json()["id"]
        # Trip 2: revenue 20000
        r = requests.post(f"{API}/trips", headers=JSON_HEADERS, json={
            "customer_id": cls.state["cid"], "date": "2026-04-02",
            "vehicle_number": "LG02", "tons": 20,
            "freight_mode": "per_ton", "rate_per_ton": 1000,
            "expenses": {"diesel": 2000, "toll": 100, "batta": 0, "repair": 0, "other": 0},
        })
        t2 = r.json()["id"]
        cls.state["tids"] = [t1, t2]

        # Invoice on 2026-04-10 with RCM=true (subtotal 40000 → total 40000)
        r = requests.post(f"{API}/invoices", headers=JSON_HEADERS, json={
            "customer_id": cls.state["cid"], "trip_ids": [t1, t2],
            "invoice_date": "2026-04-10",
            "gst_type": "cgst_sgst", "rcm": True,
        })
        assert r.status_code == 200, r.text
        inv = r.json()
        cls.state["iid"] = inv["id"]
        cls.state["inv_no"] = inv["invoice_number"]
        assert inv["subtotal"] == 40000.0
        assert inv["total_amount"] == 40000.0

        # Payment of 15000 on 2026-04-20
        r = requests.post(f"{API}/invoices/{inv['id']}/payments",
                         headers=JSON_HEADERS, json={
                             "amount": 15000, "date": "2026-04-20", "mode": "Bank",
                         })
        assert r.status_code == 200

    @classmethod
    def teardown_class(cls):
        iid = cls.state.get("iid")
        if iid: requests.delete(f"{API}/invoices/{iid}", headers=HEADERS)
        for tid in cls.state.get("tids", []):
            requests.delete(f"{API}/trips/{tid}", headers=HEADERS)
        cid = cls.state.get("cid")
        if cid: requests.delete(f"{API}/customers/{cid}", headers=HEADERS)

    def test_01_ledger_full(self):
        r = requests.get(f"{API}/reports/ledger", headers=HEADERS,
                        params={"customer_id": self.state["cid"]})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["opening_balance"] == 0
        assert d["total_debit"] == 40000.0
        assert d["total_credit"] == 15000.0
        assert d["closing_balance"] == 25000.0
        # entries: 1 invoice + 1 payment
        inv_entries = [e for e in d["entries"] if e["type"] == "invoice"]
        pay_entries = [e for e in d["entries"] if e["type"] == "payment"]
        assert len(inv_entries) == 1
        assert inv_entries[0]["debit"] == 40000.0
        assert len(pay_entries) == 1
        assert pay_entries[0]["credit"] == 15000.0
        # running balance sanity
        assert inv_entries[0]["balance"] == 40000.0
        assert pay_entries[0]["balance"] == 25000.0
        assert d["customer"]["name"] == "TEST_LedgerCo"

    def test_02_ledger_date_filter_excludes_payment(self):
        # window that excludes 2026-04-20 payment
        r = requests.get(f"{API}/reports/ledger", headers=HEADERS,
                        params={"customer_id": self.state["cid"],
                                "start": "2026-04-01", "end": "2026-04-15"})
        assert r.status_code == 200
        d = r.json()
        # payment on 04-20 excluded
        assert d["total_credit"] == 0
        assert d["total_debit"] == 40000.0
        assert d["closing_balance"] == 40000.0
        assert not any(e["type"] == "payment" for e in d["entries"])

    def test_03_ledger_missing_customer_id_422(self):
        r = requests.get(f"{API}/reports/ledger", headers=HEADERS)
        assert r.status_code == 422

    def test_04_ledger_pdf(self):
        r = requests.get(f"{API}/reports/ledger/pdf", headers=HEADERS,
                        params={"customer_id": self.state["cid"]})
        assert r.status_code == 200, r.text
        assert r.headers.get("content-type", "").startswith("application/pdf")
        assert r.content[:5] == b"%PDF-"
        assert len(r.content) > 2000

    def test_05_pl_report(self):
        r = requests.get(f"{API}/reports/pl", headers=HEADERS,
                        params={"start": "2026-01-01", "end": "2026-12-31"})
        assert r.status_code == 200, r.text
        d = r.json()
        # revenue includes our 2 trips (40000) plus any other 2026 trips seeded
        # so just assert relationships and presence
        assert d["revenue"] >= 40000.0
        assert d["expenses"]["diesel"] >= 5000.0
        assert d["expenses"]["total"] == round(
            d["expenses"]["diesel"] + d["expenses"]["toll"] + d["expenses"]["batta"]
            + d["expenses"]["repair"] + d["expenses"]["other"], 2)
        assert d["net_profit"] == round(d["revenue"] - d["expenses"]["total"], 2)
        assert isinstance(d["per_customer"], list)
        pc = next((x for x in d["per_customer"]
                   if x["customer_id"] == self.state["cid"]), None)
        assert pc is not None, "per-customer entry missing"
        assert pc["revenue"] == 40000.0
        assert pc["expense"] == 5100.0  # 3000 + (2000+100)
        assert pc["profit"] == 34900.0

    def test_06_balance_sheet(self):
        r = requests.get(f"{API}/reports/balance-sheet", headers=HEADERS,
                        params={"as_of": "2026-12-31"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["assets"]["cash_and_bank"] >= 15000.0
        assert d["assets"]["sundry_debtors"] >= 25000.0
        # assets.total == equity.total + liabilities.total
        assert d["assets"]["total"] == round(
            d["equity"]["total"] + d["liabilities"]["total"], 2)
        # retained_earnings = revenue - expenses (from P&L up to as_of)
        assert isinstance(d["equity"]["retained_earnings"], (int, float))


# ==================== Regression smoke ====================
class TestRegression:
    def test_auth_me(self):
        r = requests.get(f"{API}/auth/me", headers=HEADERS)
        assert r.status_code == 200
        assert r.json()["user_id"] == "test-user-bitumen"

    def test_list_endpoints(self):
        for path in ["/customers", "/trips", "/invoices", "/drivers",
                     "/products", "/dashboard"]:
            r = requests.get(f"{API}{path}", headers=HEADERS)
            assert r.status_code == 200, f"{path} -> {r.status_code}"

    def test_public_pdf_still_works(self):
        # Grab any invoice with share_token by creating one quickly
        r = requests.get(f"{API}/invoices", headers=HEADERS)
        invs = r.json()
        if not invs:
            pytest.skip("no invoices to test public pdf")
        # Find or create share
        iid = invs[0]["id"]
        r = requests.post(f"{API}/invoices/{iid}/share", headers=HEADERS)
        token = r.json()["share_token"]
        s = requests.Session()
        r = s.get(f"{API}/public/invoice/{token}/pdf")
        assert r.status_code == 200
        assert r.content[:5] == b"%PDF-"

    def test_invoice_pdf(self):
        r = requests.get(f"{API}/invoices", headers=HEADERS)
        invs = r.json()
        if not invs:
            pytest.skip("no invoices")
        iid = invs[0]["id"]
        r = requests.get(f"{API}/invoices/{iid}/pdf", headers=HEADERS)
        assert r.status_code == 200
        assert r.content[:5] == b"%PDF-"
