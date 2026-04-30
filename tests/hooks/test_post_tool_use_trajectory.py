# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for PostToolUse PRM trajectory hook (OMN-10370)."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from omniclaude.hooks.post_tool_use_trajectory import (
    HookResult,
    _extract_result,
    _extract_target,
    build_trajectory_entry,
    process_tool_envelope,
)

# ---------------------------------------------------------------------------
# Minimal local stubs — used only in tests, independent of omnibase_core
# ---------------------------------------------------------------------------


@dataclass
class _StubTrajectoryEntry:
    step: int
    agent: str
    action: str
    target: str
    result: str


@dataclass
class _StubPrmMatch:
    dedup_key: str = "test:a:b:0-1"
    severity_level: int = 1


@dataclass
class _StubEscalationResult:
    severity_level: int
    course_correction: str


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def read_envelope() -> dict:
    return {
        "sessionId": "test-session-001",
        "tool_name": "Read",
        "tool_input": {"file_path": "/src/foo.py"},
        "tool_response": {"content": "def foo(): ..."},
    }


@pytest.fixture
def edit_envelope() -> dict:
    return {
        "sessionId": "test-session-001",
        "tool_name": "Edit",
        "tool_input": {"file_path": "/src/bar.py", "new_content": "x = 1"},
        "tool_response": {"success": True},
    }


@pytest.fixture(autouse=True)
def reset_store_singleton() -> None:
    """Reset module-level trajectory_store singleton between tests."""
    import omniclaude.hooks.post_tool_use_trajectory as m

    m.trajectory_store = None
    m._last_processed_step = 0
    yield
    m.trajectory_store = None
    m._last_processed_step = 0


# ---------------------------------------------------------------------------
# _extract_target tests
# ---------------------------------------------------------------------------


class TestExtractTarget:
    def test_file_path_preferred(self) -> None:
        assert (
            _extract_target("Read", {"file_path": "/src/foo.py", "command": "ls"})
            == "/src/foo.py"
        )

    def test_command_fallback(self) -> None:
        assert _extract_target("Bash", {"command": "ls -la"}) == "ls -la"

    def test_empty_when_no_string_values(self) -> None:
        assert _extract_target("Task", {"count": 3}) == ""

    def test_first_string_value_as_fallback(self) -> None:
        target = _extract_target("TaskCreate", {"subject": "my task"})
        assert target == "my task"


class TestExtractResult:
    def test_error_when_error_field(self) -> None:
        assert _extract_result({"error": "file not found"}) == "error"

    def test_ok_on_empty(self) -> None:
        assert _extract_result({}) == "ok"

    def test_ok_on_success(self) -> None:
        assert _extract_result({"content": "data"}) == "ok"


# ---------------------------------------------------------------------------
# build_trajectory_entry tests
# ---------------------------------------------------------------------------


class TestBuildTrajectoryEntry:
    def test_constructs_entry_from_read_envelope(self, read_envelope: dict) -> None:
        stub_entry = _StubTrajectoryEntry(
            step=1,
            agent="test-session-001",
            action="Read",
            target="/src/foo.py",
            result="ok",
        )
        with patch(
            "omniclaude.hooks.post_tool_use_trajectory._make_trajectory_entry",
            return_value=stub_entry,
        ) as mock_make:
            entry = build_trajectory_entry(step=1, envelope=read_envelope)
            mock_make.assert_called_once_with(
                step=1,
                agent="test-session-001",
                action="Read",
                target="/src/foo.py",
                result="ok",
            )
        assert entry.step == 1
        assert entry.agent == "test-session-001"
        assert entry.action == "Read"
        assert entry.target == "/src/foo.py"

    def test_constructs_entry_from_edit_envelope(self, edit_envelope: dict) -> None:
        stub_entry = _StubTrajectoryEntry(
            step=2,
            agent="test-session-001",
            action="Edit",
            target="/src/bar.py",
            result="ok",
        )
        with patch(
            "omniclaude.hooks.post_tool_use_trajectory._make_trajectory_entry",
            return_value=stub_entry,
        ):
            entry = build_trajectory_entry(step=2, envelope=edit_envelope)
        assert entry.action == "Edit"
        assert entry.target == "/src/bar.py"

    def test_result_is_error_when_response_has_error(self) -> None:
        envelope = {
            "sessionId": "s1",
            "tool_name": "Read",
            "tool_input": {"file_path": "/missing.py"},
            "tool_response": {"error": "file not found"},
        }
        stub_entry = _StubTrajectoryEntry(
            step=4,
            agent="s1",
            action="Read",
            target="/missing.py",
            result="error",
        )
        with patch(
            "omniclaude.hooks.post_tool_use_trajectory._make_trajectory_entry",
            return_value=stub_entry,
        ) as mock_make:
            build_trajectory_entry(step=4, envelope=envelope)
            _, kwargs = mock_make.call_args
            assert kwargs["result"] == "error"

    def test_bash_target_is_command(self) -> None:
        envelope = {
            "sessionId": "s1",
            "tool_name": "Bash",
            "tool_input": {"command": "ls -la"},
            "tool_response": {"output": "..."},
        }
        stub_entry = _StubTrajectoryEntry(
            step=3,
            agent="s1",
            action="Bash",
            target="ls -la",
            result="ok",
        )
        with patch(
            "omniclaude.hooks.post_tool_use_trajectory._make_trajectory_entry",
            return_value=stub_entry,
        ) as mock_make:
            build_trajectory_entry(step=3, envelope=envelope)
            _, kwargs = mock_make.call_args
            assert kwargs["target"] == "ls -la"


# ---------------------------------------------------------------------------
# process_tool_envelope tests
# ---------------------------------------------------------------------------


class TestProcessToolEnvelope:
    def _make_mock_store(self, entries: list | None = None) -> MagicMock:
        mock_store = MagicMock()
        mock_store.read_recent.return_value = entries or []
        return mock_store

    def test_severity_0_returns_allow_with_no_context(
        self, read_envelope: dict
    ) -> None:
        mock_store = self._make_mock_store()
        with (
            patch(
                "omniclaude.hooks.post_tool_use_trajectory._get_store",
                return_value=mock_store,
            ),
            patch(
                "omniclaude.hooks.post_tool_use_trajectory.build_trajectory_entry",
                return_value=_StubTrajectoryEntry(
                    step=1, agent="s", action="Read", target="/f", result="ok"
                ),
            ),
            patch(
                "omniclaude.hooks.post_tool_use_trajectory._run_detectors",
                return_value=[],
            ),
            patch(
                "omniclaude.hooks.post_tool_use_trajectory._escalate_matches",
                return_value=[],
            ),
        ):
            result = process_tool_envelope(read_envelope, step=1)

        assert result.exit_code == 0
        assert result.additional_context is None

    def test_severity_1_injects_context(self, edit_envelope: dict) -> None:
        mock_store = self._make_mock_store()
        esc_result = _StubEscalationResult(
            severity_level=1, course_correction="Stop and reassess your approach."
        )

        with (
            patch(
                "omniclaude.hooks.post_tool_use_trajectory._get_store",
                return_value=mock_store,
            ),
            patch(
                "omniclaude.hooks.post_tool_use_trajectory.build_trajectory_entry",
                return_value=_StubTrajectoryEntry(
                    step=2, agent="s", action="Edit", target="/f", result="ok"
                ),
            ),
            patch(
                "omniclaude.hooks.post_tool_use_trajectory._run_detectors",
                return_value=[_StubPrmMatch()],
            ),
            patch(
                "omniclaude.hooks.post_tool_use_trajectory._escalate_matches",
                return_value=[esc_result],
            ),
        ):
            result = process_tool_envelope(edit_envelope, step=2)

        assert result.exit_code == 0
        assert result.additional_context is not None
        assert "Stop and reassess" in result.additional_context

    def test_severity_3_returns_nonzero_exit(self, edit_envelope: dict) -> None:
        mock_store = self._make_mock_store()
        esc_result = _StubEscalationResult(
            severity_level=3,
            course_correction="HARD STOP: pattern escalated to level 3.",
        )

        with (
            patch(
                "omniclaude.hooks.post_tool_use_trajectory._get_store",
                return_value=mock_store,
            ),
            patch(
                "omniclaude.hooks.post_tool_use_trajectory.build_trajectory_entry",
                return_value=_StubTrajectoryEntry(
                    step=3, agent="s", action="Edit", target="/f", result="ok"
                ),
            ),
            patch(
                "omniclaude.hooks.post_tool_use_trajectory._run_detectors",
                return_value=[_StubPrmMatch()],
            ),
            patch(
                "omniclaude.hooks.post_tool_use_trajectory._escalate_matches",
                return_value=[esc_result],
            ),
        ):
            result = process_tool_envelope(edit_envelope, step=3)

        assert result.exit_code != 0
        assert result.additional_context is not None
        assert "HARD STOP" in result.additional_context

    def test_severity_2_injects_context_exits_0(self, edit_envelope: dict) -> None:
        mock_store = self._make_mock_store()
        esc_result = _StubEscalationResult(
            severity_level=2, course_correction="WARNING: repeated pattern detected."
        )

        with (
            patch(
                "omniclaude.hooks.post_tool_use_trajectory._get_store",
                return_value=mock_store,
            ),
            patch(
                "omniclaude.hooks.post_tool_use_trajectory.build_trajectory_entry",
                return_value=_StubTrajectoryEntry(
                    step=4, agent="s", action="Edit", target="/f", result="ok"
                ),
            ),
            patch(
                "omniclaude.hooks.post_tool_use_trajectory._run_detectors",
                return_value=[_StubPrmMatch()],
            ),
            patch(
                "omniclaude.hooks.post_tool_use_trajectory._escalate_matches",
                return_value=[esc_result],
            ),
        ):
            result = process_tool_envelope(edit_envelope, step=4)

        assert result.exit_code == 0
        assert result.additional_context is not None
        assert "WARNING" in result.additional_context

    def test_trajectory_store_append_called(self, read_envelope: dict) -> None:
        mock_store = self._make_mock_store()
        stub_entry = _StubTrajectoryEntry(
            step=1, agent="s", action="Read", target="/f", result="ok"
        )

        with (
            patch(
                "omniclaude.hooks.post_tool_use_trajectory._get_store",
                return_value=mock_store,
            ),
            patch(
                "omniclaude.hooks.post_tool_use_trajectory.build_trajectory_entry",
                return_value=stub_entry,
            ),
            patch(
                "omniclaude.hooks.post_tool_use_trajectory._run_detectors",
                return_value=[],
            ),
            patch(
                "omniclaude.hooks.post_tool_use_trajectory._escalate_matches",
                return_value=[],
            ),
        ):
            process_tool_envelope(read_envelope, step=1)

        mock_store.append.assert_called_once_with(stub_entry)

    def test_all_five_detectors_invoked_via_run_detectors(
        self, read_envelope: dict
    ) -> None:
        mock_store = self._make_mock_store()

        with (
            patch(
                "omniclaude.hooks.post_tool_use_trajectory._get_store",
                return_value=mock_store,
            ),
            patch(
                "omniclaude.hooks.post_tool_use_trajectory.build_trajectory_entry",
                return_value=_StubTrajectoryEntry(
                    step=1, agent="s", action="Read", target="/f", result="ok"
                ),
            ),
            patch(
                "omniclaude.hooks.post_tool_use_trajectory._run_detectors",
                return_value=[],
            ) as mock_run,
            patch(
                "omniclaude.hooks.post_tool_use_trajectory._escalate_matches",
                return_value=[],
            ),
        ):
            process_tool_envelope(read_envelope, step=1)

        mock_run.assert_called_once()
        call_entries = mock_run.call_args[0][0]
        assert isinstance(call_entries, list)

    def test_multiple_escalations_use_max_severity(self, edit_envelope: dict) -> None:
        mock_store = self._make_mock_store()
        esc1 = _StubEscalationResult(severity_level=1, course_correction="advisory")
        esc3 = _StubEscalationResult(severity_level=3, course_correction="HARD STOP")

        with (
            patch(
                "omniclaude.hooks.post_tool_use_trajectory._get_store",
                return_value=mock_store,
            ),
            patch(
                "omniclaude.hooks.post_tool_use_trajectory.build_trajectory_entry",
                return_value=_StubTrajectoryEntry(
                    step=1, agent="s", action="Edit", target="/f", result="ok"
                ),
            ),
            patch(
                "omniclaude.hooks.post_tool_use_trajectory._run_detectors",
                return_value=[_StubPrmMatch(), _StubPrmMatch()],
            ),
            patch(
                "omniclaude.hooks.post_tool_use_trajectory._escalate_matches",
                return_value=[esc1, esc3],
            ),
        ):
            result = process_tool_envelope(edit_envelope, step=1)

        assert result.exit_code != 0
        assert "advisory" in result.additional_context
        assert "HARD STOP" in result.additional_context


# ---------------------------------------------------------------------------
# HookResult tests
# ---------------------------------------------------------------------------


class TestHookResult:
    def test_hook_result_allow(self) -> None:
        r = HookResult(exit_code=0, additional_context=None)
        assert r.exit_code == 0
        assert r.additional_context is None

    def test_hook_result_block(self) -> None:
        r = HookResult(exit_code=2, additional_context="stop now")
        assert r.exit_code == 2
        assert r.additional_context == "stop now"
