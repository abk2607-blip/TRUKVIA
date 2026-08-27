"""Iter127c-invoice-shipto v3 · Guarded Ship-To resolver (Feb 2026, user-approved).

Single source of truth for invoice Ship-To rendering, used by BOTH:
  * backend/pdf/invoice.py       — Invoice PDF header
  * backend/routers/invoices.py  — GET /api/invoices/{iid}/ship-to  (Invoice Preview)

Guardrails (per user directive):
  * READ-ONLY inference. Never writes an inferred ship_site_id back to Trip.
  * Never invents fields. If the resolved site has empty state / pincode /
    gstin, they stay empty (NO silent inheritance from Customer.state).
  * Preview and PDF MUST call this same function so their outputs match.

Guarded inference rules — for a trip with an EMPTY `ship_site_id`, we infer
the customer's ship_site ONLY when destination evidence unambiguously
identifies EXACTLY ONE ship_site on the customer.  Ambiguous (>1 match) or
zero-match ⇒ no inference ⇒ falls through to display-tuple identity ⇒
typically renders as Mixed.

Evidence rules (ANY of the following counts, but all evaluated together;
match set must be size 1):
  R1  normalized `to_location` == normalized `site.site_name`
  R2  6-digit PIN in `to_location` == `site.pincode` or PIN embedded in
      `site.address`
  R3  normalized `to_location` appears as a WHOLE TOKEN (>= 4 chars) inside
      normalized `site.address`

Note: a trip that already has an explicit `ship_site_id` is authoritative
and never touched by inference — that FK is treated as identity as-is.
"""
from __future__ import annotations

import re
from typing import Any, Optional

_TOKEN_MIN = 4
_PIN_RE = re.compile(r"\b(\d{6})\b")
_TOKEN_SPLIT_RE = re.compile(r"[^0-9a-z\u0900-\u097f]+")

# Iter127c-invoice-shipto v3.1 (Feb 2026 · user-approved GSTIN cleanup).
# Strips a leading `GSTIN` / `GST` / `GSTN` prefix (case-insensitive), trims
# whitespace, and collapses internal whitespace. Used by BOTH:
#   * Ship-Site POST/PUT endpoints  → cleans the value ON SAVE
#   * Resolver render output        → cleans dirty historic values ON RENDER
# Never mutates the DB during render — see `_display_from_site`.
_GSTIN_PREFIX_RE = re.compile(r"^\s*(?:gstin|gstn|gst)\b[\s:.-]*", re.IGNORECASE)


def normalize_gstin(value) -> str:
    """Return a cleaned GSTIN string.  Blank input ⇒ empty string."""
    if not value:
        return ""
    s = str(value).replace("\t", " ").replace("\r", " ").replace("\n", " ")
    s = s.strip()
    if not s:
        return ""
    s = _GSTIN_PREFIX_RE.sub("", s)          # drop leading GSTIN / GST / GSTN
    s = re.sub(r"\s+", "", s).strip()        # collapse whitespace (GSTIN has none)
    return s.upper()


# Iter127c-invoice-shipto v3.2 (Feb 2026 · user-approved) — Ship-To GSTIN
# auto-derives the Indian State + State Code from the first two digits of
# a *valid* GSTIN.  Never guesses on blank / invalid input, never silently
# overwrites an existing manually-entered state (conflict is surfaced by
# the FE; the backend simply refuses to overwrite).
_GSTIN_FULL_RE = re.compile(
    r"^([0-9]{2})([A-Z]{5}[0-9]{4}[A-Z])([0-9A-Z])(Z)([0-9A-Z])$"
)


def _gstin_state_code(gstin: str) -> str:
    """First 2 digits of a well-formed GSTIN, or '' if not well-formed."""
    g = normalize_gstin(gstin)
    m = _GSTIN_FULL_RE.match(g)
    return m.group(1) if m else ""


def derive_state_from_gstin(gstin: str) -> dict:
    """Given a candidate GSTIN string, return `{state_code, state}` if the
    GSTIN is well-formed AND its state code maps to a known Indian state.
    Otherwise returns `{"state_code": "", "state": ""}`.

    NEVER raises. NEVER silently overwrites a caller's data — the caller
    decides whether to accept the derivation.
    """
    # Local import to avoid a hard cycle: services imports ship_to_resolver
    # is not (yet) established. This function is used from routers/customers
    # which already imports services, so it's safe here.
    try:
        from services import STATE_CODE_TO_NAME
    except Exception:
        STATE_CODE_TO_NAME = {}
    code = _gstin_state_code(gstin)
    if not code:
        return {"state_code": "", "state": ""}
    name = STATE_CODE_TO_NAME.get(code) or ""
    if not name:
        return {"state_code": "", "state": ""}
    return {"state_code": code, "state": name}


def apply_gstin_state_derivation(payload: dict) -> dict:
    """Fill blank `state_code` / `state` on a ship-site payload from its GSTIN.

    Rules (user-locked):
      * GSTIN is authoritative — but only when well-formed.
      * NEVER overwrite a non-blank manual value that CONFLICTS with GSTIN;
        the FE warns the user and the backend keeps their entry. This
        preserves historical Ship-To records against silent mutation.
      * NEVER guesses when GSTIN is blank or invalid.

    Mutates and returns the same dict for chaining. Caller is expected to
    have already run `normalize_gstin` on payload["gstin"].
    """
    if not isinstance(payload, dict):
        return payload
    derived = derive_state_from_gstin(payload.get("gstin"))
    if not derived["state_code"]:
        return payload
    # State Code — auto-fill only when blank.
    existing_code = (payload.get("state_code") or "").strip()
    if not existing_code:
        payload["state_code"] = derived["state_code"]
    # State Name — auto-fill only when blank.
    existing_state = (payload.get("state") or "").strip()
    if not existing_state:
        payload["state"] = derived["state"]
    return payload


def _norm(s: Any) -> str:
    """Lower-cased, whitespace-collapsed, tab/newline-safe."""
    return re.sub(r"\s+", " ", (str(s) if s else "").strip().casefold())


def _extract_pin(s: Any) -> Optional[str]:
    m = _PIN_RE.search(str(s) if s else "")
    return m.group(1) if m else None


def _site_matches_trip(site: dict, trip: dict) -> bool:
    """True when destination evidence unambiguously points at this site."""
    to_raw = trip.get("to_location") or ""
    to_n = _norm(to_raw)
    if not to_n:
        return False

    # R1 · normalized name equality.
    name_n = _norm(site.get("site_name") or site.get("name") or "")
    if name_n and name_n == to_n:
        return True

    # R2 · pincode match (either dedicated field or embedded in address).
    trip_pin = _extract_pin(to_raw)
    if trip_pin:
        site_pin = _norm(site.get("pincode") or "")
        addr_pin = _extract_pin(site.get("address") or "")
        if (site_pin and site_pin == trip_pin) or (addr_pin and addr_pin == trip_pin):
            return True

    # R3 · to_location appears as a whole token inside the site address.
    addr_n = _norm(site.get("address") or "")
    if addr_n and len(to_n) >= _TOKEN_MIN:
        tokens = [t for t in _TOKEN_SPLIT_RE.split(addr_n) if t]
        if to_n in tokens:
            return True

    return False


def infer_site_for_trip(trip: dict, sites: list) -> Optional[dict]:
    """Return the single evidence-matched site, or None if 0 or >1 matches."""
    matches = [s for s in (sites or []) if _site_matches_trip(s, trip)]
    return matches[0] if len(matches) == 1 else None


def _display_from_site(site: dict) -> dict:
    return {
        "site_name": (site.get("site_name") or site.get("name") or "").strip(),
        "address": (site.get("address") or "").strip(),
        # Render-time GSTIN cleanup — dirty historic records display cleanly
        # WITHOUT mutating the stored DB value.
        "gstin": normalize_gstin(site.get("gstin")),
        "state": (site.get("state") or "").strip(),
        "state_code": (site.get("state_code") or "").strip(),
        "pincode": (site.get("pincode") or "").strip(),
        "phone": (site.get("phone") or "").strip(),
        "contact_person": (site.get("contact_person") or "").strip(),
        "linked": True,
    }


def _display_fallback(trip: dict) -> dict:
    return {
        "site_name": (trip.get("to_location") or "").strip(),
        "address": "",
        "gstin": "",
        "state": "",
        "state_code": "",
        "pincode": "",
        "phone": "",
        "contact_person": "",
        "linked": False,
    }


def _identity(trip: dict, resolved: dict, inferred_sid: Optional[str]) -> tuple:
    """Identity tuple — trips with equal tuples share the same Ship-To."""
    explicit_sid = (trip.get("ship_site_id") or "").strip()
    sid = explicit_sid or (inferred_sid or "")
    if sid:
        return ("site_id", sid)
    return (
        "fb",
        _norm(resolved.get("site_name") or ""),
        _norm(resolved.get("address") or ""),
        (resolved.get("gstin") or "").strip().upper(),
    )


def resolve_invoice_ship_to(customer: dict, trips: list) -> dict:
    """Resolve the Ship-To header for an invoice's trip list.

    Returns:
      {
        "mixed": bool,
        "common": dict | None,        # resolved display when not mixed
        "per_trip": [
          {
            "resolved":  dict,        # display record for this trip's Ship-To
            "site_id":   str | None,  # explicit FK, or inferred FK, or None
            "inferred":  bool,        # True when site_id was guarded-inferred
            "identity":  tuple,       # opaque; same value ⇒ same Ship-To
          },
          ...
        ],
      }
    """
    sites = (customer.get("ship_sites") or []) if customer else []
    sites_by_id = {s.get("id"): s for s in sites if s.get("id")}
    per_trip = []
    for t in trips or []:
        explicit_sid = (t.get("ship_site_id") or "").strip()
        site = sites_by_id.get(explicit_sid) if explicit_sid else None
        inferred_sid: Optional[str] = None
        if not site and not explicit_sid:
            candidate = infer_site_for_trip(t, sites)
            if candidate:
                site = candidate
                inferred_sid = (candidate.get("id") or "") or None
        resolved = _display_from_site(site) if site else _display_fallback(t)
        per_trip.append({
            "resolved": resolved,
            "site_id": explicit_sid or inferred_sid or None,
            "inferred": bool(inferred_sid and not explicit_sid),
            "identity": _identity(t, resolved, inferred_sid),
        })
    identities = {p["identity"] for p in per_trip}
    mixed = len(identities) > 1
    common = per_trip[0]["resolved"] if per_trip and not mixed else None
    return {"mixed": mixed, "common": common, "per_trip": per_trip}
