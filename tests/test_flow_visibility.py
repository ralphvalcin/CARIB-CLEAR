"""Tests for FlowVisibilityAgent — currency flow ingestion and matching."""

from __future__ import annotations

from carib_clear.agents.flow_visibility import (
    CurrencyFlow,
    FlowVisibilityAgent,
    MatchingOpportunity,
)


def test_currency_flow_defaults() -> None:
    """Verify CurrencyFlow dataclass."""
    flow = CurrencyFlow(currency="BBD", jurisdiction="BB", direction="demand",
                        amount_usd=50000, urgency=0.8, source="merchant")
    assert flow.direction == "demand"
    assert flow.currency == "BBD"


def test_matching_opportunity_defaults() -> None:
    """Verify MatchingOpportunity dataclass."""
    demand = CurrencyFlow("BBD", "BB", "demand", 50000, 0.8, "merchant")
    supply = CurrencyFlow("JMD", "JM", "supply", 50000, 0.9, "treasury")
    opp = MatchingOpportunity(
        opportunity_id="opp-001",
        demand_flow=demand, supply_flow=supply,
        match_amount_usd=50000, implied_rate=76.5,
        confidence=0.85, estimated_savings_bps=700,
    )
    assert opp.confidence == 0.85
    assert opp.match_amount_usd == 50000


def test_ingest_demand_flow() -> None:
    """Verify demand flows are ingested and stored."""
    agent = FlowVisibilityAgent()
    flow = CurrencyFlow("BBD", "BB", "demand", 50000, 0.8, "merchant")
    agent.ingest_flow(flow)
    assert len(agent.demand_flows) == 1
    assert len(agent.supply_flows) == 0
    assert agent.demand_flows[0].amount_usd == 50000


def test_ingest_supply_flow() -> None:
    """Verify supply flows are ingested and stored."""
    agent = FlowVisibilityAgent()
    flow = CurrencyFlow("JMD", "JM", "supply", 50000, 0.9, "treasury")
    agent.ingest_flow(flow)
    assert len(agent.supply_flows) == 1


def test_ingest_unknown_direction() -> None:
    """Verify unknown flow direction is handled."""
    agent = FlowVisibilityAgent()
    flow = CurrencyFlow("BBD", "BB", "unknown", 50000, 0.5, "test")
    agent.ingest_flow(flow)
    assert len(agent.demand_flows) == 0
    assert len(agent.supply_flows) == 0


def test_start_stop() -> None:
    """Verify start/stop toggles running state."""
    agent = FlowVisibilityAgent()
    agent.start()
    assert agent._running is True
    agent.stop()
    assert agent._running is False


def test_scan_matches_same_currency_pair() -> None:
    """Verify scanning finds matches for valid currency pairs."""
    agent = FlowVisibilityAgent()
    demand = CurrencyFlow("BBD", "BB", "demand", 50000, 0.8, "merchant")
    supply = CurrencyFlow("JMD", "BB", "supply", 60000, 0.9, "treasury")
    agent.ingest_flow(demand)
    agent.ingest_flow(supply)
    matches = agent.scan_for_matches()
    assert len(matches) >= 1
    m = matches[0]
    assert m.match_amount_usd == 50000  # Min of demand/supply
    assert m.confidence > 0.5


def test_scan_no_match_unrelated_pairs() -> None:
    """Verify scanning returns no matches for unrelated currencies."""
    agent = FlowVisibilityAgent()
    # BBD and EUR — EUR isn't in our corridors
    demand = CurrencyFlow("BBD", "BB", "demand", 50000, 0.8, "merchant")
    supply = CurrencyFlow("EUR", "BB", "supply", 50000, 0.9, "treasury")
    agent.ingest_flow(demand)
    agent.ingest_flow(supply)
    matches = agent.scan_for_matches()
    assert len(matches) == 0


def test_scan_no_match_small_amount() -> None:
    """Verify scanning ignores very small matches."""
    agent = FlowVisibilityAgent()
    demand = CurrencyFlow("BBD", "BB", "demand", 50, 0.8, "merchant")
    supply = CurrencyFlow("JMD", "BB", "supply", 50, 0.9, "treasury")
    agent.ingest_flow(demand)
    agent.ingest_flow(supply)
    matches = agent.scan_for_matches()
    assert len(matches) == 0  # Below minimum $100


def test_valid_pair() -> None:
    """Verify currency pair validation."""
    agent = FlowVisibilityAgent()
    assert agent._is_valid_pair("BBD", "JMD") is True
    assert agent._is_valid_pair("JMD", "BBD") is True  # Reversed
    assert agent._is_valid_pair("BBD", "EUR") is False  # Not in corridors


def test_compatible_jurisdictions_same() -> None:
    """Verify same jurisdiction is always compatible."""
    agent = FlowVisibilityAgent()
    assert agent._compatible_jurisdictions("BB", "BB") is True
    assert agent._compatible_jurisdictions("HT", "HT") is True


def test_compatible_jurisdictions_corridor() -> None:
    """Verify corridor jurisdictions are compatible."""
    agent = FlowVisibilityAgent()
    assert agent._compatible_jurisdictions("BB", "JM") is True
    assert agent._compatible_jurisdictions("HT", "ECCB") is True


def test_compatible_jurisdictions_incompatible() -> None:
    """Verify incompatible jurisdictions return False."""
    agent = FlowVisibilityAgent()
    assert agent._compatible_jurisdictions("BB", "US") is False
    assert agent._compatible_jurisdictions("HT", "BB") is False


def test_generate_mock_flows() -> None:
    """Verify mock flow generation."""
    agent = FlowVisibilityAgent()
    agent.generate_mock_flows(count=5)
    # Flows are ingested directly into the agent
    assert len(agent.demand_flows) + len(agent.supply_flows) == 5
    for f in agent.demand_flows:
        assert f.direction == "demand"


def test_scan_multi_currency_matches() -> None:
    """Verify scanning multiple flows finds best matches first."""
    agent = FlowVisibilityAgent()
    # Add flows for multiple corridors
    agent.ingest_flow(CurrencyFlow("BBD", "BB", "demand", 100000, 0.9, "merchant"))
    agent.ingest_flow(CurrencyFlow("JMD", "BB", "supply", 80000, 0.7, "treasury"))
    agent.ingest_flow(CurrencyFlow("TTD", "TT", "demand", 50000, 0.8, "importer"))
    agent.ingest_flow(CurrencyFlow("XCD", "TT", "supply", 45000, 0.9, "reserves"))
    matches = agent.scan_for_matches()
    assert len(matches) >= 2
    # Sorted by confidence * savings — top match first
    assert matches[0].confidence > 0.5


def test_savings_estimate() -> None:
    """Verify savings estimate returns non-zero for valid pairs."""
    agent = FlowVisibilityAgent()
    savings = agent._estimate_savings("BBD", "JMD")
    assert savings > 0
    assert savings < 2000  # Sanity check: within reasonable range


def test_calculate_implied_rate() -> None:
    """Verify implied rate calculation."""
    agent = FlowVisibilityAgent()
    demand = CurrencyFlow("BBD", "BB", "demand", 50000, 0.8, "merchant")
    supply = CurrencyFlow("JMD", "BB", "supply", 50000, 0.9, "treasury")
    rate = agent._calculate_implied_rate(demand, supply)
    assert rate > 0


def test_flow_window_limited() -> None:
    """Verify flows are capped at 1000 entries."""
    agent = FlowVisibilityAgent()
    for i in range(1100):
        flow = CurrencyFlow("BBD", "BB", "demand", 100, 0.5, "test")
        agent.ingest_flow(flow)
    assert len(agent.demand_flows) == 1000  # Capped