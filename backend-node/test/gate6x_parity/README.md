# TRUKVIA · Phase-3 · Gate-6x · MechanicPayment list read-only shadow — Parity Harness

**Endpoint under parity**
- `GET /api/mechanics/{mid}/payments`

**Python source of truth**
- `backend/routers/mechanics.py::list_mechanic_payments` (lines 152–160)

**Class**: C — pure read. GET handler executes ONLY
`db.mechanic_payments.find(...).sort([('date', -1)]).to_list(5000)`.
Zero writer hook / audit / backfill / recompute / FinTxn / approvals /
policy / counters / idempotency / cross-collection reads on the GET
path.

## Data isolation

- Isolated DB: `trukvia_gate6x_parity_<epoch>` — dropped in `finally`.
- Never touches `test_database` or any TRUKVIA UAT tenant / login.
- Ports: Python `8202`, Node `8203`.

## Bound Gate-6x dimensions

1. **Single soft-delete predicate** `is_deleted: {$ne: true}`:
   - `true` → EXCLUDED
   - `false` → included
   - missing → INCLUDED (MongoDB `$ne` matches missing keys)
   - `null` → included
2. **5000 cap** (matches Gate 6t/6u/6v/6w).
3. **`activeCompanyId()` consumed** — `X-Company-Id` owned override
   changes rowset; unowned / no-header falls back to default company.
4. **NO 404 / NO 422** — this LIST-scoped-to-mechanic endpoint performs
   NO `find_one` on mechanics. Unknown mid / wrong-company mid / no
   matching payments ALL return HTTP 200 with body `[]`.
5. **Path param** `mid: str` — plain string, no coercion, no trimming,
   no normalization, no ObjectId, no datetime conversion.
6. **No query parameters.**
7. **Sort** — `date` DESC (ISO string lexicographic).
8. **Projection** — `{_id: 0, user_id: 0}`.

## Cases

10 HTTP cases covering:
- happy list · mec-1 · co-a · [q1, q2] DESC (deleted excluded, alt-co hidden)
- empty · mec-empty (no payments) → 200 []
- unknown mechanic · no existence lookup → 200 []
- different mechanic · mec-2 → [q-mec2]
- cross-user · u2 · mec-1 → [q-u2]
- owned X-Company-Id override · co-a-alt → [q-alt]
- unowned X-Company-Id fallback · co-b for u1 → default co-a
- no-auth 401 `Not authenticated`
- invalid-bearer 401 `Invalid session`
- expired-bearer 401 `Session expired`

Plus zero-write aggregate: `node_write_events = 0` across all cases,
snapshotting every established business collection before/after each
request pair.

## How to run

```bash
cd /app
python3 backend-node/test/gate6x_parity/harness.py
```

Results are written to `/tmp/gate6x_parity_results.json`; the disposable
DB is dropped in `finally` even on failure.

## Parity exceptions

None. All 10 HTTP cases use full-body comparison. Byte-identical output
required. Any deviation → parity FAIL.

## Gate-7 boundary

`POST` / `PUT` / `DELETE` under `/api/mechanics/{mid}/payments*` remain
Python-authoritative and are strictly out of Gate-6x scope. They fire
`hook_after_source_write`, `_log_audit`, party-bank snapshot capture,
and company-bank source-snapshot capture — reserved for the
Maker-Checker port in Gate 7.
