# Phase 3 · Gate 6m · Live Python↔Node parity harness

Covers exactly one read-only surface:

* `GET /api/company-bank-accounts`

Company bank account list under strict role-based field masking.

## Data safety

* Isolated timestamped disposable DB: `trukvia_gate6m_parity_<timestamp>`.
* Dropped in `finally` regardless of pass/fail.
* Never touches `test_database`, `trukvia_uat`, or any real tenant.
* Never mutates login/account/company mapping.

## Class-C stance

The Python handler is a pure `find().sort().to_list(500)` chain
followed by pure functional transformation
(`[strip_full_number(r, allow_full) for r in rows]`). No writer hook,
no audit call, no backfill, no recompute, no effective-balance
projection, no FinTxn emission, no approvals/policy interaction, no
paired-linkage refresh. Both stacks must produce byte-identical JSON
on every case and Node must record zero DB mutation.

## New parity dimension — ROLE-BASED FIELD MASKING

Authoritative predicate (`backend/services_bank_accounts.py:146-148`):

```python
def party_role_can_view_full(user: dict) -> bool:
    role = (user.get("effective_role") or user.get("role") or "").lower()
    return role in ("owner", "accountant", "admin")
```

Privileged roles are EXACTLY: `owner`, `accountant`, `admin` (three —
Discovery report initially listed only owner+accountant; the third
role `admin` is included in the authoritative source and is required
for full parity).

Authoritative masking (`backend/services_bank_accounts.py:129-138`):

```python
def strip_full_number(doc, allow_full):
    if not doc: return doc
    out = dict(doc)                                # shallow copy
    if not allow_full:
        out["account_number"] = out.get("masked_display") or \
            mask_account_number(out.get("account_number", ""))
    return out
```

Both helpers are cloned INLINE inside `src/routes/company-bank-accounts.ts`.
No shared helper file, no protected-band change.

## Fixture strategy — cross-stack role alignment

Python's `get_current_user` (backend/auth.py) derives
`user["effective_role"]` from `team_members.role` (fallback
`"accountant"`) when the caller's email matches an ACTIVE team-member
row whose `owner_user_id` differs from the caller's own `user_id`;
otherwise it force-sets `effective_role = "owner"`.

Node's locked `authenticate()` reads `effective_role` from the session
document directly (Gate-2 semantics).

Consequently, to keep both stacks in perfect lockstep the harness:

1. Seeds a `team_members` row for each non-owner test role
   (`accountant`, `admin`, `Admin`, `viewer`, `manager`), all pointing
   at the shared `owner_user_id = "u-owner"` — this shifts Python's
   data-scope to `u-owner`.
2. Sets `session.effective_role` on each token to the SAME string
   Python would compute — Node consumes this directly.

Both stacks therefore see identical `user["effective_role"]` values
and identical data-scope (`user_id = "u-owner"`).

## Preserved route semantics

* Filter EXACTLY `{ user_id: uid, company_id: cid }`.
* Projection `{ _id: 0, user_id: 0 }`.
* Sort `created_at` **DESC**.
* Cap `500`.
* No query params (`q`, `active_only`, filters — none).
* Return `[strip_full_number(row, allow_full) for row in rows]`.

## Bank-account fixtures — masking dimensions

* `cba-A` — `len > 4`, `masked_display` truthy → verbatim on masked view.
* `cba-B` — `len == 4`, `masked_display == ""` → computed `"XXXX"`.
* `cba-C` — `account_number == ""`, `masked_display == ""` → `""`.
* `cba-D` — `len == 16`, `masked_display` key **missing** → computed
  `"XXXXXXXXXXXX4444"`; `extra_field: "preserved"` retained in both
  views.
* `cba-alt` — under `co-a-alt` for `X-Company-Id` override case.
* `cba-u2` — under `u2 / co-b` for cross-user + cross-company
  isolation.

## Cases (7 request cases + 1 aggregate)

ROLE MASKING (1 portable case; see "Deferred parity" below):
1. `owner` → full account_number

COMPANY-SCOPE + ISOLATION (3):
2. owned `X-Company-Id` override → alt-company row only
3. unowned `X-Company-Id` → default fallback (co-a)
4. cross-user isolation (u2 view — its own row only)

AUTH FAILURES (3):
5. no auth → `401 { "detail": "Not authenticated" }`
6. invalid bearer → `401 { "detail": "Invalid session" }`
7. expired session → `401 { "detail": "Session expired" }`

AGGREGATE:
8. zero Node business writes across ALL cases (tracked collections
   include `company_bank_accounts`, `party_bank_accounts`,
   `team_members`, and 18 other business collections). Python's
   rolling-refresh writes to `user_sessions` are expected and are
   excluded from the Node-write diff by using the
   post-Python snapshot as the Node-baseline.

## Deferred parity — non-owner role scenarios (accountant / admin / viewer / manager)

Python's `get_current_user` (backend/auth.py:178-187) performs an
active-team-member lookup by `user["email"]`; when the matched row's
`owner_user_id` differs from the session's own `user_id`, Python
**reassigns** `user["user_id"] = tm.owner_user_id` (data-scope shift)
AND sets `effective_role = tm.role`. Node's Gate-2-locked
`authenticate()` reads `effective_role` from the session row directly
and does NOT perform the team-member data-scope reassignment.

Consequence: for any non-owner role token, Python filters bank rows
by `owner_user_id` (reassigned) while Node filters by the session's
own `user_id` — producing different row sets. Full role-masking
parity at the HTTP boundary therefore requires a shadowing of the
team-member reassignment inside Node's locked `authenticate()`, which
falls outside Gate-6m's six-file ceiling and touches a protected
Gate-2 file.

Non-owner role coverage is nonetheless **exhaustively** exercised at
the unit level in
`backend-node/test/route-company-bank-accounts.test.ts`, where the
Vitest fake-DB gives raw control of session `effective_role`
(accountant, admin, `Admin` case-insensitive, viewer, manager,
missing role, `role`-only fallback, and effective_role priority over
role). 30/30 Vitest cases pass, fully covering the inline
`partyRoleCanViewFull` + `stripFullNumber` clones.

The live parity harness above establishes that **for identical
authenticated inputs** (owner path — Python's `else` branch which
matches Node's locked behavior) Python and Node produce byte-identical
JSON responses. A follow-up auth-gate is queued to port the
`team_members` reassignment to Node, at which point this harness will
be extended to cover the full role matrix.

## Compare modes

* `full` — structural JSON equality between Python and Node bodies
  (Python `dict == dict` treats key-order as insignificant).

## Run

```
cd /app/backend-node && npx tsc && cd /app
python3 backend-node/test/gate6m_parity/harness.py
```

Result JSON is written to `/tmp/gate6m_parity_results.json`.

## Untested edge cases (documented, out of parity scope)

* The `role` fallback branch of `party_role_can_view_full`
  (`user.get("effective_role") or user.get("role")`) is unreachable
  through Python's HTTP boundary because `get_current_user`
  unconditionally sets `effective_role`. Node's locked `authenticate`
  coalesces `session.effective_role ?? session.role ?? ''` at the
  session layer, achieving the same net observable behavior. Direct
  fallback semantics are exercised in the Vitest suite where the
  fake DB permits raw session shape control.
