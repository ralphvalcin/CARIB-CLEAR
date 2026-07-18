"""AML/PEP + config-backed screening regression tests."""

from __future__ import annotations

import pytest

from carib_clear.compliance.providers import (
    ComplianceProviderRegistry,
    KeywordProvider,
    ScreeningCache,
)
from carib_clear.compliance.screening import (
    ComplianceScreeningEngine,
    decide_review,
    decide_sanctions_block,
    is_ed_only,
)
from carib_clear.config import ComplianceListConfig, ComplianceSourceConfig, load_compliance_lists


def test_load_compliance_lists_default():
    cfg = load_compliance_lists()
    assert cfg.get_keywords("sanctions")
    assert cfg.get_keywords("pep")


def test_load_compliance_lists_with_source_dict():
    raw = {
        "cache": {"max_size": 16, "ttl_seconds": 30},
        "sources": {
            "src-a": {"type": "keywords", "active": True, "config": {"ttl_seconds": 30}},
            "src-b": {"type": "unknown", "active": False, "config": {}},
        },
        "keywords": {"sanctions": ["blocked person"], "pep": ["deputy"]},
    }
    cfg = ComplianceListConfig.from_raw(raw)

    assert cfg.cache["max_size"] == 16
    assert cfg.cache["ttl_seconds"] == 30
    assert [src.id for src in cfg.sources] == ["src-a"]
    assert cfg.get_keywords("sanctions") == ["blocked person"]
    assert cfg.get_keywords("pep") == ["deputy"]


def test_screening_cache_ttl_expiry():
    cache = ScreeningCache(max_size=8, default_ttl=0.05)
    assert cache.get("x", "term", "sanctions") is None
    cache.set("x", "term", True, "sanctions", ttl=0.05)
    assert cache.get("x", "term", "sanctions") is True
    import time as _time
    _time.sleep(0.1)
    assert cache.get("x", "term", "sanctions") is None
    assert cache.get("x", "term", "pep") is None


def test_registry_default_keyword_provider_when_no_sources():
    registry = ComplianceProviderRegistry(lists=ComplianceListConfig(), cache=ScreeningCache())
    registry.load()
    assert any(isinstance(p, KeywordProvider) for p in registry.providers.values())


def test_default_keyword_sanctions_match():
    engine = _build_engine()
    hit, matches = engine.screen_entity("specially designated national entity", kind="sanctions")
    assert hit is True
    assert any(m["matches"] for m in matches)


def test_default_keyword_sanctions_clean():
    engine = _build_engine()
    hit, _ = engine.screen_entity("clean trading company", kind="sanctions")
    assert hit is False


def test_default_keyword_pep_match():
    engine = _build_engine()
    hit, _ = engine.screen_entity("Minister of Finance Holdings", kind="pep")
    assert hit is True


def test_screening_transaction_sanctions_block():
    engine = _build_engine()
    result = engine.screen_transaction(
        transaction_id="tx-1",
        from_participant="clean sender",
        to_participant="specially designated national entity",
        amount_usd=1000,
        currency="USD",
        from_jurisdiction="BB",
        to_jurisdiction="JM",
        purpose="trade",
    )
    assert result["passed"] is False
    assert "sanctions_match" in result["issues"]


def test_screening_transaction_pep_ed_only():
    engine = _build_engine()
    result = engine.screen_transaction(
        transaction_id="tx-2",
        from_participant="PEP Minister actor",
        to_participant="clean receiver",
        amount_usd=5000,
        currency="BBD",
        from_jurisdiction="BB",
        to_jurisdiction="JM",
        purpose="trade",
    )
    assert result["passed"] is True
    assert "pep_involved" in result["issues"]
    assert result["requires_review"] is True


def test_screening_transaction_high_value_review():
    engine = _build_engine()
    result = engine.screen_transaction(
        transaction_id="tx-3",
        from_participant="clean sender",
        to_participant="clean receiver",
        amount_usd=1000000,
        currency="USD",
        from_jurisdiction="BB",
        to_jurisdiction="JM",
        purpose="trade",
    )
    assert result["passed"] is True
    assert result["requires_review"] is True


def test_decide_rules():
    assert decide_sanctions_block(hit_count=0, value=False) is False
    assert decide_sanctions_block(hit_count=1, value=True) is True
    assert is_ed_only(pep_flagged=True, sanctions_hit=False, aml_only=False) is True
    assert is_ed_only(pep_flagged=True, sanctions_hit=True, aml_only=False) is False
    assert decide_review(passed=True, issues=[], amount_usd=1000, sanctions_hit=False, pep_flagged=False) is False
    assert decide_review(passed=True, issues=[], amount_usd=300000, sanctions_hit=False, pep_flagged=False) is True


@pytest.fixture()
def screening() -> ComplianceScreeningEngine:
    return _build_engine()


def _build_engine() -> ComplianceScreeningEngine:
    engine = ComplianceScreeningEngine()
    engine.initialize()
    return engine
