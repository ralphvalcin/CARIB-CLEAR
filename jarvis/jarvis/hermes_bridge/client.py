from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Protocol, Optional, Sequence
import json
import subprocess


class HermesClient(Protocol):
    def chat(self, prompt: str, model: Optional[str] = None) -> str: ...
    def run_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]: ...
    def load_skill(self, name: str) -> Dict[str, Any]: ...
    def memory_add(self, target: str, content: str) -> Dict[str, Any]: ...


@dataclass
class CLIHermesClient(HermesClient):
    """Hermes CLI transport.

    Uses subprocess calls to the local `hermes` binary.
    """

    hermes_bin: str = "hermes"
    timeout_sec: int = 120

    def _run(self, args: Sequence[str]) -> Dict[str, Any]:
        cmd = [self.hermes_bin, *args]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout_sec,
                check=False,
            )
            return {
                "ok": proc.returncode == 0,
                "returncode": proc.returncode,
                "stdout": proc.stdout.strip(),
                "stderr": proc.stderr.strip(),
                "cmd": cmd,
            }
        except FileNotFoundError:
            return {
                "ok": False,
                "returncode": 127,
                "stdout": "",
                "stderr": f"{self.hermes_bin} not found",
                "cmd": cmd,
            }
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "returncode": 124,
                "stdout": "",
                "stderr": f"command timed out after {self.timeout_sec}s",
                "cmd": cmd,
            }

    def chat(self, prompt: str, model: Optional[str] = None) -> str:
        args = ["chat", "-q", prompt]
        if model:
            args.extend(["-m", model])
        result = self._run(args)
        if result["ok"]:
            return str(result["stdout"])
        return f"[hermes_chat_error] {result['stderr']}"

    def run_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        tool_payload = json.dumps(arguments, ensure_ascii=False)
        prompt = (
            "Use exactly one Hermes tool call if possible. "
            f"Tool name: {name}. "
            f"Arguments JSON: {tool_payload}. "
            "Return a strict JSON object with keys: ok, tool, result, error."
        )
        result = self._run(["chat", "-q", prompt, "-Q"])
        if not result["ok"]:
            return {
                "ok": False,
                "tool": name,
                "error": result["stderr"],
                "transport": "hermes-cli",
                "cmd": result["cmd"],
            }

        out = str(result["stdout"])
        try:
            parsed = json.loads(out)
            if isinstance(parsed, dict):
                parsed.setdefault("transport", "hermes-cli")
                return parsed
        except json.JSONDecodeError:
            pass

        return {
            "ok": True,
            "tool": name,
            "result": out,
            "error": None,
            "transport": "hermes-cli",
        }

    def load_skill(self, name: str) -> Dict[str, Any]:
        # `skills inspect` validates visibility without mutating local state.
        result = self._run(["skills", "inspect", name])
        return {
            "ok": result["ok"],
            "transport": "hermes-cli",
            "skill": name,
            "stdout": result["stdout"],
            "stderr": result["stderr"],
            "cmd": result["cmd"],
        }

    def memory_add(self, target: str, content: str) -> Dict[str, Any]:
        # Hermes has no direct memory-write CLI endpoint currently, so we route
        # via a one-shot chat instruction.
        prompt = (
            "Use the memory tool once. "
            f"action=add target={target} content={content}. "
            "Return strict JSON with keys: ok, summary."
        )
        result = self._run(["chat", "-q", prompt, "-Q"])
        return {
            "ok": result["ok"],
            "transport": "hermes-cli",
            "target": target,
            "content": content,
            "stdout": result["stdout"],
            "stderr": result["stderr"],
            "cmd": result["cmd"],
        }
