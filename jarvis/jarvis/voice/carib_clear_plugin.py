"""CARIB-CLEAR Plugin for JARVIS Voice — loan intent detection and processing.

When the user says something that looks like a loan request
(in English or Kreyòl), this plugin intercepts it and routes through
the CARIB-CLEAR MSME Credit pipeline instead of the general LLM.

Integration point: VoiceLLMClient.send() and VoiceLLMClient.stream_send()
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Optional

logger = logging.getLogger("jarvis.carib_clear")

# Lazy import to avoid circular deps / startup cost
_carib_clear_loaded = False
_voice_bridge = None


def _ensure_carib_clear():
    """Lazy-load CARIB-CLEAR modules (adds ~0.5s on first call)."""
    global _carib_clear_loaded, _voice_bridge
    if _carib_clear_loaded:
        return

    try:
        # Ensure the CARIB-CLEAR project root is on the path
        repo_root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
        )
        if repo_root not in sys.path:
            sys.path.insert(0, repo_root)

        from carib_clear.voice_bridge import VoiceLoanBridge

        _voice_bridge = VoiceLoanBridge()
        _carib_clear_loaded = True
        logger.info("[CARIB-CLEAR Plugin] VoiceLoanBridge loaded")
    except ImportError as e:
        logger.warning("[CARIB-CLEAR Plugin] Failed to load: %s", e)


# Loan intent keywords (English and Kreyòl)
LOAN_KEYWORDS = [
    # English
    "loan", "credit", "borrow", "financing", "lending", "funding",
    "i need $", "i need money", "i need cash", "business loan",
    "working capital", "inventory financing",
    # Kreyòl
    "prè", "lajan", "biznis", "kredi", "finansman",
    "mwen bezwen", "m bezwen", "ede m", "kòb",
    "lajan pou biznis", "prè biznis",
    # Dollar amounts
    "$5,000", "$10,000", "$15,000", "$20,000", "$25,000",
    "$50,000", "$100,000",
    "5000", "10000", "25000", "50000",
]


def is_loan_request(text: str) -> bool:
    """Check if user text looks like a loan/financing request."""
    lower = text.lower().strip()
    for kw in LOAN_KEYWORDS:
        if kw in lower:
            return True
    return False


def process_loan_request(text: str) -> Optional[str]:
    """Process a loan request through CARIB-CLEAR VoiceLoanBridge.

    Returns:
        The response text (in appropriate language) ready for TTS,
        or None if processing failed.
    """
    _ensure_carib_clear()
    if _voice_bridge is None:
        return None

    try:
        result = _voice_bridge.process_request(text)
        if result.success:
            # Return the Kreyòl response if the input was Kreyòl,
            # otherwise English
            if _detect_language(text) == "ht" and result.response_text_ht:
                return result.response_text_ht
            return result.response_text
        return None
    except Exception as e:
        logger.error("[CARIB-CLEAR Plugin] Processing error: %s", e)
        return None


def _detect_language(text: str) -> str:
    """Simple language detection: 'ht' for Kreyòl, 'en' for English."""
    ht_markers = [
        "mwen", "ou", "li", "nou", "yo", "ap", "pa", "pou",
        "prè", "lajan", "kòb", "biznis", "kredi",
        "bezwen", "ede", "mache", "travay",
    ]
    words = set(text.lower().split())
    ht_score = sum(1 for m in ht_markers if m in words)
    return "ht" if ht_score >= 2 else "en"
