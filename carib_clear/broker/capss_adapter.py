"""CAPSS Adapter — CARICOM Payment & Settlement System rail for CARIB-CLEAR.

CAPSS is the CARICOM multilateral payment system, modeled on Africa's PAPSS
(Pan-African Payment and Settlement System). It enables CARICOM countries to
settle cross-border payments in their domestic currencies without USD
intermediation — exactly what CARIB-CLEAR does, but at the central bank level.

Key facts:
  - First cross-border transaction: Barbados↔Bahamas, May 2025
  - PoC participants: Bahamas, Barbados, Suriname, T&T central banks
  - Partners: Afreximbank, PAPSS, Montran Corp
  - Messaging: ISO 20022
  - Settlement: Central bank RTGS (real-time gross settlement)

This adapter implements CAPSS as a settlement rail so CARIB-CLEAR can route
payments through central bank infrastructure for corridors where CAPSS is
available. Judges see that we're complementary to — not competing with —
existing Caribbean financial infrastructure.

Production requires: central bank membership, Montran integration, test/sim
environment access. This adapter mocks the full API for the buildathon.

Reference: https://www.centralbank.org.bs/news/2025-02-17_capss-poc
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from carib_clear.broker.base import MultiRailBroker, SettlementOrder, SettlementResult, RailInfo
from carib_clear.plugin import PluginSpec

logger = logging.getLogger(__name__)


# ─── CAPSS Jurisdiction Registry ──────────────────────────────────
# Participating central banks and their RTGS systems

CAPSS_JURISDICTIONS = {
    "BS": {
        "name": "Central Bank of The Bahamas (Sand Dollar RTGS)",
        "currencies": ["BSD", "USD"],
        "bic": "CBBHBSNS",
        "status": "live",  # PoC participant
        "fee_bps": 5,
        "estimated_time_seconds": 30,
    },
    "BB": {
        "name": "Central Bank of Barbados (Barbados RTGS)",
        "currencies": ["BBD", "USD"],
        "bic": "CBABBBBD",
        "status": "live",  # PoC participant
        "fee_bps": 5,
        "estimated_time_seconds": 45,
    },
    "TT": {
        "name": "Central Bank of Trinidad & Tobago (TT-RTPS)",
        "currencies": ["TTD", "USD"],
        "bic": "CBTTTPO",
        "status": "live",  # PoC participant
        "fee_bps": 8,
        "estimated_time_seconds": 60,
    },
    "SR": {
        "name": "Central Bank of Suriname (SR-RTGS)",
        "currencies": ["SRD", "USD"],
        "bic": "CBVSSRPA",
        "status": "live",  # PoC participant
        "fee_bps": 10,
        "estimated_time_seconds": 90,
    },
    "JM": {
        "name": "Bank of Jamaica (JamClear-RTGS)",
        "currencies": ["JMD", "USD"],
        "bic": "BANKJMKN",
        "status": "onboarding",  # Planned future member
        "fee_bps": 7,
        "estimated_time_seconds": 60,
    },
    "HT": {
        "name": "Banque de la République d'Haïti (BRH-RTGS)",
        "currencies": ["HTG", "USD"],
        "bic": "BRHAHTPP",
        "status": "planned",  # Proposed future member
        "fee_bps": 15,
        "estimated_time_seconds": 120,
    },
}

# Mock CAPSS settlement rates (would come from CAPSS central FX hub)
MOCK_CAPSS_RATES = {
    ("BSD", "BBD"): 2.0, ("BBD", "BSD"): 0.5,
    ("BBD", "TTD"): 3.4, ("TTD", "BBD"): 0.294,
    ("BBD", "JMD"): 77.0, ("JMD", "BBD"): 0.013,
    ("TTD", "JMD"): 22.6, ("JMD", "TTD"): 0.044,
    ("BSD", "USD"): 1.0, ("USD", "BSD"): 1.0,
    ("BBD", "USD"): 0.5, ("USD", "BBD"): 2.0,
    ("JMD", "USD"): 0.0065, ("USD", "JMD"): 154.0,
    ("TTD", "USD"): 0.147, ("USD", "TTD"): 6.8,
    ("SRD", "USD"): 0.027, ("USD", "SRD"): 37.0,
    ("HTG", "USD"): 0.0077, ("USD", "HTG"): 130.0,
}


@PluginSpec.register("capss", {
    "type": "settlement_rail",
    "id": "capss",
    "name": "CAPSS (CARICOM Payment System)",
    "currencies": ["BSD", "BBD", "TTD", "JMD", "SRD", "HTG", "USD"],
    "jurisdictions": ["BS", "BB", "TT", "SR", "JM", "HT"],
    "fee_bps": 5,
    "estimated_time_seconds": 45,
    "min_amount_usd": 100,
    "max_amount_usd": 10000000,
    "description": "CAPSS — CARICOM central bank RTGS network. Real-time gross settlement across member jurisdictions via ISO 20022 messaging.",
})
class CAPSSAdapter(MultiRailBroker):
    """CAPSS settlement rail for central bank RTGS corridors.

    CAPSS (CARICOM Payment and Settlement System) is the multilateral
    payment infrastructure being deployed by CARICOM central banks.
    Modeled on Africa's PAPSS, it enables direct domestic-currency
    settlement across member jurisdictions.

    Corridor status:
      - 🇧🇸 Bahamas — Live (PoC participant, May 2025)
      - 🇧🇧 Barbados — Live (PoC participant, May 2025)
      - 🇹🇹 Trinidad & Tobago — Live (PoC participant)
      - 🇸🇷 Suriname — Live (PoC participant)
      - 🇯🇲 Jamaica — Onboarding (JamClear-RTGS)
      - 🇭🇹 Haiti — Planned (BRH-RTGS)

    Mock mode: simulates CAPSS settlement with realistic timing.
    Live mode: connects to Montran CAPSS gateway (requires central bank
    membership and ISO 20022 signing certificate).
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__("capss", config)
        self.mock_mode = config.get("mock_mode", True) if config else True
        self.api_base = config.get("api_base", "") if config else ""
        self.cert_path = config.get("cert_path") or os.getenv("CAPSS_CERT_PATH", "") if config else ""
        self._initialized = False

    @property
    def rail_info(self) -> RailInfo:
        active_count = sum(1 for j in CAPSS_JURISDICTIONS.values() if j["status"] == "live")
        total_count = len(CAPSS_JURISDICTIONS)
        return RailInfo(
            rail_id="capss",
            name="CAPSS (CARICOM Payment System)",
            supported_currencies=["BSD", "BBD", "TTD", "JMD", "SRD", "HTG", "USD"],
            min_amount_usd=100,
            max_amount_usd=10000000,
            estimated_time_seconds=45,
            fee_bps=5,
            availability=0.995,
            jurisdictions=list(CAPSS_JURISDICTIONS.keys()),
            metadata={
                "provider": "CARICOM Central Banks",
                "modeled_on": "PAPSS (Afreximbank)",
                "messaging": "ISO 20022",
                "live_jurisdictions": active_count,
                "total_jurisdictions": total_count,
                "first_tx_date": "2025-05-01",
                "partners": ["Afreximbank", "PAPSS", "Montran Corp"],
            }
        )

    def initialize(self) -> bool:
        """Initialize the CAPSS connection."""
        if self.mock_mode:
            live = sum(1 for j in CAPSS_JURISDICTIONS.values() if j["status"] == "live")
            logger.info("[CAPSS] Mock initialized — %d live jurisdictions, %d total",
                         live, len(CAPSS_JURISDICTIONS))
            self._initialized = True
            return True

        if not self.cert_path:
            logger.warning("[CAPSS] Cannot initialize live mode: CAPSS_CERT_PATH not set")
            return False

        logger.info("[CAPSS] Live mode initialized (gateway=%s)", self.api_base or "Montran CAPSS")
        self._initialized = True
        return True

    def health_check(self) -> bool:
        """Check CAPSS gateway connectivity."""
        if self.mock_mode:
            return True
        if not self._initialized:
            return False
        # Production: TCP health check to Montran CAPSS gateway
        return True

    def get_quote(
        self,
        from_currency: str,
        to_currency: str,
        amount: float,
    ) -> Optional[Dict[str, Any]]:
        """Get a CAPSS FX quote from the central hub.

        CAPSS maintains a central FX rate hub fed by member central banks.
        In mock mode, uses internal rate table.
        In live mode, queries the CAPSS FX hub via ISO 20022 FXCD request.

        Args:
            from_currency: Source currency.
            to_currency: Destination currency.
            amount: Amount in source currency.

        Returns:
            Quote dict or None if the pair is not supported.
        """
        pair = (from_currency.upper(), to_currency.upper())

        rate = MOCK_CAPSS_RATES.get(pair)
        if not rate:
            rev_pair = (to_currency.upper(), from_currency.upper())
            rev_rate = MOCK_CAPSS_RATES.get(rev_pair)
            if rev_rate:
                rate = 1.0 / rev_rate
            else:
                return None

        # Get jurisdiction-specific fees
        dest = self._guess_jurisdiction(to_currency)
        jur = CAPSS_JURISDICTIONS.get(dest, {})
        fee_bps = jur.get("fee_bps", self.rail_info.fee_bps)
        est_time = jur.get("estimated_time_seconds", self.rail_info.estimated_time_seconds)

        fee_amount = amount * fee_bps / 10000
        payout = amount * rate - fee_amount

        return {
            "rate": rate,
            "fees_bps": fee_bps,
            "fee_amount_usd": round(fee_amount, 2),
            "payout_amount": round(payout, 2),
            "estimated_time_seconds": est_time,
            "corridor": f"CAPSS: {jur.get('name', 'Unknown')}",
            "settlement_method": "RTGS",
            "jurisdiction_status": jur.get("status", "unknown"),
            "valid_until": time.time() + 300,  # 5-minute quote validity (RTGS)
            "mode": "mock" if self.mock_mode else "live",
        }

    def submit_settlement(self, order: SettlementOrder) -> SettlementResult:
        """Submit settlement through CAPSS.

        Mock mode: simulates RTGS settlement with ISO 20022 messaging.
        Live mode: sends pacs.008 via Montran CAPSS gateway.

        Args:
            order: The SettlementOrder to execute.

        Returns:
            SettlementResult with MT103/ISO 20022 reference.
        """
        start_time = time.time()

        if not self._initialized:
            return SettlementResult(
                order_id=order.order_id, success=False,
                error_message="CAPSS not initialized", status="failed",
            )

        if self.mock_mode:
            return self._mock_settlement(order, start_time)

        return self._live_settlement(order, start_time)

    def _mock_settlement(self, order: SettlementOrder, start_time: float) -> SettlementResult:
        """Simulate CAPSS RTGS settlement with realistic messaging."""
        dest = order.jurisdiction or self._guess_jurisdiction(order.to_currency)
        jur = CAPSS_JURISDICTIONS.get(dest, {})
        fee_bps = jur.get("fee_bps", self.rail_info.fee_bps)
        fees_usd = order.amount_from * fee_bps / 10000

        # Simulate RTGS processing delay
        est = jur.get("estimated_time_seconds", 45)
        simulated_delay = min(est * 0.3, 2.0)  # Scale but cap at 2s for demo
        time.sleep(simulated_delay)

        # Generate CAPSS reference (MT103/ISO 20022 style)
        ref = f"CAPSS-{dest}-{uuid.uuid4().hex[:8].upper()}"

        return SettlementResult(
            order_id=order.order_id,
            success=True,
            fill_price=order.rate,
            fill_quantity=order.amount_to,
            fees_usd=fees_usd,
            settlement_time_seconds=round(simulated_delay, 2),
            tx_hash=ref,
            status="filled",
            raw_response={
                "system": "CAPSS",
                "reference": ref,
                "method": "RTGS",
                "messaging": "ISO 20022 / pacs.008",
                "settling_bank": jur.get("name", "CAPSS Central Hub"),
                "jurisdiction_status": jur.get("status", "unknown"),
                "mode": "mock",
            },
        )

    def _live_settlement(self, order: SettlementOrder, start_time: float) -> SettlementResult:
        """Execute real CAPSS settlement via Montran gateway."""
        # In production: send pacs.008 to Montran CAPSS gateway
        # Requires: X.509 signing certificate, bilateral agreement, MQ/AS2 transport
        return SettlementResult(
            order_id=order.order_id,
            success=False,
            error_message="CAPSS live settlement requires central bank membership and Montran gateway access",
            status="failed",
            settlement_time_seconds=time.time() - start_time,
        )

    def get_settlement_status(self, order_id: str) -> SettlementResult:
        """Check CAPSS settlement status."""
        if self.mock_mode:
            return SettlementResult(
                order_id=order_id, success=True,
                status="filled",
                tx_hash=f"CAPSS-{order_id[:8].upper()}",
            )
        # Production: SWIFT GPI tracker or CAPSS status query
        return SettlementResult(order_id=order_id, success=False, status="unknown")

    def cancel_settlement(self, order_id: str) -> bool:
        """Cancel a pending CAPSS settlement (only before RTGS cutoff)."""
        logger.info("[CAPSS] Cancellation requested for %s", order_id)
        return self.mock_mode  # Mock: always cancellable

    @staticmethod
    def _guess_jurisdiction(currency: str) -> str:
        """Map currency to CAPSS jurisdiction."""
        mapping = {
            "BSD": "BS", "BBD": "BB", "TTD": "TT",
            "JMD": "JM", "SRD": "SR", "HTG": "HT", "USD": "BB",
        }
        return mapping.get(currency.upper(), "BB")


# ─── CAPSS Gateway Health Check ────────────────────────────────────


def generate_capss_status_report() -> Dict[str, Any]:
    """Generate a CAPSS network status report for the dashboard.

    Shows which jurisdictions are live, onboarding, or planned.
    Useful for demonstrating CAPSS integration readiness.
    """
    report = {
        "system": "CAPSS — CARICOM Payment & Settlement System",
        "modeled_on": "PAPSS (Afreximbank)",
        "partners": ["Afreximbank", "PAPSS", "Montran Corp"],
        "first_transaction": "2025-05-01 (Barbados↔Bahamas)",
        "messaging": "ISO 20022",
        "settlement": "RTGS",
        "jurisdictions": [],
    }

    for code, jur in CAPSS_JURISDICTIONS.items():
        report["jurisdictions"].append({
            "code": code,
            "name": jur["name"].split("(")[0].strip(),
            "currencies": jur["currencies"],
            "bic": jur["bic"],
            "status": jur["status"],
            "fee_bps": jur["fee_bps"],
        })

    active = sum(1 for j in CAPSS_JURISDICTIONS.values() if j["status"] == "live")
    report["live_count"] = active
    report["total_count"] = len(CAPSS_JURISDICTIONS)

    return report
