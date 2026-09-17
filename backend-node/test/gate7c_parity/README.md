# Gate 7c · WalletRecharges list · Live parity harness

Shadow target: `GET /api/wallet-recharges`

## Scope

Class-C read-only shadow of `backend/routers/wallet_recharges.py::list_wallet_recharges`
(lines 28–53). Contract IDENTICAL LINE-FOR-LINE to Gate 7a
wallet-adjustments except for the collection name (`wallet_recharges`)
and the route path. Zero new parity dimensions.

Python handler executes ONLY:
```python
rows = await db.wallet_recharges.find(
    q, {"_id": 0, "user_id": 0}
).sort("date", -1).to_list(5000)
return rows
```

Writers remain Python-authoritative and OUT OF SCOPE:
- `POST /api/wallet-recharges`
- `PUT /api/wallet-recharges/{wr_id}`
- `DELETE /api/wallet-recharges/{wr_id}`

## Parity axes (all inherited from Gate 7a — no new dimensions)

| Param             | Type          | Semantics                                             |
|-------------------|---------------|-------------------------------------------------------|
| `wallet_code`     | Optional[str] | truthy → exact string equality; blank/omitted → OMIT  |
| `date_from`       | Optional[str] | truthy → `date: {$gte}`; lexicographic, no datetime parse |
| `date_to`         | Optional[str] | truthy → `date: {$lte}`                               |
| `include_deleted` | bool = False  | Pydantic v2 bool coercion (byte-exact envelope on 422)|

### `include_deleted` bool coercion — Pydantic v2 (2.13.4)

- **True set**  : `true`, `True`, `TRUE`, `1`, `yes`, `Yes`, `YES`, `on`, `On`, `ON`
- **False set** : `false`, `False`, `FALSE`, `0`, `no`, `No`, `NO`, `off`, `Off`, `OFF`
- **Invalid**   : `""`, `FOO`, other → **HTTP 422** byte-exact envelope
  (matches Gate 7a exactly, url points to `.../2.13/v/bool_parsing`).
- **Omitted** → default `False`.
- **Auth precedence**: unauthenticated request always returns 401.

## UAT data preservation

- Isolated DB: `trukvia_gate7c_parity_<unix_ts>`, dropped in `finally`.

## Ports

- Python (uvicorn): `8212`
- Node   (dist):    `8213`

## Run

```bash
cd /app/backend-node
npm run build
python test/gate7c_parity/harness.py
```

Results file: `/tmp/gate7c_parity_results.json`.

Exit code: `0` on all-pass zero-write; `1` on parity/zero-write violation; `2` on process bring-up failure.

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
|  8 | include_deleted='' → 422 envelope                        | 422 body |
|  9 | include_deleted=FOO → 422 envelope                       | 422 body |
| 10 | wallet_code=WALLET_FUEL exact filter                     | 200 body |
| 11 | wallet_code='' → omitted                                 | 200 body |
| 12 | wallet_code=NON_EXISTENT → 200 []                        | 200 body |
| 13 | date_from only                                           | 200 body |
| 14 | date_to only                                             | 200 body |
| 15 | both bounds · inclusive                                  | 200 body |
| 16 | blank date bounds omitted                                | 200 body |
| 17 | no auth (precedes 422)                                   | 401 `Not authenticated` |
| 18 | invalid bearer                                           | 401 `Invalid session`   |
| 19 | expired bearer                                           | 401 `Session expired`   |
| 20 | owned X-Company-Id · co-a-alt                            | 200 body |
| 21 | unowned X-Company-Id · fallback                          | 200 body |
| 22 | cross-user · u2 · own rows only                          | 200 body |
| 23 | Node write events across all cases                       | 0        |

**Body compare mode**: `full` for every case (including 422). No relaxation.

## Observed results

Filled in at implementation time by the harness — see `/tmp/gate7c_parity_results.json`.
