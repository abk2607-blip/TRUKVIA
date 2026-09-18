# Phase 4 · Gate 9b · Login identity + role parity (live)

Python authority: `backend/auth.py::get_current_user`. Node: `backend-node/src/auth.ts::authenticate`.

`harness.py` seeds a disposable DB (`trukvia_gate9b_parity_<ts>`, dropped in `finally`) with sessions shaped
exactly as `routers/auth_router.py` writes them at login (no role field), `users`, `team_members`, companies and
business rows. It then runs uvicorn and `node dist/server.js` against that DB and compares raw-socket responses
byte-exactly.

Identities: owner, accountant staff, viewer staff, inactive staff row, staff row without `role` (defaults to
accountant), a user with several team rows, a self-owner row, a missing user (401 "User not found"), a users doc
without `email` (500), a session with `user_id: None` or without `user_id` (500), a second tenant, a user without a
default company, and an expired session.

Routes (already locked): vendors list and detail, fin-txn detail, suppliers, customer ship-sites, company bank
accounts, party bank accounts, files (user-scoped), reminders digest (user-scoped). It also covers `expires_at`
string, None, missing and int variants; cookie/Bearer token forms; and staff with the `X-Company-Id` variants.

Checks per case:
- status and body are byte-exact;
- the auth read sequence (`user_sessions` → `users` → `team_members` filters) is equal per server, taken from the
  profiler by `appName`;
- no Node-attributed dbHash change (Python's refresh is quiesced first).

Global checks: zero Node writes, and application collections unchanged.

Known framework differences are reported, never used to pass a case. They are reserved for Gate 9d:
- a `; charset=utf-8` suffix on the older routes;
- Python's 500 body is plain text, Node's is Fastify JSON (status must still match).

Python-only writes (rolling session refresh, default-company repair) are listed separately.

Run: `python backend-node/test/gate9b_parity/harness.py` (needs local MongoDB, the backend venv, `npm run build`).
Result at lock: 155/155 PASS, Node writes 0, 373 auth read commands compared.
