"""Phase 3 · Gate 7s · live Python↔Node parity harness for Fin Day Book.

Covers:
  * GET /api/fin/day-book

Class-C stance:
  Pure-read in Python. Handler executes exactly
    fin_txn.find(q, {_id:0, user_id:0}).sort([("txn_date",-1),("created_at",-1)])
           .to_list(int(max(1, min(limit, 20000))))
  and aggregates per-account totals in memory. Zero DB writes.

Comparison is BYTE-EXACT on the body and EXACT on the full content-type
header (Python JSONResponse → `application/json`; Starlette 500 →
`text/plain; charset=utf-8`), plus status.

Money axes: float() of every stored type, round-half-even round(x, 2) per
account, accumulation order, NaN / ±Infinity → 500, totals dict semantics
(insertion order, setdefault hash merging, jsonable_encoder re-keying with
last-value-wins collisions, duplicate numeric JSON keys, unhashable → 500).
Every money case lives in its own company (X-Company-Id).

Sort / limit axes: txn_date DESC, created_at DESC with heavy ties; default
5000 and clamp 20000 over a 20 005-row tenant — Node must NOT send a server
limit (Motor to_list semantics).

Write detection: MongoDB `dbHash` around each request + profiler level 2
attributed by driver appName.
"""
from __future__ import annotations
import asyncio, http.client, json, os, random, signal, subprocess, sys, tempfile, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote
from bson import Binary, Code, Decimal128, Int64, ObjectId, Timestamp
from motor.motor_asyncio import AsyncIOMotorClient

REPO = Path(__file__).resolve().parents[3]
MONGO = "mongodb://localhost:27017"
DB = f"trukvia_gate7s_parity_{int(time.time())}"
PY_APP, NODE_APP = "trukvia-gate7s-py", "trukvia-gate7s-node"
PY_PORT, NODE_PORT = 8256, 8257
LOGDIR = Path(tempfile.gettempdir())
P = "/api/fin/day-book"
WIN = "date_from=2026-01-01&date_to=2026-12-31"
BIG_N = 20005
_M = object()


def now_iso() -> str: return datetime.now(timezone.utc).isoformat()
def future(s: int) -> str: return (datetime.now(timezone.utc) + timedelta(seconds=s)).isoformat()
def past(s: int) -> str: return (datetime.now(timezone.utc) - timedelta(seconds=s)).isoformat()


def leg(amount: Any = 100.0, direction: Any = "in", acct: Any = "AR", txn_date: Any = "2026-04-30",
        created_at: Any = "2026-04-30T10:00:00+00:00", **extra: Any) -> dict[str, Any]:
    d: dict[str, Any] = {"status": "active"}
    for k, v in (("txn_date", txn_date), ("created_at", created_at), ("account_code", acct),
                 ("amount", amount), ("direction", direction)):
        if v is not _M:
            d[k] = v
    d["source_type"] = "invoice"
    d.update(extra)
    return d


M: list[dict[str, Any]] = []


def money(desc: str, legs: list[dict[str, Any]], expect: int | None = 200, query: str = WIN) -> None:
    M.append({"d": desc, "legs": legs, "expect": expect, "query": query})


# shape / aggregation
money("single leg", [leg(100.0)])
money("empty window → rows [] totals {}", [])
money("multi accounts, insertion order by sorted rows", [
    leg(1.0, acct="BANK", txn_date="2026-04-30"), leg(2.0, acct="AR", txn_date="2026-04-29"),
    leg(3.0, "out", "BANK", txn_date="2026-04-28"), leg(4.0, acct="CASH", txn_date="2026-04-27")])
money("duplicate aggregation into one account", [leg(1.5), leg(2.25), leg(0.75, "out"), leg(10.0, "out")])
money("zero / negative / decimal", [leg(0.0), leg(-0.0, "out"), leg(-12.345), leg(0.1, "out"), leg(0.2, "out")])
money("net per account round(round(in)-round(out))", [leg(0.125), leg(0.005, "out"), leg(2.675, acct="X"), leg(1.005, "out", "X")])
for x in (0.125, 0.375, 0.625, 0.875, 2.675, 1.005, 1.115, 0.285, 1.255, 8.345, 10.125, 1234567.125, 0.005,
          0.015, 0.025, 0.035, 0.045, -0.125, -2.675, 0.1250000000000001, 0.12499999999999999, 2.675000000000001,
          2.6749999999999994, 2.5, 1e15 + 0.125, 4503599627370495.5, 5e-324, 2.2250738585072014e-308,
          1.7976931348623157e308, 0.1 + 0.2):
    money(f"round in={x!r}", [leg(x)])
money("accumulation 0.1 x 10", [leg(0.1) for _ in range(10)])
money("accumulation 0.01 x 100 two accounts", [leg(0.01, acct=("A" if i % 2 else "B")) for i in range(100)])
money("large+small order (sort decides order)", [leg(1e16, txn_date="2026-04-30"), leg(1.0, txn_date="2026-04-29"),
                                                  leg(-1e16, txn_date="2026-04-28")])
money("large+small reversed order", [leg(-1e16, txn_date="2026-04-30"), leg(1.0, txn_date="2026-04-29"),
                                     leg(1e16, txn_date="2026-04-28")])
money("overflow → inf → 500", [leg(1.7976931348623157e308), leg(1.7976931348623157e308)], expect=500)
money("inf - inf in one account → nan → 500", [leg(float("inf")), leg(float("inf"), "out")], expect=500)
money("inf in other account only → 500", [leg(1.0, acct="OK"), leg(float("-inf"), acct="BAD")], expect=500)
for label, v in [("str '12.5'", "12.5"), ("str '42'", "42"), ("str '1_000.25'", "1_000.25"),
                 ("str arabic digits", " ١٢.5 "), ("str NBSP", " 7.5"), ("str '1e3'", "1e3"),
                 ("str '+.5'", "+.5"), ("str '-5.'", "-5."), ("str ''", ""), ("str math digits", "\U0001d7cf\U0001d7d0"),
                 ("int32", 7), ("int64 big", Int64(9007199254740993)), ("bool true", True), ("bool false", False),
                 ("null", None), ("empty list", []), ("empty dict", {}), ("Binary b'2.5'", Binary(b"2.5")),
                 ("Code '1.5'", Code("1.5"))]:
    money(f"amount {label}", [leg(v)])
money("amount missing", [leg(_M)])
for label, v in [("str 'abc'", "abc"), ("str '1,5'", "1,5"), ("str '0x10'", "0x10"), ("str '1__0'", "1__0"),
                 ("str BOM", "﻿1"), ("str 'inf'", "inf"), ("str 'nan'", "nan"), ("str '1e400'", "1e400"),
                 ("double NaN", float("nan")), ("double +inf", float("inf")), ("double -inf", float("-inf")),
                 ("Decimal128", Decimal128("1.5")), ("datetime", datetime(2026, 1, 1)),
                 ("ObjectId", ObjectId("65f000000000000000000001")), ("list [1]", [1]), ("dict {a:1}", {"a": 1}),
                 ("Binary invalid", Binary(b"\xff")), ("Timestamp", Timestamp(1, 1))]:
    money(f"amount {label} → 500", [leg(v)], expect=500)
money("direction IN / missing / None / out / in", [leg(1.0, "IN"), leg(2.0, _M), leg(4.0, None), leg(8.0, "out"), leg(16.0, "in")])
# totals key semantics
money("keys int 1, True, str '1' (dup JSON keys)", [leg(1.0, acct=1), leg(1.0, acct=True), leg(1.0, acct="1")])
money("keys True then 1.0 (merge, first text)", [leg(1.0, acct=True), leg(2.0, acct=1.0)])
money("keys double 5.0 / 1e16 / 0.1", [leg(1.0, acct=5.0), leg(1.0, acct=1e16), leg(1.0, acct=0.1)])
money("keys numeric-looking strings keep order", [leg(1.0, acct="10", txn_date="2026-04-30"), leg(1.0, acct="2", txn_date="2026-04-29"),
                                                   leg(1.0, acct="a", txn_date="2026-04-28"), leg(1.0, acct="1", txn_date="2026-04-27")])
money("keys falsy → ''", [leg(1.0, acct=_M), leg(1.0, acct=None), leg(1.0, acct=""), leg(1.0, acct=0), leg(1.0, acct=-0.0),
                          leg(1.0, acct=[]), leg(1.0, acct={})])
money("keys bytes then str collide (last value wins)", [leg(1.0, acct=Binary(b"AR"), txn_date="2026-04-30"),
                                                        leg(5.0, acct="AR", txn_date="2026-04-29")])
money("keys str then bytes collide (last value wins)", [leg(5.0, acct="AR", txn_date="2026-04-30"),
                                                        leg(1.0, acct=Binary(b"AR"), txn_date="2026-04-29")])
money("keys datetime vs str isoformat collide", [leg(1.0, acct=datetime(2026, 1, 2, 3, 4, 5), txn_date="2026-04-30"),
                                                 leg(2.0, acct="2026-01-02T03:04:05", txn_date="2026-04-29")])
money("key int64 big", [leg(1.0, acct=Int64(9007199254740993))])
for label, v in [("list", ["x"]), ("dict", {"a": 1}), ("Code", Code("x")), ("ObjectId", ObjectId("65f000000000000000000002")),
                 ("Decimal128", Decimal128("1")), ("NaN", float("nan")), ("inf", float("inf"))]:
    money(f"key {label} → 500", [leg(1.0, acct=v)], expect=500)
# sort ties
money("ties: same txn_date, created_at decides", [leg(1.0, created_at=f"2026-04-30T0{i}:00:00+00:00", tag=i) for i in range(6)])
money("ties: identical txn_date and created_at", [leg(float(i), tag=i) for i in range(12)])
money("mixed-type txn_date excluded by string range", [leg(1.0, txn_date=20260430), leg(2.0)])
# rows serialisation
money("row field types", [leg(1.0, x_dt=datetime(2026, 1, 2, 3, 4, 5, 123000), x_dt0=datetime(2026, 1, 2),
                              x_bin=Binary(b"hello"), x_code=Code("c", {"s": 1}), x_i64=Int64(9007199254740993),
                              x_d=[5.0, 1e16, 1e15, 1e-5, 1e-4, -0.0, 123456789.123, 5e-324],
                              x_nested={"a": [1, 2.0, {"b": None, "c": "q\"\\\n\t\x01 é₹"}]})])
for label, v in [("ObjectId", ObjectId("65f000000000000000000003")), ("Decimal128", Decimal128("2.5")),
                 ("Timestamp", Timestamp(5, 1)), ("nested NaN", {"a": [float("nan")]}), ("Binary invalid", Binary(b"\xfe"))]:
    money(f"row field {label} → 500", [leg(1.0, x=v)], expect=500)
# filters (own company each)
FLT = [leg(1.0, account_id="acc-1", party_id="p-1", vehicle_id="v-1", trip_id="t-1", source_type="invoice"),
       leg(2.0, acct="BANK", account_id="acc-2", party_id="p-2", vehicle_id="v-2", trip_id="t-2", source_type="expense"),
       leg(4.0, "out", account_id="acc-1", party_id="p-2", vehicle_id="v-1", trip_id="t-2", source_type="expense")]
for q in ("account_code=AR", "account_id=acc-1", "source_type=expense", "party_id=p-2", "vehicle_id=v-1",
          "trip_id=t-2", "account_code=AR&source_type=expense&trip_id=t-2", "account_code=&account_id=",
          "account_code=NOPE", "foo=bar", "account_code=BANK&account_code=AR"):
    money(f"filter {q}", FLT, query=f"{WIN}&{q}")
for q in ("date_from=2026-04-30&date_to=2026-04-30", "date_from=2026-05-01&date_to=2026-04-01",
          "date_from=2026&date_to=2026-4", "date_from=%20&date_to=~", "date_from=2026-04-29&date_to=2026-04-29T99"):
    money(f"window {q}", FLT, query=q)
for q in ("limit=1", "limit=0", "limit=-5", "limit=2", "limit=1.0", "limit=+2", "limit=%202%20", "limit=1_0"):
    money(f"limit {q}", FLT, query=f"{WIN}&{q}")


def fuzz_amount_strings(n: int = 200) -> list[str]:
    rnd = random.Random(7_000_018)
    alpha = list("0123456789") * 3 + list("._eE+- ") + ["_", "_", "i", "n", "f", "a", "١", " ", "　", "x"]
    return ["".join(rnd.choice(alpha) for _ in range(rnd.randint(1, 9))) for _ in range(n)]


def fuzz_accounts(n: int = 200) -> list[list[tuple[float, str, str]]]:
    rnd = random.Random(7_000_019)
    out = []
    for _ in range(n):
        legs = []
        for _ in range(rnd.randint(1, 6)):
            base = rnd.choice([rnd.randint(0, 99999) / 1000, rnd.randint(0, 999) / 8, rnd.randint(-5000, 5000) / 200,
                               rnd.uniform(-1e6, 1e6), rnd.randint(0, 10 ** 12) / 1000 + 0.005])
            legs.append((base, rnd.choice(["in", "in", "out"]), rnd.choice(["AR", "BANK", "CASH", "EXP", "2", "10"])))
        out.append(legs)
    return out


for s in fuzz_amount_strings():
    money(f"fuzz amount {s!r}", [leg(s)], expect=None)
for i, legs in enumerate(fuzz_accounts()):
    money(f"fuzz accounts {len(legs)} legs",
          [leg(a, d, ac, txn_date=f"2026-04-{(j % 28) + 1:02d}", created_at=f"2026-04-01T00:00:{j % 3:02d}+00:00")
           for j, (a, d, ac) in enumerate(legs)], expect=None)


def fixtures() -> dict[str, list[dict[str, Any]]]:
    now = now_iso()
    comps = [
        {"id": "co-a",     "user_id": "u1", "is_default": True,  "name": "Acme Co"},
        {"id": "co-a-alt", "user_id": "u1", "is_default": False, "name": "Acme Alt"},
        {"id": "co-b",     "user_id": "u2", "is_default": True,  "name": "Beta Co"},
        {"id": "co-big",   "user_id": "u1", "is_default": False, "name": "Big"},
    ]
    txns = [
        {"id": "t-a1", "user_id": "u1", "company_id": "co-a", **leg(100.125, "in", "AR")},
        {"id": "t-a2", "user_id": "u1", "company_id": "co-a", **leg(40.0, "out", "BANK", txn_date="2026-03-01")},
        {"id": "t-a3", "user_id": "u1", "company_id": "co-a", **leg(9.0, "in", "AR", status="void")},
        {"id": "t-alt", "user_id": "u1", "company_id": "co-a-alt", **leg(7.5, "in", "CASH")},
        {"id": "t-u2", "user_id": "u2", "company_id": "co-b", **leg(3.25, "in", "AR")},
        {"id": "t-leak", "user_id": "u2", "company_id": "co-a", **leg(999.0, "in", "LEAK")},
    ]
    txns += [{"id": f"big-{i:05d}", "user_id": "u1", "company_id": "co-big",
              **leg(0.01, "in" if i % 3 else "out", ["AR", "BANK", "CASH"][i % 3],
                    txn_date=f"2026-04-{(i % 5) + 1:02d}", created_at=f"2026-04-01T00:00:0{i % 4}+00:00", seq=i)}
             for i in range(BIG_N)]
    for i, m in enumerate(M):
        co = f"m{i:04d}"
        comps.append({"id": co, "user_id": "u1", "is_default": False, "name": co})
        for j, lg in enumerate(m["legs"]):
            txns.append({"id": f"t-{co}-{j:03d}", "user_id": "u1", "company_id": co, **lg})
    return {
        "user_sessions": [
            {"session_token": "tok-u1",      "user_id": "u1", "effective_role": "owner", "expires_at": future(7200), "last_refreshed_at": now},
            {"session_token": "tok-u2",      "user_id": "u2", "effective_role": "owner", "expires_at": future(7200), "last_refreshed_at": now},
            {"session_token": "tok-expired", "user_id": "u1", "effective_role": "owner", "expires_at": past(60),      "last_refreshed_at": now},
        ],
        "users": [{"user_id": u, "email": f"{u}@x", "name": u.upper(), "picture": "", "created_at": now} for u in ("u1", "u2")],
        "companies": comps,
        "fin_txn": txns,
    }


TRACKED = ["users", "user_sessions", "companies", "fin_txn", "fin_accounts", "audit_logs",
           "approvals", "counters", "fin_hook_failures"]


async def seed(cli, dbname):
    await cli.drop_database(dbname)
    for coll, rows in fixtures().items():
        if rows:
            await cli[dbname][coll].insert_many([dict(r) for r in rows])


async def dbhash(cli, dbname) -> dict[str, str]:
    r = await cli[dbname].command("dbHash", collections=TRACKED)
    return dict(r.get("collections", {}))


def start_py():
    env = os.environ.copy()
    env.update({"MONGO_URL": f"{MONGO}/?appName={PY_APP}", "DB_NAME": DB,
                "ENABLE_DEMO_TOKEN": "0", "DEMO_TOKEN_VALUE": "", "IS_PREVIEW_ENV": "0",
                "DISABLE_SCHEDULER": "1", "REGRESSION_GUARD_PERIODIC": "0",
                "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"})
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1",
         "--port", str(PY_PORT), "--log-level", "warning", "--no-access-log"],
        cwd=str(REPO / "backend"), env=env,
        stdout=open(LOGDIR / "gate7s_py.log", "wb"), stderr=subprocess.STDOUT)


def start_node():
    env = os.environ.copy()
    env.update({"NODE_ENV": "test", "NODE_LOG_LEVEL": "silent",
                "NODE_PORT": str(NODE_PORT), "NODE_HOST": "127.0.0.1",
                "NODE_MONGO_URL": f"{MONGO}/?appName={NODE_APP}", "NODE_DB_NAME": DB,
                "NODE_CORS_ORIGINS": "", "NODE_REQUEST_ID_HEADER": "x-request-id",
                "NODE_TRUST_INCOMING_REQUEST_ID": "false"})
    return subprocess.Popen(
        ["node", str(REPO / "backend-node/dist/server.js")],
        cwd=str(REPO / "backend-node"), env=env,
        stdout=open(LOGDIR / "gate7s_node.log", "wb"), stderr=subprocess.STDOUT)


def raw_get(port: int, path: str, hdr: dict[str, str]) -> tuple[int, str, bytes]:
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=120)
    c.putrequest("GET", path, skip_accept_encoding=True)
    for k, v in hdr.items():
        c.putheader(k, v)
    c.endheaders()
    r = c.getresponse()
    body = r.read()
    ctype = r.getheader("content-type") or ""
    c.close()
    return r.status, ctype, body


def wait(port: int, path: str, timeout: int = 120) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if raw_get(port, path, {})[0] < 500:
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


HDR = {
    "u1": {"Authorization": "Bearer tok-u1"},
    "u2": {"Authorization": "Bearer tok-u2"},
    "expired": {"Authorization": "Bearer tok-expired"},
    "bad": {"Authorization": "Bearer nope"},
    "none": {},
}
BIG = {"X-Company-Id": "co-big"}

CASES: list[dict[str, Any]] = [
    {"d": "no bearer → 401", "url": f"{P}?{WIN}", "hk": "none", "expect": 401},
    {"d": "invalid bearer → 401", "url": f"{P}?{WIN}", "hk": "bad", "expect": 401},
    {"d": "expired bearer → 401", "url": f"{P}?{WIN}", "hk": "expired", "expect": 401},
    {"d": "no bearer + missing dates → 401 (auth before 422)", "url": P, "hk": "none", "expect": 401},
    {"d": "expired + bad limit → 401", "url": f"{P}?{WIN}&limit=abc", "hk": "expired", "expect": 401},
    {"d": "missing both dates → 422 two errors", "url": P, "hk": "u1", "expect": 422},
    {"d": "missing date_from → 422", "url": f"{P}?date_to=2026-12-31", "hk": "u1", "expect": 422},
    {"d": "missing date_to → 422", "url": f"{P}?date_from=2026-01-01", "hk": "u1", "expect": 422},
    {"d": "missing both + bad limit → 422 three errors in order", "url": f"{P}?limit=abc", "hk": "u1", "expect": 422},
    {"d": "bad limit only → 422", "url": f"{P}?{WIN}&limit=abc", "hk": "u1", "expect": 422},
    {"d": "limit '' → 422", "url": f"{P}?{WIN}&limit=", "hk": "u1", "expect": 422},
    {"d": "limit 4301 digits → 422 int_parsing_size", "url": f"{P}?{WIN}&limit={'1' * 4301}", "hk": "u1", "expect": 422},
    {"d": "limit repeated (abc, 2) → last wins", "url": f"{P}?{WIN}&limit=abc&limit=2", "hk": "u1", "expect": 200},
    {"d": "date_from '' → 400", "url": f"{P}?date_from=&date_to=2026-12-31", "hk": "u1", "expect": 400},
    {"d": "date_to '' → 400", "url": f"{P}?date_from=2026-01-01&date_to=", "hk": "u1", "expect": 400},
    {"d": "bare ?date_from&date_to → 400", "url": f"{P}?date_from&date_to", "hk": "u1", "expect": 400},
    {"d": "both '' + bad limit → 422 (validation before 400)", "url": f"{P}?date_from=&date_to=&limit=x", "hk": "u1", "expect": 422},
    {"d": "u1 default co-a (void excluded, leak hidden)", "url": f"{P}?{WIN}", "hk": "u1", "expect": 200},
    {"d": "u2 own", "url": f"{P}?{WIN}", "hk": "u2", "expect": 200},
    {"d": "u1 owned X-Company-Id co-a-alt", "url": f"{P}?{WIN}", "hk": "u1", "extra_hdr": {"X-Company-Id": "co-a-alt"}, "expect": 200},
    {"d": "u1 unowned X-Company-Id co-b → fallback", "url": f"{P}?{WIN}", "hk": "u1", "extra_hdr": {"X-Company-Id": "co-b"}, "expect": 200},
    {"d": "u1 nonexistent X-Company-Id → fallback", "url": f"{P}?{WIN}", "hk": "u1", "extra_hdr": {"X-Company-Id": "co-zzz"}, "expect": 200},
    {"d": "u1 empty X-Company-Id → default", "url": f"{P}?{WIN}", "hk": "u1", "extra_hdr": {"X-Company-Id": ""}, "expect": 200},
    {"d": "u2 X-Company-Id co-a → fallback co-b (leak row not visible to u1 either)", "url": f"{P}?{WIN}", "hk": "u2", "extra_hdr": {"X-Company-Id": "co-a"}, "expect": 200},
    {"d": "unicode / quote dates echoed", "url": P + "?date_from=" + quote('२०२६ "q') + "&date_to=" + quote("é"), "hk": "u1", "expect": 200},
    {"d": "big tenant default limit 5000 (heavy ties)", "url": f"{P}?{WIN}", "hk": "u1", "extra_hdr": BIG, "expect": 200},
    {"d": "big tenant limit=20000", "url": f"{P}?{WIN}&limit=20000", "hk": "u1", "extra_hdr": BIG, "expect": 200},
    {"d": "big tenant limit=99999 → clamp 20000", "url": f"{P}?{WIN}&limit=99999", "hk": "u1", "extra_hdr": BIG, "expect": 200},
    {"d": "big tenant limit=777 (ties across the cut)", "url": f"{P}?{WIN}&limit=777", "hk": "u1", "extra_hdr": BIG, "expect": 200},
    {"d": "big tenant account filter + limit", "url": f"{P}?{WIN}&account_code=BANK&limit=1234", "hk": "u1", "extra_hdr": BIG, "expect": 200},
] + [
    {"d": m["d"], "url": f"{P}?{m['query']}", "hk": "u1", "extra_hdr": {"X-Company-Id": f"m{i:04d}"},
     "expect": m["expect"], "money": True, "fuzz": m["d"].startswith("fuzz")}
    for i, m in enumerate(M)
]


async def run() -> int:
    print(f"[gate7s] DB={DB} (isolated — UAT data untouched)  money cases={len(M)}")
    cli = AsyncIOMotorClient(MONGO, serverSelectionTimeoutMS=5000)
    py = node = None
    try:
        await seed(cli, DB)
        py = start_py(); node = start_node()
        okp = wait(PY_PORT, "/api/"); okn = wait(NODE_PORT, "/health/live")
        print(f"[gate7s] py={okp} node={okn}")
        if not (okp and okn):
            if not okp: print((LOGDIR / "gate7s_py.log").read_text(errors="replace")[-3000:])
            if not okn: print((LOGDIR / "gate7s_node.log").read_text(errors="replace")[-3000:])
            return 2
        await asyncio.sleep(8)

        pdb = cli[DB]
        await pdb.command({"profile": 0})
        await pdb.drop_collection("system.profile")
        await pdb.create_collection("system.profile", capped=True, size=256 * 1024 * 1024)
        await pdb.command({"profile": 2})

        results = []; passed = failed = node_w = py_w_cases = 0
        py_w_colls: set[str] = set()
        for i, c in enumerate(CASES, 1):
            hdr = dict(HDR[c["hk"]]); hdr.update(c.get("extra_hdr", {}))
            h0 = await dbhash(cli, DB)
            rp = raw_get(PY_PORT, c["url"], hdr)
            h1 = await dbhash(cli, DB)
            rn = raw_get(NODE_PORT, c["url"], hdr)
            h2 = await dbhash(cli, DB)
            pw = [k for k in TRACKED if h0.get(k) != h1.get(k)]
            nw = [k for k in TRACKED if h1.get(k) != h2.get(k)]
            if pw: py_w_cases += 1; py_w_colls.update(pw)
            if nw: node_w += 1
            exp = c["expect"]
            status_ok = rp[0] == rn[0] and (exp is None or rp[0] == exp)
            ctype_ok = rp[1] == rn[1]
            bytes_ok = rp[2] == rn[2]
            ok = status_ok and ctype_ok and bytes_ok and not nw
            passed += ok; failed += (not ok)
            count = None
            if rp[0] == 200:
                try: count = json.loads(rp[2]).get("count")
                except Exception: pass
            results.append({"case": i, "desc": c["d"], "verdict": "PASS" if ok else "FAIL",
                            "money": c.get("money", False), "fuzz": c.get("fuzz", False),
                            "py_status": rp[0], "node_status": rn[0], "py_ctype": rp[1], "node_ctype": rn[1],
                            "count": count, "bytes_equal": bytes_ok, "bytes": len(rp[2]),
                            "py_writes": pw, "node_writes": nw,
                            "py_body": "" if bytes_ok else rp[2][:1200].decode("utf-8", "replace"),
                            "node_body": "" if bytes_ok else rn[2][:1200].decode("utf-8", "replace")})

        await pdb.command({"profile": 0})
        prof = await pdb["system.profile"].find({"appName": NODE_APP}, {"op": 1, "ns": 1, "command": 1}).to_list(None)
        kinds: dict[str, int] = {}; by_ns: dict[str, int] = {}; write_ops = 0; limited = 0
        write_names = {"insert", "update", "delete", "findAndModify", "findandmodify", "bulkWrite",
                       "create", "createIndexes", "drop", "dropIndexes", "renameCollection"}
        for p in prof:
            cmd = p.get("command") or {}
            first = next(iter(cmd), "") if isinstance(cmd, dict) else ""
            kinds[f"{p.get('op')}:{first}"] = kinds.get(f"{p.get('op')}:{first}", 0) + 1
            ns = p.get("ns", "").split(".", 1)[-1]
            by_ns[ns] = by_ns.get(ns, 0) + 1
            if first == "find" and ns == "fin_txn" and "limit" in cmd:
                limited += 1
            if p.get("op") in ("insert", "update", "remove") or first in write_names:
                write_ops += 1
        zero_ok = write_ops == 0 and node_w == 0 and by_ns.get("fin_txn", 0) > 0 and limited == 0
        results.append({"case": len(CASES) + 1,
                        "desc": "zero-write + no server-side limit on fin_txn finds — profiler + dbHash",
                        "verdict": "PASS" if zero_ok else "FAIL", "node_profiled_ops": len(prof),
                        "node_op_kinds": kinds, "node_ops_by_ns": by_ns, "node_write_ops": write_ops,
                        "node_fin_txn_finds_with_limit": limited})
        passed += zero_ok; failed += (not zero_ok)

        print("\n" + "=" * 78)
        print("PHASE 3 · GATE 7s · LIVE PARITY MATRIX (Fin Day Book) — BYTE-EXACT + FULL CONTENT-TYPE")
        print("=" * 78)
        for r in results:
            if r.get("money") and r["verdict"] == "PASS":
                continue
            extra = f" count={r['count']} bytes={r['bytes']}" if r.get("count") is not None else ""
            print(f"  [{r['verdict']}] case {r['case']:>4} py={r.get('py_status', '-')} node={r.get('node_status', '-')}{extra}  {r['desc']}")
            if r["verdict"] == "FAIL" and "py_body" in r:
                print(f"      ctype py={r['py_ctype']!r} node={r['node_ctype']!r}  node_writes={r['node_writes']}")
                print(f"      py_body  : {r['py_body']}\n      node_body: {r['node_body']}")
        mon = [r for r in results if r.get("money")]
        fz = [r for r in mon if r.get("fuzz")]
        mix = {s: sum(r["py_status"] == s for r in mon) for s in (200, 500)}
        print(f"  money cases: {sum(r['verdict'] == 'PASS' for r in mon)}/{len(mon)} PASS  "
              f"(fuzz {sum(r['verdict'] == 'PASS' for r in fz)}/{len(fz)}; py status mix {mix})")
        print(f"  node profiled ops={len(prof)} kinds={kinds} write_ops={write_ops} fin_txn finds with limit={limited}")
        print(f"  node ops by collection={by_ns}")
        print("-" * 78)
        print(f"  cases: {len(results)} (fixed {len(CASES) - len(fz)} + fuzz {len(fz)} + zero-write 1)   passed: {passed}   failed: {failed}")
        print(f"  python dbHash-change cases: {py_w_cases} {sorted(py_w_colls)}   node dbHash-change cases: {node_w}")
        print("=" * 78)
        out = LOGDIR / "gate7s_parity_results.json"
        out.write_text(json.dumps({"db": DB, "cases": len(results), "passed": passed, "failed": failed,
                                   "node_write_ops": write_ops, "results": results},
                                  indent=2, default=str, ensure_ascii=False), encoding="utf-8")
        print(f"[gate7s] results → {out}")
        return 0 if failed == 0 else 1
    finally:
        stop(py); stop(node)
        try: await cli[DB].command({"profile": 0})
        except Exception: pass
        try:
            await cli.drop_database(DB)
            print(f"[gate7s] dropped {DB} (UAT data untouched)")
        except Exception as e:
            print(f"[gate7s] drop failed: {e}")
        print(f"[gate7s] leftover gate7s DBs: {[d for d in await cli.list_database_names() if d.startswith('trukvia_gate7s_parity_')]}")
        cli.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
