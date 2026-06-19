from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Literal, Protocol, Set

Decision = Literal["allow", "deny", "require_approval"]


@dataclass
class PolicyResult:
    decision: Decision
    reason: str


class PolicyEngine(Protocol):
    def evaluate(self, action: str, payload: Dict[str, Any]) -> PolicyResult: ...


class DefaultPolicyEngine:
    """MVP safety policy.

    - allowlisted read actions pass directly
    - write/admin/destructive actions require approval
    - blocked actions are denied
    """

    def __init__(self) -> None:
        self.allow_actions: Set[str] = {
            "web_search",
            "read_file",
            "search_files",
            "load_skill",
            "drift_check",
        }
        self.approval_actions: Set[str] = {
            "write_file",
            "patch",
            "terminal",
            "memory_add",
            "send_message",
            "cron_create",
        }
        self.denied_actions: Set[str] = {
            "rm_rf",
            "exfiltrate_secret",
        }

    def evaluate(self, action: str, payload: Dict[str, Any]) -> PolicyResult:
        _ = payload

        if action in self.denied_actions:
            return PolicyResult(decision="deny", reason=f"action '{action}' is explicitly denied")

        if action in self.allow_actions:
            return PolicyResult(decision="allow", reason=f"action '{action}' is allowlisted")

        if action in self.approval_actions:
            return PolicyResult(
                decision="require_approval",
                reason=f"action '{action}' requires human approval",
            )

        return PolicyResult(
            decision="require_approval",
            reason=f"action '{action}' is unknown; defaulting to approval",
        )
