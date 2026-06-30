"""SEP-31 Compliance Layer — Stellar cross-border payment standard for CARIB-CLEAR.

SEP-31 defines how anchors send cross-border payments to each other on the
Stellar network. CARIB-CLEAR implements the SEP-31 receiving anchor role,
allowing any Stellar anchor to route cross-border payments through our
Caribbean corridors.

Key SEP standards implemented:
  - SEP-31: Cross-border Payment API
  - SEP-12: KYC/AML Customer Data Sharing
  - SEP-38: Liquidity Pool / DEX Quotes

Architecture:
  Sending Anchor (external)
       │  SEP-31 POST /transactions
       ▼
  CARIB-CLEAR SEP-31 Server
       │
       ├── ComplianceAgent (KYC/AML via SEP-12)
       ├── LiquidityPoolManager (quotes via SEP-38)
       └── MultiRailRouter (settlement via Stellar/USDC)
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ─── SEP-31 Status Codes ──────────────────────────────────────────────


class SEP31Status(str, Enum):
    """SEP-31 transaction status codes."""
    PENDING_SENDER = "pending_sender"          # Awaiting sender funds
    PENDING_RECEIVER = "pending_receiver"       # Awaiting receiver info
    PENDING_TRANSACTION = "pending_transaction" # Waiting for completion
    COMPLETED = "completed"                      # Success
    ERROR = "error"                              # Failed


class SEP12Status(str, Enum):
    """SEP-12 KYC status codes."""
    ACCEPTED = "ACCEPTED"          # KYC passed
    PROCESSING = "PROCESSING"      # Under review
    REJECTED = "REJECTED"          # KYC failed
    NEEDS_INFO = "NEEDS_INFO"      # More info required


# ─── Data Models ──────────────────────────────────────────────────────


@dataclass
class SEPA31Transaction:
    """A SEP-31 cross-border payment transaction."""
    transaction_id: str
    status: SEP31Status
    amount: float
    amount_fee: float
    amount_expected: float
    source_asset: str
    destination_asset: str
    sender_id: str  # SEP-12 customer ID for sender
    receiver_id: str  # SEP-12 customer ID for receiver
    stellar_transaction_id: str  # Stellar tx hash once sent
    started_at: str
    completed_at: str = ""
    required_info_updates: List[str] = field(default_factory=list)
    message: str = ""


@dataclass
class SEPA12Customer:
    """SEP-12 KYC customer record."""
    customer_id: str
    status: SEP12Status
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    phone: str = ""
    country_code: str = ""
    jurisdiction: str = ""
    bank_account: str = ""
    wallet_address: str = ""
    status_message: str = ""
    provided_fields: List[str] = field(default_factory=list)
    required_fields: List[str] = field(default_factory=list)
    created_at: str = ""

    def __post_init__(self):
        if not self.customer_id:
            self.customer_id = f"cus_{uuid.uuid4().hex[:12]}"
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()


# ─── SEP-31 Server ────────────────────────────────────────────────────


class SEP31Server:
    """SEP-31 compliant server for receiving cross-border payments.

    This server implements the receiving anchor role, allowing external
    Stellar anchors to send cross-border payments to Caribbean beneficiaries
    through CARIB-CLEAR's network.
    """

    def __init__(self, compliance_agent=None, liquidity_manager=None, settlement_router=None):
        self._transactions: Dict[str, SEPA31Transaction] = {}
        self._customers: Dict[str, SEPA12Customer] = {}
        self._compliance = compliance_agent
        self._liquidity = liquidity_manager
        self._router = settlement_router

        # Supported assets
        self.assets = {
            "stellar:USDC:GCO4O4WT6ZJV7MXXSQPH4INW54XP2LRWPQBMHF4JS6BHNVW3FPUYO6AG": {
                "code": "USDC",
                "issuer": "GCO4O4WT6ZJV7MXXSQPH4INW54XP2LRWPQBMHF4JS6BHNVW3FPUYO6AG",
                "status": "enabled",
                "send_fee_fixed": 0.0,
                "send_fee_percent": 0.001,  # 0.1%
                "min_amount": 1.0,
                "max_amount": 500000.0,
                "countries": ["BB", "JM", "TT", "HT", "ECCB"],
            }
        }

    # ── SEP-31: Asset Info ─────────────────────────────────────────

    def get_info(self) -> Dict[str, Any]:
        """GET /sep31/info — returns supported assets and fees.

        Returns:
            Dict in SEP-31 /info format.
        """
        return {
            "receive": self.assets,
        }

    # ── SEP-31: Create Transaction ─────────────────────────────────

    def create_transaction(
        self,
        amount: float,
        source_asset: str,
        destination_asset: str,
        sender_id: str,
        receiver_id: str,
        stellar_transaction_id: str = "",
    ) -> SEPA31Transaction:
        """POST /sep31/transactions — create a new inbound payment.

        Args:
            amount: Amount to send in destination asset.
            source_asset: Asset code of the sending anchor.
            destination_asset: Asset code for the beneficiary.
            sender_id: SEP-12 customer ID of the sender.
            receiver_id: SEP-12 customer ID of the receiver.
            stellar_transaction_id: The Stellar payment tx hash.

        Returns:
            SEPA31Transaction with status and fee info.
        """
        tx_id = f"sep31_{uuid.uuid4().hex[:12]}"

        # Validate sender + receiver KYC
        sender = self._customers.get(sender_id)
        receiver = self._customers.get(receiver_id)

        if not sender or sender.status != SEP12Status.ACCEPTED:
            return SEPA31Transaction(
                transaction_id=tx_id,
                status=SEP31Status.PENDING_SENDER,
                amount=amount, amount_fee=0, amount_expected=amount,
                source_asset=source_asset, destination_asset=destination_asset,
                sender_id=sender_id, receiver_id=receiver_id,
                stellar_transaction_id=stellar_transaction_id,
                started_at=datetime.now(timezone.utc).isoformat(),
                message="Awaiting sender KYC approval",
            )

        if not receiver or receiver.status != SEP12Status.ACCEPTED:
            return SEPA31Transaction(
                transaction_id=tx_id,
                status=SEP31Status.PENDING_RECEIVER,
                amount=amount, amount_fee=0, amount_expected=amount,
                source_asset=source_asset, destination_asset=destination_asset,
                sender_id=sender_id, receiver_id=receiver_id,
                stellar_transaction_id=stellar_transaction_id,
                started_at=datetime.now(timezone.utc).isoformat(),
                message="Awaiting receiver KYC approval",
            )

        # Calculate fee
        asset_info = self.assets.get(destination_asset, {})
        fee_percent = asset_info.get("send_fee_percent", 0.001)
        fee = amount * fee_percent
        amount_after_fee = amount - fee

        tx = SEPA31Transaction(
            transaction_id=tx_id,
            status=SEP31Status.PENDING_TRANSACTION,
            amount=amount,
            amount_fee=round(fee, 2),
            amount_expected=round(amount_after_fee, 2),
            source_asset=source_asset,
            destination_asset=destination_asset,
            sender_id=sender_id,
            receiver_id=receiver_id,
            stellar_transaction_id=stellar_transaction_id,
            started_at=datetime.now(timezone.utc).isoformat(),
            message="Transaction created, awaiting Stellar payment",
        )

        self._transactions[tx_id] = tx
        logger.info("[SEP-31] Created transaction %s: $%.2f %s → %s",
                     tx_id, amount, source_asset, destination_asset)
        return tx

    # ── SEP-31: Transaction Status ────────────────────────────────

    def get_transaction(self, transaction_id: str) -> Optional[SEPA31Transaction]:
        """GET /sep31/transactions/:id — check transaction status.

        Args:
            transaction_id: The SEP-31 transaction ID.

        Returns:
            SEPA31Transaction or None if not found.
        """
        return self._transactions.get(transaction_id)

    def list_transactions(self, limit: int = 20) -> List[SEPA31Transaction]:
        """List recent SEP-31 transactions."""
        return list(self._transactions.values())[-limit:]

    # ── SEP-31: Complete Transaction ──────────────────────────────

    def complete_transaction(self, transaction_id: str) -> bool:
        """Mark a transaction as completed (after Stellar payment settles)."""
        tx = self._transactions.get(transaction_id)
        if tx and tx.status == SEP31Status.PENDING_TRANSACTION:
            tx.status = SEP31Status.COMPLETED
            tx.completed_at = datetime.now(timezone.utc).isoformat()
            logger.info("[SEP-31] Completed transaction %s", transaction_id)
            return True
        return False

    # ── SEP-12: Customer KYC ──────────────────────────────────────

    def register_customer(
        self,
        customer_id: str = "",
        first_name: str = "",
        last_name: str = "",
        email: str = "",
        phone: str = "",
        country_code: str = "",
        jurisdiction: str = "",
        bank_account: str = "",
        wallet_address: str = "",
    ) -> SEPA12Customer:
        """PUT /sep12/customer — register or update a customer's KYC info.

        Returns the customer record. If KYC is complete, status = ACCEPTED.
        """
        existing = self._customers.get(customer_id)
        if existing:
            customer = existing
            customer.first_name = first_name or customer.first_name
            customer.last_name = last_name or customer.last_name
            customer.email = email or customer.email
            customer.phone = phone or customer.phone
            customer.country_code = country_code or customer.country_code
            customer.jurisdiction = jurisdiction or customer.jurisdiction
            customer.bank_account = bank_account or customer.bank_account
            customer.wallet_address = wallet_address or customer.wallet_address
        else:
            customer = SEPA12Customer(
                customer_id=customer_id or f"cus_{uuid.uuid4().hex[:12]}",
                status=SEP12Status.PROCESSING,
                first_name=first_name,
                last_name=last_name,
                email=email,
                phone=phone,
                country_code=country_code,
                jurisdiction=jurisdiction,
                bank_account=bank_account,
                wallet_address=wallet_address,
            )

        # Track provided fields
        for field_name in ["first_name", "last_name", "email", "phone",
                           "country_code", "jurisdiction", "bank_account"]:
            if getattr(customer, field_name, ""):
                if field_name not in customer.provided_fields:
                    customer.provided_fields.append(field_name)

        # Auto-accept KYC if we have enough info
        required = {"first_name", "last_name", "email", "country_code", "jurisdiction"}
        has_required = required.issubset(set(customer.provided_fields))

        if has_required:
            customer.status = SEP12Status.ACCEPTED
            customer.status_message = "KYC verified"
        else:
            customer.required_fields = list(required - set(customer.provided_fields))
            customer.status = SEP12Status.NEEDS_INFO
            customer.status_message = f"Missing: {', '.join(customer.required_fields)}"

        self._customers[customer.customer_id] = customer
        logger.info("[SEP-12] Customer %s: %s (%s)",
                     customer.customer_id, customer.status.value, customer.status_message)
        return customer

    def get_customer(self, customer_id: str) -> Optional[SEPA12Customer]:
        """GET /sep12/customer/:id — get customer KYC status."""
        return self._customers.get(customer_id)

    def delete_customer(self, customer_id: str) -> bool:
        """DELETE /sep12/customer/:id — remove customer data."""
        if customer_id in self._customers:
            del self._customers[customer_id]
            return True
        return False

    # ── SEP-38: Quotes ─────────────────────────────────────────────

    def get_prices(self) -> List[Dict[str, Any]]:
        """GET /sep38/prices — list available asset pairs with rates."""
        prices = []
        # Map our liquidity pools to SEP-38 format
        if self._liquidity:
            for pool_name, pool in self._liquidity._pools.items():
                base_asset = f"stellar:{pool_name.upper()}:CARIB-CLEAR"
                prices.append({
                    "selling_asset": f"stellar:USDC:GCO4O4...",
                    "buying_asset": base_asset,
                    "price": str(pool.current_spread_bps / 10000 + 1),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
        return prices

    def get_quote(
        self,
        sell_asset: str,
        buy_asset: str,
        sell_amount: Optional[float] = None,
        buy_amount: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """POST /sep38/quote — get a firm quote for an asset pair."""
        # Extract currency codes from asset strings
        sell_code = sell_asset.split(":")[1] if ":" in sell_asset else sell_asset
        buy_code = buy_asset.split(":")[1] if ":" in buy_asset else buy_asset

        if self._router:
            for broker in self._router.brokers:
                quote = broker.get_quote(sell_code, buy_code, sell_amount or 1000)
                if quote:
                    return {
                        "id": f"q_{uuid.uuid4().hex[:8]}",
                        "sell_asset": sell_asset,
                        "buy_asset": buy_asset,
                        "sell_amount": str(sell_amount or "1000"),
                        "buy_amount": str(quote.get("payout_amount", quote.get("amount_to", 0))),
                        "fee": {
                            "total": str(quote.get("fee_amount_usd", 0)),
                            "asset": "USD",
                        },
                        "price": str(quote.get("rate", 1)),
                        "expires_at": datetime.fromtimestamp(
                            quote.get("valid_until", time.time() + 60),
                            tz=timezone.utc
                        ).isoformat(),
                    }
        return None


# ─── Pydantic Models for API ──────────────────────────────────────────

from pydantic import BaseModel, Field


class SEP31TransactionRequestModel(BaseModel):
    """SEP-31 transaction creation request."""
    amount: float = Field(..., gt=0)
    source_asset: str
    destination_asset: str
    sender_id: str
    receiver_id: str
    stellar_transaction_id: str = ""


class SEP12CustomerRequestModel(BaseModel):
    """SEP-12 customer registration request."""
    customer_id: str = ""
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    phone: str = ""
    country_code: str = ""
    jurisdiction: str = ""
    bank_account: str = ""
    wallet_address: str = ""


class SEP38QuoteRequestModel(BaseModel):
    """SEP-38 quote request."""
    sell_asset: str
    buy_asset: str
    sell_amount: Optional[float] = None
    buy_amount: Optional[float] = None


# ─── Helper: Build SEP-31 FastAPI router ──────────────────────────────


def create_sep31_router(server: SEP31Server):
    """Create a FastAPI APIRouter with SEP-31/12/38 endpoints.

    Usage:
        from fastapi import APIRouter
        sep31_router = create_sep31_router(server)
        app.include_router(sep31_router, prefix="/sep31")
    """
    from fastapi import APIRouter, HTTPException

    router = APIRouter()

    @router.get("/info")
    async def sep31_info():
        return server.get_info()

    @router.post("/transactions")
    async def sep31_create_transaction(body: SEP31TransactionRequestModel):
        tx = server.create_transaction(
            amount=body.amount,
            source_asset=body.source_asset,
            destination_asset=body.destination_asset,
            sender_id=body.sender_id,
            receiver_id=body.receiver_id,
            stellar_transaction_id=body.stellar_transaction_id,
        )
        return {
            "transaction_id": tx.transaction_id,
            "status": tx.status.value,
            "amount_expected": tx.amount_expected,
            "amount_fee": tx.amount_fee,
            "message": tx.message,
        }

    @router.get("/transactions")
    async def sep31_list_transactions(limit: int = 20):
        txs = server.list_transactions(limit=limit)
        return {
            "transactions": [
                {"id": t.transaction_id, "status": t.status.value,
                 "amount": t.amount, "source": t.source_asset,
                 "destination": t.destination_asset}
                for t in txs
            ]
        }

    @router.get("/transactions/{transaction_id}")
    async def sep31_get_transaction(transaction_id: str):
        tx = server.get_transaction(transaction_id)
        if not tx:
            raise HTTPException(404, "Transaction not found")
        return {
            "transaction_id": tx.transaction_id,
            "status": tx.status.value,
            "amount": tx.amount,
            "amount_fee": tx.amount_fee,
            "amount_expected": tx.amount_expected,
            "source_asset": tx.source_asset,
            "destination_asset": tx.destination_asset,
            "stellar_transaction_id": tx.stellar_transaction_id,
            "started_at": tx.started_at,
            "completed_at": tx.completed_at or "",
            "message": tx.message,
        }

    @router.post("/customer")
    async def sep12_register_customer(body: SEP12CustomerRequestModel):
        customer = server.register_customer(
            customer_id=body.customer_id,
            first_name=body.first_name,
            last_name=body.last_name,
            email=body.email,
            phone=body.phone,
            country_code=body.country_code,
            jurisdiction=body.jurisdiction,
            bank_account=body.bank_account,
            wallet_address=body.wallet_address,
        )
        return {
            "customer_id": customer.customer_id,
            "status": customer.status.value,
            "provided_fields": customer.provided_fields,
            "required_fields": customer.required_fields,
            "message": customer.status_message,
        }

    @router.get("/customer/{customer_id}")
    async def sep12_get_customer(customer_id: str):
        customer = server.get_customer(customer_id)
        if not customer:
            raise HTTPException(404, "Customer not found")
        return {
            "customer_id": customer.customer_id,
            "status": customer.status.value,
            "first_name": customer.first_name,
            "last_name": customer.last_name,
            "email": customer.email,
            "jurisdiction": customer.jurisdiction,
            "provided_fields": customer.provided_fields,
            "message": customer.status_message,
        }

    @router.delete("/customer/{customer_id}")
    async def sep12_delete_customer(customer_id: str):
        if server.delete_customer(customer_id):
            return {"status": "deleted"}
        raise HTTPException(404, "Customer not found")

    @router.get("/prices")
    async def sep38_prices():
        return {"asset_pairs": server.get_prices()}

    @router.post("/quote")
    async def sep38_get_quote(body: SEP38QuoteRequestModel):
        quote = server.get_quote(
            body.sell_asset, body.buy_asset,
            body.sell_amount, body.buy_amount,
        )
        if not quote:
            raise HTTPException(400, "Could not find quote for this pair")
        return quote

    return router


# ─── Plugin registration ──────────────────────────────────────────────

def register_with_app(app) -> SEP31Server:
    """Register SEP-31 endpoints on a FastAPI app.

    Called at startup to mount the SEP-31 server on the main API.
    Returns the SEP31Server instance for direct access.
    """
    server = SEP31Server()
    router = create_sep31_router(server)
    app.include_router(router, prefix="/sep31", tags=["SEP-31"])
    logger.info("[SEP-31] Registered endpoints at /sep31/*")
    return server
