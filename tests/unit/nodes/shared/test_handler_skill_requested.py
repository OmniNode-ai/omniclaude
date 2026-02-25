# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Unit tests for handler_skill_requested.py.

Covers (22 tests):
- test_build_args_string_bare_flag_for_empty_value
- test_build_args_string_bare_flag_for_true_value
- test_build_args_string_key_value_pair
- test_build_args_string_mixed
- test_build_args_string_empty_dict
- test_handle_skill_requested_dispatches_polly_with_skill_path
- test_handle_skill_requested_returns_failure_on_exception
- test_handle_skill_requested_parses_result_block
- test_handle_skill_requested_partial_when_no_result_block
- test_handle_skill_requested_failed_status_from_result_block
- test_handle_skill_requested_includes_args_in_prompt
- test_handle_skill_requested_partial_for_unrecognized_status
- test_trailing_status_and_error_after_blank_line_are_ignored
TestHandleSkillRequestedWithEventEmitter (9 tests — OMN-2773):
- test_emits_started_before_dispatch
- test_emits_completed_on_success
- test_emits_completed_on_dispatcher_exception
- test_no_emit_when_emitter_is_none
- test_emit_exception_does_not_propagate
- test_run_id_is_same_for_started_and_completed
- test_event_id_parses_as_uuid
- test_payload_matches_model_schema
- test_duration_ms_is_non_negative
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from omniclaude.nodes.shared.handler_skill_requested import (
    _build_args_string,
    handle_skill_requested,
)
from omniclaude.nodes.shared.models.model_skill_lifecycle_events import (
    ModelSkillCompletedEvent,
    ModelSkillStartedEvent,
)
from omniclaude.nodes.shared.models.model_skill_request import ModelSkillRequest
from omniclaude.nodes.shared.models.model_skill_result import SkillResultStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(
    skill_name: str = "pr-review",
    skill_path: str = "/plugins/onex/skills/pr-review/SKILL.md",
    args: dict[str, str] | None = None,
) -> ModelSkillRequest:
    return ModelSkillRequest(
        skill_name=skill_name,
        skill_path=skill_path,
        args=args or {},
        correlation_id=uuid4(),
    )


# ---------------------------------------------------------------------------
# _build_args_string tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildArgsString:
    """Unit tests for _build_args_string()."""

    def test_build_args_string_bare_flag_for_empty_value(self) -> None:
        """An empty string value produces a bare flag."""
        result = _build_args_string({"verbose": ""})
        assert result == "--verbose"

    def test_build_args_string_bare_flag_for_true_value(self) -> None:
        """The literal value 'true' produces a bare flag."""
        result = _build_args_string({"dry-run": "true"})
        assert result == "--dry-run"

    def test_build_args_string_key_value_pair(self) -> None:
        """A non-empty, non-'true' value produces a --key value pair."""
        result = _build_args_string({"count": "5"})
        assert result == "--count 5"

    def test_build_args_string_mixed(self) -> None:
        """Mixed args: bare flags and key-value pairs coexist."""
        # Use an ordered dict to get deterministic output
        args: dict[str, str] = {"verbose": "", "count": "3", "dry-run": "true"}
        result = _build_args_string(args)
        assert "--verbose" in result
        assert "--count 3" in result
        assert "--dry-run" in result
        # bare flag "true" must NOT appear as a value
        assert "true" not in result

    def test_build_args_string_empty_dict(self) -> None:
        """Empty args dict produces an empty string."""
        result = _build_args_string({})
        assert result == ""


# ---------------------------------------------------------------------------
# handle_skill_requested tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandleSkillRequested:
    """Integration-style tests for handle_skill_requested()."""

    @pytest.mark.asyncio
    async def test_handle_skill_requested_dispatches_polly_with_skill_path(
        self,
    ) -> None:
        """The prompt passed to task_dispatcher includes the skill_path."""
        skill_path = "/plugins/onex/skills/pr-review/SKILL.md"
        request = _make_request(skill_path=skill_path)

        output_with_result = "Some output\nRESULT:\nstatus: success\nerror:\n"
        dispatcher = AsyncMock(return_value=output_with_result)

        await handle_skill_requested(request, task_dispatcher=dispatcher)

        dispatcher.assert_awaited_once()
        prompt_arg: str = dispatcher.call_args[0][0]
        assert skill_path in prompt_arg

    @pytest.mark.asyncio
    async def test_handle_skill_requested_returns_failure_on_exception(
        self,
    ) -> None:
        """When task_dispatcher raises, the result status is FAILED."""
        request = _make_request()
        dispatcher = AsyncMock(side_effect=RuntimeError("connection refused"))

        result = await handle_skill_requested(request, task_dispatcher=dispatcher)

        assert result.status == SkillResultStatus.FAILED
        assert result.error is not None
        assert "exception" in result.error.lower()
        assert result.skill_name == request.skill_name
        assert result.correlation_id == request.correlation_id

    @pytest.mark.asyncio
    async def test_handle_skill_requested_parses_result_block(self) -> None:
        """A valid RESULT: block is parsed and reflected in the ModelSkillResult."""
        request = _make_request()
        polly_output = (
            "I executed the skill successfully.\nRESULT:\nstatus: success\nerror:\n"
        )
        dispatcher = AsyncMock(return_value=polly_output)

        result = await handle_skill_requested(request, task_dispatcher=dispatcher)

        assert result.status == SkillResultStatus.SUCCESS
        assert result.error is None
        assert result.output is not None
        assert "RESULT:" in result.output

    @pytest.mark.asyncio
    async def test_handle_skill_requested_partial_when_no_result_block(
        self,
    ) -> None:
        """Output missing the RESULT: block produces a PARTIAL result."""
        request = _make_request()
        dispatcher = AsyncMock(return_value="Done, but no structured block here.")

        result = await handle_skill_requested(request, task_dispatcher=dispatcher)

        assert result.status == SkillResultStatus.PARTIAL
        assert result.error is not None
        assert result.error == "No RESULT: block in output"

    @pytest.mark.asyncio
    async def test_handle_skill_requested_failed_status_from_result_block(
        self,
    ) -> None:
        """A RESULT: block with status: failed is returned as FAILED."""
        request = _make_request()
        polly_output = (
            "The skill failed to execute.\n"
            "RESULT:\n"
            "status: failed\n"
            "error: skill script exited with code 1\n"
        )
        dispatcher = AsyncMock(return_value=polly_output)

        result = await handle_skill_requested(request, task_dispatcher=dispatcher)

        assert result.status == SkillResultStatus.FAILED
        assert result.error == "skill script exited with code 1"

    @pytest.mark.asyncio
    async def test_handle_skill_requested_includes_args_in_prompt(self) -> None:
        """Args are serialized into the prompt dispatched to Polly."""
        request = _make_request(args={"verbose": "", "pr": "42"})
        output = "RESULT:\nstatus: success\nerror:\n"
        dispatcher = AsyncMock(return_value=output)

        await handle_skill_requested(request, task_dispatcher=dispatcher)

        prompt_arg: str = dispatcher.call_args[0][0]
        assert "--verbose" in prompt_arg
        assert "--pr 42" in prompt_arg

    @pytest.mark.asyncio
    async def test_handle_skill_requested_partial_for_unrecognized_status(
        self,
    ) -> None:
        """A RESULT: block with an unrecognized status value produces PARTIAL."""
        request = _make_request()
        polly_output = (
            "Skill execution finished.\nRESULT:\nstatus: in-progress\nerror:\n"
        )
        dispatcher = AsyncMock(return_value=polly_output)

        result = await handle_skill_requested(request, task_dispatcher=dispatcher)

        assert result.status == SkillResultStatus.PARTIAL

    @pytest.mark.asyncio
    async def test_trailing_status_and_error_after_blank_line_are_ignored(
        self,
    ) -> None:
        """status:/error: lines after a blank line must not overwrite the RESULT block.

        Verbose Polly output sometimes re-states status information after the
        RESULT block.  The parser must stop at the first blank line so those
        trailing lines do not corrupt the parsed values.
        """
        request = _make_request()
        # RESULT block says success / no error.
        # After a blank line there are rogue status: failed / error: trailing
        # lines that should be completely ignored.
        polly_output = (
            "I ran the skill.\n"
            "RESULT:\n"
            "status: success\n"
            "error:\n"
            "\n"
            "status: failed\n"
            "error: trailing noise from verbose output\n"
        )
        dispatcher = AsyncMock(return_value=polly_output)

        result = await handle_skill_requested(request, task_dispatcher=dispatcher)

        assert result.status == SkillResultStatus.SUCCESS
        assert result.error is None


# ---------------------------------------------------------------------------
# TestHandleSkillRequestedWithEventEmitter — OMN-2773 lifecycle event tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandleSkillRequestedWithEventEmitter:
    """Unit tests for skill lifecycle event emission (OMN-2773).

    Verifies that handle_skill_requested() emits skill.started and
    skill.completed events correctly via an injected event_emitter.
    """

    @pytest.mark.asyncio
    async def test_emits_started_before_dispatch(self) -> None:
        """skill.started must be emitted before task_dispatcher is called."""
        call_order: list[str] = []

        def mock_emitter(event_type: str, payload: dict[str, object]) -> bool:
            call_order.append(f"emit:{event_type}")
            return True

        async def mock_dispatcher(prompt: str) -> str:
            call_order.append("dispatch")
            return "RESULT:\nstatus: success\nerror:\n"

        request = _make_request()
        await handle_skill_requested(
            request,
            task_dispatcher=mock_dispatcher,
            event_emitter=mock_emitter,
        )

        started_idx = call_order.index("emit:skill.started")
        dispatch_idx = call_order.index("dispatch")
        assert started_idx < dispatch_idx, (
            "skill.started must be emitted before dispatch"
        )

    @pytest.mark.asyncio
    async def test_emits_completed_on_success(self) -> None:
        """skill.completed is emitted after successful dispatch."""
        emitted: list[tuple[str, dict[str, object]]] = []

        def mock_emitter(event_type: str, payload: dict[str, object]) -> bool:
            emitted.append((event_type, payload))
            return True

        request = _make_request()
        dispatcher = AsyncMock(return_value="RESULT:\nstatus: success\nerror:\n")

        await handle_skill_requested(
            request,
            task_dispatcher=dispatcher,
            event_emitter=mock_emitter,
        )

        event_types = [e[0] for e in emitted]
        assert "skill.started" in event_types
        assert "skill.completed" in event_types

        completed_payload = next(p for et, p in emitted if et == "skill.completed")
        assert completed_payload["status"] == "success"
        assert completed_payload["skill_name"] == request.skill_name

    @pytest.mark.asyncio
    async def test_emits_completed_on_dispatcher_exception(self) -> None:
        """skill.completed is emitted (status=failed) when task_dispatcher raises."""
        emitted: list[tuple[str, dict[str, object]]] = []

        def mock_emitter(event_type: str, payload: dict[str, object]) -> bool:
            emitted.append((event_type, payload))
            return True

        request = _make_request()
        dispatcher = AsyncMock(side_effect=RuntimeError("dispatch failed"))

        result = await handle_skill_requested(
            request,
            task_dispatcher=dispatcher,
            event_emitter=mock_emitter,
        )

        assert result.status == SkillResultStatus.FAILED
        event_types = [e[0] for e in emitted]
        assert "skill.completed" in event_types

        completed_payload = next(p for et, p in emitted if et == "skill.completed")
        assert completed_payload["status"] == "failed"
        assert completed_payload["error_type"] == "RuntimeError"

    @pytest.mark.asyncio
    async def test_no_emit_when_emitter_is_none(self) -> None:
        """When event_emitter is None, no emission occurs and existing behaviour is unchanged."""
        request = _make_request()
        dispatcher = AsyncMock(return_value="RESULT:\nstatus: success\nerror:\n")

        # Should not raise; existing callers pass no event_emitter
        result = await handle_skill_requested(request, task_dispatcher=dispatcher)

        assert result.status == SkillResultStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_emit_exception_does_not_propagate(self) -> None:
        """An exception in event_emitter must not propagate to the caller."""

        def raising_emitter(event_type: str, payload: dict[str, object]) -> bool:
            raise OSError("socket unavailable")

        request = _make_request()
        dispatcher = AsyncMock(return_value="RESULT:\nstatus: success\nerror:\n")

        # Must not raise despite emitter raising
        result = await handle_skill_requested(
            request,
            task_dispatcher=dispatcher,
            event_emitter=raising_emitter,
        )

        assert result.status == SkillResultStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_run_id_is_same_for_started_and_completed(self) -> None:
        """The run_id in skill.started and skill.completed must be identical (join key)."""
        emitted: list[tuple[str, dict[str, object]]] = []

        def mock_emitter(event_type: str, payload: dict[str, object]) -> bool:
            emitted.append((event_type, payload))
            return True

        request = _make_request()
        dispatcher = AsyncMock(return_value="RESULT:\nstatus: success\nerror:\n")

        await handle_skill_requested(
            request,
            task_dispatcher=dispatcher,
            event_emitter=mock_emitter,
        )

        started_payload = next(p for et, p in emitted if et == "skill.started")
        completed_payload = next(p for et, p in emitted if et == "skill.completed")
        assert started_payload["run_id"] == completed_payload["run_id"], (
            "run_id must be identical in both events (join key correctness)"
        )

    @pytest.mark.asyncio
    async def test_event_id_parses_as_uuid(self) -> None:
        """The event_id field in emitted payloads must be a valid UUID string."""
        emitted: list[tuple[str, dict[str, object]]] = []

        def mock_emitter(event_type: str, payload: dict[str, object]) -> bool:
            emitted.append((event_type, payload))
            return True

        request = _make_request()
        dispatcher = AsyncMock(return_value="RESULT:\nstatus: success\nerror:\n")

        await handle_skill_requested(
            request,
            task_dispatcher=dispatcher,
            event_emitter=mock_emitter,
        )

        for event_type, payload in emitted:
            event_id_val = payload.get("event_id")
            assert event_id_val is not None, f"{event_type} missing event_id"
            # Must be parseable as UUID (Pydantic serialises UUID as str in mode="json")
            UUID(str(event_id_val))

    @pytest.mark.asyncio
    async def test_payload_matches_model_schema(self) -> None:
        """Emitted payloads must match the ModelSkillStartedEvent / ModelSkillCompletedEvent schemas.

        Validates that the dicts emitted by the handler can be re-parsed by
        the Pydantic models, catching payload/model drift.
        """
        emitted: list[tuple[str, dict[str, object]]] = []

        def mock_emitter(event_type: str, payload: dict[str, object]) -> bool:
            emitted.append((event_type, payload))
            return True

        request = _make_request()
        dispatcher = AsyncMock(return_value="RESULT:\nstatus: success\nerror:\n")

        await handle_skill_requested(
            request,
            task_dispatcher=dispatcher,
            event_emitter=mock_emitter,
        )

        started_payload = next(p for et, p in emitted if et == "skill.started")
        completed_payload = next(p for et, p in emitted if et == "skill.completed")

        # Re-parse — should not raise
        ModelSkillStartedEvent.model_validate(started_payload)
        ModelSkillCompletedEvent.model_validate(completed_payload)

    @pytest.mark.asyncio
    async def test_duration_ms_is_non_negative(self) -> None:
        """The duration_ms in the completed event must be >= 0."""
        emitted: list[tuple[str, dict[str, object]]] = []

        def mock_emitter(event_type: str, payload: dict[str, object]) -> bool:
            emitted.append((event_type, payload))
            return True

        request = _make_request()
        dispatcher = AsyncMock(return_value="RESULT:\nstatus: success\nerror:\n")

        await handle_skill_requested(
            request,
            task_dispatcher=dispatcher,
            event_emitter=mock_emitter,
        )

        completed_payload = next(p for et, p in emitted if et == "skill.completed")
        duration = completed_payload.get("duration_ms")
        assert isinstance(duration, int), "duration_ms must be an int"
        assert duration >= 0, f"duration_ms must be non-negative, got {duration}"
