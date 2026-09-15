# Phase 3 · Gate 5 · Live Python ↔ Node parity harness

Purpose-built for `POST /api/expenditure-types` (Gate-5 target, Path B.3-α —
Bucket-B idempotency middleware is NOT used for this endpoint). Mirrors the
Gate-4 harness shape: isolated DB, two disposable services on ports 8103/8104,
19 parity cases including natural-dedup replay + fresh-tenant no-seed guard,
write-observation across 9 tracked collections.

## Run
```
python3 backend-node/test/gate5_parity/harness.py
```
Self-manages both processes and drops the isolated DB at the end.
