"""Intent router: maps natural language to action paths."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Literal, Optional

RoutePath = Literal["direct_response", "tool_action", "drift_check", "memory_action", "drift_repair"]


@dataclass
class RouteDecision:
    path: RoutePath
    tool_name: Optional[str] = None
    tool_args: Optional[Dict[str, Any]] = None
    quick_response: Optional[str] = None  # Set = skip LLM, use this directly


# ── Conversational shortcuts ─────────────────────────────────────────────────
# These match common chit-chat patterns and return instant responses,
# bypassing the LLM entirely. Add new patterns here as needed.

_QUICK_RESPONSES: list[tuple[list[str], str]] = [
    # Greetings
    (["hello", "hi ", "hey ", "howdy", "sup ", "yo ", "what's up", "whats up"],
     "Hey there! I'm listening. What do you need?"),
    (["good morning", "good evening", "good afternoon", "morning ", "evening "],
     "Good to hear from you! Ready when you are."),
    # How are you
    (["how are you", "how ya doing", "how you doing", "how do you feel", "how's it going", "hows it going"],
     "I'm doing great — all systems online and ready to help. What's on your mind?"),
    # Thanks
    (["thank you", "thanks ", "thx ", "appreciate it", "good job", "nice work"],
     "You're welcome! Happy to help."),
    # Farewells
    (["goodbye", "bye ", "see ya", "see you", "peace out", "later ", "gotta go", "i'm done", "i'm leaving"],
     "Catch you later! I'll be here if you need me."),
    # Affirmation / agreement — use word boundaries to avoid false positives
    ([" yes ", " yeah ", " yep ", " sure ", " okay ", " alright ", " correct ", " indeed ", "yes please", "sure thing", "that's right", "that is right", "you're right", "you are right"],
     "Got it. What's next?"),
    # Negation — use word boundaries
    ([" no ", " nope ", " nah ", "not really", "never mind", "forget it", "nothing"],
     "No problem. Just say the word when you need something."),
    # Status / presence
    (["are you there", "you there", "hello jarvis", "hey jarvis", "jarvis ", "listen", "wake up"],
     "Right here and ready. What can I do for you?"),
    # Identity
    (["who are you", "what are you", "tell me about yourself", "your name"],
     "I'm JARVIS — your voice-controlled assistant. I can run commands, search the web, manage tasks, and more."),
    # Capabilities
    (["what can you do", "help ", "commands", "capabilities", "features"],
     "I can execute commands, search the web, check system drift, manage memory, and answer questions. Just tell me what you need."),
    # Time / date
    (["what time", "current time", "time is it", "tell me the time", "what's the date", "todays date", "today's date"],
     "I'd need to check the system clock for that. Try 'run command date' if you'd like the exact time."),
    # Confusion / don't understand
    (["i don't know", "i'm not sure", "idk", "whatever", "never mind", "doesn't matter"],
     "No worries. Take your time — I'm here whenever you're ready."),
]


class IntentRouter:
    """Route-first MVP router with memory and repair support.

    Routes:
    - drift_check → check for missing capabilities
    - drift_repair → attempt to fix drift automatically
    - memory_action → save/recall conversation facts
    - tool_action → execute a Hermes/local tool
    - direct_response → LLM-generated conversational response
                     (or quick_response if a pattern matches)
    """

    def route(self, text: str) -> RouteDecision:
        t = text.lower().strip()

        # ── Drift commands ────────────────────────────────────────────────
        if any(k in t for k in ["drift", "capability", "self-knowledge"]):
            return RouteDecision(path="drift_check")

        if any(x in t for x in ["fix yourself", "repair yourself", "fix drift", "self-repair", "self repair"]):
            return RouteDecision(path="drift_repair")

        # ── Memory commands ────────────────────────────────────────────────
        if t.startswith("remember") or t.startswith("don't forget") or t.startswith("dont forget"):
            return RouteDecision(path="memory_action", tool_name="memory_save")

        if any(q in t for q in ["what did we talk about", "what were we doing", "what was i working on",
                                 "recall", "what did i ask", "what happened", "earlier"]):
            return RouteDecision(path="memory_action", tool_name="memory_search")

        if any(q in t for q in ["forget", "clear memory", "erase memory", "clear history"]):
            return RouteDecision(path="memory_action", tool_name="memory_clear")

        # ── Tool commands ──────────────────────────────────────────────────
        if any(k in t for k in ["run command", "shell", "terminal"]):
            return RouteDecision(
                path="tool_action",
                tool_name="terminal",
                tool_args={"command": text.strip(), "timeout": 120},
            )

        if any(k in t for k in ["search", "look up", "find", "web", "news", "headlines",
                              "what's happening", "whats happening", "current events",
                              "world news", "latest news"]):
            query = text.strip()
            return RouteDecision(
                path="tool_action",
                tool_name="web_search",
                tool_args={"query": query, "limit": 5},
            )

        # ── Conversational shortcuts ─────────────────────────────────────
        # Check quick-response patterns before falling through to LLM
        for keywords, reply in _QUICK_RESPONSES:
            if any(kw in t for kw in keywords):
                return RouteDecision(
                    path="direct_response",
                    quick_response=reply,
                )

        # ── Everything else → LLM conversation ──────────────────────────
        return RouteDecision(path="direct_response")