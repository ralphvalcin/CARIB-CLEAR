"""Runtime config reload helper."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def reload_compliance_lists(path: str, actor: Optional[str] = None) -> Dict[str, Any]:
    from carib_clear.audit import audit as _audit_rel
    from carib_clear.compliance.cache import ScreeningCache
    from carib_clear.compliance.screening import ComplianceScreeningEngine

    source_type = "env"
    if not path:
        path = os.getenv("CARIB_CLEAR_COMPLIANCE_LISTS", "")
    if not path or not os.path.isfile(path):
        status = "failed"
        reason = "missing or unreadable lists path"
        _audit_rel(
            event="compliance.reload_lists",
            actor=actor or "api",
            action="reload_compliance_lists",
            entity="compliance_lists",
            entity_id=path or "",
            payload={"path": path or "", "status": status, "reason": reason},
            outcome=status,
        )
        return {
            "file": path or "",
            "status": status,
            "reason": reason,
            "source_count": 0,
            "keyword_groups": [],
            "cache_max_size": 0,
            "content_sha256": "",
        }

    if os.path.getsize(path) <= 0:
        status = "failed"
        reason = "empty compliance lists file"
        _audit_rel(
            event="compliance.reload_lists",
            actor=actor or "api",
            action="reload_compliance_lists",
            entity="compliance_lists",
            entity_id=path,
            payload={"path": path, "status": status, "reason": reason},
            outcome=status,
        )
        return {
            "file": path,
            "status": status,
            "reason": reason,
            "source_count": 0,
            "keyword_groups": [],
            "cache_max_size": 0,
            "content_sha256": "",
        }

    try:
        content_hash = _sha256_file(path)
    except Exception as exc:
        status = "failed"
        _audit_rel(
            event="compliance.reload_lists",
            actor=actor or "api",
            action="reload_compliance_lists",
            entity="compliance_lists",
            entity_id=path,
            payload={"path": path, "status": status, "error": str(exc)},
            outcome=status,
        )
        return {
            "file": path,
            "status": status,
            "reason": f"hash error: {exc}",
            "source_count": 0,
            "keyword_groups": [],
            "cache_max_size": 0,
        }

    try:
        engine = ComplianceScreeningEngine(lists_path=path)
        engine.initialize()
        status = "success"
        payload = {
            "file": path,
            "source_count": len(engine.providers),
            "keyword_groups": sorted(engine.lists.keywords.keys()),
            "cache_max_size": engine.cache.max_size,
            "content_sha256": content_hash,
        }
        _audit_rel(
            event="compliance.reload_lists",
            actor=actor or "api",
            action="reload_compliance_lists",
            entity="compliance_lists",
            entity_id=path,
            payload=payload,
            outcome=status,
        )
        return {
            "file": path,
            "status": status,
            **payload,
        }
    except Exception as exc:
        status = "failed"
        _audit_rel(
            event="compliance.reload_lists",
            actor="api",
            action="reload_compliance_lists",
            entity="compliance_lists",
            entity_id=path,
            payload={"path": path, "status": status, "error": str(exc), "content_sha256": content_hash},
            outcome=status,
        )
        return {
            "file": path,
            "status": status,
            "reason": str(exc),
            "source_count": 0,
            "keyword_groups": [],
            "cache_max_size": 0,
            "content_sha256": content_hash,
        }
