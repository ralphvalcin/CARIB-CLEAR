#!/usr/bin/env python3
"""
CARIB-CLEAR — Stellar Testnet Bootstrap

Creates and funds Stellar testnet accounts for the CARICOM FX Swap Network.

Participants created:
  - HUB: Central settlement account (multi-sig capable)
  - USD_ISSUER: USDC trustline anchor (or uses Circle's actual USDC issuer)
  - BBD_ISSUER: Barbados Dollar token issuer (for self-issued demo)
  - JMD_ISSUER: Jamaica Dollar token issuer
  - TTD_ISSUER: Trinidad & Tobago Dollar token issuer
  - XCD_ISSUER: Eastern Caribbean Dollar token issuer
  - HTG_ISSUER: Haitian Gourde token issuer
  - PARTICIPANTS: Demo participant accounts (BB hotel, JM supplier, etc.)

Usage:
    python scripts/bootstrap_stellar_testnet.py              # Create + fund all
    python scripts/bootstrap_stellar_testnet.py --dry-run    # Show what would be created
    python scripts/bootstrap_stellar_testnet.py --show       # Show existing keys only

Env output written to .env (gitignored) — DO NOT COMMIT.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Load .env before anything else
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# ── Participant Registry ──────────────────────────────────────────────────

PARTICIPANTS: Dict[str, Dict[str, Any]] = {
    # Network operations
    "HUB": {
        "role": "hub",
        "description": "CARIB-CLEAR central settlement hub",
    },
    "USDC_ISSUER": {
        "role": "issuer",
        "description": "USDC trustline for demo (or Circle's real issuer)",
    },
    # CARICOM currency issuers (for self-issued token demo)
    "BBD_ISSUER": {
        "role": "issuer",
        "currency": "BBD",
        "description": "Barbados Dollar token issuer",
    },
    "JMD_ISSUER": {
        "role": "issuer",
        "currency": "JMD",
        "description": "Jamaica Dollar token issuer",
    },
    "TTD_ISSUER": {
        "role": "issuer",
        "currency": "TTD",
        "description": "Trinidad & Tobago Dollar token issuer",
    },
    "XCD_ISSUER": {
        "role": "issuer",
        "currency": "XCD",
        "description": "Eastern Caribbean Dollar token issuer",
    },
    "HTG_ISSUER": {
        "role": "issuer",
        "currency": "HTG",
        "description": "Haitian Gourde token issuer",
    },
    # Demo participants
    "BB_HOTEL": {
        "role": "participant",
        "jurisdiction": "BB",
        "currency": "BBD",
        "description": "Barbados Grand Hotel (BBD holder)",
    },
    "JM_SUPPLIER": {
        "role": "participant",
        "jurisdiction": "JM",
        "currency": "JMD",
        "description": "Jamaica Food Exports (JMD holder)",
    },
    "TT_ENERGY": {
        "role": "participant",
        "jurisdiction": "TT",
        "currency": "TTD",
        "description": "Trinidad Energy Supply (TTD holder)",
    },
    "HT_ARTISAN": {
        "role": "participant",
        "jurisdiction": "HT",
        "currency": "HTG",
        "description": "Atelier Kreyol Artisans (HTG holder)",
    },
}

HORIZON_TESTNET = "https://horizon-testnet.stellar.org"
NETWORK_PASSPHRASE = "Test SDF Network ; September 2015"
FRIENDBOT_URL = "https://friendbot.stellar.org"
SECRETS_DIR = Path(__file__).resolve().parent.parent / "secrets"
SECRETS_FILE = SECRETS_DIR / "stellar-testnet.json"
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def load_existing() -> Dict[str, Any]:
    """Load existing keys if bootstrap was already run."""
    if SECRETS_FILE.exists():
        with open(SECRETS_FILE) as f:
            return json.load(f)
    return {}


def save_accounts(accounts: Dict[str, Any]) -> None:
    """Save accounts to secrets file (gitignored)."""
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    with open(SECRETS_FILE, "w") as f:
        json.dump(accounts, f, indent=2)
    logger.info(f"💾 Saved %d accounts to %s", len(accounts), SECRETS_FILE)


def write_env(accounts: Dict[str, Any]) -> None:
    """Write key env vars to .env file."""
    if not accounts:
        return

    lines = []
    lines.append("# CARIB-CLEAR Stellar Testnet Configuration")
    lines.append(f"STELLAR_HORIZON_URL={HORIZON_TESTNET}")
    lines.append(f"STELLAR_NETWORK_PASSPHRASE={NETWORK_PASSPHRASE}")

    for name, info in accounts.items():
        secret_key = info.get("secret_key", "")
        public_key = info.get("public_key", "")
        if name == "HUB":
            lines.append(f"STELLAR_HUB_SECRET={secret_key}")
            lines.append(f"STELLAR_HUB_PUBLIC={public_key}")
        else:
            lines.append(f"STELLAR_{name}_SECRET={secret_key}")
            lines.append(f"STELLAR_{name}_PUBLIC={public_key}")

    lines.append("")
    # Already-existing keys from this file
    env_text = "\n".join(lines) + "\n"

    # Read existing .env to preserve non-Stellar vars
    existing = ""
    if ENV_FILE.exists():
        existing = ENV_FILE.read_text()

    # Remove old Stellar block if present
    new_lines = []
    in_stellar_block = False
    for line in existing.split("\n"):
        if line.strip().startswith("# CARIB-CLEAR Stellar"):
            in_stellar_block = True
            continue
        if in_stellar_block and line.strip() == "":
            in_stellar_block = False
            continue
        if not in_stellar_block and not line.startswith("STELLAR_"):
            new_lines.append(line)

    # Remove trailing blank lines
    while new_lines and new_lines[-1].strip() == "":
        new_lines.pop()

    if new_lines:
        full_text = "\n".join(new_lines) + "\n\n" + env_text
    else:
        full_text = env_text

    ENV_FILE.write_text(full_text)
    logger.info("🔐 Updated %s with Stellar testnet keys", ENV_FILE)


def add_env(name: str, secret_key: str, public_key: str) -> None:
    """Convenience: write a single keypair to the .env."""
    from carib_clear.broker.stellar_adapter import StellarAdapter
    # Stub if not needed
    pass


async def create_account(
    public_key: str, dry_run: bool = False
) -> bool:
    """Fund an account via Stellar Friendbot (testnet only)."""
    if dry_run:
        logger.info("  [dry-run] Would fund %s via Friendbot", public_key[:8])
        return True

    import httpx

    url = f"{FRIENDBOT_URL}?addr={public_key}"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                logger.info("  ✅ Funded %s... (10,000 XLM)", public_key[:12])
                return True
            elif resp.status_code == 400:
                body = resp.json()
                if "already exists" in body.get("detail", ""):
                    logger.info("  ⚡ Already exists: %s...", public_key[:12])
                    return True
                logger.warning("  ⚠️  Friendbot error for %s...: %s", public_key[:12], body.get("detail", resp.text))
                return False
            else:
                logger.warning("  ⚠️  HTTP %d for %s...: %s", resp.status_code, public_key[:12], resp.text[:100])
                return False
    except Exception as e:
        logger.warning("  ⚠️  Request failed for %s...: %s", public_key[:12], e)
        return False


async def bootstrap(
    dry_run: bool = False,
    show: bool = False,
    regenerate: bool = False,
) -> None:
    """Run the full bootstrap process."""
    from stellar_sdk import Keypair

    existing = load_existing()
    accounts: Dict[str, Any] = {}

    if show:
        if existing:
            logger.info("\n📋 Existing Stellar Testnet Accounts:\n")
            for name, info in sorted(existing.items()):
                funded = "✅" if info.get("funded") else "🟡"
                logger.info(
                    "  %s %-15s  %s...  role=%-12s  %s",
                    funded,
                    name,
                    info.get("public_key", "?")[:12],
                    info.get("role", "?"),
                    info.get("description", ""),
                )
            logger.info(
                "\n📍 Keys stored in: %s", SECRETS_FILE
            )
            logger.info("📍 Env vars in: %s\n", ENV_FILE)
        else:
            logger.info("No existing accounts found. Run without --show to create them.")
        return

    if regenerate:
        logger.info("♻️  Regenerating all keys (existing will be overwritten)...")
    else:
        logger.info("🔄 Checking existing accounts...")

    for name, meta in sorted(PARTICIPANTS.items()):
        # Skip if exists and not regenerating
        if not regenerate and name in existing:
            accounts[name] = existing[name]
            continue

        kp = Keypair.random()
        entry = {
            "role": meta["role"],
            "description": meta.get("description", ""),
            "public_key": kp.public_key,
            "secret_key": kp.secret,
            "funded": False,
        }
        if "currency" in meta:
            entry["currency"] = meta["currency"]
        if "jurisdiction" in meta:
            entry["jurisdiction"] = meta["jurisdiction"]
        accounts[name] = entry

    # Fund all accounts via Friendbot
    total = len(accounts)
    logger.info("\n🚀 Funding %d accounts via Stellar Friendbot...\n", total)

    import asyncio

    # Fund in parallel batches of 5
    batch_size = 5
    names = sorted(accounts.keys())
    for i in range(0, len(names), batch_size):
        batch = names[i : i + batch_size]
        tasks = []
        for name in batch:
            info = accounts[name]
            if info.get("funded"):
                continue
            tasks.append(create_account(info["public_key"], dry_run=dry_run))

        results = await asyncio.gather(*tasks)
        for name, ok in zip(batch, results):
            accounts[name]["funded"] = ok

    # Summary
    funded = sum(1 for a in accounts.values() if a.get("funded"))
    logger.info(
        "\n📊 Bootstrap complete: %d/%d accounts funded\n", funded, total
    )

    if not dry_run:
        save_accounts(accounts)
        write_env(accounts)

    # Print table
    logger.info("%-18s %-14s %-8s %s", "Name", "Public Key", "Status", "Role")
    logger.info("-" * 60)
    for name in sorted(accounts.keys()):
        info = accounts[name]
        pk = info["public_key"][:12] + "..."
        status = "✅" if info.get("funded") else "❌"
        logger.info("%-18s %-14s %-8s %s", name, pk, status, info["role"])


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bootstrap Stellar testnet accounts for CARIB-CLEAR"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be created without funding",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Display existing accounts only",
    )
    parser.add_argument(
        "--regenerate",
        action="store_true",
        help="Regenerate all keys (overwrites existing)",
    )
    args = parser.parse_args()

    import asyncio

    asyncio.run(bootstrap(
        dry_run=args.dry_run,
        show=args.show,
        regenerate=args.regenerate,
    ))


if __name__ == "__main__":
    main()
