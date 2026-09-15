# Phase 3 · Gate 6b · Live Python ↔ Node parity harness

Purpose-built for `GET /api/trips` — Slice-6b strict-read-only shadow with
Class-B `_backfill_to_default` neutralisation (fresh multi-company
fixtures). Isolated Mongo DB (`trukvia_gate6b_parity_<ts>`, auto-dropped
in `finally`); two disposable services on ports 8107 / 8108; ≥19 parity
cases plus strict write-observation across 14 tracked collections.

**UAT-data preservation**: this harness NEVER touches the shared
`test_database` or any existing TRUKVIA tenant. It creates an isolated,
timestamp-suffixed DB, seeds fresh multi-company fixtures inside it, and
drops it when the run ends. Any existing login/UAT dataset remains
completely untouched.

## Run
```
python3 backend-node/test/gate6b_parity/harness.py
```
