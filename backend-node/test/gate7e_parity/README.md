# Gate 7e · SupplierVehicles list · Live parity harness

Shadow target: `GET /api/suppliers/{sid}/vehicles`

## Scope

Class-C read-only shadow of `backend/routers/suppliers.py::supplier_vehicles`
(lines 275–291). Python handler:
```python
sup = await db.suppliers.find_one(
    {"id": sid, "user_id": uid, "company_id": cid},
    {"_id": 0, "name": 1},
)
if not sup:
    raise HTTPException(status_code=404, detail="Supplier not found")
query = {
    "user_id": uid, "company_id": cid, "vehicle_type": "supplier",
    "$or": [
        {"supplier_id": sid},
        {"supplier_name": {"$regex": f"^{sup['name']}$", "$options": "i"}},
    ],
}
veh = await db.vehicles.find(
    query, {"_id": 0, "user_id": 0},
).sort("vehicle_number", 1).to_list(500)
return veh
```

Zero writer hook / audit / backfill / recompute / FinTxn / approvals /
counters / idempotency / cross-collection writes on the GET path.

Writers remain Python-authoritative and OUT OF SCOPE:
- `POST /suppliers` · `PUT /suppliers/{sid}` · `DELETE /suppliers/{sid}`
  · `POST /suppliers/{sid}/reactivate`
- `POST /vehicles` · `PUT /vehicles/{vid}` · `PATCH /vehicles/{vid}/status`
  · `DELETE /vehicles/{vid}` · bulk-import

## NEW parity axes for Gate 7e

| Axis | Detail |
|---|---|
| Path parameter `{sid}` | First path-param Class-C read in the Gate 7 series |
| Cross-collection precheck | `suppliers.findOne` → `vehicles.find` |
| 404 branch | `{"detail":"Supplier not found"}` after successful auth |
| `vehicle_type` equality | Literal `"supplier"` string match |
| `$or` (2 branches) | supplier_id equality **OR** anchored name regex |
| `$regex` + `$options:"i"` | Verbatim server-side Mongo evaluation |
| **Unescaped dynamic regex** | Pattern `^{sup.name}$` — supplier.name passes VERBATIM (no `.replace()`, no escape helper). Regex metacharacters are respected as PCRE ops |
| No `is_active` predicate | Inactive suppliers still return their vehicles |
| Projection | `{_id:0, user_id:0}` — strips both, preserves all others |
| Sort | `vehicle_number` ASC (single field) |
| Cap | 500 rows |
| Response envelope | **Bare JSON array** (NOT wrapped `{items,total}`) |
| No 422 branch | Handler has no query parameters |

### Auth precedence

401 fires BEFORE the supplier precheck / 404. Case 4 exercises this
(unauthenticated request against a missing sid must yield 401, not 404).

### Regex — critical parity note

MongoDB evaluates `{$regex, $options}` server-side. Both Python (motor)
and Node (mongodb@6.9.0) send the identical BSON regex predicate to the
same Mongo engine, so byte parity on any regex-matched body is
mathematically guaranteed. This harness deliberately uses a supplier
name containing bracket-class metacharacters (`"Gamma [X]"`) to prove
that Node does **not** escape/sanitize the pattern.

### Tie-order note

Python sorts by `vehicle_number` ASC only. All parity fixtures use
distinct vehicle_number values — no ambiguous tie order, no Node
tie-breaker.

## UAT data preservation

- Isolated DB: `trukvia_gate7e_parity_<unix_ts>`, dropped in `finally`.
- Never touches `test_database` or any TRUKVIA UAT tenant.

## Ports

- Python (uvicorn): `8216`
- Node   (dist):    `8217`

## Run

```bash
cd /app/backend-node
npm run build
python test/gate7e_parity/harness.py
```

Results file: `/tmp/gate7e_parity_results.json`.

Exit code: `0` on all-pass zero-write; `1` on parity/zero-write violation;
`2` on process bring-up failure.

## Case matrix (15 cases + zero-write aggregate)

| #  | Description                                                                | Expected |
|----|----------------------------------------------------------------------------|----------|
|  1 | no auth · valid sid → 401 Not authenticated                                | 401 body |
|  2 | invalid bearer → 401 Invalid session                                       | 401 body |
|  3 | expired bearer → 401 Session expired                                       | 401 body |
|  4 | auth precedence — no auth + missing sid → 401 (not 404)                    | 401 body |
|  5 | sup-1 · default co-a · id-branch (v1) + name-regex (v2/v3/v4) ASC          | 200 body |
|  6 | sup-2 · valid supplier with zero matches → 200 []                          | 200 body |
|  7 | sup-3 (inactive · name "Gamma [X]") → v-i1 (id) + v-i2 (regex)             | 200 body |
|  8 | missing supplier → 404 Supplier not found                                  | 404 body |
|  9 | wrong-user supplier (u1 accessing u2's sup-cross) → 404                    | 404 body |
| 10 | u2 accessing sup-1 (belongs to u1) → 404                                   | 404 body |
| 11 | owned X-Company-Id co-a-alt + sup-1 → 404 (sup-1 scoped to co-a)           | 404 body |
| 12 | owned X-Company-Id co-a-alt + sup-alt → v-alt-1, v-alt-2 ASC               | 200 body |
| 13 | unowned X-Company-Id co-b → fallback co-a → sup-1 rows                     | 200 body |
| 14 | cross-user u2 · sup-cross → v-cross only (same-name isolation)             | 200 body |
| 15 | URL-encoded whitespace sid ` sup-1 ` → 404                                 | 404 body |
| 16 | Node write events across all cases                                         | 0        |

Body compare mode: `full` for every case. No relaxation.

## Observed results

Filled in at run time — see `/tmp/gate7e_parity_results.json`.
