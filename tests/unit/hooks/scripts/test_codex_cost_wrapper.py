# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

# Ensure the scripts directory is importable
_SCRIPTS_DIR = Path(__file__).parents[4] / "plugins" / "onex" / "hooks" / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from codex_cost_wrapper import emit_codex_invocation_cost  # type: ignore[import]


def test_emit_creates_event_file(tmp_path: Path) -> None:
    path = emit_codex_invocation_cost(
        correlation_id="test-corr-001",
        session_id="test-session-001",
        omni_home=str(tmp_path),
    )

    assert path is not None
    assert path.exists()
    assert path.name == "codex-test-corr-001.json"


def test_emit_event_schema(tmp_path: Path) -> None:
    path = emit_codex_invocation_cost(
        correlation_id="test-corr-002",
        session_id="test-session-002",
        omni_home=str(tmp_path),
    )

    assert path is not None
    event = json.loads(path.read_text(encoding="utf-8"))

    assert event["model_name"] == "codex"
    assert event["prompt_tokens"] == 0
    assert event["completion_tokens"] == 0
    assert event["total_tokens"] == 0
    assert event["estimated_cost_usd"] == 0.0
    assert event["session_id"] == "test-session-002"
    assert event["correlation_id"] == "test-corr-002"
    assert event["usage_source"] == "UNKNOWN"
    assert event["reporting_source"] == "codex"
    assert event["estimation_method"] == "codex_cli_no_usage_output"
    assert "emitted_at" in event


def test_emit_returns_none_without_omni_home(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("OMNI_HOME", raising=False)

    path = emit_codex_invocation_cost(
        correlation_id="test-corr-003",
        session_id="test-session-003",
        omni_home=None,
    )

    assert path is None
    captured = capsys.readouterr()
    assert "OMNI_HOME not set" in captured.err


def test_emit_generates_correlation_id_when_not_provided(tmp_path: Path) -> None:
    path = emit_codex_invocation_cost(
        session_id="test-session-004",
        omni_home=str(tmp_path),
    )

    assert path is not None
    event = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(event["correlation_id"], str)
    assert len(event["correlation_id"]) > 0


def test_emit_event_file_written_to_correct_dir(tmp_path: Path) -> None:
    emit_codex_invocation_cost(
        correlation_id="test-corr-005",
        omni_home=str(tmp_path),
    )

    expected_dir = tmp_path / ".onex_state" / "llm-cost-events"
    assert expected_dir.is_dir()
    files = list(expected_dir.glob("codex-*.json"))
    assert len(files) == 1
