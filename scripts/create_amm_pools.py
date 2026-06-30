#!/usr/bin/env python3
"""Create AMM liquidity pools on Stellar testnet for CARIB-CLEAR.

Creates BBD/USDC, JMD/USDC, TTD/USDC, XCD/USDC, HTG/USDC pools
on the Stellar DEX using the HUB account's balances.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from dotenv import load_dotenv
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

from stellar_sdk import Server, Keypair, Asset, TransactionBuilder, LiquidityPoolAsset
from stellar_sdk.exceptions import BadRequestError

HORIZON_URL = os.getenv("STELLAR_HORIZON_URL", "https://horizon-testnet.stellar.org")
NETWORK_PASSPHRASE = "Test SDF Network ; September 2015"
SCRIPT_DIR=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SECRETS_DIR = os.path.join(SCRIPT_DIR, "secrets")
SECRETS_FILE = Path(os.path.join(SECRETS_DIR, "stellar-testnet.json"))

USDC = Asset("USDC", "GCO4O4WT6ZJV7MXXSQPH4INW54XP2LRWPQBMHF4JS6BHNVW3FPUYO6AG")

POOLS = [
    ("BBD/USDC", "BBD_ISSUER", "50000",  "25000"),
    ("JMD/USDC", "JMD_ISSUER", "5000000","32500"),
    ("TTD/USDC", "TTD_ISSUER", "250000", "37500"),
    ("XCD/USDC", "XCD_ISSUER", "100000", "37000"),
    ("HTG/USDC", "HTG_ISSUER", "5000000","38500"),
]


def load_accounts() -> Dict[str, Any]:
    if not SECRETS_FILE.exists():
        logger.error("Secrets file not found.")
        sys.exit(1)
    return json.loads(SECRETS_FILE.read_text())


def find_pool_id(server, asset_a, asset_b) -> Optional[str]:
    try:
        assets = sorted([asset_a, asset_b], key=lambda a: f"{a.type}:{a.code}:{a.issuer}")
        r = server.liquidity_pools().for_assets(assets[0], assets[1]).call()
        recs = r.get("_embedded", {}).get("records", [])
        return recs[0]["id"] if recs else None
    except Exception:
        return None


async def create_pools(dry_run=False, show=False) -> int:
    server = Server(HORIZON_URL)
    accounts = load_accounts()
    errors = created = 0
    hub = accounts.get("HUB")
    if not hub:
        logger.error("HUB account not found"); return 1
    hub_pk, hub_secret = hub["public_key"], hub["secret_key"]
    kp = Keypair.from_secret(hub_secret)

    if show:
        logger.info("\n📋 AMM Pools\n" + "━" * 60)
        for name, issuer_name, _, _ in POOLS:
            iss = accounts.get(issuer_name)
            if not iss: continue
            asset = Asset(name[:3], iss["public_key"])
            pid = find_pool_id(server, asset, USDC)
            logger.info("  %-12s  %s", name, f"✅ ID={pid[:20]}..." if pid else "❌")
        return errors

    logger.info("\n🚀 Creating AMM pools\n" + "━" * 60)

    for name, issuer_name, ccy_amt, usdc_amt in POOLS:
        iss = accounts.get(issuer_name)
        if not iss:
            logger.warning("  ⚠️  No issuer for %s", name); errors += 1; continue
        asset = Asset(name[:3], iss["public_key"])

        if find_pool_id(server, asset, USDC):
            logger.info("  ⏭️  %-12s exists", name)
            continue
        if dry_run:
            logger.info("  [dry-run] %s", name)
            continue

        try:
            lp_asset = LiquidityPoolAsset(asset, USDC, 30)
            lp_id = lp_asset.liquidity_pool_id

            # Trust pool shares
            acct = server.load_account(kp.public_key)
            tx1 = (TransactionBuilder(source_account=acct, network_passphrase=NETWORK_PASSPHRASE, base_fee=100)
                   .append_change_trust_op(asset=lp_asset, limit="922337203685.4775807").set_timeout(30).build())
            tx1.sign(kp)
            server.submit_transaction(tx1)

            # Deposit
            time.sleep(0.3)
            acct = server.load_account(kp.public_key)
            tx2 = (TransactionBuilder(source_account=acct, network_passphrase=NETWORK_PASSPHRASE, base_fee=100)
                   .append_liquidity_pool_deposit_op(liquidity_pool_id=lp_id,
                       max_amount_a=ccy_amt, max_amount_b=usdc_amt,
                       min_price="0.5", max_price="2.0")
                   .set_timeout(30).build())
            tx2.sign(kp)
            r = server.submit_transaction(tx2)

            if r.get("successful"):
                created += 1
                logger.info("  ✅ %-12s tx=%s...", name, r["hash"][:12])
            else:
                errors += 1
        except BadRequestError as e:
            if "already" in str(e).lower():
                logger.info("  ⏭️  %-12s exists", name)
            else:
                logger.warning("  ⚠️  %-12s %s", name, str(e)[:120])
                errors += 1
        except Exception as e:
            logger.warning("  ⚠️  %-12s %s", name, str(e)[:120])
            errors += 1
        time.sleep(0.5)

    logger.info(f"\n{'━'*60}\n✅ {created} pools created, {errors} errors")
    return errors


def main():
    p = argparse.ArgumentParser(description="Create AMM pools for CARIB-CLEAR")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--show", action="store_true")
    args = p.parse_args()
    sys.exit(asyncio.run(create_pools(dry_run=args.dry_run, show=args.show)))


if __name__ == "__main__":
    main()
