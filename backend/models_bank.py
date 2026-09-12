"""Iter150G · Bank Account master models (new · non-locked · additive).

CompanyBankAccount + PartyBankAccount. Both are pure masters — the ledger
account_code stays `BANK_DEFAULT`; per-bank codes are explicitly NOT created.

Frozen invariants (see PRD Iter150G section):
  * Historical rows are never deleted. Deactivation is terminal.
  * Account number / IFSC change → NEW row + NEW id. Old row is
    `deactivated_at` with `deactivation_reason='replaced_by:<new_id>'`.
  * At most one `is_primary=True` active row per (owner_type, owner_id).
  * `id` is the identity — account_number is NOT a business identity.
"""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field
from models import new_id, now_utc


ACCOUNT_TYPES = ("savings", "current", "cc", "od")
PARTY_TYPES = ("supplier", "vendor", "mechanic", "driver", "customer")
VERIFICATION_STATES = ("unverified", "penny_drop_pending", "verified", "failed")
BANK_SNAPSHOT_KEYS = ("bank_name", "masked_number", "ifsc", "holder_name")


class CompanyBankAccount(BaseModel):
    """Company-owned bank account master. Non-ledger — the accounting
    account_code remains `BANK_DEFAULT` for all postings."""
    id: str = Field(default_factory=lambda: new_id("cba_"))
    company_id: str = ""
    account_holder_name: str = ""
    bank_name: str = ""
    branch: str = ""
    account_number: str = ""
    ifsc: str = ""
    account_type: Literal["savings", "current", "cc", "od"] = "current"
    is_active: bool = True
    is_primary: bool = False
    verification_status: Literal[
        "unverified", "penny_drop_pending", "verified", "failed"
    ] = "unverified"
    masked_display: str = ""              # derived at write-time · XXXXXX1234
    created_by: str = ""
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())
    modified_by: str = ""
    modified_at: str = ""
    deactivated_by: str = ""
    deactivated_at: str = ""
    deactivation_reason: str = ""


class PartyBankAccount(BaseModel):
    """Party-owned bank account master. `party_type` chooses the party
    collection; `party_id` is the FK. Uniqueness on active rows:
    (user_id, party_type, party_id, account_number, ifsc)."""
    id: str = Field(default_factory=lambda: new_id("pba_"))
    party_type: Literal["supplier", "vendor", "mechanic", "driver", "customer"]
    party_id: str
    account_holder_name: str = ""
    bank_name: str = ""
    branch: str = ""
    account_number: str = ""
    ifsc: str = ""
    account_type: Literal["savings", "current", "cc", "od"] = "savings"
    is_active: bool = True
    is_primary: bool = False
    verification_status: Literal[
        "unverified", "penny_drop_pending", "verified", "failed"
    ] = "unverified"
    masked_display: str = ""
    created_by: str = ""
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())
    modified_by: str = ""
    modified_at: str = ""
    deactivated_by: str = ""
    deactivated_at: str = ""
    deactivation_reason: str = ""
