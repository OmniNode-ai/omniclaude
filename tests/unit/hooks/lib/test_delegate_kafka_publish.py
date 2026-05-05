# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for /onex:delegate runtime ingress dispatch.

DoD evidence for OMN-10206:
- classify_and_publish() builds a ModelRuntimeSkillRequest for
  node_delegation_orchestrator whenever the intent is delegatable.
- The skill uses LocalRuntimeSkillClient, not emit_event or EmitClient.
- Recipient and wait options are threaded into the delegation payload for the
  runtime-owned Pattern B broker path.
"""

from __future__ import annotations

import importlib
import sys
import uuid
from pathlib import Path
from types import ModuleType

import pytest
from omnibase_core.models.dispatch import ModelDispatchBusTerminalResult
from omnibase_core.models.runtime import (
    ModelRuntimeSkillError,
    ModelRuntimeSkillResponse,
)

_TESTS_DIR = Path(__file__).parent
_REPO_ROOT = _TESTS_DIR.parent.parent.parent.parent
_DELEGATE_LIB = _REPO_ROOT / "plugins" / "onex" / "skills" / "delegate" / "_lib"

if _DELEGATE_LIB.exists() and str(_DELEGATE_LIB) not in sys.path:
    sys.path.insert(0, str(_DELEGATE_LIB))


class FakeRuntimeSkillClient:
    requests: list[object] = []
    response: ModelRuntimeSkillResponse = ModelRuntimeSkillResponse(
        ok=True,
        command_name="node_delegation_orchestrator",
        resolved_node_name="node_delegation_orchestrator",
        contract_name="node_delegation_orchestrator",
        command_topic="onex.cmd.omniclaude.delegate-task.v1",
        terminal_event="onex.evt.omniclaude.delegation-completed.v1",
        correlation_id=uuid.uuid4(),
        dispatch_result=ModelDispatchBusTerminalResult(
            status="completed",
            correlation_id=uuid.uuid4(),
            payload={"result": "queued"},
        ),
        output_payloads=[{"result": "queued"}],
    )

    def dispatch_sync(self, request: object) -> ModelRuntimeSkillResponse:
        self.requests.append(request)
        return self.response.model_copy(
            update={"correlation_id": request.correlation_id}
        )


@pytest.fixture(autouse=True)
def reset_fake_client() -> None:
    FakeRuntimeSkillClient.requests = []
    FakeRuntimeSkillClient.response = ModelRuntimeSkillResponse(
        ok=True,
        command_name="node_delegation_orchestrator",
        resolved_node_name="node_delegation_orchestrator",
        contract_name="node_delegation_orchestrator",
        command_topic="onex.cmd.omniclaude.delegate-task.v1",
        terminal_event="onex.evt.omniclaude.delegation-completed.v1",
        correlation_id=uuid.uuid4(),
        dispatch_result=ModelDispatchBusTerminalResult(
            status="completed",
            correlation_id=uuid.uuid4(),
            payload={"result": "queued"},
        ),
        output_payloads=[{"result": "queued"}],
    )


@pytest.fixture
def delegate_run() -> ModuleType:
    sys.modules.pop("run", None)
    import run as delegate_run_module  # noqa: PLC0415

    imported = importlib.reload(delegate_run_module)
    imported.LocalRuntimeSkillClient = FakeRuntimeSkillClient
    return imported


class TestDelegateRuntimeDispatch:
    def test_delegatable_prompt_dispatches_runtime_skill_request(
        self,
        delegate_run: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("CLAUDE_SESSION_ID", "session-test-123")
        prompt = "write unit tests for handler_event_emitter.py"

        result = delegate_run.classify_and_publish(
            prompt=prompt,
            source_file="src/omniclaude/hooks/handler_event_emitter.py",
            max_tokens=4096,
            recipient="codex",
            wait_for_result=True,
            working_directory="/tmp/work",
            codex_sandbox_mode="workspace-write",
        )

        assert result.get("success") is True, f"Expected success, got: {result}"
        assert result["command_name"] == "node_delegation_orchestrator"
        assert result["dispatch_status"] == "completed"

        assert len(FakeRuntimeSkillClient.requests) == 1
        request = FakeRuntimeSkillClient.requests[0]
        assert request.command_name == "node_delegation_orchestrator"
        assert request.correlation_id is not None

        payload = request.payload
        assert payload["prompt"] == prompt
        assert payload["session_id"] == "session-test-123"
        assert payload["prompt_length"] == len(prompt)
        assert payload["source_file_path"] == (
            "src/omniclaude/hooks/handler_event_emitter.py"
        )
        assert payload["max_tokens"] == 4096
        assert payload["recipient"] == "codex"
        assert payload["wait_for_result"] is True
        assert payload["working_directory"] == "/tmp/work"
        assert payload["codex_sandbox_mode"] == "workspace-write"

        from omniclaude.nodes.node_delegation_orchestrator.models.model_delegation_command import (
            ModelDelegationCommand,
        )

        command = ModelDelegationCommand.model_validate(payload)
        assert command.prompt == prompt

    def test_correlation_id_is_valid_uuid(self, delegate_run: ModuleType) -> None:
        result = delegate_run.classify_and_publish(
            prompt="document the routing architecture",
        )

        assert result.get("success") is True, f"Expected success, got: {result}"
        corr = result.get("correlation_id")
        assert corr is not None
        uuid.UUID(str(corr))

    def test_explicit_correlation_id_is_threaded_through(
        self, delegate_run: ModuleType
    ) -> None:
        expected_corr = str(uuid.uuid4())

        result = delegate_run.classify_and_publish(
            prompt="research and explain the delegation routing flow in detail",
            correlation_id=expected_corr,
        )

        assert result.get("success") is True, f"Expected success, got: {result}"
        assert result.get("correlation_id") == expected_corr
        request = FakeRuntimeSkillClient.requests[0]
        assert str(request.correlation_id) == expected_corr
        assert request.payload["correlation_id"] == expected_corr

    def test_non_delegatable_intent_does_not_dispatch(
        self, delegate_run: ModuleType
    ) -> None:
        result = delegate_run.classify_and_publish(
            prompt="debug the database connection failure",
        )

        assert FakeRuntimeSkillClient.requests == []
        assert result.get("success") is False

    def test_runtime_failure_returns_error_result(
        self, delegate_run: ModuleType
    ) -> None:
        FakeRuntimeSkillClient.response = ModelRuntimeSkillResponse(
            ok=False,
            command_name="node_delegation_orchestrator",
            correlation_id=uuid.uuid4(),
            error=ModelRuntimeSkillError(
                code="runtime_unavailable",
                message="runtime socket unavailable",
                retryable=True,
            ),
        )

        result = delegate_run.classify_and_publish(
            prompt="write unit tests for verify_registration.py",
        )

        assert result.get("success") is False
        assert result["error"] == "runtime socket unavailable"
        assert result["error_code"] == "runtime_unavailable"
        assert result["retryable"] is True
