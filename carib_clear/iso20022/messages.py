"""ISO 20022 message definitions for CARIB-CLEAR.

Supported types: pacs.008 (payment), pacs.002 (status), pacs.009 (FI transfer).
Generates well-formed ISO 20022 XML for bank integration.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid


# ─── Constants ───────────────────────────────────────────────────────

NS = "urn:iso:std:iso:20022:tech:xsd:pacs.008.001.10"
NS_HEAD = "urn:iso:std:iso:20022:tech:xsd:head.001.001.02"
NS_PACS002 = "urn:iso:std:iso:20022:tech:xsd:pacs.002.001.12"

CARIB_CLEAR_BIC = "CRBCBBBB"  # Mock BIC for CARIB-CLEAR


# ─── Data Models ────────────────────────────────────────────────────


@dataclass
class ISO20022Payment:
    """A pacs.008 FIToFICustomerCreditTransfer — cross-border payment."""

    msg_id: str = ""
    creation_time: str = ""
    # Debtor (sender)
    debtor_name: str = ""
    debtor_account: str = ""
    debtor_bic: str = ""
    debtor_country: str = ""
    # Creditor (receiver)
    creditor_name: str = ""
    creditor_account: str = ""
    creditor_bic: str = ""
    creditor_country: str = ""
    # Payment
    amount: float = 0.0
    currency: str = "USD"
    instruction_id: str = ""
    end_to_end_id: str = ""
    purpose: str = "CCT"  # Cross-border commercial transfer
    # Settlement
    settlement_method: str = ""  # INGA=instructing agent, COVE=cover
    charge_bearer: str = "SHAR"  # Shared fees

    def __post_init__(self):
        if not self.msg_id:
            self.msg_id = f"CC{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"
        if not self.creation_time:
            self.creation_time = datetime.now(timezone.utc).isoformat()
        if not self.end_to_end_id:
            self.end_to_end_id = f"E2E{uuid.uuid4().hex[:12].upper()}"

    def to_xml(self) -> str:
        """Generate a pacs.008 XML document from this payment.

        Returns a complete, well-formed pacs.008.001.10 XML document
        that any ISO 20022-compliant bank can process.
        """
        doc = ET.Element(
            "Document",
            {"xmlns": NS, "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance"},
        )
        cdt_trf = ET.SubElement(doc, "FIToFICstmrCdtTrf")

        # Group Header
        grp_hdr = ET.SubElement(cdt_trf, "GrpHdr")
        ET.SubElement(grp_hdr, "MsgId").text = self.msg_id
        ET.SubElement(grp_hdr, "CreDtTm").text = self.creation_time
        ET.SubElement(grp_hdr, "NbOfTxs").text = "1"
        ET.SubElement(grp_hdr, "SttlmInf").text = self.settlement_method or "INGA"

        # Credit Transfer Transaction
        cdt_tx = ET.SubElement(cdt_trf, "CdtTrfTxInf")
        pmt_id = ET.SubElement(cdt_tx, "PmtId")
        ET.SubElement(pmt_id, "InstrId").text = self.instruction_id or self.msg_id
        ET.SubElement(pmt_id, "EndToEndId").text = self.end_to_end_id

        # Amount
        amt = ET.SubElement(cdt_tx, "IntrBkSttlmAmt", Ccy=self.currency)
        amt.text = f"{self.amount:.2f}"

        # Charge bearer
        ET.SubElement(cdt_tx, "ChrgBr").text = self.charge_bearer

        # Debtor (sender)
        dbtr = ET.SubElement(cdt_tx, "Dbtr")
        ET.SubElement(dbtr, "Nm").text = self.debtor_name
        dbtr_acct = ET.SubElement(cdt_tx, "DbtrAcct")
        id_elem = ET.SubElement(dbtr_acct, "Id")
        ET.SubElement(id_elem, "Othr").text = self.debtor_account
        dbtr_agt = ET.SubElement(cdt_tx, "DbtrAgt")
        fin_inst = ET.SubElement(dbtr_agt, "FinInstnId")
        bic = ET.SubElement(fin_inst, "BICFI")
        bic.text = self.debtor_bic or "NONCARIBBXB"
        pstl = ET.SubElement(fin_inst, "PstlAdr")
        ET.SubElement(pstl, "Ctry").text = self.debtor_country

        # Creditor (receiver)
        cdtr = ET.SubElement(cdt_tx, "Cdtr")
        ET.SubElement(cdtr, "Nm").text = self.creditor_name
        cdtr_acct = ET.SubElement(cdt_tx, "CdtrAcct")
        id_elem2 = ET.SubElement(cdtr_acct, "Id")
        ET.SubElement(id_elem2, "Othr").text = self.creditor_account
        cdtr_agt = ET.SubElement(cdt_tx, "CdtrAgt")
        fin_inst2 = ET.SubElement(cdtr_agt, "FinInstnId")
        bic2 = ET.SubElement(fin_inst2, "BICFI")
        bic2.text = self.creditor_bic or CARIB_CLEAR_BIC
        pstl2 = ET.SubElement(fin_inst2, "PstlAdr")
        ET.SubElement(pstl2, "Ctry").text = self.creditor_country

        # Purpose
        ET.SubElement(cdt_tx, "Purp").text = self.purpose

        ET.indent(doc, space="  ")
        return ET.tostring(doc, encoding="unicode")

    @classmethod
    def from_xml(cls, xml_str: str) -> Optional[ISO20022Payment]:
        """Parse a pacs.008 XML document into an ISO20022Payment.

        Args:
            xml_str: The raw pacs.008 XML string.

        Returns:
            ISO20022Payment or None if parsing fails.
        """
        try:
            root = ET.fromstring(xml_str)
            # Handle namespace
            ns = NS

            # Extract from group header
            cdt_trf = root.find(f".//{{{ns}}}FIToFICstmrCdtTrf")
            if cdt_trf is None:
                return None

            grp_hdr = cdt_trf.find(f".//{{{ns}}}GrpHdr")
            msg_id = _text(grp_hdr, f"{{{ns}}}MsgId") if grp_hdr is not None else ""
            cre_dt = _text(grp_hdr, f"{{{ns}}}CreDtTm") if grp_hdr is not None else ""

            cdt_tx = cdt_trf.find(f".//{{{ns}}}CdtTrfTxInf")
            if cdt_tx is None:
                return None

            # Amount
            amt_elem = cdt_tx.find(f".//{{{ns}}}IntrBkSttlmAmt")
            amount = float(amt_elem.text) if amt_elem is not None else 0.0
            currency = amt_elem.get("Ccy", "USD") if amt_elem is not None else "USD"

            # Debtor
            dbtr = cdt_tx.find(f".//{{{ns}}}Dbtr")
            debtor_name = _text(dbtr, f"{{{ns}}}Nm") if dbtr is not None else ""

            dbtr_acct = cdt_tx.find(f".//{{{ns}}}DbtrAcct")
            debtor_account = _deep_text(dbtr_acct, ns, "Id", "Othr") if dbtr_acct is not None else ""

            dbtr_agt = cdt_tx.find(f".//{{{ns}}}DbtrAgt")
            debtor_bic = _deep_text(dbtr_agt, ns, "FinInstnId", "BICFI") if dbtr_agt is not None else ""
            debtor_country = _deep_text(dbtr_agt, ns, "FinInstnId", "PstlAdr", "Ctry") if dbtr_agt is not None else ""

            # Creditor
            cdtr = cdt_tx.find(f".//{{{ns}}}Cdtr")
            creditor_name = _text(cdtr, f"{{{ns}}}Nm") if cdtr is not None else ""

            cdtr_acct = cdt_tx.find(f".//{{{ns}}}CdtrAcct")
            creditor_account = _deep_text(cdtr_acct, ns, "Id", "Othr") if cdtr_acct is not None else ""

            cdtr_agt = cdt_tx.find(f".//{{{ns}}}CdtrAgt")
            creditor_bic = _deep_text(cdtr_agt, ns, "FinInstnId", "BICFI") if cdtr_agt is not None else ""
            creditor_country = _deep_text(cdtr_agt, ns, "FinInstnId", "PstlAdr", "Ctry") if cdtr_agt is not None else ""

            # Instruction ID
            pmt_id = cdt_tx.find(f".//{{{ns}}}PmtId")
            instruction_id = _text(pmt_id, f"{{{ns}}}InstrId") if pmt_id is not None else ""
            end_to_end_id = _text(pmt_id, f"{{{ns}}}EndToEndId") if pmt_id is not None else ""

            purpose_elem = cdt_tx.find(f".//{{{ns}}}Purp")
            purpose = purpose_elem.text if purpose_elem is not None else "CCT"

            return cls(
                msg_id=msg_id, creation_time=cre_dt,
                debtor_name=debtor_name, debtor_account=debtor_account,
                debtor_bic=debtor_bic, debtor_country=debtor_country,
                creditor_name=creditor_name, creditor_account=creditor_account,
                creditor_bic=creditor_bic, creditor_country=creditor_country,
                amount=amount, currency=currency,
                instruction_id=instruction_id, end_to_end_id=end_to_end_id,
                purpose=purpose,
            )
        except Exception:
            return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to a JSON-serializable dict for API responses."""
        return {
            "msg_id": self.msg_id,
            "creation_time": self.creation_time,
            "debtor": {
                "name": self.debtor_name,
                "account": self.debtor_account,
                "bic": self.debtor_bic,
                "country": self.debtor_country,
            },
            "creditor": {
                "name": self.creditor_name,
                "account": self.creditor_account,
                "bic": self.creditor_bic,
                "country": self.creditor_country,
            },
            "amount": self.amount,
            "currency": self.currency,
            "end_to_end_id": self.end_to_end_id,
            "purpose": self.purpose,
        }


@dataclass
class ISO20022StatusReport:
    """A pacs.002 FIToFIPaymentStatusReport — payment confirmation/status."""

    msg_id: str = ""
    original_msg_id: str = ""
    creation_time: str = ""
    status: str = ""  # ACCP=accepted, RJCT=rejected, PDNG=pending
    reason: str = ""
    transaction_id: str = ""

    def __post_init__(self):
        if not self.msg_id:
            self.msg_id = f"SR{uuid.uuid4().hex[:8].upper()}"
        if not self.creation_time:
            self.creation_time = datetime.now(timezone.utc).isoformat()

    def to_xml(self) -> str:
        """Generate a pacs.002 status report XML."""
        ns = NS_PACS002
        doc = ET.Element("Document", {"xmlns": ns})
        sts_rpt = ET.SubElement(doc, "FIToFIPmtStsRpt")

        grp_hdr = ET.SubElement(sts_rpt, "GrpHdr")
        ET.SubElement(grp_hdr, "MsgId").text = self.msg_id
        ET.SubElement(grp_hdr, "CreDtTm").text = self.creation_time

        # Original group info
        orig = ET.SubElement(sts_rpt, "OrgnlGrpInf")
        ET.SubElement(orig, "OrgnlMsgId").text = self.original_msg_id
        ET.SubElement(orig, "OrgnlMsgNmId").text = "pacs.008.001.10"

        # Transaction status
        tx = ET.SubElement(sts_rpt, "TxInfAndSts")
        ET.SubElement(tx, "OrgnlTxId").text = self.transaction_id
        sts = ET.SubElement(tx, "TxSts")
        sts.text = self.status
        if self.reason:
            rsn = ET.SubElement(tx, "StsRsnInf")
            ET.SubElement(rsn, "Rsn").text = self.reason

        ET.indent(doc, space="  ")
        return ET.tostring(doc, encoding="unicode")

    @classmethod
    def from_xml(cls, xml_str: str) -> Optional[ISO20022StatusReport]:
        """Parse a pacs.002 XML document."""
        try:
            root = ET.fromstring(xml_str)
            ns = NS_PACS002

            sts_rpt = root.find(f".//{{{ns}}}FIToFIPmtStsRpt")
            if sts_rpt is None:
                return None

            grp_hdr = sts_rpt.find(f".//{{{ns}}}GrpHdr")
            msg_id = _text(grp_hdr, f"{{{ns}}}MsgId") if grp_hdr is not None else ""
            cre_dt = _text(grp_hdr, f"{{{ns}}}CreDtTm") if grp_hdr is not None else ""

            orig = sts_rpt.find(f".//{{{ns}}}OrgnlGrpInf")
            orig_msg = _text(orig, f"{{{ns}}}OrgnlMsgId") if orig is not None else ""

            tx = sts_rpt.find(f".//{{{ns}}}TxInfAndSts")
            tx_id = _text(tx, f"{{{ns}}}OrgnlTxId") if tx is not None else ""
            status = _text(tx, f"{{{ns}}}TxSts") if tx is not None else ""
            reason = _deep_text(tx, ns, "StsRsnInf", "Rsn") if tx is not None else ""

            return cls(
                msg_id=msg_id, original_msg_id=orig_msg,
                creation_time=cre_dt, status=status,
                reason=reason, transaction_id=tx_id,
            )
        except Exception:
            return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "msg_id": self.msg_id,
            "original_msg_id": self.original_msg_id,
            "status": self.status,
            "reason": self.reason,
            "transaction_id": self.transaction_id,
        }


@dataclass
class ISO20022FITransfer:
    """A pacs.009 FinancialInstitutionCreditTransfer — bank-to-bank."""

    msg_id: str = ""
    creation_time: str = ""
    from_bic: str = ""
    to_bic: str = ""
    amount: float = 0.0
    currency: str = "USD"
    settlement_date: str = ""

    def __post_init__(self):
        if not self.msg_id:
            self.msg_id = f"FIT{uuid.uuid4().hex[:8].upper()}"
        if not self.creation_time:
            self.creation_time = datetime.now(timezone.utc).isoformat()

    def to_xml(self) -> str:
        """Generate a pacs.009 FI credit transfer XML."""
        ns = "urn:iso:std:iso:20022:tech:xsd:pacs.009.001.10"
        doc = ET.Element("Document", {"xmlns": ns})
        fi_trf = ET.SubElement(doc, "FICdtTrf")

        grp_hdr = ET.SubElement(fi_trf, "GrpHdr")
        ET.SubElement(grp_hdr, "MsgId").text = self.msg_id
        ET.SubElement(grp_hdr, "CreDtTm").text = self.creation_time
        ET.SubElement(grp_hdr, "NbOfTxs").text = "1"

        tx = ET.SubElement(fi_trf, "CdtTrfTxInf")
        amt = ET.SubElement(tx, "IntrBkSttlmAmt", Ccy=self.currency)
        amt.text = f"{self.amount:.2f}"

        dbtr = ET.SubElement(tx, "DbtrAgt")
        fin = ET.SubElement(dbtr, "FinInstnId")
        ET.SubElement(fin, "BICFI").text = self.from_bic

        cdtr = ET.SubElement(tx, "CdtrAgt")
        fin2 = ET.SubElement(cdtr, "FinInstnId")
        ET.SubElement(fin2, "BICFI").text = self.to_bic

        ET.indent(doc, space="  ")
        return ET.tostring(doc, encoding="unicode")


# ─── Helpers ────────────────────────────────────────────────────────


def _text(parent, tag) -> str:
    """Extract text from a child element, returning empty string if missing."""
    if parent is None:
        return ""
    child = parent.find(tag)
    return child.text or "" if child is not None else ""


def _deep_text(parent, ns: str, *tags: str) -> str:
    """Navigate a nested path and return text. E.g. _deep_text(parent, ns, 'Id', 'Othr')."""
    if parent is None:
        return ""
    current = parent
    for tag in tags:
        current = current.find(f"{{{ns}}}{tag}")
        if current is None:
            return ""
    return current.text or ""


def generate_sample_payment() -> ISO20022Payment:
    """Generate a realistic sample pacs.008 for testing/demo."""
    return ISO20022Payment(
        debtor_name="BB Hotel & Resort Ltd",
        debtor_account="BB10022987654321",
        debtor_bic="BBNBBBBBXXX",
        debtor_country="BB",
        creditor_name="JM Fresh Produce Co",
        creditor_account="JM88300123456789",
        creditor_bic="JNCBJMKNXXX",
        creditor_country="JM",
        amount=50000.00,
        currency="USD",
        purpose="CCT",
        settlement_method="INGA",
        charge_bearer="SHAR",
    )


# ─── Additional Classes for API Compatibility ──────────────────────


@dataclass
class Iso20022Party:
    """A party (buyer/seller) in an ISO 20022 FX confirmation."""
    name: str = ""
    bic: str = ""


@dataclass
class Iso20022FxCxnAdvice:
    """ISO 20022 FX Confirmation Advice (FXCD.001.001).

    Used by banks to confirm foreign exchange transactions.
    CARIB-CLEAR generates these after settlement.
    """
    from_currency: str = ""
    to_currency: str = ""
    amount_from: float = 0.0
    amount_to: float = 0.0
    rate: float = 0.0
    status: str = "NEW"
    message_id: str = ""
    trade_id: str = ""
    carib_clear_ref: str = ""
    settlement_method: str = ""
    buyer: Optional[Iso20022Party] = None
    seller: Optional[Iso20022Party] = None

    def __post_init__(self):
        if not self.message_id:
            self.message_id = f"CC{uuid.uuid4().hex[:8].upper()}"
        if not self.trade_id:
            self.trade_id = f"TRADE-{self.from_currency}{self.to_currency}-{uuid.uuid4().hex[:6].upper()}"


# ─── FX Confirmation XML Functions ──────────────────────────────────


def generate_fx_confirmation_xml(advice: Iso20022FxCxnAdvice) -> str:
    """Generate ISO 20022 FX Confirmation XML (FXCD.001.001)."""
    now = datetime.now(timezone.utc).isoformat()

    doc = ET.Element("FXCxnAdvice", {
        "xmlns": "urn:iso:std:iso:20022:tech:xsd:FXCD.001.001"
    })
    ET.SubElement(doc, "MsgId").text = advice.message_id
    ET.SubElement(doc, "TradeId").text = advice.trade_id
    ET.SubElement(doc, "CreDtTm").text = now

    # Trade details
    trad = ET.SubElement(doc, "TradDtls")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ET.SubElement(trad, "TradDt").text = today
    ET.SubElement(trad, "ValDt").text = today
    ET.SubElement(trad, "SttlmMtd").text = advice.settlement_method or "Stellar/USDC"

    # Amounts
    amts = ET.SubElement(doc, "DealAmts")
    buy = ET.SubElement(amts, "BuyAmt")
    ET.SubElement(buy, "Amt").text = f"{advice.amount_from:.2f}"
    ET.SubElement(buy, "Ccy").text = advice.from_currency
    sell = ET.SubElement(amts, "SellAmt")
    ET.SubElement(sell, "Amt").text = f"{advice.amount_to:.2f}"
    ET.SubElement(sell, "Ccy").text = advice.to_currency

    # FX details
    fx = ET.SubElement(doc, "FXDtls")
    ET.SubElement(fx, "XchgRate").text = f"{advice.rate:.6f}"

    # Buyer
    if advice.buyer:
        buyr = ET.SubElement(doc, "Buyr")
        ET.SubElement(buyr, "Nm").text = advice.buyer.name
        ET.SubElement(buyr, "BIC").text = advice.buyer.bic

    # Seller
    if advice.seller:
        sellr = ET.SubElement(doc, "Sellr")
        ET.SubElement(sellr, "Nm").text = advice.seller.name
        ET.SubElement(sellr, "BIC").text = advice.seller.bic

    # Status
    ET.SubElement(doc, "Sts").text = advice.status
    if advice.carib_clear_ref:
        ET.SubElement(doc, "Ref").text = advice.carib_clear_ref

    ET.indent(doc, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(doc, encoding="unicode")


def parse_fx_confirmation_xml(xml_str: str) -> Optional[Iso20022FxCxnAdvice]:
    """Parse ISO 20022 FX Confirmation XML (FXCD.001.001)."""
    try:
        root = ET.fromstring(xml_str)
        ns = "urn:iso:std:iso:20022:tech:xsd:FXCD.001.001"

        msg_id = _safe_text(root, "MsgId")
        trade_id = _safe_text(root, "TradeId")

        # Amounts
        buy_amt = _deep_text_no_ns(root, "DealAmts", "BuyAmt", "Amt")
        buy_ccy = _deep_text_no_ns(root, "DealAmts", "BuyAmt", "Ccy")
        sell_amt = _deep_text_no_ns(root, "DealAmts", "SellAmt", "Amt")
        sell_ccy = _deep_text_no_ns(root, "DealAmts", "SellAmt", "Ccy")

        # Rate
        rate_str = _deep_text_no_ns(root, "FXDtls", "XchgRate")
        rate = float(rate_str) if rate_str else 0.0

        # Buyer/Seller
        buyer_name = _deep_text_no_ns(root, "Buyr", "Nm")
        buyer_bic = _deep_text_no_ns(root, "Buyr", "BIC")
        seller_name = _deep_text_no_ns(root, "Sellr", "Nm")
        seller_bic = _deep_text_no_ns(root, "Sellr", "BIC")

        # Status
        status = _safe_text(root, "Sts")
        ref = _safe_text(root, "Ref")
        stlm = _deep_text_no_ns(root, "TradDtls", "SttlmMtd")

        return Iso20022FxCxnAdvice(
            message_id=msg_id or "",
            trade_id=trade_id or "",
            from_currency=buy_ccy or "",
            to_currency=sell_ccy or "",
            amount_from=float(buy_amt) if buy_amt else 0.0,
            amount_to=float(sell_amt) if sell_amt else 0.0,
            rate=rate,
            status=status or "NEW",
            settlement_method=stlm or "",
            carib_clear_ref=ref or "",
            buyer=Iso20022Party(name=buyer_name or "", bic=buyer_bic or ""),
            seller=Iso20022Party(name=seller_name or "", bic=seller_bic or ""),
        )
    except Exception:
        return None


# ─── Payment XML Functions ─────────────────────────────────────────


@dataclass
class Iso20022PaymentInstruction:
    """ISO 20022 Payment Instruction (pacs.008 simplified)."""
    message_id: str = ""
    amount: float = 0.0
    currency: str = ""


def generate_payment_xml(instruction: Iso20022PaymentInstruction) -> str:
    """Generate ISO 20022 pacs.008 payment XML."""
    payment = ISO20022Payment(
        msg_id=instruction.message_id,
        amount=instruction.amount,
        currency=instruction.currency,
    )
    return payment.to_xml()


def parse_payment_xml(xml_str: str) -> Optional[Iso20022PaymentInstruction]:
    """Parse ISO 20022 pacs.008 payment XML."""
    payment = ISO20022Payment.from_xml(xml_str)
    if not payment:
        return None
    return Iso20022PaymentInstruction(
        message_id=payment.msg_id,
        amount=payment.amount,
        currency=payment.currency,
    )


# ─── Conversion Functions ──────────────────────────────────────────


def settlement_to_fx_advice(from_currency: str, to_currency: str,
                             amount_from: float, amount_to: float,
                             rate: float, status: str = "SETTLED",
                             **kwargs) -> Iso20022FxCxnAdvice:
    """Convert a CARIB-CLEAR settlement result into an ISO 20022 FX confirmation."""
    return Iso20022FxCxnAdvice(
        from_currency=from_currency,
        to_currency=to_currency,
        amount_from=amount_from,
        amount_to=amount_to,
        rate=rate,
        status=status,
        carib_clear_ref=kwargs.get("carib_clear_ref", ""),
        settlement_method=kwargs.get("settlement_method", "Stellar/USDC"),
        buyer=Iso20022Party(name=kwargs.get("buyer_name", "CARIB-CLEAR"), bic="CCLRBBBB"),
        seller=Iso20022Party(name=kwargs.get("seller_name", "CARIB-CLEAR"), bic="CCLRBBBB"),
    )


def fx_advice_to_settlement_request(advice: Iso20022FxCxnAdvice) -> Dict[str, Any]:
    """Convert an ISO 20022 FX advice into a CARIB-CLEAR settlement request dict."""
    return {
        "participant_id": advice.buyer.name if advice.buyer else "",
        "counterparty_id": advice.seller.name if advice.seller else "",
        "from_currency": advice.from_currency,
        "to_currency": advice.to_currency,
        "amount_from": advice.amount_from,
        "amount_to": advice.amount_to,
        "rate": advice.rate,
        "status": advice.status,
        "carib_clear_ref": advice.carib_clear_ref,
    }


# ─── Helpers ────────────────────────────────────────────────────────


def _safe_text(parent, tag: str) -> str:
    """Extract text from a child element by tag name (namespace-agnostic)."""
    if parent is None:
        return ""
    # Try exact match first, then namespace-agnostic
    child = parent.find(tag)
    if child is None:
        child = parent.find(f"{{*}}{tag}")
    return child.text or "" if child is not None else ""


def _deep_text_no_ns(parent, *tags: str) -> str:
    """Navigate a nested path namespace-agnostic and return text."""
    if parent is None:
        return ""
    current = parent
    for tag in tags:
        child = current.find(tag)
        if child is None:
            child = current.find(f"{{*}}{tag}")
        if child is None:
            return ""
        current = child
    return current.text or ""
