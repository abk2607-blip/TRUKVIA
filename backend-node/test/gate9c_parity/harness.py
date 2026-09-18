"""Phase 4 · Gate 9c · live Python↔Node parity for X-Company-Id tenant resolution.

Python authority: Starlette `request.headers.get("x-company-id")` (uvicorn 0.25 /
h11 0.16, as pinned in backend/requirements.txt) → FIRST raw occurrence, header
name case-insensitive, value stripped of SP/HTAB only by the HTTP parser. Then
ownership lookup {id, user_id} → default → first company (company.py /
supplier_ledger.py / approval_gate.py resolvers).

Node: backend-node/src/tenant.ts::activeCompanyId (reads req.raw.rawHeaders).

Data: every company-scoped collection holds one co-a row and one co-b row for
the owner u1, so the selected company is visible in the response body. Param
routes target the co-b entity (200 under co-b, 404 under co-a).

Matrix:
  * ALL 66 allowlisted routes (+ deferred controls) × 9 header variants (owner)
  * representative routes × identities (owner, accountant, viewer, other user,
    no-default-company user, expired session, invalid session) × key variants
Per case: status + raw body byte-exact, content-type (modulo the known
`; charset=utf-8` Gate-9d item), and the ownership-lookup filters on
`companies` (profiler, per server) must be equal. Node must never write.
"""
from __future__ import annotations
import asyncio, http.client, json, os, signal, socket, subprocess, sys, tempfile, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from motor.motor_asyncio import AsyncIOMotorClient

REPO = Path(__file__).resolve().parents[3]
MONGO = "mongodb://localhost:27017"
DB = f"trukvia_gate9c_parity_{int(time.time())}"
PY_APP, NODE_APP = "trukvia-gate9c-py", "trukvia-gate9c-node"
PY_PORT, NODE_PORT = 8296, 8297
LOGDIR = Path(tempfile.gettempdir())
WRITE_CMDS = {"insert", "update", "delete", "findAndModify", "createIndexes", "create", "drop", "bulkWrite"}

NOW = datetime.now(timezone.utc)
FUT = NOW + timedelta(days=30)
T0, T1 = "2026-05-01T10:00:00+00:00", "2026-05-02T10:00:00+00:00"


def sess(tok, uid, exp=FUT):
    return {"user_id": uid, "session_token": tok, "expires_at": exp, "created_at": NOW, "last_refreshed_at": NOW}


def seed_docs():
    d: dict[str, list] = {
        "user_sessions": [sess("tok-owner", "u1"), sess("tok-acc", "s-acc"), sess("tok-view", "s-view"),
                          sess("tok-u2", "u2"), sess("tok-nodef", "u-nodef"),
                          sess("tok-expired", "u1", NOW - timedelta(minutes=5))],
        "users": [{"user_id": "u1", "email": "owner@x", "name": "Owner"}, {"user_id": "s-acc", "email": "acc@x"},
                  {"user_id": "s-view", "email": "view@x"}, {"user_id": "u2", "email": "u2@x"},
                  {"user_id": "u-nodef", "email": "nodef@x"}],
        "team_members": [{"id": "tm1", "owner_user_id": "u1", "email": "acc@x", "role": "accountant", "active": True},
                         {"id": "tm2", "owner_user_id": "u1", "email": "view@x", "role": "viewer", "active": True}],
        "companies": [
            {"id": "co-a", "user_id": "u1", "name": "Company A", "is_default": True, "invoice_prefix": "A-", "next_invoice_number": 7},
            {"id": "co-b", "user_id": "u1", "name": "Company B", "is_default": False, "invoice_prefix": "B-", "next_invoice_number": 42},
            {"id": "co-b, co-a", "user_id": "u2", "name": "Literal comma id (other user)", "is_default": False},
            {"id": "co-z", "user_id": "u2", "name": "Company Z", "is_default": True, "invoice_prefix": "Z-", "next_invoice_number": 3},
            {"id": "co-n1", "user_id": "u-nodef", "name": "N1", "invoice_prefix": "N1-"},
            {"id": "co-n2", "user_id": "u-nodef", "name": "N2", "invoice_prefix": "N2-"},
        ],
        "party_bank_accounts": [], "credit_debit_notes": [], "files": [], "reminder_digests": [],
        "audit_logs": [], "chat_messages": [], "approval_revisions": [], "approval_audits": [],
        "payment_corrections": [], "driver_payment_corrections": [],
    }

    def add(coll, doc):
        d.setdefault(coll, []).append(doc)

    owners = [("a", "co-a", "u1"), ("b", "co-b", "u1"), ("z", "co-z", "u2"), ("n1", "co-n1", "u-nodef"), ("n2", "co-n2", "u-nodef")]
    for s, cid, uid in owners:
        base = {"user_id": uid, "company_id": cid, "created_at": T0 if s != "b" else T1}
        add("vendors", {**base, "id": f"v-{s}", "name": f"Vendor {s}", "is_active": True})
        add("suppliers", {**base, "id": f"sup-{s}", "name": f"Supplier {s}", "is_active": True})
        add("customers", {**base, "id": f"cus-{s}", "name": f"Customer {s}", "ship_sites": [{"id": f"ss-{s}", "label": f"Plant {s}"}]})
        add("mechanics", {**base, "id": f"mech-{s}", "name": f"Mechanic {s}", "is_active": True})
        add("drivers", {**base, "id": f"drv-{s}", "name": f"Driver {s}"})
        add("vehicles", {**base, "id": f"veh-{s}", "vehicle_number": f"KA01{s}", "vehicle_type": "supplier",
                         "supplier_id": f"sup-{s}", "supplier_name": f"Supplier {s}", "is_active": True})
        add("trips", {**base, "id": f"trip-{s}", "trip_number": f"T-{s}", "vehicle_type": "supplier",
                      "supplier_name": f"Supplier {s}", "loading_date": "2026-05-01"})
        add("expenses", {**base, "id": f"exp-{s}", "date": "2026-05-01", "amount": 100, "category": "toll",
                         "source_type": "fastag_import", "source_txn_ref": "ref-1", "source": "x"})
        add("templates", {**base, "id": f"tpl-{s}", "name": f"Template {s}", "is_active": True})
        add("company_bank_accounts", {**base, "id": f"cba-{s}", "account_number": f"1234567890{len(s)}{s}",
                                      "masked_display": f"XXXX{s}"})
        add("repair_events", {**base, "id": f"rep-{s}", "vehicle_id": f"veh-{s}", "status": "open"})
        add("mechanic_work_orders", {**base, "id": f"mwo-{s}", "mechanic_id": f"mech-{s}"})
        add("vendor_bills", {**base, "id": f"vb-{s}", "vendor_id": f"v-{s}", "bill_date": "2026-05-01"})
        add("supplier_payments", {**base, "id": f"spay-{s}", "supplier_id": "sup-b", "date": "2026-05-01", "amount": 5})
        add("mechanic_payments", {**base, "id": f"mpay-{s}", "mechanic_id": "mech-b", "date": "2026-05-01", "amount": 5})
        add("driver_payments", {**base, "id": f"dpay-{s}", "driver_id": f"drv-{s}", "date": "2026-05-01", "amount": 5})
        add("vendor_payments", {**base, "id": f"vpay-{s}", "vendor_id": "v-b", "date": "2026-05-01", "amount": 5})
        for kind in ("supplier", "mechanic", "vendor"):
            add("payment_corrections", {**base, "id": f"pc-{kind}-{s}", "payment_type": kind, "payment_id": "pay-1",
                                        "correction_index": 1, "reason": f"fix {s}"})
        add("driver_payment_corrections", {**base, "id": f"dpc-{s}", "payment_id": "pay-1", "correction_index": 1})
        add("wallet_adjustments", {**base, "id": f"wa-{s}", "date": "2026-05-01", "wallet_code": "W1", "amount": 1})
        add("wallet_transfers", {**base, "id": f"wt-{s}", "date": "2026-05-01", "amount": 1})
        add("wallet_recharges", {**base, "id": f"wr-{s}", "date": "2026-05-01", "wallet_code": "W1", "amount": 1})
        add("policy_change_events", {**base, "id": f"pce-{s}", "customer_id": f"cus-{s}"})
        add("approvals", {**base, "id": f"apr-{s}", "status": "PENDING_APPROVAL", "entity_kind": "trip"})
        add("approval_revisions", {**base, "id": f"arev-{s}", "approval_id": "apr-b", "revision_index": 0})
        add("fuel_vehicle_maps", {**base, "id": f"fvm-{s}", "source": "hpcl", "vehicle_id": f"veh-{s}"})
        add("fin_day_closures", {**base, "id": f"fdc-{s}", "close_date": "2026-05-01", "status": "closed",
                                 "closed_at": "2026-05-01T20:00:00+00:00", "closed_by": uid})
        add("fin_txn", {**base, "id": f"tx-{s}", "txn_date": "2026-05-01", "status": "active", "amount": 10,
                        "direction": "in", "account_code": "CASH", "source_type": "manual", "source_id": "",
                        "created_at": "2026-05-03T00:00:00+00:00"})
        add("driver_salary_masters", {**base, "id": f"dsm-{s}", "driver_id": f"drv-{s}", "effective_from": "2026-01-01"})
        add("driver_shortage_policies", {**base, "id": f"dsp-{s}", "name": f"Policy {s}", "active": True,
                                         "product_category": "bitumen", "effective_from": "2026-01-01", "version": 1})
        add("chat_sessions", {**base, "id": f"ses-{s}", "title": f"Chat {s}"})
        add("chat_messages", {"session_id": f"ses-{s}", "role": "user", "content": f"hi {s}", "created_at": T0})
        add("vehicle_status_audit_log", {**base, "id": f"vsa-{s}", "vehicle_id": f"veh-{s}", "at": T0})
        add("invoices", {**base, "id": f"inv-{s}", "invoice_number": f"{s.upper()}-1", "invoice_date": "2026-01-01",
                         "balance_due": 100.0, "status": "issued", "customer_id": f"cus-{s}"})
        add("saved_trip_filters", {**base, "id": f"stf-{s}", "name": f"Filter {s}"})
    add("party_bank_accounts", {"user_id": "u1", "id": "pba-1", "party_type": "vendor", "party_id": "v-b",
                                "account_number": "998877665544", "masked_display": "XXXX5544", "created_at": T0})
    add("credit_debit_notes", {"user_id": "u1", "company_id": "co-b", "id": "cn-b", "kind": "credit",
                               "invoice_id": "inv-b", "note_date": "2026-01-02", "status": "issued"})
    add("files", {"user_id": "u1", "company_id": "co-a", "id": "f-1", "filename": "a.pdf", "size": 10,
                  "category": "general", "is_deleted": False, "created_at": T0})
    add("reminder_digests", {"user_id": "u1", "date": "2026-05-01", "generated_at": T0, "entries": [], "total_customers": 0})
    add("audit_logs", {"user_id": "u1", "company_id": "co-b", "id": "al-1", "module": "trips", "action": "x", "timestamp": T0})
    return d


# (label, target) — every allowlisted path (66) + deferred controls.
ALLOWLIST_ROUTES = [
    ("supplier-payments/:pid/corrections", "/api/supplier-payments/pay-1/corrections"),
    ("invoices/next-preview", "/api/invoices/next-preview?invoice_date=2026-05-01"),
    ("invoices/:iid/notes", "/api/invoices/inv-b/notes"),
    ("invoices/overdue", "/api/invoices/overdue"),
    ("invoices/:iid/ship-to", "/api/invoices/inv-b/ship-to"),
    ("credit-notes", "/api/credit-notes"),
    ("credit-notes/:nid", "/api/credit-notes/cn-b"),
    ("debit-notes", "/api/debit-notes"),
    ("debit-notes/:nid", "/api/debit-notes/cn-b"),
    ("customers/:cid/ship-sites", "/api/customers/cus-b/ship-sites"),
    ("company", "/api/company"),
    ("suppliers/:sid", "/api/suppliers/sup-b"),
    ("expenses", "/api/expenses"),
    ("expenses/:eid", "/api/expenses/exp-b"),
    ("vendors", "/api/vendors"),
    ("vendors/:vid", "/api/vendors/v-b"),
    ("suppliers", "/api/suppliers"),
    ("mechanics", "/api/mechanics"),
    ("mechanics/:mid", "/api/mechanics/mech-b"),
    ("company-bank-accounts", "/api/company-bank-accounts"),
    ("mechanic-payments/:pid/corrections", "/api/mechanic-payments/pay-1/corrections"),
    ("vendor-payments/:pid/corrections", "/api/vendor-payments/pay-1/corrections"),
    ("driver-payments/:pid/corrections", "/api/driver-payments/pay-1/corrections"),
    ("templates", "/api/templates"),
    ("templates/:tid", "/api/templates/tpl-b"),
    ("party-bank-accounts", "/api/party-bank-accounts?party_type=vendor&party_id=v-b"),
    ("audit-logs", "/api/audit-logs"),
    ("repair-events", "/api/repair-events"),
    ("repair-events/:rid", "/api/repair-events/rep-b"),
    ("mechanic-work-orders", "/api/mechanic-work-orders"),
    ("mechanic-work-orders/:wid", "/api/mechanic-work-orders/mwo-b"),
    ("vendor-bills", "/api/vendor-bills"),
    ("vendor-bills/:bid", "/api/vendor-bills/vb-b"),
    ("suppliers/:sid/payments", "/api/suppliers/sup-b/payments"),
    ("mechanics/:mid/payments", "/api/mechanics/mech-b/payments"),
    ("drivers/:did/payments", "/api/drivers/drv-b/payments"),
    ("vendors/:vid/payments", "/api/vendors/v-b/payments"),
    ("wallet-adjustments", "/api/wallet-adjustments"),
    ("wallet-transfers", "/api/wallet-transfers"),
    ("wallet-recharges", "/api/wallet-recharges"),
    ("policy-changes", "/api/policy-changes"),
    ("suppliers/:sid/vehicles", "/api/suppliers/sup-b/vehicles"),
    ("approvals/summary/pending", "/api/approvals/summary/pending"),
    ("approvals", "/api/approvals"),
    ("fuel/vehicle-maps", "/api/fuel/vehicle-maps"),
    ("files", "/api/files"),
    ("files/usage", "/api/files/usage"),
    ("toll-import/lookup", "/api/toll-import/lookup?txn_ref=ref-1"),
    ("approvals/:aid", "/api/approvals/apr-b"),
    ("fin/day-closures", "/api/fin/day-closures"),
    ("fin/day-closures/:close_date", "/api/fin/day-closures/2026-05-01"),
    ("fin/day-status", "/api/fin/day-status?date=2026-05-01"),
    ("drivers/:did/salary-masters", "/api/drivers/drv-b/salary-masters"),
    ("fin/fin-txn/:txid", "/api/fin/fin-txn/tx-b"),
    ("fin/day-closures/:close_date/late-entries", "/api/fin/day-closures/2026-05-01/late-entries"),
    ("fin/day-book", "/api/fin/day-book?date_from=2026-05-01&date_to=2026-05-31"),
    ("(api root)", "/api/"),
    ("gstin/lookup", "/api/gstin/lookup?gstin=27AAPFU0939F1ZV"),
    ("ai/sessions", "/api/ai/sessions"),
    ("reminders/digest", "/api/reminders/digest"),
    ("drivers/:did/salary-settlement-hint", "/api/drivers/drv-b/salary-settlement-hint?month=2026-05"),
    ("ai/sessions/:sid/messages", "/api/ai/sessions/ses-b/messages"),
    ("vehicles/:vid/status-audit", "/api/vehicles/veh-b/status-audit"),
    ("driver-shortage-policies/resolve", "/api/driver-shortage-policies/resolve?product_category=bitumen&trip_date=2026-05-01"),
    ("driver-shortage-policies", "/api/driver-shortage-policies"),
    ("reports/suppliers", "/api/reports/suppliers"),
]
DEFERRED_CONTROLS = [("DEFERRED saved-trip-filters", "/api/saved-trip-filters")]
# Pre-existing, header-independent probes (reported, never counted as pass).
PREEXISTING_PROBES = [("invoices/next-preview (no invoice_date → 422)", "/api/invoices/next-preview")]

VARIANTS = [
    ("none", []),
    ("single co-b", [("X-Company-Id", "co-b")]),
    ("dup co-b,co-a", [("X-Company-Id", "co-b"), ("X-Company-Id", "co-a")]),
    ("dup co-a,co-b", [("X-Company-Id", "co-a"), ("X-Company-Id", "co-b")]),
    ("dup co-b,co-b", [("X-Company-Id", "co-b"), ("X-Company-Id", "co-b")]),
    ("dup names x-company-id/X-COMPANY-ID", [("x-company-id", "co-b"), ("X-COMPANY-ID", "co-a")]),
    ("SINGLE literal 'co-b, co-a'", [("X-Company-Id", "co-b, co-a")]),
    ("dup co-z(unowned),co-b", [("X-Company-Id", "co-z"), ("X-Company-Id", "co-b")]),
    ("dup ''(empty),co-b", [("X-Company-Id", ""), ("X-Company-Id", "co-b")]),
]
TENANT_EDGE = [
    ("single unowned co-z", [("X-Company-Id", "co-z")]),
    ("single unknown", [("X-Company-Id", "co-nope")]),
    ("single empty", [("X-Company-Id", "")]),
    ("single SP/HTAB padded co-b", [("X-Company-Id", " \t co-b \t ")]),
    ("single NBSP-suffixed co-b", [("X-Company-Id", "co-b\xa0")]),
    ("single CO-B (id casing)", [("X-Company-Id", "CO-B")]),
    ("single 'co-b,co-a' no space", [("X-Company-Id", "co-b,co-a")]),
    ("dup co-nope,co-b", [("X-Company-Id", "co-nope"), ("X-Company-Id", "co-b")]),
    ("dup co-b,co-z", [("X-Company-Id", "co-b"), ("X-Company-Id", "co-z")]),
    ("dup with other header between", [("X-Company-Id", "co-b"), ("X-Other", "1"), ("X-Company-Id", "co-a")]),
    ("dup whitespace-only first", [("X-Company-Id", "   "), ("X-Company-Id", "co-b")]),
    ("triple co-b,co-a,co-z", [("X-Company-Id", "co-b"), ("X-Company-Id", "co-a"), ("X-Company-Id", "co-z")]),
]
REPRESENTATIVE = ["vendors", "vendors/:vid", "fin/fin-txn/:txid", "suppliers", "customers/:cid/ship-sites",
                  "invoices/next-preview", "reports/suppliers", "expenses", "suppliers/:sid/payments", "approvals",
                  "wallet-transfers", "fuel/vehicle-maps", "company-bank-accounts", "party-bank-accounts",
                  "vehicles/:vid/status-audit", "drivers/:did/payments", "company", "files"]
IDENTITIES = ["tok-owner", "tok-acc", "tok-view", "tok-u2", "tok-nodef", "tok-expired", "tok-invalid"]
NODEF_VARIANTS = [("none", []), ("dup co-n2,co-n1", [("X-Company-Id", "co-n2"), ("X-Company-Id", "co-n1")]),
                  ("dup co-n1,co-n2", [("X-Company-Id", "co-n1"), ("X-Company-Id", "co-n2")]),
                  ("SINGLE literal 'co-n2, co-n1'", [("X-Company-Id", "co-n2, co-n1")])]
U2_VARIANTS = [("dup co-a(u1's),co-z", [("X-Company-Id", "co-a"), ("X-Company-Id", "co-z")]),
               ("SINGLE literal 'co-b, co-a' (u2 owns that literal id)", [("X-Company-Id", "co-b, co-a")]),
               ("dup co-b,co-a (u1's; literal id NOT matched)", [("X-Company-Id", "co-b"), ("X-Company-Id", "co-a")])]


def raw(port, target, hdr):
    s = socket.create_connection(("127.0.0.1", port), timeout=30)
    req = b"GET " + target.encode() + b" HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n"
    for k, v in hdr:
        req += f"{k}: {v}\r\n".encode("latin-1")
    s.sendall(req + b"\r\n")
    r = http.client.HTTPResponse(s, method="GET")
    r.begin()
    b = r.read()
    h = {k.lower(): v for k, v in r.getheaders()}
    s.close()
    return r.status, h, b


def wait(port, path):
    for _ in range(480):
        try:
            if raw(port, path, [])[0] < 500:
                return True
        except Exception:
            pass
        time.sleep(0.25)
    return False


def stop(p):
    if p and p.poll() is None:
        try:
            p.send_signal(signal.SIGTERM); p.wait(timeout=5)
        except Exception:
            try: p.kill()
            except Exception: pass


def override_lookups(ops):
    """companies ownership lookups by explicit id, in order (the tenant override step)."""
    out = []
    for o in ops:
        c = o.get("command") or {}
        if c.get("find") == "companies" and isinstance(c.get("filter"), dict) and "id" in c["filter"]:
            out.append(json.dumps(c["filter"], sort_keys=True))
    return out


async def run() -> int:
    print(f"[gate9c] DB={DB} (isolated — UAT data untouched)")
    cli = AsyncIOMotorClient(MONGO, serverSelectionTimeoutMS=5000)
    d = cli[DB]
    py = node = None
    try:
        seeds = seed_docs()
        for coll, rows in seeds.items():
            if rows:
                await d[coll].insert_many([dict(r) for r in rows])
        tracked = sorted(seeds.keys())
        app_colls = [c for c in tracked if c not in ("companies", "user_sessions", "trips", "invoices", "customers",
                                                        "vehicles", "drivers", "files", "audit_logs")]
        env = os.environ.copy()
        env.update({"MONGO_URL": f"{MONGO}/?appName={PY_APP}", "DB_NAME": DB, "ENABLE_DEMO_TOKEN": "0", "IS_PREVIEW_ENV": "0",
                    "DISABLE_SCHEDULER": "1", "REGRESSION_GUARD_PERIODIC": "0", "PYTHONIOENCODING": "utf-8"})
        py = subprocess.Popen([sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(PY_PORT),
                               "--log-level", "warning", "--no-access-log"], cwd=str(REPO / "backend"), env=env,
                              stdout=open(LOGDIR / "gate9c_py.log", "wb"), stderr=subprocess.STDOUT)
        env2 = os.environ.copy()
        env2.update({"NODE_ENV": "test", "NODE_LOG_LEVEL": "silent", "NODE_PORT": str(NODE_PORT), "NODE_HOST": "127.0.0.1",
                     "NODE_MONGO_URL": f"{MONGO}/?appName={NODE_APP}", "NODE_DB_NAME": DB, "NODE_CORS_ORIGINS": "",
                     "NODE_REQUEST_ID_HEADER": "x-request-id", "NODE_TRUST_INCOMING_REQUEST_ID": "false"})
        node = subprocess.Popen(["node", str(REPO / "backend-node/dist/server.js")], cwd=str(REPO / "backend-node"), env=env2,
                                stdout=open(LOGDIR / "gate9c_node.log", "wb"), stderr=subprocess.STDOUT)
        if not (wait(PY_PORT, "/api/") and wait(NODE_PORT, "/health/live")):
            print("[gate9c] servers did not start"); return 2
        await asyncio.sleep(8)
        await d.command({"profile": 0}); await d.drop_collection("system.profile")
        await d.create_collection("system.profile", capped=True, size=128 * 1024 * 1024)
        await d.command({"profile": 2})
        h_start = (await d.command("dbHash", collections=tracked))["collections"]

        routes = dict(ALLOWLIST_ROUTES + DEFERRED_CONTROLS)
        cases = []  # (group, desc, target, headers)
        for label, target in ALLOWLIST_ROUTES + DEFERRED_CONTROLS:
            grp = "deferred" if label.startswith("DEFERRED") else "all-routes"
            for vname, vh in VARIANTS:
                cases.append((grp, f"{label} · owner · {vname}", target, [("Authorization", "Bearer tok-owner")] + vh))
        for label in REPRESENTATIVE:
            for vname, vh in TENANT_EDGE:
                cases.append(("edge", f"{label} · owner · {vname}", routes[label], [("Authorization", "Bearer tok-owner")] + vh))
            for tok in IDENTITIES:
                if tok == "tok-owner":
                    continue
                vs = NODEF_VARIANTS if tok == "tok-nodef" else U2_VARIANTS if tok == "tok-u2" else VARIANTS
                for vname, vh in vs:
                    cases.append(("identity", f"{label} · {tok} · {vname}", routes[label],
                                  [("Authorization", f"Bearer {tok}")] + vh))

        rows, py_writes, node_changes, charset_only, body500 = [], [], [], [], []
        passed = failed = 0
        lookups_compared = 0
        body_by = {}
        for grp, desc, target, hdr in cases:
            n_py0 = await d["system.profile"].count_documents({"appName": PY_APP})
            h0 = (await d.command("dbHash", collections=tracked))["collections"]
            rp = raw(PY_PORT, target, hdr)
            last, stable = -1, 0
            while stable < 4:  # quiesce Python's late refresh / repair writes
                await asyncio.sleep(0.06)
                cur = await d["system.profile"].count_documents({"appName": PY_APP})
                stable = stable + 1 if cur == last else 0
                last = cur
            py_ops = await d["system.profile"].find({"appName": PY_APP}).skip(n_py0).to_list(None)
            h_mid = (await d.command("dbHash", collections=tracked))["collections"]
            pch = [k for k in tracked if h0.get(k) != h_mid.get(k)]
            if pch:
                py_writes.append((desc, pch))
            n_nd0 = await d["system.profile"].count_documents({"appName": NODE_APP})
            n_py1 = await d["system.profile"].count_documents({"appName": PY_APP})
            rn = raw(NODE_PORT, target, hdr)
            await asyncio.sleep(0.06)
            nd_ops = await d["system.profile"].find({"appName": NODE_APP}).skip(n_nd0).to_list(None)
            h1 = (await d.command("dbHash", collections=tracked))["collections"]
            # A late Python refresh write landing in Node's window is attributed to Python (profiler proof).
            late_py = {(o.get("ns") or ".").split(".", 1)[1] for o in
                       await d["system.profile"].find({"appName": PY_APP}).skip(n_py1).to_list(None)
                       if o.get("op") in ("update", "insert", "remove")}
            nd_w = {(o.get("ns") or ".").split(".", 1)[1] for o in nd_ops if o.get("op") in ("update", "insert", "remove")}
            changed = [k for k in tracked if h_mid.get(k) != h1.get(k)]
            nch = [k for k in changed if k in nd_w or k not in late_py]
            if any(k in late_py for k in changed):
                py_writes.append((desc + " (late)", sorted(late_py)))
            if nch:
                node_changes.append((desc, nch))
            lp, ln = override_lookups(py_ops), override_lookups(nd_ops)
            # Python re-dispatches on 500 (framework, Gate 8a) → lookups may be doubled.
            look_ok = lp == ln or (rp[0] == 500 and lp == ln * 2)
            lookups_compared += len(ln)
            status_ok = rp[0] == rn[0]
            if rp[0] == 500:
                body_ok = status_ok
                if rp[2] != rn[2]:
                    body500.append(desc)
            else:
                body_ok = status_ok and rp[2] == rn[2]
            ct_p = (rp[1].get("content-type") or "").replace("; charset=utf-8", "")
            ct_n = (rn[1].get("content-type") or "").replace("; charset=utf-8", "")
            if rp[1].get("content-type") != rn[1].get("content-type") and ct_p == ct_n:
                charset_only.append(desc)
            ct_ok = rp[0] == 500 or ct_p == ct_n
            ok = body_ok and ct_ok and look_ok and not nch
            passed += ok; failed += (not ok)
            rows.append((grp, ok, desc, rp, rn, lp, ln, hdr))
            body_by[desc] = rp

        # Classify failures. Tenant-independent PRE-EXISTING = the same route+token with
        # NO X-Company-Id header fails with the identical (python, node) responses and the
        # ownership lookups were equal. Everything else is a tenant failure.
        def key(desc):
            parts = desc.split(" · ")
            return parts[0], parts[1]
        none_fail = {}
        for grp, ok, desc, rp, rn, lp, ln, hdr in rows:
            if not ok and not any(k.lower() == "x-company-id" for k, _ in hdr):
                none_fail[key(desc)] = (rp[0], rp[2], rn[0], rn[2])
        pre_existing, tenant_fail = [], []
        for grp, ok, desc, rp, rn, lp, ln, hdr in rows:
            if ok:
                continue
            nf = none_fail.get(key(desc))
            if nf and lp == ln and (rp[0], rp[2], rn[0], rn[2]) == nf:
                pre_existing.append(desc)
            else:
                tenant_fail.append(desc)
        probes = []
        for label, target in PREEXISTING_PROBES:
            pa = raw(PY_PORT, target, [("Authorization", "Bearer tok-owner")])
            pb = raw(NODE_PORT, target, [("Authorization", "Bearer tok-owner")])
            probes.append((label, pa, pb))

        # Company-discrimination evidence: routes whose Python body differs co-a vs co-b.
        disc = []
        for label, target in ALLOWLIST_ROUTES:
            a = body_by.get(f"{label} · owner · none")
            b = body_by.get(f"{label} · owner · single co-b")
            if a and b and (a[0], a[2]) != (b[0], b[2]):
                disc.append(label)

        prof = await d["system.profile"].find({"appName": NODE_APP}).to_list(None)
        is_write = lambda p: p.get("op") in ("insert", "update", "remove") or next(iter(p.get("command") or {}), "") in WRITE_CMDS
        node_writes = [p for p in prof if is_write(p)]
        node_reads = [p for p in prof if not is_write(p) and p.get("op") in ("query", "command", "getmore")]
        node_colls = sorted({(p.get("ns") or ".").split(".", 1)[1] for p in prof})
        h_end = (await d.command("dbHash", collections=tracked))["collections"]

        print("\n" + "=" * 110 + "\nPHASE 4 · GATE 9c · X-COMPANY-ID TENANT PARITY\n" + "=" * 110)
        for grp in ("all-routes", "deferred", "edge", "identity"):
            g = [r for r in rows if r[0] == grp]
            print(f"\n-- {grp}: {sum(r[1] for r in g)}/{len(g)} pass")
            for _, ok, desc, rp, rn, lp, ln, _h in g:
                if not ok or grp != "all-routes" or "dup co-b,co-a" in desc or "literal" in desc:
                    print(f"  [{'PASS' if ok else 'FAIL'}] {desc[:78]:78} py={rp[0]} node={rn[0]} {rp[2][:60]!r}")
                if not ok:
                    print(f"        node body: {rn[2][:200]!r}\n        lookups py={lp}\n        lookups nd={ln}")
        zero_ok = not node_writes and not node_changes
        passed += zero_ok; failed += (not zero_ok)
        print(f"\n  [{'PASS' if zero_ok else 'FAIL'}] zero-write: node ops={len(prof)} reads={len(node_reads)} "
              f"writes={len(node_writes)} node-attributed changes={node_changes or 'none'}")
        print(f"         node collections touched: {node_colls}")
        app_ok = all(h_start.get(k) == h_end.get(k) for k in app_colls)
        passed += app_ok; failed += (not app_ok)
        print(f"  [{'PASS' if app_ok else 'FAIL'}] application collections unchanged ({len(app_colls)}; Python GET-time "
              f"write targets excluded & attributed): changed={[k for k in app_colls if h_start.get(k) != h_end.get(k)]}")
        print(f"  ownership-lookup filters compared: {lookups_compared}")
        print(f"  company-discriminating allowlisted routes (Python body co-a != co-b): {len(disc)}/{len(ALLOWLIST_ROUTES)}")
        print(f"     non-discriminating (user-only / no tenant): {[l for l, _ in ALLOWLIST_ROUTES if l not in disc]}")
        print(f"  python-side writes (refresh / repair / GET-time, Python-only): {len(py_writes)} requests; "
              f"{sorted({c for _, cs in py_writes for c in cs})}")
        print(f"  KNOWN framework (Gate 9d, not hiding status/body): charset-only content-type diffs={len(charset_only)}; "
              f"500 body-format diffs={len(body500)}")
        print(f"  TENANT failures (header-dependent): {len(tenant_fail)} {tenant_fail[:20]}")
        print(f"  PRE-EXISTING header-independent mismatches (fail identically with NO header; NOT counted as pass): "
              f"{len(pre_existing)} routes={sorted({key(x)[0] for x in pre_existing})}")
        for label, pa, pb in probes:
            print(f"  PRE-EXISTING probe {label}:\n      py={pa[0]} {pa[2][:150]!r}\n    node={pb[0]} {pb[2][:150]!r}")
        print("-" * 110 + f"\n  cases: {len(rows) + 2}   passed: {passed}   failed: {failed} "
              f"(tenant={len(tenant_fail)}, pre-existing={len(pre_existing)}, "
              f"zero-write/app={int(not zero_ok) + int(not app_ok)})\n" + "=" * 110)
        return 0 if (not tenant_fail and zero_ok and app_ok) else 1
    finally:
        stop(py); stop(node)
        try: await d.command({"profile": 0})
        except Exception: pass
        await cli.drop_database(DB)
        print(f"[gate9c] dropped {DB}; leftover gate9c DBs: "
              f"{[x for x in await cli.list_database_names() if x.startswith('trukvia_gate9c_parity_')]}")
        cli.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
