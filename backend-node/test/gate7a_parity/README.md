# Gate 7a · WalletAdjustments list · Live parity harness

Shadow target: `GET /api/wallet-adjustments`

## Scope

Class-C read-only shadow of `backend/routers/wallet_adjustments.py::list_wallet_adjustments`
(lines 37–62). Python handler executes ONLY:

```python
rows = await db.wallet_adjustments.find(
    q, {"_id": 0, "user_id": 0}
).sort("date", -1).to_list(5000)
return rows
```

Zero writer hook / audit / backfill / recompute / FinTxn / approvals /
policy / counters / idempotency / cross-collection reads on the GET path.

Writers remain Python-authoritative and OUT OF SCOPE:
- `POST /api/wallet-adjustments`
- `PUT /api/wallet-adjustments/{wa_id}`
- `DELETE /api/wallet-adjustments/{wa_id}`
- `POST /api/wallet-adjustments/{wa_id}/reverse`

## NEW parity axis introduced by Gate 7a

**Query-string parsing** — the first Class-C gate that exercises query
parameters:

| Param             | Type          | Semantics                                             |
|-------------------|---------------|-------------------------------------------------------|
| `wallet_code`     | Optional[str] | truthy → exact string equality; no trim / no case fold |
| `date_from`       | Optional[str] | truthy → `date: {$gte: <s>}`; lexicographic, no datetime parse |
| `date_to`         | Optional[str] | truthy → `date: {$lte: <s>}`                          |
| `include_deleted` | bool = False  | Pydantic v2 bool coercion (see below)                 |

Blank string values (`?wallet_code=`, `?date_from=`, `?date_to=`) are
Python-falsy and therefore OMIT their predicate. `?include_deleted=`
(blank) is Pydantic-invalid → **422**.

### `include_deleted` bool coercion — Pydantic v2 (byte-verified 2.13.4)

- **True set**  : `true`, `True`, `TRUE`, `1`, `yes`, `Yes`, `YES`, `on`, `On`, `ON`
- **False set** : `false`, `False`, `FALSE`, `0`, `no`, `No`, `NO`, `off`, `Off`, `OFF`
- **Invalid**   : `""`, `FOO`, any other value → **HTTP 422** with the
  EXACT Pydantic v2 envelope:

```json
{
  "detail": [
    {
      "type": "bool_parsing",
      "loc": ["query", "include_deleted"],
      "msg": "Input should be a valid boolean, unable to interpret input",
      "input": "<raw value>",
      "url": "https://errors.pydantic.dev/2.13/v/bool_parsing"
    }
  ]
}
```

- **Omitted** → default `False`.
- **Auth precedence**: unauthenticated request always returns 401 —
  including when `include_deleted` is malformed.

### Filter assembly (mirrors Python line-for-line)

```
base = { user_id: uid, company_id: cid }
if not include_deleted:                base.is_deleted = { $ne: true }
if wallet_code:                        base.wallet_code = <value>
if date_from or date_to:
    rng = {}
    if date_from: rng.$gte = date_from
    if date_to:   rng.$lte = date_to
    base.date = rng
```

### Projection / sort / cap / response

- Projection: `{ _id: 0, user_id: 0 }` (strips both).
- Sort: `date` DESC.
- Limit: `.to_list(5000)` → Node `.limit(5000)`.
- Response: **bare JSON array** (no envelope). NO 404. NO cross-collection lookup.

## UAT data preservation

- Isolated DB name: `trukvia_gate7a_parity_<unix_ts>`.
- Dropped in `finally` regardless of pass/fail.
- Never touches `test_database` or any TRUKVIA UAT tenant / login.

## Ports

- Python (uvicorn): `8208`
- Node   (dist):    `8209`

Both processes started and torn down inside the harness.

## Run

```bash
cd /app/backend-node
npm run build           # ensure dist/server.js is fresh
python test/gate7a_parity/harness.py
```

Results file: `/tmp/gate7a_parity_results.json`.

Exit code:
- `0` — all cases PASS and zero Node write events.
- `1` — parity or zero-write violation.
- `2` — process bring-up failure.

## Case matrix (22 cases + zero-write aggregate)

| #  | Description                                              | Expected |
|----|----------------------------------------------------------|----------|
|  1 | default (include_deleted omitted → false)                | 200 body |
|  2 | include_deleted=true                                     | 200 body |
|  3 | include_deleted=false                                    | 200 body |
|  4 | include_deleted=TRUE                                     | 200 body |
|  5 | include_deleted=1                                        | 200 body |
|  6 | include_deleted=yes                                      | 200 body |
|  7 | include_deleted=off                                      | 200 body |
|  8 | include_deleted='' → 422 Pydantic bool_parsing envelope  | 422 body |
|  9 | include_deleted=FOO → 422 Pydantic bool_parsing envelope | 422 body |
| 10 | wallet_code=FUEL exact filter                            | 200 body |
| 11 | wallet_code='' → omitted                                 | 200 body |
| 12 | wallet_code=DOES_NOT_EXIST → 200 []                      | 200 body |
| 13 | date_from only · rows >= 2026-05-03                      | 200 body |
| 14 | date_to only · rows <= 2026-05-02                        | 200 body |
| 15 | both bounds · inclusive lexicographic range              | 200 body |
| 16 | blank date bounds · omitted                              | 200 body |
| 17 | no auth (auth precedes 422)                              | 401 `Not authenticated` |
| 18 | invalid bearer                                           | 401 `Invalid session`   |
| 19 | expired bearer                                           | 401 `Session expired`   |
| 20 | owned X-Company-Id override · co-a-alt                   | 200 body |
| 21 | unowned X-Company-Id · fallback to default               | 200 body |
| 22 | cross-user · u2 · own rows only                          | 200 body |
| 23 | Node write events across all cases                       | 0        |

**Body compare mode**: `full` for every case, including invalid-bool
422 cases (byte-exact Pydantic v2 envelope). No `status_only` relaxation
was required. If future Pydantic upgrades change the `url` version
segment (e.g. `2.14`), update the constant in
`src/routes/wallet-adjustments-list.ts` in a subsequent gate.

## Observed results

Filled in at implementation time by the harness output —
see `/tmp/gate7a_parity_results.json` after each run.
