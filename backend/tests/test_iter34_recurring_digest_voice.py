"""Iter34 — Recurring trip suggestions, one-tap repeat, voice parse contexts, daily digest, MoM in insights."""
import os
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"
TOKEN = "test_session_bitumen_2026"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def _get_or_create_customer():
    r = requests.get(f"{API}/customers", headers=HEADERS)
    for c in r.json():
        if c.get("name") == "TEST_Iter34_Recur":
            return c["id"]
    return requests.post(f"{API}/customers", headers=HEADERS, json={"name": "TEST_Iter34_Recur", "state": "Andhra Pradesh"}).json()["id"]


def _create_trip(**kw):
    payload = {"date": "2026-02-06", "vehicle_number": "AP99RC0001",
               "from_location": "Chennai", "to_location": "Hyderabad",
               "load_details": "Bitumen", "tons": 20,
               "freight_mode": "per_ton", "rate_per_ton": 1200}
    payload.update(kw)
    return requests.post(f"{API}/trips", headers=HEADERS, json=payload).json()


def test_voice_parse_expense_context():
    r = requests.post(f"{API}/ai/parse", headers=HEADERS, json={
        "transcript": "Diesel 3000 rupees, toll 500 rupees, batta 400 rupees",
        "context": "expense"
    })
    assert r.status_code == 200
    p = r.json()["parsed"]
    assert p["diesel"] == 3000
    assert p["toll"] == 500
    assert p["batta"] == 400


def test_voice_parse_payment_context():
    r = requests.post(f"{API}/ai/parse", headers=HEADERS, json={
        "transcript": "Payment 5000 rupees received via UPI on today from TEST_Iter34_Recur",
        "context": "payment"
    })
    assert r.status_code == 200
    p = r.json()["parsed"]
    assert p.get("amount") == 5000
    assert p.get("mode", "").lower() in ("upi", "cash", "bank transfer", "cheque")


def test_voice_parse_invoice_context():
    r = requests.post(f"{API}/ai/parse", headers=HEADERS, json={
        "transcript": "New invoice for TEST_Iter34_Recur customer dated today with GST 12 percent",
        "context": "invoice"
    })
    assert r.status_code == 200
    p = r.json()["parsed"]
    # customer_name OR gst_rate must be extracted
    assert p.get("customer_name") or p.get("gst_rate") == 12


def test_daily_digest_returns_whatsapp_and_stats():
    r = requests.get(f"{API}/ai/daily-digest", headers=HEADERS)
    assert r.status_code == 200
    d = r.json()
    assert d["whatsapp_url"].startswith("https://wa.me/?text=")
    assert "text" in d
    assert d["stats"] is not None
    assert "today_trips" in d["stats"]


def test_recurring_suggestions_detects_repeat_route():
    from datetime import datetime, timezone, timedelta
    cid = _get_or_create_customer()
    today = datetime.now(timezone.utc).date()
    # Create 3 trips on same customer × route within last 30 days
    ids = []
    for i in range(3):
        d = (today - timedelta(days=i + 1)).isoformat()
        t = _create_trip(customer_id=cid, date=d, vehicle_number="AP99RC0001",
                          from_location="Chennai", to_location="Hyderabad")
        ids.append(t["id"])
    try:
        r = requests.get(f"{API}/trips/recurring-suggestions", headers=HEADERS)
        assert r.status_code == 200
        rs = r.json()
        # Find our test customer suggestion
        ours = [s for s in rs if s["customer_id"] == cid]
        assert len(ours) >= 1, f"expected our customer in suggestions, got {rs}"
        s = ours[0]
        assert s["count_60d"] >= 3
        assert s["from_location"].lower().startswith("chennai")
        assert s["to_location"].lower().startswith("hyderabad")
        assert s["last_trip_id"] in ids

        # Now use one-tap repeat
        rep = requests.post(f"{API}/trips/quick-repeat/{s['last_trip_id']}", headers=HEADERS)
        assert rep.status_code == 200
        new_trip = rep.json()
        assert new_trip["id"] not in ids
        assert new_trip["customer_id"] == cid
        assert new_trip["from_location"].lower().startswith("chennai")
        assert new_trip["status"] == "pending"
        assert new_trip["lr_number"] == ""
        ids.append(new_trip["id"])
    finally:
        for tid in ids:
            requests.delete(f"{API}/trips/{tid}", headers=HEADERS, params={"reason": "test cleanup"})


def test_insights_includes_mom_stats():
    r = requests.post(f"{API}/ai/insights/refresh", headers=HEADERS)
    assert r.status_code == 200
    d = r.json()
    assert d["insights"]
    mom = d.get("stats_snapshot", {}).get("mom")
    assert mom is not None
    assert "revenue" in mom
    assert "profit" in mom
    assert "trip_count" in mom
    # each delta dict has prev/curr/direction
    for k in ("revenue", "profit", "trip_count"):
        assert "curr" in mom[k]
        assert "direction" in mom[k]
