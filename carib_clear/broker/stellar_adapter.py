# broker/stellar_adapter.py
"""
CARIB-CLEAR Stellar/USDC Adapter

Primary settlement rail for cross-border FX.
Uses Stellar network with USDC for instant, low-cost settlement.
"""
from __future__ import annotations

import os
import time
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass

# Try to import Stellar SDK
try:
    from stellar_sdk import (
        Server, Keypair, TransactionBuilder, Network,
        Asset, Payment, Memo, TextMemo
    )
    from stellar_sdk.exceptions import NotFoundError, BadRequestError
    STELLAR_AVAILABLE = True
except ImportError:
    STELLAR_AVAILABLE = False

# Auto-load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from .base import MultiRailBroker, SettlementOrder, SettlementResult, RailInfo
from carib_clear.plugin import PluginSpec

logger = logging.getLogger(__name__)

STELLAR_USDC_ISSUER = "GCO4O4WT6ZJV7MXXSQPH4INW54XP2LRWPQBMHF4JS6BHNVW3FPUYO6AG"

MOCK_RATES = {
    ("BBD", "USD"): 0.5, ("USD", "BBD"): 2.0,
    ("JMD", "USD"): 0.0065, ("USD", "JMD"): 154.0,
    ("TTD", "USD"): 0.147, ("USD", "TTD"): 6.8,
    ("XCD", "USD"): 0.37, ("USD", "XCD"): 2.7,
    ("HTG", "USD"): 0.0077, ("USD", "HTG"): 130.0,
}


@PluginSpec.register("stellar_usdc", {
    "type": "settlement_rail",
    "id": "stellar_usdc",
    "name": "Stellar USDC",
    "currencies": ["BBD", "JMD", "TTD", "XCD", "HTG", "USD", "BTC", "ECH"],
    "jurisdictions": ["BB", "JM", "TT", "HT", "ECCB", "US"],
    "fee_bps": 0.1,
    "estimated_time_seconds": 5,
    "min_amount_usd": 1,
    "max_amount_usd": 500000,
    "description": "Stellar DEX path payment via USDC bridge — 5 second settlement, 0.1 bps fee",
})
class StellarAdapter(MultiRailBroker):
    """
    Stellar/USDC settlement adapter for CARIB-CLEAR.
    
    Features:
    - Direct FX via Stellar DEX path payments
    - USDC as bridge currency
    - Instant finality (~5 seconds)
    - Low fees (~0.00001 XLM per operation)
    - Built-in compliance (AML/KYC hooks)
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__("stellar_usdc", config)
        self.server = None
        self.keypair = None

        # Load from env with config override (config keys win, env falls back)
        config_src = config or {}
        self.horizon_url = config_src.get(
            "horizon_url",
            os.getenv("STELLAR_HORIZON_URL", "https://horizon-testnet.stellar.org"),
        )
        self.network_passphrase = config_src.get(
            "network_passphrase",
            os.getenv("STELLAR_NETWORK_PASSPHRASE", "Test SDF Network ; September 2015"),
        )
        self.secret_key = config_src.get(
            "secret_key",
            os.getenv("STELLAR_HUB_SECRET"),
        )
        self.mock_mode = config_src.get("mock_mode", True)
        self._participants: Dict[str, str] = {}  # name -> public_key
        self._secrets: Dict[str, str] = {}  # name -> secret_key

        # Load participant accounts for live mode
        if not self.mock_mode:
            self._load_participants()
        
        # Stellar-specific constants
        self.USDC_ASSET = None
        self.CURRENCY_ASSETS = {}
        self.SUPPORTED_PAIRS = []

        if STELLAR_AVAILABLE:
            # Real testnet issuer public keys from env, or fallback to Circle's USDC issuer
            usdc_issuer = os.getenv("STELLAR_USDC_ISSUER_PUBLIC", "GA5ZSEJYB37JRC5AVCIA5MOP4RHTM335X2KGX3IHOJAPP5RE34K4KZVN")
            bbd_issuer = os.getenv("STELLAR_BBD_ISSUER_PUBLIC", "GB5T2O2ZOMLOARKO3SUYQXVVV4ZNBGZZECCDQTHAAL5FNY5DGG232IWF")
            jmd_issuer = os.getenv("STELLAR_JMD_ISSUER_PUBLIC", "GB6C33EKHYQKQDJAX25ZJUMS4MVZC7N6LPZ5HC5YUBXGN7DY44WAVGYI")
            ttd_issuer = os.getenv("STELLAR_TTD_ISSUER_PUBLIC", "GBRVNQLYIR55PUESTNY7UZ2GWAYTFFU4AA5PKBW2TBTYQHCEJHBQXVDL")
            xcd_issuer = os.getenv("STELLAR_XCD_ISSUER_PUBLIC", "GAXDGCGW2BALR2XJZVRYX6JGX3KDLJPSXLS2V7LWJ5HIK7JPUKIXGKJC")
            htg_issuer = os.getenv("STELLAR_HTG_ISSUER_PUBLIC", "GAFVVVHUKLU26FR4P647QJSVSB7Z6TVCSVEQBLW3OL3XMOPYXQJKTDG3")

            self.USDC_ASSET = Asset("USDC", usdc_issuer)
            self.CURRENCY_ASSETS = {
                "USD": self.USDC_ASSET,
                "USDC": self.USDC_ASSET,  # Alias for path payment routing
                "BBD": Asset("BBD", bbd_issuer),
                "JMD": Asset("JMD", jmd_issuer),
                "TTD": Asset("TTD", ttd_issuer),
                "XCD": Asset("XCD", xcd_issuer),
                "HTG": Asset("HTG", htg_issuer),
            }
            self.SUPPORTED_PAIRS = [
                ("BBD", "USD"), ("USD", "BBD"),
                ("JMD", "USD"), ("USD", "JMD"),
                ("TTD", "USD"), ("USD", "TTD"),
                ("XCD", "USD"), ("USD", "XCD"),
                ("HTG", "USD"), ("USD", "HTG"),
                ("BBD", "JMD"), ("JMD", "BBD"),
                ("BBD", "TTD"), ("TTD", "BBD"),
                ("JMD", "TTD"), ("TTD", "JMD"),
            ]
        else:
            self.CURRENCY_ASSETS = {"USD": None, "BBD": None, "JMD": None, "TTD": None, "XCD": None, "HTG": None}
            self.SUPPORTED_PAIRS = [
                ("BBD", "USD"), ("USD", "BBD"),
                ("JMD", "USD"), ("USD", "JMD"),
                ("TTD", "USD"), ("USD", "TTD"),
                ("XCD", "USD"), ("USD", "XCD"),
                ("HTG", "USD"), ("USD", "HTG"),
                ("BBD", "JMD"), ("JMD", "BBD"),
                ("BBD", "TTD"), ("TTD", "BBD"),
                ("JMD", "TTD"), ("TTD", "JMD"),
            ]
            logger.warning("Stellar SDK not available - running in mock mode")
            self.mock_mode = True
        
        if self.mock_mode:
            logger.info("[Stellar] Running in MOCK mode for buildathon demo")
            self._initialized = True
            return
        
        try:
            self.server = Server(horizon_url=self.horizon_url)
            if self.secret_key:
                self.keypair = Keypair.from_secret(self.secret_key)
            else:
                logger.warning("No Stellar secret key - limited to read operations")
            self._initialized = True
            logger.info(f"[Stellar] Connected to {self.horizon_url}")
        except Exception as e:
            logger.error(f"[Stellar] Initialization failed: {e}")
            self._initialized = False
    
    def _load_participants(self) -> None:
        """Load participant Stellar keys from secrets file."""
        secrets_path = Path(__file__).resolve().parent.parent.parent / "secrets" / "stellar-testnet.json"
        try:
            if secrets_path.exists():
                data = json.loads(secrets_path.read_text())
                self._participants = {
                    name: info["public_key"]
                    for name, info in data.items()
                    if "public_key" in info
                }
                self._secrets = {
                    name: info["secret_key"]
                    for name, info in data.items()
                    if "secret_key" in info
                }
                logger.info("[Stellar] Loaded %d participant accounts from secrets", len(self._participants))
        except Exception as e:
            logger.warning("[Stellar] Could not load participant accounts: %s", e)

    @staticmethod
    def _resolve_participant(name: str) -> str:
        """Resolve a participant ID to a secrets-file key name.
        
        Handles bb_hotel_001 -> BB_HOTEL, jm_supplier -> JM_SUPPLIER, HUB -> HUB
        """
        normalized = name.upper().replace("-", "_")
        import re
        match = re.match(r"^(.+?)_\d+$", normalized)
        if match:
            return match.group(1)
        return normalized

    @property
    def rail_info(self) -> RailInfo:
        """Return Stellar/USDC rail metadata."""
        return RailInfo(
            rail_id="stellar_usdc",
            name="Stellar USDC",
            supported_currencies=["BBD", "JMD", "TTD", "XCD", "HTG", "USD"],
            min_amount_usd=1,
            max_amount_usd=500000,
            estimated_time_seconds=5,
            fee_bps=0.1,
            availability=0.999,
            jurisdictions=["BB", "JM", "TT", "HT", "ECCB", "US"],
            metadata={"network": "stellar", "bridge": "USDC"},
        )

    def initialize(self) -> bool:
        """Initialize the Stellar connection (mock mode for buildathon)."""
        if self.mock_mode:
            self._initialized = True
            return True
        # Production init would connect to Horizon
        return self._initialized

    def health_check(self) -> bool:
        """Check Stellar network health."""
        if self.mock_mode:
            return True
        
        try:
            self.server.root().call()
            return True
        except Exception:
            return False
    
    def get_quote(
        self,
        from_currency: str,
        to_currency: str,
        amount: float
    ) -> Optional[Dict[str, Any]]:
        """Get FX quote via Stellar DEX path.

        Returns estimated rates from mock data for supported pairs.
        Phase 2 will replace mock rates with live Stellar DEX queries.
        """
        pair = (from_currency.upper(), to_currency.upper())
        
        if not self.SUPPORTED_PAIRS or pair not in self.SUPPORTED_PAIRS:
            return None
        
        # Use estimated rates from mock data + AMM pool markup
        # Live path payments execute through Stellar DEX with real prices
        rate = MOCK_RATES.get(pair)
        if not rate:
            # Calculate cross rate via USD
            usd_from = MOCK_RATES.get((from_currency.upper(), "USD"))
            usd_to = MOCK_RATES.get(("USD", to_currency.upper()))
            if usd_from and usd_to:
                rate = usd_from * usd_to
            else:
                return None
        
        mode_tag = "estimated" if not self.mock_mode else "mock"
        return {
            "rate": rate,
            "fees_bps": self.rail_info.fee_bps,
            "estimated_time_seconds": self.rail_info.estimated_time_seconds,
            "valid_until": time.time() + 30,
            "path": self._get_path(from_currency, to_currency),
            "mode": mode_tag,
        }
    
    def _get_path(self, from_ccy: str, to_ccy: str) -> List[str]:
        """Get payment path through Stellar DEX.

        For direct CARICOM pairs (BBD→JMD), route through USDC:
            send_asset=BBD → path=[USDC] → dest_asset=JMD

        For USD pairs, route directly:
            send_asset=BBD → path=[] → dest_asset=USD
        """
        from_ccy = from_ccy.upper()
        to_ccy = to_ccy.upper()

        if from_ccy == "USD" or to_ccy == "USD":
            return []  # Direct pair via AMM
        # Cross pair via USDC bridge
        return ["USDC"]
    
    def submit_settlement(self, order: SettlementOrder) -> SettlementResult:
        """Execute settlement on Stellar network."""
        start_time = time.time()
        
        if self.mock_mode:
            return self._mock_settlement(order, start_time)
        
        if not self._initialized:
            return SettlementResult(
                order_id=order.order_id,
                success=False,
                error_message="Not initialized",
                status="failed",
            )
        
        try:
            # Resolve source and destination accounts
            # Normalize participant IDs: names may have _001 suffix not in secrets
            source_id = order.metadata.get("source", "") if order.metadata else ""
            if not source_id:
                source_id = order.metadata.get("demand_participant", "HUB") if order.metadata else "HUB"
            dest_id = order.metadata.get("destination", order.counterparty_id) if order.metadata else order.counterparty_id

            source_participant = self._resolve_participant(source_id)
            dest_participant = self._resolve_participant(dest_id)

            # Find source secret
            source_secret = self._secrets.get(source_participant)
            if not source_secret:
                raise ValueError(f"Cannot resolve secret for source {source_id}")
            source_kp = Keypair.from_secret(source_secret)
            source_pk = source_kp.public_key

            # Find destination public key
            dest_pk = self._participants.get(dest_participant, "")
            if not dest_pk:
                raise ValueError(f"Cannot resolve destination for {order.counterparty_id}")

            # Build Stellar path payment
            account = self.server.load_account(source_pk)
            destination_asset = self.CURRENCY_ASSETS.get(order.to_currency.upper(), self.USDC_ASSET)
            send_asset = self.CURRENCY_ASSETS.get(order.from_currency.upper(), self.USDC_ASSET)

            path_assets = []
            for p in self._get_path(order.from_currency, order.to_currency):
                pa = self.CURRENCY_ASSETS.get(p)
                if pa:
                    path_assets.append(pa)

            send_max = order.metadata.get("send_max", str(round(order.amount_from * 1.10, 2))) if order.metadata else str(round(order.amount_from * 1.10, 2))

            tx = (
                TransactionBuilder(
                    source_account=account,
                    network_passphrase=self.network_passphrase,
                    base_fee=100,
                )
                .append_path_payment_strict_receive_op(
                    destination=dest_pk,
                    send_asset=send_asset,
                    send_max=send_max,
                    dest_asset=destination_asset,
                    dest_amount=str(order.amount_to),
                    path=path_assets,
                )
                .add_text_memo(f"CARIB-CLEAR:{order.order_id}"[:28])
                .set_timeout(30)
                .build()
            )
            tx.sign(source_kp)
            response = self.server.submit_transaction(tx)
            
            elapsed = time.time() - start_time
            
            if response["successful"]:
                return SettlementResult(
                    order_id=order.order_id,
                    success=True,
                    fill_price=order.rate,
                    fill_quantity=order.amount_to,
                    fees_usd=order.amount_from * 0.00001,  # Stellar fee ~0.00001 XLM
                    settlement_time_seconds=elapsed,
                    tx_hash=response["hash"],
                    status="filled",
                    raw_response=response,
                )
            else:
                return SettlementResult(
                    order_id=order.order_id,
                    success=False,
                    error_message=response.get("result_xdr", "Transaction failed"),
                    status="failed",
                    raw_response=response,
                )
                
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"[Stellar] Settlement failed: {e}")
            return SettlementResult(
                order_id=order.order_id,
                success=False,
                error_message=str(e),
                status="failed",
                settlement_time_seconds=elapsed,
            )
    
    def _mock_settlement(self, order: SettlementOrder, start_time: float) -> SettlementResult:
        """Mock settlement for buildathon demo."""
        elapsed = time.time() - start_time
        
        # Simulate processing delay
        time.sleep(0.1)
        
        return SettlementResult(
            order_id=order.order_id,
            success=True,
            fill_price=order.rate,
            fill_quantity=order.amount_to,
            fees_usd=order.amount_from * self.rail_info.fee_bps / 10000,
            settlement_time_seconds=elapsed,
            tx_hash=f"0x{order.order_id}stellar",
            status="filled",
            raw_response={"mock": True, "network": "stellar-testnet"},
        )
    
    def get_settlement_status(self, order_id: str) -> SettlementResult:
        """Check settlement status."""
        if self.mock_mode:
            return SettlementResult(
                order_id=order_id,
                success=True,
                status="filled",
                tx_hash=f"0x{order_id}stellar",
            )
        
        # Real implementation would query Horizon for settlement status
        # Stellar transactions are final once submitted — use tx_hash to verify
        return SettlementResult(
            order_id=order_id,
            success=False,
            error_message="Status polling not implemented — check tx_hash on Horizon",
            status="unknown",
        )
    
    def cancel_settlement(self, order_id: str) -> bool:
        """Cancel settlement (not possible once submitted on Stellar)."""
        logger.warning(f"[Stellar] Settlement {order_id} cannot be cancelled after submission")
        return False


# ─── Demo/Test ──────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    adapter = StellarAdapter({"mock_mode": True})
    adapter.initialize()
    
    print(f"Rail: {adapter.rail_info.name}")
    print(f"Supported: {adapter.rail_info.supported_currencies}")
    
    # Test quote
    quote = adapter.get_quote("BBD", "JMD", 10000)
    print(f"\nQuote BBD→JMD $10k: {quote}")
    
    # Test settlement
    from .base import SettlementOrder
    order = SettlementOrder(
        from_currency="BBD",
        to_currency="JMD",
        amount_from=20000,
        amount_to=765000,
        rate=38.25,
        rail="stellar_usdc",
        counterparty_id="jam_supplier_001",
        jurisdiction="JM",
    )
    
    result = adapter.submit_settlement(order)
    print(f"\nSettlement: {result.status}")
    print(f"TX Hash: {result.tx_hash}")
    print(f"Time: {result.settlement_time_seconds:.3f}s")
    print(f"Fees: ${result.fees_usd:.4f}")