# Gate 7l · Approval detail · Live parity harness

Shadow target: `GET /api/approvals/{aid}`

## Scope

Class-C read-only shadow of `backend/routers/approvals.py::api_get_approval`
(L59-63) + `backend/services_approvals.py::get_approval_detail` (L544-560).

Three sequential reads: `approvals.find_one` → (404 if missing) →
`approval_revisions.find(...).sort("revision_index", 1).to_list(200)` →
`approval_audits.find(...).sort("at", 1).to_list(500)`. Wrapper response
`{approval, revisions, audits}`.

Zero writes / audits / backfill / recompute / hooks. Approval writers
(`POST /approvals`, `POST /approvals/{aid}/{approve|reject|withdraw|resubmit}`)
remain Python-authoritative and OUT OF SCOPE.

## Parity axes

| Axis | Detail |
|---|---|
| Auth precedence | AUTH BEFORE path handling. 401 short-circuits before the primary approval read. |
| 401 literals | `Not authenticated` / `Invalid session` / `Session expired` |
| 404 literal | `{"detail": "Approval not found"}` |
| Tenant | Owned X-Company-Id override / unowned fallback / no-header default (locked `activeCompanyId`) |
| Primary filter | `{id: aid, user_id, company_id}` on `approvals` |
| Revisions filter | `{approval_id: aid, user_id, company_id}` on `approval_revisions`; sort `revision_index` ASC; cap 200 |
| Audits filter | `{approval_id: aid, user_id, company_id}` on `approval_audits`; sort `at` ASC; cap 500 |
| Projection | `{_id: 0}` on all three collections — **`user_id` PRESERVED** (contrast Gates 7a–7f) |
| Response | Wrapper object `{approval, revisions, audits}` — three keys |
| Static-route collision | Gate 7f `/api/approvals/summary/pending` remains reachable; Fastify prefers static routes over param — verified via case `aid=summary` reaching this handler |

## Ports

- Python (uvicorn): `8230`
- Node   (dist):    `8231`

## UAT data preservation

- Isolated DB: `trukvia_gate7l_parity_<unix_ts>`, dropped in `finally`.
- Never touches `test_database` or any TRUKVIA UAT tenant.

## Run

```bash
cd /app/backend-node
npm run build
python test/gate7l_parity/harness.py
```

Results: `/tmp/gate7l_parity_results.json`. Exit 0 on all-pass zero-write.

## Case matrix (12 cases + zero-write aggregate)

| # | Description | Expected |
|---|---|---|
| 1  | no bearer → 401 Not authenticated | 401 body |
| 2  | invalid bearer → 401 Invalid session | 401 body |
| 3  | expired bearer → 401 Session expired | 401 body |
| 4  | u1 apr-1 → wrapper (deep-equal 3-revision + 3-audit sorted result) | 200 body |
| 5  | u1 apr-2 → 1 revision, 0 audits | 200 body |
| 6  | nonexistent aid → 404 Approval not found | 404 body |
| 7  | cross-user u2 requesting u1 apr-1 → 404 | 404 body |
| 8  | u1 default co-a cannot see co-a-alt apr-alt → 404 | 404 body |
| 9  | owned X-Company-Id co-a-alt → apr-alt visible | 200 body |
| 10 | unowned X-Company-Id co-b → fallback co-a → apr-1 visible | 200 body |
| 11 | aid='summary' → 404 (not intercepted by 7f static route) | 404 body |
| 12 | u2 apr-u2 → own approval visible | 200 body |
| 13 | Node write events across all cases | 0 |

Body compare: `full` deep-equal for every case.

## Observed results

Filled in at run time — see `/tmp/gate7l_parity_results.json`.
