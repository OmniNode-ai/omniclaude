# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for handler_session_cost_emitter (OMN-8020).

Tests cover:
- emit_session_cost returns False when no token data is available
- emit_session_cost normalizes payload and calls emit_event with correct event type
- emit_session_cost degrades gracefully when daemon is unavailable
- Accumulator fallback path delegates to normalize_session_cost_payload
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from omniclaude.hooks.handler_session_cost_emitter import (
    _EVENT_TYPE,
    emit_session_cost,
)

pytestmark = pytest.mark.unit

FIXTURE_DIR = Path(__file__).parents[2] / "fixtures" / "session_cost"


def _fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


class TestEmitSessionCostSkipsWhenNoTokens:
    def test_returns_false_on_empty_payload(self) -> None:
        result = emit_session_cost(session_end_payload={})
        assert result is False

    def test_returns_false_when_tokens_are_zero(self) -> None:
        payload: dict[str, object] = {
            "context_window": {"current_usage": {"input_tokens": 0, "output_tokens": 0}}
        }
        result = emit_session_cost(session_end_payload=payload)
        assert result is False

    def test_returns_false_when_no_accumulator_and_no_tokens(
        self, tmp_path: Path
    ) -> None:
        result = emit_session_cost(
            session_end_payload={},
            accumulator_dir=tmp_path,
        )
        assert result is False


class TestEmitSessionCostDaemonPath:
    def test_calls_emit_event_with_llm_cost_completed_type(
        self, tmp_path: Path
    ) -> None:
        captured: list[tuple[str, dict]] = []

        def fake_emit(event_type: str, payload: dict, timeout_ms: int = 3000) -> bool:
            captured.append((event_type, payload))
            return True

        payload = _fixture("session_end_context_window.json")
        env = {
            "OMNI_HOME": "/workspace/omni_home",
            "CLAUDE_PROJECT_DIR": "/workspace/omni_home/omniclaude",
            "ONEX_MACHINE_ID": "devbox-1",
        }

        mock_module = MagicMock()
        mock_module.emit_event = fake_emit

        with patch.dict("sys.modules", {"emit_client_wrapper": mock_module}):
            result = emit_session_cost(
                session_end_payload=payload,
                env=env,
                session_id="test-session-001",
                correlation_id="corr-abc",
                accumulator_dir=tmp_path,
            )

        assert result is True
        assert len(captured) == 1
        event_type, emitted_payload = captured[0]
        assert event_type == _EVENT_TYPE
        assert event_type == "llm.cost.completed"
        assert emitted_payload["session_id"] == "test-session-001"
        assert emitted_payload["total_tokens"] > 0

    def test_propagates_correlation_id(self, tmp_path: Path) -> None:
        captured: list[dict] = []

        mock_module = MagicMock()
        mock_module.emit_event = lambda _et, p, **_kw: captured.append(p) or True

        payload = _fixture("session_end_context_window.json")
        env = {"OMNI_HOME": "/workspace/omni_home"}

        with patch.dict("sys.modules", {"emit_client_wrapper": mock_module}):
            emit_session_cost(
                session_end_payload=payload,
                env=env,
                correlation_id="corr-xyz-999",
                accumulator_dir=tmp_path,
            )

        assert len(captured) == 1
        assert captured[0]["correlation_id"] == "corr-xyz-999"

    def test_returns_false_when_daemon_rejects(self, tmp_path: Path) -> None:
        mock_module = MagicMock()
        mock_module.emit_event = MagicMock(return_value=False)

        payload = _fixture("session_end_context_window.json")
        env = {"OMNI_HOME": "/workspace/omni_home"}

        with patch.dict("sys.modules", {"emit_client_wrapper": mock_module}):
            result = emit_session_cost(
                session_end_payload=payload,
                env=env,
                accumulator_dir=tmp_path,
            )

        assert result is False

    def test_degrades_gracefully_on_import_error(self, tmp_path: Path) -> None:
        payload = _fixture("session_end_context_window.json")
        env = {"OMNI_HOME": "/workspace/omni_home"}

        # Remove emit_client_wrapper from sys.modules so import fails
        import sys

        sys.modules.pop("emit_client_wrapper", None)

        # plugin_root left empty so hooks_lib path is "" and import will fail
        result = emit_session_cost(
            session_end_payload=payload,
            env=env,
            accumulator_dir=tmp_path,
            plugin_root="",
        )

        # Must degrade silently, never raise
        assert result is False


class TestEmitSessionCostAccumulatorFallback:
    def test_uses_accumulator_when_session_end_has_no_tokens(
        self, tmp_path: Path
    ) -> None:
        accumulator = tmp_path / "omniclaude-session-fallback-session.json"
        accumulator.write_text(
            json.dumps({"total_input_tokens": 500, "total_output_tokens": 200}),
            encoding="utf-8",
        )

        captured: list[dict] = []
        mock_module = MagicMock()
        mock_module.emit_event = lambda _et, p, **_kw: captured.append(p) or True

        with patch.dict("sys.modules", {"emit_client_wrapper": mock_module}):
            result = emit_session_cost(
                session_end_payload={},
                env={"OMNI_HOME": "/workspace/omni_home"},
                session_id="fallback-session",
                accumulator_dir=tmp_path,
            )

        assert result is True
        assert len(captured) == 1
        assert captured[0]["prompt_tokens"] == 500
        assert captured[0]["completion_tokens"] == 200
        assert captured[0]["total_tokens"] == 700
