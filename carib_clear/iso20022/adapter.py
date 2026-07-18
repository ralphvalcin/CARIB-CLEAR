"""ISO 20022 adapter — convert CARIB-CLEAR internal orders to/from bank messages.

Provides bidirectional conversion between CARIB-CLEAR's SettlementOrder
and ISO 20022 pacs.008 messages, enabling integration with any SWIFT MX-
compliant bank.

Usage:
    from carib_clear.iso20022 import ISO20022Adapter
    adapter = ISO20022Adapter()
    xml = adapter.order_to_pacs008(order)   # CARIB-CLEAR → ISO 20022
    order = adapter.pacs008_to_order(xml)   # ISO 20022 → CARIB-CLEAR
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
import logging

from .messages import (
    ISO20022Payment,
    ISO20022StatusReport,
    ISO20022FITransfer,
    generate_sample_payment,
    CARIB_CLEAR_BIC,
)

logger = logging.getLogger(__name__)


# ─── Currency-to-country mapping ─────────────────────────────────────

CURRENCY_COUNTRY = {
    "BBD": "BB", "JMD": "JM", "TTD": "TT",
    "XCD": "ECCB", "HTG": "HT", "USD": "US",
}

COUNTRY_BIC_PREFIX = {
    "BB": "BBNB", "JM": "JNCB", "TT": "TTCB",
    "ECCB": "ECCB", "HT": "BRBH", "US": "BOFA",
}


class ISO20022Adapter:
    """Converts CARIB-CLEAR internal orders to/from ISO 20022 bank messages.

    This is the bridge between CARIB-CLEAR's agent-based FX network and
    the standard financial messaging system used by banks worldwide.
    """

    @staticmethod
    def order_to_pacs008(order, debtor_name: str = "", creditor_name: str = "",
                          debtor_bic: str = "", creditor_bic: str = "") -> ISO20022Payment:
        """Convert a CARIB-CLEAR SettlementOrder into an ISO 20022 pacs.008 payment.

        Args:
            order: The CARIB-CLEAR settlement order.
            debtor_name: Sender's legal name.
            creditor_name: Receiver's legal name.
            debtor_bic: Sender bank BIC.
            creditor_bic: Receiver bank BIC.

        Returns:
            An ISO20022Payment ready to be serialized to XML.
        """
        from_country = CURRENCY_COUNTRY.get(order.from_currency, "BB")
        to_country = CURRENCY_COUNTRY.get(order.to_currency, "JM")

        if not debtor_bic:
            debtor_bic = COUNTRY_BIC_PREFIX.get(from_country, "NONC") + "BBBXXX"

        if not creditor_bic:
            creditor_bic = COUNTRY_BIC_PREFIX.get(to_country, "NONC") + "BBBXXX"

        return ISO20022Payment(
            debtor_name=debtor_name or order.participant_id or "CARIB-CLEAR Participant",
            debtor_account=order.participant_id or "CC-UNKNOWN",
            debtor_bic=debtor_bic,
            debtor_country=from_country,
            creditor_name=creditor_name or order.counterparty_id or "CARIB-CLEAR Beneficiary",
            creditor_account=order.counterparty_id or "CC-UNKNOWN",
            creditor_bic=creditor_bic,
            creditor_country=to_country,
            amount=order.amount_from,
            currency=order.from_currency,
            purpose="CCT",
            settlement_method="INGA",
            charge_bearer="SHAR",
            instruction_id=order.order_id,
        )

    @staticmethod
    def pacs008_to_order(payment: ISO20022Payment) -> dict:
        """Convert an ISO 20022 pacs.008 into a CARIB-CLEAR order dict.

        Returns a dict with keys: participant_id, counterparty_id,
        from_currency, to_currency, amount_from, amount_to, rate.

        The rate will be 0 (unknown) since pacs.008 only has one amount.
        """
        from_currency = _guess_currency(payment.debtor_country)
        to_currency = _guess_currency(payment.creditor_country)

        return {
            "participant_id": payment.debtor_account or payment.debtor_name,
            "counterparty_id": payment.creditor_account or payment.creditor_name,
            "from_currency": from_currency,
            "to_currency": to_currency,
            "amount_from": payment.amount,
            "amount_to": 0.0,  # Cannot determine from pacs.008 alone
            "rate": 0.0,
            "order_id": payment.instruction_id or payment.msg_id,
            "end_to_end_id": payment.end_to_end_id,
        }

    @staticmethod
    def create_status_report(original_msg_id: str, status: str,
                              reason: str = "", transaction_id: str = "") -> ISO20022StatusReport:
        """Create a pacs.002 status report for an original pacs.008.

        Args:
            original_msg_id: The msg_id of the original pacs.008.
            status: ACCP (accepted), RJCT (rejected), PDNG (pending).
            reason: Optional rejection reason.
            transaction_id: CARIB-CLEAR transaction reference.

        Returns:
            An ISO20022StatusReport ready for XML.
        """
        return ISO20022StatusReport(
            original_msg_id=original_msg_id,
            status=status,
            reason=reason,
            transaction_id=transaction_id,
        )

    @staticmethod
    def create_fi_transfer(from_bic: str, to_bic: str,
                            amount: float, currency: str) -> ISO20022FITransfer:
        """Create a pacs.009 FI-to-FI transfer for settlement between banks."""
        return ISO20022FITransfer(
            from_bic=from_bic,
            to_bic=to_bic,
            amount=amount,
            currency=currency,
        )


def _guess_currency(country_code: str) -> str:
    """Guess a currency from a country code."""
    mapping = {"BB": "BBD", "JM": "JMD", "TT": "TTD", "ECCB": "XCD", "HT": "HTG", "US": "USD"}
    return mapping.get(country_code, "USD")
