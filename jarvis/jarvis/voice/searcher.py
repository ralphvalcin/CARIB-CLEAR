"""Web search via Tavily for the voice loop.

Provides live search results that get injected as context before
LLM calls, so JARVIS can answer questions about current events.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("jarvis.voice.search")

# Keywords that trigger a web search before answering
SEARCH_KEYWORDS = {
    "news", "weather", "forecast", "headlines", "current events",
    "today", "latest", "breaking", "update", "happening",
    "stock", "price", "score", "game", "match", "election",
    "what is", "what are", "who is", "what's", "who's",
    "tell me about", "how is", "how are",
    "temperature", "rain", "storm", "earthquake",
    "nba", "nfl", "mlb", "nhl", "soccer", "football", "baseball",
    "basketball", "hockey", "tennis", "sports",
    "president", "congress", "senate", "war", "conflict",
    "covid", "virus", "pandemic", "disease",
    "election", "vote", "poll",
    "schedule", "show", "movie", "release",
    "traffic", "flight", "delay",
    "date", "time is it", "day is",
}

_TAVILY_URL = "https://api.tavily.com/search"


def _resolve_tavily_key() -> Optional[str]:
    """Read Tavily API key from Hermes .env."""
    env_path = Path.home() / ".hermes" / ".env"
    if not env_path.exists():
        return None
    raw = env_path.read_bytes()
    m = re.search(rb"TAVILY_API_KEY=([^\s]+)", raw)
    return m.group(1).decode() if m else None


def needs_search(text: str) -> bool:
    """Check if a user utterance likely needs a web search."""
    t = text.lower().strip()
    for kw in SEARCH_KEYWORDS:
        if kw in t:
            return True
    return False


def search(query: str, max_results: int = 5) -> Optional[str]:
    """Search Tavily and return a formatted context string, or None on failure."""
    key = _resolve_tavily_key()
    if not key:
        logger.warning("No Tavily API key found")
        return None

    try:
        resp = httpx.post(
            _TAVILY_URL,
            json={
                "api_key": key,
                "query": query,
                "search_depth": "basic",
                "include_answer": True,
                "max_results": max_results,
            },
            timeout=15,
        )
        if resp.status_code != 200:
            logger.error("Tavily error %d: %s", resp.status_code, resp.text[:200])
            return None

        data: Dict[str, Any] = resp.json()
        answer = data.get("answer", "")
        results = data.get("results", [])

        parts: List[str] = []
        if answer:
            parts.append(f"Summary: {answer}")
        for r in results[:3]:
            title = r.get("title", "")
            content = r.get("content", "")[:200]
            if title and content:
                parts.append(f"- {title}: {content}")
            elif content:
                parts.append(f"- {content}")

        if parts:
            context = "Here are current web search results for context:\n" + "\n".join(parts)
            logger.info("Tavily search returned %d results for: %s", len(results), query[:60])
            return context
        return None

    except Exception as exc:
        logger.error("Tavily search failed: %s", exc)
        return None