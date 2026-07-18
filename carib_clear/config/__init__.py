"""CARIB-CLEAR compliance/screening configuration loader."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from carib_clear.secrets import get_secret

logger = logging.getLogger(__name__)


@dataclass
class ComplianceSourceConfig:
    id: str
    type: str
    active: bool
    config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ComplianceListConfig:
    cache: Dict[str, Any] = field(default_factory=dict)
    sources: List[ComplianceSourceConfig] = field(default_factory=list)
    keywords: Dict[str, List[str]] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)

    def get_keywords(self, group: str) -> List[str]:
        return list(self.keywords.get(group, []))

    @classmethod
    def from_raw(cls, raw: Dict[str, Any]) -> "ComplianceListConfig":
        cache = raw.get("cache", {})
        sources = [
            ComplianceSourceConfig(
                id=src.get("id", source_id),
                type=src.get("type", source_id),
                active=bool(src.get("active", True)),
                config=src.get("config", {}),
            )
            for source_id, src in raw.get("sources", {}).items()
            if bool(src.get("active", True))
        ]
        return cls(cache=cache, sources=sources, keywords=raw.get("keywords", {}), raw=raw)


def load_compliance_lists(path: Optional[str] = None) -> ComplianceListConfig:
    candidates = [
        path,
        os.getenv("CARIB_CLEAR_COMPLIANCE_LISTS"),
        os.path.join(os.path.dirname(__file__), "compliance_lists.json"),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            with open(candidate, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            cache = raw.get("cache", {})
            sources = [
                ComplianceSourceConfig(
                    id=src.get("id", source_id),
                    type=src.get("type", source_id),
                    active=bool(src.get("active", True)),
                    config=src.get("config", {}),
                )
                for source_id, src in raw.get("sources", {}).items()
            ]
            return ComplianceListConfig(
                cache=cache,
                sources=sources,
                keywords=raw.get("keywords", {}),
                raw=raw,
            )
        except FileNotFoundError:
            continue
        except Exception as exc:  # noQA: BLE001
            logger.warning("Failed to load compliance lists: %s", exc)
            break
    return ComplianceListConfig()
