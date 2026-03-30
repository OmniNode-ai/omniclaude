# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for local verifier (B) -- routes verification to local Qwen3-14B."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from omniclaude.verification.local_verifier import (
    EnumDispatchSurface,
    EnumVerdict,
    ModelLocalVerifierResult,
    build_local_verification_prompt,
    parse_verification_response,
    run_local_verification,
)
from omniclaude.verification.self_check import (
    EnumCheckType,
    ModelMechanicalCheck,
    ModelTaskContract,
)


@pytest.mark.unit
class TestBuildLocalVerificationPrompt:
    """Local verifier sends contract checks as structured prompt to local LLM."""

    def test_prompt_contains_task_id_and_checks(self) -> None:
        contract = ModelTaskContract(
            task_id="task-1",
            definition_of_done=[
                ModelMechanicalCheck(
                    criterion="Tests pass",
                    check="uv run pytest",
                    check_type=EnumCheckType.COMMAND_EXIT_0,
                )
            ],
        )
        prompt = build_local_verification_prompt(contract, self_check_passed=True)

        assert "task-1" in prompt
        assert "Tests pass" in prompt
        assert "PASS or FAIL" in prompt
        assert "advisory only" in prompt

    def test_prompt_reflects_self_check_fail(self) -> None:
        contract = ModelTaskContract(
            task_id="task-2",
            definition_of_done=[
                ModelMechanicalCheck(
                    criterion="File exists",
                    check="test -f output.txt",
                    check_type=EnumCheckType.FILE_EXISTS,
                )
            ],
        )
        prompt = build_local_verification_prompt(contract, self_check_passed=False)

        assert "Self-check reported: FAIL" in prompt
        assert "task-2" in prompt


@pytest.mark.unit
class TestParseVerificationResponse:
    """Parse local LLM response into typed verification result."""

    def test_pass_response(self) -> None:
        raw = json.dumps(
            {
                "passed": True,
                "checks": [{"criterion": "Tests pass", "status": "PASS"}],
            }
        )
        result = parse_verification_response(raw, task_id="task-1")

        assert isinstance(result, ModelLocalVerifierResult)
        assert result.passed is True
        assert result.verdict == EnumVerdict.PASS
        assert len(result.checks) == 1
        assert result.checks[0].criterion == "Tests pass"
        assert result.checks[0].status == "PASS"
        assert result.dispatch_surface == EnumDispatchSurface.LOCAL_LLM

    def test_fail_response(self) -> None:
        raw = json.dumps(
            {
                "passed": False,
                "checks": [{"criterion": "Tests pass", "status": "FAIL"}],
            }
        )
        result = parse_verification_response(raw, task_id="task-1")

        assert result.passed is False
        assert result.verdict == EnumVerdict.FAIL

    def test_empty_checks_returns_insufficient_evidence(self) -> None:
        raw = json.dumps({"passed": False, "checks": []})
        result = parse_verification_response(raw, task_id="task-1")

        assert result.verdict == EnumVerdict.INSUFFICIENT_EVIDENCE

    def test_invalid_json_returns_insufficient_evidence(self) -> None:
        result = parse_verification_response("not json", task_id="task-1")

        assert result.verdict == EnumVerdict.INSUFFICIENT_EVIDENCE
        assert result.passed is False
        assert result.raw_response == "not json"


@pytest.mark.unit
class TestRunLocalVerification:
    """Integration test for async verification runner."""

    @pytest.mark.asyncio
    async def test_successful_verification(self) -> None:
        llm_response = json.dumps(
            {
                "passed": True,
                "checks": [{"criterion": "Tests pass", "status": "PASS"}],
            }
        )
        mock_response = httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": llm_response}}],
            },
            request=httpx.Request("POST", "http://test:8001/v1/chat/completions"),
        )

        contract = ModelTaskContract(
            task_id="task-1",
            definition_of_done=[
                ModelMechanicalCheck(
                    criterion="Tests pass",
                    check="uv run pytest",
                    check_type=EnumCheckType.COMMAND_EXIT_0,
                )
            ],
        )

        with patch(
            "omniclaude.verification.local_verifier.httpx.AsyncClient"
        ) as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await run_local_verification(
                contract, self_check_passed=True, endpoint_url="http://test:8001"
            )

        assert result.passed is True
        assert result.verdict == EnumVerdict.PASS
        assert result.is_fallback is False

    @pytest.mark.asyncio
    async def test_unreachable_llm_returns_fallback(self) -> None:
        contract = ModelTaskContract(
            task_id="task-1",
            definition_of_done=[
                ModelMechanicalCheck(
                    criterion="Tests pass",
                    check="uv run pytest",
                    check_type=EnumCheckType.COMMAND_EXIT_0,
                )
            ],
        )

        with patch(
            "omniclaude.verification.local_verifier.httpx.AsyncClient"
        ) as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = httpx.ConnectError("Connection refused")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await run_local_verification(
                contract, self_check_passed=True, endpoint_url="http://test:8001"
            )

        assert result.is_fallback is True
        assert result.attempted_route == EnumDispatchSurface.LOCAL_LLM
        assert result.actual_route == EnumDispatchSurface.CLAUDE_CODE
        assert result.verdict == EnumVerdict.INSUFFICIENT_EVIDENCE
