# Phase 3 · Gate 6q · Live Python↔Node parity harness

Covers exactly two read-only surfaces:

* `GET /api/templates`
* `GET /api/templates/{tid}`

## Data safety

* Isolated timestamped disposable DB: `trukvia_gate6q_parity_<timestamp>`.
* Dropped in `finally` regardless of pass/fail.
* Never touches `test_database`, `trukvia_uat`, or any real tenant.
* Never mutates login/account/company mapping.

## Class-C stance

Python handlers (`backend/routers/templates.py`, lines 16–23 and 39–45)
execute ONLY:

```python
# LIST
db.templates.find(
    {"company_id": cid, "is_active": True},
    {"_id": 0, "user_id": 0},
).sort("name", 1).to_list(500)

# DETAIL
db.templates.find_one(
    {"id": tid, "company_id": cid},
    {"_id": 0, "user_id": 0},
)
if not doc: raise HTTPException(404, "Template not found")
```

Zero writer hook, zero audit call, zero backfill, zero recompute, zero
FinTxn emission, zero approvals/policy/counters/idempotency
interaction, zero unrelated collection reads. Both stacks must produce
byte-identical JSON on every case and Node must record zero DB mutation.

## Preserved semantics (bind precisely — new dimensions vs prior gates)

| Dimension | Gate 6q (this gate) | Prior 6m–6p gates |
|-----------|---------------------|-------------------|
| Filter shape (LIST) | `{company_id, is_active:true}` — **NO user_id** | `{user_id, company_id, ...}` |
| Filter shape (DETAIL) | `{id, company_id}` — **NO user_id** | user-scoped |
| Projection | `{_id:0, user_id:0}` on BOTH | varies |
| Sort | `name` ASC on LIST | `created_at` DESC / `correction_index` ASC |
| Cap | LIST `.to_list(500)`; DETAIL none | `.to_list(500)` or none |
| 404 path | DETAIL missing/wrong-company → `{"detail":"Template not found"}` | mostly `200 []` |
| Cross-user access | **Same-company different-user templates visible** | strictly user-scoped |

Additionally:
* No query params. No body. No path-param validation on `tid`.
* Retired (`is_active:false`) rows excluded from LIST but still
  addressable via DETAIL by id.

## Cases (12 request cases + 1 aggregate)

1. list happy · `u1` default co-a · sorted name ASC, inactive excluded
2. detail 404 unknown tid · exact literal (covers empty/negative shape)
3. list · same-company different-user visibility · `u2` sees u1-authored co-a rows
4. list · cross-company isolation · `u3` default co-b · only its own rows
5. list · owned `X-Company-Id` override · `u1` → `co-a-alt` → `[t-alt]`
6. list · unowned `X-Company-Id` fallback · `u1` → `co-b` override → default `co-a`
7. detail happy · `u1` → `t-a1`
8. detail 404 unknown tid · `u1` → missing → exact literal
9. detail 404 wrong-company · `u1` → `t-b` in `co-b` → exact literal
10. no auth (LIST) → 401 `Not authenticated`
11. invalid bearer (LIST) → 401 `Invalid session`
12. expired session (LIST) → 401 `Session expired`

AGGREGATE:
13. zero Node business writes across ALL cases (tracked collections
    include `templates` plus 25 other business collections). Python's
    rolling-refresh writes to `user_sessions` are excluded from the
    Node-write diff by using the post-Python snapshot as the
    Node-baseline.

## Company-shared fixture

Fixtures seed the `companies` collection with **two rows for `co-a`** —
one owned by `u1` (default) and one owned by `u2` (default). This
matches the Python "company-shared" semantic (a template authored by
`u1` in `co-a` MUST be visible to `u2` because both users' active
company resolves to `co-a`), while preserving the `activeCompanyId()`
contract in both stacks unchanged.

## Compare mode

* `full` — structural JSON equality between Python and Node bodies
  (Python `dict == dict` treats key-order as insignificant).

## Ports

Python: `8187`  ·  Node: `8188`  (non-overlapping with prior gates 6m–6p).

## Run

```
cd /app/backend-node && npx tsc && cd /app
python3 backend-node/test/gate6q_parity/harness.py
```

Result JSON is written to `/tmp/gate6q_parity_results.json`.

## Writer boundary (Gate-7)

`POST /api/templates`, `PUT /api/templates/{tid}` and
`DELETE /api/templates/{tid}` (Python authoritative writers with
`insert_one` / `update_one` / `delete_one`) are OUT OF SCOPE for
Gate 6q and remain Python-authoritative until Gate 7 (Maker-Checker
framework).
