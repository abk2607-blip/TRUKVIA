# Gate 7y · Reminder digest · Live parity harness

Shadow target: `GET /api/reminders/digest`

## Python source contract

`backend/routers/customers.py::get_reminder_digest` (L1395-1401):

```python
@router.get("/reminders/digest")
async def get_reminder_digest(request: Request, user=Depends(get_current_user)):
    doc = await db.reminder_digests.find_one({"user_id": user["user_id"]}, {"_id": 0},
                                             sort=[("generated_at", -1)])
    if not doc:
        return {"digest": None, "message": "No digest yet — cron runs at 18:00 IST daily. "
                                           "Try /reminders/digest/run to generate now."}
    return {"digest": doc}
```

| Aspect | Python (verified live) | Node |
|---|---|---|
| Scope | **USER-ONLY**: auth only, no `_active_company_id`, no company_id filter | identical, and `companies` is never read |
| Query parameters | none, all ignored | ignored |
| Read | `find {user_id}` · projection `{_id:0}` (user_id kept) · sort `generated_at` -1 · `limit 1`, `singleBatch` | same (Node additionally sends `batchSize: 1`, which cannot affect a single top-1 batch) |
| Branch: no document | `{"digest":null,"message":"No digest yet — …"}` | identical literal |
| Branch: document | `{"digest": <doc>}` | identical |
| Body | jsonable_encoder + `json.dumps` (whole doubles `1500.0`, naive datetime isoformat) | rebuilt from the typed document (`promoteValues:false`) |
| NaN / ObjectId in the digest | 500 `Internal Server Error` text/plain | identical |
| Content-Type | `application/json` | identical (Buffer payload) |
| `HEAD` | 405 · `allow: GET` · length 31 · before auth | explicit HEAD 405 (auto-HEAD disabled for this route) |

Class-C: one `find_one` on `reminder_digests`. Digests are written only by
`scheduler.py::_nightly_reminder_digest` and `POST /api/reminders/digest/run`,
and neither is migrated. The Python server runs with `DISABLE_SCHEDULER=1`,
so no cron job writes during parity. `companies` was unchanged for the whole
run: this route never triggers Python's company repair, even for a user with
no default company.

## Ties

`find_one` picks the top document from MongoDB's limited sort. Tested live:
- a 5-way tie on `generated_at`
- a 60-way tie on `generated_at`
- mixed BSON types in `generated_at`: Date > string > number > null/missing

Python and Node pick the same document in every case.

## Recorded separately (NOT counted)

| Request | Python | Node |
|---|---|---|
| `GET /api/reminders/digest/` | 307 → no slash | 404 |
| `GET /api/reminders/digest/x` | 404 `{"detail":"Not Found"}` | Fastify 404 body |
| `GET /api/reminders/digest/run` | 405 `allow: POST` | 404 |
| Raw non-ASCII query bytes | h11 400 text/plain | Node http 400 JSON |
| Duplicate `X-Company-Id` headers | irrelevant here (user-only), bodies identical | same, but the tenant finding stays open for tenant-scoped routes |

## Ports

- Python (uvicorn): `8270`
- Node   (dist):    `8271`

## Run

```bash
cd backend-node
npm run build
python test/gate7y_parity/harness.py
```

## Observed results

Lock run (2026-09-18 · Windows 11 · MongoDB 7.0 · Python 3.11.9 · Node 24.21.0):
**36 / 36 PASS**:
- 33 byte-exact requests covering both branches, 11 users, the tie cases and serialization
- zero-write and user-only (no Node `companies` access)
- identical find command
- application collections unchanged

Node ops: 58 reads, 0 writes (`reminder_digests`, `user_sessions`). It passed on
the first run. The disposable DB was dropped, with 0 leftover
`trukvia_gate7y_parity_*` databases.
