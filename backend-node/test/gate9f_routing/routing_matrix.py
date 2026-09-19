"""Phase 4 · Gate 9f · deterministic routing matrix for backend/node_router.py.

Runs the router's decision function against the REAL Python app route table
(imports backend/server.py; no server, no DB traffic). The expected target is
computed independently: a request is Node-eligible iff it is GET/HEAD and the
FIRST Python route that FULL-matches it for GET has a template on the frozen
allowlist and not on the deferred list. Everything else must be Python.
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "backend"))
os.chdir(REPO / "backend")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "trukvia_gate9f_import_unused")
import server  # noqa: E402
import node_router  # noqa: E402
from starlette.routing import Match  # noqa: E402

APP = server.app
ALLOW = node_router._read_list(REPO / "backend-node" / ".migration-allowlist")
DEFERRED = node_router._read_list(REPO / "backend-node" / ".migration-deferred")
ALLOW_N = {node_router._norm_node(p) for p in ALLOW}
DEFERRED_N = {node_router._norm_node(p) for p in DEFERRED}
METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
ON = {"NODE_ROUTING_MODE": "on", "NODE_ROUTING_ROUTES": "all", "NODE_ROUTING_PERCENT": "100",
      "NODE_ROUTING_KILL_FILE": str(Path(tempfile.gettempdir()) / "gate9f-no-such-kill-file")}


def concrete(path: str, val: str = "x-1") -> str:
    return re.sub(r"\{[^}:]+:path\}", "a/b", re.sub(r"\{[^}:]+\}", val, path))


def expected(method: str, target: str) -> str:
    if method not in ("GET", "HEAD"):
        return "python"
    path = unquote(target.split("?", 1)[0])
    scope = {"type": "http", "method": "GET", "path": path, "root_path": "", "headers": []}
    for r in APP.router.routes:
        if r.matches(scope)[0] == Match.FULL:
            n = node_router._norm_py(r.path)
            return "node" if n in ALLOW_N and n not in DEFERRED_N else "python"
    return "python"


def run(cases, env):
    return node_router.routing_matrix(APP, cases, env)


def main() -> int:
    results: dict[str, list[bool]] = {}
    fails: list[str] = []

    def check(group: str, cases, env, want=None):
        got = run(cases, env)
        for (m, t), (_, _, target, _tpl) in zip(cases, got):
            exp = want if want is not None else expected(m, t)
            ok = target == exp
            results.setdefault(group, []).append(ok)
            if not ok:
                fails.append(f"{group}: {m} {t} → {target} (expected {exp})")

    py_routes = [r for r in APP.router.routes if hasattr(r, "path")]
    # 1. every Python route × every method (writers, GET-with-write, unmigrated reads, allowlisted)
    all_cases = [(m, concrete(r.path)) for r in py_routes for m in METHODS]
    check("1 all-python-routes×methods", all_cases, ON)

    # 2. frozen allowlist patterns: GET / HEAD / query / trailing slash / double slash / encoded slash
    allow_cases = []
    for p in ALLOW:
        c = re.sub(r":[^/]+", "x-1", p)
        allow_cases += [("GET", c), ("HEAD", c), ("GET", c + "?a=1&b=%20&a=2"), ("HEAD", c + "?x"),
                        ("GET", c.rstrip("/") + "/" if not c.endswith("/") else c.rstrip("/")),
                        ("GET", c.replace("/api/", "/api//", 1)), ("POST", c), ("DELETE", c)]
        if ":" in p:
            allow_cases.append(("GET", re.sub(r":[^/]+", "a%2Fb", p)))
    check("2 allowlist variants", allow_cases, ON)
    node_hits = [t for (m, t), (_, _, target, _) in zip(allow_cases, run(allow_cases, ON)) if target == "node"]

    # 3. precedence: a param value equal to a static sibling segment must follow Python's order
    prec = []
    for p in ALLOW:
        if ":" not in p:
            continue
        segs = p.split("/")
        for r in py_routes:
            rs = r.path.split("/")
            if len(rs) != len(segs):
                continue
            if all(a == b or a.startswith(":") for a, b in zip(segs, rs)) and any(
                    a.startswith(":") and not b.startswith("{") for a, b in zip(segs, rs)):
                prec += [("GET", concrete(r.path)), ("HEAD", concrete(r.path))]
    check("3 precedence shadows", prec, ON)

    # 4. deferred routes (GET/HEAD) — never Node
    deferred_cases = [(m, re.sub(r":[^/]+", "x-1", p)) for p in DEFERRED for m in ("GET", "HEAD", "POST")]
    check("4 deferred", deferred_cases, ON, want=None)
    for (m, t), (_, _, target, _) in zip(deferred_cases, run(deferred_cases, ON)):
        if target == "node":
            fails.append(f"4 deferred reached Node: {m} {t}")

    # 5. unknown /api and non-/api
    other = [("GET", t) for t in ["/api/definitely-not-a-route", "/api/vendors/x/y/z", "/api", "/", "/docs", "/openapi.json",
                                  "/health/live", "/health/ready", "/static/js/main.js", "/api/v2/vendors", "/API/VENDORS",
                                  "/apivendors", "/api/vendorsX", "/api/vendors-x"]]
    check("5 unknown & non-/api", other + [("HEAD", t) for _, t in other], ON, want="python")

    everything = all_cases + allow_cases + prec + deferred_cases + other
    # 6. kill switch ON → Python for everything
    kill = Path(tempfile.gettempdir()) / "gate9f-kill-file"
    kill.write_text("kill")
    try:
        check("6 kill switch", everything, {**ON, "NODE_ROUTING_KILL_FILE": str(kill)}, want="python")
    finally:
        kill.unlink()
    # 7. default / off / partial configurations → Python for everything
    check("7a default env (nothing set)", everything, {}, want="python")
    check("7b mode off", everything, {**ON, "NODE_ROUTING_MODE": "off"}, want="python")
    check("7c percent 0", everything, {**ON, "NODE_ROUTING_PERCENT": "0"}, want="python")
    check("7d no routes listed", everything, {**ON, "NODE_ROUTING_ROUTES": ""}, want="python")
    check("7e deferred route listed → router disabled", everything, {**ON, "NODE_ROUTING_ROUTES": "/api/trips,/api/vendors"}, want="python")
    check("7f unknown route listed → router disabled", everything, {**ON, "NODE_ROUTING_ROUTES": "/api/vendors,/api/nope"}, want="python")
    check("7g allowlist unreadable → router disabled", everything, {**ON, "NODE_ALLOWLIST_PATH": str(REPO / "no-such-allowlist")}, want="python")
    check("7h garbage percent → 0", everything, {**ON, "NODE_ROUTING_PERCENT": "abc"}, want="python")
    # 8. per-route subset: only /api/vendors (list) may reach Node
    sub = {**ON, "NODE_ROUTING_ROUTES": "/api/vendors"}
    for (m, t), (_, _, target, tpl) in zip(everything, run(everything, sub)):
        exp = "node" if (m in ("GET", "HEAD") and expected(m, t) == "node" and tpl == "/api/vendors") else "python"
        ok = target == exp and (target == "python" or tpl == "/api/vendors")
        results.setdefault("8 per-route subset", []).append(ok)
        if not ok:
            fails.append(f"8 subset: {m} {t} → {target} {tpl}")
    # 9. percent rollout is deterministic and proportional (stable per token+route)
    r = node_router.NodeRouter(app=None, fastapi_app=APP, config=node_router.RouterConfig({**ON, "NODE_ROUTING_PERCENT": "30"}))
    scopes = [{"type": "http", "method": "GET", "path": "/api/vendors", "raw_path": b"/api/vendors", "query_string": b"",
               "root_path": "", "scheme": "http", "headers": [(b"authorization", f"Bearer tok-{i}".encode())]} for i in range(2000)]
    first = [r.decide(s)[0] for s in scopes]
    second = [r.decide(s)[0] for s in scopes]
    share = first.count("node") / len(first)
    results["9 percent rollout"] = [first == second, 0.25 <= share <= 0.35]
    if not all(results["9 percent rollout"]):
        fails.append(f"9 percent: stable={first == second} share={share:.3f}")

    total = sum(len(v) for v in results.values())
    passed = sum(sum(v) for v in results.values())
    print("=" * 90 + "\nPHASE 4 · GATE 9f · ROUTING MATRIX (real Python route table, frozen lists)\n" + "=" * 90)
    print(f"  Python routes: {len(py_routes)}   allowlist: {len(ALLOW)}   deferred: {len(DEFERRED)}")
    print(f"  allowlist variants routed to Node: {len(node_hits)} (GET/HEAD/query forms of the {len(ALLOW)} patterns)")
    for g, v in results.items():
        print(f"  {g}: {sum(v)}/{len(v)}")
    for f in fails[:30]:
        print("  [FAIL]", f)
    print("-" * 90 + f"\n  cases: {total}  passed: {passed}  failed: {total - passed}\n" + "=" * 90)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
