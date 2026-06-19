"""Drift repairer — automatically fixes missing JARVIS capabilities.

Takes a DriftReport and attempts to restore missing capabilities:
1. Reinstall missing Hermes skills
2. Restart broken JARVIS modules
3. Log events for visibility (and optionally notify on failure)
"""

from __future__ import annotations

import importlib
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Set

from jarvis.knowledge.drift_checker import DriftReport

logger = logging.getLogger("jarvis.knowledge.drift_repair")

# Known Hermes skill categories — maps skill names to their likely category
# Used when `hermes skills install <name>` needs a category hint
_HERMES_SKILL_CATEGORIES: Dict[str, str] = {
    # Apple/macOS
    "apple-notes": "apple",
    "apple-reminders": "apple",
    "findmy": "apple",
    "imessage": "apple",
    "macos-computer-use": "apple",
    "macos-disk-cleanup": "apple",
    "macos-voice-loop": "apple",
    # Autonomous AI agents
    "agent-infrastructure": "autonomous-ai-agents",
    "claude-code": "autonomous-ai-agents",
    "codex": "autonomous-ai-agents",
    "hermes-agent": "autonomous-ai-agents",
    "opencode": "autonomous-ai-agents",
    # Blockchain
    "hedera-agent": "blockchain",
    # Creative
    "architecture-diagram": "creative",
    "ascii-art": "creative",
    "baoyu-article-illustrator": "creative",
    "baoyu-comic": "creative",
    "baoyu-infographic": "creative",
    "claude-design": "creative",
    "excalidraw": "creative",
    "humanizer": "creative",
    "ideation": "creative",
    "manim-video": "creative",
    "pixel-art": "creative",
    "popular-web-designs": "creative",
    "songwriting-and-ai-music": "creative",
    # Data science
    "jupyter-live-kernel": "data-science",
    # DevOps
    "kanban-orchestrator": "devops",
    "kanban-worker": "devops",
    "webhook-subscriptions": "devops",
    # Dogfood
    "dogfood": "dogfood",
    # Email
    "himalaya": "email",
    # Gaming
    "minecraft-modpack-server": "minecraft",
    "pokemon-player": "gaming",
    # GitHub
    "github-auth": "github",
    "github-code-review": "github",
    "github-issues": "github",
    "github-pr-workflow": "github",
    "github-repo-management": "github",
    # K8s
    "Kubernetes": "k8s",
    # MCP
    "native-mcp": "mcp",
    # Media
    "gif-search": "media",
    "songsee": "media",
    "youtube-content": "media",
    # MLOps
    "huggingface-hub": "mlops",
    "massive-market-data": "mlops",
    "voice-assistant": "mlops",
    "evaluating-llms-harness": "mlops/evaluation",
    "weights-and-biases": "mlops",
    "llama-cpp": "mlops/inference",
    "outlines": "mlops/inference",
    "serving-llms-vllm": "mlops/inference",
    "audiocraft-audio-generation": "mlops/models",
    "segment-anything-model": "mlops/models",
    "dspy": "mlops/research",
    "axolotl": "mlops/training",
    "fine-tuning-with-trl": "mlops/training",
    "unsloth": "mlops/training",
    # Note-taking
    "obsidian": "note-taking",
    # Productivity
    "airtable": "productivity",
    "google-workspace": "productivity",
    "linear": "productivity",
    "maps": "productivity",
    "nano-pdf": "productivity",
    "notion": "productivity",
    "ocr-and-documents": "productivity",
    "powerpoint": "productivity",
    # Red-teaming
    "godmode": "red-teaming",
    # Research
    "arxiv": "research",
    "blogwatcher": "research",
    "llm-wiki": "research",
    "polymarket": "research",
    "social-signal-research": "research",
    # Smart home
    "openhue": "smart-home",
    # Social media
    "xurl": "social-media",
    # Software development
    "debugging-hermes-tui-commands": "software-development",
    "hermes-agent-skill-authoring": "software-development",
    "hermes-s6-container-supervision": "software-development",
    "node-inspect-debugger": "software-development",
    "plan": "software-development",
    "python-debugpy": "software-development",
    "requesting-code-review": "software-development",
    "spike": "software-development",
    "subagent-driven-development": "software-development",
    "systematic-debugging": "software-development",
    "test-driven-development": "software-development",
    "writing-plans": "software-development",
    # JARVIS extras (not Hermes skills)
    "approval_queue": "__jarvis__",
    "event_logging": "__jarvis__",
    "voice_input": "__jarvis__",
    "voice_output": "__jarvis__",
    "policy_gating": "__jarvis__",
    "hermes_cli_bridge": "__jarvis__",
    "drift_check": "__jarvis__",
}


class RepairResult:
    """Result of a repair attempt."""

    def __init__(
        self,
        success_count: int = 0,
        failure_count: int = 0,
        skipped_count: int = 0,
        details: Optional[List[Dict]] = None,
    ) -> None:
        self.success_count = success_count
        self.failure_count = failure_count
        self.skipped_count = skipped_count
        self.details = details or []

    def to_dict(self) -> dict:
        return {
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "skipped_count": self.skipped_count,
            "details": self.details,
        }

    @property
    def ok(self) -> bool:
        return self.failure_count == 0

    @property
    def total(self) -> int:
        return self.success_count + self.failure_count + self.skipped_count


class DriftRepairer:
    """Attempts to repair missing capabilities identified by DriftChecker.

    Strategy:
    1. Hermes skills → reinstall via `hermes skills install`
    2. JARVIS modules → attempt reload / reinstall
    3. Log events and optionally notify on failure
    """

    def __init__(self, hermes_bin: str = "hermes", dry_run: bool = False) -> None:
        self._hermes_bin = hermes_bin
        self.dry_run = dry_run

    def repair(self, report: DriftReport) -> RepairResult:
        """Attempt to repair all missing capabilities from a DriftReport."""
        result = RepairResult()

        if not report.missing:
            logger.info("No missing capabilities to repair")
            return result

        for cap in report.missing:
            detail = self._repair_one(cap)
            result.details.append(detail)
            if detail["status"] == "success":
                result.success_count += 1
            elif detail["status"] == "failure":
                result.failure_count += 1
            else:
                result.skipped_count += 1

        return result

    def _repair_one(self, capability: str) -> dict:
        """Attempt to repair a single missing capability."""
        logger.info("Attempting to repair missing capability: %s", capability)

        category = _HERMES_SKILL_CATEGORIES.get(capability, "")

        # ── JARVIS internal module ────────────────────────────────────────
        if category == "__jarvis__":
            return self._repair_jarvis_module(capability)

        # ── Hermes skill ──────────────────────────────────────────────────
        if category:
            return self._repair_hermes_skill(capability, category)

        # Unknown — try as a Hermes skill anyway
        return self._repair_hermes_skill(capability, "")

    def _repair_hermes_skill(self, skill_name: str, category: str) -> dict:
        """Install a missing Hermes skill."""
        if self.dry_run:
            return {
                "capability": skill_name,
                "status": "skipped",
                "message": f"dry-run: would install Hermes skill '{skill_name}'",
                "action": "hermes_skill_install",
            }

        try:
            cmd = [self._hermes_bin, "skills", "install", skill_name]
            if category:
                cmd.extend(["--category", category])

            start = time.time()
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
            )
            elapsed = time.time() - start

            if result.returncode == 0:
                logger.info("Successfully installed Hermes skill '%s' (%.1fs)", skill_name, elapsed)
                return {
                    "capability": skill_name,
                    "status": "success",
                    "message": f"installed Hermes skill '{skill_name}'",
                    "action": "hermes_skill_install",
                    "elapsed_seconds": round(elapsed, 2),
                }
            else:
                logger.warning("Failed to install Hermes skill '%s': %s", skill_name, result.stderr[:200])
                return {
                    "capability": skill_name,
                    "status": "failure",
                    "message": f"install failed: {result.stderr[:200]}",
                    "action": "hermes_skill_install",
                    "error": result.stderr[:200],
                }

        except FileNotFoundError:
            logger.warning("Hermes CLI not found at %s", self._hermes_bin)
            return {
                "capability": skill_name,
                "status": "failure",
                "message": f"Hermes CLI '{self._hermes_bin}' not found",
                "action": "hermes_skill_install",
                "error": "binary not found",
            }
        except subprocess.TimeoutExpired:
            logger.warning("Hermes install timed out for '%s'", skill_name)
            return {
                "capability": skill_name,
                "status": "failure",
                "message": f"install timed out after 60s",
                "action": "hermes_skill_install",
                "error": "timeout",
            }
        except Exception as e:
            logger.error("Unexpected error installing '%s': %s", skill_name, e)
            return {
                "capability": skill_name,
                "status": "failure",
                "message": str(e),
                "action": "hermes_skill_install",
                "error": str(e),
            }

    def _repair_jarvis_module(self, capability: str) -> dict:
        """Try to re-import or restart a broken JARVIS module."""
        if self.dry_run:
            return {
                "capability": capability,
                "status": "skipped",
                "message": f"dry-run: would restart JARVIS module for '{capability}'",
                "action": "jarvis_module_reload",
            }

        # Map capability names back to module paths
        cap_to_module = {
            "policy_gating": ["jarvis.runtime.policy", "jarvis.runtime.router"],
            "approval_queue": ["jarvis.runtime.approval_queue"],
            "event_logging": ["jarvis.events.store", "jarvis.events.models"],
            "voice_input": ["jarvis.voice.core", "jarvis.voice.loop"],
            "voice_output": ["jarvis.voice.core"],
            "hermes_cli_bridge": ["jarvis.hermes_bridge.client", "jarvis.hermes_bridge.retry_client"],
            "drift_check": ["jarvis.knowledge.drift_checker"],
        }

        modules = cap_to_module.get(capability, [])
        if not modules:
            return {
                "capability": capability,
                "status": "skipped",
                "message": f"no known modules for '{capability}'",
                "action": "jarvis_module_reload",
            }

        errors: List[str] = []
        for mod_name in modules:
            try:
                if mod_name in sys.modules:
                    importlib.reload(sys.modules[mod_name])
                    logger.info("Reloaded module '%s' for capability '%s'", mod_name, capability)
                else:
                    importlib.import_module(mod_name)
                    logger.info("Imported module '%s' for capability '%s'", mod_name, capability)
            except Exception as e:
                errors.append(f"{mod_name}: {e}")
                logger.warning("Failed to load module '%s': %s", mod_name, e)

        if not errors:
            return {
                "capability": capability,
                "status": "success",
                "message": f"reloaded {len(modules)} JARVIS module(s)",
                "action": "jarvis_module_reload",
                "modules": modules,
            }
        else:
            return {
                "capability": capability,
                "status": "failure",
                "message": f"module errors: {'; '.join(errors)}",
                "action": "jarvis_module_reload",
                "error": "; ".join(errors),
            }

    def can_repair(self, capability: str) -> bool:
        """Check if a capability looks repairable."""
        return capability in _HERMES_SKILL_CATEGORIES