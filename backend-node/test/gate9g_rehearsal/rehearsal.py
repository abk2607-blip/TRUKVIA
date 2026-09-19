"""Phase 4 · Gate 9g · pre-production rehearsal (local, throwaway, read-only application traffic).

Environment (closest safe production-like setup available on this workstation):
  * a THROWAWAY auth-enabled mongod (:27018, temp dbpath, --auth) — users: root
    (Python, the only writer), node_ro (strategy 1: role `read`) and node_idx
    (strategy 2: `read` + createIndex on idempotency_keys only);
  * Python reference   uvicorn :8400  routing OFF          (today's production)
  * Python front door  uvicorn :8401  routing per scenario (backend/node_router.py)
  * Node               deploy/supervisor/run-backend-node.sh → dist/server.js on
                       127.0.0.1:8002 (NODE_ENV=production, git-ignored-style .env)
  * fake upstream      :8403 (fake_upstream.py) for failure injection.
NOT available here (reported, never claimed): supervisord itself (Unix-only; no
WSL/Docker on this host) — auto-restart / retries / TERM / log rotation are
platform-only. The harness restarts Node itself where a supervisor would.

Output: sections A–J with pass/fail per check, plus FINDINGS.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from pymongo import MongoClient
from pymongo.errors import OperationFailure

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
NODE_DIR = REPO / "backend-node"
WRAPPER = REPO / "deploy" / "supervisor" / "run-backend-node.sh"
MONGOD = Path(r"C:\Program Files\MongoDB\Server\7.0\bin\mongod.exe")
SH = shutil.which("sh") or r"C:\Program Files\Git\bin\sh.exe"
TMP = Path(tempfile.mkdtemp(prefix="gate9g_"))
DBPATH = TMP / "db"
MPORT, P_REF, P_FD, NODE, FAKE = 27018, 8400, 8401, 8002, 8403
DB = "trukvia_gate9g_rehearsal"
ROOT_PW, RO_PW, IDX_PW = "RootPwSECRETMARK1", "RoPwSECRETMARK2", "IdxPwSECRETMARK3"
SECRET_TOKEN = "tok-SECRETMARK-7f3a"
SECRET_COOKIE = "cookieSECRETMARK"
SECRET_QUERY = "qSECRETMARK"
KILL = TMP / "node-routing-kill"
ROOT_URL = f"mongodb://root:{ROOT_PW}@127.0.0.1:{MPORT}/?authSource=admin"
R4 = "/api/vendors,/api/vendors/:vid,/api/company-bank-accounts,/api/fin/day-book"
SECRETS = [ROOT_PW, RO_PW, IDX_PW, SECRET_TOKEN, SECRET_COOKIE, SECRET_QUERY]

_spec = importlib.util.spec_from_file_location("g9c", NODE_DIR / "test" / "gate9c_parity" / "harness.py")
g9c = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(g9c)  # type: ignore[union-attr]
ROUTES = g9c.ALLOWLIST_ROUTES

results: dict[str, list[bool]] = {}
fails: list[str] = []
findings: list[str] = []
logs_to_scan: list[Path] = []


def rec(group: str, ok: bool, msg: str = "") -> None:
    results.setdefault(group, []).append(bool(ok))
    if not ok:
        fails.append(f"{group}: {msg}"[:400])


def port_open(port: int) -> bool:
    try:
        socket.create_connection(("127.0.0.1", port), 0.5).close()
        return True
    except OSError:
        return False


def wait_port(port: int, up: bool = True, secs: float = 60) -> bool:
    end = time.time() + secs
    while time.time() < end:
        if port_open(port) == up:
            return True
        time.sleep(0.25)
    return False


def kill_tree(p: subprocess.Popen | None) -> None:
    if p and p.poll() is None:
        subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
        try:
            p.wait(timeout=10)
        except Exception:
            pass


def req(port, method, target, hdr=()):
    s = socket.create_connection(("127.0.0.1", port), timeout=30)
    h = b"".join(f"{k}: {v}\r\n".encode("latin-1") for k, v in hdr)
    s.sendall(method.encode() + b" " + target.encode("latin-1") + b" HTTP/1.1\r\nHost: api.example\r\nConnection: close\r\n" + h + b"\r\n")
    out = b""
    while True:
        c = s.recv(1 << 20)
        if not c:
            break
        out += c
    s.close()
    head, _, body = out.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    hs, chunked = [], False
    for ln in lines[1:]:
        k, _, v = ln.partition(":")
        k = k.strip().lower(); v = v.strip()
        if k == "transfer-encoding":
            chunked = "chunked" in v.lower(); continue
        if k in ("date", "connection"):
            continue
        hs.append((k, v))
    if chunked:
        o, r = b"", body
        while r:
            n_, _, r = r.partition(b"\r\n"); n = int(n_.split(b";")[0] or b"0", 16)
            if n == 0:
                break
            o += r[:n]; r = r[n + 2:]
        body = o
    return lines[0], sorted(hs), body


class Log:
    def __init__(self, path: Path):
        self.path, self.pos = path, 0

    def new(self) -> list[dict]:
        time.sleep(0.06)
        data = self.path.read_bytes()[self.pos:] if self.path.exists() else b""
        self.pos += len(data)
        out = []
        for ln in data.decode("utf-8", "replace").splitlines():
            i = ln.find('{"event": "node_router')
            if i >= 0:
                try:
                    ev = json.loads(ln[i:])
                except ValueError:
                    continue
                out.append(ev)
        return out


def targets(evs):
    return [e["target"] for e in evs if e.get("event") == "node_router"]


# ── mongod (throwaway, auth) ─────────────────────────────────────────────
mongod: subprocess.Popen | None = None


def start_mongod() -> None:
    global mongod
    DBPATH.mkdir(parents=True, exist_ok=True)
    mongod = subprocess.Popen([str(MONGOD), "--dbpath", str(DBPATH), "--port", str(MPORT), "--bind_ip", "127.0.0.1", "--auth",
                               "--quiet", "--logpath", str(TMP / "mongod.log")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert wait_port(MPORT), "mongod did not start"


def stop_mongod() -> None:
    if mongod and mongod.poll() is None:
        try:
            MongoClient(ROOT_URL, serverSelectionTimeoutMS=3000).admin.command("shutdown")
        except Exception:
            pass
        try:
            mongod.wait(timeout=30)
        except Exception:
            kill_tree(mongod)
    wait_port(MPORT, up=False, secs=30)


def setup_auth() -> None:
    boot = MongoClient(f"mongodb://127.0.0.1:{MPORT}/", serverSelectionTimeoutMS=5000)
    boot.admin.command("createUser", "root", pwd=ROOT_PW, roles=["root"])
    root = MongoClient(ROOT_URL)
    d = root[DB]
    seeds = g9c.seed_docs()
    seeds["user_sessions"].append(g9c.sess(SECRET_TOKEN, "u1"))
    seeds["user_sessions"] += [g9c.sess(f"tok-pct-{i:03d}", "u1") for i in range(200)]
    for coll, rows in seeds.items():
        if rows:
            d[coll].insert_many([dict(r) for r in rows])
    # Strategy 1: the operator (or Python, which already does this at startup) pre-creates
    # the ONLY index Node's boot touches, then Node runs with a genuinely read-only user.
    d.idempotency_keys.create_index("created_at", expireAfterSeconds=86400, name="ttl_created_at")
    d.command("createUser", "node_ro", pwd=RO_PW, roles=[{"role": "read", "db": DB}])
    # Strategy 2: read + createIndex on idempotency_keys ONLY (narrow startup permission).
    d.command("createRole", "nodeStartupIndex", privileges=[{"resource": {"db": DB, "collection": "idempotency_keys"},
                                                            "actions": ["createIndex"]}], roles=[{"role": "read", "db": DB}])
    d.command("createUser", "node_idx", pwd=IDX_PW, roles=[{"role": "nodeStartupIndex", "db": DB}])


def node_url(user: str, pw: str) -> str:
    return f"mongodb://{user}:{pw}@127.0.0.1:{MPORT}/{DB}?authSource={DB}&appName=trukvia-gate9g-node"


def node_env_file(name: str, **over: str) -> Path:
    vals = {"NODE_ENV": "production", "NODE_LOG_LEVEL": "info", "NODE_HOST": "127.0.0.1", "NODE_PORT": str(NODE),
            "NODE_MONGO_URL": node_url("node_ro", RO_PW), "NODE_DB_NAME": DB, "NODE_CORS_ORIGINS": "",
            "NODE_REQUEST_ID_HEADER": "x-request-id", "NODE_TRUST_INCOMING_REQUEST_ID": "true"}
    vals.update(over)
    p = TMP / (re.sub(r"[^A-Za-z0-9_-]", "_", name) + ".env")
    # Values are QUOTED: a Mongo URL contains `&`, which an unquoted sourced line would treat as `&` (background).
    # LF endings: a CRLF file would leave a trailing \r inside every sourced value.
    p.write_text("".join(f'{k}="{v}"\n' for k, v in vals.items() if v is not None), encoding="utf-8", newline="\n")
    return p


def start_node(env_file: Path, name: str) -> tuple[subprocess.Popen, Path]:
    log = TMP / f"{name}.log"
    logs_to_scan.append(log)
    env = {k: v for k, v in os.environ.items() if not k.startswith("NODE_")}
    env.update({"APP_DIR": str(NODE_DIR), "NODE_ENV_FILE": str(env_file)})
    p = subprocess.Popen([SH, str(WRAPPER)], env=env, stdout=open(log, "wb"), stderr=subprocess.STDOUT)
    return p, log


def run_wrapper(env_file: Path | None, app_dir: Path = NODE_DIR, extra: dict | None = None, secs: float = 25) -> tuple[int | None, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("NODE_")}
    env.update({"APP_DIR": str(app_dir), "NODE_ENV_FILE": str(env_file or TMP / "absent.env")})
    env.update(extra or {})
    try:
        r = subprocess.run([SH, str(WRAPPER)], env=env, capture_output=True, timeout=secs)
        return r.returncode, (r.stdout + r.stderr).decode("utf-8", "replace")
    except subprocess.TimeoutExpired as e:
        return None, ((e.stdout or b"") + (e.stderr or b"")).decode("utf-8", "replace")


def run_node_direct(env: dict, secs: float = 25) -> tuple[int | None, str]:
    base = {k: v for k, v in os.environ.items() if not k.startswith("NODE_")}
    base.update(env)
    try:
        r = subprocess.run(["node", "dist/server.js"], cwd=NODE_DIR, env=base, capture_output=True, timeout=secs)
        return r.returncode, (r.stdout + r.stderr).decode("utf-8", "replace")
    except subprocess.TimeoutExpired as e:
        return None, ((e.stdout or b"") + (e.stderr or b"")).decode("utf-8", "replace")


def start_py(port: int, name: str, extra: dict) -> tuple[subprocess.Popen, Path]:
    log = TMP / f"{name}.log"
    logs_to_scan.append(log)
    env = {k: v for k, v in os.environ.items() if not k.startswith("NODE_ROUTING") and k not in ("CORS_ORIGINS", "NODE_UPSTREAM_URL")}
    env.update({"MONGO_URL": f"{ROOT_URL}&appName=trukvia-gate9g-{name}", "DB_NAME": DB, "ENABLE_DEMO_TOKEN": "0",
                "IS_PREVIEW_ENV": "0", "DISABLE_SCHEDULER": "1", "REGRESSION_GUARD_PERIODIC": "0", "PYTHONIOENCODING": "utf-8",
                "PYTHONUNBUFFERED": "1", "NODE_ROUTING_KILL_FILE": str(KILL)})
    env.update(extra)
    p = subprocess.Popen([sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(port),
                          "--log-level", "warning", "--no-access-log"], cwd=REPO / "backend", env=env,
                         stdout=open(log, "wb"), stderr=subprocess.STDOUT)
    assert wait_port(port, secs=120), f"python {name} did not start"
    time.sleep(6)
    return p, log


def dbhash(colls: list[str]) -> dict:
    return MongoClient(ROOT_URL)[DB].command("dbHash", collections=colls)["collections"]


def node_ops(since: float) -> list[dict]:
    d = MongoClient(ROOT_URL)[DB]
    return list(d["system.profile"].find({"appName": "trukvia-gate9g-node", "ts": {"$gte": since}}))


def is_write(p: dict) -> bool:
    c = p.get("command") or {}
    return p.get("op") in ("insert", "update", "remove") or next(iter(c), "") in (
        "insert", "update", "delete", "findAndModify", "createIndexes", "create", "drop", "dropIndexes")


OWN = [("Authorization", "Bearer tok-owner")]


def main() -> int:  # noqa: C901 — linear rehearsal script
    from datetime import datetime, timezone
    procs: dict[str, subprocess.Popen] = {}
    t_start = datetime.now(timezone.utc)
    try:
        start_mongod()
        setup_auth()
        root = MongoClient(ROOT_URL)
        rdb = root[DB]
        business = sorted(c for c in rdb.list_collection_names() if c not in ("user_sessions", "companies", "system.profile"))
        h_begin = dbhash(business)

        # ═══ A · configuration / wrapper validation ═══════════════════════
        for label, over, code in [("public bind 0.0.0.0", {"NODE_HOST": "0.0.0.0"}, 64), ("public bind ::", {"NODE_HOST": "::"}, 64),
                                  ("host unset", {"NODE_HOST": None}, 64), ("mongo url missing", {"NODE_MONGO_URL": None}, None),
                                  ("db name missing", {"NODE_DB_NAME": None}, None), ("NODE_ENV missing", {"NODE_ENV": None}, None)]:
            rc, out = run_wrapper(node_env_file(f"a-{label.replace(' ', '_')}", **over))
            rec("A wrapper refuses unsafe/missing config", rc not in (0, None) and (code is None or rc == code), f"{label}: rc={rc} {out[:160]}")
            logs_to_scan.append(TMP / f"a-out-{len(logs_to_scan)}.txt"); logs_to_scan[-1].write_text(out, encoding="utf-8")
        rc, out = run_wrapper(node_env_file("a-nodist"), app_dir=TMP / "no-build")
        rec("A wrapper refuses missing build", rc == 66, f"rc={rc} {out[:160]}")
        # sourcing an UNQUOTED Mongo URL containing '&' breaks the variable (template must say: quote values)
        unq = TMP / "a-unquoted.env"
        unq.write_text(f"NODE_ENV=production\nNODE_HOST=127.0.0.1\nNODE_PORT={NODE}\nNODE_DB_NAME={DB}\n"
                       f"NODE_MONGO_URL=mongodb://node_ro:{RO_PW}@127.0.0.1:{MPORT}/{DB}?authSource={DB}&appName=x\n", encoding="utf-8",
                       newline="\n")
        rc, out = run_wrapper(unq, secs=15)
        if rc not in (0, None):
            findings.append("F1 (fixed in docs): an UNQUOTED .env value containing '&' (every Mongo URL with options) is split by "
                            "`. $ENV_FILE`; the wrapper then refuses to start. Values must be double-quoted.")
        rec("A unquoted '&' URL is rejected, not silently truncated", rc not in (0, None), f"rc={rc}")
        logs_to_scan.append(TMP / "a-unquoted-out.txt"); logs_to_scan[-1].write_text(out, encoding="utf-8")
        base_env = {"NODE_ENV": "production", "NODE_LOG_LEVEL": "info", "NODE_HOST": "127.0.0.1", "NODE_PORT": str(NODE),
                    "NODE_MONGO_URL": node_url("node_ro", RO_PW), "NODE_DB_NAME": DB, "NODE_CORS_ORIGINS": ""}
        for label, over in [("NODE_ENV invalid", {"NODE_ENV": "prod"}), ("NODE_PORT invalid", {"NODE_PORT": "abc"}),
                            ("mongo url not mongodb://", {"NODE_MONGO_URL": "http://x"}), ("host missing", {"NODE_HOST": ""}),
                            ("log level invalid", {"NODE_LOG_LEVEL": "verbose"}),
                            ("production DB name containing 'prod' (safety guard)", {"NODE_DB_NAME": "trukvia_prod"}),
                            ("wrong DB password", {"NODE_MONGO_URL": node_url("node_ro", "WrongPwSECRETMARK4")})]:
            env = {**base_env, **over}
            rc, out = run_node_direct({k: v for k, v in env.items() if v != ""})
            rec("A node refuses invalid production config (fail loud)", rc not in (0, None), f"{label}: rc={rc} {out[:200]}")
            rec("A config errors never echo credentials", not any(s in out for s in SECRETS + ["WrongPwSECRETMARK4"]),
                f"{label}: {out[:300]}")

        # ═══ B · DB permission strategy ═══════════════════════════════════
        ro = MongoClient(node_url("node_ro", RO_PW))[DB]
        try:
            ro.vendors.insert_one({"x": 1}); ok = False
        except OperationFailure as e:
            ok = e.code == 13
        rec("B1 strategy-1 node_ro cannot write", ok)
        try:
            ro.idempotency_keys.create_index("created_at", expireAfterSeconds=86400, name="ttl_created_at"); ok = False
        except OperationFailure as e:
            ok = e.code == 13
        rec("B1 strategy-1 node_ro cannot even createIndex", ok)
        rec("B1 strategy-1 node_ro can read", ro.vendors.count_documents({}) > 0)
        idx = MongoClient(node_url("node_idx", IDX_PW))[DB]
        idx.idempotency_keys.create_index("created_at", expireAfterSeconds=86400, name="ttl_created_at")
        for label, fn in [("insert idempotency_keys", lambda: idx.idempotency_keys.insert_one({"x": 1})),
                          ("insert vendors", lambda: idx.vendors.insert_one({"x": 1})),
                          ("createIndex vendors", lambda: idx.vendors.create_index("zz"))]:
            try:
                fn(); ok = False
            except OperationFailure as e:
                ok = e.code == 13
            rec("B2 strategy-2 node_idx: only createIndex on idempotency_keys", ok, label)
        rdb.command({"profile": 2})
        for user, pw, label in (("node_idx", IDX_PW, "strategy 2"), ("node_ro", RO_PW, "strategy 1")):
            t0 = datetime.now(timezone.utc)
            p, log = start_node(node_env_file(f"b-{user}", NODE_MONGO_URL=node_url(user, pw)), f"node-b-{user}")
            up = wait_port(NODE, secs=60)
            st, _h, body = req(NODE, "GET", "/health/ready") if up else ("down", [], b"")
            rec(f"B3 node boots and is ready with {label} user", up and "200" in st and b'"registered_routes":66' in body, f"{st} {body[:160]}")
            if user == "node_ro":
                procs["node"] = p
                time.sleep(1)
                ops = node_ops(t0)
                rec("B3 read-only boot: no successful write", not [o for o in ops if is_write(o) and o.get("ok", 1) == 1 and not o.get("errCode")],
                    str([o.get("command") for o in ops if is_write(o)])[:300])
            else:
                kill_tree(p); wait_port(NODE, up=False)
        idx_names = sorted(i["name"] for i in rdb.idempotency_keys.list_indexes())
        rec("B4 only the pre-created TTL index exists", idx_names == ["_id_", "ttl_created_at"], str(idx_names))

        # ═══ C · health / readiness (live) ═══════════════════════════════
        t0 = datetime.now(timezone.utc)
        for _ in range(10):
            s1 = req(NODE, "GET", "/health/live")[0]; s2 = req(NODE, "GET", "/health/ready")[0]
        rec("C1 live 200 / ready 200", "200" in s1 and "200" in s2, f"{s1} {s2}")
        time.sleep(1)
        cmds = sorted({next(iter(o.get("command") or {"?": 1})) for o in node_ops(t0)})
        rec("C2 readiness touches no business data (ping only)", set(cmds) <= {"ping"}, str(cmds))
        stop_mongod()
        time.sleep(1)
        t_down = time.time()
        st = req(NODE, "GET", "/health/ready")
        rec("C3 DB down → ready 503 (live stays 200)", "503" in st[0] and b'"mongo":"unavailable"' in st[2]
            and "200" in req(NODE, "GET", "/health/live")[0], f"{st[0]} {st[2][:120]} after {time.time() - t_down:.1f}s")
        kill_tree(procs.pop("node")); wait_port(NODE, up=False)
        rc, out = run_wrapper(node_env_file("c-dbdown"), secs=40)
        rec("C4 DB down at boot → node exits non-zero (supervisor would retry)", rc not in (0, None), f"rc={rc} {out[-200:]}")
        logs_to_scan.append(TMP / "c-dbdown-out.txt"); logs_to_scan[-1].write_text(out, encoding="utf-8")
        start_mongod()
        # Full-window profiler (64 MB) BEFORE any Python process starts, so every later write is attributable.
        rdb.command({"profile": 0}); rdb.drop_collection("system.profile")
        rdb.create_collection("system.profile", capped=True, size=64 * 1024 * 1024)
        rdb.command({"profile": 2})
        h_begin = dbhash(business)
        p, nlog = start_node(node_env_file("main"), "node-main"); procs["node"] = p
        rec("C5 DB back → node ready 200", wait_port(NODE) and "200" in (time.sleep(1) or req(NODE, "GET", "/health/ready"))[0])

        # ═══ D · routing modes (Python reference vs front door) ══════════
        procs["ref"], _ = start_py(P_REF, "py-ref", {})
        procs["fd"], fdlog = start_py(P_FD, "py-fd-off", {})
        rdb.command({"profile": 2})
        log = Log(fdlog); log.new()
        t0 = datetime.now(timezone.utc)
        for _n, t in ROUTES:
            a, b = req(P_REF, "GET", t, OWN), req(P_FD, "GET", t, OWN)
            rec("D1 MODE off: identical to Python, nothing forwarded", a == b and not targets(log.new()), t)
        time.sleep(1)
        rec("D1 MODE off: Node received zero requests", not node_ops(t0), f"{len(node_ops(t0))} ops")

        def restart_fd(name: str, extra: dict) -> Log:
            kill_tree(procs.pop("fd")); wait_port(P_FD, up=False)
            procs["fd"], lp = start_py(P_FD, name, extra)
            lg = Log(lp)
            evs = lg.new()
            return lg, evs

        ON = {"NODE_ROUTING_MODE": "on", "NODE_ROUTING_ROUTES": R4, "NODE_ROUTING_PERCENT": "100",
              "NODE_UPSTREAM_URL": f"http://127.0.0.1:{NODE}"}
        log, evs = restart_fd("py-fd-r4", ON)
        req(P_FD, "GET", "/api/vendors", OWN)  # validation is lazy: runs on the first request after start
        evs = log.new()
        rec("D2 first request: router validated + enabled for exactly 4 routes",
            any(e.get("event") == "node_router_enabled" and e.get("routes") == 4 for e in evs), str(evs))
        for name, t in ROUTES:
            a, b = req(P_REF, "GET", t, OWN), req(P_FD, "GET", t, OWN)
            tg = targets(log.new())
            want = "node" if name in ("vendors", "vendors/:vid", "company-bank-accounts", "fin/day-book") else "python"
            rec("D2 explicit route set: only listed routes reach Node", (tg == ["node"]) == (want == "node") and a == b,
                f"{name} {tg} {a[0]} {b[0]}")
        for m, t in [("POST", "/api/vendors"), ("PUT", "/api/vendors/v-b"), ("DELETE", "/api/vendors/v-b"), ("GET", "/api/trips"),
                     ("GET", "/api/saved-trip-filters"), ("GET", "/api/vendors/"), ("GET", "/api/auth/me"), ("GET", "/api/nope"),
                     ("HEAD", "/api/trips"), ("GET", "/")]:
            a, b = req(P_REF, m, t), req(P_FD, m, t)
            rec("D2 Python-owned requests never reach Node", "node" not in targets(log.new()) and a[0] == b[0], f"{m} {t}")
        log, _ = restart_fd("py-fd-pct", {**ON, "NODE_ROUTING_ROUTES": "/api/vendors", "NODE_ROUTING_PERCENT": "50"})
        passes = []
        for _rep in range(2):
            tg_all = []
            for i in range(200):
                h = [("Authorization", f"Bearer tok-pct-{i:03d}")]
                a, b = req(P_REF, "GET", "/api/vendors", h), req(P_FD, "GET", "/api/vendors", h)
                tg = targets(log.new())
                tg_all.append(tg[0] if tg else "?")
                rec("D3 percentage: every response identical to Python", a == b, f"tok {i}")
            passes.append(tg_all)
        share = passes[0].count("node") / 200
        rec("D3 percentage: ~50% share and stable per token", 0.40 <= share <= 0.60 and passes[0] == passes[1], f"share={share}")
        log, _ = restart_fd("py-fd-kill", ON)
        req(P_FD, "GET", "/api/vendors", OWN); log.new()
        KILL.write_text("kill"); t_k = time.time()
        time.sleep(1.1)
        for _i in range(10):
            a, b = req(P_REF, "GET", "/api/vendors", OWN), req(P_FD, "GET", "/api/vendors", OWN)
            evs = [e for e in log.new() if e.get("event") == "node_router"]
            rec("D4 kill switch: Python immediately, no restart", a == b and [e["reason"] for e in evs] == ["kill-switch"], str(evs))
        rec("D4 kill switch effective within 1.2 s", time.time() - t_k < 30)
        KILL.unlink(); time.sleep(1.1)
        req(P_FD, "GET", "/api/vendors", OWN)
        rec("D4 kill file removed → Node again", targets(log.new()) == ["node"])
        log, _ = restart_fd("py-fd-off2", {})
        for _n, t in ROUTES[:20]:
            req(P_FD, "GET", t, OWN)
            rec("D5 restart with routing unset → Python only", not targets(log.new()), t)
        for label, extra, forwarded_ok in [
                ("deferred route listed", {**ON, "NODE_ROUTING_ROUTES": "/api/vendors,/api/trips"}, False),
                ("unknown route listed", {**ON, "NODE_ROUTING_ROUTES": "/api/vendors,/api/nope"}, False),
                ("percent not a number", {**ON, "NODE_ROUTING_PERCENT": "abc"}, False),
                ("mode 'yes' (not 'on')", {**ON, "NODE_ROUTING_MODE": "yes"}, False),
                ("allowlist unreadable", {**ON, "NODE_ALLOWLIST_PATH": str(TMP / "nope")}, False),
                ("upstream URL malformed", {**ON, "NODE_UPSTREAM_URL": "http://[bad"}, False),
                ("upstream not http", {**ON, "NODE_UPSTREAM_URL": "ftp://127.0.0.1:8002"}, False)]:
            log, _ = restart_fd("py-fd-mis", extra)
            for _n, t in ROUTES[:6]:
                a, b = req(P_REF, "GET", t, OWN), req(P_FD, "GET", t, OWN)
                tg = targets(log.new())
                rec("D6 misconfiguration → safe Python responses", a == b and "node" not in tg, f"{label}: {t} {a[0]} vs {b[0]} {tg}")

        # ═══ E · failure injection (fake upstream) ═══════════════════════
        state = TMP / "fake"; state.mkdir(exist_ok=True)
        (state / "mode").write_text("ok")
        FAIL = {**ON, "NODE_ROUTING_ROUTES": "/api/vendors", "NODE_UPSTREAM_URL": f"http://127.0.0.1:{FAKE}",
                "NODE_ROUTING_READ_TIMEOUT_S": "1"}
        log, _ = restart_fd("py-fd-fake", FAIL)
        hits = lambda: len((state / "hits").read_text().splitlines()) if (state / "hits").exists() else 0  # noqa: E731
        vend_finds = lambda: rdb["system.profile"].count_documents({"appName": "trukvia-gate9g-py-fd-fake", "command.find": "vendors"})  # noqa: E731
        h0b = dbhash(business)
        a, b = req(P_REF, "GET", "/api/vendors", OWN), req(P_FD, "GET", "/api/vendors", OWN)
        evs = [e for e in log.new() if e.get("event") == "node_router"]
        rec("E connection refused → Python fallback", a == b and [e["target"] for e in evs] == ["python-fallback"], str(evs))
        procs["fake"] = subprocess.Popen([sys.executable, str(HERE / "fake_upstream.py"), str(FAKE), str(state)])
        wait_port(FAKE)
        for mode in ("hang", "garbage", "close", "s502", "s503", "s504", "s431"):
            (state / "mode").write_text(mode)
            h1, f1 = hits(), vend_finds()
            a, b = req(P_REF, "GET", "/api/vendors", OWN), req(P_FD, "GET", "/api/vendors", OWN)
            time.sleep(0.3)
            evs = [e for e in log.new() if e.get("event") == "node_router"]
            rec("E infrastructure failure → one Python fallback", a == b and [e["target"] for e in evs] == ["python-fallback"]
                and hits() - h1 == 1 and vend_finds() - f1 == 1, f"{mode}: {evs} node_hits={hits() - h1} py_route_runs={vend_finds() - f1}")
            (state / "mode").write_text("ok")
            b = req(P_FD, "GET", "/api/vendors", OWN)
            rec("E success after failure resets the breaker", b[2] == b'{"fake":"node"}' and targets(log.new()) == ["node"], mode)
        for mode, want in (("g404", b'{"detail":"Vendor not found"}'), ("g500", b"Internal Server Error")):
            (state / "mode").write_text(mode)
            h1, f1 = hits(), vend_finds()
            b = req(P_FD, "GET", "/api/vendors", OWN)
            time.sleep(0.3)
            rec("E genuine Node 4xx/500 passed through once, never re-run in Python",
                b[2] == want and targets(log.new()) == ["node"] and hits() - h1 == 1 and vend_finds() - f1 == 0,
                f"{mode}: {b[0]} node_hits={hits() - h1} py_route_runs={vend_finds() - f1}")
        (state / "mode").write_text("s503")
        seq = []
        h1 = hits()
        for _i in range(12):
            a, b = req(P_REF, "GET", "/api/vendors", OWN), req(P_FD, "GET", "/api/vendors", OWN)
            seq += [(e["target"], e["reason"]) for e in log.new() if e.get("event") == "node_router"]
            rec("E circuit phase: responses identical to Python", a == b)
        rec("F circuit breaker opens after 5 consecutive failures", seq[:5] == [("python-fallback", "node-503")] * 5
            and seq[5:] == [("python", "circuit-open")] * 7 and hits() - h1 == 5, str(seq))
        (state / "mode").write_text("ok")
        time.sleep(31)
        b = req(P_FD, "GET", "/api/vendors", OWN)
        rec("F circuit closes after the 30 s cool-down", b[2] == b'{"fake":"node"}' and targets(log.new()) == ["node"])
        log, _ = restart_fd("py-fd-ctimeout", {**FAIL, "NODE_UPSTREAM_URL": "http://10.255.255.1:8002"})
        t1 = time.time()
        a, b = req(P_REF, "GET", "/api/vendors", OWN), req(P_FD, "GET", "/api/vendors", OWN)
        evs = [e for e in log.new() if e.get("event") == "node_router"]
        rec("E connect timeout / unroutable upstream → Python fallback", a == b and [e["target"] for e in evs] == ["python-fallback"],
            f"{evs} in {time.time() - t1:.2f}s")
        rec("E fallback never changed business data", dbhash(business) == h0b)
        kill_tree(procs.pop("fake"))

        # ═══ F · real Node crash / restart ═══════════════════════════════
        log, _ = restart_fd("py-fd-crash", ON)
        req(P_FD, "GET", "/api/vendors", OWN)
        rec("F Node serving before crash", targets(log.new()) == ["node"])
        kill_tree(procs.pop("node")); wait_port(NODE, up=False)
        seq = []
        for _n, t in ROUTES[:10]:
            a, b = req(P_REF, "GET", t, OWN), req(P_FD, "GET", t, OWN)
            seq += [e["target"] for e in log.new() if e.get("event") == "node_router"]
            rec("F Node down: every response still correct (Python)", a == b, t)
        procs["node"], nlog2 = start_node(node_env_file("restart"), "node-restart")
        up = wait_port(NODE, secs=60)
        time.sleep(31)
        req(P_FD, "GET", "/api/vendors", OWN)
        rec("F Node restarted (harness acting as supervisor) → routing resumes", up and targets(log.new()) == ["node"])

        # ═══ G · CORS alignment ══════════════════════════════════════════
        cors = "https://app.example,https://ops.example"
        kill_tree(procs.pop("ref")); wait_port(P_REF, up=False)
        procs["ref"], _ = start_py(P_REF, "py-ref-cors", {"CORS_ORIGINS": cors})
        for node_cors, aligned in ((cors, True), ("", False)):
            kill_tree(procs.pop("node")); wait_port(NODE, up=False)
            procs["node"], _ = start_node(node_env_file(f"cors-{aligned}", NODE_CORS_ORIGINS=node_cors), f"node-cors-{aligned}")
            wait_port(NODE)
            log, _ = restart_fd(f"py-fd-cors-{aligned}", {**ON, "CORS_ORIGINS": cors})
            same = []
            for origin, extra in (("https://app.example", []), ("https://evil.example", []), ("https://ops.example", [("Cookie", "a=1")])):
                a = req(P_REF, "GET", "/api/vendors", OWN + [("Origin", origin)] + extra)
                b = req(P_FD, "GET", "/api/vendors", OWN + [("Origin", origin)] + extra)
                same.append(a == b and targets(log.new()) == ["node"])
            if aligned:
                rec("G CORS aligned (NODE_CORS_ORIGINS == CORS_ORIGINS): routed CORS identical", all(same), str(same))
            else:
                rec("G CORS misaligned is detectable (responses differ) — checklist item is real", not all(same), str(same))
        kill_tree(procs.pop("node")); wait_port(NODE, up=False)
        procs["node"], nlog = start_node(node_env_file("final"), "node-final")
        wait_port(NODE)
        kill_tree(procs.pop("ref")); wait_port(P_REF, up=False)
        procs["ref"], _ = start_py(P_REF, "py-ref-final", {})
        log, _ = restart_fd("py-fd-final", ON)

        # ═══ H · forwarded headers ═══════════════════════════════════════
        for spoof in ([("X-Forwarded-Proto", "https")], [("X-Forwarded-For", "6.6.6.6")], [("X-Request-Id", "spoofed-id-12345")],
                      [("X-Forwarded-Host", "evil.example")]):
            a, b = req(P_REF, "GET", "/api/vendors", OWN + spoof), req(P_FD, "GET", "/api/vendors", OWN + spoof)
            evs = [e for e in log.new() if e.get("event") == "node_router"]
            rec("H spoofed forwarded headers change nothing", a == b and [e["target"] for e in evs] == ["node"]
                and all(e["request_id"] != "spoofed-id-12345" for e in evs), str(spoof))

        # ═══ I · correlation + log hygiene ═══════════════════════════════
        ids = []
        for t in ["/api/vendors?" + SECRET_QUERY + "=1", "/api/vendors/v-a?x=" + SECRET_QUERY]:
            req(P_FD, "GET", t, [("Authorization", f"Bearer {SECRET_TOKEN}"), ("Cookie", f"session_token={SECRET_COOKIE}")])
            ids += [e["request_id"] for e in log.new() if e.get("target") == "node"]
        time.sleep(1.5)
        node_text = nlog.read_text(encoding="utf-8", errors="replace")
        rec("I request id correlates Python router ↔ Node logs", len(ids) == 2 and all(i and i in node_text for i in ids), str(ids))
        # Observability still complete after the F2/F3 redaction.
        fd_events = [json.loads(ln[ln.find('{"event": "node_router"'):]) for ln in
                     (TMP / "py-fd-final.log").read_text(encoding="utf-8", errors="replace").splitlines()
                     if '{"event": "node_router"' in ln]
        routed = [e for e in fd_events if e.get("request_id") in ids]
        rec("I router log keeps request_id/method/route/target/status/latency/reason",
            len(routed) == 2 and all({"request_id", "method", "route", "target", "status", "latency_ms", "reason"} <= set(e)
                                     and e["route"] and e["target"] == "node" and isinstance(e["status"], int) for e in routed), str(routed))
        node_lines = [json.loads(ln) for ln in node_text.splitlines() if ln.startswith("{") and '"request_completed"' in ln]
        mine = [n for n in node_lines if n.get("request_id") in ids]
        rec("I Node request log keeps request_id/method/route/status/latency (no query)",
            len(mine) == 2 and all({"request_id", "method", "route", "status", "latency_ms"} <= set(n) and "?" not in str(n["route"])
                                   for n in mine), str(mine)[:300])
        rec("I Node emits no per-request URL log (Fastify request logging off)",
            '"msg":"incoming request"' not in node_text and '"url":' not in node_text, "")
        leaks: dict[str, list[str]] = {}
        for p in dict.fromkeys(logs_to_scan):
            if p.exists():
                txt = p.read_text(encoding="utf-8", errors="replace")
                for s in SECRETS:
                    if s in txt:
                        leaks.setdefault(s, []).append(p.name)
                        line = next(ln for ln in txt.splitlines() if s in ln)
                        masked = line.replace(s, "<MARKER>")
                        findings.append(f"LOG-EVIDENCE {p.name}: {masked[:260]}")
        secret_leaks = {k: v for k, v in leaks.items() if k != SECRET_QUERY}
        rec("I no tokens / cookies / passwords in any log", not secret_leaks, str(secret_leaks))
        py_router_q = [p for p in leaks.get(SECRET_QUERY, []) if p.startswith("py-")]
        if py_router_q:
            findings.append("F3 BLOCKER (needs authorisation): with routing ON, httpx (used by backend/node_router.py) logs "
                            "'HTTP Request: GET <full upstream URL incl. query>' at INFO because server.py configures root "
                            f"logging at INFO (seen in {sorted(set(py_router_q))}). Remedy (infra, node_router.py): set the "
                            "`httpx` / `httpcore` loggers to WARNING.")
        rec("I Python front door never logs query strings", not py_router_q, str(py_router_q))
        node_q = [p for p in leaks.get(SECRET_QUERY, []) if p.startswith("node-")]
        if node_q:
            findings.append("F2 BLOCKER (needs authorisation): Node's Fastify request logging (`disableRequestLogging: false`, "
                            "default `req.url` serializer) writes the full URL INCLUDING the query string at info level "
                            f"(seen in {sorted(set(node_q))}). Query strings may carry business identifiers. Remedy (infra, "
                            "app.ts/logger.ts): drop/strip the query in the request serializer, or disable Fastify's per-request log.")
        rec("I Node logs contain no query strings", not node_q, str(sorted(set(node_q))))

        # ═══ J · data safety ═════════════════════════════════════════════
        rdb.command({"profile": 0})
        all_node = node_ops(t_start)
        writes = [o for o in all_node if is_write(o) and not o.get("errCode") and o.get("ok", 1) == 1]
        rec("J Node performed zero successful writes", not writes, str([o.get("command") for o in writes])[:300])
        changed = [k for k in business if dbhash([k]).get(k) != h_begin.get(k)]
        writers: dict[str, set[str]] = {}
        for o in rdb["system.profile"].find({}):
            if is_write(o) and not o.get("errCode"):
                coll = (o.get("ns") or ".").split(".", 1)[1]
                writers.setdefault(coll, set()).add(o.get("appName") or "?")
        unattributed = [k for k in changed if not writers.get(k)]
        non_python = {k: sorted(v) for k, v in writers.items() if k in business and any(not a.startswith("trukvia-gate9g-py") for a in v)}
        rec("J every business-collection change is a Python write (Python = only business writer)",
            not unattributed and not non_python, f"changed={changed} unattributed={unattributed} non_python={non_python}")
        print(f"BUSINESS changed={changed} writers={ {k: sorted(v) for k, v in writers.items() if k in changed} }")
        print(f"NODE_OPS total={len(all_node)} writes={len(writes)} "
              f"denied_write_attempts={len([o for o in all_node if is_write(o) and (o.get('errCode') or o.get('ok', 1) != 1)])}")
    finally:
        for k in ("fd", "ref", "node", "fake"):
            kill_tree(procs.get(k))
        if KILL.exists():
            KILL.unlink()
        stop_mongod()
        time.sleep(1)
        shutil.rmtree(TMP, ignore_errors=True)

    total = sum(len(v) for v in results.values()); passed = sum(sum(v) for v in results.values())
    print("=" * 96 + "\nPHASE 4 · GATE 9g · PRE-PRODUCTION REHEARSAL\n" + "=" * 96)
    for g, v in results.items():
        print(f"  [{'PASS' if all(v) else 'FAIL'}] {g}: {sum(v)}/{len(v)}")
    for f in fails[:40]:
        print("   ✗", f)
    for f in findings:
        print("  FINDING:", f)
    print("-" * 96 + f"\n  checks: {total}  passed: {passed}  failed: {total - passed}\n" + "=" * 96)
    shutil.rmtree(TMP, ignore_errors=True)
    print(f"[gate9g] throwaway mongod + temp dir removed: {not TMP.exists()}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
