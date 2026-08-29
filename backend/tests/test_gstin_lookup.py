"""Tests for GSTIN offline lookup endpoint (Iteration 14)."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://trip-billing-pro-1.preview.emergentagent.com").rstrip("/")
TOKEN = os.environ["DEMO_TOKEN_VALUE"]
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def _get(params=None):
    return requests.get(f"{BASE_URL}/api/gstin/lookup", params=params, headers=HEADERS, timeout=30)


def test_valid_gstin_andhra():
    r = _get({"gstin": "37AAECR5210P2Z2"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["valid_format"] is True
    assert d["checksum_ok"] is True
    assert d["state_code"] == "37"
    assert d["state"] == "Andhra Pradesh"
    assert d["pan"] == "AAECR5210P"
    assert d["entity_code"] == "2"
    assert d["source"] == "offline_parse"


def test_valid_gstin_telangana():
    r = _get({"gstin": "36AAAAA0000A1Z5"})
    assert r.status_code == 200
    d = r.json()
    assert d["state_code"] == "36"
    assert d["state"] == "Telangana"
    assert d["pan"] == "AAAAA0000A"
    assert d["valid_format"] is True


def test_valid_gstin_delhi():
    r = _get({"gstin": "07AABCU9603R1ZM"})
    assert r.status_code == 200
    d = r.json()
    assert d["state_code"] == "07"
    assert d["state"] == "Delhi"


def test_bad_gstin():
    r = _get({"gstin": "BAD"})
    assert r.status_code == 200
    d = r.json()
    assert d["valid_format"] is False
    assert d["checksum_ok"] is False
    assert d["state"] == ""
    assert d["pan"] == ""


def test_missing_gstin():
    r = _get(None)
    # FastAPI returns 422 for missing required query param, but endpoint says 400 if empty string
    assert r.status_code in (400, 422)


def test_empty_gstin():
    r = _get({"gstin": "   "})
    assert r.status_code == 400
    assert "GSTIN is required" in r.text


def test_lowercase_and_spaces():
    r = _get({"gstin": " 37aaecr5210p2z2 "})
    assert r.status_code == 200
    d = r.json()
    assert d["valid_format"] is True
    assert d["gstin"] == "37AAECR5210P2Z2"
    assert d["state"] == "Andhra Pradesh"


def test_note_present_when_no_paid_key():
    r = _get({"gstin": "37AAECR5210P2Z2"})
    d = r.json()
    if not os.environ.get("GSTIN_LOOKUP_API_KEY"):
        assert d.get("note")
        assert "paid" in d["note"].lower() or "Signzy" in d["note"]


def test_auth_required():
    r = requests.get(f"{BASE_URL}/api/gstin/lookup", params={"gstin": "37AAECR5210P2Z2"}, timeout=30)
    assert r.status_code in (401, 403)
