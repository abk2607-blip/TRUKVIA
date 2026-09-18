"""Phase 3 · Gate 7v · live Python↔Node parity harness for the GSTIN offline lookup.

Covers:
  * GET /api/gstin/lookup   (backend/routers/gst.py::gstin_lookup, L31-72)

Python: `get_current_user` then a pure offline parse — no DB, no network.
Comparison is BYTE-EXACT on the body and EXACT on status, the full
content-type header and content-length. Requests are sent over a raw socket
so non-ASCII / malformed query bytes reach both servers unaltered.

Two passes, each with freshly started servers:
  pass A — GSTIN_LOOKUP_API_KEY unset   (note = offline text)
  pass B — GSTIN_LOOKUP_API_KEY="k-7v"  (note = null)

Per request: DB operations are profiled per server (appName). Node may only
touch the auth collections (user_sessions, users) and must never write;
collection checksums (dbHash) must not change.

Recorded separately (framework gate, NOT counted): trailing slash, POST.
"""
from __future__ import annotations
import asyncio, http.client, json, os, signal, socket, subprocess, sys, tempfile, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from motor.motor_asyncio import AsyncIOMotorClient

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "backend"))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017"); os.environ.setdefault("DB_NAME", "gate7v_import_only")
from services import _gstin_checksum  # noqa: E402  (pure function — used only to build valid fixtures)

MONGO = "mongodb://localhost:27017"
DB = f"trukvia_gate7v_parity_{int(time.time())}"
PY_APP, NODE_APP = "trukvia-gate7v-py", "trukvia-gate7v-node"
PY_PORT, NODE_PORT = 8264, 8265
LOGDIR = Path(tempfile.gettempdir())
TRACKED = ["users", "user_sessions", "companies", "audit_logs", "save_health", "idempotency_keys"]
AUTH_COLLS = {"user_sessions", "users"}
AUTH = {"Authorization": "Bearer tok-u1"}
P = "/api/gstin/lookup"


def valid(first14: str) -> str:
    return first14 + _gstin_checksum(first14)


def raw(port: int, method: str, target: bytes, hdr: dict[str, str]):
    s = socket.create_connection(("127.0.0.1", port), timeout=30)
    req = method.encode() + b" " + target + b" HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n"
    for k, v in hdr.items():
        req += f"{k}: {v}\r\n".encode("latin-1")
    s.sendall(req + b"\r\n")
    r = http.client.HTTPResponse(s, method=method)
    r.begin()
    body = r.read()
    headers = {k.lower(): v for k, v in r.getheaders()}
    s.close()
    return r.status, headers, body


def wait(port: int, path: str, timeout: int = 120) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if raw(port, "GET", path.encode(), {})[0] < 500:
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


V1 = "27AAPFU0939F1ZV"
assert valid(V1[:14]) == V1


def q(v: bytes | str) -> bytes:
    return (P + "?gstin=").encode() + (v.encode() if isinstance(v, str) else v)


CASES: list[tuple[str, bytes, dict[str, str], str]] = [
    # auth precedence
    ("GET", q(V1), {}, "no auth"),
    ("GET", P.encode(), {}, "no auth + missing param"),
    ("GET", q(V1), {"Authorization": "Bearer nope"}, "invalid bearer"),
    ("GET", q(V1), {"Cookie": "session_token=tok-u1"}, "session cookie"),
    ("GET", q(""), {"Authorization": "Bearer nope"}, "invalid bearer + empty"),
    # required / empty
    ("GET", P.encode(), AUTH, "missing param"),
    ("GET", (P + "?").encode(), AUTH, "empty query"),
    ("GET", (P + "?other=1").encode(), AUTH, "other param only"),
    ("GET", (P + "?gstin[]=" + V1).encode(), AUTH, "gstin[] key"),
    ("GET", q(""), AUTH, "empty value"),
    ("GET", (P + "?gstin").encode(), AUTH, "key without ="),
    ("GET", q("%20%20%20"), AUTH, "spaces only"),
    ("GET", q("+++"), AUTH, "plus signs only"),
    ("GET", q("%09%0A%0B%0C%0D%1C%1D%1E%1F"), AUTH, "ASCII py-whitespace only"),
    ("GET", q("%C2%85%C2%A0%E3%80%80%E2%80%A8"), AUTH, "unicode whitespace only"),
    ("GET", q("%EF%BB%BF"), AUTH, "BOM only (not py-space)"),
    # repeated keys
    ("GET", (P + "?gstin=AAA&gstin=" + V1).encode(), AUTH, "repeated → last valid"),
    ("GET", (P + "?gstin=" + V1 + "&gstin=").encode(), AUTH, "repeated → last empty"),
    ("GET", (P + "?gstin=" + V1 + "&gstin").encode(), AUTH, "repeated → last bare"),
    ("GET", (P + "?&&gstin=" + V1 + "&&x=1&").encode(), AUTH, "empty fields"),
    ("GET", (P + "?gst%69n=" + V1).encode(), AUTH, "percent-encoded key"),
    ("GET", (P + "?gstin+=" + V1).encode(), AUTH, "key with plus"),
    ("GET", (P + "?=x&gstin=" + V1).encode(), AUTH, "empty key field"),
    ("GET", (P + "?gstin=" + V1 + "=x").encode(), AUTH, "second = in value"),
    # formats
    ("GET", q(V1), AUTH, "valid"),
    ("GET", q(V1.lower()), AUTH, "lowercase"),
    ("GET", q("27%20AAPFU%200939F%201ZV"), AUTH, "internal spaces"),
    ("GET", q("27+AAPFU+0939F+1ZV"), AUTH, "plus as space"),
    ("GET", q("%09%20" + V1 + "%0A%0D%C2%85"), AUTH, "surrounding py-whitespace"),
    ("GET", q("%EF%BB%BF" + V1), AUTH, "leading BOM"),
    ("GET", q(V1 + "%0A"), AUTH, "trailing newline"),
    ("GET", q("27AAPFU0939F1Z%0AV"), AUTH, "internal newline"),
    ("GET", q("27AAPFU0939F1ZV%E3%80%80"), AUTH, "trailing ideographic space"),
    ("GET", q("27AAPFU0939F1Z%09V"), AUTH, "internal tab"),
    ("GET", q("27AAPFU0939F1ZW"), AUTH, "bad checksum"),
    ("GET", q("27AAPFU0939F1YV"), AUTH, "14th not Z"),
    ("GET", q("27AAPFU0939F1Z"), AUTH, "length 14"),
    ("GET", q(V1 + "X"), AUTH, "length 16"),
    ("GET", q("2AAAPFU0939F1ZV"), AUTH, "state not digits"),
    ("GET", q("27AAPF10939F1ZV"), AUTH, "pan shape bad"),
    ("GET", q("%EF%BC%92%EF%BC%97AAPFU0939F1ZV"), AUTH, "fullwidth digits"),
    ("GET", q("27AAPFU0939F1Z%C3%9F"), AUTH, "sharp s → SS (len 16)"),
    ("GET", q("27AAPFU0939F1%EF%AC%81"), AUTH, "ligature fi → FI"),
    ("GET", q("27AAPFU0939F%C4%B1ZV"), AUTH, "dotless i → I"),
    ("GET", q("%C5%BF"), AUTH, "long s → S"),
    ("GET", q("%C6%9B%C9%A4%E1%B2%8A%EA%9F%8D"), AUTH, "post-Unicode-14 lower (unchanged in py)"),
    ("GET", q("%F0%90%B5%B0%F0%96%BA%BB"), AUTH, "post-Unicode-14 astral"),
    ("GET", q("%C3%A9%CE%B1%D0%B6%D5%A1%E1%BA%9E%C7%85%E1%BE%80%E1%BE%B3"), AUTH, "misc case mappings"),
    ("GET", q("%F0%9F%98%80"), AUTH, "emoji"),
    # encoding edge cases (echoed in `gstin`)
    ("GET", q("%zz27"), AUTH, "invalid escape %zz"),
    ("GET", q("abc%"), AUTH, "trailing %"),
    ("GET", q("abc%4"), AUTH, "truncated escape"),
    ("GET", q("%C3"), AUTH, "lone lead byte"),
    ("GET", q("%E0%A4"), AUTH, "truncated 3-byte"),
    ("GET", q("%ED%A0%80"), AUTH, "encoded surrogate"),
    ("GET", q("%F4%90%80%80"), AUTH, "above U+10FFFF"),
    ("GET", q("%C0%AF%FF%FE"), AUTH, "overlong + invalid bytes"),
    ("GET", q("%F0%9F%98"), AUTH, "truncated 4-byte"),
    ("GET", q("%00%01%1F%7F%22%5C%2F"), AUTH, "json escapes"),
    ("GET", q("%E2%80%A8%E2%80%A9"), AUTH, "U+2028/2029"),
    ("GET", q(V1 + "#frag"), AUTH, "hash in target"),
    ("GET", q("%26%3D%3F"), AUTH, "encoded & = ?"),
    ("GET", q("A" * 5000), AUTH, "5000 chars"),
    # HEAD
    ("HEAD", q(V1), AUTH, "HEAD auth"),
    ("HEAD", P.encode(), {}, "HEAD no auth"),
]
# every state code 00..39 plus 97/99 with a valid checksum
for sc in [f"{i:02d}" for i in range(40)] + ["97", "99"]:
    CASES.append(("GET", q(valid(sc + "AAPFU0939F1Z")), AUTH, f"state {sc}"))
# entity codes and checksum characters
for ent in "019AKZ":
    CASES.append(("GET", q(valid("29ABCDE1234F" + ent + "Z")), AUTH, f"entity {ent}"))
for i in range(5):
    CASES.append(("GET", q(V1), AUTH, f"repeat #{i + 1}"))

INFO = [("GET", (P + "/?gstin=" + V1).encode(), AUTH, "trailing slash"),
        ("GET", (P + "/").encode(), AUTH, "trailing slash, missing param"),
        ("POST", q(V1), AUTH, "POST method"),
        # Raw (un-escaped) non-ASCII bytes in the request target are rejected by
        # the HTTP server layer on BOTH sides before routing (h11 400 text/plain
        # "Invalid HTTP request received." vs Node http 400 JSON) — transport gap.
        ("GET", q(b"\xc3\xa9"), AUTH, "raw UTF-8 bytes in target"),
        ("GET", q(b"%C3\xa9"), AUTH, "escape then raw byte")]


async def pass_run(d, label: str, api_key: str | None) -> tuple[int, int, list]:
    py = node = None
    try:
        env = os.environ.copy(); env.pop("GSTIN_LOOKUP_API_KEY", None)
        env.update({"MONGO_URL": f"{MONGO}/?appName={PY_APP}", "DB_NAME": DB, "ENABLE_DEMO_TOKEN": "0", "IS_PREVIEW_ENV": "0",
                    "DISABLE_SCHEDULER": "1", "REGRESSION_GUARD_PERIODIC": "0", "PYTHONIOENCODING": "utf-8"})
        env2 = os.environ.copy(); env2.pop("GSTIN_LOOKUP_API_KEY", None)
        env2.update({"NODE_ENV": "test", "NODE_LOG_LEVEL": "silent", "NODE_PORT": str(NODE_PORT), "NODE_HOST": "127.0.0.1",
                     "NODE_MONGO_URL": f"{MONGO}/?appName={NODE_APP}", "NODE_DB_NAME": DB, "NODE_CORS_ORIGINS": "",
                     "NODE_REQUEST_ID_HEADER": "x-request-id", "NODE_TRUST_INCOMING_REQUEST_ID": "false"})
        if api_key is not None:
            env["GSTIN_LOOKUP_API_KEY"] = api_key; env2["GSTIN_LOOKUP_API_KEY"] = api_key
        py = subprocess.Popen([sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(PY_PORT),
                               "--log-level", "warning", "--no-access-log"], cwd=str(REPO / "backend"), env=env,
                              stdout=open(LOGDIR / f"gate7v_py_{label}.log", "wb"), stderr=subprocess.STDOUT)
        node = subprocess.Popen(["node", str(REPO / "backend-node/dist/server.js")], cwd=str(REPO / "backend-node"), env=env2,
                                stdout=open(LOGDIR / f"gate7v_node_{label}.log", "wb"), stderr=subprocess.STDOUT)
        if not (wait(PY_PORT, "/api/") and wait(NODE_PORT, "/health/live")):
            print(f"[gate7v] pass {label}: servers did not start"); return 0, 1, []
        await asyncio.sleep(8)
        await d.command({"profile": 0}); await d.drop_collection("system.profile")
        await d.create_collection("system.profile", capped=True, size=32 * 1024 * 1024)
        await d.command({"profile": 2})

        cases = CASES if api_key is None else [c for c in CASES if c[3] in (
            "valid", "lowercase", "bad checksum", "length 14", "state 25", "state 27", "empty value",
            "missing param", "no auth", "HEAD auth", "sharp s → SS (len 16)", "encoded surrogate")]
        passed = failed = 0
        rows = []
        py_auth_writes: list = []
        for method, target, hdr, desc in cases:
            n_py0 = await d["system.profile"].count_documents({"appName": PY_APP})
            h0 = (await d.command("dbHash", collections=TRACKED))["collections"]
            rp = raw(PY_PORT, method, target, hdr)
            await asyncio.sleep(0.1)
            n_py1 = await d["system.profile"].count_documents({"appName": PY_APP})
            h_mid = (await d.command("dbHash", collections=TRACKED))["collections"]
            py_changed = [k for k in TRACKED if h0.get(k) != h_mid.get(k)]
            t_nd = datetime.now(timezone.utc) - timedelta(milliseconds=5)
            n_nd0 = await d["system.profile"].count_documents({"appName": NODE_APP})
            rn = raw(NODE_PORT, method, target, hdr)
            await asyncio.sleep(0.1)
            nd_ops = await d["system.profile"].find({"appName": NODE_APP}).skip(n_nd0).to_list(None)
            h1 = (await d.command("dbHash", collections=TRACKED))["collections"]
            changed = [k for k in TRACKED if h_mid.get(k) != h1.get(k)]  # attributable to Node only
            if py_changed:
                py_auth_writes.append((desc, py_changed))
            colls = sorted({(o.get("ns") or ".").split(".", 1)[1] for o in nd_ops})
            same = (rp[0] == rn[0] and rp[2] == rn[2]
                    and rp[1].get("content-type") == rn[1].get("content-type")
                    and rp[1].get("content-length") == rn[1].get("content-length")
                    and rp[1].get("allow") == rn[1].get("allow"))
            ok = same and set(colls) <= AUTH_COLLS and not changed
            passed += ok; failed += (not ok)
            rows.append((ok, desc, method, target, rp, rn, n_py1 - n_py0, len(nd_ops), colls, changed))
        prof = await d["system.profile"].find({"appName": NODE_APP}).to_list(None)
        wn = {"insert", "update", "delete", "findAndModify", "createIndexes", "create", "drop", "bulkWrite"}
        node_writes = [p for p in prof if p.get("op") in ("insert", "update", "remove") or next(iter(p.get("command") or {}), "") in wn]
        node_colls = sorted({(p.get("ns") or ".").split(".", 1)[1] for p in prof})

        print("\n" + "=" * 90 + f"\nPHASE 3 · GATE 7v · LIVE PARITY PASS {label} (GSTIN_LOOKUP_API_KEY={api_key!r})\n" + "=" * 90)
        for ok, desc, method, target, rp, rn, dpy, dnd, colls, changed in rows:
            print(f"  [{'PASS' if ok else 'FAIL'}] {method:4} {desc:40} py={rp[0]} node={rn[0]} len py={rp[1].get('content-length')} "
                  f"node={rn[1].get('content-length')} ct={'=' if rp[1].get('content-type') == rn[1].get('content-type') else 'DIFF'} "
                  f"db py={dpy} node={dnd} {colls} changed={changed or 'none'}")
            if not ok:
                print(f"        target: {target[:120]!r}\n        py  : {rp[1].get('content-type')!r} {rp[2][:400]!r}\n"
                      f"        node: {rn[1].get('content-type')!r} {rn[2][:400]!r}")
        zero_ok = not node_writes and set(node_colls) <= AUTH_COLLS
        passed += zero_ok; failed += (not zero_ok)
        print(f"  [{'PASS' if zero_ok else 'FAIL'}] zero-write / zero-business-read: node ops={len(prof)} writes={len(node_writes)} "
              f"collections={node_colls}")
        print(f"  python-side auth writes (get_current_user sliding session refresh — Python-only, pre-existing, "
              f"NOT the handler): {py_auth_writes or 'none'}")
        info = []
        if api_key is None:
            for method, target, hdr, desc in INFO:
                info.append((desc, method, raw(PY_PORT, method, target, hdr), raw(NODE_PORT, method, target, hdr)))
            print("  informational (framework gate — NOT counted):")
            for desc, method, rp, rn in info:
                print(f"    {method:4} {desc:30} py={rp[0]} {rp[2][:70]!r} loc={rp[1].get('location')!r} allow={rp[1].get('allow')!r}"
                      f" | node={rn[0]} {rn[2][:70]!r}")
        print(f"  pass {label}: cases {len(rows) + 1}  passed {passed}  failed {failed}")
        return passed, failed, [(r[1], r[4][0], r[4][2][:200].decode("utf-8", "replace")) for r in rows]
    finally:
        stop(py); stop(node)
        try: await d.command({"profile": 0})
        except Exception: pass


async def run() -> int:
    print(f"[gate7v] DB={DB} (isolated — UAT data untouched)")
    cli = AsyncIOMotorClient(MONGO, serverSelectionTimeoutMS=5000)
    d = cli[DB]
    try:
        now = datetime.now(timezone.utc)
        await d.user_sessions.insert_one({"session_token": "tok-u1", "user_id": "u1", "effective_role": "owner",
                                          "expires_at": (now + timedelta(hours=2)).isoformat(), "last_refreshed_at": now.isoformat()})
        await d.users.insert_one({"user_id": "u1", "email": "u1@x", "name": "U1"})
        await d.companies.insert_one({"id": "co-a", "user_id": "u1", "is_default": True, "name": "A"})
        pa, fa, sample = await pass_run(d, "A", None)
        pb, fb, _ = await pass_run(d, "B", "k-7v")
        total_p, total_f = pa + pb, fa + fb
        print("=" * 90 + f"\n  TOTAL passed {total_p}  failed {total_f}\n" + "=" * 90)
        (LOGDIR / "gate7v_parity_results.json").write_text(json.dumps(
            {"db": DB, "passA": [pa, fa], "passB": [pb, fb], "passed": total_p, "failed": total_f,
             "python_samples": sample}, indent=2, ensure_ascii=False), encoding="utf-8")
        return 0 if total_f == 0 else 1
    finally:
        await cli.drop_database(DB)
        print(f"[gate7v] dropped {DB}; leftover gate7v DBs: "
              f"{[x for x in await cli.list_database_names() if x.startswith('trukvia_gate7v_parity_')]}")
        cli.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
