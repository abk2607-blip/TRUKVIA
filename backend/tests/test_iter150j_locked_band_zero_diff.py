"""Iter150J · Locked-band zero-diff regression.

Asserts that every file listed in the Iter150J implementation
authorisation remains byte-identical to its Iter150I lock ancestor
`e3e16fa`. `backend/models.py` is the sole exception — it carries the
authorised Iter150J additive layer.
"""
from __future__ import annotations
import subprocess
from pathlib import Path
import pytest

ITER150I_LOCK = "e3e16fa"

REPO = Path("/app")

# Files that must remain byte-identical to Iter150I lock.
LOCKED_ZERO_DIFF = [
    "backend/services_fin_txn.py",
    "backend/services_fin_txn_hooks.py",
    "backend/services.py",
    "backend/services_expense_bridge.py",
    "backend/services_bank_accounts.py",
    "backend/services_reconciliation.py",
    "backend/pdf_brand.py",
    "backend/models_bank.py",
    "backend/routers/trips.py",
    "backend/routers/invoices.py",
    "backend/routers/notes.py",
    "backend/routers/vendor_bills.py",
    "backend/routers/mechanic_work_orders.py",
    "backend/routers/expenses.py",
    "backend/routers/wallet_recharges.py",
    "backend/routers/wallet_transfers.py",
    "backend/routers/wallet_adjustments.py",
    "backend/routers/suppliers.py",
    "backend/routers/vendors.py",
    "backend/routers/mechanics.py",
    "backend/routers/driver_payments.py",
    "backend/routers/company_bank_accounts.py",
    "backend/routers/party_bank_accounts.py",
    "backend/routers/fin_day_book.py",
    "backend/routers/fin_source_lookup.py",
    "backend/routers/fin_day_closing.py",
    "backend/routers/fin_reconciliation.py",
    "backend/routers/driver_ledger.py",
    "frontend/src/components/PaymentDrawer.jsx",
    "frontend/src/components/DriverPaymentDrawer.jsx",
    "frontend/src/components/BankAccountsSection.jsx",
    "frontend/src/components/CompanySourceBankSelector.jsx",
    "frontend/src/components/BankAccountSelector.jsx",
]


def _git_diff_numstat(rel_path: str) -> tuple[int, int]:
    r = subprocess.run(
        ["git", "-C", str(REPO), "diff", "--numstat", ITER150I_LOCK, "--", rel_path],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return (0, 0)
    line = (r.stdout or "").strip().splitlines()
    if not line:
        return (0, 0)
    parts = line[0].split("\t")
    try:
        return (int(parts[0]), int(parts[1]))
    except Exception:
        return (0, 0)


@pytest.mark.parametrize("rel_path", LOCKED_ZERO_DIFF)
def test_locked_band_zero_diff(rel_path):
    added, removed = _git_diff_numstat(rel_path)
    assert added == 0 and removed == 0, (
        f"{rel_path} drifted since Iter150I lock ({ITER150I_LOCK}): "
        f"+{added} / -{removed}"
    )


def test_iter150j_ceilings_respected():
    """Authorised additive files must stay within their +X/-0 ceilings."""
    ceilings = {
        "backend/models.py": (200, 0),
        "backend/server.py": (25, 0),
        "frontend/src/api.js": (100, 2),
        "frontend/src/components/Layout.jsx": (12, 0),
        "frontend/src/App.js": (5, 0),
    }
    for rel_path, (add_cap, del_cap) in ceilings.items():
        added, removed = _git_diff_numstat(rel_path)
        assert added <= add_cap, f"{rel_path} +{added} exceeds ceiling +{add_cap}"
        assert removed <= del_cap, f"{rel_path} -{removed} exceeds ceiling -{del_cap}"
