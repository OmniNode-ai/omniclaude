# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for /onex:delegate market adapter dispatch.

DoD evidence for OMN-11638:
- classify_and_publish() dispatches through DelegationDispatchAdapter.
- The shim passes prompt, task_type, source, correlation_id, max_tokens, wait,
  and cwd to DelegationDispatchAdapter.dispatch_sync.
- Correlation ID is round-tripped correctly.
- Non-delegatable intents are rejected before dispatch.
- Dispatch failure is surfaced clearly.
"""

from __future__ import annotations

import importlib
import sys
import uuid
from pathlib import Path
from types import ModuleType

import pytest

_TESTS_DIR = Path(__file__).parent
_REPO_ROOT = _TESTS_DIR.parent.parent.parent.parent
_DELEGATE_LIB = _REPO_ROOT / "plugins" / "onex" / "skills" / "delegate" / "_lib"
_DELEGATE_SKILL_COMMAND_NAME = "node_delegate_skill_orchestrator"

if _DELEGATE_LIB.exists() and str(_DELEGATE_LIB) not in sys.path:
    sys.path.insert(0, str(_DELEGATE_LIB))

_FAKE_TOPIC = "onex.cmd.omnimarket.delegate-skill.v1"


class FakeDispatchAdapter:
    calls: list[dict] = []  # type: ignore[type-arg]
    response: dict = {  # type: ignore[type-arg]
        "ok": True,
        "correlation_id": str(uuid.uuid4()),
        "command_topic": _FAKE_TOPIC,
        "terminal_events": {
            "success": "onex.evt.omnimarket.delegate-skill-completed.v1",
            "failure": "onex.evt.omnimarket.delegate-skill-failed.v1",
        },
        "status": "published",
    }

    def __init__(self, contract_path: object = None) -> None:
        pass

    def dispatch_sync(self, **kwargs: object) -> dict:  # type: ignore[type-arg]
        FakeDispatchAdapter.calls.append(dict(kwargs))
        return FakeDispatchAdapter.response


@pytest.fixture(autouse=True)
def reset_fake_adapter() -> None:
    FakeDispatchAdapter.calls = []
    FakeDispatchAdapter.response = {
        "ok": True,
        "correlation_id": str(uuid.uuid4()),
        "command_topic": _FAKE_TOPIC,
        "terminal_events": {
            "success": "onex.evt.omnimarket.delegate-skill-completed.v1",
            "failure": "onex.evt.omnimarket.delegate-skill-failed.v1",
        },
        "status": "published",
    }


@pytest.fixture
def delegate_run(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    sys.modules.pop("run", None)
    import run as delegate_run_module  # noqa: PLC0415

    imported = importlib.reload(delegate_run_module)

    monkeypatch.setattr(imported, "DelegationDispatchAdapter", FakeDispatchAdapter)
    monkeypatch.setattr(imported, "_HAS_MARKET_ADAPTER", True)
    monkeypatch.setattr(imported, "_MARKET_ADAPTER_IMPORT_ERROR", None)
    return imported


class TestDelegateMarketAdapterDispatch:
    def test_delegatable_prompt_dispatches_via_market_adapter(
        self,
        delegate_run: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("ONEX_SESSION_ID", "session-test-123")
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
        assert result.get("path") == "market_adapter"
        assert result.get("command_name") == _DELEGATE_SKILL_COMMAND_NAME

        assert len(FakeDispatchAdapter.calls) == 1
        call = FakeDispatchAdapter.calls[0]
        assert call["prompt"] == prompt
        assert call["task_type"] == "test"
        assert call["source"] == "codex"
        assert call["max_tokens"] == 4096
        assert call["wait"] is True
        assert call["cwd"] == "/tmp/work"
        assert "correlation_id" in call

    def test_correlation_id_is_valid_uuid(self, delegate_run: ModuleType) -> None:
        corr = str(uuid.uuid4())
        FakeDispatchAdapter.response = {
            **FakeDispatchAdapter.response,
            "correlation_id": corr,
        }

        result = delegate_run.classify_and_publish(
            prompt="document the routing architecture",
            correlation_id=corr,
        )

        assert result.get("success") is True, f"Expected success, got: {result}"
        assert result.get("correlation_id") == corr
        uuid.UUID(str(result["correlation_id"]))

    def test_explicit_correlation_id_is_threaded_through(
        self, delegate_run: ModuleType
    ) -> None:
        expected_corr = str(uuid.uuid4())
        FakeDispatchAdapter.response = {
            **FakeDispatchAdapter.response,
            "correlation_id": expected_corr,
        }

        result = delegate_run.classify_and_publish(
            prompt="research and explain the delegation routing flow in detail",
            correlation_id=expected_corr,
        )

        assert result.get("success") is True, f"Expected success, got: {result}"
        assert result.get("correlation_id") == expected_corr

        call = FakeDispatchAdapter.calls[0]
        assert str(call["correlation_id"]) == expected_corr

    def test_non_delegatable_intent_does_not_dispatch(
        self, delegate_run: ModuleType
    ) -> None:
        result = delegate_run.classify_and_publish(
            prompt="debug the database connection failure",
        )

        assert FakeDispatchAdapter.calls == []
        assert result.get("success") is False

    def test_adapter_failure_returns_error_result(
        self, delegate_run: ModuleType
    ) -> None:
        FakeDispatchAdapter.response = {
            "ok": False,
            "error": "runtime socket unavailable",
            "correlation_id": str(uuid.uuid4()),
        }

        result = delegate_run.classify_and_publish(
            prompt="write unit tests for verify_registration.py",
        )

        assert result.get("success") is False
        assert "runtime socket unavailable" in result["error"]
        assert result.get("path") == "market_adapter"

    def test_auto_recipient_maps_to_claude_code_source(
        self, delegate_run: ModuleType
    ) -> None:
        delegate_run.classify_and_publish(
            prompt="write unit tests for handler_event_emitter.py",
            recipient="auto",
        )

        assert len(FakeDispatchAdapter.calls) == 1
        assert FakeDispatchAdapter.calls[0]["source"] == "claude-code"
