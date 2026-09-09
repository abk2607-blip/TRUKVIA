"""Iter147 P0 · IOCL parser unit tests.

Uses the REAL BPCL/IOCL fixture files supplied by the user in the
Phase 0 discovery. These live in `backend/tests/fixtures/iter147/`.

Guarantees:
  • Diesel-only filtering (Recharge / Loyalty rows skipped).
  • Trailing apostrophe artifacts stripped from cells.
  • Vehicle references resolved (Vehicle No. (Card) → VehicleNo (User Entry) fallback).
  • Txn ID is float-normalised (no "1397005766.0" leftovers).
  • Auto-detection works from file bytes (extension is a hint, not authority).
"""
from pathlib import Path

from services_fuel_import import (
    parse_iocl, parse_fuel_file, detect_source,
)

FX = Path(__file__).parent / "fixtures" / "iter147"
IOCL = FX / "IOCL_FUEL_FILE.xls"


def _blob():
    return IOCL.read_bytes()


def test_iocl_auto_detect_by_content():
    blob = _blob()
    # Rename mimicked: filename says .xlsx but content is IOCL BIFF.
    assert detect_source("random-name.xlsx", blob) == "iocl", \
        "IOCL must be detected by content signature, not filename"
    assert detect_source("IOCL_FUEL_FILE.xls", blob) == "iocl"


def test_iocl_parses_only_diesel_sale_rows():
    rows = parse_iocl(_blob())
    # Every returned row must be a Diesel Sale (parser drops non-diesel).
    assert rows, "parser returned zero rows for the real IOCL file"
    for r in rows:
        assert r["source"] == "iocl"
        assert r["litres"] > 0, f"row {r['row_index']} litres must be > 0 for a Sale"
        assert r["amount"] > 0, f"row {r['row_index']} amount must be > 0 for a Sale"
        assert r["date"], f"row {r['row_index']} must have an ISO date"


def test_iocl_strips_apostrophe_artifacts():
    rows = parse_iocl(_blob())
    for r in rows:
        # Date must be pure ISO YYYY-MM-DD (no trailing "'").
        assert "'" not in r["date"], f"apostrophe leaked into date: {r['date']!r}"
        assert "'" not in r["source_txn_ref"], f"apostrophe leaked into txn ref: {r['source_txn_ref']!r}"


def test_iocl_txn_ref_is_string_not_float():
    rows = parse_iocl(_blob())
    for r in rows:
        assert isinstance(r["source_txn_ref"], str)
        assert not r["source_txn_ref"].endswith(".0"), \
            f"float artefact left in txn ref: {r['source_txn_ref']!r}"


def test_iocl_vehicle_ref_present():
    rows = parse_iocl(_blob())
    for r in rows:
        assert r["source_vehicle_ref"], f"missing source_vehicle_ref on row {r['row_index']}"
        assert r["source_vehicle_ref"] not in ("-", "N/A")


def test_iocl_expected_count_from_real_file():
    # Real fixture has 5 Diesel Sale rows (rest are Recharge / Loyalty).
    rows = parse_iocl(_blob())
    assert len(rows) == 5, f"expected 5 Diesel Sale rows in IOCL fixture, got {len(rows)}"


def test_iocl_first_row_matches_source_of_truth():
    rows = parse_iocl(_blob())
    r = rows[0]
    # Row 15 in the original sheet was:
    #   Sale · DIESEL · vehicle GENAKIS7234000012 · 250L @ 99.58 · Amt 24895
    assert r["source_vehicle_ref"] == "GENAKIS7234000012"
    assert r["litres"] == 250.0
    assert r["rate"] == 99.58
    assert r["amount"] == 24895.0
    assert r["date"] == "2026-09-08"
    assert r["source_txn_ref"] == "1397005766"


def test_parse_fuel_file_iocl_dispatch():
    source, rows = parse_fuel_file("IOCL_FUEL_FILE.xls", _blob())
    assert source == "iocl"
    assert len(rows) == 5
