"""Tests for NetSettlementAgent — multilateral netting, positions, cycles."""

from __future__ import annotations

from carib_clear.agents.net_settlement import (
    NetPosition,
    NetSettlementAgent,
    NettingCycle,
)
from carib_clear.governance.agent import GovernanceAgent
from carib_clear.broker.base import MultiRailRouter
from carib_clear.broker.stellar_adapter import StellarAdapter


def _make_agent() -> NetSettlementAgent:
    """Create a test net settlement agent."""
    gov = GovernanceAgent()
    router = MultiRailRouter([
        StellarAdapter({"mock_mode": True}),
    ])
    return NetSettlementAgent(gov, router)


def test_net_position_defaults() -> None:
    """Verify NetPosition dataclass."""
    pos = NetPosition(
        participant_id="test_participant",
        currency="BBD",
        net_amount_usd=10000,
        jurisdiction="BB",
    )
    assert pos.participant_id == "test_participant"
    assert pos.currency == "BBD"
    assert pos.net_amount_usd == 10000
    assert pos.transactions == []


def test_netting_cycle_defaults() -> None:
    """Verify NettingCycle dataclass."""
    cycle = NettingCycle(
        cycle_id="test-cycle-001",
        timestamp="2026-01-01",
        participants=["A", "B"],
        currencies=["BBD"],
        gross_volume_usd=100000,
        net_volume_usd=60000,
        netting_efficiency=0.40,
        settlement_instructions=[],
        governance_approvals={},
    )
    assert cycle.cycle_id == "test-cycle-001"
    assert cycle.netting_efficiency == 0.40
    assert cycle.gross_volume_usd == 100000


def test_add_transaction() -> None:
    """Verify adding transactions to the netting pool."""
    agent = _make_agent()
    agent.add_transaction(
        transaction_id="tx-001",
        from_participant="participant_a",
        to_participant="participant_b",
        from_currency="BBD",
        to_currency="JMD",
        amount_usd=50000,
        rate=76.5,
        from_jurisdiction="BB",
        to_jurisdiction="JM",
        rail="stellar_usdc",
    )
    assert len(agent.pending_transactions) == 1
    assert agent.get_pending_volume() == 50000


def test_should_run_cycle_with_volume() -> None:
    """Verify cycle should run when transactions exist."""
    agent = _make_agent()
    agent.add_transaction(
        transaction_id="tx-001",
        from_participant="a", to_participant="b",
        from_currency="BBD", to_currency="JMD",
        amount_usd=50000, rate=76.5,
        from_jurisdiction="BB", to_jurisdiction="JM",
        rail="stellar_usdc",
    )
    assert agent.should_run_cycle() is True


def test_should_not_run_cycle_empty() -> None:
    """Verify cycle should not run with no transactions."""
    agent = _make_agent()
    assert agent.should_run_cycle() is False


def test_single_transaction_netting() -> None:
    """Verify netting a single transaction produces correct positions."""
    agent = _make_agent()
    agent.add_transaction(
        transaction_id="tx-001",
        from_participant="alice", to_participant="bob",
        from_currency="BBD", to_currency="JMD",
        amount_usd=50000, rate=76.5,
        from_jurisdiction="BB", to_jurisdiction="JM",
        rail="stellar_usdc",
    )
    positions = agent._calculate_net_positions()
    # Alice pays 50K BBD, Bob receives 50K JMD (in USD terms)
    assert "alice/BBD" in positions
    assert "bob/JMD" in positions
    assert positions["alice/BBD"].net_amount_usd == -50000
    assert positions["bob/JMD"].net_amount_usd == 50000


def test_bilateral_netting() -> None:
    """Verify two parties can net their mutual obligations (same currency)."""
    agent = _make_agent()
    # Alice owes Bob $50K BBD, Bob owes Alice $30K BBD
    agent.add_transaction(
        transaction_id="tx-001",
        from_participant="alice", to_participant="bob",
        from_currency="BBD", to_currency="BBD",
        amount_usd=50000, rate=1.0,
        from_jurisdiction="BB", to_jurisdiction="BB",
        rail="stellar_usdc",
    )
    agent.add_transaction(
        transaction_id="tx-002",
        from_participant="bob", to_participant="alice",
        from_currency="BBD", to_currency="BBD",
        amount_usd=30000, rate=1.0,
        from_jurisdiction="BB", to_jurisdiction="BB",
        rail="stellar_usdc",
    )

    positions = agent._calculate_net_positions()
    assert "alice/BBD" in positions
    assert "bob/BBD" in positions

    # Alice: -50K + 30K = -20K net (owes 20K)
    assert positions["alice/BBD"].net_amount_usd == -20000
    # Bob: +50K - 30K = +20K net (receives 20K)
    assert positions["bob/BBD"].net_amount_usd == 20000

    instructions = agent._generate_settlement_instructions(positions)
    assert len(instructions) >= 1
    total_net = sum(i["amount_usd"] for i in instructions)
    assert total_net == 20000  # 20K net instead of 80K gross


def test_triangular_netting_efficiency() -> None:
    """Verify triangular netting reduces gross volume."""
    agent = _make_agent()
    # A→B $50K, B→C $30K, C→A $20K = $100K gross
    agent.add_transaction(
        transaction_id="tx-ab", from_participant="a", to_participant="b",
        from_currency="BBD", to_currency="USD",
        amount_usd=50000, rate=0.5,
        from_jurisdiction="BB", to_jurisdiction="US", rail="stellar_usdc",
    )
    agent.add_transaction(
        transaction_id="tx-bc", from_participant="b", to_participant="c",
        from_currency="USD", to_currency="BBD",
        amount_usd=30000, rate=2.0,
        from_jurisdiction="US", to_jurisdiction="BB", rail="stellar_usdc",
    )
    agent.add_transaction(
        transaction_id="tx-ca", from_participant="c", to_participant="a",
        from_currency="BBD", to_currency="USD",
        amount_usd=20000, rate=0.5,
        from_jurisdiction="BB", to_jurisdiction="US", rail="stellar_usdc",
    )

    positions = agent._calculate_net_positions()
    assert len(positions) >= 1  # At least one net position

    instructions = agent._generate_settlement_instructions(positions)
    instructions_total = sum(i["amount_usd"] for i in instructions)
    assert instructions_total < 100000  # Net less than gross


def test_run_netting_cycle() -> None:
    """Verify full netting cycle execution (same-jurisdiction)."""
    agent = _make_agent()
    agent.add_transaction(
        transaction_id="tx-001",
        from_participant="alice", to_participant="bob",
        from_currency="BBD", to_currency="BBD",
        amount_usd=50000, rate=1.0,
        from_jurisdiction="BB", to_jurisdiction="BB",
        rail="stellar_usdc",
    )
    agent.add_transaction(
        transaction_id="tx-002",
        from_participant="bob", to_participant="charlie",
        from_currency="BBD", to_currency="BBD",
        amount_usd=25000, rate=1.0,
        from_jurisdiction="BB", to_jurisdiction="BB",
        rail="stellar_usdc",
    )

    cycle = agent.run_netting_cycle()
    assert cycle is not None, f"Cycle was None. Check governance accepts same-jurisdiction settlements."
    assert isinstance(cycle, NettingCycle)
    assert cycle.gross_volume_usd == 75000
    assert cycle.netting_efficiency >= 0


def test_run_netting_cycle_empty() -> None:
    """Verify no cycle runs with no transactions."""
    agent = _make_agent()
    cycle = agent.run_netting_cycle()
    assert cycle is None


def test_pending_by_currency() -> None:
    """Verify pending volume grouping by currency."""
    agent = _make_agent()
    agent.add_transaction(
        transaction_id="tx-001",
        from_participant="a", to_participant="b",
        from_currency="BBD", to_currency="JMD",
        amount_usd=50000, rate=76.5,
        from_jurisdiction="BB", to_jurisdiction="JM",
        rail="stellar_usdc",
    )
    agent.add_transaction(
        transaction_id="tx-002",
        from_participant="c", to_participant="d",
        from_currency="TTD", to_currency="USD",
        amount_usd=25000, rate=0.147,
        from_jurisdiction="TT", to_jurisdiction="US",
        rail="stellar_usdc",
    )
    by_ccy = agent.get_pending_by_currency()
    assert "BBD" in by_ccy
    assert "TTD" in by_ccy
    assert by_ccy["BBD"] >= 50000


def test_recommend_rail_same_jurisdiction() -> None:
    """Verify same-jurisdiction netting prefers local ACH."""
    agent = _make_agent()
    rail = agent._recommend_rail("BB", "BB", "BBD")
    assert "ach" in rail


def test_recommend_rail_cross_jurisdiction() -> None:
    """Verify cross-jurisdiction netting prefers Stellar."""
    agent = _make_agent()
    rail = agent._recommend_rail("BB", "JM", "BBD")
    assert rail == "stellar_usdc"


def test_get_stats() -> None:
    """Verify stats tracking."""
    agent = _make_agent()
    stats = agent.get_stats()
    assert stats["pending_transactions"] == 0
    assert stats["completed_cycles"] == 0

    agent.add_transaction(
        transaction_id="tx-001",
        from_participant="a", to_participant="b",
        from_currency="BBD", to_currency="JMD",
        amount_usd=50000, rate=76.5,
        from_jurisdiction="BB", to_jurisdiction="JM",
        rail="stellar_usdc",
    )
    stats = agent.get_stats()
    assert stats["pending_transactions"] == 1