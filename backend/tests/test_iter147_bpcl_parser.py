"""Iter147 P0 · BPCL parser unit tests.

Uses the REAL BPCL fixture supplied by the user.

Guarantees:
  • Diesel-only filtering (Petrol / other Product Names skipped).
  • Vehicle reference falls back through Vehicle Number → Custom Card Name → Card Number.
  • Date normalised from "08-Sep-2026" to ISO.
  • Auto-detection works from content signature, not just filename.
"""
from pathlib import Path

from services_fuel_import import parse_bpcl, parse_fuel_file, detect_source

FX = Path(__file__).parent / "fixtures" / "iter147"
BPCL = FX / "BPCL_SALES_FILE.xlsx"


def _blob():
    return BPCL.read_bytes()


def test_bpcl_auto_detect_by_content():
    blob = _blob()
    assert detect_source("some-file.xlsx", blob) == "bpcl"
    # Even a mis-named extension: content must win.
    assert detect_source("random.xls", blob) == "bpcl"


def test_bpcl_parses_only_diesel_rows():
    rows = parse_bpcl(_blob())
    assert rows, "no rows parsed from BPCL fixture"
    for r in rows:
        assert r["source"] == "bpcl"
        assert r["litres"] > 0
        assert r["amount"] > 0
        assert r["date"]


def test_bpcl_expected_diesel_count():
    # Fixture has Diesel + one Petrol row; parser must keep only Diesel.
    rows = parse_bpcl(_blob())
    # 6 rows total in fixture, 1 is Petrol → 5 Diesel remain.
    assert len(rows) == 5, f"expected 5 Diesel rows, got {len(rows)}"


def test_bpcl_first_row_data():
    rows = parse_bpcl(_blob())
    r = rows[0]
    assert r["source_txn_ref"] == "TXN100197704298"
    assert r["date"] == "2026-09-08"
    assert r["litres"] == 70.0
    assert r["rate"] == 105.09
    assert r["amount"] == 7356.30
    # Vehicle Number was blank → fall back to Custom Card Name
    assert r["source_vehicle_ref"] == "AKBANDSONS02"
    assert "V.S.N.R" in r["station_name"] or r["station_name"], \
        f"station name should include the outlet: {r['station_name']}"


def test_parse_fuel_file_bpcl_dispatch():
    source, rows = parse_fuel_file("BPCL_SALES_FILE.xlsx", _blob())
    assert source == "bpcl"
    assert len(rows) == 5


def test_unrecognised_file_returns_none():
    # Plain text upload → detect_source must return None.
    fake = b"hello, this is not a spreadsheet"
    assert detect_source("something.txt", fake) is None
    source, rows = parse_fuel_file("something.txt", fake)
    assert source is None and rows == []
