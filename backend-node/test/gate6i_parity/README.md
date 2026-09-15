# Phase 3 · Gate 6i · Live Python↔Node parity harness

Covers exactly two read-only surfaces:

* `GET /api/expenses`
* `GET /api/expenses/{eid}`

## Data safety

* Isolated timestamped disposable DB: `trukvia_gate6i_parity_<timestamp>`.
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

* `$ne: true` on `is_deleted` / `is_reversed` — **only** literal
  boolean `true` is excluded. `false`, missing, `null`, `0`, `""` and
  every other non-`true` value remain visible.
* `include_cancelled` / `include_reversed` — FastAPI/Pydantic v2
  boolean tokens (`1 t true on yes` / `0 f false off n no`,
  case-insensitive). Invalid → `422`.
* `source_type` — CSV split → trim → drop empty parts.
  One remaining → equality; multiple → `$in`; zero → filter omitted.
* Date filters passed as raw ISO strings (lexicographic Mongo comparison).
* Projection `{_id: 0, user_id: 0}`; sort `date` DESC; cap 20 000.
* Detail miss → `404 { "detail": "Expense not found" }`.

## Cases

LIST (30 cases):
1. happy path (default guards)
2. `include_cancelled=true`
3. `include_reversed=true`
4. both include flags true
5. `trip_id` filter
6. `vehicle_id` filter
7. `repair_event_id` filter
8. `vendor_bill_id` filter
9. `mechanic_work_order_id` filter
10. `party_type` filter
11. `party_id` filter
12. `category` filter
13. `source_type` single equality
14. `source_type` CSV → `$in`
15. `source_type` empty → filter omitted
16. `source_type` CSV with padding + empty parts
17. `date_from` lower bound
18. `date_to` upper bound
19. both date bounds inclusive
20. cross-user isolation (u2 view)
21. owned `X-Company-Id` override
22. unowned `X-Company-Id` → default fallback
23. `include_reversed=YES` (TRUE token)
24. `include_reversed=0` (FALSE token)
25. `include_cancelled=t` (TRUE token)
26. `include_cancelled=off` (FALSE token)
27. invalid boolean → `422` (status-only compare; Python vs Fastify body shapes differ)
28. list no auth → `401`
29. list invalid bearer → `401`
30. list expired → `401`

DETAIL (11 cases):
31. detail happy path
32. detail extra fields preserved
33. detail missing → `404`
34. detail `is_deleted=true` → `404`
35. detail `is_deleted=null` → visible
36. detail cross-user → `404`
37. detail cross-company → `404`
38. detail owned `X-Company-Id` override → alt row accessible
39. detail no auth → `401`
40. detail invalid bearer → `401`
41. detail expired → `401`

AGGREGATE:
42. zero Node business writes across ALL cases

## Compare modes

* `full` — byte-identical JSON body between Python and Node.
* `status_only` — HTTP status only (invalid-boolean `422` case:
  FastAPI + Fastify emit different `detail` array shapes and both
  are internal-only validation error bodies).

## Run

```
cd /app/backend-node && npx tsc && cd /app
python3 backend-node/test/gate6i_parity/harness.py
```

Result JSON is written to `/tmp/gate6i_parity_results.json`.
