"""Integration tests against live Stellar testnet.

Run with:  STELLAR_INTEGRATION_TEST=1 pytest tests/ -v -m integration
Skip/basic: pytest tests/ -v                           (skips these)

Uses the bootstrap secrets file to connect to real testnet accounts.
These tests execute actual Stellar DEX operations with small amounts.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

# Skip all tests in this file unless STELLAR_INTEGRATION_TEST=1
if not os.getenv("STELLAR_INTEGRATION_TEST"):
    pytest.skip("Set STELLAR_INTEGRATION_TEST=1 to run integration tests", allow_module_level=True)

# ── Test imports (only if running integration) ──────────────────────────

from stellar_sdk import (
    Server, Keypair, Asset, TransactionBuilder, LiquidityPoolAsset,
)
from stellar_sdk.exceptions import BadRequestError

from carib_clear.broker.stellar_adapter import StellarAdapter
from carib_clear.broker.base import SettlementOrder

SECRETS_FILE = Path(__file__).resolve().parent.parent / "secrets" / "stellar-testnet.json"
HORIZON = "https://horizon-testnet.stellar.org"
NETWORK = "Test SDF Network ; September 2015"
USDC_ISSUER = "GCO4O4WT6ZJV7MXXSQPH4INW54XP2LRWPQBMHF4JS6BHNVW3FPUYO6AG"


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def secrets():
    return json.loads(SECRETS_FILE.read_text())


@pytest.fixture(scope="module")
def server():
    return Server(HORIZON)


@pytest.fixture(scope="module")
def usdc():
    return Asset("USDC", USDC_ISSUER)


@pytest.fixture(scope="module")
def hub_kp(secrets):
    return Keypair.from_secret(secrets["HUB"]["secret_key"])


# ─── Trustline Tests ────────────────────────────────────────────────────


def test_hub_has_usdc_trustline(server, secrets, usdc):
    """Verify HUB has a USDC trustline with balance."""
    account = server.accounts().account_id(secrets["HUB"]["public_key"]).call()
    has_usdc = any(
        b.get("asset_code") == "USDC" and b.get("asset_issuer") == USDC_ISSUER
        for b in account["balances"]
    )
    assert has_usdc, "HUB missing USDC trustline"


def test_bb_hotel_has_bbd_trustline(server, secrets):
    """Verify BB_HOTEL has a BBD trustline."""
    bbd = Asset("BBD", secrets["BBD_ISSUER"]["public_key"])
    account = server.accounts().account_id(secrets["BB_HOTEL"]["public_key"]).call()
    has_bbd = any(
        b.get("asset_code") == "BBD" and b.get("asset_issuer") == bbd.issuer
        for b in account["balances"]
    )
    assert has_bbd, "BB_HOTEL missing BBD trustline"


def test_all_participants_have_trustlines(server, secrets):
    """Verify all 10 non-hub accounts have their currency + USDC."""
    required = {
        "BB_HOTEL": "BBD", "JM_SUPPLIER": "JMD",
        "TT_ENERGY": "TTD", "HT_ARTISAN": "HTG",
    }
    for account_name, expected_currency in required.items():
        pk = secrets[account_name]["public_key"]
        account = server.accounts().account_id(pk).call()
        codes = {b.get("asset_code") for b in account["balances"] if b.get("asset_type") != "native"}
        assert "USDC" in codes, f"{account_name} missing USDC trustline"
        assert expected_currency in codes, f"{account_name} missing {expected_currency} trustline"


# ─── AMM Pool Tests ──────────────────────────────────────────────────────


def test_bbd_usdc_pool_exists(server, secrets, usdc):
    """Verify BBD/USDC AMM pool has liquidity."""
    bbd = Asset("BBD", secrets["BBD_ISSUER"]["public_key"])
    pool = LiquidityPoolAsset(bbd, usdc, 30)
    r = server.liquidity_pools().liquidity_pool(pool.liquidity_pool_id).call()
    assert len(r["reserves"]) == 2
    total = sum(float(res["amount"]) for res in r["reserves"])
    assert total > 0, "BBD/USDC pool has no liquidity"


def test_all_amm_pools_have_liquidity(server, secrets, usdc):
    """Verify all 5 AMM pools have non-zero reserves."""
    for currency, issuer_name in [("BBD","BBD_ISSUER"),("JMD","JMD_ISSUER"),
                                   ("TTD","TTD_ISSUER"),("XCD","XCD_ISSUER"),("HTG","HTG_ISSUER")]:
        asset = Asset(currency, secrets[issuer_name]["public_key"])
        try:
            pool = LiquidityPoolAsset(asset, usdc, 30)
        except ValueError:
            # Reversed order for XCD (X > U)
            pool = LiquidityPoolAsset(usdc, asset, 30)
        r = server.liquidity_pools().liquidity_pool(pool.liquidity_pool_id).call()
        total = sum(float(res["amount"]) for res in r["reserves"])
        assert total > 0, f"{currency}/USDC pool has no liquidity"


# ─── Path Payment Tests ──────────────────────────────────────────────────


def test_live_path_payment_bbd_to_jmd(server, secrets, usdc):
    """Execute a small BBD→JMD path payment on testnet.

    BB_HOTEL sends 10 BBD, JM_SUPPLIER receives JMD via USDC bridge.
    Amount is kept small (<$10) to avoid draining demo balances.
    """
    bb_hotel = secrets["BB_HOTEL"]
    jm_supplier = secrets["JM_SUPPLIER"]
    kp = Keypair.from_secret(bb_hotel["secret_key"])
    bbd = Asset("BBD", secrets["BBD_ISSUER"]["public_key"])
    jmd = Asset("JMD", secrets["JMD_ISSUER"]["public_key"])

    # Check pre-balances
    pre_jm = _get_balance(server, jm_supplier["public_key"], jmd)

    # Execute path payment: 10 BBD → JMD via USDC
    account = server.load_account(kp.public_key)
    tx = (
        TransactionBuilder(source_account=account, network_passphrase=NETWORK, base_fee=100)
        .append_path_payment_strict_receive_op(
            destination=jm_supplier["public_key"],
            send_asset=bbd,
            send_max="12",
            dest_asset=jmd,
            dest_amount="765",  # ~$10 worth of JMD
            path=[usdc],
        )
        .add_text_memo("CARIB-CLEAR:integ-test")
        .set_timeout(30)
        .build()
    )
    tx.sign(kp)
    response = server.submit_transaction(tx)

    assert response.get("successful"), f"Path payment failed: {response}"

    # Verify JM_SUPPLIER received JMD
    post_jm = _get_balance(server, jm_supplier["public_key"], jmd)
    assert post_jm > pre_jm, f"JMD balance did not increase: {pre_jm} → {post_jm}"


def test_live_adapter_path_payment():
    """Verify StellarAdapter handles a live path payment correctly."""
    adapter = StellarAdapter({"mock_mode": False})
    adapter.initialize()

    order = SettlementOrder(
        order_id="integ-live-001",
        from_currency="BBD", to_currency="JMD",
        amount_from=10, amount_to=765, rate=76.5,
        rail="stellar_usdc",
        counterparty_id="JM_SUPPLIER",
        jurisdiction="JM",
        metadata={"source": "BB_HOTEL", "destination": "JM_SUPPLIER",
                  "send_max": "15"},  # Override slippage for small amounts
    )
    result = adapter.submit_settlement(order)

    assert result.success, f"Adapter path payment failed: {result.error_message}"
    assert result.status == "filled"
    assert result.tx_hash is not None
    assert result.settlement_time_seconds < 30


# ─── Quote Tests ─────────────────────────────────────────────────────────


def test_adapter_live_quote():
    """Verify StellarAdapter returns a live quote from testnet."""
    adapter = StellarAdapter({"mock_mode": False})
    adapter.initialize()

    quote = adapter.get_quote("BBD", "JMD", 1000)
    assert quote is not None
    assert quote["rate"] > 0
    assert quote["mode"] == "estimated"
    assert quote.get("fees_bps", 0) > 0


def test_live_quote_unsupported_pair():
    """Verify unsupported pair returns None."""
    adapter = StellarAdapter({"mock_mode": False})
    quote = adapter.get_quote("EUR", "JPY", 1000)
    assert quote is None


# ─── Helpers ─────────────────────────────────────────────────────────────


def _get_balance(server, public_key, asset) -> float:
    try:
        account = server.accounts().account_id(public_key).call()
        for b in account["balances"]:
            if b.get("asset_type") == "native":
                continue
            if b.get("asset_code") == asset.code and b.get("asset_issuer") == asset.issuer:
                return float(b["balance"])
        return 0.0
    except Exception:
        return 0.0
