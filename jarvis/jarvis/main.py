from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, Optional
import socket
import time

from jarvis.runtime.errors import ErrorCode
from jarvis.runtime.llm_client import LLMClient
from jarvis.runtime.local_runner import LocalCapabilityRunner
from jarvis.runtime.router import IntentRouter, RouteDecision
from jarvis.runtime.policy import DefaultPolicyEngine
from jarvis.runtime.approval_queue import SqliteApprovalQueue
from jarvis.hermes_bridge.client import CLIHermesClient
from jarvis.hermes_bridge.retry_client import RetryingHermesClient
from jarvis.knowledge.drift_checker import DriftChecker, HermesCapabilitySource
from jarvis.knowledge.drift_repairer import DriftRepairer
from jarvis.knowledge.conversation_memory import ConversationMemory
from jarvis.knowledge.self_doc import SelfKnowledgeBuilder
from jarvis.events.models import Event
from jarvis.events.store import JsonlEventStore, SqliteEventStore
from jarvis.notifications.scheduler import NotificationService


class JarvisApp:
    """Runtime shell with LLM conversation, routing, policy gate, drift repair,
    persistent memory, approval state, and event logging."""

    def __init__(
        self,
        approvals_db_path: str = "./data/approvals.db",
        approval_lease_seconds: float = 30.0,
        max_execution_retries: int = 2,
        memory_db_path: str = "./data/conversation_memory.db",
        llm_model: str = "llama3.2:3b",
        auto_repair_drift: bool = True,
    ) -> None:
        self.router = IntentRouter()
        self.policy = DefaultPolicyEngine()
        self.local_runner = LocalCapabilityRunner()
        self.approvals = SqliteApprovalQueue(db_path=approvals_db_path)
        self.approval_lease_seconds = approval_lease_seconds
        self.max_execution_retries = max_execution_retries
        self.worker_id = f"jarvis-{socket.gethostname()}"
        self.hermes = RetryingHermesClient(inner=CLIHermesClient())
        self.drift_checker = DriftChecker(HermesCapabilitySource())
        self.drift_repairer = DriftRepairer()
        self.auto_repair_drift = auto_repair_drift
        self.memory = ConversationMemory(db_path=memory_db_path)
        self.llm = LLMClient(model=llm_model)
        self.jsonl_store = JsonlEventStore()
        self.sqlite_store = SqliteEventStore()
        # System preamble — cached, refreshed on TTL expiry
        self._preamble: str | None = None
        self._preamble_ts: float = 0.0
        self._preamble_ttl: float = 300.0  # 5 min
        self._knowledge_builder = SelfKnowledgeBuilder()
        self.notifications = NotificationService()

    def _get_preamble(self) -> str:
        """Build or return cached system preamble.

        Injects self-knowledge + drift status + memory context as a
        system prompt preamble so JARVIS knows its own capabilities
        and relevant past context when generating responses.
        """
        now = time.time()
        if self._preamble is not None and (now - self._preamble_ts) < self._preamble_ttl:
            return self._preamble

        try:
            doc = self._knowledge_builder.build()
        except Exception:
            # Graceful fallback if self-knowledge builder fails
            self._preamble = "I am JARVIS, a personal assistant. System status: checking."
            self._preamble_ts = now
            return self._preamble

        import datetime as _dt

        lines: list[str] = [
            "You are JARVIS, an intelligent personal assistant.",
            "",
            f"Current date and time: {_dt.datetime.now(_dt.timezone.utc).strftime('%A, %B %d, %Y at %H:%M UTC')}",
            f"You are running in the year 2026 with full awareness of current events up to this moment.",
            "",
        ]

        # System info
        summary = doc.system_summary
        if summary:
            os_info = summary.get("os", "macOS")
            cpu = summary.get("cpu_count", "?")
            mem = summary.get("memory_gb", "?")
            lines.append(f"System: {os_info} ({cpu} cores, {mem} GB RAM)")
            lines.append("")

        # Capability summary
        total_caps = doc.to_dict().get("capability_count", 0)
        lines.append(f"Capabilities: {total_caps} total")
        lines.append("")

        # Drift warning
        if doc.drift and (doc.drift.missing or doc.drift.unexpected):
            missing = doc.drift.missing
            unexpected = doc.drift.unexpected
            parts: list[str] = []
            if missing:
                parts.append(f"{len(missing)} capabilities drifted (missing)")
            if unexpected:
                parts.append(f"{len(unexpected)} unexpected capabilities")
            lines.append(
                f"⚠️ SYSTEM STATUS: DRIFT DETECTED — {', '.join(parts)}. "
                "Some capabilities may be unavailable."
            )
            lines.append("")

        # Local tools available
        local_tools = self.local_runner.list_tools()
        if local_tools:
            tool_names = [t["name"] for t in local_tools]
            lines.append(f"Local tools available: {', '.join(sorted(tool_names))}")
            lines.append("")

        # LLM status
        if getattr(self.llm, "enabled", True) and self.llm._available is not False:
            lines.append(f"Using local LLM: {self.llm.model}")
            lines.append("")

        self._preamble = "\n".join(lines)
        self._preamble_ts = now
        return self._preamble

    def _log(self, session_id: str, event_type: str, payload: Dict[str, Any], level: str = "info") -> None:
        evt = Event(
            type=event_type,
            session_id=session_id,
            payload=payload,
            level=level,  # type: ignore[arg-type]
        )
        self.jsonl_store.append(evt)
        self.sqlite_store.append(evt)

    def list_pending_approvals(self) -> Dict[str, Any]:
        return {"ok": True, "pending": self.approvals.list(status="pending")}

    def list_approvals(self, status: Optional[str] = None) -> Dict[str, Any]:
        return {"ok": True, "approvals": self.approvals.list(status=status)}

    def sweep_stale_approvals(self) -> Dict[str, Any]:
        reclaimed = self.approvals.reclaim_stale_claims(lease_seconds=self.approval_lease_seconds)
        return {"ok": True, "reclaimed": reclaimed}

    def metrics(self) -> Dict[str, Any]:
        return {"ok": True, "metrics": self.approvals.metrics()}

    def approve_action(self, approval_id: str, worker_id: Optional[str] = None) -> Dict[str, Any]:
        claimant = worker_id or self.worker_id
        claimed = self.approvals.claim_for_execution(
            approval_id,
            worker_id=claimant,
            lease_seconds=self.approval_lease_seconds,
        )
        if claimed:
            try:
                tool_result = self.hermes.run_tool(name=claimed.action, arguments=claimed.payload)
                executed = self.approvals.mark_executed(approval_id, result=tool_result, worker_id=claimant)

                self._log(
                    claimed.session_id,
                    "approval_executed",
                    {
                        "approval_id": approval_id,
                        "action": claimed.action,
                        "tool_result": tool_result,
                        "worker_id": claimant,
                    },
                )

                return {
                    "ok": True,
                    "executed": True,
                    "approval": executed.to_dict() if executed else claimed.to_dict(),
                    "tool_result": tool_result,
                }
            except Exception as exc:
                failed = self.approvals.mark_failed(
                    approval_id,
                    worker_id=claimant,
                    error=str(exc),
                    max_retries=self.max_execution_retries,
                )
                self._log(
                    claimed.session_id,
                    "approval_execution_failed",
                    {
                        "approval_id": approval_id,
                        "action": claimed.action,
                        "error": str(exc),
                        "worker_id": claimant,
                        "next_status": failed.status if failed else "unknown",
                    },
                    level="warn",
                )
                return {
                    "ok": False,
                    "error": str(exc),
                    "error_code": ErrorCode.APPROVAL_EXECUTION_FAILED,
                    "executed": False,
                    "approval": failed.to_dict() if failed else None,
                }

        item = self.approvals.get(approval_id)
        if not item:
            return {"ok": False, "error": "approval_id not found", "error_code": ErrorCode.APPROVAL_NOT_FOUND}

        if item.status == "denied":
            return {"ok": False, "error": "approval already denied", "error_code": ErrorCode.APPROVAL_ALREADY_DENIED}

        if item.status == "executed":
            return {"ok": True, "approval": item.to_dict(), "executed": True}

        if item.status == "failed":
            return {
                "ok": False,
                "approval": item.to_dict(),
                "executed": False,
                "error": "approval execution failed",
                "error_code": ErrorCode.APPROVAL_EXECUTION_FAILED,
            }

        if item.status == "approved":
            return {
                "ok": True,
                "executed": False,
                "approval": item.to_dict(),
                "message": "approval already claimed by another worker",
            }

        return {"ok": False, "error": "failed to claim approval", "error_code": ErrorCode.APPROVAL_CLAIM_CONFLICT}

    def deny_action(self, approval_id: str, reason: Optional[str] = None) -> Dict[str, Any]:
        item = self.approvals.deny(approval_id)
        if not item:
            return {"ok": False, "error": "approval_id not found", "error_code": ErrorCode.APPROVAL_NOT_FOUND}

        self._log(
            item.session_id,
            "approval_denied",
            {
                "approval_id": approval_id,
                "action": item.action,
                "reason": reason or "operator denied",
            },
            level="warn",
        )

        return {"ok": True, "approval": item.to_dict()}

    # ── Core text handler ────────────────────────────────────────────────────

    def handle_text(self, session_id: str, text: str) -> Dict[str, Any]:
        decision: RouteDecision = self.router.route(text=text)
        self._log(session_id, "route_decision", {"path": decision.path, "text": text})

        # ── Drift check ──────────────────────────────────────────────────────
        if decision.path == "drift_check":
            report = self.drift_checker.run()
            response: Dict[str, Any] = {
                "session_id": session_id,
                "ts": time.time(),
                "path": decision.path,
                "drift_report": asdict(report),
            }

            # Auto-repair if configured and drift detected
            if self.auto_repair_drift and report.missing:
                repair_result = self.drift_repairer.repair(report)
                response["auto_repair"] = repair_result.to_dict()

                if repair_result.ok:
                    # Recheck after repair
                    recheck = self.drift_checker.run()
                    response["recheck"] = asdict(recheck)
                    response["repair_status"] = "all_fixed" if not recheck.missing else "partial"

            self._log(session_id, "drift_check", response)

            # Notify on drift detected or auto-fixed
            if report.missing:
                n = len(report.missing)
                self.notifications.fire(
                    "drift_detected",
                    f"⚠️ Drift Detected",
                    f"{n} capability{'s' if n != 1 else ''} drifted: {', '.join(report.missing[:5])}",
                    severity="warning",
                )
            elif response.get("repair_status") == "all_fixed":
                self.notifications.fire(
                    "drift_fixed",
                    "✅ Drift Repaired",
                    "All drifted capabilities have been restored automatically.",
                    severity="info",
                )

            return response

        # ── Drift repair ─────────────────────────────────────────────────────
        if decision.path == "drift_repair":
            report = self.drift_checker.run()
            repair_result = self.drift_repairer.repair(report)
            recheck = self.drift_checker.run()
            response = {
                "session_id": session_id,
                "ts": time.time(),
                "path": decision.path,
                "drift_report": asdict(report),
                "repair_result": repair_result.to_dict(),
                "recheck": asdict(recheck),
                "repair_status": "all_fixed" if not recheck.missing else "partial",
            }
            self._log(session_id, "drift_repair", response)

            # Notify on repair result
            status = response.get("repair_status", "unknown")
            if status == "all_fixed":
                self.notifications.fire(
                    "drift_fixed",
                    "✅ Drift Repaired",
                    "All capabilities restored.",
                    severity="info",
                )
            elif status == "partial":
                self.notifications.fire(
                    "drift_detected",
                    "⚠️ Partial Repair",
                    f"Fixed {repair_result.success_count}, {len(recheck.missing)} still drifted.",
                    severity="warning",
                )

            return response

        # ── Memory actions ───────────────────────────────────────────────────
        if decision.path == "memory_action":
            action = decision.tool_name or "memory_save"
            return self._handle_memory_action(session_id, text, action)

        # ── Tool actions ─────────────────────────────────────────────────────
        if decision.path == "tool_action":
            return self._handle_tool_action(session_id, text, decision)

        # ── Direct response (LLM conversation) ───────────────────────────────
        # This is the default for all non-keyword-matched text

        # Fast path: use quick_response if the router matched a conversation pattern
        if decision.quick_response:
            response = {
                "session_id": session_id,
                "ts": time.time(),
                "path": decision.path,
                "response": decision.quick_response,
                "quick": True,
            }
            self._log(session_id, "quick_response", response)
            return response

        preamble = self._get_preamble()

        # Log user turn
        self.memory.log_turn(session_id, "user", text)

        # Build context from memory + preamble
        memory_context = self.memory.get_context_for_llm(
            session_id,
            max_facts=5,
            max_history=8,
        )

        # Build system prompt with memory context injected
        system_prompt = preamble
        if memory_context:
            system_prompt = f"{preamble}\n\n{memory_context}"

        # Call the real LLM
        llm_response = self.llm.chat(
            user_message=text,
            system_prompt=system_prompt,
            session_id=session_id,
        )

        # Log assistant turn
        self.memory.log_turn(session_id, "assistant", llm_response)

        response = {
            "session_id": session_id,
            "ts": time.time(),
            "path": decision.path,
            "response": llm_response,
            "llm_model": self.llm.model,
            "llm_available": self.llm.check_available() if self.llm._available is not False else False,
        }
        self._log(session_id, "llm_response", response)
        return response

    # ── Memory action handler ─────────────────────────────────────────────────

    def _handle_memory_action(self, session_id: str, text: str, action: str) -> Dict[str, Any]:
        """Handle memory_save, memory_search, and memory_clear actions."""
        t = text.lower().strip()

        if action == "memory_save":
            # Parse "remember X is Y" or "remember X = Y" or "don't forget X"
            # Extract the fact from the natural language
            fact_text = text
            for prefix in ["remember", "don't forget", "dont forget"]:
                if t.startswith(prefix):
                    fact_text = text[len(prefix):].strip().lstrip(":, \t")
                    break

            # Try to split into key=value on common delimiters
            fact_key = None
            fact_value = fact_text

            for sep in [" is ", " = ", ":", " → ", " -> "]:
                if sep in fact_text:
                    idx = fact_text.index(sep)
                    fact_key = fact_text[:idx].strip().lower().replace(" ", "_")
                    fact_value = fact_text[idx + len(sep):].strip()
                    break

            if fact_key and fact_value:
                self.memory.save_fact(fact_key, fact_value)
                self._log(session_id, "memory_fact_saved", {
                    "key": fact_key,
                    "value": fact_value,
                })
                return {
                    "session_id": session_id,
                    "ts": time.time(),
                    "path": "memory_action",
                    "action": "memory_save",
                    "ok": True,
                    "response": f"Got it — I'll remember that {fact_key}: {fact_value}",
                    "fact": {"key": fact_key, "value": fact_value},
                }
            else:
                # Store as a general fact
                auto_key = f"fact_{int(time.time())}"
                self.memory.save_fact(auto_key, fact_text)
                self._log(session_id, "memory_fact_saved", {
                    "key": auto_key,
                    "value": fact_text,
                })
                return {
                    "session_id": session_id,
                    "ts": time.time(),
                    "path": "memory_action",
                    "action": "memory_save",
                    "ok": True,
                    "response": f"Got it — I'll remember that: {fact_text}",
                    "fact": {"key": auto_key, "value": fact_text},
                }

        if action == "memory_search":
            # Extract query: "what did we talk about X" or just search memory
            query = t
            for qp in ["what did we talk about", "what were we doing", "what was i working on",
                        "recall", "what did i ask", "what happened"]:
                if qp in t:
                    # Get everything after the phrase
                    idx = t.index(qp) + len(qp)
                    after = t[idx:].strip().lstrip(":, \t")
                    if after:
                        query = after
                    break

            # Search conversations
            conv_results = self.memory.search_conversations(query, limit=5)
            # Search facts too
            fact_results = self.memory.search_facts(query, limit=5)

            self._log(session_id, "memory_search", {
                "query": query,
                "conversation_matches": len(conv_results),
                "fact_matches": len(fact_results),
            })

            # Build a natural response
            response_parts = []
            if conv_results:
                response_parts.append("Here's what I found in our past conversations:")
                for r in conv_results[:5]:
                    role_label = "You" if r["role"] == "assistant" else "User"
                    highlight = r.get("highlight", r["content"][:120])
                    ts = r.get("timestamp", "")
                    response_parts.append(f"  • [{ts}] {role_label}: {highlight}")

            if fact_results:
                if response_parts:
                    response_parts.append("")
                response_parts.append("And here are things I remember:")
                for f in fact_results[:5]:
                    response_parts.append(f"  • {f['key']}: {f['value']}")

            if not conv_results and not fact_results:
                response_parts.append("I couldn't find anything matching that in my memory.")

            return {
                "session_id": session_id,
                "ts": time.time(),
                "path": "memory_action",
                "action": "memory_search",
                "ok": True,
                "response": "\n".join(response_parts),
                "conversation_matches": conv_results[:5],
                "fact_matches": fact_results[:5],
            }

        if action == "memory_clear":
            self.llm.clear_history(session_id)
            self._log(session_id, "memory_clear", {"session_id": session_id})
            return {
                "session_id": session_id,
                "ts": time.time(),
                "path": "memory_action",
                "action": "memory_clear",
                "ok": True,
                "response": "I've cleared our current conversation history. What would you like to talk about?",
            }

        return {
            "session_id": session_id,
            "ts": time.time(),
            "path": "memory_action",
            "action": action,
            "ok": False,
            "response": "I'm not sure how to handle that memory request.",
        }

    # ── Tool action handler ───────────────────────────────────────────────────

    def _handle_tool_action(self, session_id: str, text: str, decision: RouteDecision) -> Dict[str, Any]:
        """Execute a tool action with policy gating, local runner, and Hermes fallback."""
        action = decision.tool_name or "web_search"
        payload = decision.tool_args or {}
        policy_result = self.policy.evaluate(action=action, payload=payload)
        self._log(session_id, "policy_decision", {
            "action": action, "decision": policy_result.decision, "reason": policy_result.reason,
        })

        if policy_result.decision == "deny":
            denied = {
                "session_id": session_id,
                "ts": time.time(),
                "path": decision.path,
                "denied": True,
                "reason": policy_result.reason,
            }
            self._log(session_id, "tool_denied", denied, level="warn")
            return denied

        if policy_result.decision == "require_approval":
            queued = self.approvals.enqueue(
                session_id=session_id,
                action=action,
                payload=payload,
                reason=policy_result.reason,
            )
            pending = {
                "session_id": session_id,
                "ts": time.time(),
                "path": decision.path,
                "requires_approval": True,
                "approval_id": queued.approval_id,
                "action": action,
                "reason": policy_result.reason,
            }
            self._log(session_id, "tool_requires_approval", pending, level="warn")

            # Notify on pending approval
            self.notifications.fire(
                "approval_pending",
                "📋 Approval Required",
                f"{action} needs approval: {policy_result.reason[:80]}",
                severity="info",
                payload={"approval_id": queued.approval_id, "action": action, "reason": policy_result.reason},
            )

            return pending

        # Try local runner first, then fall back to Hermes CLI
        if self.local_runner.can_handle(action):
            local_result = self.local_runner.run(action, arguments=payload)
            if local_result.ok:
                tool_result = local_result.to_dict()
            else:
                tool_result = self.hermes.run_tool(name=action, arguments=payload)
        else:
            tool_result = self.hermes.run_tool(name=action, arguments=payload)

        response = {
            "session_id": session_id,
            "ts": time.time(),
            "path": decision.path,
            "tool_result": tool_result,
        }
        self._log(session_id, "tool_executed", response)
        return response

    # ── Memory info endpoint ─────────────────────────────────────────────────

    def memory_stats(self) -> Dict[str, Any]:
        """Return memory statistics."""
        return {"ok": True, "stats": self.memory.stats()}

    def get_memory_facts(self) -> Dict[str, Any]:
        """Return all saved memory facts."""
        return {"ok": True, "facts": self.memory.list_facts()}


def main() -> None:
    app = JarvisApp()
    demo = app.handle_text(session_id="demo", text="run a drift check")
    print(demo)


if __name__ == "__main__":
    main()