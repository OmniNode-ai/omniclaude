#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for emitter sentinel/empty-string validation (OMN-6907).

Covers:
- agent_status_emitter: data_quality=degraded metadata tag when sentinels used
- shadow_validation: warning logged when session_id falls back to "unknown"
- pipeline_event_emitters: run_id rejection, correlation_id warning
"""

from __future__ import annotations

import logging
import sys
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from pydantic import BaseModel, ConfigDict, Field

pytestmark = pytest.mark.unit


# =============================================================================
# Tiktoken-safe schema mocking (same pattern as test_agent_status_emitter.py)
# =============================================================================

_SCHEMAS_MOCK_INSTALLED = False

try:
    from omniclaude.hooks.schemas import (  # noqa: F401
        EnumAgentState,
        ModelAgentStatusPayload,
    )
except Exception:

    class EnumAgentState(StrEnum):  # type: ignore[no-redef]
        IDLE = "idle"
        WORKING = "working"
        BLOCKED = "blocked"
        AWAITING_INPUT = "awaiting_input"
        FINISHED = "finished"
        ERROR = "error"

    class ModelAgentStatusPayload(BaseModel):  # type: ignore[no-redef]
        model_config = ConfigDict(frozen=True, extra="forbid")

        correlation_id: UUID = Field(...)
        agent_name: str = Field(..., min_length=1)
        session_id: str = Field(..., min_length=1)
        agent_instance_id: str | None = Field(default=None)
        state: EnumAgentState = Field(...)
        schema_version: Literal[1] = Field(default=1)
        message: str = Field(..., min_length=1, max_length=500)
        progress: float | None = Field(default=None, ge=0.0, le=1.0)
        current_phase: str | None = Field(default=None)
        current_task: str | None = Field(default=None)
        blocking_reason: str | None = Field(default=None)
        emitted_at: datetime = Field(...)
        metadata: dict[str, str] = Field(default_factory=dict)
        task_id: str | None = Field(default=None)

    import types as _types

    _schemas_mod = sys.modules.get("omniclaude.hooks.schemas")
    if _schemas_mod is None:
        _schemas_mod = _types.ModuleType("omniclaude.hooks.schemas")
        for _parent in ("omniclaude", "omniclaude.hooks"):
            if _parent not in sys.modules:
                sys.modules[_parent] = _types.ModuleType(_parent)
        sys.modules["omniclaude.hooks.schemas"] = _schemas_mod

    _schemas_mod.EnumAgentState = EnumAgentState  # type: ignore[attr-defined]
    _schemas_mod.ModelAgentStatusPayload = ModelAgentStatusPayload  # type: ignore[attr-defined]
    _SCHEMAS_MOCK_INSTALLED = True


# =============================================================================
# agent_status_emitter: data_quality degraded tagging (OMN-6907)
# =============================================================================


class TestAgentStatusEmitterDegradedTag:
    """Verify sentinel fallbacks tag metadata with data_quality=degraded."""

    def test_unknown_agent_name_tags_metadata_degraded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When agent_name resolves to 'unknown', metadata includes data_quality=degraded."""
        from plugins.onex.hooks.lib.agent_status_emitter import emit_agent_status

        captured_payload: dict = {}

        def capture_emit(event_type: str, payload: dict) -> bool:
            captured_payload.update(payload)
            return True

        monkeypatch.delenv("AGENT_NAME", raising=False)
        monkeypatch.delenv("SESSION_ID", raising=False)

        with patch(
            "plugins.onex.hooks.lib.emit_client_wrapper.emit_event",
            side_effect=capture_emit,
        ):
            result = emit_agent_status(
                "idle",
                "Test degraded tag",
                session_id="real-session",
            )

        assert result is True
        assert captured_payload["metadata"]["data_quality"] == "degraded"
        assert "agent_name" in captured_payload["metadata"]["degraded_fields"]

    def test_unknown_session_id_tags_metadata_degraded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When session_id resolves to 'unknown', metadata includes data_quality=degraded."""
        from plugins.onex.hooks.lib.agent_status_emitter import emit_agent_status

        captured_payload: dict = {}

        def capture_emit(event_type: str, payload: dict) -> bool:
            captured_payload.update(payload)
            return True

        monkeypatch.delenv("SESSION_ID", raising=False)

        with patch(
            "plugins.onex.hooks.lib.emit_client_wrapper.emit_event",
            side_effect=capture_emit,
        ):
            result = emit_agent_status(
                "idle",
                "Test degraded session",
                agent_name="real-agent",
            )

        assert result is True
        assert captured_payload["metadata"]["data_quality"] == "degraded"
        assert "session_id" in captured_payload["metadata"]["degraded_fields"]

    def test_both_unknown_lists_both_degraded_fields(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When both resolve to 'unknown', degraded_fields lists both."""
        from plugins.onex.hooks.lib.agent_status_emitter import emit_agent_status

        captured_payload: dict = {}

        def capture_emit(event_type: str, payload: dict) -> bool:
            captured_payload.update(payload)
            return True

        monkeypatch.delenv("AGENT_NAME", raising=False)
        monkeypatch.delenv("SESSION_ID", raising=False)

        with patch(
            "plugins.onex.hooks.lib.emit_client_wrapper.emit_event",
            side_effect=capture_emit,
        ):
            emit_agent_status("idle", "Both unknown")

        degraded = captured_payload["metadata"]["degraded_fields"]
        assert "agent_name" in degraded
        assert "session_id" in degraded

    def test_no_degraded_tag_when_values_provided(self) -> None:
        """When both agent_name and session_id are explicit, no degraded tag."""
        from plugins.onex.hooks.lib.agent_status_emitter import emit_agent_status

        captured_payload: dict = {}

        def capture_emit(event_type: str, payload: dict) -> bool:
            captured_payload.update(payload)
            return True

        with patch(
            "plugins.onex.hooks.lib.emit_client_wrapper.emit_event",
            side_effect=capture_emit,
        ):
            emit_agent_status(
                "idle",
                "All good",
                agent_name="real-agent",
                session_id="real-session",
            )

        assert "data_quality" not in captured_payload["metadata"]

    def test_caller_metadata_preserved_alongside_degraded_tag(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Caller-provided metadata is preserved when degraded tags are added."""
        from plugins.onex.hooks.lib.agent_status_emitter import emit_agent_status

        captured_payload: dict = {}

        def capture_emit(event_type: str, payload: dict) -> bool:
            captured_payload.update(payload)
            return True

        monkeypatch.delenv("AGENT_NAME", raising=False)

        with patch(
            "plugins.onex.hooks.lib.emit_client_wrapper.emit_event",
            side_effect=capture_emit,
        ):
            emit_agent_status(
                "idle",
                "With user metadata",
                session_id="real-session",
                metadata={"request_id": "req-001"},
            )

        assert captured_payload["metadata"]["request_id"] == "req-001"
        assert captured_payload["metadata"]["data_quality"] == "degraded"


# =============================================================================
# pipeline_event_emitters: run_id validation (OMN-6907)
# =============================================================================


@pytest.fixture
def mock_emit_fn() -> MagicMock:
    return MagicMock()


@pytest.fixture(autouse=True)
def _patch_pipeline_emit(mock_emit_fn: MagicMock):
    with patch(
        "plugins.onex.hooks.lib.pipeline_event_emitters._get_emit_fn",
        return_value=mock_emit_fn,
    ):
        yield


class TestPipelineEmitterRunIdValidation:
    """Verify empty run_id is rejected with warning, no event emitted."""

    def test_empty_run_id_skips_epic_emit(self, mock_emit_fn: MagicMock) -> None:
        from plugins.onex.hooks.lib.pipeline_event_emitters import (
            emit_epic_run_updated,
        )

        emit_epic_run_updated(
            run_id="",
            epic_id="OMN-123",
            status="running",
            correlation_id="corr-1",
        )

        mock_emit_fn.assert_not_called()

    def test_empty_run_id_skips_pr_watch_emit(self, mock_emit_fn: MagicMock) -> None:
        from plugins.onex.hooks.lib.pipeline_event_emitters import (
            emit_pr_watch_updated,
        )

        emit_pr_watch_updated(
            run_id="",
            pr_number=1,
            repo="OmniNode-ai/omniclaude",
            ticket_id="OMN-123",
            status="watching",
            correlation_id="corr-1",
        )

        mock_emit_fn.assert_not_called()

    def test_empty_run_id_skips_budget_cap_emit(self, mock_emit_fn: MagicMock) -> None:
        from plugins.onex.hooks.lib.pipeline_event_emitters import (
            emit_budget_cap_hit,
        )

        emit_budget_cap_hit(
            run_id="",
            tokens_used=100,
            tokens_budget=50,
            correlation_id="corr-1",
        )

        mock_emit_fn.assert_not_called()

    def test_empty_run_id_skips_dod_sweep_emit(self, mock_emit_fn: MagicMock) -> None:
        from plugins.onex.hooks.lib.pipeline_event_emitters import (
            emit_dod_sweep_completed,
        )

        emit_dod_sweep_completed(
            run_id="",
            overall_status="passed",
            total_tickets=5,
            passed=5,
            failed=0,
            exempted=0,
            lookback_days=7,
        )

        mock_emit_fn.assert_not_called()

    def test_valid_run_id_emits_normally(self, mock_emit_fn: MagicMock) -> None:
        from plugins.onex.hooks.lib.pipeline_event_emitters import (
            emit_epic_run_updated,
        )

        emit_epic_run_updated(
            run_id="real-run-id",
            epic_id="OMN-123",
            status="running",
            correlation_id="corr-1",
        )

        mock_emit_fn.assert_called_once()

    def test_empty_run_id_logs_warning(
        self, mock_emit_fn: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        from plugins.onex.hooks.lib.pipeline_event_emitters import (
            emit_epic_run_updated,
        )

        with caplog.at_level(logging.WARNING):
            emit_epic_run_updated(
                run_id="",
                epic_id="OMN-123",
                status="running",
                correlation_id="corr-1",
            )

        assert any(
            "run_id" in r.message and "skipping emit" in r.message
            for r in caplog.records
        )


class TestPipelineEmitterCorrelationIdWarning:
    """Verify empty correlation_id logs warning but still emits."""

    def test_empty_correlation_id_still_emits(self, mock_emit_fn: MagicMock) -> None:
        from plugins.onex.hooks.lib.pipeline_event_emitters import (
            emit_epic_run_updated,
        )

        emit_epic_run_updated(
            run_id="real-run-id",
            epic_id="OMN-123",
            status="running",
            correlation_id="",
        )

        # Event still emits (correlation_id is non-fatal)
        mock_emit_fn.assert_called_once()

    def test_empty_correlation_id_logs_warning(
        self, mock_emit_fn: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        from plugins.onex.hooks.lib.pipeline_event_emitters import (
            emit_epic_run_updated,
        )

        with caplog.at_level(logging.WARNING):
            emit_epic_run_updated(
                run_id="real-run-id",
                epic_id="OMN-123",
                status="running",
                correlation_id="",
            )

        assert any("correlation_id is empty" in r.message for r in caplog.records)

    def test_valid_correlation_id_no_warning(
        self, mock_emit_fn: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        from plugins.onex.hooks.lib.pipeline_event_emitters import (
            emit_epic_run_updated,
        )

        with caplog.at_level(logging.WARNING):
            emit_epic_run_updated(
                run_id="real-run-id",
                epic_id="OMN-123",
                status="running",
                correlation_id="real-corr-id",
            )

        assert not any("correlation_id is empty" in r.message for r in caplog.records)


# =============================================================================
# shadow_validation: session_id sentinel warning (OMN-6907)
# =============================================================================


class TestShadowValidationSessionIdWarning:
    """Verify shadow_validation warns when session_id falls back to 'unknown'."""

    def test_empty_session_id_logs_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        from pathlib import Path

        # Insert hooks/lib for direct import
        hooks_lib = (
            Path(__file__).parent.parent.parent.parent.parent
            / "plugins"
            / "onex"
            / "hooks"
            / "lib"
        )
        if str(hooks_lib) not in sys.path:
            sys.path.insert(0, str(hooks_lib))

        import shadow_validation as sv

        with caplog.at_level(logging.WARNING):
            # Call the internal _emit function which does the session_id resolution
            # We mock the schema import and emit to isolate the warning behavior
            with (
                patch.object(sv, "_get_consecutive_passing_days", return_value=0),
                patch.object(sv, "_get_exit_threshold", return_value=0.95),
                patch.object(sv, "_get_exit_window_days", return_value=30),
                patch("emit_client_wrapper.emit_event", return_value=True),
            ):
                try:
                    sv._emit_shadow_comparison_event(
                        session_id="",
                        correlation_id=str(__import__("uuid").uuid4()),
                        task_type="test",
                        local_model="test-model",
                        shadow_model="claude-sonnet-4-6",
                        comparison={
                            "local_response_length": 100,
                            "shadow_response_length": 100,
                            "length_divergence_ratio": 0.0,
                            "keyword_overlap_score": 1.0,
                            "structural_match": True,
                            "quality_gate_passed": True,
                            "divergence_reason": None,
                        },
                        shadow_latency_ms=100,
                        sample_rate=1.0,
                        emitted_at=datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC),
                        auto_disable_triggered=False,
                    )
                except Exception:
                    pass  # Schema import may fail; we only care about the warning

        assert any(
            "session_id resolved to 'unknown'" in r.message for r in caplog.records
        )

    def test_valid_session_id_no_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        from pathlib import Path

        hooks_lib = (
            Path(__file__).parent.parent.parent.parent.parent
            / "plugins"
            / "onex"
            / "hooks"
            / "lib"
        )
        if str(hooks_lib) not in sys.path:
            sys.path.insert(0, str(hooks_lib))

        import shadow_validation as sv

        with caplog.at_level(logging.WARNING):
            with (
                patch.object(sv, "_get_consecutive_passing_days", return_value=0),
                patch.object(sv, "_get_exit_threshold", return_value=0.95),
                patch.object(sv, "_get_exit_window_days", return_value=30),
                patch("emit_client_wrapper.emit_event", return_value=True),
            ):
                try:
                    sv._emit_shadow_comparison_event(
                        session_id="real-session-id",
                        correlation_id=str(__import__("uuid").uuid4()),
                        task_type="test",
                        local_model="test-model",
                        shadow_model="claude-sonnet-4-6",
                        comparison={
                            "local_response_length": 100,
                            "shadow_response_length": 100,
                            "length_divergence_ratio": 0.0,
                            "keyword_overlap_score": 1.0,
                            "structural_match": True,
                            "quality_gate_passed": True,
                            "divergence_reason": None,
                        },
                        shadow_latency_ms=100,
                        sample_rate=1.0,
                        emitted_at=datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC),
                        auto_disable_triggered=False,
                    )
                except Exception:
                    pass

        assert not any(
            "session_id resolved to 'unknown'" in r.message for r in caplog.records
        )
