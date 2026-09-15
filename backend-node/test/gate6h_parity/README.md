# Phase 3 · Gate 6h · Live Python↔Node parity harness

Covers exactly two read-only surfaces:

* `GET /api/company`
* `GET /api/suppliers/{sid}`

## Data safety

* Isolated timestamped disposable DB: `trukvia_gate6h_parity_<timestamp>`.
* Dropped in `finally` regardless of pass/fail.
* Never touches `test_database`, `trukvia_uat`, or any real tenant.
* Never mutates login/account/company mapping.

## Class-C stance

Both Python handlers are pure-read (`find_one` only). No writer hooks,
no audit calls, no backfills, no recompute. Both stacks must produce
byte-identical JSON on every HIT case AND zero DB mutation.

## Special parity rule — default Company id tolerance

On the `/api/company` MISS path (no company row exists for the user):

* Python returns `Company().model_dump()`.
* Both stacks emit 36 fields; `id` uses `co_` + 16 lowercase hex chars.
* Byte identity of the generated `id` is IMPOSSIBLE by design.
* Harness tolerates ONLY the `id` field on this path — every other of
  the 35 default fields must be byte-identical.
* Both stacks assert `id` matches `^co_[0-9a-f]{16}$`.

Every other case (existing company, existing supplier, 404, 401)
requires full byte identity.

## Cases

Company:
1. existing default company (hit) — byte-identical body
2. owned X-Company-Id override → alt company (hit) — byte-identical
3. unowned X-Company-Id → default fallback (hit) — byte-identical
4. missing company (user with no company) → 200 default body — id-tolerated
5. no auth → 401
6. invalid bearer → 401
7. expired session → 401

Supplier:
8. existing supplier under default company — byte-identical
9. missing supplier id → 404 "Supplier not found"
10. cross-user supplier id → 404
11. cross-company supplier id (correct user, wrong company) → 404
12. no X-Company-Id header → default company scope
13. owned override → alt-company supplier accessible
14. unowned override → default fallback
15. no auth → 401
16. invalid bearer → 401
17. expired session → 401

Aggregate:
18. zero Node business writes across ALL cases

## Run

```
cd /app/backend-node && npx tsc && cd /app
python3 backend-node/test/gate6h_parity/harness.py
```

Result JSON is written to `/tmp/gate6h_parity_results.json`.
