#!/usr/bin/env python3
"""
CARIB-CLEAR — Stellar Testnet Trustline Setup (Phase 2, Block 1)

Establishes USDC trustlines and local currency trustlines for all
11 testnet accounts. Idempotent — skips accounts that already have
the required trustlines.

Usage:
    python scripts/setup_trustlines.py                    # Full run
    python scripts/setup_trustlines.py --dry-run           # Preview only
    python scripts/setup_trustlines.py --show              # Show current state
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

from stellar_sdk import (
    Server, Keypair, Asset, TransactionBuilder, Network,
)
from stellar_sdk.exceptions import NotFoundError, BadRequestError

from decimal import Decimal

HORIZON_URL = os.getenv("STELLAR_HORIZON_URL", "https://horizon-testnet.stellar.org")
NETWORK_PASSPHRASE = os.getenv(
    "STELLAR_NETWORK_PASSPHRASE",
    "Test SDF Network ; September 2015",
)
SECRETS_DIR = Path(__file__).resolve().parent.parent / "secrets"
SECRETS_FILE = SECRETS_DIR / "stellar-testnet.json"


# Trustline configuration
# Each account type needs trustlines for specific assets.
# Format: { "account_name": [("currency_code", "issuer_env_var"), ...] }
TRUSTLINES: Dict[str, List[tuple]] = {
    "HUB": [
        ("USDC", "STELLAR_USDC_ISSUER_PUBLIC"),
        ("BBD", "STELLAR_BBD_ISSUER_PUBLIC"),
        ("JMD", "STELLAR_JMD_ISSUER_PUBLIC"),
        ("TTD", "STELLAR_TTD_ISSUER_PUBLIC"),
        ("XCD", "STELLAR_XCD_ISSUER_PUBLIC"),
        ("HTG", "STELLAR_HTG_ISSUER_PUBLIC"),
    ],
    "USDC_ISSUER": [
        ("USDC", "STELLAR_USDC_ISSUER_PUBLIC"),
    ],
    "BBD_ISSUER": [
        ("USDC", "STELLAR_USDC_ISSUER_PUBLIC"),
        ("BBD", "STELLAR_BBD_ISSUER_PUBLIC"),
    ],
    "JMD_ISSUER": [
        ("USDC", "STELLAR_USDC_ISSUER_PUBLIC"),
        ("JMD", "STELLAR_JMD_ISSUER_PUBLIC"),
    ],
    "TTD_ISSUER": [
        ("USDC", "STELLAR_USDC_ISSUER_PUBLIC"),
        ("TTD", "STELLAR_TTD_ISSUER_PUBLIC"),
    ],
    "XCD_ISSUER": [
        ("USDC", "STELLAR_USDC_ISSUER_PUBLIC"),
        ("XCD", "STELLAR_XCD_ISSUER_PUBLIC"),
    ],
    "HTG_ISSUER": [
        ("USDC", "STELLAR_USDC_ISSUER_PUBLIC"),
        ("HTG", "STELLAR_HTG_ISSUER_PUBLIC"),
    ],
    "BB_HOTEL": [
        ("USDC", "STELLAR_USDC_ISSUER_PUBLIC"),
        ("BBD", "STELLAR_BBD_ISSUER_PUBLIC"),
    ],
    "JM_SUPPLIER": [
        ("USDC", "STELLAR_USDC_ISSUER_PUBLIC"),
        ("JMD", "STELLAR_JMD_ISSUER_PUBLIC"),
    ],
    "TT_ENERGY": [
        ("USDC", "STELLAR_USDC_ISSUER_PUBLIC"),
        ("TTD", "STELLAR_TTD_ISSUER_PUBLIC"),
    ],
    "HT_ARTISAN": [
        ("USDC", "STELLAR_USDC_ISSUER_PUBLIC"),
        ("HTG", "STELLAR_HTG_ISSUER_PUBLIC"),
    ],
}

# Maximum trustline limit (max int64 in stroops = 922337203685.4775807)
TRUST_LIMIT = "922337203685.4775807"


def load_accounts() -> Dict[str, Any]:
    """Load the secrets file."""
    if not SECRETS_FILE.exists():
        logger.error("Secrets file not found. Run bootstrap_stellar_testnet.py first.")
        sys.exit(1)
    return json.loads(SECRETS_FILE.read_text())


def resolve_asset(code: str, issuer_env_var: str) -> Optional[Asset]:
    """Resolve an Asset from env var or fallback issuer key."""
    issuer_pk = os.getenv(issuer_env_var)
    if not issuer_pk:
        # Fallback to the secret key's public key from secrets file
        accounts = load_accounts()
        for name, info in accounts.items():
            if code in name:  # e.g. BBD_ISSUER → BBD
                issuer_pk = info["public_key"]
                break
    if not issuer_pk:
        logger.error(f"Cannot resolve issuer for {code} ({issuer_env_var})")
        return None
    return Asset(code, issuer_pk)


def has_trustline(server: Server, public_key: str, asset: Asset) -> bool:
    """Check if an account already has a trustline for the given asset."""
    try:
        account = server.accounts().account_id(public_key).call()
        for balance in account["balances"]:
            if balance.get("asset_type") == "native":
                continue
            bal_asset_code = balance.get("asset_code", "")
            bal_asset_issuer = balance.get("asset_issuer", "")
            if bal_asset_code == asset.code and bal_asset_issuer == asset.issuer:
                return True
        return False
    except Exception:
        return False


async def setup_trustlines(
    dry_run: bool = False,
    show: bool = False,
) -> int:
    """Set up trustlines for all accounts."""
    from stellar_sdk import Server, Keypair, TransactionBuilder

    server = Server(HORIZON_URL)
    accounts = load_accounts()
    errors = 0
    total_ops = 0
    submitted_ops = 0

    if show:
        logger.info("\n📋 Current Trustline Status")
        logger.info("━" * 60)
        logger.info("%-18s %-14s %s", "Account", "Asset", "Trustline")
        logger.info("-" * 60)
        for name, info in sorted(accounts.items()):
            pk = info["public_key"]
            assets_to_check = TRUSTLINES.get(name, [])
            for code, env_var in assets_to_check:
                asset = resolve_asset(code, env_var)
                if not asset:
                    continue
                exists = has_trustline(server, pk, asset)
                status = "✅" if exists else "❌"
                logger.info("%-18s %-14s %s", name[:18], f"{code}:{asset.issuer[:8]}", status)
        return errors

    logger.info("\n🚀 Setting up trustlines on Stellar testnet")
    logger.info("━" * 60)

    for name in sorted(accounts.keys()):
        info = accounts[name]
        pk = info["public_key"]
        secret = info["secret_key"]
        assets_to_add = TRUSTLINES.get(name, [])

        if not assets_to_add:
            continue

        kp = Keypair.from_secret(secret)
        needed_assets = []

        for code, env_var in assets_to_add:
            asset = resolve_asset(code, env_var)
            if not asset:
                errors += 1
                continue

            # Skip self-trustlines (issuer always trusts own asset)
            if asset.issuer == pk:
                logger.info("  ⏭️  %-16s skips self-trust for %s (issuer owns it)", name[:16], code)
                continue

            if has_trustline(server, pk, asset):
                logger.info("  ⏭️  %-16s already trusts %s", name[:16], code)
                continue

            needed_assets.append(asset)

        if not needed_assets:
            continue

        total_ops += len(needed_assets)

        if dry_run:
            logger.info(
                "  [dry-run] %-16s would add %d trustlines: %s",
                name[:16],
                len(needed_assets),
                ", ".join(a.code for a in needed_assets),
            )
            continue

        # Build and submit the transaction
        try:
            account = server.load_account(kp.public_key)

            builder = TransactionBuilder(
                source_account=account,
                network_passphrase=NETWORK_PASSPHRASE,
                base_fee=100,
            )

            for asset in needed_assets:
                builder.append_change_trust_op(asset=asset, limit=TRUST_LIMIT)

            tx = builder.set_timeout(30).build()
            tx.sign(kp)

            response = server.submit_transaction(tx)

            if response.get("successful"):
                submitted_ops += len(needed_assets)
                logger.info(
                    "  ✅ %-16s trusts %s  (tx: %s...)",
                    name[:16],
                    ", ".join(a.code for a in needed_assets),
                    response["hash"][:12],
                )
            else:
                logger.warning(
                    "  ⚠️  %-16s trustline TX failed: %s",
                    name[:16],
                    response.get("result_xdr", "unknown")[:60],
                )
                errors += 1

        except Exception as e:
            logger.warning("  ⚠️  %-16s error: %s", name[:16], str(e)[:80])
            errors += 1

        # Small delay between transactions to avoid rate limiting
        time.sleep(0.5)

    # Summary
    logger.info("\n" + "━" * 60)
    if dry_run:
        logger.info("📊 Dry run: %d trustline operations would be submitted", total_ops)
    else:
        logger.info(
            "📊 Trustlines: %d/%d operations submitted successfully",
            submitted_ops,
            total_ops,
        )
    status = "❌" if errors else "✅"
    logger.info("%s Setup complete: %d errors", status, errors)
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Set up Stellar testnet trustlines for CARIB-CLEAR"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without submitting")
    parser.add_argument("--show", action="store_true", help="Show current trustline status")
    args = parser.parse_args()

    import asyncio
    sys.exit(asyncio.run(setup_trustlines(
        dry_run=args.dry_run,
        show=args.show,
    )))


if __name__ == "__main__":
    main()
