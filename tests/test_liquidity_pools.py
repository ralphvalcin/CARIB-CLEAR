"""Tests for LiquidityPoolManager."""

from __future__ import annotations

from carib_clear.agents.liquidity_pools import (
    LiquidityPoolManager,
    LiquidityProvider,
    CurrencyPool,
    PoolQuote,
)


def test_liquidity_provider_creation() -> None:
    """Verify LiquidityProvider creation."""
    provider = LiquidityProvider(
        provider_id="test_bank",
        name="Test Bank",
        jurisdiction="BB",
        provider_type="bank",
        tier=1,
    )
    assert provider.provider_id == "test_bank"
    assert provider.currencies == []
    assert provider.active is True


def test_currency_pool_defaults() -> None:
    """Verify CurrencyPool defaults."""
    pool = CurrencyPool(currency="BBD")
    assert pool.currency == "BBD"
    assert pool.total_liquidity_usd == 0.0
    assert pool.provider_count == 0
    assert pool.available_liquidity_usd == 0.0


def test_register_provider() -> None:
    """Verify provider registration."""
    mgr = LiquidityPoolManager()
    provider = mgr.register_provider("test_001", "Test Provider", "JM", "bank", 1)
    assert provider.provider_id == "test_001"
    assert provider.name == "Test Provider"
    assert provider.jurisdiction == "JM"


def test_deposit_and_withdraw() -> None:
    """Verify deposit and withdrawal."""
    mgr = LiquidityPoolManager()
    mgr.register_provider("test_001", "Test Provider", "JM")
    assert mgr.deposit("test_001", "JMD", 100000) is True
    assert mgr.deposit("test_001", "USD", 50000) is True

    stats = mgr.get_stats()
    assert stats["total_liquidity_usd"] == 150000
    assert stats["total_providers"] == 1

    assert mgr.withdraw("test_001", "JMD", 50000) is True
    stats = mgr.get_stats()
    assert stats["total_liquidity_usd"] == 100000


def test_withdraw_insufficient() -> None:
    """Verify withdrawal fails for insufficient balance."""
    mgr = LiquidityPoolManager()
    mgr.register_provider("test_001", "Test Provider", "JM")
    mgr.deposit("test_001", "JMD", 10000)
    assert mgr.withdraw("test_001", "JMD", 50000) is False


def test_unknown_provider_deposit() -> None:
    """Verify deposit fails for unknown provider."""
    mgr = LiquidityPoolManager()
    assert mgr.deposit("unknown", "USD", 1000) is False


def test_get_quote_supported_pair() -> None:
    """Verify quote generation for a supported pair."""
    mgr = LiquidityPoolManager()
    mgr.register_provider("test_001", "Test Provider", "JM")
    mgr.deposit("test_001", "BBD", 500000)
    mgr.deposit("test_001", "JMD", 500000)

    quote = mgr.get_quote("BBD", "JMD", 10000)
    assert quote is not None
    assert quote.pair == ("BBD", "JMD")
    assert quote.rate > 0
    assert quote.spread_bps > 0
    assert quote.estimated_fee_usd > 0
    assert isinstance(quote, PoolQuote)


def test_get_quote_unsupported_pair() -> None:
    """Verify quote returns None for unsupported pair."""
    mgr = LiquidityPoolManager()
    quote = mgr.get_quote("XXX", "YYY", 1000)
    assert quote is None


def test_get_quote_inverted_pair() -> None:
    """Verify quote works for inverted pairs (JMD→BBD when BBD→JMD known)."""
    mgr = LiquidityPoolManager()
    mgr.register_provider("test_001", "Test Provider", "JM")
    mgr.deposit("test_001", "BBD", 500000)
    mgr.deposit("test_001", "JMD", 500000)

    quote = mgr.get_quote("JMD", "BBD", 10000)
    assert quote is not None
    assert quote.pair == ("JMD", "BBD")
    assert quote.rate > 0


def test_order_book_depth() -> None:
    """Verify order book depth query."""
    mgr = LiquidityPoolManager()
    mgr.register_provider("test_001", "Test Provider", "JM")
    mgr.deposit("test_001", "BBD", 500000)
    mgr.deposit("test_001", "JMD", 500000)

    depth = mgr.get_order_book_depth("BBD", "JMD")
    assert depth is not None
    assert depth.spread_bps > 0
    assert depth.mid_market_rate > 0


def test_commit_and_release() -> None:
    """Verify liquidity commitment and release."""
    mgr = LiquidityPoolManager()
    mgr.register_provider("test_001", "Test Provider", "JM")
    mgr.deposit("test_001", "USD", 100000)

    assert mgr.commit_liquidity("USD", 30000) is True
    stats = mgr.get_stats()
    assert stats["total_committed_usd"] == 30000

    mgr.release_liquidity("USD", 30000)
    stats = mgr.get_stats()
    assert stats["total_committed_usd"] == 0


def test_commit_insufficient() -> None:
    """Verify commit fails when liquidity is insufficient."""
    mgr = LiquidityPoolManager()
    mgr.register_provider("test_001", "Test Provider", "JM")
    mgr.deposit("test_001", "USD", 10000)
    assert mgr.commit_liquidity("USD", 50000) is False


def test_get_stats_summary() -> None:
    """Verify stats summary is well-formed."""
    mgr = LiquidityPoolManager()
    mgr.register_provider("test_001", "Test Provider", "JM")
    mgr.deposit("test_001", "BBD", 100000)
    mgr.deposit("test_001", "JMD", 100000)

    stats = mgr.get_stats()
    assert "total_liquidity_usd" in stats
    assert "pools" in stats
    assert "BBD" in stats["pools"]
    assert "JMD" in stats["pools"]


def test_generate_mock_providers() -> None:
    """Verify mock provider generation."""
    mgr = LiquidityPoolManager()
    ids = mgr.generate_mock_providers()
    assert len(ids) == 10

    stats = mgr.get_stats()
    assert stats["total_providers"] == 10
    assert stats["total_liquidity_usd"] > 0
    assert stats["currency_count"] >= 5


def test_spread_widens_with_thin_liquidity() -> None:
    """Verify spread is wider when liquidity is thin."""
    mgr = LiquidityPoolManager()

    # Thin pool
    mgr.register_provider("small", "Small Bank", "BB")
    mgr.deposit("small", "BBD", 5000)
    mgr.deposit("small", "JMD", 5000)
    thin_spread = mgr.calculate_spread("BBD", "JMD", 1000)

    # Deep pool
    mgr2 = LiquidityPoolManager()
    mgr2.register_provider("big", "Big Bank", "BB")
    mgr2.deposit("big", "BBD", 5000000)
    mgr2.deposit("big", "JMD", 5000000)
    deep_spread = mgr2.calculate_spread("BBD", "JMD", 1000)

    assert thin_spread > deep_spread