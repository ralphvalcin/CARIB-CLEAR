from __future__ import annotations

import os
import time
import tempfile
import pytest

from pathlib import Path

from jarvis.runtime.local_runner import (
    LocalCapabilityRunner,
    WHITELIST_PATHS,
    _in_whitelist,
    TimeoutError,
    _run_with_timeout,
)


class TestWhitelist:
    def test_home_is_whitelisted(self) -> None:
        assert _in_whitelist(Path.home() / "test.txt")

    def test_etc_is_not_whitelisted(self) -> None:
        assert not _in_whitelist(Path("/etc/passwd"))

    def test_tmp_is_whitelisted(self) -> None:
        assert _in_whitelist(Path("/tmp/test_file.txt"))

    def test_deeply_nested_outside_whitelist(self) -> None:
        assert not _in_whitelist(Path("/var/log/system.log"))


class TestLocalCapabilityRunnerList:
    def test_lists_all_tools(self) -> None:
        runner = LocalCapabilityRunner()
        tools = runner.list_tools()
        names = [t["name"] for t in tools]
        assert "read_file" in names
        assert "list_directory" in names
        assert "run_python" in names
        assert "check_disk" in names
        assert "current_time" in names
        assert "system_info" in names


class TestLocalCapabilityRunnerReadFile:
    def test_unknown_tool_returns_error(self) -> None:
        runner = LocalCapabilityRunner()
        result = runner.run("nonexistent_tool")
        assert not result.ok
        assert "unknown local tool" in result.error

    def test_can_handle_known_tool(self) -> None:
        runner = LocalCapabilityRunner()
        assert runner.can_handle("read_file")
        assert not runner.can_handle("rainbow_magic")

    def test_read_whitelisted_file(self) -> None:
        runner = LocalCapabilityRunner()
        # Read the project's own pyproject.toml
        result = runner.run("read_file", arguments={"path": "pyproject.toml"})
        assert result.ok
        assert result.data["size"] > 0
        assert "[tool.pytest" in result.data["content"] or "pytest" in result.data["content"]

    def test_read_non_whitelisted_file_denied(self) -> None:
        runner = LocalCapabilityRunner()
        result = runner.run("read_file", arguments={"path": "/etc/passwd"})
        assert not result.ok
        assert "not in whitelist" in result.error

    def test_read_nonexistent_file(self) -> None:
        runner = LocalCapabilityRunner()
        result = runner.run("read_file", arguments={"path": "/tmp/__nonexistent_xyz__"})
        assert not result.ok
        assert "not found" in result.error

    def test_list_directory(self) -> None:
        runner = LocalCapabilityRunner()
        result = runner.run("list_directory", arguments={"path": "."})
        assert result.ok
        assert result.data["count"] > 0
        names = [e["name"] for e in result.data["entries"]]
        assert "pyproject.toml" in names or "jarvis" in names

    def test_list_directory_denied(self) -> None:
        runner = LocalCapabilityRunner()
        result = runner.run("list_directory", arguments={"path": "/etc"})
        assert not result.ok
        assert "not in whitelist" in result.error


class TestLocalCapabilityRunnerRunPython:
    def test_run_python_simple(self) -> None:
        runner = LocalCapabilityRunner()
        result = runner.run("run_python", arguments={"code": "print(2 + 2)"})
        assert result.ok
        assert "4" in result.data["stdout"]
        assert result.data["exit_code"] == 0

    def test_run_python_with_error(self) -> None:
        runner = LocalCapabilityRunner()
        result = runner.run("run_python", arguments={"code": "1/0"})
        assert result.ok  # subprocess succeeded even if python errored
        assert result.data["exit_code"] != 0
        assert "ZeroDivisionError" in result.data["stderr"]

    def test_run_python_timeout(self) -> None:
        runner = LocalCapabilityRunner()
        result = runner.run(
            "run_python",
            arguments={"code": "import time; time.sleep(10)", "timeout": 1.0},
            timeout=3.0,
        )
        assert not result.ok
        assert "timed out" in result.error or "timeout" in result.error


class TestLocalCapabilityRunnerSystemTools:
    def test_current_time(self) -> None:
        runner = LocalCapabilityRunner()
        result = runner.run("current_time")
        assert result.ok
        assert "utc" in result.data
        assert result.data["epoch"] > 1_700_000_000  # since 2023

    def test_system_info_has_basic_fields(self) -> None:
        runner = LocalCapabilityRunner()
        result = runner.run("system_info")
        assert result.ok
        assert "os" in result.data
        assert "cpu_count" in result.data
        assert "memory_gb" in result.data

    def test_check_disk(self) -> None:
        runner = LocalCapabilityRunner()
        result = runner.run("check_disk", arguments={"path": "."})
        assert result.ok
        assert "total_gb" in result.data
        assert "free_gb" in result.data

    def test_check_disk_denied_path(self) -> None:
        runner = LocalCapabilityRunner()
        result = runner.run("check_disk", arguments={"path": "/etc"})
        assert not result.ok
        assert "not in whitelist" in result.error


class TestTimeoutHelper:
    def test_timeout_raises(self) -> None:
        with pytest.raises(TimeoutError):
            _run_with_timeout(lambda: time.sleep(5), timeout=0.1)

    def test_no_timeout_returns_result(self) -> None:
        result = _run_with_timeout(lambda: 42, timeout=5.0)
        assert result == 42

    def test_exception_propagates(self) -> None:
        with pytest.raises(ValueError, match="boom"):
            _run_with_timeout(lambda: (_ for _ in ()).throw(ValueError("boom")), timeout=5.0)


class TestLocalCapabilityRunnerEdgeCases:
    def test_invalid_arguments_type_error(self) -> None:
        runner = LocalCapabilityRunner()
        result = runner.run("read_file", arguments={"nope": "whatever"})
        assert not result.ok
        assert "invalid arguments" in result.error or "unexpected keyword" in result.error


class TestCapabilityListDescriptive:
    def test_descriptions_are_readable(self) -> None:
        runner = LocalCapabilityRunner()
        tools = runner.list_tools()
        for t in tools:
            assert len(t["description"]) > 10
            assert t["timeout"] > 0