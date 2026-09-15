# Phase 3 · Gate 6a · Live Python ↔ Node parity harness

Purpose-built for `GET /api/trips/{tid}` — Slice-6a strict-read-only shadow.
Isolated Mongo DB, two disposable services on ports 8105 / 8106, 15+ parity
cases covering happy path, not-found, three 401 paths, cross-tenant isolation,
X-Company-Id owned/unowned, historical trip, populated nested fields, empty
arrays, deterministic serialization + strict write-observation.

## Run
```
python3 backend-node/test/gate6a_parity/harness.py
```
Self-manages both processes and drops the isolated DB at the end.
