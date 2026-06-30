#!/usr/bin/env python3
"""
CARIB-CLEAR — Stellar Testnet Currency Token Issuance (Phase 2, Block 2)

Issues CARICOM currency tokens from issuer accounts to demo participants.
This creates the balances needed for trading on the Stellar DEX.

Issuance plan (USD-equivalent values for demo):
  BBD_ISSUER → BB_HOTEL:     100,000 BBD  (~$50,000 USD)
  JMD_ISSUER → JM_SUPPLIER: 10,000,000 JMD (~$65,000 USD)
  TTD_ISSUER → TT_ENERGY:      500,000 TTD (~$73,500 USD)
  XCD_ISSUER → HUB:            200,000 XCD (~$74,000 USD)
  HTG_ISSUER → HT_ARTISAN:  10,000,000 HTG (~$77,000 USD)

HUB also receives some of each currency to act as market maker.

Usage:
    python scripts/issue_currency_tokens.py              # Full run
    python scripts/issue_currency_tokens.py --dry-run     # Preview only
    python scripts/issue_currency_tokens.py --show        # Show current balances
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

from stellar_sdk import (
    Server, Keypair, Asset, TransactionBuilder,
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


# Issuance plan
# Format: (from_name, to_name, currency, amount, memo)
ISSUANCE_PLAN: List[Tuple[str, str, str, str, str]] = [
    ("BBD_ISSUER", "BB_HOTEL",  "BBD", "100000",     "BBD issuance for BB_HOTEL"),
    ("JMD_ISSUER", "JM_SUPPLIER","JMD", "10000000",   "JMD issuance for JM_SUPPLIER"),
    ("TTD_ISSUER", "TT_ENERGY",  "TTD", "500000",     "TTD issuance for TT_ENERGY"),
    ("XCD_ISSUER", "HUB",        "XCD", "200000",     "XCD issuance for HUB (market maker)"),
    ("HTG_ISSUER", "HT_ARTISAN", "HTG", "10000000",   "HTG issuance for HT_ARTISAN"),
    # HUB also receives some of each currency for market making
    ("BBD_ISSUER", "HUB",  "BBD", "50000",    "BBD for HUB market making"),
    ("JMD_ISSUER", "HUB",  "JMD", "5000000",  "JMD for HUB market making"),
    ("TTD_ISSUER", "HUB",  "TTD", "250000",   "TTD for HUB market making"),
    ("HTG_ISSUER", "HUB",  "HTG", "5000000",  "HTG for HUB market making"),
]


def load_accounts() -> Dict[str, Any]:
    """Load the secrets file."""
    if not SECRETS_FILE.exists():
        logger.error("Secrets file not found. Run bootstrap_stellar_testnet.py first.")
        sys.exit(1)
    return json.loads(SECRETS_FILE.read_text())


def get_balance(server: Server, public_key: str, asset: Asset) -> float:
    """Get balance for a specific asset. Returns 0.0 if no trustline."""
    try:
        account = server.accounts().account_id(public_key).call()
        for balance in account["balances"]:
            if balance.get("asset_type") == "native":
                continue
            if (
                balance.get("asset_code") == asset.code
                and balance.get("asset_issuer") == asset.issuer
            ):
                return float(balance["balance"])
        return 0.0
    except Exception:
        return 0.0


async def issue_tokens(
    dry_run: bool = False,
    show: bool = False,
) -> int:
    """Issue currency tokens per the issuance plan."""
    server = Server(HORIZON_URL)
    accounts = load_accounts()
    errors = 0
    submitted = 0

    if show:
        logger.info("\n📋 Current Token Balances")
        logger.info("━" * 70)
        logger.info("%-18s %-8s %-16s %s", "Account", "Asset", "Balance", "Issuer")
        logger.info("-" * 70)
        seen = set()
        for from_name, to_name, currency, amount, memo in ISSUANCE_PLAN:
            # Show sender balance
            from_info = accounts.get(from_name)
            to_info = accounts.get(to_name)
            if from_info:
                issuer_pk = from_info["public_key"]
                asset = Asset(currency, issuer_pk)
                key = (to_name, currency, issuer_pk)
                if key not in seen:
                    seen.add(key)
                    bal = get_balance(server, to_info["public_key"], asset)
                    logger.info(
                        "%-18s %-8s %-16s %s...",
                        to_name[:18],
                        currency,
                        f"{bal:,.0f}" if bal > 0 else "0",
                        issuer_pk[:12],
                    )
        return errors

    logger.info("\n🚀 Issuing CARICOM currency tokens")
    logger.info("━" * 70)

    for from_name, to_name, currency, amount, memo in ISSUANCE_PLAN:
        from_info = accounts.get(from_name)
        to_info = accounts.get(to_name)

        if not from_info or not to_info:
            logger.warning("  ⚠️  Skipping %s→%s: account not found", from_name, to_name)
            errors += 1
            continue

        issuer_pk = from_info["public_key"]
        from_secret = from_info["secret_key"]
        to_pk = to_info["public_key"]

        asset = Asset(currency, issuer_pk)

        if dry_run:
            logger.info(
                "  [dry-run] %s → %s: %s %s",
                from_name[:14],
                to_name[:14],
                f"{int(float(amount)):,}",
                currency,
            )
            continue

        # Check existing balance
        current_bal = get_balance(server, to_pk, asset)
        if current_bal > 0:
            logger.info(
                "  ⏭️  %-14s → %-14s %s already has %s %s",
                from_name[:14],
                to_name[:14],
                to_name[:10],
                f"{current_bal:,.0f}",
                currency,
            )
            continue

        # Build and submit payment
        try:
            kp = Keypair.from_secret(from_secret)
            account = server.load_account(kp.public_key)

            tx = (
                TransactionBuilder(
                    source_account=account,
                    network_passphrase=NETWORK_PASSPHRASE,
                    base_fee=100,
                )
                .append_payment_op(
                    destination=to_pk,
                    asset=asset,
                    amount=amount,
                )
                .add_text_memo(memo[:28])
                .set_timeout(30)
                .build()
            )
            tx.sign(kp)
            response = server.submit_transaction(tx)

            if response.get("successful"):
                submitted += 1
                logger.info(
                    "  ✅ %-14s → %-14s %s %s  (tx: %s...)",
                    from_name[:14],
                    to_name[:14],
                    f"{int(float(amount)):,}",
                    currency,
                    response["hash"][:12],
                )
            else:
                logger.warning(
                    "  ⚠️  %s→%s TX failed: %s",
                    from_name,
                    to_name,
                    response.get("result_xdr", "unknown")[:50],
                )
                errors += 1

        except Exception as e:
            logger.warning(
                "  ⚠️  %s→%s error: %s",
                from_name,
                to_name,
                str(e)[:80],
            )
            errors += 1

        time.sleep(0.5)

    # Summary
    total = len(ISSUANCE_PLAN)
    logger.info("\n" + "━" * 70)
    if dry_run:
        logger.info("📊 Dry run: %d issuance operations", total)
    else:
        logger.info("📊 Issuance: %d/%d payments submitted", submitted, total - errors)
    status = "❌" if errors else "✅"
    logger.info("%s Issuance complete: %d errors", status, errors)
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Issue CARICOM currency tokens for CARIB-CLEAR"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without submitting")
    parser.add_argument("--show", action="store_true", help="Show current balances")
    args = parser.parse_args()

    import asyncio
    sys.exit(asyncio.run(issue_tokens(
        dry_run=args.dry_run,
        show=args.show,
    )))


if __name__ == "__main__":
    main()
