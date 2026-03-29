# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for mandatory code tracing (OMN-6819)."""

from __future__ import annotations

import pytest

from omniclaude.hooks.code_tracing import (
    EnumTraceStatus,
    ModelCodeTraceBlock,
    ModelCodeTraceConfig,
    ModelCodeTraceRequirement,
    build_trace_requirements,
    format_trace_prompt_section,
)


@pytest.mark.unit
class TestModelCodeTraceRequirement:
    """Tests for ModelCodeTraceRequirement model."""

    def test_create_basic(self) -> None:
        req = ModelCodeTraceRequirement(
            file_path="src/foo.py",
            reason="Contains the handler",
        )
        assert req.file_path == "src/foo.py"
        assert req.status == EnumTraceStatus.PENDING
        assert req.trace_points == []

    def test_with_trace_points(self) -> None:
        req = ModelCodeTraceRequirement(
            file_path="src/handler.py",
            reason="Main handler",
            trace_points=["class FooHandler", "def execute"],
        )
        assert len(req.trace_points) == 2


@pytest.mark.unit
class TestModelCodeTraceBlock:
    """Tests for ModelCodeTraceBlock model."""

    def test_all_completed_empty(self) -> None:
        block = ModelCodeTraceBlock(ticket_id="OMN-1234")
        assert block.all_completed is True  # vacuously true

    def test_all_completed_mixed(self) -> None:
        block = ModelCodeTraceBlock(
            ticket_id="OMN-1234",
            requirements=[
                ModelCodeTraceRequirement(
                    file_path="a.py",
                    reason="test",
                    status=EnumTraceStatus.COMPLETED,
                ),
                ModelCodeTraceRequirement(
                    file_path="b.py",
                    reason="test",
                    status=EnumTraceStatus.PENDING,
                ),
            ],
        )
        assert block.all_completed is False
        assert block.pending_count == 1

    def test_all_completed_with_skipped(self) -> None:
        block = ModelCodeTraceBlock(
            ticket_id="OMN-1234",
            requirements=[
                ModelCodeTraceRequirement(
                    file_path="a.py",
                    reason="test",
                    status=EnumTraceStatus.COMPLETED,
                ),
                ModelCodeTraceRequirement(
                    file_path="b.py",
                    reason="test",
                    status=EnumTraceStatus.SKIPPED,
                ),
            ],
        )
        assert block.all_completed is True
        assert block.pending_count == 0


@pytest.mark.unit
class TestModelCodeTraceConfig:
    """Tests for configuration loading."""

    def test_defaults(self) -> None:
        config = ModelCodeTraceConfig()
        assert config.enabled is True
        assert config.min_files == 2

    def test_from_env_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OMNICLAUDE_CODE_TRACING_ENABLED", raising=False)
        monkeypatch.delenv("OMNICLAUDE_CODE_TRACING_MIN_FILES", raising=False)
        config = ModelCodeTraceConfig.from_env()
        assert config.enabled is True
        assert config.min_files == 2

    def test_from_env_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OMNICLAUDE_CODE_TRACING_ENABLED", "false")
        config = ModelCodeTraceConfig.from_env()
        assert config.enabled is False

    def test_from_env_custom_min(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OMNICLAUDE_CODE_TRACING_MIN_FILES", "5")
        config = ModelCodeTraceConfig.from_env()
        assert config.min_files == 5

    def test_from_env_invalid_falls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OMNICLAUDE_CODE_TRACING_MIN_FILES", "abc")
        config = ModelCodeTraceConfig.from_env()
        assert config.min_files == 2


@pytest.mark.unit
class TestBuildTraceRequirements:
    """Tests for building trace requirements from research output."""

    def test_basic_build(self) -> None:
        block = build_trace_requirements(
            relevant_files=["src/handler.py", "src/model.py"],
            ticket_id="OMN-5678",
        )
        assert block.ticket_id == "OMN-5678"
        assert len(block.requirements) == 2
        assert block.requirements[0].file_path == "src/handler.py"
        assert block.requirements[1].file_path == "src/model.py"
        assert all(r.status == EnumTraceStatus.PENDING for r in block.requirements)

    def test_empty_files(self) -> None:
        block = build_trace_requirements(
            relevant_files=[],
            ticket_id="OMN-9999",
        )
        assert len(block.requirements) == 0
        assert block.all_completed is True


@pytest.mark.unit
class TestFormatTracePromptSection:
    """Tests for prompt section formatting."""

    def test_disabled_returns_empty(self) -> None:
        block = ModelCodeTraceBlock(
            ticket_id="OMN-1234",
            requirements=[
                ModelCodeTraceRequirement(
                    file_path="a.py",
                    reason="test",
                ),
            ],
        )
        config = ModelCodeTraceConfig(enabled=False)
        result = format_trace_prompt_section(block, config=config)
        assert result == ""

    def test_empty_requirements_returns_empty(self) -> None:
        block = ModelCodeTraceBlock(ticket_id="OMN-1234")
        result = format_trace_prompt_section(block)
        assert result == ""

    def test_formats_requirements(self) -> None:
        block = ModelCodeTraceBlock(
            ticket_id="OMN-1234",
            requirements=[
                ModelCodeTraceRequirement(
                    file_path="src/handler.py",
                    reason="Main handler to modify",
                ),
                ModelCodeTraceRequirement(
                    file_path="src/model.py",
                    reason="Model definitions",
                    trace_points=["class ModelFoo"],
                ),
            ],
        )
        config = ModelCodeTraceConfig(enabled=True, min_files=2)
        result = format_trace_prompt_section(block, config=config)

        assert "## Mandatory Code Tracing" in result
        assert "`src/handler.py`" in result
        assert "`src/model.py`" in result
        assert "Main handler to modify" in result
        assert "`class ModelFoo`" in result
        assert "at least 2 files" in result

    def test_completed_has_checkmark(self) -> None:
        block = ModelCodeTraceBlock(
            ticket_id="OMN-1234",
            requirements=[
                ModelCodeTraceRequirement(
                    file_path="a.py",
                    reason="done",
                    status=EnumTraceStatus.COMPLETED,
                ),
                ModelCodeTraceRequirement(
                    file_path="b.py",
                    reason="pending",
                    status=EnumTraceStatus.PENDING,
                ),
            ],
        )
        result = format_trace_prompt_section(block)
        assert "[x] `a.py`" in result
        assert "[ ] `b.py`" in result
