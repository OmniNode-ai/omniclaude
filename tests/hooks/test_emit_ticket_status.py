# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Tests for emit_ticket_status CLI wrapper module.

This module tests the thin CLI wrapper that enables the ticket-work skill
to emit agent status events via bash commands. It validates:
- CLI argument parsing (required/optional args, types)
- Ticket ID injection into metadata
- Delegation to emit_agent_status with correct arguments
- Fail-open behavior (always exits 0 regardless of errors)

Transitive dependency note:
    Same tiktoken consideration as test_agent_status_emitter.py. We install
    schema stand-ins if the real schemas are unavailable. See that module's
    docstring for full explanation.
"""

from __future__ import annotations

import sys
from enum import StrEnum
from typing import Literal
from unittest.mock import patch
from uuid import UUID

import pytest
from pydantic import BaseModel, ConfigDict, Field

# All tests in this module are unit tests
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
    from datetime import datetime

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
# Import the module under test
# =============================================================================

from plugins.onex.hooks.lib.emit_ticket_status import main  # noqa: E402

# =============================================================================
# CLI Parsing Tests
# =============================================================================


class TestCLIParsing:
    """Tests for CLI argument parsing."""

    def test_required_args_state_and_message(self) -> None:
        """Missing --state or --message should still exit 0 (fail-open)."""
        # Missing both
        main([])
        # Missing --message
        main(["--state", "working"])
        # Missing --state
        main(["--message", "hello"])
        # If we reach here, no exception was raised and exit 0 was preserved

    def test_all_optional_args_parsed(self) -> None:
        """All optional args (--phase, --task, --progress, etc.) parse correctly."""
        with patch(
            "plugins.onex.hooks.lib.agent_status_emitter.emit_agent_status",
            return_value=True,
        ) as mock_emit:
            main(
                [
                    "--state",
                    "working",
                    "--message",
                    "Doing work",
                    "--phase",
                    "research",
                    "--task",
                    "Researching codebase",
                    "--progress",
                    "0.15",
                    "--blocking-reason",
                    "Waiting for API",
                    "--ticket-id",
                    "OMN-1850",
                    "--metadata",
                    '{"key": "val"}',
                ]
            )

        mock_emit.assert_called_once()
        kwargs = mock_emit.call_args
        assert kwargs.kwargs["current_phase"] == "research"
        assert kwargs.kwargs["current_task"] == "Researching codebase"
        assert kwargs.kwargs["progress"] == 0.15
        assert kwargs.kwargs["blocking_reason"] == "Waiting for API"

    def test_progress_parsed_as_float(self) -> None:
        """--progress 0.82 parses as float, not string."""
        with patch(
            "plugins.onex.hooks.lib.agent_status_emitter.emit_agent_status",
            return_value=True,
        ) as mock_emit:
            main(["--state", "working", "--message", "test", "--progress", "0.82"])

        assert mock_emit.call_args.kwargs["progress"] == 0.82
        assert isinstance(mock_emit.call_args.kwargs["progress"], float)

    def test_metadata_parsed_as_json(self) -> None:
        """--metadata '{"key": "val"}' parses to a dict."""
        with patch(
            "plugins.onex.hooks.lib.agent_status_emitter.emit_agent_status",
            return_value=True,
        ) as mock_emit:
            main(
                [
                    "--state",
                    "working",
                    "--message",
                    "test",
                    "--metadata",
                    '{"key": "val"}',
                ]
            )

        metadata = mock_emit.call_args.kwargs["metadata"]
        assert isinstance(metadata, dict)
        assert metadata["key"] == "val"

    def test_metadata_non_dict_json(self) -> None:
        """--metadata '[1,2,3]' is valid JSON but not a dict; falls back to empty dict."""
        with patch(
            "plugins.onex.hooks.lib.agent_status_emitter.emit_agent_status",
            return_value=True,
        ) as mock_emit:
            main(
                [
                    "--state",
                    "working",
                    "--message",
                    "test",
                    "--metadata",
                    "[1, 2, 3]",
                    "--ticket-id",
                    "OMN-1850",
                ]
            )

        # Non-dict JSON falls back to {}, then ticket_id is injected
        metadata = mock_emit.call_args.kwargs["metadata"]
        assert metadata == {"ticket_id": "OMN-1850"}

    def test_metadata_non_dict_json_without_ticket_id(self) -> None:
        """--metadata '"just a string"' (valid JSON, not dict) without --ticket-id."""
        with patch(
            "plugins.onex.hooks.lib.agent_status_emitter.emit_agent_status",
            return_value=True,
        ) as mock_emit:
            main(
                [
                    "--state",
                    "working",
                    "--message",
                    "test",
                    "--metadata",
                    '"just a string"',
                ]
            )

        # Non-dict JSON falls back to empty dict; no ticket_id to inject
        metadata = mock_emit.call_args.kwargs["metadata"]
        assert metadata == {}

    def test_progress_out_of_range_exits_zero(self) -> None:
        """Out-of-range --progress values (e.g., 1.5, -0.1) still exit 0 (fail-open).

        The CLI now validates --progress is in [0.0, 1.0] via a custom argparse
        type callback. Invalid values cause argparse to call sys.exit(2), which
        the SystemExit handler catches (fail-open). The emitter is never called.
        """
        with patch(
            "plugins.onex.hooks.lib.agent_status_emitter.emit_agent_status",
            return_value=True,
        ) as mock_emit:
            # Progress > 1.0 -- rejected by argparse, emitter never called
            main(["--state", "working", "--message", "test", "--progress", "1.5"])

        mock_emit.assert_not_called()

        with patch(
            "plugins.onex.hooks.lib.agent_status_emitter.emit_agent_status",
            return_value=True,
        ) as mock_emit:
            # Progress < 0.0 -- rejected by argparse, emitter never called
            main(["--state", "working", "--message", "test", "--progress", "-0.1"])

        mock_emit.assert_not_called()

    def test_progress_out_of_range_emitter_raises_exits_zero(self) -> None:
        """If emitter rejects out-of-range progress with an exception, CLI still exits 0."""
        with patch(
            "plugins.onex.hooks.lib.agent_status_emitter.emit_agent_status",
            side_effect=ValueError("progress must be between 0.0 and 1.0"),
        ):
            # Should not raise -- fail-open catches the ValueError
            main(["--state", "working", "--message", "test", "--progress", "1.5"])


# =============================================================================
# Ticket ID Injection Tests
# =============================================================================


class TestTicketIdInjection:
    """Tests for ticket_id injection into metadata dict."""

    def test_ticket_id_merged_into_metadata(self) -> None:
        """When both --ticket-id and --metadata provided, ticket_id is merged in."""
        with patch(
            "plugins.onex.hooks.lib.agent_status_emitter.emit_agent_status",
            return_value=True,
        ) as mock_emit:
            main(
                [
                    "--state",
                    "working",
                    "--message",
                    "test",
                    "--ticket-id",
                    "OMN-1850",
                    "--metadata",
                    '{"foo": "bar"}',
                ]
            )

        metadata = mock_emit.call_args.kwargs["metadata"]
        assert metadata == {"foo": "bar", "ticket_id": "OMN-1850"}

    def test_ticket_id_without_metadata(self) -> None:
        """When only --ticket-id provided, metadata is {"ticket_id": "..."}."""
        with patch(
            "plugins.onex.hooks.lib.agent_status_emitter.emit_agent_status",
            return_value=True,
        ) as mock_emit:
            main(
                [
                    "--state",
                    "working",
                    "--message",
                    "test",
                    "--ticket-id",
                    "OMN-1850",
                ]
            )

        metadata = mock_emit.call_args.kwargs["metadata"]
        assert metadata == {"ticket_id": "OMN-1850"}

    def test_no_ticket_id_no_metadata(self) -> None:
        """When neither --ticket-id nor --metadata provided, metadata is None."""
        with patch(
            "plugins.onex.hooks.lib.agent_status_emitter.emit_agent_status",
            return_value=True,
        ) as mock_emit:
            main(["--state", "working", "--message", "test"])

        metadata = mock_emit.call_args.kwargs["metadata"]
        assert metadata is None


# =============================================================================
# Emission Delegation Tests
# =============================================================================


class TestEmissionDelegation:
    """Tests that main() delegates to emit_agent_status with correct args."""

    def test_calls_emit_agent_status_with_correct_args(self) -> None:
        """All CLI args are forwarded to emit_agent_status as keyword args."""
        with patch(
            "plugins.onex.hooks.lib.agent_status_emitter.emit_agent_status",
            return_value=True,
        ) as mock_emit:
            main(
                [
                    "--state",
                    "blocked",
                    "--message",
                    "Awaiting spec approval",
                    "--phase",
                    "spec",
                    "--task",
                    "Generating specification",
                    "--progress",
                    "0.45",
                    "--blocking-reason",
                    "Human gate: approve spec",
                    "--ticket-id",
                    "OMN-1850",
                    "--metadata",
                    '{"extra": "data"}',
                ]
            )

        mock_emit.assert_called_once_with(
            state="blocked",
            message="Awaiting spec approval",
            current_phase="spec",
            current_task="Generating specification",
            progress=0.45,
            blocking_reason="Human gate: approve spec",
            metadata={"extra": "data", "ticket_id": "OMN-1850"},
        )

    def test_exit_code_zero_on_success(self) -> None:
        """main() does not raise when emit_agent_status returns True."""
        with patch(
            "plugins.onex.hooks.lib.agent_status_emitter.emit_agent_status",
            return_value=True,
        ):
            # Should not raise
            main(["--state", "working", "--message", "Success path"])

    def test_exit_code_zero_on_failure(self) -> None:
        """main() does not raise when emit_agent_status returns False (fail-open)."""
        with patch(
            "plugins.onex.hooks.lib.agent_status_emitter.emit_agent_status",
            return_value=False,
        ):
            # Should not raise (fail-open)
            main(["--state", "working", "--message", "Emission failed"])

    def test_exit_code_zero_on_exception(self) -> None:
        """main() does not raise when emit_agent_status raises an exception."""
        with patch(
            "plugins.onex.hooks.lib.agent_status_emitter.emit_agent_status",
            side_effect=ConnectionRefusedError("Daemon not running"),
        ):
            # Should not raise (fail-open catches all exceptions)
            main(["--state", "working", "--message", "Exception path"])

    def test_exit_code_zero_on_import_error(self) -> None:
        """main() does not raise when the emitter import fails."""
        # Simulate import failure by patching the import target
        import builtins

        _real_import = builtins.__import__

        def _fake_import(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
            if "agent_status_emitter" in name:
                raise ImportError("Simulated import failure")
            return _real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=_fake_import):
            # Should not raise
            main(["--state", "working", "--message", "Import failure"])

    def test_invalid_metadata_json_still_exits_zero(self) -> None:
        """Invalid JSON in --metadata prints warning but does not crash."""
        with patch(
            "plugins.onex.hooks.lib.agent_status_emitter.emit_agent_status",
            return_value=True,
        ) as mock_emit:
            main(
                [
                    "--state",
                    "working",
                    "--message",
                    "test",
                    "--metadata",
                    "not-valid-json",
                    "--ticket-id",
                    "OMN-1850",
                ]
            )

        # Should still call emit with ticket_id in metadata (invalid JSON -> empty dict)
        metadata = mock_emit.call_args.kwargs["metadata"]
        assert metadata == {"ticket_id": "OMN-1850"}

    def test_dunder_main_guard_invokes_main(self) -> None:
        """The ``if __name__ == '__main__': main()`` guard works end-to-end."""
        import runpy

        with (
            patch(
                "plugins.onex.hooks.lib.agent_status_emitter.emit_agent_status",
                return_value=True,
            ) as mock_emit,
            patch(
                "sys.argv",
                [
                    "emit_ticket_status",
                    "--state",
                    "working",
                    "--message",
                    "main guard test",
                    "--ticket-id",
                    "OMN-9999",
                ],
            ),
        ):
            runpy.run_module(
                "plugins.onex.hooks.lib.emit_ticket_status",
                run_name="__main__",
            )

        mock_emit.assert_called_once()
        assert mock_emit.call_args.kwargs["state"] == "working"
        assert mock_emit.call_args.kwargs["message"] == "main guard test"
        assert mock_emit.call_args.kwargs["metadata"] == {"ticket_id": "OMN-9999"}
