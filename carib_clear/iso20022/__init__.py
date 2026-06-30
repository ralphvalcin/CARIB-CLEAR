"""ISO 20022 Translation Layer — bank integration for CARIB-CLEAR.

Translates between ISO 20022 XML (the global standard for financial messaging)
and CARIB-CLEAR's internal JSON models. Banks can submit FX settlement
instructions and receive confirmations in their standard message format.

Supported message types:
  - head.001.001: Business Application Header (message envelope)
  - FXCD.001.001: Foreign Exchange Confirmation (FX trade confirmations)
  - pacs.008.001: FIToFICustomerCreditTransfer (customer payments)
  - camt.053.001: BankToCustomerStatement (account statements)

Usage:
    from carib_clear.iso20022 import (
        parse_fx_confirmation_xml,
        generate_fx_confirmation_xml,
        Iso20022FxCxnAdvice,
)

    # Parse incoming bank message
    advice = parse_fx_confirmation_xml(xml_string)

    # Process through CARIB-CLEAR pipeline
    result = process_advice(advice)

    # Generate response XML for the bank
    response_xml = generate_fx_confirmation_xml(result)
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

# XML namespaces for ISO 20022
NS = {
    "doc": "urn:iso:std:iso:20022:tech:xsd:head.001.001.01",
    "fx": "urn:iso:std:iso:20022:tech:xsd:FXCD.001.001",
    "pacs": "urn:iso:std:iso:20022:tech:xsd:pacs.008.001.08",
    "camt": "urn:iso:std:iso:20022:tech:xsd:camt.053.001.08",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}


# ─── Data Models ──────────────────────────────────────────────────────


@dataclass
class Iso20022Party:
    """A financial institution or party in ISO 20022 format."""
    name: str = ""
    bic: str = ""  # Bank Identifier Code (SWIFT)
    account: str = ""
    country: str = ""


@dataclass
class Iso20022FxCxnAdvice:
    """ISO 20022 Foreign Exchange Confirmation (FXCD.001.001).

    This is the primary message type for CARIB-CLEAR — banks send these
    to confirm FX swap settlements.
    """
    message_id: str = ""
    trade_id: str = ""
    buyer: Iso20022Party = field(default_factory=Iso20022Party)
    seller: Iso20022Party = field(default_factory=Iso20022Party)
    trade_date: str = ""
    value_date: str = ""
    from_currency: str = ""
    to_currency: str = ""
    amount_from: float = 0.0
    amount_to: float = 0.0
    rate: float = 0.0
    settlement_method: str = "Stellar/USDC"
    status: str = "NEW"  # NEW, MATCHED, SETTLED, FAILED
    carib_clear_ref: str = ""  # Our internal reference

    def __post_init__(self):
        if not self.message_id:
            self.message_id = f"FXCD-{uuid.uuid4().hex[:12].upper()}"
        if not self.trade_id:
            self.trade_id = f"TRADE-{uuid.uuid4().hex[:8].upper()}"
        if not self.value_date:
            self.value_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")


@dataclass
class Iso20022PaymentInstruction:
    """ISO 20022 Payment Instruction (pacs.008).

    Banks use this to send credit transfer instructions through CARIB-CLEAR.
    """
    message_id: str = ""
    instruction_id: str = ""
    end_to_end_id: str = ""
    amount: float = 0.0
    currency: str = ""
    debtor: Iso20022Party = field(default_factory=Iso20022Party)
    debtor_account: str = ""
    creditor: Iso20022Party = field(default_factory=Iso20022Party)
    creditor_account: str = ""
    remittance_info: str = ""
    created_at: str = ""

    def __post_init__(self):
        if not self.message_id:
            self.message_id = f"PACS-{uuid.uuid4().hex[:12].upper()}"
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()


# ─── FX Confirmation (FXCD.001.001) ──────────────────────────────────


def generate_fx_confirmation_xml(advice: Iso20022FxCxnAdvice) -> str:
    """Generate ISO 20022 FX Confirmation XML (FXCD.001.001).

    This is what CARIB-CLEAR sends back to a bank after settling an FX swap.

    Args:
        advice: The FX confirmation data.

    Returns:
        ISO 20022 XML string.
    """
    ns_fx = NS["fx"]

    root = ET.Element(f"{{{ns_fx}}}FXCxnAdvice")
    root.set("xmlns", ns_fx)

    _add_element(root, "MsgId", advice.message_id)
    _add_element(root, "TradeId", advice.trade_id)
    _add_element(root, "CreDtTm", datetime.now(timezone.utc).isoformat())

    # Trade details
    trade = ET.SubElement(root, "TradDtls")
    _add_element(trade, "TradDt", advice.trade_date)
    _add_element(trade, "ValDt", advice.value_date)
    _add_element(trade, "SttlmMtd", advice.settlement_method)

    # Deal amount
    deal = ET.SubElement(root, "DealAmts")
    buy = ET.SubElement(deal, "BuyAmt")
    _add_element(buy, "Amt", f"{advice.amount_from:.2f}")
    _add_element(buy, "Ccy", advice.from_currency)
    sell = ET.SubElement(deal, "SellAmt")
    _add_element(sell, "Amt", f"{advice.amount_to:.2f}")
    _add_element(sell, "Ccy", advice.to_currency)

    # Exchange rate
    fx = ET.SubElement(root, "FXDtls")
    _add_element(fx, "XchgRate", f"{advice.rate:.6f}")

    # Parties
    if advice.buyer.name:
        prty = ET.SubElement(root, "Buyr")
        _add_element(prty, "Nm", advice.buyer.name)
        if advice.buyer.bic:
            _add_element(prty, "BIC", advice.buyer.bic)

    if advice.seller.name:
        prty = ET.SubElement(root, "Sellr")
        _add_element(prty, "Nm", advice.seller.name)
        if advice.seller.bic:
            _add_element(prty, "BIC", advice.seller.bic)

    # Status
    _add_element(root, "Sts", advice.status)

    # CARIB-CLEAR reference
    if advice.carib_clear_ref:
        _add_element(root, "Ref", advice.carib_clear_ref)

    return _pretty_xml(root)


def parse_fx_confirmation_xml(xml_str: str) -> Optional[Iso20022FxCxnAdvice]:
    """Parse ISO 20022 FX Confirmation XML into a data model.

    Args:
        xml_str: ISO 20022 XML string.

    Returns:
        Iso20022FxCxnAdvice or None if parsing fails.
    """
    try:
        root = ET.fromstring(xml_str)
        ns = _ns(root.tag)

        def _txt(path: str) -> str:
            """Get text from an XPath-like path within the root."""
            el = root.find(f".//{{{ns}}}{path}")
            return el.text.strip() if el is not None and el.text else ""

        def _float(path: str) -> float:
            val = _txt(path)
            try:
                return float(val) if val else 0.0
            except ValueError:
                return 0.0

        advice = Iso20022FxCxnAdvice(
            message_id=_txt("MsgId") or _txt("MsgId"),
            trade_id=_txt("TradeId"),
            trade_date=_txt("TradDtls/TradDt") or _txt("TradDt"),
            value_date=_txt("TradDtls/ValDt") or _txt("ValDt") or _txt("TradDtls/TradDt"),
            from_currency=_txt("DealAmts/BuyAmt/Ccy") or "USD",
            to_currency=_txt("DealAmts/SellAmt/Ccy") or "USD",
            amount_from=_float("DealAmts/BuyAmt/Amt"),
            amount_to=_float("DealAmts/SellAmt/Amt"),
            rate=_float("FXDtls/XchgRate") or 1.0,
            settlement_method=_txt("TradDtls/SttlmMtd") or "Stellar/USDC",
            status=_txt("Sts") or "NEW",
            carib_clear_ref=_txt("Ref"),
            buyer=Iso20022Party(
                name=_txt("Buyr/Nm"),
                bic=_txt("Buyr/BIC"),
            ),
            seller=Iso20022Party(
                name=_txt("Sellr/Nm"),
                bic=_txt("Sellr/BIC"),
            ),
        )
        return advice

    except ET.ParseError as e:
        logger.error("[ISO20022] XML parse error: %s", e)
        return None
    except Exception as e:
        logger.error("[ISO20022] Parse error: %s", e)
        return None


# ─── Payment Instruction (pacs.008.001) ──────────────────────────────


def generate_payment_xml(instruction: Iso20022PaymentInstruction) -> str:
    """Generate ISO 20022 Payment XML (pacs.008.001).

    Used when CARIB-CLEAR needs to send a payment instruction to a bank.
    """
    ns_pacs = NS["pacs"]

    root = ET.Element(f"{{{ns_pacs}}}FIToFICstmrCdtTrf")
    root.set("xmlns", ns_pacs)

    grp_hdr = ET.SubElement(root, "GrpHdr")
    _add_element(grp_hdr, "MsgId", instruction.message_id)
    _add_element(grp_hdr, "CreDtTm", instruction.created_at)
    _add_element(grp_hdr, "NbOfTxs", "1")
    _add_element(grp_hdr, "TtlIntrBkSttlmAmt", f"{instruction.amount:.2f}")
    _add_element(grp_hdr, "IntrBkSttlmDt",
                 datetime.now(timezone.utc).strftime("%Y-%m-%d"))

    cdt_trf_tx = ET.SubElement(root, "CdtTrfTxInf")

    pmt_id = ET.SubElement(cdt_trf_tx, "PmtId")
    _add_element(pmt_id, "InstrId", instruction.instruction_id)
    _add_element(pmt_id, "EndToEndId", instruction.end_to_end_id)

    amt = ET.SubElement(cdt_trf_tx, "IntrBkSttlmAmt")
    _add_element(amt, "Amt", f"{instruction.amount:.2f}")
    _add_element(amt, "Ccy", instruction.currency)

    if instruction.debtor.name:
        dbtr = ET.SubElement(cdt_trf_tx, "Dbtr")
        _add_element(dbtr, "Nm", instruction.debtor.name)

    if instruction.creditor.name:
        cdtr = ET.SubElement(cdt_trf_tx, "Cdtr")
        _add_element(cdtr, "Nm", instruction.creditor.name)

    if instruction.remittance_info:
        rmt = ET.SubElement(cdt_trf_tx, "RmtInf")
        _add_element(rmt, "Ustrd", instruction.remittance_info)

    return _pretty_xml(root)


def parse_payment_xml(xml_str: str) -> Optional[Iso20022PaymentInstruction]:
    """Parse ISO 20022 Payment XML into data model."""
    try:
        root = ET.fromstring(xml_str)
        ns = _ns(root.tag)

        def _txt(path: str) -> str:
            el = root.find(f".//{{{ns}}}{path}")
            return el.text.strip() if el is not None and el.text else ""

        def _float(path: str) -> float:
            val = _txt(path)
            return float(val) if val else 0.0

        return Iso20022PaymentInstruction(
            message_id=_txt("GrpHdr/MsgId"),
            instruction_id=_txt("CdtTrfTxInf/PmtId/InstrId") or _txt("GrpHdr/MsgId"),
            end_to_end_id=_txt("CdtTrfTxInf/PmtId/EndToEndId"),
            amount=_float("GrpHdr/TtlIntrBkSttlmAmt") or _float("CdtTrfTxInf/IntrBkSttlmAmt/Amt"),
            currency=_txt("CdtTrfTxInf/IntrBkSttlmAmt/Ccy") or "USD",
            debtor=Iso20022Party(name=_txt("CdtTrfTxInf/Dbtr/Nm")),
            creditor=Iso20022Party(name=_txt("CdtTrfTxInf/Cdtr/Nm")),
            remittance_info=_txt("CdtTrfTxInf/RmtInf/Ustrd"),
        )

    except ET.ParseError as e:
        logger.error("[ISO20022] Payment XML parse error: %s", e)
        return None
    except Exception as e:
        logger.error("[ISO20022] Payment parse error: %s", e)
        return None


# ─── Convert CARIB-CLEAR → ISO 20022 ─────────────────────────────────


def settlement_to_fx_advice(
    settlement_result: Any,
    from_ccy: str = "BBD",
    to_ccy: str = "JMD",
) -> Iso20022FxCxnAdvice:
    """Convert a CARIB-CLEAR SettlementResult to an ISO 20022 FX Confirmation.

    Args:
        settlement_result: A SettlementResult object from the broker.
        from_ccy: Source currency code.
        to_ccy: Destination currency code.

    Returns:
        Iso20022FxCxnAdvice ready for XML generation.
    """
    return Iso20022FxCxnAdvice(
        from_currency=from_ccy,
        to_currency=to_ccy,
        amount_from=getattr(settlement_result, "fill_quantity", 0) or 0,
        amount_to=0,  # Filled after rate calculation
        rate=getattr(settlement_result, "fill_price", 1) or 1,
        status="SETTLED" if getattr(settlement_result, "success", False) else "FAILED",
        carib_clear_ref=getattr(settlement_result, "tx_hash", "") or "",
        settlement_method="Stellar/USDC",
        trade_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        value_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        buyer=Iso20022Party(name="CARIB-CLEAR", bic="CCLRBBBB"),
        seller=Iso20022Party(name="CARIB-CLEAR", bic="CCLRBBBB"),
    )


# ─── HELPER: Generate CARIB-CLEAR response from ISO 20022 ────────────


def fx_advice_to_settlement_request(advice: Iso20022FxCxnAdvice) -> Dict[str, Any]:
    """Convert an ISO 20022 FX Confirmation to a CARIB-CLEAR settlement request.

    Banks send FXCD XML → we parse → convert to internal format → process.

    Args:
        advice: The parsed FX confirmation.

    Returns:
        Dict matching CARIB-CLEAR's internal settlement request format.
    """
    return {
        "from_currency": advice.from_currency,
        "to_currency": advice.to_currency,
        "amount_from": advice.amount_from,
        "amount_to": advice.amount_to,
        "rate": advice.rate,
        "trade_id": advice.trade_id,
        "message_id": advice.message_id,
        "buyer": {
            "name": advice.buyer.name,
            "bic": advice.buyer.bic,
        },
        "seller": {
            "name": advice.seller.name,
            "bic": advice.seller.bic,
        },
    }


# ─── Internal Helpers ────────────────────────────────────────────────


def _add_element(parent: ET.Element, tag: str, text: str) -> ET.Element:
    """Add a simple text element to an XML parent."""
    el = ET.SubElement(parent, tag)
    el.text = text
    return el


def _pretty_xml(root: ET.Element) -> str:
    """Convert an XML element tree to a pretty-printed string."""
    ET.indent(root, space="  ")
    declaration = '<?xml version="1.0" encoding="UTF-8"?>\n'
    return declaration + ET.tostring(root, encoding="unicode")


def _ns(tag: str) -> str:
    """Extract the namespace from a fully qualified XML tag."""
    if tag.startswith("{"):
        return tag[1:tag.index("}")]
    return ""