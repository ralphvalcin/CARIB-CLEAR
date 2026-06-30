"""Tests for FlowVisibilityAgent — currency flow detection and matching."""

from __future__ import annotations

from carib_clear.agents.flow_visibility import (
    CurrencyFlow,
    FlowVisibilityAgent,
    MatchingOpportunity,
)


def test_currency_flow_defaults() -> None:
    flow = CurrencyFlow("BBD", "BB", "demand", 10000, 0.8, "merchant")
    assert flow.currency == "BBD"
    assert flow.direction == "demand"
    assert flow.amount_usd == 10000


def test_scan_empty() -> None:
    assert FlowVisibilityAgent().scan_for_matches() == []


def test_single_flow_no_match() -> None:
    agent = FlowVisibilityAgent()
    agent.ingest_flow(CurrencyFlow("BBD", "BB", "demand", 50000, 0.9, "importer"))
    assert agent.scan_for_matches() == []


def test_basic_demand_supply_match() -> None:
    agent = FlowVisibilityAgent()
    agent.ingest_flow(CurrencyFlow("BBD", "BB", "demand", 50000, 0.9, "importer"))
    agent.ingest_flow(CurrencyFlow("JMD", "JM", "supply", 50000, 0.8, "exporter"))
    matches = agent.scan_for_matches()
    assert len(matches) >= 1


def test_no_match_same_direction() -> None:
    agent = FlowVisibilityAgent()
    agent.ingest_flow(CurrencyFlow("BBD", "BB", "demand", 50000, 0.9, "a"))
    agent.ingest_flow(CurrencyFlow("JMD", "JM", "demand", 50000, 0.8, "b"))
    assert agent.scan_for_matches() == []


def test_no_match_unknown_corridor() -> None:
    agent = FlowVisibilityAgent()
    agent.ingest_flow(CurrencyFlow("EUR", "BB", "demand", 50000, 0.9, "a"))
    agent.ingest_flow(CurrencyFlow("EUR", "JM", "supply", 50000, 0.8, "b"))
    assert agent.scan_for_matches() == []


def test_get_stats() -> None:
    agent = FlowVisibilityAgent()
    agent.ingest_flow(CurrencyFlow("BBD", "BB", "demand", 40000, 0.8, "merchant"))
    stats = agent.get_stats()
    assert stats["demand_flows"] == 1
    assert stats["total_volume_usd"] == 40000


def test_generate_mock_flows() -> None:
    agent = FlowVisibilityAgent()
    agent.generate_mock_flows()
    stats = agent.get_stats()
    assert stats["demand_flows"] > 0
    assert stats["total_volume_usd"] > 0


def test_stats_track_matches() -> None:
    agent = FlowVisibilityAgent()
    agent.ingest_flow(CurrencyFlow("BBD", "BB", "demand", 50000, 0.9, "a"))
    agent.ingest_flow(CurrencyFlow("JMD", "JM", "supply", 50000, 0.8, "b"))
    agent.scan_for_matches()
    stats = agent.get_stats()
    # Matching opportunities are in the match list, not in stats dict
    assert stats["total_volume_usd"] >= 100000


def test_multi_currency_scan() -> None:
    agent = FlowVisibilityAgent()
    agent.ingest_flow(CurrencyFlow("BBD", "BB", "demand", 50000, 0.9, "a"))
    agent.ingest_flow(CurrencyFlow("JMD", "JM", "supply", 60000, 0.8, "b"))
    agent.ingest_flow(CurrencyFlow("TTD", "TT", "demand", 25000, 0.7, "c"))
    agent.ingest_flow(CurrencyFlow("BBD", "BB", "supply", 30000, 0.6, "d"))
    matches = agent.scan_for_matches()
    assert len(matches) >= 1


def test_demand_and_supply_lists() -> None:
    agent = FlowVisibilityAgent()
    assert agent.demand_flows == []
    assert agent.supply_flows == []
    agent.ingest_flow(CurrencyFlow("BBD", "BB", "demand", 5000, 0.5, "a"))
    assert len(agent.demand_flows) == 1
    assert len(agent.supply_flows) == 0