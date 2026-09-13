# TRUKVIA · Error String Parity (Frontend-observable literals)

**Contract tag:** `contract@v1.iter150j`
**Class:** All entries are **Class-A** unless annotated otherwise. Any drift triggers automatic route rollback in the migration harness.
**Rule:** Node re-implementation MUST reproduce these exact HTTP status codes AND exact `detail` string literals.

The frontend's interceptor and toast layers are string-matched against these values. Rephrasing an error is a Class-A break.

## 1 · Approval framework (Iter150J)

| # | Trigger | HTTP status | Response body (essential fields) | Frontend dependency | Class |
|--:|---|:-:|---|---|:-:|
| 1 | Writer POST blocked by `ApprovalGateMiddleware` when tenant toggle is ON | **409** | `{"detail":"approval_required","approval_required":true,"entity_type":"driver","entity_kind":"driver_payment","party_id":"drv_...","writer_url":"/api/drivers/{did}/payments","method":"POST","redirect":"/api/approvals"}` | `frontend/src/api.js:263-273` — interceptor 409 branch tests `detail === "approval_required"` (lowercased) OR `approval_required === true` | A |
| 2 | Approve endpoint invoked by maker of the same approval | **403** | `{"detail":"Maker cannot approve own submission"}` | Approval detail dialog toast + Jest tests | A |
| 3 | Approve invoked by user without `approve_transactions` permission | **403** | `{"detail":"Not permitted to approve"}` | Detail dialog error path | A |
| 4 | Submit invoked by user without submit/approve permission | **403** | `{"detail":"Not permitted to submit approvals"}` | Detail dialog error path | A |
| 5 | Reject called with empty `reason` | **400** | `{"detail":"reason is required"}` OR (service-level) `{"detail":"Rejection reason is required"}` | Detail dialog input validation | A |
| 6 | Resubmit called with empty `payload` | **400** | `{"detail":"payload is required"}` | Detail dialog resubmit form | A |
| 7 | Second approve on already-advanced approval | **409** | `{"detail":"Approval already advanced"}` | Detail dialog concurrent-action toast | A |
| 8 | Detail read for unknown / cross-tenant approval id | **404** | `{"detail":"Approval not found"}` | Detail dialog navigation | A |
| 9 | Withdraw called from status other than PENDING_APPROVAL | **409** | `{"detail":"Cannot withdraw from status <STATUS>"}` | Toast | A |
| 10 | Reject called from status other than PENDING_APPROVAL | **409** | `{"detail":"Cannot reject from status <STATUS>"}` | Toast | A |
| 11 | Edit-and-resubmit called from status other than REJECTED/WITHDRAWN | **409** | `{"detail":"Cannot edit-and-resubmit from status <STATUS>"}` | Toast | A |
| 12 | Withdraw by non-maker without approve permission | **403** | `{"detail":"Only the maker (or an owner) may withdraw"}` | Toast | A |
| 13 | Resubmit by user other than original maker | **403** | `{"detail":"Only the original maker may edit-and-resubmit"}` | Toast | A |
| 14 | `entity_kind` missing on approval create | **400** | `{"detail":"entity_kind is required"}` | Interceptor error path (should never fire under normal reroute) | A |
| 15 | `payload` not an object on approval create | **400** | `{"detail":"payload must be an object"}` | Interceptor error path | A |

## 2 · Authentication / session

| # | Trigger | HTTP status | Response body | Frontend dependency | Class |
|--:|---|:-:|---|---|:-:|
| 16 | Missing or invalid bearer / expired session on `/api/auth/me` | **401** | `{"detail":"Not authenticated"}` (or FastAPI default) | `api.js:336` rolling-refresh guard (`_retriedAuthMe`) | A |
| 17 | Foreign `X-Company-Id` (not owned by user) | Falls through to route default OR **404** on the target lookup | route-dependent | Company-picker fallback logic | A |
| 18 | Demo-token bypass when `ENABLE_DEMO_TOKEN=false` | **401** | `{"detail":"Not authenticated"}` | Must be off in production tenants | A |

## 3 · Idempotency (Bucket-B)

| # | Trigger | HTTP status | Response body | Class |
|--:|---|:-:|---|:-:|
| 19 | POST replay with same `Idempotency-Key` | **200 / 201** (identical to original) | ORIGINAL body byte-for-byte | A |
| 20 | POST replay with same key but body-hash mismatch | **409** | `{"detail":"Idempotency-Key conflict"}` (see `idempotency.py` for exact form) | A |

## 4 · Tenant / permission gates (financial writers)

| # | Trigger | HTTP status | Response body | Class |
|--:|---|:-:|---|:-:|
| 21 | Owner-only endpoint invoked by non-owner (Day Closing) | **403** | `{"detail":"..."}` (route-specific — capture verbatim in openapi.v1.json) | A |
| 22 | Cross-company entity id (writer targets an id belonging to another tenant) | **404** | `{"detail":"... not found in tenant"}` (route-specific literal) | A |
| 23 | Bank-full reveal without `view_bank_account_full` | **403** | route-specific `detail` | A |

## 5 · Silent-restart / save-health (preview-mode)

| # | Trigger | Mechanism | Frontend dependency | Class |
|--:|---|---|---|:-:|
| 24 | Backend restart during a session | Backend writes to `save_health` collection; frontend polls | `SilentRestartToast.jsx` — depends on save-health poll shape | C (preview only) |

## 6 · General

| # | Rule | Class |
|--:|---|:-:|
| 25 | All error responses use the shape `{"detail": "..."}` (FastAPI HTTPException convention). Node re-implementation MUST NOT switch to RFC-7807 `application/problem+json` — the interceptor does not parse it. | A |
| 26 | Error `detail` MUST NOT be internationalised (Node's built-in i18n MUST NOT translate). Toast layer performs any translation. | A |
| 27 | All 4xx responses set `Content-Type: application/json`. | A |
| 28 | CORS preflight (`OPTIONS`) returns `204` with the CORS response headers from `CORS_ORIGINS` env. | B |

## 7 · Header / cookie contract

| # | Header / cookie | Behaviour | Class |
|--:|---|---|:-:|
| 29 | `Set-Cookie: session_token=...; HttpOnly; SameSite=Lax; Path=/` | Cookie name and attrs frozen | A |
| 30 | `Idempotency-Key` request header | Case-insensitive read, canonical case on echo | A |
| 31 | `X-Company-Id` request header | Read case-insensitively; validated against `{id, user_id}` on `companies` | A |
| 32 | `Authorization: Bearer <token>` request header | Preferred over cookie when both present | A |

## Capture rule

Every literal above appears in the current Python source at HEAD `a327b83`. If any Node port is unable to reproduce a literal exactly (case, punctuation, spelling), that route is BLOCKED from cutover.

Any new error string added by future Python work MUST be added to this document in the same PR, or the frontend-observable contract is deemed to have silently drifted.
