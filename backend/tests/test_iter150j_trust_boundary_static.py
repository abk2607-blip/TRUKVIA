"""Iter150J · Trust-boundary static scan.

Ensures that the six domain-writer create functions are ONLY invoked
from:
  * their router-definition site
  * backend/services_approvals.py (authorised delegation)
  * backend/tests/ (test fixtures)

Any external call site would let an approval-gated writer be reached
without passing through the approval envelope and would break the
maker-checker invariant.
"""
from __future__ import annotations
import re
from pathlib import Path

ALLOWED = {
    "backend/services_approvals.py",
    "backend/routers/trips.py",
    "backend/routers/invoices.py",
    "backend/routers/suppliers.py",
    "backend/routers/vendors.py",
    "backend/routers/mechanics.py",
    "backend/routers/driver_payments.py",
}

CALL_RX = re.compile(
    r"(?<![A-Za-z_.])"
    r"(create_trip|create_invoice|create_payment|create_vendor_payment|"
    r"create_mechanic_payment|create_driver_payment)\s*\("
)


def test_trust_boundary_static_grep():
    root = Path("/app/backend")
    offenders = []
    for py in root.rglob("*.py"):
        rel = py.relative_to("/app").as_posix()
        if "/tests/" in "/" + rel or "__pycache__" in rel:
            continue
        if rel in ALLOWED:
            continue
        try:
            txt = py.read_text()
        except Exception:
            continue
        for i, ln in enumerate(txt.splitlines(), 1):
            stripped = ln.lstrip()
            if stripped.startswith("#"):
                continue
            if CALL_RX.search(ln):
                offenders.append(f"{rel}:{i}:{ln.strip()[:100]}")
    assert not offenders, (
        "Trust-boundary violation — writer called outside authorised sites:\n"
        + "\n".join(offenders)
    )
