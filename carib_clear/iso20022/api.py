"""ISO 20022 API endpoints — banks submit/receive messages via REST."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from carib_clear.iso20022 import (
    Iso20022FxCxnAdvice,
    Iso20022Party,
    generate_fx_confirmation_xml,
    parse_fx_confirmation_xml,
    generate_payment_xml,
    parse_payment_xml,
    settlement_to_fx_advice,
    fx_advice_to_settlement_request,
)

logger = logging.getLogger(__name__)


class Iso20022SubmitRequest(BaseModel):
    """Bank submits an ISO 20022 message (raw XML)."""
    xml_message: str = Field(..., description="Raw ISO 20022 XML message")


class Iso20022SubmitResponse(BaseModel):
    """Response to a bank's ISO 20022 submission."""
    accepted: bool
    message: str
    carib_clear_ref: str = ""
    internal_status: str = ""
    response_xml: str = ""


# ─── Demo FX confirmation XML for Swagger/testing ─────────────────

DEMO_FX_XML = """<?xml version="1.0" encoding="UTF-8"?>
<FXCxnAdvice xmlns="urn:iso:std:iso:20022:tech:xsd:FXCD.001.001">
  <MsgId>FXCD-DEMO-001</MsgId>
  <TradeId>TRADE-BBDJMD-001</TradeId>
  <CreDtTm>2026-06-25T12:00:00Z</CreDtTm>
  <TradDtls>
    <TradDt>2026-06-25</TradDt>
    <ValDt>2026-06-25</ValDt>
    <SttlmMtd>Stellar/USDC</SttlmMtd>
  </TradDtls>
  <DealAmts>
    <BuyAmt><Amt>50000.00</Amt><Ccy>BBD</Ccy></BuyAmt>
    <SellAmt><Amt>3825000.00</Amt><Ccy>JMD</Ccy></SellAmt>
  </DealAmts>
  <FXDtls>
    <XchgRate>76.500000</XchgRate>
  </FXDtls>
  <Buyr><Nm>Barbados Grand Hotel</Nm><BIC>BBGHBBBB</BIC></Buyr>
  <Sellr><Nm>Jamaica Food Exports</Nm><BIC>JMFEJMJM</BIC></Sellr>
  <Sts>NEW</Sts>
</FXCxnAdvice>"""


def register_iso20022(app) -> None:
    """Mount ISO 20022 endpoints on a FastAPI app.

    Adds /iso20022/* routes for bank integration.
    """
    router = APIRouter()

    @router.post("/iso20022/fx", tags=["ISO 20022"])
    async def submit_fx_confirmation(body: Iso20022SubmitRequest):
        """Submit an ISO 20022 FX Confirmation (FXCD.001.001).

        Banks send FX swap confirmations as XML. CARIB-CLEAR parses,
        processes, and returns a confirmation XML.
        """
        # Parse the bank's XML
        advice = parse_fx_confirmation_xml(body.xml_message)
        if not advice:
            raise HTTPException(400, "Failed to parse ISO 20022 FX confirmation XML")

        # Convert to CARIB-CLEAR internal format
        request = fx_advice_to_settlement_request(advice)

        # Generate response XML
        response_advice = Iso20022FxCxnAdvice(
            message_id=f"CC-{advice.message_id}",
            trade_id=advice.trade_id,
            from_currency=advice.from_currency,
            to_currency=advice.to_currency,
            amount_from=advice.amount_from,
            amount_to=advice.amount_to,
            rate=advice.rate,
            status="MATCHED",
            settlement_method="Stellar/USDC",
            carib_clear_ref=f"CC-{advice.trade_id}",
            buyer=Iso20022Party(name="CARIB-CLEAR", bic="CCLRBBBB"),
            seller=Iso20022Party(name="CARIB-CLEAR", bic="CCLRBBBB"),
        )
        response_xml = generate_fx_confirmation_xml(response_advice)

        return Iso20022SubmitResponse(
            accepted=True,
            message=f"FX confirmation {advice.trade_id} processed",
            carib_clear_ref=response_advice.carib_clear_ref,
            internal_status=response_advice.status,
            response_xml=response_xml,
        )

    @router.post("/iso20022/payment", tags=["ISO 20022"])
    async def submit_payment(body: Iso20022SubmitRequest):
        """Submit an ISO 20022 Payment (pacs.008.001).

        Banks send payment instructions as XML. CARIB-CLEAR acknowledges.
        """
        instruction = parse_payment_xml(body.xml_message)
        if not instruction:
            raise HTTPException(400, "Failed to parse ISO 20022 payment XML")

        # Generate acknowledgment XML
        response_advice = Iso20022FxCxnAdvice(
            message_id=f"CC-{instruction.message_id}",
            status="MATCHED",
            carib_clear_ref=f"CC-{instruction.message_id}",
        )
        response_xml = generate_fx_confirmation_xml(response_advice)

        return Iso20022SubmitResponse(
            accepted=True,
            message=f"Payment instruction {instruction.message_id} received",
            carib_clear_ref=response_advice.carib_clear_ref,
            internal_status="RECEIVED",
            response_xml=response_xml,
        )

    @router.get("/iso20022/example/fx", tags=["ISO 20022"])
    async def get_fx_example():
        """Get a sample ISO 20022 FX Confirmation XML for testing."""
        return {
            "description": "Sample ISO 20022 FX Confirmation (FXCD.001.001)",
            "xml": DEMO_FX_XML,
            "usage": "POST this XML to /iso20022/fx to process",
        }

    @router.post("/iso20022/settlement", tags=["ISO 20022"])
    async def convert_settlement(
        from_currency: str = "BBD",
        to_currency: str = "JMD",
        amount: float = 50000,
        rate: float = 76.5,
    ):
        """Generate an ISO 20022 FX Confirmation from settlement params.

        Useful for banks that want to receive confirmations in ISO 20022 format
        after CARIB-CLEAR executes a settlement.
        """
        advice = Iso20022FxCxnAdvice(
            from_currency=from_currency,
            to_currency=to_currency,
            amount_from=amount,
            amount_to=amount * rate,
            rate=rate,
            status="SETTLED",
            carib_clear_ref=f"CC-{from_currency}{to_currency}-DEMO",
            buyer=Iso20022Party(name="CARIB-CLEAR Buyer", bic="CCLRBBBB"),
            seller=Iso20022Party(name="CARIB-CLEAR Seller", bic="CCLRBBBB"),
        )
        xml = generate_fx_confirmation_xml(advice)
        return {
            "message": f"ISO 20022 confirmation for {amount:.0f} {from_currency} → {to_currency}",
            "xml": xml,
        }

    app.include_router(router)
    logger.info("[ISO20022] Bank integration routes registered")
