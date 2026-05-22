# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for /onex:delegate market-adapter dispatch."""

from __future__ import annotations

import importlib
import sys
import uuid
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

_TESTS_DIR = Path(__file__).parent
_REPO_ROOT = _TESTS_DIR.parent.parent.parent.parent
_DELEGATE_LIB = _REPO_ROOT / "plugins" / "onex" / "skills" / "delegate" / "_lib"
_DELEGATE_SKILL_COMMAND_NAME = "delegate_skill.orchestrate"
_DELEGATE_NODE_NAME = "node_delegate_skill_orchestrator"

if _DELEGATE_LIB.exists() and str(_DELEGATE_LIB) not in sys.path:
    sys.path.insert(0, str(_DELEGATE_LIB))


class _Intent:
    value = "test"


class _FakeClassifier:
    def classify(self, _prompt: str) -> SimpleNamespace:
        return SimpleNamespace(primary_intent=_Intent)


class _FakeAdapter:
    calls: list[dict[str, object]] = []
    response: dict[str, object] = {}

    def dispatch_sync(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        return {
            "ok": True,
            "correlation_id": str(kwargs["correlation_id"]),
            "command_topic": "onex.cmd.omnimarket.delegate-skill.v1",
            "terminal_events": {
                "success": "onex.evt.omnimarket.delegate-skill-completed.v1",
                "failure": "onex.evt.omnimarket.delegate-skill-failed.v1",
            },
            **self.response,
        }


@pytest.fixture
def delegate_run(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    sys.modules.pop("run", None)
    import run as delegate_run_module  # noqa: PLC0415

    imported = importlib.reload(delegate_run_module)
    _FakeAdapter.calls = []
    _FakeAdapter.response = {}
    monkeypatch.setattr(imported, "TaskClassifier", _FakeClassifier)
    monkeypatch.setattr(imported, "_HAS_CLASSIFIER", True)
    monkeypatch.setattr(imported, "DELEGATABLE", frozenset({_Intent}))
    monkeypatch.setattr(imported, "DelegationDispatchAdapter", _FakeAdapter)
    return imported


def test_delegatable_prompt_dispatches_market_adapter(
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
        timeout_ms=12345,
    )

    assert result.get("success") is True, f"Expected success, got: {result}"
    assert result["command_name"] == _DELEGATE_SKILL_COMMAND_NAME
    assert result["resolved_node_name"] == _DELEGATE_NODE_NAME
    assert result["path"] == "omnimarket_adapter"

    assert len(_FakeAdapter.calls) == 1
    call = _FakeAdapter.calls[0]
    assert call["prompt"] == prompt
    assert call["task_type"] == "test"
    assert call["source"] == "claude-code"
    assert call["cwd"] == "/tmp/work"
    assert call["wait"] is True
    assert call["max_tokens"] == 4096
    assert call["timeout_ms"] == 12345

    metadata = call["metadata"]
    assert isinstance(metadata, dict)
    assert metadata["source_file_path"] == (
        "src/omniclaude/hooks/handler_event_emitter.py"
    )
    assert metadata["session_id"] == "session-test-123"
    assert metadata["recipient"] == "codex"
    assert metadata["wait_for_result"] == "true"
    assert metadata["working_directory"] == "/tmp/work"
    assert metadata["codex_sandbox_mode"] == "workspace-write"


def test_explicit_correlation_id_is_threaded_through(delegate_run: ModuleType) -> None:
    expected_corr = str(uuid.uuid4())

    result = delegate_run.classify_and_publish(
        prompt="research and explain the delegation routing flow",
        correlation_id=expected_corr,
    )

    assert result.get("success") is True, f"Expected success, got: {result}"
    assert result.get("correlation_id") == expected_corr
    assert str(_FakeAdapter.calls[0]["correlation_id"]) == expected_corr


def test_non_delegatable_intent_does_not_dispatch(
    delegate_run: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _OtherIntent:
        value = "implement"

    class _OtherClassifier:
        def classify(self, _prompt: str) -> SimpleNamespace:
            return SimpleNamespace(primary_intent=_OtherIntent)

    monkeypatch.setattr(delegate_run, "TaskClassifier", _OtherClassifier)

    result = delegate_run.classify_and_publish(
        prompt="debug the database connection failure",
    )

    assert _FakeAdapter.calls == []
    assert result.get("success") is False
    assert "not delegatable" in result["error"]


def test_adapter_failure_returns_error_result(delegate_run: ModuleType) -> None:
    _FakeAdapter.response = {"ok": False, "error": "runtime unavailable"}

    result = delegate_run.classify_and_publish(
        prompt="write unit tests for verify_registration.py",
    )

    assert result.get("success") is False
    assert result["error"] == "runtime unavailable"


def test_missing_adapter_returns_explicit_error(
    delegate_run: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(delegate_run, "DelegationDispatchAdapter", None)
    monkeypatch.setattr(
        delegate_run,
        "_load_adapter_class",
        lambda: (None, ImportError("omnimarket missing")),
    )

    result = delegate_run.classify_and_publish(
        prompt="write unit tests for verify_registration.py",
    )

    assert result.get("success") is False
    assert "Market delegation adapter unavailable" in result["error"]
