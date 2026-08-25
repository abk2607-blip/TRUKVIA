"""Iter127a · Duplicate-master helpers.

Pure normalisation + soft/hard match logic used by the customers / vehicles
/ suppliers create endpoints. NO Mongo, NO HTTP, NO side-effects. Trivially
unit-testable and safe to import from anywhere.

Rules locked with user (2026-Feb):
  Customer  · GSTIN exact → hard 409
             · PAN exact (when GSTIN empty) → hard 409
             · Name / phone matches → SOFT (attached to response, not blocking)
  Vehicle   · Normalised vehicle_number exact → hard 409
  Supplier  · GSTIN exact → hard 409
             · PAN exact (when GSTIN empty) → hard 409
             · Normalised name → hard 409
             · Mobile → SOFT (attached to response, not blocking)

Matching is ALWAYS scoped per (user_id, company_id) — cross-company
namespaces never collide. Case-, space-, hyphen- and dot-insensitive.
"""
from __future__ import annotations

import re
from typing import Iterable

# ---- Normalisers ---- #

_NAME_SUFFIX_RX = re.compile(
    r"\b(pvt|private|ltd|limited|llp|inc|company|co|and|&)\b", re.IGNORECASE,
)
_NAME_PUNCT_RX = re.compile(r"[\.,\-/&()]+")
_WS_RX = re.compile(r"\s+")


def norm_gstin(v) -> str:
    """GSTIN is fixed-length 15 chars, uppercase. Strip whitespace, drop
    anything that isn't length 15 (treats invalid GSTINs as absent)."""
    s = (str(v) if v is not None else "").upper().strip()
    s = _WS_RX.sub("", s)
    return s if len(s) == 15 else ""


def norm_pan(v) -> str:
    s = (str(v) if v is not None else "").upper().strip()
    s = _WS_RX.sub("", s)
    return s if len(s) == 10 else ""


def norm_vehicle_number(v) -> str:
    """`AP 27 TT-6008`, `ap27tt6008`, `AP27TT.6008` all collapse to the
    same canonical form."""
    s = (str(v) if v is not None else "").upper()
    return re.sub(r"[\s\-\.]", "", s)


def norm_name(v) -> str:
    s = (str(v) if v is not None else "").lower()
    s = _NAME_PUNCT_RX.sub(" ", s)
    s = _NAME_SUFFIX_RX.sub(" ", s)
    return _WS_RX.sub(" ", s).strip()


def norm_phone(v) -> str:
    """Last-10-digits — makes `+91-98xxxxxxxx`, `098xxxxxxxx`, `98xxxxxxxx`
    equivalent. Anything shorter than 10 digits is treated as absent."""
    digits = re.sub(r"\D+", "", str(v) if v is not None else "")
    return digits[-10:] if len(digits) >= 10 else ""


# ---- Match responders ---- #

def existing_summary(row: dict, gstin_key: str = "gstin") -> dict:
    """Compact JSON payload the frontend uses to power the
    'Open existing / Cancel' modal. Never leaks internals like _id or
    user_id."""
    return {
        "id": row.get("id"),
        "name": row.get("name") or row.get("vehicle_number") or "",
        "gstin": row.get(gstin_key) or "",
        "phone": row.get("phone") or row.get("mobile") or "",
        "vehicle_number": row.get("vehicle_number") or "",
    }


def hard_conflict_response(matched_field: str, entity_label: str, row: dict, gstin_key: str = "gstin") -> dict:
    """Payload for FastAPI HTTPException(detail=…). Rendered to the client
    as a JSON body plus HTTP 409."""
    return {
        "detail": f"{entity_label} already exists.",
        "code": "duplicate_master",
        "matched_field": matched_field,
        "existing": existing_summary(row, gstin_key=gstin_key),
    }


def soft_match_entry(matched_field: str, row: dict, gstin_key: str = "gstin") -> dict:
    return {
        "matched_field": matched_field,
        "existing": existing_summary(row, gstin_key=gstin_key),
    }


# ---- Override authorisation ---- #

ALLOWED_OVERRIDE_ROLES = {"owner", "admin"}
MIN_OVERRIDE_REASON_LEN = 6


def is_override_authorised(user: dict) -> bool:
    role = (user.get("effective_role") or "owner").lower()
    return role in ALLOWED_OVERRIDE_ROLES


def read_override_request(request, body_payload: dict) -> tuple[bool, str]:
    """Returns (override_requested, reason). A caller must set the header
    `X-Duplicate-Override: allow` AND provide `X-Duplicate-Override-Reason`
    (≥ 6 chars) — either alone is insufficient so accidental clicks can't
    slip through. `body_payload` is kept in the signature for future
    per-endpoint expansion but is currently unused (Pydantic strips
    unknown fields, so the reason must come from a header)."""
    if request is None:
        return False, ""
    header = (request.headers.get("X-Duplicate-Override") or "").strip().lower()
    reason = (request.headers.get("X-Duplicate-Override-Reason") or "").strip()
    if header == "allow" and len(reason) >= MIN_OVERRIDE_REASON_LEN:
        return True, reason
    return False, ""
