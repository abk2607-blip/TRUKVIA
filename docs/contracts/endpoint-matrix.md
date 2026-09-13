# TRUKVIA · Endpoint Contract Matrix

**Contract tag:** `contract@v1.iter150j`
**Baseline commit:** `a327b83` (Iter150J lock)
**Source of truth:** runtime OpenAPI dump at `docs/contracts/openapi.v1.json` — this matrix is a curated companion.
**Rule:** every row here is a Node re-implementation target. New Python endpoints MUST update both this file and `openapi.v1.json` in the same PR.

## Column semantics

| Column | Meaning |
|---|---|
| `Method` | HTTP verb |
| `Route` | Path (all API routes prefixed `/api/`) |
| `Domain` | Owning module (matches `routers/*.py` name) |
| `R/W` | `R` = read-only · `W` = mutating |
| `Auth` | `bearer` = session token via `get_current_user` dep; `-` for non-auth routes |
| `Tenant` | `X-Company-Id` = scoped via `company._active_company_id`; `-` = user-scope only |
| `Idem` | `yes` = expects Bucket-B `Idempotency-Key` header (server dedupes) |
| `ApprovalGate` | Iter150J-gated writers show their `entity_kind`; `-` otherwise |
| `source_type` | If writer triggers `hook_after_source_write`, the source_type string; `-` otherwise |
| `Audit` | `audit_logs` = writes to the audit ledger (append-only) |

## Class-A rules for every row

- Auth `bearer`: HTTP `401` with `{"detail":"Not authenticated"}` on invalid session.
- Tenant `X-Company-Id`: cross-tenant `id` → HTTP `404` with route-specific `not found` detail (see `error-string-parity.md`).
- Idem `yes`: replay with same key returns the ORIGINAL response body byte-for-byte.
- ApprovalGate row: direct POST returns HTTP `409` `{"detail":"approval_required", ...}` when the tenant toggle is ON (see Iter150J invariants).

## Uncertainty markers

Rows are derived from the runtime OpenAPI export + static router inspection. Fields marked `-` (dash) are either not-applicable OR unverified via runtime dump. Any row needing manual confirmation should be tagged in a follow-up PR.

Non-writer routes (`GET`) show `Idem = -` because idempotency is a POST-only concept in Bucket-B.

---

**Total endpoints indexed:** 358

| Method | Route | Domain | R/W | Auth | Tenant | Idem | ApprovalGate | source_type | Audit |
|---|---|---|:-:|---|---|:-:|---|---|---|
| GET | `/api/` | api | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/admin/deploy-history` | admin | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/admin/deploy-readiness` | admin | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/admin/deploy-readiness/run-now` | admin | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/admin/iter127-duplicates` | admin | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/admin/save-health` | admin | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/admin/save-health/alert-config` | admin | R | bearer | X-Company-Id | - | - | - | - |
| PUT | `/api/admin/save-health/alert-config` | admin | W | bearer | X-Company-Id | - | - | - | audit_logs |
| GET | `/api/admin/save-health/alerts` | admin | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/admin/save-health/alerts/test` | admin | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| POST | `/api/admin/save-health/alerts/{fired_at}/ack` | admin | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/admin/save-health/auth-failures` | admin | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/admin/save-health/sparkline` | admin | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/ai/chat` | ai | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/ai/daily-digest` | ai | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/ai/insights` | ai | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/ai/insights/refresh` | ai | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| POST | `/api/ai/parse` | ai | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| POST | `/api/ai/parse-template` | ai | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| POST | `/api/ai/parse-trip` | ai | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| POST | `/api/ai/report` | ai | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/ai/sessions` | ai | R | bearer | X-Company-Id | - | - | - | - |
| DELETE | `/api/ai/sessions/{sid}` | ai | W | bearer | X-Company-Id | - | - | - | audit_logs |
| GET | `/api/ai/sessions/{sid}/messages` | ai | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/approvals` | approvals | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/approvals` | approvals | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/approvals/summary/pending` | approvals | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/approvals/{aid}` | approvals | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/approvals/{aid}/approve` | approvals | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| POST | `/api/approvals/{aid}/reject` | approvals | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| POST | `/api/approvals/{aid}/resubmit` | approvals | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| POST | `/api/approvals/{aid}/withdraw` | approvals | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/audit-logs` | audit-logs | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/auth/demo-login` | auth | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/auth/health` | auth | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/auth/logout` | auth | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/auth/me` | auth | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/auth/session` | auth | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/companies` | companies | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/companies` | companies | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| PUT | `/api/companies/{cid}` | companies | W | bearer | X-Company-Id | - | - | - | audit_logs |
| DELETE | `/api/companies/{cid}` | companies | W | bearer | X-Company-Id | - | - | - | audit_logs |
| POST | `/api/companies/{cid}/set-default` | companies | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/company` | company | R | bearer | X-Company-Id | - | - | - | - |
| PUT | `/api/company` | company | W | bearer | X-Company-Id | - | - | - | audit_logs |
| GET | `/api/company-bank-accounts` | company-bank-accounts | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/company-bank-accounts` | company-bank-accounts | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| PUT | `/api/company-bank-accounts/{bid}` | company-bank-accounts | W | bearer | X-Company-Id | - | - | - | audit_logs |
| POST | `/api/company-bank-accounts/{bid}/deactivate` | company-bank-accounts | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| POST | `/api/company-bank-accounts/{bid}/replace` | company-bank-accounts | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/company-bank-accounts/{bid}/reveal` | company-bank-accounts | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/company-bank-accounts/{bid}/set-primary` | company-bank-accounts | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| POST | `/api/company/logo` | company | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| DELETE | `/api/company/logo` | company | W | bearer | X-Company-Id | - | - | - | audit_logs |
| POST | `/api/credit-notes` | credit-notes | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/credit-notes` | credit-notes | R | bearer | X-Company-Id | - | - | - | - |
| PUT | `/api/credit-notes/{nid}` | credit-notes | W | bearer | X-Company-Id | - | - | - | audit_logs |
| GET | `/api/credit-notes/{nid}` | credit-notes | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/credit-notes/{nid}/cancel` | credit-notes | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| POST | `/api/credit-notes/{nid}/issue` | credit-notes | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/credit-notes/{nid}/pdf` | credit-notes | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/customers` | customers | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/customers` | customers | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/customers/bulk-reminder` | customers | R | bearer | X-Company-Id | - | - | - | - |
| PUT | `/api/customers/{cid}` | customers | W | bearer | X-Company-Id | - | - | - | audit_logs |
| DELETE | `/api/customers/{cid}` | customers | W | bearer | X-Company-Id | - | - | - | audit_logs |
| POST | `/api/customers/{cid}/add-payment` | customers | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/customers/{cid}/monthly-balances` | customers | R | bearer | X-Company-Id | - | - | - | - |
| PUT | `/api/customers/{cid}/reminder-pref` | customers | W | bearer | X-Company-Id | - | - | - | audit_logs |
| POST | `/api/customers/{cid}/share-statement` | customers | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/customers/{cid}/ship-sites` | customers | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/customers/{cid}/ship-sites` | customers | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| PUT | `/api/customers/{cid}/ship-sites/{sid}` | customers | W | bearer | X-Company-Id | - | - | - | audit_logs |
| DELETE | `/api/customers/{cid}/ship-sites/{sid}` | customers | W | bearer | X-Company-Id | - | - | - | audit_logs |
| GET | `/api/customers/{cid}/statement.pdf` | customers | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/customers/{cid}/transactions` | customers | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/dashboard` | dashboard | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/dashboard/expenditure-breakdown` | dashboard | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/dashboard/expenditure-detail` | dashboard | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/debit-notes` | debit-notes | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/debit-notes` | debit-notes | R | bearer | X-Company-Id | - | - | - | - |
| PUT | `/api/debit-notes/{nid}` | debit-notes | W | bearer | X-Company-Id | - | - | - | audit_logs |
| GET | `/api/debit-notes/{nid}` | debit-notes | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/debit-notes/{nid}/cancel` | debit-notes | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| POST | `/api/debit-notes/{nid}/issue` | debit-notes | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/debit-notes/{nid}/pdf` | debit-notes | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/diagnostics/build` | diagnostics | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/driver-payments/{pid}/correct` | driver-payments | W | bearer | X-Company-Id | yes | - | driver_payment (correction) | audit_logs |
| POST | `/api/driver-payments/{pid}/correct-amount` | driver-payments | W | bearer | X-Company-Id | yes | - | driver_payment (correction) | audit_logs |
| GET | `/api/driver-payments/{pid}/corrections` | driver-payments | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/driver-shortage-policies` | driver-shortage-policies | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/driver-shortage-policies` | driver-shortage-policies | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/driver-shortage-policies/resolve` | driver-shortage-policies | R | bearer | X-Company-Id | - | - | - | - |
| PUT | `/api/driver-shortage-policies/{pid}` | driver-shortage-policies | W | bearer | X-Company-Id | - | - | - | audit_logs |
| DELETE | `/api/driver-shortage-policies/{pid}` | driver-shortage-policies | W | bearer | X-Company-Id | - | - | - | audit_logs |
| GET | `/api/drivers` | drivers | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/drivers` | drivers | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| PUT | `/api/drivers/{did}` | drivers | W | bearer | X-Company-Id | - | - | - | audit_logs |
| DELETE | `/api/drivers/{did}` | drivers | W | bearer | X-Company-Id | - | - | - | audit_logs |
| GET | `/api/drivers/{did}/ledger` | drivers | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/drivers/{did}/ledger` | drivers | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/drivers/{did}/ledger/export` | drivers | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/drivers/{did}/ledger/monthly` | drivers | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/drivers/{did}/ledger/post-monthly-salary` | drivers | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| POST | `/api/drivers/{did}/ledger/settle` | drivers | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| DELETE | `/api/drivers/{did}/ledger/{eid}` | drivers | W | bearer | X-Company-Id | - | - | - | audit_logs |
| GET | `/api/drivers/{did}/payments` | drivers | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/drivers/{did}/payments` | drivers | W | bearer | X-Company-Id | yes | driver_payment | driver_payment | audit_logs |
| GET | `/api/drivers/{did}/salary-masters` | drivers | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/drivers/{did}/salary-masters` | drivers | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/drivers/{did}/salary-settlement-hint` | drivers | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/drivers/{did}/trips` | drivers | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/drivers/{did}/trips/export` | drivers | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/expenditure-types` | expenditure-types | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/expenditure-types` | expenditure-types | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| DELETE | `/api/expenditure-types/{tid}` | expenditure-types | W | bearer | X-Company-Id | - | - | - | audit_logs |
| GET | `/api/expenses` | expenses | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/expenses` | expenses | W | bearer | X-Company-Id | yes | - | expense | audit_logs |
| POST | `/api/expenses/bulk-operational` | expenses | W | bearer | X-Company-Id | yes | - | expense | audit_logs |
| GET | `/api/expenses/{eid}` | expenses | R | bearer | X-Company-Id | - | - | - | - |
| PUT | `/api/expenses/{eid}` | expenses | W | bearer | X-Company-Id | - | - | expense | audit_logs |
| DELETE | `/api/expenses/{eid}` | expenses | W | bearer | X-Company-Id | - | - | expense | audit_logs |
| PATCH | `/api/expenses/{eid}/fleet-card-vehicle` | expenses | W | bearer | X-Company-Id | - | - | expense | audit_logs |
| PUT | `/api/expenses/{eid}/quick-diesel` | expenses | W | bearer | X-Company-Id | - | - | expense | audit_logs |
| PATCH | `/api/expenses/{eid}/toll-trip` | expenses | W | bearer | X-Company-Id | - | - | expense | audit_logs |
| GET | `/api/files` | files | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/files/bulk-upload` | files | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/files/public/{obj_path}` | files | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/files/upload` | files | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/files/usage` | files | R | bearer | X-Company-Id | - | - | - | - |
| DELETE | `/api/files/{fid}` | files | W | bearer | X-Company-Id | - | - | - | audit_logs |
| GET | `/api/files/{fid}/download` | files | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/fin/accounts` | fin | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/fin/day-book` | fin | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/fin/day-closures` | fin | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/fin/day-closures` | fin | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/fin/day-closures/{close_date}` | fin | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/fin/day-closures/{close_date}/late-entries` | fin | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/fin/day-closures/{close_date}/reopen` | fin | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/fin/day-status` | fin | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/fin/fin-txn/{txid}` | fin | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/fin/reconciliation/domain/{domain_name}` | fin | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/fin/reconciliation/mismatch/{domain_name}/{key}` | fin | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/fin/reconciliation/summary` | fin | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/fin/reproject` | fin | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/fin/source-legs/{source_type}/{source_id}` | fin | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/fin/source/{source_type}/{source_id}` | fin | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/fuel` | fuel | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/fuel` | fuel | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| POST | `/api/fuel-import/commit` | fuel-import | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| POST | `/api/fuel-import/preview` | fuel-import | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/fuel-log` | fuel-log | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/fuel-manual` | fuel-manual | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/fuel/summary` | fuel | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/fuel/vehicle-maps` | fuel | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/fuel/vehicle-maps` | fuel | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| DELETE | `/api/fuel/vehicle-maps/{fvm_id}` | fuel | W | bearer | X-Company-Id | - | - | - | audit_logs |
| PUT | `/api/fuel/{fid}` | fuel | W | bearer | X-Company-Id | - | - | - | audit_logs |
| DELETE | `/api/fuel/{fid}` | fuel | W | bearer | X-Company-Id | - | - | - | audit_logs |
| GET | `/api/gstin/lookup` | gstin | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/invoices` | invoices | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/invoices` | invoices | W | bearer | X-Company-Id | yes | invoice | invoice | audit_logs |
| GET | `/api/invoices/next-preview` | invoices | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/invoices/overdue` | invoices | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/invoices/{iid}` | invoices | R | bearer | X-Company-Id | - | - | - | - |
| PUT | `/api/invoices/{iid}` | invoices | W | bearer | X-Company-Id | - | - | invoice | audit_logs |
| DELETE | `/api/invoices/{iid}` | invoices | W | bearer | X-Company-Id | - | - | invoice | audit_logs |
| GET | `/api/invoices/{iid}/notes` | invoices | R | bearer | X-Company-Id | - | - | - | - |
| PATCH | `/api/invoices/{iid}/override-number` | invoices | W | bearer | X-Company-Id | - | - | invoice | audit_logs |
| POST | `/api/invoices/{iid}/payments` | invoices | W | bearer | X-Company-Id | yes | - | invoice | audit_logs |
| GET | `/api/invoices/{iid}/pdf` | invoices | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/invoices/{iid}/share` | invoices | W | bearer | X-Company-Id | yes | - | invoice | audit_logs |
| GET | `/api/invoices/{iid}/ship-to` | invoices | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/mechanic-payments/{pid}/correct` | mechanic-payments | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| POST | `/api/mechanic-payments/{pid}/correct-amount` | mechanic-payments | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/mechanic-payments/{pid}/corrections` | mechanic-payments | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/mechanic-work-orders` | mechanic-work-orders | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/mechanic-work-orders` | mechanic-work-orders | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/mechanic-work-orders/{wid}` | mechanic-work-orders | R | bearer | X-Company-Id | - | - | - | - |
| PUT | `/api/mechanic-work-orders/{wid}` | mechanic-work-orders | W | bearer | X-Company-Id | - | - | - | audit_logs |
| DELETE | `/api/mechanic-work-orders/{wid}` | mechanic-work-orders | W | bearer | X-Company-Id | - | - | - | audit_logs |
| GET | `/api/mechanics` | mechanics | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/mechanics` | mechanics | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/mechanics/{mid}` | mechanics | R | bearer | X-Company-Id | - | - | - | - |
| PUT | `/api/mechanics/{mid}` | mechanics | W | bearer | X-Company-Id | - | - | - | audit_logs |
| DELETE | `/api/mechanics/{mid}` | mechanics | W | bearer | X-Company-Id | - | - | - | audit_logs |
| GET | `/api/mechanics/{mid}/ledger` | mechanics | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/mechanics/{mid}/ledger.pdf` | mechanics | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/mechanics/{mid}/outstanding-as-of` | mechanics | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/mechanics/{mid}/payments` | mechanics | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/mechanics/{mid}/payments` | mechanics | W | bearer | X-Company-Id | yes | mechanic_payment | mechanic_payment | audit_logs |
| PUT | `/api/mechanics/{mid}/payments/{pid}` | mechanics | W | bearer | X-Company-Id | - | - | - | audit_logs |
| DELETE | `/api/mechanics/{mid}/payments/{pid}` | mechanics | W | bearer | X-Company-Id | - | - | - | audit_logs |
| POST | `/api/mechanics/{mid}/reactivate` | mechanics | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/parties` | parties | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/parties` | parties | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| PUT | `/api/parties/{pid}` | parties | W | bearer | X-Company-Id | - | - | - | audit_logs |
| DELETE | `/api/parties/{pid}` | parties | W | bearer | X-Company-Id | - | - | - | audit_logs |
| GET | `/api/party-bank-accounts` | party-bank-accounts | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/party-bank-accounts` | party-bank-accounts | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| PUT | `/api/party-bank-accounts/{bid}` | party-bank-accounts | W | bearer | X-Company-Id | - | - | - | audit_logs |
| POST | `/api/party-bank-accounts/{bid}/deactivate` | party-bank-accounts | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| POST | `/api/party-bank-accounts/{bid}/replace` | party-bank-accounts | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/party-bank-accounts/{bid}/reveal` | party-bank-accounts | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/party-bank-accounts/{bid}/set-primary` | party-bank-accounts | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/payment-cashbook` | payment-cashbook | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/policy-changes` | policy-changes | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/policy-changes/apply` | policy-changes | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| POST | `/api/policy-changes/preview` | policy-changes | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| POST | `/api/policy-changes/{event_id}/revert` | policy-changes | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/products` | products | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/products` | products | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| PUT | `/api/products/{pid}` | products | W | bearer | X-Company-Id | - | - | - | audit_logs |
| DELETE | `/api/products/{pid}` | products | W | bearer | X-Company-Id | - | - | - | audit_logs |
| GET | `/api/public/invoice/{token}/pdf` | public | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/reminders/digest` | reminders | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/reminders/digest/run` | reminders | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/repair-events` | repair-events | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/repair-events` | repair-events | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/repair-events/{rid}` | repair-events | R | bearer | X-Company-Id | - | - | - | - |
| PUT | `/api/repair-events/{rid}` | repair-events | W | bearer | X-Company-Id | - | - | - | audit_logs |
| DELETE | `/api/repair-events/{rid}` | repair-events | W | bearer | X-Company-Id | - | - | - | audit_logs |
| GET | `/api/reports/balance-sheet` | reports | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/reports/cndn-register` | reports | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/reports/cndn-register.pdf` | reports | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/reports/cndn-register.xlsx` | reports | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/reports/gst-summary` | reports | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/reports/gstr1` | reports | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/reports/gstr1-9b` | reports | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/reports/gstr1-9b-offline.json` | reports | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/reports/gstr1-9b.pdf` | reports | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/reports/gstr1-9b.xlsx` | reports | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/reports/gstr1.json` | reports | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/reports/gstr1.pdf` | reports | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/reports/gstr1.xlsx` | reports | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/reports/halting` | reports | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/reports/halting-verify` | reports | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/reports/ledger` | reports | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/reports/ledger/pdf` | reports | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/reports/lr-register` | reports | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/reports/lr-register.pdf` | reports | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/reports/lr-register.xlsx` | reports | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/reports/pl` | reports | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/reports/supplier-pl` | reports | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/reports/supplier-statement` | reports | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/reports/supplier-statement.pdf` | reports | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/reports/supplier-statement/share` | reports | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/reports/suppliers` | reports | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/saved-trip-filters` | saved-trip-filters | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/saved-trip-filters` | saved-trip-filters | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| DELETE | `/api/saved-trip-filters/{fid}` | saved-trip-filters | W | bearer | X-Company-Id | - | - | - | audit_logs |
| GET | `/api/suppliers` | suppliers | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/suppliers` | suppliers | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/suppliers-dashboard` | suppliers-dashboard | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/suppliers/{sid}` | suppliers | R | bearer | X-Company-Id | - | - | - | - |
| PUT | `/api/suppliers/{sid}` | suppliers | W | bearer | X-Company-Id | - | - | - | audit_logs |
| DELETE | `/api/suppliers/{sid}` | suppliers | W | bearer | X-Company-Id | - | - | - | audit_logs |
| GET | `/api/suppliers/{sid}/ledger` | suppliers | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/suppliers/{sid}/outstanding` | suppliers | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/suppliers/{sid}/payments` | suppliers | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/suppliers/{sid}/payments` | suppliers | W | bearer | X-Company-Id | yes | supplier_payment | supplier_payment | audit_logs |
| PUT | `/api/suppliers/{sid}/payments/{pid}` | suppliers | W | bearer | X-Company-Id | - | - | - | audit_logs |
| DELETE | `/api/suppliers/{sid}/payments/{pid}` | suppliers | W | bearer | X-Company-Id | - | - | - | audit_logs |
| POST | `/api/suppliers/{sid}/reactivate` | suppliers | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/suppliers/{sid}/settlement-adjustments` | suppliers | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/suppliers/{sid}/vehicles` | suppliers | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/team` | team | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/team` | team | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/team/me` | team | R | bearer | X-Company-Id | - | - | - | - |
| PUT | `/api/team/{tid}` | team | W | bearer | X-Company-Id | - | - | - | audit_logs |
| DELETE | `/api/team/{tid}` | team | W | bearer | X-Company-Id | - | - | - | audit_logs |
| GET | `/api/templates` | templates | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/templates` | templates | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/templates/{tid}` | templates | R | bearer | X-Company-Id | - | - | - | - |
| PUT | `/api/templates/{tid}` | templates | W | bearer | X-Company-Id | - | - | - | audit_logs |
| DELETE | `/api/templates/{tid}` | templates | W | bearer | X-Company-Id | - | - | - | audit_logs |
| POST | `/api/toll-import/commit` | toll-import | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/toll-import/lookup` | toll-import | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/toll-import/preview` | toll-import | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| POST | `/api/toll-import/reconcile` | toll-import | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/trips` | trips | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/trips` | trips | W | bearer | X-Company-Id | yes | trip | trip_customer_receipt | audit_logs |
| POST | `/api/trips/bulk-all-copies-zip` | trips | W | bearer | X-Company-Id | yes | - | trip_customer_receipt | audit_logs |
| POST | `/api/trips/bulk-delete` | trips | W | bearer | X-Company-Id | yes | - | trip_customer_receipt | audit_logs |
| POST | `/api/trips/bulk-invoice-preflight` | trips | W | bearer | X-Company-Id | yes | - | trip_customer_receipt | audit_logs |
| POST | `/api/trips/bulk-regenerate-lr` | trips | W | bearer | X-Company-Id | yes | - | trip_customer_receipt | audit_logs |
| GET | `/api/trips/export` | trips | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/trips/from-template/{tid}` | trips | W | bearer | X-Company-Id | yes | - | trip_customer_receipt | audit_logs |
| POST | `/api/trips/import` | trips | W | bearer | X-Company-Id | yes | - | trip_customer_receipt | audit_logs |
| GET | `/api/trips/import/template` | trips | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/trips/lr/preview` | trips | W | bearer | X-Company-Id | yes | - | trip_customer_receipt | audit_logs |
| POST | `/api/trips/quick-repeat/{last_trip_id}` | trips | W | bearer | X-Company-Id | yes | - | trip_customer_receipt | audit_logs |
| GET | `/api/trips/recurring-suggestions` | trips | R | bearer | X-Company-Id | - | - | - | - |
| PUT | `/api/trips/{tid}` | trips | W | bearer | X-Company-Id | - | - | trip_customer_receipt | audit_logs |
| DELETE | `/api/trips/{tid}` | trips | W | bearer | X-Company-Id | - | - | trip_customer_receipt | audit_logs |
| GET | `/api/trips/{tid}` | trips | R | bearer | X-Company-Id | - | - | - | - |
| PATCH | `/api/trips/{tid}/customer-ref` | trips | W | bearer | X-Company-Id | - | - | trip_customer_receipt | audit_logs |
| POST | `/api/trips/{tid}/driver-recovery/override` | trips | W | bearer | X-Company-Id | yes | - | trip_customer_receipt | audit_logs |
| POST | `/api/trips/{tid}/duplicate` | trips | W | bearer | X-Company-Id | yes | - | trip_customer_receipt | audit_logs |
| GET | `/api/trips/{tid}/ewaybill` | trips | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/trips/{tid}/field-override` | trips | W | bearer | X-Company-Id | yes | - | trip_customer_receipt | audit_logs |
| GET | `/api/trips/{tid}/lr` | trips | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/trips/{tid}/lr/all-copies` | trips | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/trips/{tid}/regenerate-lr` | trips | W | bearer | X-Company-Id | yes | - | trip_customer_receipt | audit_logs |
| POST | `/api/trips/{tid}/share-lr` | trips | W | bearer | X-Company-Id | yes | - | trip_customer_receipt | audit_logs |
| POST | `/api/trips/{tid}/supplier-advance` | trips | W | bearer | X-Company-Id | yes | - | trip_customer_receipt | audit_logs |
| PUT | `/api/trips/{tid}/supplier-advance/{eid}` | trips | W | bearer | X-Company-Id | - | - | trip_customer_receipt | audit_logs |
| DELETE | `/api/trips/{tid}/supplier-advance/{eid}` | trips | W | bearer | X-Company-Id | - | - | trip_customer_receipt | audit_logs |
| POST | `/api/trips/{tid}/supplier-diesel` | trips | W | bearer | X-Company-Id | yes | - | trip_customer_receipt | audit_logs |
| PUT | `/api/trips/{tid}/supplier-diesel/{eid}` | trips | W | bearer | X-Company-Id | - | - | trip_customer_receipt | audit_logs |
| DELETE | `/api/trips/{tid}/supplier-diesel/{eid}` | trips | W | bearer | X-Company-Id | - | - | trip_customer_receipt | audit_logs |
| GET | `/api/vehicles` | vehicles | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/vehicles` | vehicles | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| POST | `/api/vehicles/bulk-import` | vehicles | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| POST | `/api/vehicles/bulk-import/preview` | vehicles | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/vehicles/bulk-import/sample.xlsx` | vehicles | R | bearer | X-Company-Id | - | - | - | - |
| PUT | `/api/vehicles/{vid}` | vehicles | W | bearer | X-Company-Id | - | - | - | audit_logs |
| DELETE | `/api/vehicles/{vid}` | vehicles | W | bearer | X-Company-Id | - | - | - | audit_logs |
| GET | `/api/vehicles/{vid}/cost-summary` | vehicles | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/vehicles/{vid}/cost-summary.pdf` | vehicles | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/vehicles/{vid}/cost-summary.xlsx` | vehicles | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/vehicles/{vid}/repair-history` | vehicles | R | bearer | X-Company-Id | - | - | - | - |
| PATCH | `/api/vehicles/{vid}/status` | vehicles | W | bearer | X-Company-Id | - | - | - | audit_logs |
| GET | `/api/vehicles/{vid}/status-audit` | vehicles | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/vendor-bills` | vendor-bills | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/vendor-bills` | vendor-bills | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/vendor-bills/{bid}` | vendor-bills | R | bearer | X-Company-Id | - | - | - | - |
| PUT | `/api/vendor-bills/{bid}` | vendor-bills | W | bearer | X-Company-Id | - | - | - | audit_logs |
| DELETE | `/api/vendor-bills/{bid}` | vendor-bills | W | bearer | X-Company-Id | - | - | - | audit_logs |
| POST | `/api/vendor-payments/{pid}/correct` | vendor-payments | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| POST | `/api/vendor-payments/{pid}/correct-amount` | vendor-payments | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/vendor-payments/{pid}/corrections` | vendor-payments | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/vendors` | vendors | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/vendors` | vendors | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/vendors/{vid}` | vendors | R | bearer | X-Company-Id | - | - | - | - |
| PUT | `/api/vendors/{vid}` | vendors | W | bearer | X-Company-Id | - | - | - | audit_logs |
| DELETE | `/api/vendors/{vid}` | vendors | W | bearer | X-Company-Id | - | - | - | audit_logs |
| GET | `/api/vendors/{vid}/ledger` | vendors | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/vendors/{vid}/ledger.pdf` | vendors | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/vendors/{vid}/outstanding-as-of` | vendors | R | bearer | X-Company-Id | - | - | - | - |
| GET | `/api/vendors/{vid}/payments` | vendors | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/vendors/{vid}/payments` | vendors | W | bearer | X-Company-Id | yes | vendor_payment | vendor_payment | audit_logs |
| PUT | `/api/vendors/{vid}/payments/{pid}` | vendors | W | bearer | X-Company-Id | - | - | - | audit_logs |
| DELETE | `/api/vendors/{vid}/payments/{pid}` | vendors | W | bearer | X-Company-Id | - | - | - | audit_logs |
| POST | `/api/vendors/{vid}/reactivate` | vendors | W | bearer | X-Company-Id | yes | - | - | audit_logs |
| GET | `/api/wallet-adjustments` | wallet-adjustments | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/wallet-adjustments` | wallet-adjustments | W | bearer | X-Company-Id | yes | - | wallet_adjustment | audit_logs |
| PUT | `/api/wallet-adjustments/{wa_id}` | wallet-adjustments | W | bearer | X-Company-Id | - | - | wallet_adjustment | audit_logs |
| DELETE | `/api/wallet-adjustments/{wa_id}` | wallet-adjustments | W | bearer | X-Company-Id | - | - | wallet_adjustment | audit_logs |
| POST | `/api/wallet-adjustments/{wa_id}/reverse` | wallet-adjustments | W | bearer | X-Company-Id | yes | - | wallet_adjustment | audit_logs |
| GET | `/api/wallet-recharges` | wallet-recharges | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/wallet-recharges` | wallet-recharges | W | bearer | X-Company-Id | yes | - | wallet_recharge | audit_logs |
| PUT | `/api/wallet-recharges/{wr_id}` | wallet-recharges | W | bearer | X-Company-Id | - | - | wallet_recharge | audit_logs |
| DELETE | `/api/wallet-recharges/{wr_id}` | wallet-recharges | W | bearer | X-Company-Id | - | - | wallet_recharge | audit_logs |
| GET | `/api/wallet-transfers` | wallet-transfers | R | bearer | X-Company-Id | - | - | - | - |
| POST | `/api/wallet-transfers` | wallet-transfers | W | bearer | X-Company-Id | yes | - | wallet_transfer | audit_logs |
| PUT | `/api/wallet-transfers/{wt_id}` | wallet-transfers | W | bearer | X-Company-Id | - | - | wallet_transfer | audit_logs |
| DELETE | `/api/wallet-transfers/{wt_id}` | wallet-transfers | W | bearer | X-Company-Id | - | - | wallet_transfer | audit_logs |


---

## Notes on ambiguous columns

- **Permission column omitted** from the auto-generated matrix because permission checks in the current code are executed inside route handlers (`_has(user, "perm")`) rather than declared via a Depends dependency. Owner-only routes (Day Closing, bank reveal, approve) rely on `ROLE_PERMISSIONS` + `approve_transactions` / `view_bank_account_full` / `manage_bank_accounts` — a per-route permission column is a Stage-3 curation task.
- **Financial-writer routes on `/api/wallet-*`, `/api/expenses`, `/api/vendor-bills`, `/api/mechanic-work-orders`, `/api/credit-debit-notes`, `/api/trips`, `/api/invoices`** all emit FinTxn projections via `hook_after_source_write`. Some rows above may not surface a `source_type` because the URL fragment does not carry the domain hint — see `services_fin_txn.py::SUPPORTED_SOURCE_TYPES` for the authoritative dispatch table.
- **Correction endpoints** (`/*/correct`, `/correct-amount`, `payment_reversal`) are financial writers but are NOT gated by the Iter150J approval middleware. They re-invoke `hook_after_source_write` to re-project legs deterministically.

## Follow-up work (post-Phase 1)

- Fill in per-row `permission` column by static analysis of `_has(user, ...)` call sites.
- Cross-link every writer row to its golden-fixture id (once fixture catalogue is captured under `backend/tests/fixtures/parity/`).
- Add a `phase` column indicating migration phase (3–9) responsible for porting each route.
