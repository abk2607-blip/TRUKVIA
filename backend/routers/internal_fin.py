"""Phase 6 · slice 1b(b) — INTERNAL service-to-service fin_txn projection hook.

Purpose
-------
The NestJS vendor module owns the vendor write endpoints but must keep the
`fin_txn` projection correct. Rather than maintaining a second implementation of
ledger maths in TypeScript, it calls this endpoint, which delegates to the
existing `hook_after_source_write` — the same function the Python routers call.
No ledger logic lives here.

This is NOT a public API.
-------------------------
Four independent restrictions, each of which alone denies the request:

1. **Path outside `/api`.** The platform ingress routes only `/api` to this
   service, so `/internal/...` is not reachable from the internet at all. It is
   also outside the Node-routing allowlist and the approval-gate whitelist.
2. **Loopback only.** The peer address must be 127.0.0.1 or ::1. Both services
   run in the same pod, so a remote peer is always wrong.
3. **Shared secret.** `X-Internal-Token` must equal `TRUKVIA_INTERNAL_TOKEN`,
   compared with `hmac.compare_digest` so the check is not timing-revealing.
4. **Fail closed.** With `TRUKVIA_INTERNAL_TOKEN` unset or shorter than 32
   characters the endpoint refuses every request, so a misconfigured deploy
   cannot accidentally expose an unauthenticated projection trigger.

The token is never logged, never echoed, and never included in an error body.

Scope: `vendor_bill` and `vendor_payment` only. Any other source type is
rejected — this endpoint exists for one migration slice, not as a general
admin primitive.

Failure semantics are inherited unchanged from `hook_after_source_write`: a
projection failure is recorded in `fin_hook_failures` and is reported back as
`ok: false`; it never raises and never rolls back the caller's source write.

The public `POST /api/fin/reproject` and its owner-only rule are untouched.
"""
from __future__ import annotations

import hmac
import logging
import os
from typing import Any, Dict

from fastapi import APIRouter, Body, HTTPException, Request

from services_fin_txn_hooks import hook_after_source_write

logger = logging.getLogger(__name__)

# Deliberately NOT under /api: the ingress never routes this prefix.
router = APIRouter(prefix="/internal")

ALLOWED_SOURCE_TYPES = frozenset({"vendor_bill", "vendor_payment"})
_LOOPBACK = frozenset({"127.0.0.1", "::1", "::ffff:127.0.0.1"})
_MIN_TOKEN_LEN = 32


def _configured_token() -> str:
    return (os.environ.get("TRUKVIA_INTERNAL_TOKEN") or "").strip()


def _authorise(request: Request) -> None:
    """Deny unless every restriction passes. Never mentions the token value."""
    expected = _configured_token()
    if len(expected) < _MIN_TOKEN_LEN:
        # Fail closed: an unset/short secret disables the endpoint entirely.
        raise HTTPException(status_code=404, detail="Not Found")

    peer = (request.client.host if request.client else "") or ""
    if peer not in _LOOPBACK:
        logger.warning("internal projection hook refused: non-loopback peer")
        raise HTTPException(status_code=404, detail="Not Found")

    presented = request.headers.get("x-internal-token") or ""
    if not hmac.compare_digest(presented, expected):
        logger.warning("internal projection hook refused: bad credential")
        raise HTTPException(status_code=401, detail="Invalid internal credential")


@router.post("/fin/reproject")
async def internal_reproject(
    request: Request,
    body: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Reproject ONE vendor source document. Service-to-service only.

    Body: {"user_id", "company_id", "source_type", "source_id"}
    Returns the hook's own report: {"ok", "deleted", "written", ...}.
    """
    _authorise(request)

    uid = (body.get("user_id") or "").strip()
    cid = (body.get("company_id") or "").strip()
    source_type = (body.get("source_type") or "").strip()
    source_id = (body.get("source_id") or "").strip()

    if not uid or not cid or not source_id:
        raise HTTPException(
            status_code=400,
            detail="user_id, company_id and source_id are required",
        )
    if source_type not in ALLOWED_SOURCE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported source_type. Allowed: {sorted(ALLOWED_SOURCE_TYPES)}",
        )

    # Delegates to the SAME hook the Python routers use — no ledger maths here.
    # It never raises: failures land in fin_hook_failures and come back ok=False.
    result = await hook_after_source_write(uid, cid, source_type, source_id)
    return dict(result)
