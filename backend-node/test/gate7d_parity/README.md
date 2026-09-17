# Gate 7d · PolicyChanges list · Live parity harness

Shadow target: `GET /api/policy-changes`

## Scope

Class-C read-only shadow of `backend/routers/policy_changes.py::list_policy_change_events`
(lines 484–494). Python handler:
```python
rows = await db.policy_change_events.find(q, {"_id": 0}).sort(
    "created_at", -1).to_list(max(1, min(200, int(limit))))
return {"items": rows, "total": len(rows)}
```

Zero writer hook / audit / backfill / recompute / FinTxn / approvals /
counters / idempotency / cross-collection reads on the GET path.

Writers remain Python-authoritative and OUT OF SCOPE:
- `POST /api/policy-changes/apply*` (various apply flows)
- `POST /api/policy-changes/{event_id}/revert`

## NEW parity axes for Gate 7d

| Axis | Detail |
|---|---|
| `limit` int coercion | Pydantic v2 `int_parsing` — accepts optional surrounding whitespace, optional `+`/`-` sign, digits only. Rejects `""`, `"1.5"`, `"abc"`, `"null"`, `"None"`, etc. |
| `limit` clamp | `max(1, min(200, int(limit)))` applied AFTER Pydantic accepts. Default 50. |
| Response envelope | Wrapped `{ "items": rows, "total": <int> }` — NOT a bare array. |
| Projection | `{ _id: 0 }` — removes `_id` ONLY. Preserves `user_id`. |
| Sort | `created_at` DESC. |
| `customer_id` | Optional[str], truthy → exact equality, blank/omitted → omit. |
| No 404 branch | No customer-existence pre-check. |

### `limit` 422 envelope (byte-verified Pydantic v2 2.13.4)

```json
{
  "detail": [{
    "type": "int_parsing",
    "loc": ["query", "limit"],
    "msg": "Input should be a valid integer, unable to parse string as an integer",
    "input": "<raw>",
    "url": "https://errors.pydantic.dev/2.13/v/int_parsing"
  }]
}
```

**Auth precedence**: 401 fires before 422 for unauthenticated requests
with malformed `limit`.

### Tie-order note

Python calls `.sort("created_at", -1)`. When two docs share the same
`created_at`, Mongo's tie-order is UNSPECIFIED. The parity harness uses
distinct timestamps only — no Node tie-breaker is manufactured.

## UAT data preservation

- Isolated DB: `trukvia_gate7d_parity_<unix_ts>`, dropped in `finally`.

## Ports

- Python (uvicorn): `8214`
- Node   (dist):    `8215`

## Run

```bash
cd /app/backend-node
npm run build
python test/gate7d_parity/harness.py
```

Results file: `/tmp/gate7d_parity_results.json`.

Exit code: `0` on all-pass zero-write; `1` on parity/zero-write violation;
`2` on process bring-up failure.

## Case matrix (24 cases + zero-write aggregate)

| #  | Description                                              | Expected |
|----|----------------------------------------------------------|----------|
|  1 | default (limit=50) · four active rows DESC               | 200 body |
|  2 | limit=1 · top row only                                   | 200 body |
|  3 | limit=200 · all active                                   | 200 body |
|  4 | limit=0 · clamp to 1                                     | 200 body |
|  5 | limit=-5 · clamp to 1                                    | 200 body |
|  6 | limit=201 · clamp to 200                                 | 200 body |
|  7 | limit=999 · clamp to 200                                 | 200 body |
|  8 | limit=+1 (url-encoded %2B1)                              | 200 body |
|  9 | limit surrounding whitespace                             | 200 body |
| 10 | limit=abc → 422 envelope                                 | 422 body |
| 11 | limit='' → 422 envelope                                  | 422 body |
| 12 | limit=1.5 → 422 envelope                                 | 422 body |
| 13 | limit=null → 422 envelope                                | 422 body |
| 14 | limit=None → 422 envelope                                | 422 body |
| 15 | customer_id omitted · all rows                           | 200 body |
| 16 | customer_id='' blank · omitted                           | 200 body |
| 17 | customer_id=cust-1 · only cust-1                         | 200 body |
| 18 | customer_id=unknown · empty                              | 200 body |
| 19 | no auth (precedes 422)                                   | 401 `Not authenticated` |
| 20 | invalid bearer                                           | 401 `Invalid session`   |
| 21 | expired bearer                                           | 401 `Session expired`   |
| 22 | owned X-Company-Id · co-a-alt                            | 200 body |
| 23 | unowned X-Company-Id · fallback                          | 200 body |
| 24 | cross-user · u2 · own rows only                          | 200 body |
| 25 | Node write events across all cases                       | 0        |

Body compare mode: `full` for every case. No relaxation.

## Observed results

Filled in at run time — see `/tmp/gate7d_parity_results.json`.
