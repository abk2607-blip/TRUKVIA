"""Iter38 — Party Details / Advance Pool / Photo attach / Scheduler digest."""
import os
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"
TOKEN = os.environ["DEMO_TOKEN_VALUE"]
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def _cust():
    r = requests.get(f"{API}/customers", headers=HEADERS)
    for c in r.json():
        if c["name"] == "TEST_Iter38":
            return c["id"]
    return requests.post(f"{API}/customers", headers=HEADERS, json={"name": "TEST_Iter38", "state": "Andhra Pradesh", "phone": "9998887771"}).json()["id"]


def test_customer_model_new_fields():
    """New fields email, opening_balance, advance_balance, notes, reminder_enabled all round-trip via PUT."""
    cid = _cust()
    payload = {
        "name": "TEST_Iter38",
        "email": "billing@test.com",
        "opening_balance": 5000,
        "notes": "VIP customer",
        "reminder_enabled": False,
        "pan": "ABCDE1234F",
        "gstin": "37AAACC1234A1Z5",
    }
    r = requests.put(f"{API}/customers/{cid}", headers=HEADERS, json=payload)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["email"] == "billing@test.com"
    assert d["opening_balance"] == 5000
    assert d["notes"] == "VIP customer"
    assert d["reminder_enabled"] is False
    assert d["pan"] == "ABCDE1234F"
    # Also verify GET returns them
    r2 = requests.get(f"{API}/customers", headers=HEADERS)
    ours = next((c for c in r2.json() if c["id"] == cid), None)
    assert ours["email"] == "billing@test.com"


def test_add_payment_surplus_becomes_advance():
    cid = _cust()
    # Reset advance to zero first
    requests.put(f"{API}/customers/{cid}", headers=HEADERS, json={"name": "TEST_Iter38", "advance_balance": 0})
    r = requests.post(f"{API}/customers/{cid}/add-payment", headers=HEADERS, json={"amount": 1234, "mode": "Cash"})
    assert r.status_code == 200
    d = r.json()
    # With no outstanding invoices, entire amount is unallocated → advance
    assert d["amount_unallocated"] >= 1234
    assert d["advance_balance"] >= 1234
    # Verify persisted on customer
    cust = next(c for c in requests.get(f"{API}/customers", headers=HEADERS).json() if c["id"] == cid)
    assert cust["advance_balance"] >= 1234


def test_add_payment_with_photo():
    cid = _cust()
    tiny_png = (
        "data:image/png;base64,"
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
    )
    r = requests.post(f"{API}/customers/{cid}/add-payment", headers=HEADERS, json={
        "amount": 500, "mode": "UPI", "photo_data_url": tiny_png,
    })
    assert r.status_code == 200, r.text
    d = r.json()
    assert d.get("photo_url"), "expected photo_url in response"
    assert d["photo_url"].startswith("http")
    assert "/api/files/public/public/payment_photos/" in d["photo_url"]


def test_reminders_digest_manual_run():
    r = requests.post(f"{API}/reminders/digest/run", headers=HEADERS)
    assert r.status_code == 200
    d = r.json()
    assert "digest" in d
    # After a manual run, digest may be None if no outstanding invoices — still valid.
    r2 = requests.get(f"{API}/reminders/digest", headers=HEADERS)
    assert r2.status_code == 200


def test_customer_reminder_pref_toggle():
    cid = _cust()
    r = requests.put(f"{API}/customers/{cid}/reminder-pref", headers=HEADERS, json={"reminder_enabled": False})
    assert r.status_code == 200
    assert r.json()["reminder_enabled"] is False
    r = requests.put(f"{API}/customers/{cid}/reminder-pref", headers=HEADERS, json={"reminder_enabled": True})
    assert r.status_code == 200
    assert r.json()["reminder_enabled"] is True
