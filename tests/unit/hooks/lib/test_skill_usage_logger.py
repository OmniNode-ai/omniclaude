# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for skill_usage_logger (OMN-3454).

All tests run without Kafka or PostgreSQL (fully mocked / tmp file).
"""

from __future__ import annotations

import json
import os
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from omniclaude.hooks.lib.skill_usage_logger import (
    DEFAULT_USAGE_LOG,
    _build_entry,
    _write_to_file,
    append_skill_usage,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_log_lines(log_path: Path) -> list[dict]:
    """Parse a JSONL log file into a list of dicts."""
    lines = log_path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


# ---------------------------------------------------------------------------
# _build_entry
# ---------------------------------------------------------------------------


class TestBuildEntry:
    @pytest.mark.unit
    def test_contains_required_fields(self) -> None:
        entry = _build_entry(skill_name="onex:ticket-pipeline", session_id="sess-abc")
        assert set(entry.keys()) == {"skill_name", "timestamp", "session_id"}

    @pytest.mark.unit
    def test_skill_name_preserved(self) -> None:
        entry = _build_entry(skill_name="onex:pr-review", session_id="sess-xyz")
        assert entry["skill_name"] == "onex:pr-review"

    @pytest.mark.unit
    def test_session_id_preserved(self) -> None:
        entry = _build_entry(skill_name="any", session_id="my-session-123")
        assert entry["session_id"] == "my-session-123"

    @pytest.mark.unit
    def test_timestamp_is_iso_format(self) -> None:
        from datetime import datetime

        entry = _build_entry(skill_name="any", session_id="s")
        # Should be parseable as ISO datetime
        dt = datetime.fromisoformat(entry["timestamp"])
        assert dt is not None

    @pytest.mark.unit
    def test_no_extra_fields(self) -> None:
        """Log must not contain prompt content, file paths, or code."""
        entry = _build_entry(skill_name="onex:ticket-work", session_id="s")
        for forbidden in ("prompt", "code", "file_path", "content", "args"):
            assert forbidden not in entry, f"Unexpected field {forbidden!r} in entry"


# ---------------------------------------------------------------------------
# _write_to_file
# ---------------------------------------------------------------------------


class TestWriteToFile:
    @pytest.mark.unit
    def test_creates_file_if_not_exists(self, tmp_path: Path) -> None:
        log = tmp_path / "skill-usage.log"
        entry = {
            "skill_name": "onex:ticket-pipeline",
            "timestamp": "t",
            "session_id": "s",
        }
        ok = _write_to_file(entry=entry, log_path=log)
        assert ok is True
        assert log.exists()

    @pytest.mark.unit
    def test_appends_valid_json_line(self, tmp_path: Path) -> None:
        log = tmp_path / "skill-usage.log"
        entry = {
            "skill_name": "onex:ticket-pipeline",
            "timestamp": "t",
            "session_id": "s",
        }
        _write_to_file(entry=entry, log_path=log)
        lines = _read_log_lines(log)
        assert len(lines) == 1
        assert lines[0]["skill_name"] == "onex:ticket-pipeline"

    @pytest.mark.unit
    def test_appends_multiple_lines(self, tmp_path: Path) -> None:
        log = tmp_path / "skill-usage.log"
        for skill in ("onex:ticket-pipeline", "onex:pr-review", "onex:local-review"):
            entry = {"skill_name": skill, "timestamp": "t", "session_id": "s"}
            _write_to_file(entry=entry, log_path=log)
        lines = _read_log_lines(log)
        assert len(lines) == 3
        assert lines[0]["skill_name"] == "onex:ticket-pipeline"
        assert lines[2]["skill_name"] == "onex:local-review"

    @pytest.mark.unit
    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        log = tmp_path / "deep" / "nested" / "dir" / "usage.log"
        entry = {"skill_name": "any", "timestamp": "t", "session_id": "s"}
        ok = _write_to_file(entry=entry, log_path=log)
        assert ok is True
        assert log.exists()

    @pytest.mark.unit
    def test_returns_false_on_write_failure(self, tmp_path: Path) -> None:
        log = tmp_path / "usage.log"
        # Path.open() is used internally; patch mkdir to trigger failure instead
        with patch(
            "omniclaude.hooks.lib.skill_usage_logger.Path.mkdir",
            side_effect=OSError("permission denied"),
        ):
            ok = _write_to_file(entry={"k": "v"}, log_path=log)
        assert ok is False

    @pytest.mark.unit
    def test_line_is_compact_json(self, tmp_path: Path) -> None:
        """Each line must be valid JSON without leading/trailing whitespace."""
        log = tmp_path / "usage.log"
        entry = {
            "skill_name": "onex:ticket-pipeline",
            "timestamp": "t",
            "session_id": "s",
        }
        _write_to_file(entry=entry, log_path=log)
        raw_line = log.read_text(encoding="utf-8").strip()
        parsed = json.loads(raw_line)
        assert isinstance(parsed, dict)


# ---------------------------------------------------------------------------
# append_skill_usage
# ---------------------------------------------------------------------------


class TestAppendSkillUsage:
    @pytest.mark.unit
    def test_empty_skill_name_returns_false(self, tmp_path: Path) -> None:
        log = tmp_path / "usage.log"
        ok = append_skill_usage("", "sess-abc", log_path=log, db_enabled=False)
        assert ok is False

    @pytest.mark.unit
    def test_writes_log_entry(self, tmp_path: Path) -> None:
        log = tmp_path / "usage.log"
        ok = append_skill_usage(
            "onex:ticket-pipeline", "sess-abc", log_path=log, db_enabled=False
        )
        assert ok is True
        lines = _read_log_lines(log)
        assert len(lines) == 1
        assert lines[0]["skill_name"] == "onex:ticket-pipeline"
        assert lines[0]["session_id"] == "sess-abc"

    @pytest.mark.unit
    def test_no_prompt_content_in_log(self, tmp_path: Path) -> None:
        log = tmp_path / "usage.log"
        append_skill_usage(
            "onex:ticket-pipeline", "sess-abc", log_path=log, db_enabled=False
        )
        raw = log.read_text(encoding="utf-8")
        for forbidden in ("prompt", "code", "file_path", "content", "args"):
            assert forbidden not in raw

    @pytest.mark.unit
    def test_db_skipped_when_disabled(self, tmp_path: Path) -> None:
        log = tmp_path / "usage.log"
        with patch("omniclaude.hooks.lib.skill_usage_logger._write_to_db") as mock_db:
            append_skill_usage("onex:any", "s", log_path=log, db_enabled=False)
        mock_db.assert_not_called()

    @pytest.mark.unit
    def test_db_attempted_when_enabled(self, tmp_path: Path) -> None:
        log = tmp_path / "usage.log"
        with patch("omniclaude.hooks.lib.skill_usage_logger._write_to_db") as mock_db:
            append_skill_usage("onex:any", "s", log_path=log, db_enabled=True)
        mock_db.assert_called_once()

    @pytest.mark.unit
    def test_db_failure_does_not_affect_return_value(self, tmp_path: Path) -> None:
        log = tmp_path / "usage.log"
        with patch(
            "omniclaude.hooks.lib.skill_usage_logger._write_to_db",
            side_effect=RuntimeError("DB down"),
        ):
            ok = append_skill_usage("onex:any", "s", log_path=log, db_enabled=True)
        # File write succeeded; return must be True
        assert ok is True

    @pytest.mark.unit
    def test_reads_enable_postgres_from_env(self, tmp_path: Path) -> None:
        log = tmp_path / "usage.log"
        with (
            patch.dict(os.environ, {"ENABLE_POSTGRES": "true"}),
            patch("omniclaude.hooks.lib.skill_usage_logger._write_to_db") as mock_db,
        ):
            append_skill_usage("onex:any", "s", log_path=log)
        mock_db.assert_called_once()

    @pytest.mark.unit
    def test_default_log_path_constant(self) -> None:
        expected = Path.home() / ".claude" / "onex-skill-usage.log"
        assert expected == DEFAULT_USAGE_LOG

    @pytest.mark.unit
    def test_multiple_invocations_append_sequentially(self, tmp_path: Path) -> None:
        log = tmp_path / "usage.log"
        skills = ["onex:ticket-pipeline", "onex:local-review", "onex:pr-review"]
        for skill in skills:
            append_skill_usage(skill, "sess-1", log_path=log, db_enabled=False)
        lines = _read_log_lines(log)
        assert [line["skill_name"] for line in lines] == skills


# ---------------------------------------------------------------------------
# CLI entry-point (_main via stdin)
# ---------------------------------------------------------------------------


class TestMainEntryPoint:
    """Tests for the __main__ CLI path invoked from the bash hook."""

    def _run_main(self, stdin_data: str, tmp_log: Path) -> None:
        """Invoke _main() with patched stdin and log path."""
        from omniclaude.hooks.lib import skill_usage_logger

        with (
            patch("sys.stdin", StringIO(stdin_data)),
            patch.object(skill_usage_logger, "DEFAULT_USAGE_LOG", tmp_log),
            patch("omniclaude.hooks.lib.skill_usage_logger._maybe_write_to_db"),
        ):
            try:
                skill_usage_logger._main()
            except SystemExit:
                pass

    @pytest.mark.unit
    def test_skill_tool_writes_log(self, tmp_path: Path) -> None:
        log = tmp_path / "usage.log"
        hook_json = json.dumps(
            {
                "tool_name": "Skill",
                "tool_input": {"skill": "onex:ticket-pipeline"},
                "sessionId": "sess-cli-test",
            }
        )
        self._run_main(hook_json, log)
        lines = _read_log_lines(log)
        assert len(lines) == 1
        assert lines[0]["skill_name"] == "onex:ticket-pipeline"
        assert lines[0]["session_id"] == "sess-cli-test"

    @pytest.mark.unit
    def test_non_skill_tool_does_not_write(self, tmp_path: Path) -> None:
        log = tmp_path / "usage.log"
        hook_json = json.dumps(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "ls"},
                "sessionId": "sess-1",
            }
        )
        self._run_main(hook_json, log)
        assert not log.exists()

    @pytest.mark.unit
    def test_empty_stdin_does_not_crash(self, tmp_path: Path) -> None:
        log = tmp_path / "usage.log"
        self._run_main("", log)
        assert not log.exists()

    @pytest.mark.unit
    def test_malformed_json_does_not_crash(self, tmp_path: Path) -> None:
        log = tmp_path / "usage.log"
        self._run_main("{not valid json", log)
        assert not log.exists()

    @pytest.mark.unit
    def test_skill_name_from_name_field(self, tmp_path: Path) -> None:
        """Falls back to tool_input.name when tool_input.skill is absent."""
        log = tmp_path / "usage.log"
        hook_json = json.dumps(
            {
                "tool_name": "Skill",
                "tool_input": {"name": "onex:local-review"},
                "session_id": "sess-fallback",
            }
        )
        self._run_main(hook_json, log)
        lines = _read_log_lines(log)
        assert lines[0]["skill_name"] == "onex:local-review"
