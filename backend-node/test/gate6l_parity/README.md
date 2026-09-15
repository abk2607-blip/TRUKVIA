# Phase 3 · Gate 6l · Live Python↔Node parity harness

Covers exactly two read-only surfaces:

* `GET /api/mechanics`
* `GET /api/mechanics/{mid}`

Mechanic = labour / service provider party master (distinct from
Vendor/parts and Supplier/hired-vehicle owner per Iter133 PRD).

## Data safety

* Isolated timestamped disposable DB: `trukvia_gate6l_parity_<timestamp>`.
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

* `active_only` — FastAPI/Pydantic v2 boolean tokens
  (`1 t true on yes` / `0 f false off n no`, case-insensitive).
  Missing → false. Invalid → `422`. True → `is_active: true`
  equality (only literal boolean).
* `q` — truthy string builds `$or` regex over `name`, `mobile`,
  **`skill`** (NOT `contact_person`) with `$options: 'i'`. Raw
  string passthrough (server-side Mongo evaluation). No JS RegExp
  construction, no escaping, no normalization.
* List projection `{_id: 0, user_id: 0}`; sort `name` ASC; cap 20 000.
* Detail: composite `{id, user_id, company_id}` scoping — NO
  `is_deleted` / NO `is_active` filter. Inactive mechanics ARE
  returned. Miss → `404 { "detail": "Mechanic not found" }`.

## Cases (33 request cases + 1 aggregate)

LIST (23):
1. list happy path
2. `active_only=true`
3. `active_only=false`
4. `active_only=YES` (TRUE token)
5. `active_only=0` (FALSE token)
6. `active_only=on` (TRUE token)
7. `active_only=off` (FALSE token)
8. invalid boolean → `422` (status-only)
9. `q` matches name (lowercase)
10. `q` matches name UPPERCASE
11. `q` matches mobile
12. `q` matches SKILL (`Transmission`)
13. `q` matches skill lowercase (`brakes`)
14. `q` partial substring on mobile
15. `q` no match → empty array
16. empty `q` ignored
17. `active_only` + `q` combined (skill)
18. cross-user isolation (u2 view)
19. owned `X-Company-Id` override
20. unowned `X-Company-Id` → default fallback
21. list no auth → `401`
22. list invalid bearer → `401`
23. list expired → `401`

DETAIL (10):
24. detail happy
25. detail extra fields preserved
26. detail INACTIVE mechanic STILL RETURNED
27. detail missing → `404`
28. detail cross-user → `404`
29. detail cross-company → `404`
30. detail owned `X-Company-Id` override → alt row
31. detail no auth → `401`
32. detail invalid bearer → `401`
33. detail expired → `401`

AGGREGATE:
34. zero Node business writes across ALL cases (19 tracked business collections including `mechanics`)

## Compare modes

* `full` — byte-identical JSON body between Python and Node.
* `status_only` — HTTP status only (invalid-boolean `422` case:
  FastAPI + Fastify emit different validation-error `detail`
  shapes; established precedent from Gates 6g / 6i / 6j / 6k).

## Run

```
cd /app/backend-node && npx tsc && cd /app
python3 backend-node/test/gate6l_parity/harness.py
```

Result JSON is written to `/tmp/gate6l_parity_results.json`.
