# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Unit tests for handler_skill_requested.py.

Covers (10 required tests):
- test_build_args_string_bare_flag_for_empty_value
- test_build_args_string_bare_flag_for_true_value
- test_build_args_string_key_value_pair
- test_build_args_string_mixed
- test_build_args_string_empty_dict
- test_handle_skill_requested_dispatches_polly_with_skill_path
- test_handle_skill_requested_returns_failure_on_exception
- test_handle_skill_requested_parses_result_block
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from omniclaude.nodes.shared.handler_skill_requested import (
    _build_args_string,
    handle_skill_requested,
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
