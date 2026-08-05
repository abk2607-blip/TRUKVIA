"""Iteration 5 backend tests: LR PDF + auto-numbering, storage usage,
bulk file upload with filename auto-tagging, inline attachments on Trip/Vehicle,
and pincode fields on Company/Customer flowing into e-way bill."""
import io
import os
import re
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://trip-billing-pro-1.preview.emergentagent.com").rstrip("/")
TOKEN = "test_session_bitumen_2026"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
JSON_HEADERS = {**HEADERS, "Content-Type": "application/json"}
API = f"{BASE_URL}/api"


# ==================== LR PDF + Auto-numbering ====================
class TestLRGeneration:
    state = {}

    @classmethod
    def setup_class(cls):
        # Set company with pincode 500032, state Telangana
        r = requests.put(f"{API}/company", headers=JSON_HEADERS, json={
            "name": "TEST LR Co", "state": "Telangana", "gstin": "36AAAAA0000A1Z5",
            "address": "Hyd Address", "pincode": "500032",
        })
        assert r.status_code == 200, r.text
        # Customer with pincode 500001 (Hyd) initially - will be used for LR
        r = requests.post(f"{API}/customers", headers=JSON_HEADERS, json={
            "name": "TEST_LR_Cust", "state": "Telangana", "pincode": "500001",
        })
        assert r.status_code == 200, r.text
        cls.state["cid"] = r.json()["id"]
        assert r.json().get("pincode") == "500001"

        # Trip with LR-relevant fields
        r = requests.post(f"{API}/trips", headers=JSON_HEADERS, json={
            "customer_id": cls.state["cid"], "date": "2026-01-10",
            "vehicle_number": "TS09AB1234", "tons": 15,
            "from_location": "Hyderabad", "to_location": "Warangal",
            "freight_mode": "fixed", "fixed_amount": 20000,
            "driver_name": "Ramu", "driver_mobile": "9876543210",
            "consignor_name": "TEST LR Co",
            "consignee_site_location": "Warangal Highway KM 45",
            "external_invoice_no": "EXT/2026/001",
            "gross_weight": 25.5, "tare_weight": 10.5,
            "seal_numbers": "SEAL-001, SEAL-002",
            "load_details": "Bitumen VG 30",
            "expenses": {"diesel": 0, "toll": 0, "batta": 0, "repair": 0, "other": 0},
        })
        assert r.status_code == 200, r.text
        cls.state["tid"] = r.json()["id"]

    @classmethod
    def teardown_class(cls):
        tid = cls.state.get("tid")
        if tid: requests.delete(f"{API}/trips/{tid}", headers=HEADERS)
        cid = cls.state.get("cid")
        if cid: requests.delete(f"{API}/customers/{cid}", headers=HEADERS)

    def test_01_lr_pdf_generation_and_autonumber(self):
        r = requests.get(f"{API}/trips/{self.state['tid']}/lr", headers=HEADERS)
        assert r.status_code == 200, r.text
        assert r.headers.get("content-type", "").startswith("application/pdf")
        body = r.content
        assert body[:5] == b"%PDF-", f"Not a PDF: {body[:20]!r}"
        assert len(body) > 3000, f"PDF too small: {len(body)} bytes"

        # trip.lr_number should now be set with format LR/YY-YY/NNNNN
        # (No GET /trips/{tid}; use list and filter)
        r2 = requests.get(f"{API}/trips", headers=HEADERS)
        assert r2.status_code == 200
        trip_doc = next((t for t in r2.json() if t["id"] == self.state["tid"]), None)
        assert trip_doc is not None
        lr = trip_doc.get("lr_number", "")
        assert re.match(r"^LR/\d{2}-\d{2}/\d{5}$", lr), f"Bad LR format: {lr!r}"
        self.state["lr"] = lr

    def test_02_lr_number_stable_on_second_call(self):
        r = requests.get(f"{API}/trips/{self.state['tid']}/lr", headers=HEADERS)
        assert r.status_code == 200
        r2 = requests.get(f"{API}/trips", headers=HEADERS)
        trip_doc = next(t for t in r2.json() if t["id"] == self.state["tid"])
        assert trip_doc["lr_number"] == self.state["lr"], "LR must not change on regen"

    def test_03_lr_number_increments_for_new_trip(self):
        # Get current company.next_lr_number
        c1 = requests.get(f"{API}/company", headers=HEADERS).json()
        next_before = int(c1.get("next_lr_number") or 1)

        # Create another trip and generate LR
        r = requests.post(f"{API}/trips", headers=JSON_HEADERS, json={
            "customer_id": self.state["cid"], "date": "2026-01-11",
            "vehicle_number": "TS09AB1234", "tons": 10,
            "freight_mode": "fixed", "fixed_amount": 10000,
            "expenses": {"diesel": 0, "toll": 0, "batta": 0, "repair": 0, "other": 0},
        })
        assert r.status_code == 200
        tid2 = r.json()["id"]
        try:
            r = requests.get(f"{API}/trips/{tid2}/lr", headers=HEADERS)
            assert r.status_code == 200
            r2 = requests.get(f"{API}/trips", headers=HEADERS)
            trip_doc = next(t for t in r2.json() if t["id"] == tid2)
            new_lr = trip_doc["lr_number"]
            # Extract numbers and confirm new > old
            old_num = int(self.state["lr"].split("/")[-1])
            new_num = int(new_lr.split("/")[-1])
            assert new_num == old_num + 1, f"LR did not increment: {self.state['lr']} → {new_lr}"

            c2 = requests.get(f"{API}/company", headers=HEADERS).json()
            assert int(c2["next_lr_number"]) == next_before + 1
        finally:
            requests.delete(f"{API}/trips/{tid2}", headers=HEADERS)


# ==================== Storage Usage ====================
class TestStorageUsage:
    state = {"fids": []}

    @classmethod
    def teardown_class(cls):
        for fid in cls.state["fids"]:
            requests.delete(f"{API}/files/{fid}", headers=HEADERS)

    def _upload(self, filename, content_bytes, category="general"):
        files = {"file": (filename, io.BytesIO(content_bytes), "image/jpeg")}
        r = requests.post(f"{API}/files/upload", headers=HEADERS,
                          files=files, params={"category": category})
        assert r.status_code == 200, r.text
        return r.json()

    def test_01_usage_shape_and_growth(self):
        u0 = requests.get(f"{API}/files/usage", headers=HEADERS).json()
        for k in ("total_bytes", "limit_bytes", "pct", "file_count", "by_category"):
            assert k in u0, f"missing key {k} in {u0}"
        assert u0["limit_bytes"] == 500 * 1024 * 1024

        payload_a = b"A" * 2048
        payload_b = b"B" * 1024
        f1 = self._upload("TEST_usage1.jpg", payload_a, category="fuel_bill")
        f2 = self._upload("TEST_usage2.jpg", payload_b, category="vehicle_doc")
        self.state["fids"] += [f1["id"], f2["id"]]

        u1 = requests.get(f"{API}/files/usage", headers=HEADERS).json()
        assert u1["total_bytes"] >= u0["total_bytes"] + 3072
        assert u1["file_count"] >= u0["file_count"] + 2
        assert u1["by_category"].get("fuel_bill", 0) >= u0["by_category"].get("fuel_bill", 0) + 2048
        assert u1["by_category"].get("vehicle_doc", 0) >= u0["by_category"].get("vehicle_doc", 0) + 1024


# ==================== Bulk Upload Auto-Tagging ====================
class TestBulkUpload:
    state = {"fids": [], "vid": None}

    @classmethod
    def teardown_class(cls):
        for fid in cls.state["fids"]:
            requests.delete(f"{API}/files/{fid}", headers=HEADERS)
        if cls.state["vid"]:
            requests.delete(f"{API}/vehicles/{cls.state['vid']}", headers=HEADERS)

    def test_01_bulk_upload_tags_parsed(self):
        files = [
            ("files", ("AP16TA1234_2026-02-05_hp.jpg", io.BytesIO(b"x" * 512), "image/jpeg")),
            ("files", ("random.jpg", io.BytesIO(b"y" * 256), "image/jpeg")),
        ]
        r = requests.post(f"{API}/files/bulk-upload",
                          headers=HEADERS, files=files,
                          params={"category": "fuel_bill"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["total"] == 2
        assert d["uploaded"] == sum(1 for x in d["results"] if x["ok"])
        assert d["uploaded"] == 2
        r0, r1 = d["results"]
        assert r0["ok"] and r1["ok"]
        # First file parsed
        assert r0["tags"].get("vehicle_number") == "AP16TA1234"
        assert r0["tags"].get("date") == "2026-02-05"
        # No matching vehicle yet → linked_id empty
        assert r0["linked_id"] == ""
        # Second file has no tags
        assert r1["tags"] == {}
        self.state["fids"] += [r0["id"], r1["id"]]

    def test_02_bulk_upload_links_to_existing_vehicle(self):
        # Create vehicle first
        r = requests.post(f"{API}/vehicles", headers=JSON_HEADERS, json={
            "vehicle_number": "AP16TA1234", "owner_name": "TEST_Bulk"})
        assert r.status_code == 200
        self.state["vid"] = r.json()["id"]

        files = [
            ("files", ("AP16TA1234_2026-02-05.jpg", io.BytesIO(b"z" * 300), "image/jpeg")),
        ]
        r = requests.post(f"{API}/files/bulk-upload",
                          headers=HEADERS, files=files,
                          params={"category": "vehicle_doc"})
        assert r.status_code == 200
        d = r.json()
        assert d["uploaded"] == 1
        row = d["results"][0]
        assert row["ok"]
        assert row["linked_id"] == self.state["vid"]
        assert row["tags"]["vehicle_number"] == "AP16TA1234"
        self.state["fids"].append(row["id"])

        # Verify list filter by linked_type=vehicle
        r = requests.get(f"{API}/files", headers=HEADERS,
                         params={"linked_type": "vehicle", "linked_id": self.state["vid"]})
        assert r.status_code == 200
        ids = [x["id"] for x in r.json()]
        assert row["id"] in ids


# ==================== Inline Attachments (Trip / Vehicle) ====================
class TestInlineAttachments:
    state = {"fids": [], "tid": None, "vid": None, "cid": None}

    @classmethod
    def setup_class(cls):
        r = requests.post(f"{API}/customers", headers=JSON_HEADERS,
                          json={"name": "TEST_Attach_Cust"})
        cls.state["cid"] = r.json()["id"]
        r = requests.post(f"{API}/trips", headers=JSON_HEADERS, json={
            "customer_id": cls.state["cid"], "date": "2026-01-15",
            "vehicle_number": "ATTACH01", "tons": 5,
            "freight_mode": "fixed", "fixed_amount": 5000,
            "expenses": {"diesel": 0, "toll": 0, "batta": 0, "repair": 0, "other": 0},
        })
        cls.state["tid"] = r.json()["id"]
        r = requests.post(f"{API}/vehicles", headers=JSON_HEADERS,
                          json={"vehicle_number": "ATTACH_V01", "owner_name": "TEST"})
        cls.state["vid"] = r.json()["id"]

    @classmethod
    def teardown_class(cls):
        for fid in cls.state["fids"]:
            requests.delete(f"{API}/files/{fid}", headers=HEADERS)
        if cls.state["tid"]: requests.delete(f"{API}/trips/{cls.state['tid']}", headers=HEADERS)
        if cls.state["vid"]: requests.delete(f"{API}/vehicles/{cls.state['vid']}", headers=HEADERS)
        if cls.state["cid"]: requests.delete(f"{API}/customers/{cls.state['cid']}", headers=HEADERS)

    def _upload_linked(self, linked_type, linked_id, category, filename):
        files = {"file": (filename, io.BytesIO(b"data" * 100), "image/jpeg")}
        r = requests.post(f"{API}/files/upload", headers=HEADERS, files=files,
                          params={"category": category, "linked_type": linked_type, "linked_id": linked_id})
        assert r.status_code == 200, r.text
        return r.json()

    def test_01_attach_on_trip(self):
        f = self._upload_linked("trip", self.state["tid"], "trip_attachment", "trip_doc.jpg")
        self.state["fids"].append(f["id"])
        assert f["linked_type"] == "trip"
        assert f["linked_id"] == self.state["tid"]

        r = requests.get(f"{API}/files", headers=HEADERS,
                         params={"linked_type": "trip", "linked_id": self.state["tid"]})
        assert r.status_code == 200
        items = r.json()
        assert len(items) >= 1
        assert all(x["linked_type"] == "trip" and x["linked_id"] == self.state["tid"] for x in items)

    def test_02_attach_on_vehicle(self):
        f = self._upload_linked("vehicle", self.state["vid"], "vehicle_doc", "vehicle_rc.jpg")
        self.state["fids"].append(f["id"])
        r = requests.get(f"{API}/files", headers=HEADERS,
                         params={"linked_type": "vehicle", "linked_id": self.state["vid"]})
        assert r.status_code == 200
        items = r.json()
        assert len(items) >= 1
        assert all(x["linked_type"] == "vehicle" and x["linked_id"] == self.state["vid"] for x in items)


# ==================== Pincode fields feed into E-Way Bill ====================
class TestPincodeInEwayBill:
    state = {}

    @classmethod
    def setup_class(cls):
        r = requests.put(f"{API}/company", headers=JSON_HEADERS, json={
            "name": "TEST PIN Co", "state": "Telangana",
            "gstin": "36AAAAA0000A1Z5", "pincode": "500032",
        })
        assert r.status_code == 200, r.text
        assert r.json().get("pincode") == "500032"

        r = requests.post(f"{API}/customers", headers=JSON_HEADERS, json={
            "name": "TEST_PIN_Cust", "state": "Karnataka", "pincode": "560001",
            "gstin": "29AAAAA1111A1Z2",
        })
        assert r.status_code == 200
        cls.state["cid"] = r.json()["id"]
        assert r.json()["pincode"] == "560001"

        r = requests.post(f"{API}/trips", headers=JSON_HEADERS, json={
            "customer_id": cls.state["cid"], "date": "2026-01-20",
            "vehicle_number": "TS09PIN01", "tons": 10,
            "freight_mode": "fixed", "fixed_amount": 12000,
            "from_location": "Hyd", "to_location": "Blr",
            "expenses": {"diesel": 0, "toll": 0, "batta": 0, "repair": 0, "other": 0},
        })
        cls.state["tid"] = r.json()["id"]

    @classmethod
    def teardown_class(cls):
        if cls.state.get("tid"): requests.delete(f"{API}/trips/{cls.state['tid']}", headers=HEADERS)
        if cls.state.get("cid"): requests.delete(f"{API}/customers/{cls.state['cid']}", headers=HEADERS)

    def test_ewaybill_pincodes(self):
        r = requests.get(f"{API}/trips/{self.state['tid']}/ewaybill", headers=HEADERS)
        assert r.status_code == 200, r.text
        bl = r.json()["billLists"][0]
        assert bl["fromPincode"] == 500032
        assert bl["toPincode"] == 560001


# ==================== Regression ====================
class TestRegression:
    def test_endpoints_available(self):
        for path in ["/auth/me", "/customers", "/trips", "/invoices", "/drivers",
                     "/products", "/dashboard", "/vehicles", "/fuel", "/fuel/summary",
                     "/files", "/files/usage", "/company"]:
            r = requests.get(f"{API}{path}", headers=HEADERS)
            assert r.status_code == 200, f"{path} -> {r.status_code} {r.text[:200]}"

    def test_reports_gstr1(self):
        r = requests.get(f"{API}/reports/gstr1", headers=HEADERS, params={"month": "2026-05"})
        assert r.status_code == 200
