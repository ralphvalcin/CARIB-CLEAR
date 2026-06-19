from __future__ import annotations

import os
import shutil
import subprocess
import time
import signal
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# ── Safe path whitelist ─────────────────────────────────────────────────
WHITELIST_PATHS = [
    Path.home(),          # ~/ — personal files
    Path.cwd(),           # project root
    Path("/tmp"),
]
MAX_DEPTH = 4  # prevent deep directory traversal


def _in_whitelist(path: Path) -> bool:
    """Check if a resolved path is under any whitelisted directory."""
    resolved = path.resolve()
    for allowed in WHITELIST_PATHS:
        try:
            allowed_resolved = allowed.resolve()
            if allowed_resolved in resolved.parents or resolved == allowed_resolved:
                # also enforce max depth
                depth = len(resolved.relative_to(allowed_resolved).parts)
                if depth <= MAX_DEPTH:
                    return True
        except (ValueError, OSError):
            continue
    return False


# ── Tool result types ────────────────────────────────────────────────────

@dataclass
class ToolResult:
    ok: bool
    data: Any = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "data": self.data, "error": self.error}


# ── Timeout helper ───────────────────────────────────────────────────────

class TimeoutError(Exception):
    pass


def _run_with_timeout(func: Callable[[], Any], timeout: float) -> Any:
    """Run a Python function with a wall-clock timeout (Unix only)."""
    import threading

    result: list[Any] = []
    exception: list[Optional[Exception]] = [None]
    done = threading.Event()

    def worker() -> None:
        try:
            result.append(func())
        except Exception as e:
            exception[0] = e
        finally:
            done.set()

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    if not done.wait(timeout=timeout):
        raise TimeoutError(f"operation timed out after {timeout}s")
    if exception[0]:
        raise exception[0]  # type: ignore[misc]
    return result[0]


# ── Individual tool implementations ─────────────────────────────────────

def _tool_read_file(path: str) -> ToolResult:
    """Read text content of a file within whitelisted paths."""
    p = Path(path)
    if not _in_whitelist(p):
        return ToolResult(ok=False, error=f"path not in whitelist: {p}")
    try:
        content = p.read_text(encoding="utf-8")
        return ToolResult(ok=True, data={"path": str(p.resolve()), "size": len(content), "content": content})
    except FileNotFoundError:
        return ToolResult(ok=False, error=f"file not found: {p}")
    except IsADirectoryError:
        return ToolResult(ok=False, error=f"is a directory: {p}")
    except PermissionError:
        return ToolResult(ok=False, error=f"permission denied: {p}")
    except Exception as e:
        return ToolResult(ok=False, error=str(e))


def _tool_list_directory(path: str) -> ToolResult:
    """List directory contents (non-recursive) within whitelisted paths."""
    p = Path(path)
    if not _in_whitelist(p):
        return ToolResult(ok=False, error=f"path not in whitelist: {p}")
    try:
        if not p.is_dir():
            return ToolResult(ok=False, error=f"not a directory: {p}")
        entries: List[Dict[str, Any]] = []
        for entry in sorted(p.iterdir()):
            try:
                stat = entry.stat()
                entries.append({
                    "name": entry.name,
                    "type": "dir" if entry.is_dir() else "file",
                    "size": stat.st_size,
                    "modified": stat.st_mtime,
                })
            except OSError:
                entries.append({"name": entry.name, "type": "unknown", "size": 0, "modified": 0})
        return ToolResult(ok=True, data={"path": str(p.resolve()), "entries": entries, "count": len(entries)})
    except PermissionError:
        return ToolResult(ok=False, error=f"permission denied: {p}")
    except Exception as e:
        return ToolResult(ok=False, error=str(e))


def _tool_run_python(code: str, timeout: float = 5.0) -> ToolResult:
    """Execute a Python snippet in a subprocess with timeout.

    **Security:** runs in a fresh subprocess. No network access by default.
    Only stdlib available unless the subprocess environment includes extras.
    """
    try:
        result = subprocess.run(
            ["python3", "-c", code],
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ},  # inherit PATH so python3 is found
        )
        return ToolResult(
            ok=True,
            data={
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.returncode,
            },
        )
    except subprocess.TimeoutExpired:
        return ToolResult(ok=False, error=f"python execution timed out after {timeout}s")
    except FileNotFoundError:
        return ToolResult(ok=False, error="python3 not found")
    except Exception as e:
        return ToolResult(ok=False, error=str(e))


def _tool_check_disk(path: str) -> ToolResult:
    """Check disk usage of a directory within whitelisted paths."""
    p = Path(path)
    if not _in_whitelist(p):
        return ToolResult(ok=False, error=f"path not in whitelist: {p}")
    try:
        if not p.exists():
            return ToolResult(ok=False, error=f"path not found: {p}")
        stat = shutil.disk_usage(p if p.is_dir() else p.parent)
        # use du with depth limit for directory
        if p.is_dir():
            du = subprocess.run(
                ["du", "-sh", "-d", str(min(2, MAX_DEPTH)), str(p)],
                capture_output=True, text=True, timeout=30,
            )
            du_output = du.stdout.strip() if du.returncode == 0 else "N/A"
        else:
            du_output = f"{p.stat().st_size} bytes"

        return ToolResult(
            ok=True,
            data={
                "path": str(p.resolve()),
                "total_gb": round(stat.total / (1024**3), 2),
                "used_gb": round(stat.used / (1024**3), 2),
                "free_gb": round(stat.free / (1024**3), 2),
                "usage": du_output,
            },
        )
    except PermissionError:
        return ToolResult(ok=False, error=f"permission denied: {p}")
    except Exception as e:
        return ToolResult(ok=False, error=str(e))


def _tool_current_time() -> ToolResult:
    """Get the current system time."""
    now = datetime.now(timezone.utc)
    return ToolResult(
        ok=True,
        data={
            "utc": now.isoformat(),
            "epoch": now.timestamp(),
            "timezone": "UTC",
        },
    )


def _tool_system_info() -> ToolResult:
    """Get basic system information."""
    info: Dict[str, Any] = {}
    try:
        uname = os.uname()
        info["os"] = f"{uname.sysname} {uname.release}"
        info["hostname"] = uname.nodename
        info["arch"] = uname.machine
    except AttributeError:
        info["os"] = "unknown"

    # CPU
    try:
        cpu_count = os.cpu_count()
        info["cpu_count"] = cpu_count
    except Exception:
        info["cpu_count"] = "unknown"

    # Memory via sysctl (macOS) or /proc (Linux)
    try:
        if os.uname().sysname.lower().startswith('darwin'):
            mem = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True, text=True, timeout=5,
            )
            if mem.returncode == 0:
                info["memory_gb"] = round(int(mem.stdout.strip()) / (1024**3), 2)
            load = subprocess.run(
                ["sysctl", "-n", "vm.loadavg"],
                capture_output=True, text=True, timeout=5,
            )
            if load.returncode == 0:
                info["load_avg"] = load.stdout.strip()
        else:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        kb = int(line.split()[1])
                        info["memory_gb"] = round(kb / (1024**2), 2)
                        break
    except Exception:
        info["memory_gb"] = "unknown"

    # Uptime
    try:
        boot_time = psutil_boot_time()
        if boot_time:
            uptime_secs = time.time() - boot_time
            days = int(uptime_secs // 86400)
            hours = int((uptime_secs % 86400) // 3600)
            info["uptime"] = f"{days}d {hours}h"
    except Exception:
        info["uptime"] = "unknown"

    return ToolResult(ok=True, data=info)


def psutil_boot_time() -> Optional[float]:
    """Try psutil first, fallback to sysctl."""
    try:
        import psutil
        return psutil.boot_time()
    except ImportError:
        try:
            if os.uname().sysname.lower().startswith('darwin'):
                kern = subprocess.run(
                    ["sysctl", "-n", "kern.boottime"],
                    capture_output=True, text=True, timeout=5,
                )
                # kern.boottime: { sec = 1712345678, usec = 0 }
                import re
                m = re.search(r'sec\s*=\s*(\d+)', kern.stdout)
                if m:
                    return float(m.group(1))
        except Exception:
            pass
    return None


# ── Tool registry ────────────────────────────────────────────────────────

LocalToolFn = Callable[..., ToolResult]


@dataclass
class ToolDef:
    name: str
    description: str
    fn: LocalToolFn
    timeout: float = 10.0


class LocalCapabilityRunner:
    """Runs safe local operations without calling Hermes CLI.

    Tools are registered with a name, description, and callable.
    Execution is subject to timeout enforcement and path whitelisting.
    """

    def __init__(self) -> None:
        self._tools: Dict[str, ToolDef] = {}

        self.register(
            ToolDef(
                name="read_file",
                description="Read text content of a file within whitelisted paths",
                fn=_tool_read_file,
                timeout=5.0,
            )
        )
        self.register(
            ToolDef(
                name="list_directory",
                description="List directory contents (non-recursive) within whitelisted paths",
                fn=_tool_list_directory,
                timeout=5.0,
            )
        )
        self.register(
            ToolDef(
                name="run_python",
                description="Execute a Python snippet in a subprocess with timeout",
                fn=_tool_run_python,
                timeout=10.0,
            )
        )
        self.register(
            ToolDef(
                name="check_disk",
                description="Check disk usage of a directory within whitelisted paths",
                fn=_tool_check_disk,
                timeout=30.0,
            )
        )
        self.register(
            ToolDef(
                name="current_time",
                description="Get the current system time",
                fn=_tool_current_time,
                timeout=2.0,
            )
        )
        self.register(
            ToolDef(
                name="system_info",
                description="Get basic system information (OS, CPU, memory, uptime)",
                fn=_tool_system_info,
                timeout=10.0,
            )
        )

    def register(self, tool: ToolDef) -> None:
        self._tools[tool.name] = tool

    def list_tools(self) -> List[Dict[str, Any]]:
        return [
            {"name": t.name, "description": t.description, "timeout": t.timeout}
            for t in self._tools.values()
        ]

    def run(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None, timeout: Optional[float] = None) -> ToolResult:
        """Run a local tool by name with optional arguments."""
        tool = self._tools.get(tool_name)
        if not tool:
            return ToolResult(
                ok=False,
                error=f"unknown local tool: {tool_name} (available: {list(self._tools.keys())})",
            )

        args = arguments or {}
        effective_timeout = timeout or tool.timeout

        try:
            result = _run_with_timeout(lambda: tool.fn(**args), timeout=effective_timeout)
            return result  # type: ignore[return-value]
        except TimeoutError:
            return ToolResult(ok=False, error=f"local tool '{tool_name}' timed out after {effective_timeout}s")
        except TypeError as e:
            return ToolResult(ok=False, error=f"invalid arguments for '{tool_name}': {e}")
        except Exception as e:
            return ToolResult(ok=False, error=f"local tool '{tool_name}' failed: {e}")

    def can_handle(self, action_name: str) -> bool:
        """Check if this runner can handle a given action name."""
        return action_name in self._tools