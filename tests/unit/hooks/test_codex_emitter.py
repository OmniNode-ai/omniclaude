# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

from omniclaude.hooks.codex_emitter import (
    NO_LOG_MESSAGE,
    emit_codex_session_costs,
    normalize_codex_session_log,
)

FIXTURE_DIR = Path(__file__).parents[2] / "fixtures" / "session_cost"


def test_normalize_codex_session_log_with_api_token_count() -> None:
    payload = normalize_codex_session_log(
        FIXTURE_DIR / "codex_session_with_tokens.jsonl",
        env={
            "OMNI_HOME": "/workspace/omni_home",
            "ONEX_MACHINE_ID": "machine-1",
        },
    )

    assert payload is not None
    assert payload["session_id"] == "019ddac6-c89a-7882-b97e-570c88cbd584"
    assert payload["tool_source"] == "codex"
    assert payload["usage_source"] == "API"
    assert payload["prompt_tokens"] == 131494
    assert payload["completion_tokens"] == 1961
    assert payload["total_tokens"] == 133455
    assert payload["repo_name"] == "omniclaude"
    assert payload["machine_id"] == "machine-1"
    assert payload["model_id"] == "codex-openai"
    assert re.fullmatch(r"sha256-[0-9a-f]{64}", str(payload["idempotency_key"]))


def test_normalize_codex_session_log_without_tokens_marks_missing() -> None:
    payload = normalize_codex_session_log(
        FIXTURE_DIR / "codex_session_without_tokens.jsonl",
        env={"OMNI_HOME": "/workspace/omni_home"},
    )

    assert payload is not None
    assert payload["usage_source"] == "MISSING"
    assert payload["prompt_tokens"] == 0
    assert payload["completion_tokens"] == 0
    assert payload["repo_name"] == "omniclaude"
    assert payload["machine_id"] is None


def test_emit_codex_session_costs_is_idempotent_on_rerun(tmp_path: Path) -> None:
    sessions_dir = tmp_path / "sessions" / "2026" / "04" / "29"
    sessions_dir.mkdir(parents=True)
    log_path = sessions_dir / "rollout-test.jsonl"
    log_path.write_text(
        (FIXTURE_DIR / "codex_session_with_tokens.jsonl").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    state_file = tmp_path / "state.json"
    emitted: list[dict[str, object]] = []

    def emit_func(event_type: str, payload: dict[str, object]) -> bool:
        emitted.append({"event_type": event_type, "payload": payload})
        return True

    first = emit_codex_session_costs(
        sessions_dir=tmp_path / "sessions",
        state_file=state_file,
        env={
            "OMNI_HOME": "/workspace/omni_home",
            "ONEX_MACHINE_ID": "machine-1",
        },
        emit_func=emit_func,
    )
    second = emit_codex_session_costs(
        sessions_dir=tmp_path / "sessions",
        state_file=state_file,
        env={
            "OMNI_HOME": "/workspace/omni_home",
            "ONEX_MACHINE_ID": "machine-1",
        },
        emit_func=emit_func,
    )

    assert first == (1, 0)
    assert second == (0, 1)
    assert len(emitted) == 1
    assert emitted[0]["event_type"] == "llm.cost.completed"


def test_emit_codex_session_costs_no_logs_exits_zero_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    emitted_count, skipped_count = emit_codex_session_costs(
        sessions_dir=tmp_path / "missing",
        state_file=tmp_path / "state.json",
        env={},
        emit_func=lambda _event_type, _payload: True,
    )

    captured = capsys.readouterr()
    assert emitted_count == 0
    assert skipped_count == 0
    assert NO_LOG_MESSAGE in captured.err
