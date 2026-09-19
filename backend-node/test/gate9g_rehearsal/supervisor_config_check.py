"""Phase 4 · Gate 9g · parse deploy/supervisor/backend-node.conf with supervisor's OWN parser.

Validates the program section exactly as supervisor 4.2.5 reads it (process
options, restart policy, stop signal, log rotation settings). This does NOT run
supervisord: supervisord is Unix-only and this rehearsal host is Windows without
WSL/Docker, so the Unix-only `pwd`/`grp`/`resource`/`fcntl` modules are stubbed purely so the
parser can import. Runtime behaviour (auto-start/restart, retries, TERM, rotation)
remains a platform verification item.

Usage: <python-with-supervisor==4.2.5> supervisor_config_check.py
"""
import sys
import types
from pathlib import Path

for name in ("pwd", "grp", "resource", "fcntl"):
    stub = types.ModuleType(name)
    stub.getpwnam = stub.getpwuid = stub.getgrnam = stub.getgrgid = lambda *_a: (_ for _ in ()).throw(KeyError("stub"))
    sys.modules.setdefault(name, stub)

import supervisor  # noqa: E402
from supervisor.options import ServerOptions, UnhosedConfigParser  # noqa: E402
from supervisor.datatypes import signal_number  # noqa: E402

CONF = Path(__file__).resolve().parents[3] / "deploy" / "supervisor" / "backend-node.conf"

parser = UnhosedConfigParser()
import tempfile  # noqa: E402
TEXT = CONF.read_text(encoding="utf-8")
assert TEXT.count("/var/log/supervisor/") == 2
# /var/log/supervisor exists on the platform, not on this Windows host: parse with the directory
# mapped to a temp dir (supervisor checks the directory exists), then assert the ORIGINAL paths.
LOGDIR = tempfile.mkdtemp().replace("\\", "/")
parser.read_string(TEXT.replace("/var/log/supervisor/", LOGDIR + "/"))
opts = ServerOptions()
opts.here = str(CONF.parent)
cfgs = opts.processes_from_section(parser, "program:backend-node", "backend-node")
assert len(cfgs) == 1
c = cfgs[0]
expect = {
    "name": "backend-node", "command": "/bin/sh /app/deploy/supervisor/run-backend-node.sh", "directory": "/app/backend-node",
    "autostart": True, "startsecs": 5, "startretries": 10, "stopsignal": signal_number("TERM"), "stopwaitsecs": 20,
    "stopasgroup": True, "killasgroup": True, "stdout_logfile": "/var/log/supervisor/backend-node.out.log",
    "stdout_logfile_maxbytes": 50 * 1024 * 1024, "stdout_logfile_backups": 5,
    "stderr_logfile": "/var/log/supervisor/backend-node.err.log", "stderr_logfile_maxbytes": 50 * 1024 * 1024,
    "stderr_logfile_backups": 5,
}
ok = True
print(f"supervisor {supervisor.__name__} parser — program:backend-node")
for k, v in expect.items():
    got = getattr(c, k)
    if isinstance(got, str):
        got = got.replace(LOGDIR + "/", "/var/log/supervisor/")
    good = got == v
    ok &= good
    print(f"  [{'PASS' if good else 'FAIL'}] {k} = {got!r}")
# autorestart: supervisor maps `true` to RestartUnconditionally
from supervisor.datatypes import RestartUnconditionally  # noqa: E402
good = c.autorestart is RestartUnconditionally
ok &= good
print(f"  [{'PASS' if good else 'FAIL'}] autorestart = {c.autorestart!r} (unconditional)")
print(f"  parsed OK: {ok}")
sys.exit(0 if ok else 1)
