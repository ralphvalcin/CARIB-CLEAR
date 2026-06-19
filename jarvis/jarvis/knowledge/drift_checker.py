"""Drift checker — compares expected Hermes capabilities against reality.

Queries the live Hermes CLI for installed skills and tools, then compares
against JARVIS' declared self-knowledge.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Protocol, Set
import logging
import subprocess
import time

logger = logging.getLogger("jarvis.knowledge.drift")


# ── Known tools ──────────────────────────────────────────────────────────────

_HERMES_BUILTIN_TOOLS: Set[str] = {
    "terminal",
    "read_file",
    "write_file",
    "patch",
    "search_files",
    "web_search",
    "web_extract",
    "memory",
    "skill_view",
    "skill_manage",
    "skills_list",
    "todo",
    "session_search",
    "execute_code",
    "delegate_task",
    "cronjob",
    "clarify",
    "vision_analyze",
    "text_to_speech",
    "image_generate",
    "send_message",
    "process",
}

_JARVIS_EXTRA_CAPABILITIES: Set[str] = {
    "drift_check",
    "approval_queue",
    "event_logging",
    "voice_input",
    "policy_gating",
    "hermes_cli_bridge",
}


# ── Data ─────────────────────────────────────────────────────────────────────


@dataclass
class DriftReport:
    """Result of a capability drift check."""

    missing: List[str]
    stale: List[str]
    unexpected: List[str]
    checked_at: float


class CapabilitySource(Protocol):
    def expected(self) -> Set[str]: ...
    def observed(self) -> Set[str]: ...


# ── Real Hermes capability source ───────────────────────────────────────────


class HermesCapabilitySource:
    """Queries the live Hermes CLI for real capabilities.

    expected = declared JARVIS self-knowledge
    observed = what the Hermes CLI + filesystem actually exposes
    """

    def __init__(self, hermes_bin: str = "hermes") -> None:
        self._hermes_bin = hermes_bin
        self._cached_skills: Set[str] | None = None

    # ── Expected capabilities ────────────────────────────────────────────────

    def expected(self) -> Set[str]:
        """Declared capabilities JARVIS should have."""
        caps: Set[str] = set()

        # All Hermes built-in tools
        caps.update(_HERMES_BUILTIN_TOOLS)

        # Expected skills (the "should have" set)
        caps.update(self._fetch_skills())

        # JARVIS extras
        caps.update(_JARVIS_EXTRA_CAPABILITIES)

        return caps

    # ── Observed capabilities ────────────────────────────────────────────────

    def observed(self) -> Set[str]:
        """Capabilities actually present on the system."""
        caps: Set[str] = set()

        # Hermes built-in tools (always available in Hermes agent context)
        caps.update(_HERMES_BUILTIN_TOOLS)

        # Actually installed skills
        caps.update(self._fetch_skills())

        # JARVIS extras — check what's importable
        caps.update(self._check_jarvis_capabilities())

        return caps

    # ── Details ──────────────────────────────────────────────────────────────

    def skill_details(self) -> List[dict]:
        """Return full skill information (name, category, source, status)."""
        skills: List[dict] = []
        try:
            result = subprocess.run(
                [self._hermes_bin, "skills", "list", "--enabled-only"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            for line in result.stdout.splitlines():
                parts = [p.strip() for p in line.split("│") if p.strip()]
                if len(parts) >= 5:
                    skills.append({
                        "name": parts[0],
                        "category": parts[1],
                        "source": parts[2],
                        "status": parts[4],
                    })
        except Exception as exc:
            logger.warning("Could not query Hermes skills: %s", exc)
        return skills

    # ── Internals ────────────────────────────────────────────────────────────

    def _fetch_skills(self) -> Set[str]:
        """Query Hermes CLI for installed skill names."""
        if self._cached_skills is not None:
            return self._cached_skills

        skills: Set[str] = set()
        try:
            result = subprocess.run(
                [self._hermes_bin, "skills", "list", "--enabled-only"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            for line in result.stdout.splitlines():
                # Parse table format: │ name │ category │ source │ trust │ status │
                stripped = line.strip()
                if stripped.startswith("│"):
                    parts = [p.strip() for p in stripped.split("│")]
                    if len(parts) >= 5:
                        name = parts[1]
                        if name and not name.startswith("└") and not name.startswith("┌"):
                            skills.add(name.rstrip("…"))
        except FileNotFoundError:
            logger.warning("Hermes CLI not found at %s", self._hermes_bin)
        except subprocess.TimeoutExpired:
            logger.warning("Hermes skills list timed out")
        except Exception as exc:
            logger.warning("Error querying Hermes skills: %s", exc)

        self._cached_skills = skills
        logger.debug("Fetched %d Hermes skills", len(skills))
        return skills

    def _check_jarvis_capabilities(self) -> Set[str]:
        """Check which JARVIS custom modules are importable."""
        caps: Set[str] = set()
        try:
            import importlib

            for mod_name in [
                "jarvis.runtime.policy",
                "jarvis.runtime.router",
                "jarvis.runtime.approval_queue",
                "jarvis.events.store",
                "jarvis.events.models",
                "jarvis.voice.core",
                "jarvis.voice.loop",
                "jarvis.hermes_bridge.client",
                "jarvis.knowledge.drift_checker",
            ]:
                try:
                    importlib.import_module(mod_name)
                    module_to_cap = {
                        "jarvis.runtime.policy": "policy_gating",
                        "jarvis.runtime.router": "policy_gating",
                        "jarvis.runtime.approval_queue": "approval_queue",
                        "jarvis.events.store": "event_logging",
                        "jarvis.events.models": "event_logging",
                        "jarvis.voice.core": "voice_input",
                        "jarvis.voice.loop": "voice_input",
                        "jarvis.hermes_bridge.client": "hermes_cli_bridge",
                        "jarvis.knowledge.drift_checker": "drift_check",
                    }
                    if mod_name in module_to_cap:
                        caps.add(module_to_cap[mod_name])
                except ImportError:
                    pass
        except Exception:
            pass

        # voice_output is checked at runtime, not via drift detection
        return caps


# ── Drift Checker ────────────────────────────────────────────────────────────


class DriftChecker:
    """Compares expected vs observed capabilities and reports drift."""

    def __init__(self, source: CapabilitySource) -> None:
        self.source = source

    def run(self) -> DriftReport:
        expected = self.source.expected()
        observed = self.source.observed()

        missing = sorted(expected - observed)
        unexpected = sorted(observed - expected)
        stale: List[str] = []

        return DriftReport(
            missing=missing,
            stale=stale,
            unexpected=unexpected,
            checked_at=time.time(),
        )