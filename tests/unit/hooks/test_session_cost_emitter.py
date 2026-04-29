# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
from pathlib import Path

from omniclaude.hooks.session_cost_emitter import (
    extract_session_tokens,
    find_accumulator_path,
    normalize_session_cost_payload,
)

FIXTURE_DIR = Path(__file__).parents[2] / "fixtures" / "session_cost"


def _fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_extract_session_tokens_from_context_window() -> None:
    payload = _fixture("session_end_context_window.json")

    assert extract_session_tokens(payload) == (1200, 345)


def test_normalize_uses_session_end_tokens_before_accumulator(tmp_path: Path) -> None:
    accumulator = tmp_path / "omniclaude-session-session-context-001.json"
    accumulator.write_text(
        json.dumps({"total_input_tokens": 9999, "total_output_tokens": 9999}),
        encoding="utf-8",
    )

    payload = normalize_session_cost_payload(
        session_end_payload=_fixture("session_end_context_window.json"),
        env={
            "OMNI_HOME": "/workspace/omni_home",
            "CLAUDE_PROJECT_DIR": "/workspace/omni_home/omniclaude",
            "ONEX_MACHINE_ID": "devbox-1",
        },
        correlation_id="corr-123",
        accumulator_dir=tmp_path,
    )

    assert payload is not None
    assert payload["prompt_tokens"] == 1200
    assert payload["completion_tokens"] == 345
    assert payload["total_tokens"] == 1545
    assert payload["repo_name"] == "omniclaude"
    assert payload["machine_id"] == "devbox-1"
    assert payload["correlation_id"] == "corr-123"
    assert payload["cost_usd"] > 0


def test_normalize_falls_back_to_accumulator(tmp_path: Path) -> None:
    accumulator = tmp_path / "omniclaude-session-session-accum-001.json"
    accumulator.write_text(
        (FIXTURE_DIR / "omniclaude-session-session-accum-001.json").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )

    payload = normalize_session_cost_payload(
        session_end_payload=_fixture("session_end_accumulator.json"),
        env={
            "OMNI_HOME": "/workspace/omni_home",
            "CLAUDE_PROJECT_DIR": (
                "/workspace/omni_home/omni_worktrees/OMN-10335/omniclaude"
            ),
        },
        accumulator_dir=tmp_path,
    )

    assert payload is not None
    assert payload["session_id"] == "session-accum-001"
    assert payload["prompt_tokens"] == 2400
    assert payload["completion_tokens"] == 610
    assert payload["repo_name"] == "omniclaude"
    assert payload["machine_id"] is None


def test_find_accumulator_path_requires_exact_session_id(tmp_path: Path) -> None:
    foreign = tmp_path / "omniclaude-session-other-session.json"
    foreign.write_text(
        json.dumps({"total_input_tokens": 9999, "total_output_tokens": 9999}),
        encoding="utf-8",
    )

    assert find_accumulator_path(None, tmp_path) is None
    assert find_accumulator_path("", tmp_path) is None
    assert find_accumulator_path("missing-session", tmp_path) is None


def test_normalize_does_not_adopt_foreign_accumulator(tmp_path: Path) -> None:
    foreign = tmp_path / "omniclaude-session-other-session.json"
    foreign.write_text(
        json.dumps({"total_input_tokens": 9999, "total_output_tokens": 9999}),
        encoding="utf-8",
    )

    payload = normalize_session_cost_payload(
        session_end_payload={
            "sessionId": "current-session",
            "timestamp": "2026-04-29T00:00:00Z",
        },
        env={},
        accumulator_dir=tmp_path,
    )

    assert payload is None


def test_normalize_returns_none_without_token_data(tmp_path: Path) -> None:
    payload = normalize_session_cost_payload(
        session_end_payload={"sessionId": "empty", "timestamp": "2026-04-29T00:00:00Z"},
        env={},
        accumulator_dir=tmp_path,
    )

    assert payload is None
