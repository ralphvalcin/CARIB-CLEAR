# broker/stellar_adapter.py
"""
CARIB-CLEAR Stellar/USDC Adapter

Primary settlement rail for cross-border FX.
Uses Stellar network with USDC for instant, low-cost settlement.
"""
from __future__ import annotations

import os
import time
import logging
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

from .base import MultiRailBroker, SettlementOrder, SettlementResult, RailInfo

logger = logging.getLogger(__name__)

# Mock rates for buildathon demo (would fetch from Stellar DEX or oracle)
MOCK_RATES = {
    ("BBD", "USD"): 0.5, ("USD", "BBD"): 2.0,
    ("JMD", "USD"): 0.0065, ("USD", "JMD"): 154.0,
    ("TTD", "USD"): 0.147, ("USD", "TTD"): 6.8,
    ("XCD", "USD"): 0.37, ("USD", "XCD"): 2.7,
    ("HTG", "USD"): 0.0077, ("USD", "HTG"): 130.0,
}


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
        self.horizon_url = config.get("horizon_url", "https://horizon-testnet.stellar.org") if config else "https://horizon-testnet.stellar.org"
        self.network_passphrase = config.get("network_passphrase", "Test SDF Network ; September 2015")
        self.secret_key = config.get("secret_key") or os.getenv("STELLAR_SECRET_KEY")
        self.mock_mode = config.get("mock_mode", True) if config else True
        
        # Stellar-specific constants
        self.USDC_ASSET = None
        self.CURRENCY_ASSETS = {}
        self.SUPPORTED_PAIRS = []

        if STELLAR_AVAILABLE:
            self.USDC_ASSET = Asset("USDC", "GA5ZSEJYB37JRC5AVCIA5MOP4RHTM335X2KGX3IHOJAPP5RE34K4KZVN")
            self.CURRENCY_ASSETS = {
                "USD": self.USDC_ASSET,
                "BBD": Asset("BBD", "GBBD..."),
                "JMD": Asset("JMD", "GJMD..."),
                "TTD": Asset("TTD", "GTTD..."),
                "XCD": Asset("XCD", "GXCD..."),
                "HTG": Asset("HTG", "GHTG..."),
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
            self.server.ledger()
            return True
        except Exception:
            return False
    
    def get_quote(
        self,
        from_currency: str,
        to_currency: str,
        amount: float
    ) -> Optional[Dict[str, Any]]:
        """Get FX quote via Stellar DEX path."""
        pair = (from_currency.upper(), to_currency.upper())
        
        if not self.SUPPORTED_PAIRS or pair not in self.SUPPORTED_PAIRS:
            return None
        
        # In production: query Stellar DEX for path payment
        # For buildathon: use mock rates
        if self.mock_mode:
            rate = MOCK_RATES.get(pair)
            if not rate:
                # Calculate cross rate via USD
                usd_from = MOCK_RATES.get((from_currency.upper(), "USD"))
                usd_to = MOCK_RATES.get(("USD", to_currency.upper()))
                if usd_from and usd_to:
                    rate = usd_from * usd_to
                else:
                    return None
            
            return {
                "rate": rate,
                "fees_bps": self.rail_info.fee_bps,
                "estimated_time_seconds": self.rail_info.estimated_time_seconds,
                "valid_until": time.time() + 30,
                "path": self._get_path(from_currency, to_currency),
            }
        
        # Real implementation would query Stellar DEX
        # For now, return mock
        return None
    
    def _get_path(self, from_ccy: str, to_ccy: str) -> List[str]:
        """Get payment path through Stellar DEX."""
        if from_ccy == "USD" or to_ccy == "USD":
            return [from_ccy, "USDC", to_ccy]
        return [from_ccy, "USDC", "USD", "USDC", to_ccy]
    
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
            # Build Stellar transaction
            source = self.keypair.public_key
            account = self.server.load_account(source)
            
            # Create path payment
            destination_asset = self.CURRENCY_ASSETS.get(order.to_currency.upper(), self.USDC_ASSET)
            send_asset = self.CURRENCY_ASSETS.get(order.from_currency.upper(), self.USDC_ASSET)
            
            tx = (
                TransactionBuilder(
                    source_account=account,
                    network_passphrase=self.network_passphrase,
                    base_fee=100,
                )
                .append_path_payment_strict_receive_op(
                    destination=order.metadata.get("destination_account"),
                    send_asset=send_asset,
                    send_max=str(order.amount_from * 1.01),  # 1% slippage tolerance
                    dest_asset=destination_asset,
                    dest_amount=str(order.amount_to),
                    path=self._get_path(order.from_currency, order.to_currency),
                )
                .add_text_memo(f"CARIB-CLEAR:{order.order_id}")
                .set_timeout(30)
                .build()
            )
            
            tx.sign(self.keypair)
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
        
        # Real implementation would query Horizon
        return SettlementResult(
            order_id=order_id,
            success=False,
            error_message="Not implemented",
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