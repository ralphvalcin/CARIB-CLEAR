"""Screening provider registry and built-in implementations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from carib_clear.compliance.cache import ScreeningCache
from carib_clear.config import ComplianceListConfig, ComplianceSourceConfig


@dataclass
class ProviderResult:
    provider_id: str
    term: str
    value: bool
    meta: Dict[str, Any]


class BaseProvider:
    provider_id: str = "base"
    kind: str = "base"

    def __init__(self, cfg: ComplianceSourceConfig, cache: Optional[ScreeningCache] = None):
        self.config = cfg
        self.cache = cache

    def screen(self, term: str, context: Dict[str, Any]) -> Optional[ProviderResult]:
        raise NotImplementedError()


class KeywordProvider(BaseProvider):
    provider_id: str = "default-keywords"
    kind: str = "keywords"

    def __init__(
        self,
        cfg: ComplianceSourceConfig,
        lists: ComplianceListConfig,
        cache: Optional[ScreeningCache] = None,
    ):
        super().__init__(cfg=cfg, cache=cache)
        self.lists = lists

    def screen(self, term: str, context: Dict[str, Any]) -> Optional[ProviderResult]:
        kind = (context.get("kind") or "sanctions").lower()
        keywords = self.lists.get_keywords(group=kind)
        matches = [k for k in keywords if k and k.lower() in term.lower()]
        value = bool(matches)
        return ProviderResult(
            provider_id=self.provider_id,
            term=term,
            value=value,
            meta={
                "kind": kind,
                "matches": matches,
                "cached": False,
            },
        )


class CachedProviderMixin:
    def _cache_lookup(self, term: str, kind: str) -> Optional[bool]:
        if not self.cache:
            return None
        return self.cache.get(source_id=self.provider_id, term=term, kind=kind)

    def _cache_store(self, term: str, value: bool, kind: str) -> None:
        if not self.cache:
            return
        ttl = self.config.config.get("ttl_seconds")
        self.cache.set(self.provider_id, term, value, kind, ttl)


class ComplianceProviderRegistry:
    def __init__(
        self,
        lists: Optional[ComplianceListConfig] = None,
        cache: Optional[ScreeningCache] = None,
    ):
        self.lists = lists or ComplianceListConfig()
        self.cache = cache
        self.providers: Dict[str, BaseProvider] = {}

    def load(self) -> None:
        self.providers = {}
        active_sources = []
        for source in self.lists.sources:
            if source.active:
                active_sources.append(source)
        if not active_sources:
            active_sources = [
                ComplianceSourceConfig(
                    id="default-keywords",
                    type="keywords",
                    active=True,
                    config={},
                )
            ]
        for src in active_sources:
            if src.type == "keywords":
                self.providers[src.id] = KeywordProvider(cfg=src, lists=self.lists, cache=self.cache)
            else:
                self.providers[src.id] = BaseProvider(cfg=src, cache=self.cache)

    def screen(
        self,
        term: str,
        kind: str = "sanctions",
        context: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None,
    ) -> List[ProviderResult]:
        context = context or {"kind": kind}
        results: List[ProviderResult] = []
        for provider in self.providers.values():
            try:
                result = provider.screen(term, context=context)
                if result is not None:
                    if correlation_id:
                        result.meta = {**(result.meta or {}), "correlation_id": correlation_id}
                    results.append(result)
                    try:
                        if isinstance(provider, CachedProviderMixin):
                            provider._cache_store(term, result.value, kind)
                    except Exception:  # noQA: BLE001
                        pass
            except Exception as exc:  # noQA: BLE001
                results.append(ProviderResult(provider_id=provider.provider_id, term=term, value=False, meta={"error": str(exc)}))
        return results
