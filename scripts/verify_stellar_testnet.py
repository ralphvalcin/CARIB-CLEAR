#!/usr/bin/env python3
"""
Verify CARIB-CLEAR Stellar testnet integration.

Tests:
  1. Network connection (Horizon root)
  2. HUB account exists and is funded
  3. All participant accounts exist
  4. Account balances
  5. Live adapter initialization (non-mock mode)

Usage:
    python scripts/verify_stellar_testnet.py
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

# Load .env before anything else
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

HORIZON_URL = os.getenv(
    "STELLAR_HORIZON_URL",
    "https://horizon-testnet.stellar.org",
)
SECRETS_FILE = Path(__file__).resolve().parent.parent / "secrets" / "stellar-testnet.json"


def load_accounts() -> dict:
    if SECRETS_FILE.exists():
        return json.loads(SECRETS_FILE.read_text())
    return {}


async def verify() -> int:
    from stellar_sdk import Server, Keypair

    server = Server(HORIZON_URL)
    accounts = load_accounts()
    errors = 0

    # ── 1. Network Health ────────────────────────────────────────────
    logger.info("\n🌐 Stellar Testnet Connection")
    logger.info("━" * 40)
    root = server.root().call()
    logger.info("  Horizon:  %s", root.get("horizon_version", "?")[:40])
    logger.info("  Core:     %s", root.get("core_version", "?")[:40])
    logger.info("  Network:  %s", root.get("network_passphrase", "?"))
    logger.info("  Ledger:   %s", root.get("history_latest_ledger", "?"))
    logger.info("  ✅ Network OK")

    # ── 2. Account Verification ──────────────────────────────────────
    if not accounts:
        logger.warning("\n⚠️  No accounts found. Run bootstrap_stellar_testnet.py first.")
        return 1

    logger.info("\n📋 Account Verification")
    logger.info("━" * 40)
    logger.info("%-18s %-14s %-12s %s", "Name", "Public Key", "Balance", "Exists")
    logger.info("-" * 60)

    for name in sorted(accounts.keys()):
        info = accounts[name]
        pk = info["public_key"]
        try:
            account = server.accounts().account_id(pk).call()
            balance_str = account["balances"][0]["balance"]
            exists = "✅"
        except Exception:
            balance_str = "—"
            exists = "❌"
            errors += 1

        logger.info(
            "%-18s %-14s %-12s %s",
            name,
            pk[:12] + "...",
            f"{float(balance_str):,.0f} XLM",
            exists,
        )

    # ── 3. Live Adapter Init (non-mock) ──────────────────────────────
    logger.info("\n🔌 Live StellarAdapter Initialization")
    logger.info("━" * 40)

    from carib_clear.broker.stellar_adapter import StellarAdapter

    adapter = StellarAdapter({"mock_mode": False})
    ok = adapter.initialize()
    if adapter.health_check():
        logger.info("  ✅ Adapter initialized and healthy")
        logger.info("  ✅ Horizon REST: %s", adapter.horizon_url[:50])
    else:
        logger.warning("  ⚠️  Adapter init returned: %s", ok)
        errors += 1

    # ── 4. Quote (live from adapter) ─────────────────────────────────
    logger.info("\n💱 Live Quote (BBD→JMD via USDC bridge)")
    logger.info("━" * 40)

    quote = adapter.get_quote("BBD", "JMD", 50000)
    if quote:
        logger.info("  Rate:   %.4f", quote["rate"])
        logger.info("  Fee:    %.1f bps", quote["fees_bps"])
        logger.info("  Time:   %ds", quote["estimated_time_seconds"])
        logger.info("  Path:   %s", " → ".join(quote.get("path", [])))
        logger.info("  ✅ Quote available")
    else:
        logger.warning("  ⚠️  No quote (expected in mock mode for direct pairs)")
        logger.info("  ℹ️  Direct BBD→JMD pairs need AMM liquidity")

    # ── Summary ──────────────────────────────────────────────────────
    status = "❌" if errors else "✅"
    logger.info("\n%s Verification Complete: %d errors", status, errors)
    return errors


if __name__ == "__main__":
    import asyncio
    sys.exit(asyncio.run(verify()))
