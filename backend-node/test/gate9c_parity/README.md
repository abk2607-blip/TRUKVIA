# Phase 4 · Gate 9c · X-Company-Id tenant parity (live)

Python authority: `request.headers.get("x-company-id")` in `company.py`, `routers/supplier_ledger.py` and
`approval_gate.py`. The server is Starlette on uvicorn 0.25 with h11 0.16, as pinned in `backend/requirements.txt`
(no httptools).
- It returns the FIRST raw occurrence.
- Header names match case-insensitively.
- The HTTP parser strips only SP/HTAB from values.
- The ownership lookup `{id, user_id}` runs next, then the default company, then the first company.

Node: `backend-node/src/tenant.ts::activeCompanyId`.
- It now reads the first `x-company-id` entry of `req.raw.rawHeaders`.
- `req.headers` joins duplicates as `"a, b"`, which is what caused the bug.
- A single header that contains a comma stays one literal value.
- There is no extra JS `trim()` (Python keeps NBSP).

`harness.py` seeds a throwaway database (`trukvia_gate9c_parity_<ts>`, dropped in `finally`).
- Every company-scoped collection has one `co-a` row and one `co-b` row, so the selected company shows up in the
  body.
- Param routes target the `co-b` entity.

It runs uvicorn and `node dist/server.js` against that database, with sessions shaped like real logins.

Matrix:
- **All routes:** all 66 allowlisted routes plus the deferred `saved-trip-filters` control, × 9 header variants.
  The variants are: none, single owned, dup b/a, dup a/b, identical dup, mixed-case dup names, the SINGLE literal
  `"co-b, co-a"`, dup with an unowned value first, and dup with an empty value first.
- **Edge cases:** 18 representative routes × 12 edge variants. These cover unowned, unknown, empty, SP/HTAB padding,
  NBSP, id casing, a comma with no space, unknown-first, owned-then-unowned, another header in between,
  whitespace-only first, and triple values.
- **Identities:** the same 18 routes × accountant, viewer, another user, a no-default-company user, an expired
  session and an invalid session.

Per case:
- status and raw body are byte-exact;
- content type matches, apart from the known Gate 9d `; charset=utf-8` item;
- the ownership-lookup filters on `companies` are equal on both servers (profiler, attributed by `appName`);
- no Node-attributed dbHash change. Late Python refresh writes are attributed to Python with profiler proof.

Global checks: zero Node writes, and the application collections are unchanged.

Failures that also happen identically with NO `X-Company-Id` header are reported as PRE-EXISTING and
header-independent. They are listed and never counted as a pass. They belong to older locked routes, out of scope
for 9c.

Run: `python backend-node/test/gate9c_parity/harness.py` (needs local MongoDB, the backend venv and
`npm run build`).

Result at lock: 1595 cases, 1586 passed, 0 tenant (header-dependent) failures.
- **Groups:** all-routes 585/594, deferred 9/9, edge 216/216, identity 774/774.
- **Lookups and data:** 987 ownership lookups compared, all equal. 49 of the 66 routes return different data for
  co-a and co-b.
- **Writes:** Node made 6971 operations, all reads, 0 writes. The application collections are unchanged.

9 PRE-EXISTING header-independent mismatches, all `GET /api/files/usage`:
- It is a user-only route. Python sends `"pct":0.0` and Node sends `"pct":0`, the Python float-serialisation
  finding.
- It happens identically with no header.

A pre-existing probe, not counted: `invoices/next-preview` without `invoice_date` returns 422 from both servers, but
the Pydantic v2 body differs from Node's (older route).

Both are reserved for a later older-route parity gate.

Known Gate 9d framework difference: 1375 responses differ only by the `; charset=utf-8` content-type suffix.
