# Phase 3 · Gate 6k · Live Python↔Node parity harness

Covers exactly one read-only surface:

* `GET /api/suppliers`

Completes the Gate-6h-deferred Supplier pair. The detail endpoint
`GET /api/suppliers/{sid}` is owned by Gate 6h
(`backend-node/src/routes/company-supplier-reads.ts`, LOCKED).

## Data safety

* Isolated timestamped disposable DB: `trukvia_gate6k_parity_<timestamp>`.
* Dropped in `finally` regardless of pass/fail.
* Never touches `test_database`, `trukvia_uat`, or any real tenant.
* Never mutates login/account/company mapping.

## Class-C stance

Python `list_suppliers` is pure-read (`find` only). Aggregate
assertion: zero Node business writes across every case.

## Preserved semantics

* `active_only` — FastAPI/Pydantic v2 boolean tokens
  (`1 t true on yes` / `0 f false off n no`, case-insensitive).
  Missing → false. Invalid → `422`. True → `is_active: true` equality.
* `q` — truthy string builds `$or` regex over `name`, `mobile`,
  `contact_person` with `$options: 'i'`. Raw string passthrough
  (server-side Mongo evaluation). NO JS RegExp construction, NO
  escaping, NO normalization.
* Projection `{_id: 0, user_id: 0}`; sort `name` ASC; cap 20 000.

## Cases (22 request cases + 1 aggregate)

1. list happy path (default scope)
2. `active_only=true` → filters inactive
3. `active_only=false` → all suppliers
4. `active_only=YES` (TRUE token)
5. `active_only=0` (FALSE token)
6. `active_only=on` (TRUE token)
7. `active_only=off` (FALSE token)
8. invalid boolean → `422` (status-only compare per Gate 6i/6j precedent)
9. `q` matches name (lowercase)
10. `q` matches name UPPERCASE
11. `q` matches mobile
12. `q` matches contact_person
13. `q` partial substring
14. `q` no match → empty array
15. empty `q` → filter omitted
16. `active_only` + `q` combined
17. cross-user isolation (u2 view)
18. owned `X-Company-Id` override
19. unowned `X-Company-Id` → default fallback
20. no auth → `401`
21. invalid bearer → `401`
22. expired → `401`
23. zero Node business writes across ALL cases (18 tracked business collections)

## Compare modes

* `full` — byte-identical JSON body between Python and Node.
* `status_only` — HTTP status only (invalid-boolean `422` case:
  FastAPI + Fastify emit different validation-error `detail` shapes;
  precedent established from Gates 6g / 6i / 6j).

## Run

```
cd /app/backend-node && npx tsc && cd /app
python3 backend-node/test/gate6k_parity/harness.py
```

Result JSON is written to `/tmp/gate6k_parity_results.json`.
