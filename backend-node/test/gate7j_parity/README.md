# Gate 7j · Files usage summary · Live parity harness

Shadow target: `GET /api/files/usage`

## Scope

Class-C read-only shadow of `backend/routers/files.py::file_usage`
(L94-109).

Python (verbatim):
```python
@router.get("/files/usage")
async def file_usage(user=Depends(get_current_user)):
    docs = await db.files.find(
        {"user_id": user["user_id"], "is_deleted": False},
        {"_id": 0, "size": 1, "category": 1},
    ).to_list(5000)
    total = sum(int(d.get("size", 0) or 0) for d in docs)
    by_cat = {}
    for d in docs:
        c = d.get("category", "general")
        by_cat[c] = by_cat.get(c, 0) + int(d.get("size", 0) or 0)
    limit = 500 * 1024 * 1024  # 500MB soft cap
    return {
        "total_bytes": total,
        "limit_bytes": limit,
        "pct": round(min(100, total / limit * 100), 2) if limit else 0,
        "file_count": len(docs),
        "by_category": by_cat,
    }
```

Zero writer hook / audit / backfill / recompute / FinTxn / counters /
idempotency / cross-collection reads. NO object-store call on this GET path.

Files writers + object-store egress remain Python-authoritative and
OUT OF SCOPE.

## CRITICAL Gate 7j axes

| Axis | Detail |
|---|---|
| USER-ONLY scope | NO `activeCompanyId`; base filter `{user_id, is_deleted: false}`. Same-user rows across arbitrary `company_id` values aggregated together; cross-user excluded. |
| Deleted semantics | Exact `{is_deleted: False}` equality — missing / null / true all excluded (no `$ne` guard). |
| Size normalization | `int(d.get("size", 0) or 0)` — missing / None / 0 / False / "" → 0. Numeric values truncated toward zero. |
| Category default | `d.get("category", "general")` — **KEY-BASED default only** (missing key → "general"). Key present with value `null` / `""` / other string → that literal value used as the by_cat key. |
| by_category ordering | Insertion order preserved (Py 3.7+ dict, V8 string-key ordering). No explicit sort. |
| limit_bytes | Constant `500 * 1024 * 1024` = `524288000`. |
| pct | `round(min(100, total / limit * 100), 2)`. Python `round()` uses banker's rounding; Node uses `Math.round(x * 100) / 100`. Deterministic fixtures avoid `.5` boundary ambiguity. |
| Response shape | Exactly 5 top-level keys: `total_bytes`, `limit_bytes`, `pct`, `file_count`, `by_category`. No wrapper. |

## Query contract

No query parameters. No 422 surface.

## Ports

- Python (uvicorn): `8226`
- Node   (dist):    `8227`

## UAT data preservation

- Isolated DB: `trukvia_gate7j_parity_<unix_ts>`, dropped in `finally`.
- Never touches `test_database` or any TRUKVIA UAT tenant.

## Run

```bash
cd /app/backend-node
npm run build
python test/gate7j_parity/harness.py
```

Results file: `/tmp/gate7j_parity_results.json`.

Exit code: `0` on all-pass zero-write; `1` on parity/zero-write violation;
`2` on process bring-up failure.

## Case matrix (11 cases + zero-write aggregate)

| # | Description | Expected |
|---|---|---|
| 1  | no bearer → 401 Not authenticated | 401 body |
| 2  | invalid bearer → 401 Invalid session | 401 body |
| 3  | expired bearer → 401 Session expired | 401 body |
| 4  | u1 full aggregate — mixed categories, missing size, missing category, empty-string category, is_deleted=true excluded, missing is_deleted excluded | 200 body deep-equal |
| 5  | u1 + X-Company-Id co-a-alt MUST equal no-header aggregate (USER-ONLY proof) | 200 body ≡ case 4 |
| 6  | u1 + X-Company-Id co-b (unowned) MUST equal no-header aggregate | 200 body ≡ case 4 |
| 7  | cross-user u2 own aggregate | 200 body |
| 8  | u3 (no files) → zero-usage `{0, 524288000, 0, 0, {}}` | 200 body |
| 9  | Oversize file → pct capped at 100 | 200 body |
| 10 | Half-limit file → pct exact 50 (deterministic) | 200 body |
| 11 | 5000 read cap: 5001 tiny files → file_count 5000, total_bytes 5000 | 200 body |
| 12 | Node write events across all cases | 0 |

Body compare mode: `full` deep-equal for every case.

## Observed results

Filled in at run time — see `/tmp/gate7j_parity_results.json`.
