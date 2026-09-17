# Gate 7b · WalletTransfers list · Live parity harness

Shadow target: `GET /api/wallet-transfers`

## Scope

Class-C read-only shadow of `backend/routers/wallet_transfers.py::list_wallet_transfers`
(lines 27–49). Python handler executes ONLY:

```python
rows = await db.wallet_transfers.find(
    q, {"_id": 0, "user_id": 0}
).sort("date", -1).to_list(5000)
return rows
```

Zero writer hook / audit / backfill / recompute / FinTxn / approvals /
policy / counters / idempotency / cross-collection reads on the GET path.

Writers remain Python-authoritative and OUT OF SCOPE:
- `POST /api/wallet-transfers`
- `PUT /api/wallet-transfers/{wt_id}`
- `DELETE /api/wallet-transfers/{wt_id}`

## Parity axes (STRICT SUBSET of Gate 7a — no new dimensions)

| Param             | Type          | Semantics                                             |
|-------------------|---------------|-------------------------------------------------------|
| `date_from`       | Optional[str] | truthy → `date: {$gte: <s>}`; lexicographic, no datetime parse |
| `date_to`         | Optional[str] | truthy → `date: {$lte: <s>}`                          |
| `include_deleted` | bool = False  | Pydantic v2 bool coercion (see below)                 |

Blank string values (`?date_from=`, `?date_to=`) are Python-falsy and
therefore OMIT their predicate. `?include_deleted=` (blank) is
Pydantic-invalid → **422**.

### `include_deleted` bool coercion — Pydantic v2 (2.13.4)

- **True set**  : `true`, `True`, `TRUE`, `1`, `yes`, `Yes`, `YES`, `on`, `On`, `ON`
- **False set** : `false`, `False`, `FALSE`, `0`, `no`, `No`, `NO`, `off`, `Off`, `OFF`
- **Invalid**   : `""`, `FOO`, any other value → **HTTP 422** with byte-exact envelope:

```json
{
  "detail": [{
    "type": "bool_parsing",
    "loc": ["query", "include_deleted"],
    "msg": "Input should be a valid boolean, unable to interpret input",
    "input": "<raw value>",
    "url": "https://errors.pydantic.dev/2.13/v/bool_parsing"
  }]
}
```

- **Omitted** → default `False`.
- **Auth precedence**: unauthenticated request always returns 401,
  including when `include_deleted` is malformed.

### Ignored extra parameters

- **NO `wallet_code` parameter** — the Python route does not accept it.
  Client-supplied `?wallet_code=WALLET_FUEL` MUST have zero effect on
  the result set (no filter, no 422).
- **Unknown extras** (e.g. `?foo=bar`) are silently ignored — matches
  FastAPI's default behaviour on undeclared query parameters.

### Filter assembly (mirrors Python line-for-line)

```
base = { user_id: uid, company_id: cid }
if not include_deleted:                base.is_deleted = { $ne: true }
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
- Response: **bare JSON array**. NO 404. NO envelope.

## UAT data preservation

- Isolated DB: `trukvia_gate7b_parity_<unix_ts>`, dropped in `finally`.
- Never touches `test_database` or any TRUKVIA UAT tenant / login.

## Ports

- Python (uvicorn): `8210`
- Node   (dist):    `8211`

Both processes started and torn down inside the harness.

## Run

```bash
cd /app/backend-node
npm run build           # ensure dist/server.js is fresh
python test/gate7b_parity/harness.py
```

Results file: `/tmp/gate7b_parity_results.json`.

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
|  8 | include_deleted='' → 422 Pydantic envelope               | 422 body |
|  9 | include_deleted=FOO → 422 Pydantic envelope              | 422 body |
| 10 | date_from only · rows >= 2026-05-03                      | 200 body |
| 11 | date_to only · rows <= 2026-05-02                        | 200 body |
| 12 | both bounds · inclusive range                            | 200 body |
| 13 | blank date bounds · omitted                              | 200 body |
| 14 | no auth (auth precedes 422)                              | 401 `Not authenticated` |
| 15 | invalid bearer                                           | 401 `Invalid session`   |
| 16 | expired bearer                                           | 401 `Session expired`   |
| 17 | owned X-Company-Id override · co-a-alt                   | 200 body |
| 18 | unowned X-Company-Id · fallback to default               | 200 body |
| 19 | cross-user · u2 · own rows only                          | 200 body |
| 20 | unknown extra param `foo=bar` ignored                    | 200 body |
| 21 | `wallet_code=WALLET_FUEL` ignored (not defined on route) | 200 body |
| 22 | empty result · far-future date_from → 200 []             | 200 body |
| 23 | Node write events across all cases                       | 0        |

**Body compare mode**: `full` for every case, including the two invalid-bool
422 cases (byte-exact Pydantic v2 envelope). No `status_only` relaxation.

## Observed results

Filled in at implementation time by the harness output — see
`/tmp/gate7b_parity_results.json`.
