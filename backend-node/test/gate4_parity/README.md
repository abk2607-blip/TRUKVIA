# Phase 3 · Gate 4 · Live Python ↔ Node parity harness

Purpose-built for `POST /api/saved-trip-filters` (Gate-4 target). Mirrors the
Gate-3 harness shape: isolated DB, two disposable services on ports 8101/8102,
15+ parity cases including idempotency replay, write-observation across 7
collections.

## Run
```
python3 backend-node/test/gate4_parity/harness.py
```
Self-manages both processes and drops the isolated DB at the end.
