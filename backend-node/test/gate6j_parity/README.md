# Phase 3 · Gate 6j · Live Python↔Node parity harness

Covers exactly two read-only surfaces:

* `GET /api/vendors`
* `GET /api/vendors/{vid}`

## Data safety

* Isolated timestamped disposable DB: `trukvia_gate6j_parity_<timestamp>`.
* Dropped in `finally` regardless of pass/fail.
* Never touches `test_database`, `trukvia_uat`, or any real tenant.
* Never mutates login/account/company mapping.

## Class-C stance

Both Python handlers are pure-read (`find` / `find_one` only). No
writer hooks, no audit calls, no backfills, no recompute, no
effective-balance projection, no FinTxn emission, no paired-linkage
refresh. Both stacks must produce byte-identical JSON on every case
and zero DB mutation.

## Preserved semantics

* `active_only` — FastAPI/Pydantic v2 boolean tokens (`1 t true on
  yes` / `0 f false off n no`, case-insensitive). Missing → false.
  Invalid → `422`. True → `is_active: true` equality (only literal
  boolean).
* `q` — truthy string builds an `$or` regex filter over `name`,
  `mobile`, `contact_person` with `$options: 'i'`. Raw string
  passthrough (server-side Mongo evaluation). NO JavaScript RegExp
  construction, NO escaping, NO normalization.
* List projection `{_id: 0, user_id: 0}`; sort `name` ASC; cap 20 000.
* Detail: composite `{id, user_id, company_id}` scoping only — NO
  `is_deleted` / NO `is_active` filter. Inactive vendors ARE
  returned. Miss → `404 { "detail": "Vendor not found" }`.

## Cases

LIST (22 cases):
1. list happy path (default scope)
2. `active_only=true` → filters inactive
3. `active_only=false` → all vendors
4. `active_only=YES` (TRUE token)
5. `active_only=0` (FALSE token)
6. `active_only=on` (TRUE token)
7. `active_only=off` (FALSE token)
8. invalid boolean → `422` (status-only compare — Python/Fastify body shapes differ)
9. `q` matches name (lowercase)
10. `q` matches name UPPERCASE (case-insensitive proof)
11. `q` matches mobile
12. `q` matches contact_person
13. `q` partial substring on mobile
14. `q` no match → empty array
15. empty `q` → filter omitted
16. `active_only` + `q` combined
17. cross-user isolation (u2 view)
18. owned `X-Company-Id` override
19. unowned `X-Company-Id` → default fallback
20. list no auth → `401`
21. list invalid bearer → `401`
22. list expired → `401`

DETAIL (10 cases):
23. detail happy path
24. detail extra fields preserved
25. detail inactive vendor STILL RETURNED (no `is_active` filter)
26. detail missing → `404`
27. detail cross-user → `404`
28. detail cross-company → `404`
29. detail owned `X-Company-Id` override → alt row accessible
30. detail no auth → `401`
31. detail invalid bearer → `401`
32. detail expired → `401`

AGGREGATE:
33. zero Node business writes across ALL cases (17 tracked business collections + `vendors`)

## Compare modes

* `full` — byte-identical JSON body between Python and Node.
* `status_only` — HTTP status only (invalid-boolean `422` case:
  FastAPI + Fastify emit different validation-error `detail` shapes;
  precedent from Gate 6g and Gate 6i).

## Run

```
cd /app/backend-node && npx tsc && cd /app
python3 backend-node/test/gate6j_parity/harness.py
```

Result JSON is written to `/tmp/gate6j_parity_results.json`.
