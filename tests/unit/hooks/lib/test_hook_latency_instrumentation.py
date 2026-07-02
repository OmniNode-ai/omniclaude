# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for per-hook latency instrumentation (OMN-13847).

Verifies the emit-side timing primitive:
    * builds a ``hook.executed`` payload carrying ``duration_ms`` (int) plus the
      hook_name / event / blocked / correlation_id fields,
    * emits ``duration_ms`` through ``emit_event`` when a hook body runs,
    * records timing even when the hook body raises / blocks,
    * is fail-open (never raises) and inert when emission is disabled.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# hooks/lib modules live outside the normal package tree -- put the dir on path.
_LIB_PATH = str(
    Path(__file__).resolve().parents[4] / "plugins" / "onex" / "hooks" / "lib"
)
if _LIB_PATH not in sys.path:
    sys.path.insert(0, _LIB_PATH)

import hook_latency_instrumentation as hli  # noqa: E402

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# build_hook_execution_payload
# ---------------------------------------------------------------------------


class TestBuildPayload:
    def test_payload_contains_duration_ms_as_int(self) -> None:
        payload = hli.build_hook_execution_payload(
            hook_name="bash_guard",
            event="PreToolUse",
            duration_ms=42,
            blocked=False,
        )
        assert payload["duration_ms"] == 42
        assert isinstance(payload["duration_ms"], int)

    def test_payload_carries_required_fields(self) -> None:
        payload = hli.build_hook_execution_payload(
            hook_name="bash_guard",
            event="PreToolUse",
            duration_ms=10,
            blocked=True,
            correlation_id="c-123",
            session_id="s-abc",
        )
        assert payload["hook_name"] == "bash_guard"
        assert payload["event"] == "PreToolUse"
        assert payload["blocked"] is True
        assert payload["correlation_id"] == "c-123"
        assert payload["session_id"] == "s-abc"

    def test_correlation_id_generated_when_absent(self) -> None:
        payload = hli.build_hook_execution_payload(
            hook_name="h",
            event="PostToolUse",
            duration_ms=1,
            blocked=False,
        )
        # A valid UUID string is generated when none is supplied.
        uuid.UUID(str(payload["correlation_id"]))

    def test_session_id_omitted_when_not_passed(self) -> None:
        # emit_event injects session_id from CLAUDE_CODE_SESSION_ID at emit time;
        # the builder only includes it when the caller supplies it explicitly.
        payload = hli.build_hook_execution_payload(
            hook_name="h",
            event="PreToolUse",
            duration_ms=1,
            blocked=False,
        )
        assert "session_id" not in payload

    def test_duration_and_blocked_are_coerced(self) -> None:
        payload = hli.build_hook_execution_payload(
            hook_name="h",
            event="PreToolUse",
            duration_ms=True,  # type: ignore[arg-type]
            blocked=1,  # type: ignore[arg-type]
        )
        assert payload["duration_ms"] == 1
        assert payload["blocked"] is True


# ---------------------------------------------------------------------------
# emit_hook_execution
# ---------------------------------------------------------------------------


class TestEmitHookExecution:
    def test_emits_hook_executed_with_duration_ms(self) -> None:
        mock_emit = MagicMock(return_value=True)
        with patch.object(hli, "_emit_event", mock_emit):
            ok = hli.emit_hook_execution(
                hook_name="bash_guard",
                event="PreToolUse",
                duration_ms=17,
            )
        assert ok is True
        mock_emit.assert_called_once()
        event_type, payload = mock_emit.call_args.args
        assert event_type == hli.HOOK_EXECUTION_EVENT_TYPE == "hook.executed"
        assert payload["duration_ms"] == 17

    def test_returns_false_when_emit_unavailable(self) -> None:
        with patch.object(hli, "_emit_event", None):
            assert (
                hli.emit_hook_execution(
                    hook_name="h", event="PreToolUse", duration_ms=1
                )
                is False
            )

    def test_never_raises_when_emit_raises(self) -> None:
        mock_emit = MagicMock(side_effect=RuntimeError("daemon exploded"))
        with patch.object(hli, "_emit_event", mock_emit):
            assert (
                hli.emit_hook_execution(
                    hook_name="h", event="PreToolUse", duration_ms=1
                )
                is False
            )


# ---------------------------------------------------------------------------
# instrument_hook context manager
# ---------------------------------------------------------------------------


class TestInstrumentHook:
    def test_emits_duration_ms_on_exit(self) -> None:
        mock_emit = MagicMock(return_value=True)
        with (
            patch.object(hli, "_emit_event", mock_emit),
            hli.instrument_hook("bash_guard", "PreToolUse") as handle,
        ):
            pass
        mock_emit.assert_called_once()
        event_type, payload = mock_emit.call_args.args
        assert event_type == "hook.executed"
        assert isinstance(payload["duration_ms"], int)
        assert payload["duration_ms"] >= 0
        assert payload["blocked"] is False
        # Handle exposes the measured duration after exit.
        assert handle.duration_ms == payload["duration_ms"]

    def test_blocked_flag_propagates_to_payload(self) -> None:
        mock_emit = MagicMock(return_value=True)
        with patch.object(hli, "_emit_event", mock_emit):
            with hli.instrument_hook("bash_guard", "PreToolUse") as handle:
                handle.blocked = True
        _event_type, payload = mock_emit.call_args.args
        assert payload["blocked"] is True

    def test_emits_even_when_body_raises(self) -> None:
        mock_emit = MagicMock(return_value=True)
        with patch.object(hli, "_emit_event", mock_emit):  # noqa: SIM117
            with pytest.raises(ValueError, match="boom"):
                with hli.instrument_hook("h", "PreToolUse"):
                    raise ValueError("boom")
        # duration event still emitted from the finally block.
        mock_emit.assert_called_once()
        _event_type, payload = mock_emit.call_args.args
        assert "duration_ms" in payload

    def test_inert_when_emit_disabled(self) -> None:
        mock_emit = MagicMock(return_value=True)
        with patch.object(hli, "_emit_event", mock_emit):
            with hli.instrument_hook("h", "PreToolUse", emit=False) as handle:
                pass
        mock_emit.assert_not_called()
        # Timing is still measured for callers that want the value.
        assert isinstance(handle.duration_ms, int)


# ---------------------------------------------------------------------------
# instrumented_hook decorator
# ---------------------------------------------------------------------------


class TestInstrumentedHookDecorator:
    def test_decorator_times_and_emits(self) -> None:
        mock_emit = MagicMock(return_value=True)

        @hli.instrumented_hook("my_hook", "PostToolUse")
        def run() -> str:
            return "done"

        with patch.object(hli, "_emit_event", mock_emit):
            result = run()

        assert result == "done"
        mock_emit.assert_called_once()
        event_type, payload = mock_emit.call_args.args
        assert event_type == "hook.executed"
        assert payload["hook_name"] == "my_hook"
        assert payload["event"] == "PostToolUse"
        assert isinstance(payload["duration_ms"], int)

    def test_decorator_preserves_metadata(self) -> None:
        @hli.instrumented_hook("my_hook", "PreToolUse")
        def documented() -> None:
            """Original docstring."""

        assert documented.__name__ == "documented"
        assert documented.__doc__ == "Original docstring."
