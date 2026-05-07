# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for /onex:delegate in-process DelegationRunner fallback.

DoD evidence for OMN-10640:
- classify_and_publish() falls back to DelegationRunner when runtime client
  raises an exception (socket unavailable, connection refused, import error).
- force_local=True bypasses the runtime attempt entirely.
- The fallback returns a result dict with path="inprocess" and the same
  success/correlation_id/task_type keys as the runtime path.
- When DelegationRunner is unavailable, fallback returns success=False.
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

if _DELEGATE_LIB.exists() and str(_DELEGATE_LIB) not in sys.path:
    sys.path.insert(0, str(_DELEGATE_LIB))


class FakeDelegationResult:
    def __init__(self, correlation_id: uuid.UUID) -> None:
        self.correlation_id = correlation_id
        self.task_type = "test"
        self.model_used = "local-model"
        self.endpoint_url = (
            "http://192.168.86.201:8000"  # onex-allow-internal-ip  # kafka-fallback-ok
        )
        self.content = "Here are the tests..."
        self.quality_passed = True
        self.quality_score = 0.95
        self.latency_ms = 1234
        self.prompt_tokens = 100
        self.completion_tokens = 200
        self.total_tokens = 300
        self.fallback_to_claude = False
        self.failure_reason = ""


class FakeDelegationRunner:
    calls: list[dict] = []
    result_correlation_id: uuid.UUID = uuid.uuid4()
    should_raise: bool = False
    raise_message: str = ""

    def run(
        self, *, task_type: str, prompt: str, **kwargs: object
    ) -> FakeDelegationResult:
        self.calls.append({"task_type": task_type, "prompt": prompt, **kwargs})
        if self.should_raise:
            raise Exception(self.raise_message)
        return FakeDelegationResult(self.result_correlation_id)


@pytest.fixture(autouse=True)
def reset_fake_runner() -> None:
    FakeDelegationRunner.calls = []
    FakeDelegationRunner.result_correlation_id = uuid.uuid4()
    FakeDelegationRunner.should_raise = False
    FakeDelegationRunner.raise_message = ""


@pytest.fixture
def delegate_run_with_runner(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    sys.modules.pop("run", None)
    import run as delegate_run_module  # noqa: PLC0415

    imported = importlib.reload(delegate_run_module)

    fake_runner_instance = FakeDelegationRunner()
    monkeypatch.setattr(imported, "_HAS_DELEGATION_RUNNER", True)
    monkeypatch.setattr(
        imported, "InProcessDelegationRunner", lambda: fake_runner_instance
    )
    return imported


@pytest.fixture
def delegate_run_no_runner(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    sys.modules.pop("run", None)
    import run as delegate_run_module  # noqa: PLC0415

    imported = importlib.reload(delegate_run_module)
    monkeypatch.setattr(imported, "_HAS_DELEGATION_RUNNER", False)
    monkeypatch.setattr(imported, "InProcessDelegationRunner", None)
    return imported


class TestDelegateInprocessFallback:
    def test_force_local_bypasses_runtime(
        self,
        delegate_run_with_runner: ModuleType,
    ) -> None:
        result = delegate_run_with_runner.classify_and_publish(
            prompt="write unit tests for handler_event_emitter.py",
            force_local=True,
        )

        assert result.get("success") is True, f"Expected success, got: {result}"
        assert result["path"] == "inprocess"
        assert result["task_type"] == "test"

    def test_force_local_returns_runner_fields(
        self,
        delegate_run_with_runner: ModuleType,
    ) -> None:
        result = delegate_run_with_runner.classify_and_publish(
            prompt="write unit tests for handler_event_emitter.py",
            source_file="src/foo.py",
            max_tokens=1024,
            force_local=True,
        )

        assert result.get("success") is True
        assert "model_used" in result
        assert "quality_passed" in result
        assert "latency_ms" in result
        assert "prompt_tokens" in result
        assert "completion_tokens" in result
        assert "total_tokens" in result
        assert result["quality_passed"] is True

    def test_runtime_exception_triggers_inprocess_fallback(
        self,
        delegate_run_with_runner: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def _bad_client() -> None:
            raise ConnectionRefusedError("socket unavailable")

        monkeypatch.setattr(
            delegate_run_with_runner, "LocalRuntimeSkillClient", _bad_client
        )
        monkeypatch.setattr(delegate_run_with_runner, "_RUNTIME_IMPORT_ERROR", None)

        result = delegate_run_with_runner.classify_and_publish(
            prompt="write unit tests for handler_event_emitter.py",
        )

        assert result.get("success") is True, (
            f"Expected fallback success, got: {result}"
        )
        assert result["path"] == "inprocess"

    def test_runtime_import_error_triggers_inprocess_fallback(
        self,
        delegate_run_with_runner: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            delegate_run_with_runner,
            "_RUNTIME_IMPORT_ERROR",
            ImportError("omnibase_infra not installed"),
        )
        monkeypatch.setattr(delegate_run_with_runner, "ModelRuntimeSkillRequest", None)
        monkeypatch.setattr(delegate_run_with_runner, "LocalRuntimeSkillClient", None)

        result = delegate_run_with_runner.classify_and_publish(
            prompt="write unit tests for handler_event_emitter.py",
        )

        assert result.get("success") is True, (
            f"Expected fallback success, got: {result}"
        )
        assert result["path"] == "inprocess"

    def test_inprocess_unavailable_returns_error(
        self,
        delegate_run_no_runner: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            delegate_run_no_runner,
            "_RUNTIME_IMPORT_ERROR",
            ImportError("omnibase_infra not installed"),
        )
        monkeypatch.setattr(delegate_run_no_runner, "ModelRuntimeSkillRequest", None)
        monkeypatch.setattr(delegate_run_no_runner, "LocalRuntimeSkillClient", None)

        result = delegate_run_no_runner.classify_and_publish(
            prompt="write unit tests for handler_event_emitter.py",
        )

        assert result.get("success") is False
        assert "InProcessDelegationRunner unavailable" in result["error"]

    def test_correlation_id_propagates_in_inprocess_path(
        self,
        delegate_run_with_runner: ModuleType,
    ) -> None:
        expected_corr = str(uuid.uuid4())

        result = delegate_run_with_runner.classify_and_publish(
            prompt="write unit tests for handler_event_emitter.py",
            correlation_id=expected_corr,
            force_local=True,
        )

        assert result.get("success") is True
        assert result["path"] == "inprocess"
        assert result["correlation_id"] is not None
        uuid.UUID(result["correlation_id"])

    def test_non_delegatable_intent_still_rejected(
        self,
        delegate_run_with_runner: ModuleType,
    ) -> None:
        result = delegate_run_with_runner.classify_and_publish(
            prompt="debug the database connection failure",
            force_local=True,
        )

        assert result.get("success") is False
        assert "not delegatable" in result["error"]

    def test_runner_error_returns_failure(
        self,
        delegate_run_with_runner: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def _failing_runner() -> FakeDelegationRunner:
            r = FakeDelegationRunner()
            r.should_raise = True
            r.raise_message = "routing failed: no endpoint configured"
            return r

        monkeypatch.setattr(
            delegate_run_with_runner, "InProcessDelegationRunner", _failing_runner
        )

        result = delegate_run_with_runner.classify_and_publish(
            prompt="write unit tests for handler_event_emitter.py",
            force_local=True,
        )

        assert result.get("success") is False
        assert "routing failed" in result["error"]
        assert result["path"] == "inprocess"

    def test_evidence_bundle_written_when_state_dir_set(
        self,
        delegate_run_with_runner: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """ONEX_STATE_DIR set → fallback writes the 5-artifact evidence bundle."""
        if not getattr(delegate_run_with_runner, "_HAS_EVIDENCE_BUNDLE", False):
            pytest.skip("evidence_bundle module not importable in this venv")

        monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path))

        result = delegate_run_with_runner.classify_and_publish(
            prompt="write unit tests for handler_event_emitter.py",
            force_local=True,
        )

        assert result.get("success") is True
        bundle_path = result.get("evidence_bundle_path")
        assert bundle_path is not None, f"expected bundle path, got result={result}"
        bundle_dir = Path(bundle_path)
        assert bundle_dir.is_dir()
        names = {p.name for p in bundle_dir.iterdir()}
        assert names == {
            "bifrost_response.json",
            "cost_event.json",
            "quality_gate_result.json",
            "receipt.json",
            "run_manifest.json",
        }, f"unexpected artifacts: {names}"

    def test_no_bundle_when_state_dir_unset(
        self,
        delegate_run_with_runner: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """ONEX_STATE_DIR unset → fallback returns evidence_bundle_path=None."""
        monkeypatch.delenv("ONEX_STATE_DIR", raising=False)

        result = delegate_run_with_runner.classify_and_publish(
            prompt="write unit tests for handler_event_emitter.py",
            force_local=True,
        )

        assert result.get("success") is True
        assert result.get("evidence_bundle_path") is None
