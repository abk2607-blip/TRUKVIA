"""Audit-log write helpers."""
import logging
from typing import Optional
from db import db
from models import AuditLog, new_id, now_utc

logger = logging.getLogger(__name__)


async def _log_audit(user: dict, module: str, action: str, entity_id: str = "", entity_ref: str = "", reason: str = "", changes: Optional[dict] = None):
    doc = AuditLog(
        module=module, action=action,
        entity_id=entity_id, entity_ref=entity_ref,
        reason=reason, changes=changes or {},
        user_email=user.get("email", ""), user_name=user.get("name", ""),
    ).model_dump()
    doc["user_id"] = user["user_id"]
    try:
        await db.audit_logs.insert_one(doc)
    except Exception as e:
        logger.warning(f"audit log failed: {e}")


def _diff_dict(old: dict, new: dict, keys: Optional[list] = None) -> dict:
    """Return {field: {old, new}} for keys where values differ."""
    diff = {}
    if keys is None:
        keys = set(list(old.keys()) + list(new.keys()))
    for k in keys:
        if old.get(k) != new.get(k):
            diff[k] = {"old": old.get(k), "new": new.get(k)}
    return diff
