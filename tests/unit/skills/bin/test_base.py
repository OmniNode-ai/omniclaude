# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for _bin/_lib/base.py -- SkillScriptResult model, stdout contract, atomic writes."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Add the _bin directory to sys.path so we can import _lib
_BIN_DIR = Path(__file__).resolve().parents[4] / "plugins" / "onex" / "skills" / "_bin"
sys.path.insert(0, str(_BIN_DIR))

from _lib.base import (  # noqa: E402
    ScriptMeta,
    ScriptStatus,
    SkillScriptResult,
    atomic_write_json,
    default_run_id,
    emit_result,
    make_meta,
    stdout_line,
)


@pytest.mark.unit
class TestScriptStatus:
    """Tests for ScriptStatus enum."""

    def test_values(self) -> None:
        assert ScriptStatus.OK == "OK"
        assert ScriptStatus.WARN == "WARN"
        assert ScriptStatus.FAIL == "FAIL"


@pytest.mark.unit
class TestStdoutLine:
    """Tests for stdout_line() contract format."""

    def test_ok_format(self) -> None:
        line = stdout_line(ScriptStatus.OK, "/tmp/test.json", "All clear")
        assert line == 'STATUS=OK LOG=/tmp/test.json MSG="All clear"'

    def test_warn_format(self) -> None:
        line = stdout_line(ScriptStatus.WARN, "/tmp/w.json", "Some issues")
        assert line == 'STATUS=WARN LOG=/tmp/w.json MSG="Some issues"'

    def test_fail_format(self) -> None:
        line = stdout_line(ScriptStatus.FAIL, "", "Error occurred")
        assert line == 'STATUS=FAIL LOG= MSG="Error occurred"'


@pytest.mark.unit
class TestSkillScriptResult:
    """Tests for SkillScriptResult model."""

    def test_basic_construction(self) -> None:
        meta = ScriptMeta(
            script="test_script",
            run_id="run-123",
            ts="2026-01-01T00:00:00Z",
            repo="OmniNode-ai/omniclaude",
        )
        result = SkillScriptResult(
            meta=meta,
            inputs={"repo": "test"},
            parsed={"data": [1, 2, 3]},
            summary={"count": 3},
        )
        assert result.meta.script == "test_script"
        assert result.inputs == {"repo": "test"}
        assert result.parsed == {"data": [1, 2, 3]}
        assert result.summary == {"count": 3}

    def test_json_schema_keys(self) -> None:
        """Verify JSON output has required top-level keys."""
        meta = ScriptMeta(
            script="test",
            run_id="r1",
            ts="2026-01-01T00:00:00Z",
            repo="OmniNode-ai/test",
        )
        result = SkillScriptResult(meta=meta)
        data = result.model_dump()
        assert "meta" in data
        assert "inputs" in data
        assert "parsed" in data
        assert "summary" in data

    def test_meta_required_fields(self) -> None:
        """Verify meta block has required fields."""
        meta = make_meta("test_script", "run-456", "OmniNode-ai/omniclaude")
        assert meta.script == "test_script"
        assert meta.run_id == "run-456"
        assert meta.repo == "OmniNode-ai/omniclaude"
        assert meta.ts  # non-empty ISO timestamp
        assert meta.version == "1.0.0"

    def test_extra_fields_forbidden(self) -> None:
        """SkillScriptResult should reject extra fields."""
        meta = ScriptMeta(
            script="t",
            run_id="r",
            ts="2026-01-01T00:00:00Z",
            repo="x/y",
        )
        with pytest.raises(Exception):
            SkillScriptResult(meta=meta, unexpected_field="bad")  # type: ignore[call-arg]


@pytest.mark.unit
class TestAtomicWriteJson:
    """Tests for atomic_write_json()."""

    def test_creates_file(self, tmp_path: Path) -> None:
        target = tmp_path / "test.json"
        data = {"key": "value", "nested": {"a": 1}}
        atomic_write_json(target, data)

        assert target.exists()
        loaded = json.loads(target.read_text())
        assert loaded == data

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        target = tmp_path / "deep" / "nested" / "test.json"
        atomic_write_json(target, {"ok": True})
        assert target.exists()

    def test_overwrites_existing(self, tmp_path: Path) -> None:
        target = tmp_path / "test.json"
        atomic_write_json(target, {"version": 1})
        atomic_write_json(target, {"version": 2})
        loaded = json.loads(target.read_text())
        assert loaded == {"version": 2}

    def test_no_partial_on_error(self, tmp_path: Path) -> None:
        """If serialization fails, no file should be left behind."""
        target = tmp_path / "fail.json"

        class BadObj:
            def __repr__(self) -> str:
                raise RuntimeError("boom")

        # json.dump with default=str won't fail for most objects,
        # so we patch to force failure
        with patch("json.dump", side_effect=RuntimeError("forced")):
            with pytest.raises(RuntimeError):
                atomic_write_json(target, {"bad": "data"})
        assert not target.exists()


@pytest.mark.unit
class TestDefaultRunId:
    """Tests for default_run_id()."""

    def test_format(self) -> None:
        run_id = default_run_id()
        assert run_id.startswith("run-")
        # The numeric part should be a valid integer
        int(run_id.split("-")[1])


@pytest.mark.unit
class TestEmitResult:
    """Tests for emit_result()."""

    def test_summary_format(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        meta = make_meta("test", "r1", "x/y")
        result = SkillScriptResult(
            meta=meta,
            summary={"ok": True},
        )
        log_path = tmp_path / "test.json"
        emit_result(
            status=ScriptStatus.OK,
            result=result,
            log_path=log_path,
            msg="All good",
            output_format="summary",
        )
        captured = capsys.readouterr()
        assert "STATUS=OK" in captured.out
        assert "All good" in captured.out
        assert log_path.exists()

    def test_json_format(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        meta = make_meta("test", "r1", "x/y")
        result = SkillScriptResult(
            meta=meta,
            summary={"ok": True},
        )
        log_path = tmp_path / "test.json"
        emit_result(
            status=ScriptStatus.OK,
            result=result,
            log_path=log_path,
            msg="All good",
            output_format="json",
        )
        captured = capsys.readouterr()
        # JSON format outputs the full JSON
        output = json.loads(captured.out)
        assert "meta" in output
        assert "summary" in output
