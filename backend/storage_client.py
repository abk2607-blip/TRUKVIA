"""Object storage client (Emergent Integrations).
Wraps put/get/init for uploaded files: logos, vehicle document scans, LR proofs, fuel bills.
"""
import os
import logging
import requests
from typing import Tuple

logger = logging.getLogger(__name__)

STORAGE_BASE = (os.environ.get("INTEGRATION_PROXY_URL") or "").strip() or "https://integrations.emergentagent.com"
STORAGE_URL = STORAGE_BASE.rstrip("/") + "/objstore/api/v1/storage"
APP_NAME = "bitumen-accounting"

_storage_key = None

MIME_TYPES = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "gif": "image/gif", "webp": "image/webp", "pdf": "application/pdf",
    "json": "application/json", "csv": "text/csv", "txt": "text/plain",
}


def init_storage(force: bool = False) -> str:
    """Call once at startup to mint a storage_key. Returns cached key by default."""
    global _storage_key
    if _storage_key and not force:
        return _storage_key
    emergent_key = os.environ.get("EMERGENT_LLM_KEY")
    if not emergent_key:
        raise RuntimeError("EMERGENT_LLM_KEY not set")
    resp = requests.post(
        f"{STORAGE_URL}/init",
        json={"emergent_key": emergent_key},
        timeout=30,
    )
    resp.raise_for_status()
    _storage_key = resp.json()["storage_key"]
    return _storage_key


def put_object(path: str, data: bytes, content_type: str) -> dict:
    """Upload; on 404 (dead session key) retry once with force init."""
    def _do(key: str):
        return requests.put(
            f"{STORAGE_URL}/objects/{path}",
            headers={"X-Storage-Key": key, "Content-Type": content_type},
            data=data,
            timeout=120,
        )

    key = init_storage()
    r = _do(key)
    if r.status_code == 404:
        key = init_storage(force=True)
        r = _do(key)
    r.raise_for_status()
    return r.json()


def get_object(path: str) -> Tuple[bytes, str]:
    def _do(key: str):
        return requests.get(
            f"{STORAGE_URL}/objects/{path}",
            headers={"X-Storage-Key": key},
            timeout=60,
        )

    key = init_storage()
    r = _do(key)
    if r.status_code == 404 and "X-Storage-Key" in r.request.headers:
        # try refresh key once
        key = init_storage(force=True)
        r = _do(key)
    r.raise_for_status()
    return r.content, r.headers.get("Content-Type", "application/octet-stream")


def mime_for(filename: str, fallback: str = "application/octet-stream") -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return MIME_TYPES.get(ext, fallback)
