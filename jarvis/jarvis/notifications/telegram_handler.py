"""Telegram message handler for JARVIS — routes commands and conversations.

Routes every incoming message through JARVIS's API. Special commands
get direct API calls; everything else goes through /control/ingest
for LLM-powered conversation.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import URLError
from urllib.request import Request, urlopen

logger = logging.getLogger("jarvis.notifications.telegram_handler")

# ── Command definitions ──────────────────────────────────────────────────────

COMMANDS = {
    "start": "🤖 JARVIS Telegram Bot — talk to me like you would in person!",
    "help": "Show this help message",
    "status": "📊 Show system health and capability status",
    "drift": "🔍 Run a capability drift check with auto-repair",
    "approve": "✅ Approve a pending action (use: /approve <id>)",
    "deny": "❌ Deny a pending action (use: /deny <id>)",
    "memory": "🧠 Show what JARVIS remembers",
    "forget": "🗑️ Clear conversation history",
}


class TelegramHandler:
    """Routes Telegram messages to JARVIS API endpoints.

    Works entirely via HTTP to the JARVIS API server (localhost:8000).
    No direct imports from JARVIS modules — works standalone.
    """

    def __init__(self, api_url: str = "http://localhost:8000") -> None:
        self.api_url = api_url.rstrip("/")
        # Map chat_id to session_id for conversation continuity
        self._sessions: Dict[str, str] = {}

    def _session_id(self, chat_id: str) -> str:
        """Get or create a stable session ID for a Telegram chat."""
        if chat_id not in self._sessions:
            self._sessions[chat_id] = f"tg-{chat_id}"
        return self._sessions[chat_id]

    def _api_post(self, path: str, body: Dict[str, Any], timeout: float = 15.0) -> Optional[Dict[str, Any]]:
        """POST to the JARVIS API and return parsed JSON."""
        try:
            data = json.dumps(body).encode()
            req = Request(
                f"{self.api_url}{path}",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode())
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            logger.warning("API POST %s failed: %s", path, exc)
            return None

    def _api_get(self, path: str, timeout: float = 10.0) -> Optional[Dict[str, Any]]:
        """GET from the JARVIS API."""
        try:
            req = Request(f"{self.api_url}{path}", method="GET")
            with urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode())
        except Exception as exc:
            logger.warning("API GET %s failed: %s", path, exc)
            return None

    # ── Main entry point ───────────────────────────────────────────────────

    def handle(self, chat_id: str, text: str, username: Optional[str] = None) -> str:
        """Process an incoming Telegram message and return the response text."""
        text = text.strip()

        if not text:
            return "Say something! I'm listening."

        # Check for commands
        if text.startswith("/"):
            return self._handle_command(chat_id, text, username)

        # Everything else → JARVIS conversation
        return self._handle_conversation(chat_id, text)

    # ── Command routing ────────────────────────────────────────────────────

    def _handle_command(self, chat_id: str, text: str, username: Optional[str] = None) -> str:
        """Route a command to the appropriate handler."""
        parts = text.split(maxsplit=1)
        command = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if command in ("/start",):
            return self._cmd_start(username)
        if command in ("/help",):
            return self._cmd_help()
        if command in ("/status",):
            return self._cmd_status()
        if command in ("/drift",):
            return self._cmd_drift()
        if command in ("/approve", "/approve "):
            return self._cmd_approve(arg)
        if command in ("/deny", "/deny "):
            return self._cmd_deny(arg)
        if command in ("/memory",):
            return self._cmd_memory(chat_id)
        if command in ("/forget", "/clear"):
            return self._cmd_forget(chat_id)

        return f"Unknown command: {command}\n\nSend /help to see available commands."

    # ── Individual commands ────────────────────────────────────────────────

    def _cmd_start(self, username: Optional[str]) -> str:
        greeting = f"Hey {username}!" if username else "Hey there!"
        return (
            f"{greeting} 🤖 I'm **JARVIS**, your personal AI assistant.\n\n"
            f"I can answer questions, run commands, check your system, "
            f"remember things, and more.\n\n"
            f"Just **talk to me naturally** — like you would to a person.\n\n"
            f"Send /help to see all commands."
        )

    def _cmd_help(self) -> str:
        lines = ["**🤖 JARVIS Commands**\n", "Talk to me naturally or use:"]
        for cmd, desc in sorted(COMMANDS.items()):
            lines.append(f"  `/{cmd}` — {desc}")
        lines.extend([
            "",
            "**Examples:**",
            "  `hello, what can you do?` — conversation",
            "  `remember my name is Ralph` — save a fact",
            "  `recall my_name` — retrieve a fact",
            "  `run a drift check` — check capabilities",
            "  `check disk usage` — run local tools",
        ])
        return "\n".join(lines)

    def _cmd_status(self) -> str:
        """System status summary."""
        status = self._api_get("/system/status")
        if not status:
            return "⚠️ Could not reach JARVIS API."

        api = "✅" if status.get("api") == "healthy" else "❌"
        voice = "🎤 ON" if status.get("voice_running") else "⏸ OFF"
        ap = status.get("approvals_pending", 0)
        dc = status.get("drift_count", 0)
        caps = status.get("capability_count", 0)

        lines = [
            f"**📊 JARVIS System Status**",
            "",
            f"{api} API: {status.get('api', 'unknown')}",
            f"{voice} Voice",
            f"📋 Approvals pending: {ap}",
            f"🔍 Drift: {dc} {'✅' if dc == 0 else '⚠️'}",
            f"🧠 Capabilities: {caps}",
        ]
        return "\n".join(lines)

    def _cmd_drift(self) -> str:
        """Run drift check and report results."""
        result = self._api_post("/control/ingest", {
            "session_id": "tg-drift",
            "text": "run drift check",
        })
        if not result:
            return "⚠️ Could not run drift check."

        report = result.get("drift_report", {})
        missing = report.get("missing", [])
        repair = result.get("auto_repair", {})
        recheck = result.get("recheck", {})

        lines = [f"**🔍 Drift Check**"]

        if missing:
            lines.append(f"\n⚠️ {len(missing)} capabilities drifted:")
            for m in missing:
                lines.append(f"  • {m}")
            if repair.get("success_count", 0) > 0:
                lines.append(f"\n✅ Auto-repaired {repair['success_count']}")
                if recheck and not recheck.get("missing"):
                    lines.append("✅ All capabilities restored!")
                else:
                    still = recheck.get("missing", [])
                    lines.append(f"⚠️ {len(still)} still missing")
        else:
            lines.append("\n✅ All capabilities in sync!")

        return "\n".join(lines)

    def _cmd_approve(self, arg: str) -> str:
        """Approve a pending action, or list pending approvals."""
        if not arg:
            return self._list_pending_approvals()

        approval_id = arg.strip()
        result = self._api_post(f"/control/approvals/{approval_id}/approve", {})
        if not result:
            return f"⚠️ Could not approve `{approval_id}` — API unreachable."

        if result.get("ok"):
            executed = result.get("executed", False)
            if executed:
                return f"✅ **Approved and executed** `{approval_id[:8]}...`"
            return f"✅ **Approved** `{approval_id[:8]}...` (already claimed)"
        else:
            error = result.get("error", "unknown error")
            return f"❌ **Failed**: {error}"

    def _cmd_deny(self, arg: str) -> str:
        """Deny a pending action."""
        if not arg:
            return "Usage: `/deny <approval_id>`\n\nSend /approve to see pending IDs."

        approval_id = arg.strip()
        result = self._api_post(f"/control/approvals/{approval_id}/deny", {"reason": "Denied via Telegram"})
        if not result:
            return f"⚠️ Could not deny `{approval_id}` — API unreachable."

        if result.get("ok"):
            return f"❌ **Denied** `{approval_id[:8]}...`"
        else:
            return f"⚠️ {result.get('error', 'unknown error')}"

    def _list_pending_approvals(self) -> str:
        """List pending approvals with IDs to approve/deny."""
        approvals = self._api_get("/control/approvals?status=pending")
        if not approvals:
            return "⚠️ Could not fetch approvals."

        pending = approvals.get("approvals", [])
        if not pending:
            return "✅ No pending approvals."

        lines = ["**📋 Pending Approvals:**"]
        for a in pending:
            aid = a.get("approval_id", "?")[:8]
            action = a.get("action", "?")
            reason = a.get("reason", "")
            lines.append(f"\n  `{aid}` — **{action}**")
            if reason:
                lines.append(f"    _{reason}_")

        lines.append("\nTo approve: `/approve <id>`")
        lines.append("To deny: `/deny <id>`")
        return "\n".join(lines)

    def _cmd_memory(self, chat_id: str) -> str:
        """Show what JARVIS remembers."""
        facts = self._api_get("/control/facts") if False else None
        # Fallback: ask JARVIS directly
        result = self._api_post("/control/ingest", {
            "session_id": self._session_id(chat_id),
            "text": "what do you remember about me?",
        })
        if result:
            return result.get("response", "I don't have any memories stored yet.")
        return "⚠️ Could not retrieve memories."

    def _cmd_forget(self, chat_id: str) -> str:
        """Clear conversation history."""
        result = self._api_post("/control/ingest", {
            "session_id": self._session_id(chat_id),
            "text": "forget",
        })
        if result:
            return result.get("response", "Conversation history cleared.")
        return "⚠️ Could not clear memory."

    # ── Conversation ───────────────────────────────────────────────────────

    def _handle_conversation(self, chat_id: str, text: str) -> str:
        """Route a natural language message through JARVIS."""
        session_id = self._session_id(chat_id)
        result = self._api_post("/control/ingest", {
            "session_id": session_id,
            "text": text,
        })
        if not result:
            return "⚠️ JARVIS is not responding. Is the API server running?"

        # Extract the best response text
        response = result.get("response", "")

        # Handle approval requests — format nicely for Telegram
        if result.get("requires_approval"):
            aid = result.get("approval_id", "?")[:8]
            action = result.get("action", "?")
            reason = result.get("reason", "")
            response = (
                f"⚠️ **Approval Required**\n\n"
                f"Action: `{action}`\n"
                f"Reason: _{reason}_\n"
                f"ID: `{aid}`\n\n"
                f"Reply with `/approve {aid}` or `/deny {aid}`"
            )

        # Handle denied actions
        elif result.get("denied"):
            reason = result.get("reason", "")
            response = f"🚫 **Denied**: {reason}"

        # Handle tool results
        elif result.get("tool_result"):
            tool_res = result["tool_result"]
            if isinstance(tool_res, dict):
                if tool_res.get("ok"):
                    response = f"✅ **Done** — {result.get('tool_result', {}).get('tool', 'action')} completed."
                elif tool_res.get("error"):
                    response = f"⚠️ **Error**: {tool_res['error'][:200]}"
                else:
                    response = "✅ Done."
            else:
                response = f"✅ **Result**: {str(tool_res)[:200]}"

        # Clean up response for Telegram
        if not response or len(response) < 5:
            response = "Done! What else can I help with?"

        return response