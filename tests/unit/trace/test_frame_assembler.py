# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for omniclaude.trace.frame_assembler.

Tests cover:
- should_trace_tool() correctly classifies tools
- run_git_diff_patch() returns diff or empty string
- parse_diff_stats() extracts files and LOC counts
- sha256_of() produces expected hashes
- assemble_change_frame() returns None for non-write tools
- assemble_change_frame() returns None when diff is empty
- assemble_change_frame() assembles complete frame for valid write
- assemble_change_frame() computes failure signature when checks fail
- persist_frame_to_jsonl() writes to correct file

All subprocess calls are mocked to avoid infrastructure dependencies.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

from omniclaude.trace.change_frame import FailureType
from omniclaude.trace.frame_assembler import (
    CheckSpec,
    SessionContext,
    assemble_change_frame,
    emit_change_frame,
    parse_diff_stats,
    persist_frame_to_jsonl,
    run_git_diff_patch,
    sha256_of,
    sha256_of_dict,
    should_trace_tool,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_DIFF = """--- a/src/foo.py
+++ b/src/foo.py
@@ -1,3 +1,4 @@
 def old_function():
-    return None
+    return "fixed"
+
+# new comment
"""

SAMPLE_SESSION = SessionContext(
    session_id="sess-abc123",
    trace_id="trace-xyz789",
    agent_id="polymorphic-agent",
    model_id="claude-opus-4-6",
    prompt_hash="abc123def456" * 4,
    repo_root="/repo",
    ticket_id="OMN-9999",
    temperature=0.0,
    seed=42,
)


# ---------------------------------------------------------------------------
# should_trace_tool tests
# ---------------------------------------------------------------------------


class TestShouldTraceTool:
    def test_write_tool_is_traced(self) -> None:
        assert should_trace_tool("Write") is True

    def test_edit_tool_is_traced(self) -> None:
        assert should_trace_tool("Edit") is True

    def test_bash_tool_is_traced(self) -> None:
        assert should_trace_tool("Bash") is True

    def test_notebook_edit_is_traced(self) -> None:
        assert should_trace_tool("NotebookEdit") is True

    def test_read_tool_not_traced(self) -> None:
        assert should_trace_tool("Read") is False

    def test_glob_tool_not_traced(self) -> None:
        assert should_trace_tool("Glob") is False

    def test_grep_tool_not_traced(self) -> None:
        assert should_trace_tool("Grep") is False

    def test_unknown_tool_not_traced(self) -> None:
        assert should_trace_tool("SomeUnknownTool") is False


# ---------------------------------------------------------------------------
# parse_diff_stats tests
# ---------------------------------------------------------------------------


class TestParseDiffStats:
    def test_parses_files_changed(self) -> None:
        files, _added, _removed = parse_diff_stats(SAMPLE_DIFF)
        assert "src/foo.py" in files

    def test_counts_added_lines(self) -> None:
        _, added, _ = parse_diff_stats(SAMPLE_DIFF)
        assert added == 3  # "+    return 'fixed'", "+", "+# new comment"

    def test_counts_removed_lines(self) -> None:
        _, _, removed = parse_diff_stats(SAMPLE_DIFF)
        assert removed == 1  # "-    return None"

    def test_empty_diff_returns_empty_stats(self) -> None:
        files, added, removed = parse_diff_stats("")
        assert files == []
        assert added == 0
        assert removed == 0

    def test_multiple_files(self) -> None:
        diff = (
            "--- a/src/a.py\n+++ b/src/a.py\n@@ -1 +1 @@\n+new\n"
            "--- a/src/b.py\n+++ b/src/b.py\n@@ -1 +1 @@\n+new\n"
        )
        files, _, _ = parse_diff_stats(diff)
        assert "src/a.py" in files
        assert "src/b.py" in files

    def test_no_duplicate_files(self) -> None:
        diff = (
            "--- a/src/a.py\n+++ b/src/a.py\n@@ -1 +1 @@\n+new\n"
            "+++ b/src/a.py\n@@ -1 +1 @@\n+new2\n"
        )
        files, _, _ = parse_diff_stats(diff)
        assert files.count("src/a.py") == 1


# ---------------------------------------------------------------------------
# Hash helper tests
# ---------------------------------------------------------------------------


class TestHashHelpers:
    def test_sha256_of_deterministic(self) -> None:
        h1 = sha256_of("hello")
        h2 = sha256_of("hello")
        assert h1 == h2

    def test_sha256_of_length(self) -> None:
        assert len(sha256_of("any string")) == 64

    def test_sha256_of_different_inputs(self) -> None:
        assert sha256_of("a") != sha256_of("b")

    def test_sha256_of_dict_deterministic(self) -> None:
        d = {"key": "value", "num": 42}
        h1 = sha256_of_dict(d)
        h2 = sha256_of_dict(d)
        assert h1 == h2

    def test_sha256_of_dict_key_order_independent(self) -> None:
        d1 = {"a": 1, "b": 2}
        d2 = {"b": 2, "a": 1}
        assert sha256_of_dict(d1) == sha256_of_dict(d2)


# ---------------------------------------------------------------------------
# run_git_diff_patch tests (mocked subprocess)
# ---------------------------------------------------------------------------


class TestRunGitDiffPatch:
    @patch("omniclaude.trace.frame_assembler.subprocess.run")
    def test_returns_diff_when_available(self, mock_run: MagicMock) -> None:
        # HEAD diff returns a patch; ls-files returns no untracked files.
        def side_effect(cmd: list, **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 0
            cmd_str = " ".join(str(c) for c in cmd)
            if "ls-files" in cmd_str:
                result.stdout = ""
            else:
                result.stdout = SAMPLE_DIFF
            return result

        mock_run.side_effect = side_effect
        diff = run_git_diff_patch("/repo")
        assert diff == SAMPLE_DIFF.strip()

    @patch("omniclaude.trace.frame_assembler.subprocess.run")
    def test_returns_empty_when_no_diff(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout="", returncode=0)
        diff = run_git_diff_patch("/repo")
        assert diff == ""

    @patch("omniclaude.trace.frame_assembler.subprocess.run")
    def test_returns_empty_on_subprocess_error(self, mock_run: MagicMock) -> None:
        import subprocess

        mock_run.side_effect = subprocess.SubprocessError("git not found")
        diff = run_git_diff_patch("/repo")
        assert diff == ""

    @patch("omniclaude.trace.frame_assembler.subprocess.run")
    def test_returns_empty_on_timeout(self, mock_run: MagicMock) -> None:
        import subprocess

        mock_run.side_effect = subprocess.TimeoutExpired("git", 10)
        diff = run_git_diff_patch("/repo")
        assert diff == ""

    @patch("omniclaude.trace.frame_assembler.subprocess.run")
    def test_includes_untracked_new_files(self, mock_run: MagicMock) -> None:
        """Newly created (untracked) files must appear in the returned diff."""
        untracked_diff = (
            "--- /dev/null\n"
            "+++ b/src/new_file.py\n"
            "@@ -0,0 +1,2 @@\n"
            "+def hello():\n"
            '+    return "world"\n'
        )

        def side_effect(cmd: list, **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 0
            cmd_str = " ".join(str(c) for c in cmd)
            if "ls-files" in cmd_str:
                result.stdout = "src/new_file.py\n"
            elif "no-index" in cmd_str:
                result.stdout = untracked_diff
                result.returncode = 1  # git diff --no-index exits 1 when files differ
            else:
                result.stdout = ""
            return result

        mock_run.side_effect = side_effect
        diff = run_git_diff_patch("/repo")
        assert "src/new_file.py" in diff
        assert "+def hello():" in diff


# ---------------------------------------------------------------------------
# assemble_change_frame tests (mocked git and checks)
# ---------------------------------------------------------------------------


class TestAssembleChangeFrame:
    def _mock_subprocess_run(
        self, mock_run: MagicMock, diff: str = SAMPLE_DIFF
    ) -> None:
        """Set up subprocess.run to return expected values for git and checks."""

        def side_effect(cmd: list, **kwargs: object) -> MagicMock:
            cmd_str = " ".join(str(c) for c in cmd)
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""

            if "diff" in cmd_str:
                result.stdout = diff
            elif "rev-parse HEAD" in cmd_str:
                result.stdout = "abc1234567890abcdef"
            elif "abbrev-ref" in cmd_str:
                result.stdout = "main"
            elif "remote get-url" in cmd_str:
                result.stdout = "git@github.com:org/repo.git"
            elif "pip freeze" in cmd_str or "uv pip" in cmd_str:
                result.stdout = "pydantic==2.0.0\nuv==0.1.0\n"

            return result

        mock_run.side_effect = side_effect

    @patch("omniclaude.trace.frame_assembler.subprocess.run")
    def test_returns_none_for_non_write_tool(self, mock_run: MagicMock) -> None:
        """Read tool should return None (not traced)."""
        frame = assemble_change_frame(
            tool_name="Read",
            tool_input={"file_path": "/foo.py"},
            tool_output="file contents",
            session_context=SAMPLE_SESSION,
            timestamp_utc="2026-02-19T14:22:31Z",
        )
        assert frame is None

    @patch("omniclaude.trace.frame_assembler.subprocess.run")
    def test_returns_none_when_diff_empty(self, mock_run: MagicMock) -> None:
        """Empty git diff should return None (nothing to trace)."""
        self._mock_subprocess_run(mock_run, diff="")
        frame = assemble_change_frame(
            tool_name="Write",
            tool_input={"file_path": "/foo.py"},
            tool_output="ok",
            session_context=SAMPLE_SESSION,
            timestamp_utc="2026-02-19T14:22:31Z",
            checks=[],  # Skip checks for this test
        )
        assert frame is None

    @patch("omniclaude.trace.frame_assembler.subprocess.run")
    def test_returns_frame_for_valid_write(self, mock_run: MagicMock) -> None:
        """Valid Write with non-empty diff should return assembled ChangeFrame."""
        self._mock_subprocess_run(mock_run)

        # Use a minimal check that always passes
        passing_check = CheckSpec(
            command=["echo", "ok"],
            failure_type=FailureType.LINT_FAIL,
        )

        # Override run_checks to return a passing result
        with patch("omniclaude.trace.frame_assembler.run_checks") as mock_checks:
            from omniclaude.trace.change_frame import ModelCheckResult

            mock_checks.return_value = [
                ModelCheckResult(
                    command="echo ok",
                    environment_hash="envhash",
                    exit_code=0,
                    output_hash="outhash",
                )
            ]
            frame = assemble_change_frame(
                tool_name="Write",
                tool_input={"file_path": "/repo/src/foo.py", "content": "new content"},
                tool_output="File written",
                session_context=SAMPLE_SESSION,
                timestamp_utc="2026-02-19T14:22:31Z",
                checks=[passing_check],
            )

        assert frame is not None
        assert frame.outcome.status == "pass"
        assert frame.delta.diff_patch == SAMPLE_DIFF.strip()
        assert frame.agent_id == SAMPLE_SESSION.agent_id
        assert frame.trace_id == SAMPLE_SESSION.trace_id

    @patch("omniclaude.trace.frame_assembler.subprocess.run")
    def test_outcome_fail_when_checks_fail(self, mock_run: MagicMock) -> None:
        """Outcome should be 'fail' when all checks fail."""
        self._mock_subprocess_run(mock_run)

        with patch("omniclaude.trace.frame_assembler.run_checks") as mock_checks:
            from omniclaude.trace.change_frame import ModelCheckResult

            mock_checks.return_value = [
                ModelCheckResult(
                    command="pytest",
                    environment_hash="envhash",
                    exit_code=1,
                    output_hash="outhash",
                    truncated_output="FAILED test_foo.py::test_bar AssertionError",
                )
            ]
            frame = assemble_change_frame(
                tool_name="Edit",
                tool_input={"file_path": "/repo/src/foo.py"},
                tool_output="ok",
                session_context=SAMPLE_SESSION,
                timestamp_utc="2026-02-19T14:22:31Z",
            )

        assert frame is not None
        assert frame.outcome.status == "fail"
        assert frame.outcome.failure_signature_id is not None

    @patch("omniclaude.trace.frame_assembler.subprocess.run")
    def test_outcome_partial_when_some_checks_fail(self, mock_run: MagicMock) -> None:
        """Outcome should be 'partial' when some but not all checks fail."""
        self._mock_subprocess_run(mock_run)

        with patch("omniclaude.trace.frame_assembler.run_checks") as mock_checks:
            from omniclaude.trace.change_frame import ModelCheckResult

            mock_checks.return_value = [
                ModelCheckResult(
                    command="ruff check",
                    environment_hash="envhash",
                    exit_code=0,
                    output_hash="outhash",
                ),
                ModelCheckResult(
                    command="mypy",
                    environment_hash="envhash",
                    exit_code=1,
                    output_hash="outhash",
                    truncated_output="error: Incompatible type",
                ),
            ]
            frame = assemble_change_frame(
                tool_name="Write",
                tool_input={},
                tool_output="ok",
                session_context=SAMPLE_SESSION,
                timestamp_utc="2026-02-19T14:22:31Z",
            )

        assert frame is not None
        assert frame.outcome.status == "partial"

    @patch("omniclaude.trace.frame_assembler.subprocess.run")
    def test_frame_has_tool_event(self, mock_run: MagicMock) -> None:
        """Assembled frame should contain a tool event record."""
        self._mock_subprocess_run(mock_run)

        with patch("omniclaude.trace.frame_assembler.run_checks") as mock_checks:
            from omniclaude.trace.change_frame import ModelCheckResult

            mock_checks.return_value = [
                ModelCheckResult(
                    command="ruff",
                    environment_hash="h",
                    exit_code=0,
                    output_hash="h",
                )
            ]
            frame = assemble_change_frame(
                tool_name="Bash",
                tool_input={"command": "echo hello"},
                tool_output="hello",
                session_context=SAMPLE_SESSION,
                timestamp_utc="2026-02-19T14:22:31Z",
            )

        assert frame is not None
        assert len(frame.tool_events) == 1
        assert frame.tool_events[0].tool_name == "Bash"

    @patch("omniclaude.trace.frame_assembler.subprocess.run")
    def test_frame_uses_injected_timestamp(self, mock_run: MagicMock) -> None:
        """Frame timestamp must use injected value, not datetime.now()."""
        self._mock_subprocess_run(mock_run)
        ts = "2026-02-19T14:22:31Z"

        with patch("omniclaude.trace.frame_assembler.run_checks") as mock_checks:
            from omniclaude.trace.change_frame import ModelCheckResult

            mock_checks.return_value = [
                ModelCheckResult(
                    command="c", environment_hash="h", exit_code=0, output_hash="h"
                )
            ]
            frame = assemble_change_frame(
                tool_name="Write",
                tool_input={},
                tool_output="",
                session_context=SAMPLE_SESSION,
                timestamp_utc=ts,
            )

        assert frame is not None
        assert frame.timestamp_utc == ts


# ---------------------------------------------------------------------------
# persist_frame_to_jsonl tests
# ---------------------------------------------------------------------------


class TestPersistFrameToJsonl:
    def test_creates_file_and_appends(self, tmp_path: Path) -> None:
        """persist_frame_to_jsonl should create file and write JSONL."""

        from omniclaude.trace.frame_assembler import persist_frame_to_jsonl

        # Build a minimal valid ChangeFrame
        with patch("omniclaude.trace.frame_assembler.subprocess.run") as mock_run:

            def side_effect(cmd: list, **kwargs: object) -> MagicMock:
                result = MagicMock()
                result.returncode = 0
                result.stdout = (
                    SAMPLE_DIFF
                    if "diff" in " ".join(str(c) for c in cmd)
                    else "abc123\n"
                )
                result.stderr = ""
                return result

            mock_run.side_effect = side_effect

            with patch("omniclaude.trace.frame_assembler.run_checks") as mock_checks:
                from omniclaude.trace.change_frame import ModelCheckResult

                mock_checks.return_value = [
                    ModelCheckResult(
                        command="c", environment_hash="h", exit_code=0, output_hash="h"
                    )
                ]

                # Patch home directory to tmp_path
                with patch(
                    "omniclaude.trace.frame_assembler.Path.home", return_value=tmp_path
                ):
                    frame = assemble_change_frame(
                        tool_name="Write",
                        tool_input={},
                        tool_output="ok",
                        session_context=SAMPLE_SESSION,
                        timestamp_utc="2026-02-19T14:22:31Z",
                    )

                assert frame is not None

                with patch(
                    "omniclaude.trace.frame_assembler.Path.home", return_value=tmp_path
                ):
                    jsonl_path = persist_frame_to_jsonl(frame, "test-session")

                assert jsonl_path.exists()
                lines = jsonl_path.read_text().strip().split("\n")
                assert len(lines) == 1
                parsed = json.loads(lines[0])
                assert "frame_id" in parsed

    def test_appends_multiple_frames(self, tmp_path: Path) -> None:
        """Multiple frames should append as separate JSONL lines."""
        from omniclaude.trace.change_frame import (
            ChangeFrame,
            ModelCheckResult,
            ModelDelta,
            ModelEvidence,
            ModelFrameConfig,
            ModelIntentRef,
            ModelOutcome,
            ModelWorkspaceRef,
        )

        def make_frame() -> ChangeFrame:
            return ChangeFrame(
                frame_id=uuid4(),
                trace_id="trace-1",
                timestamp_utc="2026-02-19T14:22:31Z",
                agent_id="agent",
                model_id="model",
                frame_config=ModelFrameConfig(),
                intent_ref=ModelIntentRef(prompt_hash="abc123"),
                workspace_ref=ModelWorkspaceRef(
                    repo="repo", branch="main", base_commit="abc"
                ),
                delta=ModelDelta(
                    diff_patch="--- a/f\n+++ b/f\n@@ -1 +1 @@\n+new\n",
                    files_changed=["f"],
                    loc_added=1,
                    loc_removed=0,
                ),
                checks=[
                    ModelCheckResult(
                        command="c", environment_hash="h", exit_code=0, output_hash="h"
                    )
                ],
                outcome=ModelOutcome(status="pass"),
                evidence=ModelEvidence(),
            )

        with patch("omniclaude.trace.frame_assembler.Path.home", return_value=tmp_path):
            p1 = persist_frame_to_jsonl(make_frame(), "sess-1")
            p2 = persist_frame_to_jsonl(make_frame(), "sess-1")

        assert p1 == p2
        lines = p1.read_text().strip().split("\n")
        assert len(lines) == 2


# ===========================================================================
# emit_change_frame tests (OMN-2651)
# ===========================================================================

import pytest

from omniclaude.trace.change_frame import (
    ChangeFrame,
    ModelCheckResult,
    ModelDelta,
    ModelEvidence,
    ModelFrameConfig,
    ModelIntentRef,
    ModelOutcome,
    ModelWorkspaceRef,
)


def _make_frame() -> ChangeFrame:
    """Build a minimal valid ChangeFrame for testing."""
    return ChangeFrame(
        frame_id=uuid4(),
        trace_id="trace-emit-test",
        timestamp_utc="2026-02-23T12:00:00Z",
        agent_id="test-agent",
        model_id="test-model",
        frame_config=ModelFrameConfig(),
        intent_ref=ModelIntentRef(prompt_hash="abc123"),
        workspace_ref=ModelWorkspaceRef(
            repo="test-repo", branch="main", base_commit="deadbeef"
        ),
        delta=ModelDelta(
            diff_patch="--- a/f\n+++ b/f\n@@ -1 +1 @@\n+new\n",
            files_changed=["f"],
            loc_added=1,
            loc_removed=0,
        ),
        checks=[
            ModelCheckResult(
                command="check", environment_hash="h", exit_code=0, output_hash="h"
            )
        ],
        outcome=ModelOutcome(status="pass"),
        evidence=ModelEvidence(),
    )


@pytest.mark.unit
class TestEmitChangeFrame:
    """Tests for emit_change_frame (OMN-2651)."""

    def test_emit_calls_emit_event_with_correct_args(self) -> None:
        """emit_change_frame should call emit_event with the right event type and payload."""
        frame = _make_frame()
        mock_emit = MagicMock(return_value=True)

        with patch.dict(
            "sys.modules",
            {"emit_client_wrapper": MagicMock(emit_event=mock_emit)},
        ):
            # Re-import to pick up the mock
            import importlib

            import omniclaude.trace.frame_assembler as mod

            importlib.reload(mod)
            result = mod.emit_change_frame(frame, "session-123")

        assert result is True
        mock_emit.assert_called_once()
        call_args = mock_emit.call_args
        assert call_args[0][0] == "change.frame.emitted"
        payload = call_args[0][1]
        assert payload["session_id"] == "session-123"
        assert payload["frame_id"] == str(frame.frame_id)
        assert payload["trace_id"] == "trace-emit-test"

    def test_emit_returns_false_when_import_fails(self) -> None:
        """emit_change_frame returns False when emit_client_wrapper is unavailable."""
        frame = _make_frame()

        with patch.dict("sys.modules", {"emit_client_wrapper": None}):
            result = emit_change_frame(frame, "session-123")

        assert result is False

    def test_emit_returns_false_on_exception(self) -> None:
        """emit_change_frame returns False and never raises on emit failure."""
        frame = _make_frame()
        mock_emit = MagicMock(side_effect=RuntimeError("daemon exploded"))

        with patch.dict(
            "sys.modules",
            {"emit_client_wrapper": MagicMock(emit_event=mock_emit)},
        ):
            import importlib

            import omniclaude.trace.frame_assembler as mod

            importlib.reload(mod)
            result = mod.emit_change_frame(frame, "session-456")

        assert result is False

    def test_emit_payload_includes_session_id(self) -> None:
        """Payload must include session_id for Kafka partitioning."""
        frame = _make_frame()
        captured_payload: dict[str, object] = {}

        def capture_emit(event_type: str, payload: dict[str, object]) -> bool:
            captured_payload.update(payload)
            return True

        mock_module = MagicMock(emit_event=capture_emit)
        with patch.dict("sys.modules", {"emit_client_wrapper": mock_module}):
            import importlib

            import omniclaude.trace.frame_assembler as mod

            importlib.reload(mod)
            mod.emit_change_frame(frame, "my-session")

        assert captured_payload["session_id"] == "my-session"
