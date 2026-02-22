"""Unit tests for commit_intent_binder module (OMN-2492).

Covers:
- detect_commit_sha: Bash tool output parsing for git commit SHAs
- read_intent_from_state: correlation state file reading
- process_tool_use: high-level orchestration (emit path mocked)
- CLI: always exits 0, even on malformed input or emit failure
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------

sys.path.insert(
    0,
    str(
        Path(__file__).parent.parent.parent.parent.parent
        / "plugins"
        / "onex"
        / "hooks"
        / "lib"
    ),
)

from commit_intent_binder import (
    IntentCommitBinding,
    detect_commit_sha,
    process_tool_use,
    read_intent_from_state,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SHORT_SHA = "abc1234"
_LONG_SHA = "abc1234def5678901234567890abcdef12345678"


# ---------------------------------------------------------------------------
# TestDetectCommitSha
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDetectCommitSha:
    """Test git commit SHA detection from Bash tool output."""

    def test_detects_short_sha_from_standard_git_output(self) -> None:
        output = f"[main {_SHORT_SHA}] feat(x): add something\n 1 file changed"
        sha = detect_commit_sha("Bash", {"output": output})
        assert sha == _SHORT_SHA

    def test_detects_long_sha_from_git_output(self) -> None:
        output = f"[feature/branch {_LONG_SHA}] fix(y): resolve bug\n 2 files"
        sha = detect_commit_sha("Bash", {"output": output})
        assert sha == _LONG_SHA

    def test_returns_none_for_non_bash_tool(self) -> None:
        output = f"[main {_SHORT_SHA}] some commit"
        sha = detect_commit_sha("Read", {"output": output})
        assert sha is None

    def test_returns_none_for_write_tool(self) -> None:
        output = f"[main {_SHORT_SHA}] some commit"
        sha = detect_commit_sha("Write", output)
        assert sha is None

    def test_returns_none_when_no_commit_in_output(self) -> None:
        output = "no git output here"
        sha = detect_commit_sha("Bash", {"output": output})
        assert sha is None

    def test_returns_none_for_empty_output(self) -> None:
        sha = detect_commit_sha("Bash", {"output": ""})
        assert sha is None

    def test_handles_string_tool_response(self) -> None:
        output = f"[main {_SHORT_SHA}] commit message"
        sha = detect_commit_sha("Bash", output)
        assert sha == _SHORT_SHA

    def test_returns_none_for_none_tool_response(self) -> None:
        sha = detect_commit_sha("Bash", None)
        assert sha is None

    def test_handles_stdout_key_in_response(self) -> None:
        output = f"[develop {_SHORT_SHA}] chore: update deps"
        sha = detect_commit_sha("Bash", {"stdout": output})
        assert sha == _SHORT_SHA

    def test_handles_content_key_in_response(self) -> None:
        output = f"[main {_SHORT_SHA}] docs: update readme"
        sha = detect_commit_sha("Bash", {"content": output})
        assert sha == _SHORT_SHA

    def test_returns_none_for_empty_response_dict(self) -> None:
        sha = detect_commit_sha("Bash", {})
        assert sha is None

    def test_git_output_with_multiline_response(self) -> None:
        output = (
            "Compiling...\n"
            f"[main {_SHORT_SHA}] refactor(core): simplify logic\n"
            " 5 files changed, 20 insertions(+), 8 deletions(-)\n"
        )
        sha = detect_commit_sha("Bash", {"output": output})
        assert sha == _SHORT_SHA


# ---------------------------------------------------------------------------
# TestReadIntentFromState
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestReadIntentFromState:
    """Test reading intent state from correlation file."""

    def test_returns_empty_when_no_state_file(self, tmp_path: Path) -> None:
        result = read_intent_from_state(state_dir=tmp_path)
        assert result["intent_id"] == ""
        assert result["intent_class"] == ""
        assert result["correlation_id"] == ""

    def test_reads_intent_id_from_state(self, tmp_path: Path) -> None:
        state = {
            "intent_id": "intent-abc-123",
            "intent_class": "CODE",
            "correlation_id": "corr-xyz-789",
        }
        (tmp_path / "correlation_id.json").write_text(json.dumps(state))
        result = read_intent_from_state(state_dir=tmp_path)
        assert result["intent_id"] == "intent-abc-123"
        assert result["intent_class"] == "CODE"
        assert result["correlation_id"] == "corr-xyz-789"

    def test_handles_missing_fields_gracefully(self, tmp_path: Path) -> None:
        state = {"correlation_id": "corr-001"}
        (tmp_path / "correlation_id.json").write_text(json.dumps(state))
        result = read_intent_from_state(state_dir=tmp_path)
        assert result["intent_id"] == ""
        assert result["correlation_id"] == "corr-001"

    def test_handles_corrupt_state_file(self, tmp_path: Path) -> None:
        (tmp_path / "correlation_id.json").write_text("not-valid-json{{")
        result = read_intent_from_state(state_dir=tmp_path)
        assert result["intent_id"] == ""

    def test_handles_null_intent_id_in_state(self, tmp_path: Path) -> None:
        state = {"intent_id": None, "correlation_id": "corr-002"}
        (tmp_path / "correlation_id.json").write_text(json.dumps(state))
        result = read_intent_from_state(state_dir=tmp_path)
        assert result["intent_id"] == ""


# ---------------------------------------------------------------------------
# TestProcessToolUse
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProcessToolUse:
    """Test the high-level process_tool_use orchestration."""

    def _make_tool_info(self, output: str) -> dict:
        return {
            "tool_name": "Bash",
            "sessionId": "sess-001",
            "tool_response": {"output": output},
        }

    def test_returns_none_for_non_bash_tool(self, tmp_path: Path) -> None:
        tool_info = {
            "tool_name": "Read",
            "sessionId": "sess-001",
            "tool_response": {"output": f"[main {_SHORT_SHA}] commit"},
        }
        result = process_tool_use(tool_info, state_dir=tmp_path)
        assert result is None

    def test_returns_none_when_no_commit_in_output(self, tmp_path: Path) -> None:
        tool_info = self._make_tool_info("no commit here")
        result = process_tool_use(tool_info, state_dir=tmp_path)
        assert result is None

    def test_returns_binding_when_commit_detected(self, tmp_path: Path) -> None:
        state = {"intent_id": "intent-001", "correlation_id": "corr-001"}
        (tmp_path / "correlation_id.json").write_text(json.dumps(state))

        output = f"[main {_SHORT_SHA}] feat: add feature"
        tool_info = self._make_tool_info(output)

        with patch("commit_intent_binder.emit_binding", return_value=True):
            result = process_tool_use(
                tool_info,
                session_id="sess-001",
                state_dir=tmp_path,
                now_iso="2026-02-21T12:00:00+00:00",
            )

        assert result is not None
        assert isinstance(result, IntentCommitBinding)
        assert result.commit_sha == _SHORT_SHA
        assert result.intent_id == "intent-001"
        assert result.session_id == "sess-001"
        assert result.correlation_id == "corr-001"
        assert result.bound_at == "2026-02-21T12:00:00+00:00"

    def test_binding_created_with_empty_intent_when_no_state(
        self, tmp_path: Path
    ) -> None:
        output = f"[main {_SHORT_SHA}] chore: cleanup"
        tool_info = self._make_tool_info(output)

        with patch("commit_intent_binder.emit_binding", return_value=False):
            result = process_tool_use(tool_info, state_dir=tmp_path)

        assert result is not None
        assert result.intent_id == ""
        assert result.commit_sha == _SHORT_SHA

    def test_emit_failure_does_not_prevent_binding_return(self, tmp_path: Path) -> None:
        output = f"[main {_SHORT_SHA}] fix: bug"
        tool_info = self._make_tool_info(output)

        with patch("commit_intent_binder.emit_binding", return_value=False):
            result = process_tool_use(tool_info, state_dir=tmp_path)

        assert result is not None
        assert result.commit_sha == _SHORT_SHA

    def test_session_id_falls_back_to_tool_info(self, tmp_path: Path) -> None:
        output = f"[main {_SHORT_SHA}] refactor: cleanup"
        tool_info = {
            "tool_name": "Bash",
            "sessionId": "fallback-session",
            "tool_response": {"output": output},
        }

        with patch("commit_intent_binder.emit_binding", return_value=True):
            result = process_tool_use(tool_info, state_dir=tmp_path)

        assert result is not None
        assert result.session_id == "fallback-session"

    def test_emit_exception_does_not_propagate(self, tmp_path: Path) -> None:
        output = f"[main {_SHORT_SHA}] docs: update"
        tool_info = self._make_tool_info(output)

        with patch(
            "commit_intent_binder.emit_binding",
            side_effect=RuntimeError("daemon exploded"),
        ):
            # Should not raise
            result = process_tool_use(tool_info, state_dir=tmp_path)

        assert result is not None

    def test_empty_tool_info_returns_none(self, tmp_path: Path) -> None:
        # An empty dict has no tool_name, so no commit is detected
        result = process_tool_use({}, state_dir=tmp_path)
        assert result is None


# ---------------------------------------------------------------------------
# TestIntentCommitBindingFrozen
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIntentCommitBindingFrozen:
    """IntentCommitBinding must be immutable (frozen dataclass)."""

    def test_binding_is_immutable(self) -> None:
        binding = IntentCommitBinding(
            intent_id="x",
            commit_sha="abc1234",
            session_id="s",
            correlation_id="c",
            bound_at="2026-01-01T00:00:00+00:00",
        )
        with pytest.raises((AttributeError, TypeError)):
            binding.commit_sha = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# TestCLIExitBehavior
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCLIExitBehavior:
    """CLI must always exit 0, even when things go wrong."""

    def _run_cli(self, stdin: str, extra_args: list[str] | None = None) -> int:
        lib_path = str(
            Path(__file__).parent.parent.parent.parent.parent
            / "plugins"
            / "onex"
            / "hooks"
            / "lib"
        )
        cmd = [
            sys.executable,
            str(Path(lib_path) / "commit_intent_binder.py"),
        ] + (extra_args or [])
        result = subprocess.run(
            cmd,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return result.returncode

    def test_exits_0_with_empty_stdin(self) -> None:
        assert self._run_cli("") == 0

    def test_exits_0_with_malformed_json(self) -> None:
        assert self._run_cli("not json at all {{{{") == 0

    def test_exits_0_with_valid_non_commit_bash_output(self) -> None:
        tool_info = json.dumps(
            {
                "tool_name": "Bash",
                "sessionId": "s",
                "tool_response": {"output": "ls -la"},
            }
        )
        assert self._run_cli(tool_info) == 0

    def test_exits_0_even_when_emit_daemon_unreachable(self) -> None:
        # Point at a non-existent socket so emit will fail
        import os

        tool_info = json.dumps(
            {
                "tool_name": "Bash",
                "sessionId": "s",
                "tool_response": {"output": f"[main {_SHORT_SHA}] feat: test"},
            }
        )
        env = {
            **os.environ,
            "OMNICLAUDE_EMIT_SOCKET": "/tmp/nonexistent-sock-omn2492.sock",
        }
        lib_path = str(
            Path(__file__).parent.parent.parent.parent.parent
            / "plugins"
            / "onex"
            / "hooks"
            / "lib"
        )
        result = subprocess.run(
            [sys.executable, str(Path(lib_path) / "commit_intent_binder.py")],
            input=tool_info,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            env=env,
        )
        assert result.returncode == 0
