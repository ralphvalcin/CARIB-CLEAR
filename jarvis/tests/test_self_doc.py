from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from jarvis.knowledge.self_doc import (
    SelfKnowledge,
    SelfKnowledgeBuilder,
    _jarvis_cap_description,
)
from jarvis.knowledge.drift_checker import DriftReport, _JARVIS_EXTRA_CAPABILITIES


class TestSelfKnowledgeBuilder:
    def test_build_succeeds(self) -> None:
        """Builder should produce a SelfKnowledge document without error."""
        builder = SelfKnowledgeBuilder()
        doc = builder.build()
        assert isinstance(doc, SelfKnowledge)
        assert doc.generated_at > 0

    def test_build_has_capability_categories(self) -> None:
        builder = SelfKnowledgeBuilder()
        doc = builder.build()
        assert "hermes_tools" in doc.capabilities
        assert "skills" in doc.capabilities
        assert "jarvis_extras" in doc.capabilities

    def test_build_has_tools(self) -> None:
        builder = SelfKnowledgeBuilder()
        doc = builder.build()
        assert "local_runner" in doc.tools
        tools = doc.tools["local_runner"]
        tool_names = [t["name"] for t in tools]
        assert "read_file" in tool_names
        assert "current_time" in tool_names
        assert "system_info" in tool_names

    def test_build_has_system_summary(self) -> None:
        builder = SelfKnowledgeBuilder()
        doc = builder.build()
        assert "os" in doc.system_summary
        assert "cpu_count" in doc.system_summary

    def test_build_has_limits(self) -> None:
        builder = SelfKnowledgeBuilder()
        doc = builder.build()
        assert len(doc.limits) > 0
        assert any("Hermes CLI" in limit for limit in doc.limits)

    def test_build_includes_drift_report(self) -> None:
        builder = SelfKnowledgeBuilder()
        doc = builder.build()
        assert doc.drift is not None
        assert isinstance(doc.drift.missing, list)
        assert isinstance(doc.drift.unexpected, list)

    def test_jarvis_extras_included(self) -> None:
        builder = SelfKnowledgeBuilder()
        doc = builder.build()
        extras = doc.capabilities.get("jarvis_extras", [])
        extra_names = {e["name"] for e in extras}
        for expected in _JARVIS_EXTRA_CAPABILITIES:
            assert expected in extra_names, f"Missing: {expected}"


class TestSelfKnowledgeToMarkdown:
    def test_markdown_contains_sections(self) -> None:
        builder = SelfKnowledgeBuilder()
        doc = builder.build()
        md = doc.to_markdown()
        assert "# JARVIS Self-Knowledge" in md
        assert "## System Overview" in md
        assert "## Capabilities" in md
        assert "## Tools" in md
        assert "## Known Limitations" in md

    def test_markdown_shows_tools(self) -> None:
        builder = SelfKnowledgeBuilder()
        doc = builder.build()
        md = doc.to_markdown()
        assert "`read_file`" in md
        assert "`current_time`" in md
        assert "`system_info`" in md

    def test_markdown_drift_marker_appears_when_drifted(self) -> None:
        # Build a self-knowledge with drifted capabilities manually
        doc = SelfKnowledge(
            capabilities={
                "jarvis_extras": [
                    {"name": "voice_input", "available": False, "drifted": True, "description": "test"},
                ],
            },
            tools={},
            limits=[],
            system_summary={},
            drift=DriftReport(
                missing=["voice_input"],
                stale=[],
                unexpected=[],
                checked_at=datetime.now().timestamp(),
            ),
        )
        md = doc.to_markdown()
        assert "DRIFTED" in md or "❌" in md


class TestSelfKnowledgeToDict:
    def test_to_dict_has_expected_keys(self) -> None:
        builder = SelfKnowledgeBuilder()
        doc = builder.build()
        d = doc.to_dict()
        assert "generated_at" in d
        assert "system_summary" in d
        assert "drift" in d
        assert "capability_count" in d
        assert "tool_count" in d


class TestJarvisCapDescription:
    def test_known_caps_have_description(self) -> None:
        for cap in _JARVIS_EXTRA_CAPABILITIES:
            desc = _jarvis_cap_description(cap)
            assert len(desc) > 10
            assert desc != cap

    def test_unknown_cap_falls_back(self) -> None:
        desc = _jarvis_cap_description("unknown_cap")
        assert "unknown_cap" in desc