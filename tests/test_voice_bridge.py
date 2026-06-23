"""Tests for VoiceLoanBridge — intent extraction, language detection, formatting."""

from __future__ import annotations

from carib_clear.voice_bridge import (
    VoiceLoanBridge,
    KreyolAmountParser,
    LoanIntent,
    detect_language,
    extract_loan_intent,
    format_loan_response,
)


# ─── Language Detection ──────────────────────────────────────────────

def test_detect_english() -> None:
    """Verify English text is detected as English."""
    assert detect_language("I need a loan for my business") == "en"


def test_detect_kreyol() -> None:
    """Verify Kreyòl text is detected as Haitian Creole."""
    assert detect_language("Mwen bezwen lajan pou biznis mwen") == "ht"
    assert detect_language("Mwen vle $5,000") == "ht"


def test_detect_kreyol_short() -> None:
    """Verify short Kreyòl phrases are detected correctly."""
    assert detect_language("Mwen bezwen prè") == "ht"


# ─── Amount Parsing ──────────────────────────────────────────────────

def test_parse_dollar_sign() -> None:
    """Verify $5,000 is parsed as 5000."""
    assert KreyolAmountParser.parse_amount("I need $5,000") == 5000.0
    assert KreyolAmountParser.parse_amount("$100,000 please") == 100000.0


def test_parse_with_dollar_word() -> None:
    """Verify '5000 dollars' is parsed."""
    assert KreyolAmountParser.parse_amount("5000 dollars for my business") == 5000.0


def test_parse_kreyol_numbers() -> None:
    """Verify Kreyòl number words are parsed."""
    result = KreyolAmountParser.parse_amount("senk mil dola")
    assert result is not None
    assert result == 5000.0


def test_parse_kreyol_large() -> None:
    """Verify larger Kreyòl amounts are parsed."""
    result = KreyolAmountParser.parse_amount("dis mil dola")
    assert result is not None
    assert result == 10000.0


def test_parse_no_amount() -> None:
    """Verify text with no amount returns None."""
    assert KreyolAmountParser.parse_amount("Hello, I need a loan") is None


# ─── Intent Extraction ───────────────────────────────────────────────

def test_extract_english_intent() -> None:
    """Verify English loan request extracts correct intent."""
    intent = extract_loan_intent("I need $50,000 to expand my restaurant in Jamaica")
    assert intent.amount_usd == 50000.0
    assert intent.jurisdiction == "JM"
    assert intent.sector == "retail"
    assert intent.purpose == "expansion"


def test_extract_kreyol_intent() -> None:
    """Verify Kreyòl loan request extracts correct intent."""
    intent = extract_loan_intent("Mwen bezwen $25,000 pou biznis agrikilti mwen an Ayiti")
    assert intent.amount_usd == 25000.0
    assert intent.jurisdiction == "HT"
    assert intent.detected_language == "ht"


def test_extract_sector_agriculture() -> None:
    """Verify 'farming' maps to agriculture sector."""
    intent = extract_loan_intent("$10,000 for my farming business in Barbados")
    assert intent.sector == "agriculture"
    assert intent.jurisdiction == "BB"


def test_extract_sector_tech() -> None:
    """Verify 'tech startup' maps to tech sector."""
    intent = extract_loan_intent("$100,000 for tech startup in Trinidad")
    assert intent.sector == "tech"
    assert intent.jurisdiction == "TT"


def test_extract_default_country() -> None:
    """Verify missing country defaults to HT."""
    intent = extract_loan_intent("$5,000 for business")
    assert intent.jurisdiction == "HT"


def test_extract_business_name() -> None:
    """Verify business name extraction from pattern."""
    intent = extract_loan_intent("My business is called Atelier Kreyol")
    assert "Kreyol" in intent.business_name or intent.business_name != ""


# ─── Response Formatting ─────────────────────────────────────────────

def test_format_approved_english() -> None:
    """Verify approved response in English."""
    text = format_loan_response(approved=True, amount_usd=25000, interest_rate=12.0,
                                lender="IDB Invest", lang="en")
    assert "Congratulations" in text
    assert "25,000" in text
    assert "12.0%" in text


def test_format_approved_kreyol() -> None:
    """Verify approved response in Kreyòl."""
    text = format_loan_response(approved=True, amount_usd=5000, interest_rate=12.0,
                                lender="IDB Invest", lang="ht")
    assert "Felisitasyon" in text
    assert "5,000" in text


def test_format_denied() -> None:
    """Verify denied response."""
    text = format_loan_response(approved=False, amount_usd=5000,
                                rejection_reason="Insufficient credit score", lang="en")
    assert "unfortunately" in text.lower() or "not be approved" in text


def test_format_denied_kreyol() -> None:
    """Verify denied response in Kreyòl."""
    text = format_loan_response(approved=False, amount_usd=5000,
                                rejection_reason="Nòt kredi ou twò ba", lang="ht")
    assert "Malerezman" in text


# ─── Full Pipeline ───────────────────────────────────────────────────

def test_voice_bridge_english() -> None:
    """Verify full voice bridge pipeline with English input."""
    bridge = VoiceLoanBridge()
    result = bridge.process_request("I need $50,000 for agriculture in Jamaica")
    assert result.success is True
    assert result.response_text is not None


def test_voice_bridge_kreyol() -> None:
    """Verify full voice bridge pipeline with Kreyòl input."""
    bridge = VoiceLoanBridge()
    result = bridge.process_request("Mwen bezwen $50,000 pou agrikilti nan Ayiti")
    assert result.success is True
    assert result.response_text_ht is not None
    assert result.details["intent"]["detected_language"] == "ht"


def test_voice_bridge_history() -> None:
    """Verify bridge tracks history."""
    bridge = VoiceLoanBridge()
    bridge.process_request("$10,000 for business")
    assert len(bridge.get_history()) == 1
    assert "timestamp" in bridge.get_history()[0]