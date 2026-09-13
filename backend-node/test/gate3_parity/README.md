# Phase 3 · Gate 3 · Live Python ↔ Node parity harness

**Scope:** proves live cross-stack behavioural parity for exactly ONE endpoint —
`GET /api/supplier-payments/{pid}/corrections` — against the same isolated
MongoDB database, using deterministic fixtures.

**Not a general framework.** Purpose-built for this one route. When Gate 4
lands, we add a second harness file next to this one; we don't try to
generalise until at least 3 routes exist.

## What it does

1. Picks a fresh isolated DB name (`trukvia_gate3_parity_<epoch>`).
2. Seeds `user_sessions`, `companies`, and `payment_corrections` deterministically.
3. Starts:
   - A second Python `uvicorn` instance on port **8101** pointed at the isolated DB
     (the supervisor-managed Python on 8001 is untouched).
   - The Node `dist/server.js` on port **8102** pointed at the same isolated DB.
4. For each parity case, issues **identical HTTP requests** to both, captures
   status + JSON body + headers, and diffs them.
5. For each Node request: snapshots the DB state before/after and asserts
   **zero write-side change** on the corrections/companies/sessions collections.
6. Also captures Python `last_refreshed_at` deltas (the one intentional
   Python-only writeback documented at Gate 2). Response body must not
   diverge.
7. Prints a PASS / FAIL matrix.
8. Tears down: stops both processes, drops the isolated DB.

## Running

```
python3 backend-node/test/gate3_parity/harness.py
```

The harness owns the whole lifecycle. It does not require any pre-started
process besides the container's MongoDB (already provided by supervisor).

## What it does NOT do

- Does not modify supervisor.
- Does not modify production ingress.
- Does not touch the supervisor-managed Python backend.
- Does not touch `main`, `backend/**`, `frontend/**`, or `docs/contracts/**`.
- Does not add production dependencies.
- Does not commit anything.
