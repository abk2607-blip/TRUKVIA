"""Phase 3 · Gate 7r · live Python↔Node parity harness for Fin day-closure late-entries.

Covers:
  * GET /api/fin/day-closures/{close_date}/late-entries

Class-C stance:
  Pure-read in Python. Handler executes exactly
    fin_day_closures.find_one({user_id, company_id, close_date}, {_id:0, closed_at:1})
    fin_txn.find({user_id, company_id, status:"active", txn_date:{$lte: close_date},
                  created_at:{$gt: closed_at}}, {_id:0, user_id:0}).sort("txn_date",-1).to_list(5000)
  and aggregates in memory. Zero DB writes.

Comparison is BYTE-EXACT on the response body (plus status and base
content-type): Node rebuilds FastAPI jsonable_encoder + json.dumps output.

Money axes: float() of every stored type, round-half-even round(x, 2),
float accumulation order, NaN / ±Infinity → 500, by_source_type dict
semantics (insertion order, hash merging, duplicate JSON keys), days_late
buckets. Each money case lives in its own company (X-Company-Id) so
fixtures never leak between cases.

Write detection: MongoDB `dbHash` of every tracked collection around each
request + profiler level 2 attributed by driver appName.

Framework-level gaps (NOT counted; owned by the framework gate): invalid
UTF-8 escapes, trailing slash, param > 100 chars.
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
DB = f"trukvia_gate7r_parity_{int(time.time())}"
PY_APP, NODE_APP = "trukvia-gate7r-py", "trukvia-gate7r-node"
PY_PORT, NODE_PORT = 8254, 8255
LOGDIR = Path(tempfile.gettempdir())
CLOSED_AT = "2026-05-10T18:00:00+00:00"
LATE = "2026-05-11T00:00:00+00:00"
_M = object()  # "field missing" marker


def now_iso() -> str: return datetime.now(timezone.utc).isoformat()
def future(s: int) -> str: return (datetime.now(timezone.utc) + timedelta(seconds=s)).isoformat()
def past(s: int) -> str: return (datetime.now(timezone.utc) - timedelta(seconds=s)).isoformat()


def leg(amount: Any = 100.0, direction: Any = "in", stype: Any = "invoice", txn_date: Any = "2026-04-30",
        created_at: Any = LATE, **extra: Any) -> dict[str, Any]:
    d: dict[str, Any] = {"status": "active"}
    for k, v in (("txn_date", txn_date), ("created_at", created_at), ("amount", amount),
                 ("direction", direction), ("source_type", stype)):
        if v is not _M:
            d[k] = v
    d["account_code"] = "AR"
    d.update(extra)
    return d


# ── Money / shape cases, each in its own company ────────────────────────
M: list[dict[str, Any]] = []


def money(desc: str, legs: list[dict[str, Any]], close_date: str = "2026-05-01",
          closed_at: Any = CLOSED_AT, expect: int | None = None) -> None:
    M.append({"d": desc, "legs": legs, "close_date": close_date, "closed_at": closed_at, "expect": expect})


# normal / multi / empty
money("single in leg", [leg(100.0)], expect=200)
money("in + out legs, net", [leg(250.5), leg(100.25, "out")], expect=200)
money("many legs, several source types (insertion order b,a,c)", [
    leg(1.0, stype="b"), leg(2.0, stype="a"), leg(3.0, stype="b"), leg(4.0, "out", "c")], expect=200)
money("closure exists, no late legs", [], expect=200)
money("leg created before close is not late", [leg(5.0, created_at="2026-05-01T00:00:00+00:00")], expect=200)
money("inactive leg excluded", [leg(5.0, status="void")], expect=200)
money("leg after close_date excluded", [leg(5.0, txn_date="2026-05-02")], expect=200)
money("zero amounts", [leg(0.0), leg(0, "out"), leg(-0.0)], expect=200)
money("negative amounts", [leg(-12.345), leg(-0.125, "out")], expect=200)
money("decimal amounts", [leg(0.1), leg(0.2), leg(0.3, "out")], expect=200)
# round-half-even matrix (single leg → totals.in = round(x, 2))
for x in (0.125, 0.375, 0.625, 0.875, 2.675, 1.005, 1.115, 0.285, 1.255, 8.345, 10.125, 1234567.125,
          0.005, 0.015, 0.025, 0.035, 0.045, -0.125, -2.675, 0.1250000000000001, 0.12499999999999999,
          2.5, 1e15 + 0.125, 4503599627370495.5, 5e-324, 1.7976931348623157e308, 0.1 + 0.2):
    money(f"round in={x!r}", [leg(x)], expect=200)
money("net rounding round(round(in)-round(out))", [leg(0.125), leg(0.005, "out")], expect=200)
money("accumulation 0.1 x 10", [leg(0.1) for _ in range(10)], expect=200)
money("accumulation order large+small", [leg(1e16, txn_date="2026-04-30"), leg(1.0, txn_date="2026-04-29"),
                                          leg(-1e16, txn_date="2026-04-28")], expect=200)
money("sum overflows to inf → 500", [leg(1.7976931348623157e308), leg(1.7976931348623157e308)])
money("inf - inf → nan → 500", [leg(float("inf")), leg(float("inf"), "out")])
# stored amount conversions
for label, v in [("str '12.5'", "12.5"), ("str int '42'", "42"), ("str underscores '1_000.25'", "1_000.25"),
                 ("str spaces+arabic digits", " ١٢.5 "), ("str NBSP", " 7.5"),
                 ("str exponent '1e3'", "1e3"), ("str '+.5'", "+.5"), ("str '-5.'", "-5."),
                 ("str '0.125'", "0.125"), ("str empty", ""), ("str math digits", "\U0001d7cf\U0001d7d0"),
                 ("int32 7", 7), ("int64 big", Int64(9007199254740993)), ("bool true", True),
                 ("bool false", False), ("null", None), ("empty list", []), ("empty dict", {}),
                 ("Binary b'2.5'", Binary(b"2.5")), ("Binary empty", Binary(b"")), ("Code '1.5'", Code("1.5"))]:
    money(f"amount {label}", [leg(v)], expect=200)
money("amount missing", [leg(_M)], expect=200)
for label, v in [("str 'abc'", "abc"), ("str '1,5'", "1,5"), ("str '0x10'", "0x10"), ("str '1__0'", "1__0"),
                 ("str '\\x1c1'", "\x1c1"), ("str BOM", "﻿1"), ("str 'inf'", "inf"), ("str '-Infinity'", "-Infinity"),
                 ("str 'nan'", "nan"), ("str '1e400'", "1e400"), ("double NaN", float("nan")),
                 ("double +inf", float("inf")), ("double -inf", float("-inf")), ("Decimal128", Decimal128("1.5")),
                 ("datetime", datetime(2026, 1, 1)), ("ObjectId", ObjectId("65f000000000000000000001")),
                 ("list [1]", [1]), ("dict {a:1}", {"a": 1}), ("Binary b'\\xff'", Binary(b"\xff")),
                 ("Binary b'1 5'", Binary(b"1 5")), ("Timestamp", Timestamp(1, 1))]:
    money(f"amount {label} → 500", [leg(v)], expect=500)
# direction
money("direction variants (IN / missing / out / None)", [leg(1.0, "IN"), leg(2.0, _M), leg(4.0, "out"),
                                                          leg(8.0, None), leg(16.0, "in")], expect=200)
# by_source_type dict semantics
money("source keys int 1, True, str '1' (dup JSON keys)", [leg(1.0, stype=1), leg(1.0, stype=True), leg(1.0, stype="1")], expect=200)
money("source keys True then 1.0", [leg(1.0, stype=True), leg(1.0, stype=1.0)], expect=200)
money("source key double 5.0 / 1e16 / 0.1", [leg(1.0, stype=5.0), leg(1.0, stype=1e16), leg(1.0, stype=0.1)], expect=200)
money("source key int64 big", [leg(1.0, stype=Int64(9007199254740993))], expect=200)
money("source keys numeric-looking strings keep insertion order", [leg(1.0, stype="10"), leg(1.0, stype="2"),
                                                                  leg(1.0, stype="a"), leg(1.0, stype="1")], expect=200)
money("source keys falsy → '' (missing, None, '', 0, -0.0, [], {})", [leg(1.0, stype=_M), leg(1.0, stype=None),
      leg(1.0, stype=""), leg(1.0, stype=0), leg(1.0, stype=-0.0), leg(1.0, stype=[]), leg(1.0, stype={})], expect=200)
money("source key Binary vs str 'hello' (distinct keys)", [leg(1.0, stype=Binary(b"hello")), leg(1.0, stype="hello")], expect=200)
money("source key datetime", [leg(1.0, stype=datetime(2026, 1, 2, 3, 4, 5, 123000))], expect=200)
for label, v in [("list", ["x"]), ("dict", {"a": 1}), ("Code", Code("x")), ("ObjectId", ObjectId("65f000000000000000000002")),
                 ("Decimal128", Decimal128("1")), ("NaN", float("nan")), ("inf", float("inf"))]:
    money(f"source key {label} → 500", [leg(1.0, stype=v)], expect=500)
# days_late buckets
money("days_late buckets 0,7,8,30,31,90,91,400", [leg(1.0, txn_date=d) for d in (
    "2026-05-01", "2026-04-24", "2026-04-23", "2026-04-01", "2026-03-31", "2026-01-31", "2026-01-30", "2025-03-27")], expect=200)
money("txn_date [:10] of longer string", [leg(1.0, txn_date="2026-04-01 extra")], close_date="2026-05-02", expect=200)
money("txn_date unparsable → 0 days", [leg(1.0, txn_date="2026-04-3x"), leg(2.0, txn_date="bad")], expect=200)
money("txn_date array → 0 days", [leg(1.0, txn_date=["2026-04-01"])], expect=200)
money("txn_date astral char at pos 10", [leg(1.0, txn_date="2026-04-0\U0001d7cf")], expect=200)
money("week-date close_date 2026-W18-5", [leg(1.0, txn_date="2026-04-01")], close_date="2026-W18-5", expect=200)
money("compact close_date 20260501", [leg(1.0, txn_date="20260401")], close_date="20260501", expect=200)
money("existing days_late field keeps position", [leg(1.0, days_late=999, zz="tail")], expect=200)
# closed_at variants
money("closed_at '' → every created_at string is late", [leg(1.0, created_at="2000-01-01")], closed_at="", expect=200)
money("closed_at null → ''", [leg(1.0, created_at="2000-01-01")], closed_at=None, expect=200)
money("closed_at numeric 5 → only numeric created_at > 5", [leg(1.0, created_at=6), leg(2.0, created_at="x")], closed_at=5, expect=200)
money("closure without closed_at → 404", [leg(1.0)], closed_at=_M, expect=404)
# row serialisation
money("row field types (datetime, Binary, Code, int64, doubles, nested)", [leg(
    1.0, x_dt=datetime(2026, 1, 2, 3, 4, 5, 123000), x_dt0=datetime(2026, 1, 2), x_bin=Binary(b"hello"),
    x_bin4=Binary(b"\x12\x34\x56\x78" * 4, 4), x_code=Code("c", {"s": 1}), x_i64=Int64(9007199254740993),
    x_d=[5.0, 1e16, 1e15, 1e-5, 1e-4, -0.0, 123456789.123, 5e-324],
    x_nested={"a": [1, 2.0, {"b": None, "c": "q\"\\\n\t\x01 é₹"}]}, x_bool=[True, False])], expect=200)
for label, v in [("ObjectId", ObjectId("65f000000000000000000003")), ("Decimal128", Decimal128("2.5")),
                 ("Timestamp", Timestamp(5, 1)), ("nested NaN", {"a": [float("nan")]}), ("Binary invalid utf-8", Binary(b"\xfe"))]:
    money(f"row field {label} → 500", [leg(1.0, x=v)], expect=500)


def fuzz_amount_strings(n: int = 220) -> list[str]:
    rnd = random.Random(7_000_016)
    alpha = list("0123456789") * 3 + list("._eE+- ") + ["_", "_", "i", "n", "f", "a", "١", " ", "　", "x"]
    return ["".join(rnd.choice(alpha) for _ in range(rnd.randint(1, 9))) for _ in range(n)]


def fuzz_rounding(n: int = 180) -> list[list[tuple[float, str]]]:
    rnd = random.Random(7_000_017)
    out = []
    for _ in range(n):
        legs = []
        for _ in range(rnd.randint(1, 4)):
            base = rnd.choice([rnd.randint(0, 99999) / 1000, rnd.randint(0, 999) / 8, rnd.randint(-5000, 5000) / 200,
                               rnd.uniform(-1e6, 1e6), rnd.randint(0, 10 ** 12) / 1000 + 0.005])
            legs.append((base, rnd.choice(["in", "in", "out"])))
        out.append(legs)
    return out


for s in fuzz_amount_strings():
    money(f"fuzz amount str {s!r}", [leg(s)], expect=None)
for legs in fuzz_rounding():
    money(f"fuzz rounding {len(legs)} legs", [leg(a, d) for a, d in legs], expect=None)
money("5002 late legs → cap 5000", [leg(0.01, txn_date=f"2026-04-{(i % 28) + 1:02d}") for i in range(5002)], expect=200)


def fixtures() -> dict[str, list[dict[str, Any]]]:
    now = now_iso()
    comps = [
        {"id": "co-a",     "user_id": "u1", "is_default": True,  "name": "Acme Co"},
        {"id": "co-a-alt", "user_id": "u1", "is_default": False, "name": "Acme Alt"},
        {"id": "co-b",     "user_id": "u2", "is_default": True,  "name": "Beta Co"},
    ]
    closures = [
        {"id": "c1", "user_id": "u1", "company_id": "co-a", "close_date": "2026-05-01", "status": "closed", "closed_at": CLOSED_AT},
        {"id": "c-alt", "user_id": "u1", "company_id": "co-a-alt", "close_date": "2026-05-01", "status": "closed", "closed_at": CLOSED_AT},
        {"id": "c-u2", "user_id": "u2", "company_id": "co-b", "close_date": "2026-05-01", "status": "reopened", "closed_at": CLOSED_AT},
        {"id": "c-leak", "user_id": "u2", "company_id": "co-a", "close_date": "2026-05-03", "status": "closed", "closed_at": CLOSED_AT},
    ]
    txns = [
        {"id": "t-a1", "user_id": "u1", "company_id": "co-a", **leg(100.125, "in", "invoice")},
        {"id": "t-a2", "user_id": "u1", "company_id": "co-a", **leg(40.0, "out", "expense", txn_date="2026-03-01")},
        {"id": "t-alt", "user_id": "u1", "company_id": "co-a-alt", **leg(7.5, "in", "wallet_recharge")},
        {"id": "t-u2", "user_id": "u2", "company_id": "co-b", **leg(3.25, "in", "invoice")},
        {"id": "t-u2-in-u1co", "user_id": "u2", "company_id": "co-a", **leg(999.0, "in", "leak")},
    ]
    for i, m in enumerate(M):
        co = f"m{i:04d}"
        comps.append({"id": co, "user_id": "u1", "is_default": False, "name": co})
        c = {"id": f"c-{co}", "user_id": "u1", "company_id": co, "close_date": m["close_date"], "status": "closed"}
        if m["closed_at"] is not _M:
            c["closed_at"] = m["closed_at"]
        closures.append(c)
        for j, lg in enumerate(m["legs"]):
            txns.append({"id": f"t-{co}-{j:04d}", "user_id": "u1", "company_id": co, **lg})
    return {
        "user_sessions": [
            {"session_token": "tok-u1",      "user_id": "u1", "effective_role": "owner", "expires_at": future(7200), "last_refreshed_at": now},
            {"session_token": "tok-u2",      "user_id": "u2", "effective_role": "owner", "expires_at": future(7200), "last_refreshed_at": now},
            {"session_token": "tok-expired", "user_id": "u1", "effective_role": "owner", "expires_at": past(60),      "last_refreshed_at": now},
        ],
        "users": [{"user_id": u, "email": f"{u}@x", "name": u.upper(), "picture": "", "created_at": now} for u in ("u1", "u2")],
        "companies": comps,
        "fin_day_closures": closures,
        "fin_txn": txns,
    }


TRACKED = ["users", "user_sessions", "companies", "fin_day_closures", "fin_txn", "audit_logs",
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
        stdout=open(LOGDIR / "gate7r_py.log", "wb"), stderr=subprocess.STDOUT)


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
        stdout=open(LOGDIR / "gate7r_node.log", "wb"), stderr=subprocess.STDOUT)


def raw_get(port: int, path: str, hdr: dict[str, str]) -> tuple[int, str, bytes]:
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
    c.putrequest("GET", path, skip_accept_encoding=True)
    for k, v in hdr.items():
        c.putheader(k, v)
    c.endheaders()
    r = c.getresponse()
    body = r.read()
    ctype = (r.getheader("content-type") or "").split(";")[0].strip()
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


def u(close_date: str) -> str:
    return f"/api/fin/day-closures/{quote(close_date, safe='')}/late-entries"


CASES: list[dict[str, Any]] = [
    {"d": "no bearer → 401", "url": u("2026-05-01"), "hk": "none", "expect": 401},
    {"d": "invalid bearer → 401", "url": u("2026-05-01"), "hk": "bad", "expect": 401},
    {"d": "expired bearer → 401", "url": u("2026-05-01"), "hk": "expired", "expect": 401},
    {"d": "no bearer + invalid date → 401 (auth first)", "url": u("bad"), "hk": "none", "expect": 401},
    {"d": "u1 default co-a", "url": u("2026-05-01"), "hk": "u1", "expect": 200},
    {"d": "no closure for date → 404", "url": u("2026-05-02"), "hk": "u1", "expect": 404},
    {"d": "valid compact date, no closure → 404 raw echo", "url": u("20260501"), "hk": "u1", "expect": 404},
    {"d": "invalid date → 400", "url": u("2026-13-01"), "hk": "u1", "expect": 400},
    {"d": "invalid date text → 400", "url": u("not-a-date"), "hk": "u1", "expect": 400},
    {"d": "unicode date → 400", "url": u("२०२६-05-01"), "hk": "u1", "expect": 400},
    {"d": "encoded slash → 404 Not Found", "url": "/api/fin/day-closures/2026%2F05/late-entries", "hk": "u1", "expect": 404},
    {"d": "encoded slash no auth → 404 Not Found", "url": "/api/fin/day-closures/2026%2F05/late-entries", "hk": "none", "expect": 404},
    {"d": "empty segment → 404 Not Found", "url": "/api/fin/day-closures//late-entries", "hk": "u1", "expect": 404},
    {"d": "query string ignored", "url": u("2026-05-01") + "?limit=1", "hk": "u1", "expect": 200},
    {"d": "cross-user u2 own (reopened closure still served)", "url": u("2026-05-01"), "hk": "u2", "expect": 200},
    {"d": "u1 owned X-Company-Id co-a-alt", "url": u("2026-05-01"), "hk": "u1", "extra_hdr": {"X-Company-Id": "co-a-alt"}, "expect": 200},
    {"d": "u1 unowned X-Company-Id co-b → fallback co-a", "url": u("2026-05-01"), "hk": "u1", "extra_hdr": {"X-Company-Id": "co-b"}, "expect": 200},
    {"d": "u1 nonexistent X-Company-Id → fallback", "url": u("2026-05-01"), "hk": "u1", "extra_hdr": {"X-Company-Id": "co-zzz"}, "expect": 200},
    {"d": "u1 empty X-Company-Id → default", "url": u("2026-05-01"), "hk": "u1", "extra_hdr": {"X-Company-Id": ""}, "expect": 200},
    {"d": "u1 cannot see u2 closure carrying co-a → 404", "url": u("2026-05-03"), "hk": "u1", "expect": 404},
    {"d": "u2 X-Company-Id co-a → fallback co-b", "url": u("2026-05-01"), "hk": "u2", "extra_hdr": {"X-Company-Id": "co-a"}, "expect": 200},
] + [
    {"d": m["d"], "url": u(m["close_date"]), "hk": "u1", "extra_hdr": {"X-Company-Id": f"m{i:04d}"},
     "expect": m["expect"], "money": True, "fuzz": m["d"].startswith("fuzz")}
    for i, m in enumerate(M)
]

INFORMATIONAL = [
    {"d": "[framework] invalid UTF-8 %FF", "url": "/api/fin/day-closures/%FF/late-entries", "hk": "u1"},
    {"d": "[framework] trailing slash", "url": u("2026-05-01") + "/", "hk": "u1"},
    {"d": "[framework] close_date > 100 chars", "url": u("2" * 101), "hk": "u1"},
]


async def run() -> int:
    print(f"[gate7r] DB={DB} (isolated — UAT data untouched)  money cases={len(M)}")
    cli = AsyncIOMotorClient(MONGO, serverSelectionTimeoutMS=5000)
    py = node = None
    try:
        await seed(cli, DB)
        py = start_py(); node = start_node()
        okp = wait(PY_PORT, "/api/"); okn = wait(NODE_PORT, "/health/live")
        print(f"[gate7r] py={okp} node={okn}")
        if not (okp and okn):
            if not okp: print((LOGDIR / "gate7r_py.log").read_text(errors="replace")[-3000:])
            if not okn: print((LOGDIR / "gate7r_node.log").read_text(errors="replace")[-3000:])
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
            results.append({"case": i, "desc": c["d"], "verdict": "PASS" if ok else "FAIL",
                            "money": c.get("money", False), "fuzz": c.get("fuzz", False),
                            "py_status": rp[0], "node_status": rn[0], "py_ctype": rp[1], "node_ctype": rn[1],
                            "bytes_equal": bytes_ok, "py_writes": pw, "node_writes": nw,
                            "py_body": "" if bytes_ok else rp[2][:1200].decode("utf-8", "replace"),
                            "node_body": "" if bytes_ok else rn[2][:1200].decode("utf-8", "replace"),
                            "sample": rp[2][:260].decode("utf-8", "replace") if (ok and not c.get("fuzz")) else ""})

        await pdb.command({"profile": 0})
        prof = await pdb["system.profile"].find({"appName": NODE_APP}, {"op": 1, "ns": 1, "command": 1}).to_list(None)
        kinds: dict[str, int] = {}; by_ns: dict[str, int] = {}; write_ops = 0
        write_names = {"insert", "update", "delete", "findAndModify", "findandmodify", "bulkWrite",
                       "create", "createIndexes", "drop", "dropIndexes", "renameCollection"}
        for p in prof:
            cmd = p.get("command") or {}
            first = next(iter(cmd), "") if isinstance(cmd, dict) else ""
            kinds[f"{p.get('op')}:{first}"] = kinds.get(f"{p.get('op')}:{first}", 0) + 1
            ns = p.get("ns", "").split(".", 1)[-1]
            by_ns[ns] = by_ns.get(ns, 0) + 1
            if p.get("op") in ("insert", "update", "remove") or first in write_names:
                write_ops += 1
        zero_ok = (write_ops == 0 and node_w == 0 and by_ns.get("fin_day_closures", 0) > 0 and by_ns.get("fin_txn", 0) > 0)
        results.append({"case": len(CASES) + 1, "desc": "zero-write — profiler + dbHash across full live matrix",
                        "verdict": "PASS" if zero_ok else "FAIL", "node_profiled_ops": len(prof),
                        "node_op_kinds": kinds, "node_ops_by_ns": by_ns, "node_write_ops": write_ops})
        passed += zero_ok; failed += (not zero_ok)

        info = []
        for c in INFORMATIONAL:
            rp = raw_get(PY_PORT, c["url"], HDR[c["hk"]]); rn = raw_get(NODE_PORT, c["url"], HDR[c["hk"]])
            info.append({"desc": c["d"], "same": (rp[0], rp[2]) == (rn[0], rn[2]),
                         "py": [rp[0], rp[2][:120].decode("utf-8", "replace")],
                         "node": [rn[0], rn[2][:120].decode("utf-8", "replace")]})

        print("\n" + "=" * 78)
        print("PHASE 3 · GATE 7r · LIVE PARITY MATRIX (Fin day-closure late-entries) — BYTE-EXACT")
        print("=" * 78)
        for r in results:
            if r.get("fuzz") and r["verdict"] == "PASS":
                continue
            print(f"  [{r['verdict']}] case {r['case']:>4} py={r.get('py_status', '-')} node={r.get('node_status', '-')}  {r['desc']}")
            if r["verdict"] == "FAIL" and "py_body" in r:
                print(f"      ctype py={r['py_ctype']} node={r['node_ctype']}  node_writes={r['node_writes']}")
                print(f"      py_body  : {r['py_body']}\n      node_body: {r['node_body']}")
        fz = [r for r in results if r.get("fuzz")]
        mix = {s: sum(r["py_status"] == s for r in fz) for s in (200, 500)}
        mon = [r for r in results if r.get("money")]
        print(f"  money cases: {sum(r['verdict'] == 'PASS' for r in mon)}/{len(mon)} PASS  (fuzz {sum(r['verdict'] == 'PASS' for r in fz)}/{len(fz)}, py status mix {mix})")
        print(f"  node profiled ops={len(prof)} kinds={kinds} write_ops={write_ops}")
        print(f"  node ops by collection={by_ns}")
        print("-" * 78)
        print(f"  cases: {len(results)} (fixed {len(CASES) - len(fz)} + fuzz {len(fz)} + zero-write 1)   passed: {passed}   failed: {failed}")
        print(f"  python dbHash-change cases: {py_w_cases} {sorted(py_w_colls)}   node dbHash-change cases: {node_w}")
        print("  informational (framework gate — NOT counted):")
        for x in info:
            print(f"    [{'SAME' if x['same'] else 'DIFF'}] {x['desc']}\n        py   {x['py']}\n        node {x['node']}")
        print("=" * 78)
        out = LOGDIR / "gate7r_parity_results.json"
        out.write_text(json.dumps({"db": DB, "cases": len(results), "passed": passed, "failed": failed,
                                   "node_write_ops": write_ops, "results": results, "informational": info},
                                  indent=2, default=str, ensure_ascii=False), encoding="utf-8")
        print(f"[gate7r] results → {out}")
        return 0 if failed == 0 else 1
    finally:
        stop(py); stop(node)
        try: await cli[DB].command({"profile": 0})
        except Exception: pass
        try:
            await cli.drop_database(DB)
            print(f"[gate7r] dropped {DB} (UAT data untouched)")
        except Exception as e:
            print(f"[gate7r] drop failed: {e}")
        print(f"[gate7r] leftover gate7r DBs: {[d for d in await cli.list_database_names() if d.startswith('trukvia_gate7r_parity_')]}")
        cli.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
