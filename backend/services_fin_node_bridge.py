"""Phase 6 · slice 2c — the reverse bridge: Python delegating to NestJS.

Per-source-type, DEFAULT OFF. With none of these set, nothing here activates
and every projection path behaves exactly as it did before, which is also the
rollback: unset the env var.

    TRUKVIA_FIN_NODE_URL           NestJS POST /internal/fin/reproject
    TRUKVIA_INTERNAL_TOKEN         the shared secret (>= 32 chars)
    TRUKVIA_FIN_NODE_SOURCE_TYPES  comma-separated types to delegate

Why this lives in its own module: `services_fin_txn_hooks` imports from
`services_fin_txn`, so the ledger module cannot import from the hook module
without a cycle. Both need the bridge, so the bridge belongs to neither.

The token travels only in the X-Internal-Token header. It is never logged,
never echoed, and never placed in an error message.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger("trukvia.fin.node_bridge")

_MIN_TOKEN_LEN = 32


def _timeout_seconds() -> float:
    return float(os.environ.get("TRUKVIA_FIN_NODE_TIMEOUT", "10"))


def delegate_types() -> frozenset:
    raw = os.environ.get("TRUKVIA_FIN_NODE_SOURCE_TYPES") or ""
    return frozenset(t.strip() for t in raw.split(",") if t.strip())


def node_bridge_ready(source_type: str) -> bool:
    """True only when the url, a long-enough secret AND this type are all set."""
    url = (os.environ.get("TRUKVIA_FIN_NODE_URL") or "").strip()
    token = (os.environ.get("TRUKVIA_INTERNAL_TOKEN") or "").strip()
    return bool(url) and len(token) >= _MIN_TOKEN_LEN and source_type in delegate_types()


async def delegate_to_node(uid: str, cid: str, source_type: str,
                           source_id: str) -> Optional[Dict[str, Any]]:
    """Return the NestJS hook report, or None when the caller should fall back.

    None means a TRANSPORT failure — unreachable, timed out, or a non-200 —
    so the local projection must run and the ledger is never left stale. A
    well-formed report is returned as-is, including `ok: false`: NestJS has
    already recorded that failure in fin_hook_failures, and projecting again
    locally would double-handle it.
    """
    import httpx

    url = (os.environ.get("TRUKVIA_FIN_NODE_URL") or "").strip()
    token = (os.environ.get("TRUKVIA_INTERNAL_TOKEN") or "").strip()
    try:
        async with httpx.AsyncClient(timeout=_timeout_seconds()) as client:
            resp = await client.post(
                url,
                json={"user_id": uid, "company_id": cid,
                      "source_type": source_type, "source_id": source_id},
                headers={"X-Internal-Token": token},
            )
        if resp.status_code != 200:
            logger.warning("node projection bridge returned %s for %s/%s; "
                           "falling back to the local projection",
                           resp.status_code, source_type, source_id)
            return None
        return dict(resp.json())
    except Exception as ex:                              # noqa: BLE001
        logger.warning("node projection bridge unreachable (%s) for %s/%s; "
                       "falling back to the local projection",
                       type(ex).__name__, source_type, source_id)
        return None
