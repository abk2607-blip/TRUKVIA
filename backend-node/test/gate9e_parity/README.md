# Phase 4 · Gate 9e · Older-route parity cleanup (live)

Every fix below was reproduced live against Python first: 63 differences in the pre-fix probe, plus 14 routes that
differed at the cap boundary. Each fix changes only a representation or read-mechanics mismatch. No business
calculation changed.

## Fixes

**A. `GET /api/files/usage`**
- **File:** `src/routes/files-usage-list.ts`
- **Before:** `"pct":0` (Python `0.0`), `100` (Python `100.0` below the cap), `0.13` (Python half-even `0.12`), `0`
  (Python `-0.0`). `size` `true`, `"1_000"` and int64 were wrong. `"1.5"` and NaN returned 200 where Python returns 500.
  `by_category` was reordered, and `1`/`"1"` were merged.
- **Now:** the body is rendered like Python's `json.dumps`. `min(100, …)` returns an int or a float as in Python,
  `round(x, 2)` is correctly rounded half-even, and floats print with Python `repr`. `int(v or 0)` follows Python over
  BSON types, including the `str`/`bytes` rules, ValueError/TypeError → 500, and the 4300-digit limit. `by_category`
  behaves as a Python dict (insertion order, hash/equality merging, first-key rendering). The read is Motor
  `to_list(5000)`, with no server limit.

**B. `GET /api/invoices/next-preview`**
- **File:** `src/routes/invoices.ts`
- **Before:** a Zod-shaped 422, raised before auth, and 422 on a repeated key.
- **Now:** auth runs first (unauthenticated → 401), then Pydantic v2's exact `missing` 422. `invoice_date` is read as
  the last occurrence using CPython's `parse_qsl`/`unquote_plus` (route-local copy of the Gate 7v port).

**C. `limit` parsing**
- **Files:** `audit-logs.ts`, `policy-changes-list.ts`, `approvals-list.ts`
- **Now:**
  - The exact Pydantic 2.13.4 integer parser (route-local copy of the live-verified Gate 7m port), so `1.0`, `1_000`,
    `-0.0`, `00012`, `+5` and Unicode whitespace behave as in Python, with `int_parsing_size` for more than 4300 digits.
  - The last `limit` value wins, and `%FF` becomes `�`.
  - audit-logs: `limit=0` returns `[]`, and a negative limit returns 500 (Motor `ValueError`).

**D. Capped-list tie order**
- **Cause:** Motor `to_list(n)` sends no server-side limit. `.limit(n)` turns the sort into a top-k, whose order among
  equal keys differs at the cap. Below the cap, all 24 capped routes already matched.
- **Test:** 24 routes, each with cap+15 identical sort keys, three random seeds.
- **Differed on all three seeds, now fixed (14 routes):** company-bank-accounts, party-bank-accounts,
  driver-salary-masters, files, fuel-vehicle-maps, supplier-payments, supplier-vehicles, templates, the three wallet
  lists, approval-detail (revisions and audits), audit-logs, policy-changes.
- **Fix:** a route-local `motorToList` (unlimited sorted cursor, stop at n).
- **Left unchanged:** 10 routes were identical at the cap on every seed (the three payment-corrections lists,
  driver/mechanic/vendor payments, mechanic-work-orders, repair-events, vendor-bills, and approvals, which uses a
  server `.limit` in Python too).

## Harness

`harness.py` uses one throwaway database, dropped in `finally`, and raw-socket GETs. It compares status, content type
and the raw body byte-for-byte.

**Groups:**
- **A:** 27 `files/usage` data shapes.
- **B:** 14 `next-preview` variants.
- **C:** 144 integer-parsing cases across 3 routes.
- **D:** 24 capped routes at the cap boundary, plus 12 limit-parameter caps.

**Zero writes:** checked from the profiler by `appName`, plus the `dbHash` of the application collections.

**Run:** `python backend-node/test/gate9e_parity/harness.py` needs local MongoDB, the backend venv and
`npm run build`.

## Result at lock

- 221/221 parity cases pass.
- Node made 1034 operations, 0 writes.
- 0 of the fixed capped lists send a server-side limit.

## Known, not 9e (reported, not fixed)

Python's `date.fromisoformat` accepts `YYYYMMDD` and ISO-week dates (`2026-W18-5`) for `next-preview`, returning 200,
where Node returns 400. This is a 200-vs-400 validation difference outside 9e's 422 scope, and it needs its own
authorisation.
