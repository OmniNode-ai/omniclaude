# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for delegate skill --local in-process dispatch (restored in OMN-10604).

OMN-10723 removed the silent inprocess fallback. OMN-10604 restores an explicit
--local / force_local=True path that dispatches through InProcessDelegationRunner
with a curl-based LLM shim. These tests verify that wiring without hitting a
real LLM endpoint.

Non-delegatable intent rejection is tested here as well since it runs before
any dispatch attempt.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    from omnimarket.nodes.node_delegation_orchestrator.models.model_delegation_result import (
        ModelDelegationResult,
    )

# ---------------------------------------------------------------------------
# Make the delegate skill _lib module importable as `run`
# ---------------------------------------------------------------------------
_TESTS_DIR = Path(__file__).parent
_REPO_ROOT = _TESTS_DIR.parent.parent
_DELEGATE_LIB = _REPO_ROOT / "plugins" / "onex" / "skills" / "delegate" / "_lib"

if _DELEGATE_LIB.exists() and str(_DELEGATE_LIB) not in sys.path:
    sys.path.insert(0, str(_DELEGATE_LIB))


@pytest.fixture
def delegate_run_module() -> ModuleType:
    """Reload the delegate skill's run module fresh for each test."""
    sys.modules.pop("run", None)
    import importlib  # noqa: PLC0415

    import run as _run  # noqa: PLC0415

    return importlib.reload(_run)


def _make_fake_result(
    task_type: str = "test",
    correlation_id: uuid.UUID | None = None,
) -> ModelDelegationResult:
    """Build a fake ModelDelegationResult for unit tests."""
    from omnimarket.nodes.node_delegation_orchestrator.models.model_delegation_result import (  # noqa: PLC0415
        ModelDelegationResult,
    )

    cid = correlation_id or uuid.uuid4()
    return ModelDelegationResult(
        correlation_id=cid,
        task_type=task_type,
        model_used="cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit",
        endpoint_url="http://192.168.86.201:8000",  # onex-allow-internal-ip
        content="def test_foo(): assert True",
        quality_passed=True,
        quality_score=0.95,
        latency_ms=1234,
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        fallback_to_claude=False,
        failure_reason="",
    )


@pytest.mark.unit
class TestInprocessWiringEndToEnd:
    """OMN-10604: force_local dispatches through InProcessDelegationRunner."""

    def test_force_local_returns_inprocess_path(
        self,
        delegate_run_module: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """force_local=True returns path='inprocess', not an error."""
        monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path))

        fake_result = _make_fake_result()
        with patch(
            "omniclaude.delegation.inprocess_runner.InProcessDelegationRunner.run",  # fallback-removed
            return_value=fake_result,
        ):
            result = delegate_run_module.classify_and_publish(
                prompt="write unit tests for handler_event_emitter.py",
                source_file="src/foo.py",
                max_tokens=512,
                force_local=True,
            )

        assert result["path"] == "inprocess"

    def test_force_local_success_returns_content(
        self,
        delegate_run_module: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """force_local=True with mocked runner returns success=True and content."""
        monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path))

        fake_result = _make_fake_result()
        with patch(
            "omniclaude.delegation.inprocess_runner.InProcessDelegationRunner.run",  # fallback-removed
            return_value=fake_result,
        ):
            result = delegate_run_module.classify_and_publish(
                prompt="write unit tests for handler_event_emitter.py",
                force_local=True,
            )

        assert result["success"] is True
        assert result["content"] == "def test_foo(): assert True"
        assert result["task_type"] == "test"

    def test_force_local_returns_correlation_id(
        self,
        delegate_run_module: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """force_local result dict includes the caller-supplied correlation_id."""
        monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path))
        corr = str(uuid.uuid4())
        fake_result = _make_fake_result(correlation_id=uuid.UUID(corr))

        with patch(
            "omniclaude.delegation.inprocess_runner.InProcessDelegationRunner.run",  # fallback-removed
            return_value=fake_result,
        ):
            result = delegate_run_module.classify_and_publish(
                prompt="write unit tests for handler_event_emitter.py",
                force_local=True,
                correlation_id=corr,
            )

        assert result["correlation_id"] == corr

    def test_force_local_pipeline_failure_returns_error(
        self,
        delegate_run_module: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """When InProcessDelegationRunner raises, force_local returns success=False."""
        monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path))

        with patch(
            "omniclaude.delegation.inprocess_runner.InProcessDelegationRunner.run",  # fallback-removed
            side_effect=RuntimeError("LLM endpoint unreachable"),
        ):
            result = delegate_run_module.classify_and_publish(
                prompt="write unit tests for handler_event_emitter.py",
                force_local=True,
            )

        assert result["success"] is False
        assert "pipeline failed" in result["error"].lower()
        assert result["path"] == "inprocess"

    def test_force_local_writes_evidence_bundle_on_success(
        self,
        delegate_run_module: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """force_local=True on success writes an evidence bundle to ONEX_STATE_DIR."""
        monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path))

        fake_result = _make_fake_result()
        with patch(
            "omniclaude.delegation.inprocess_runner.InProcessDelegationRunner.run",  # fallback-removed
            return_value=fake_result,
        ):
            result = delegate_run_module.classify_and_publish(
                prompt="write unit tests for handler_event_emitter.py",
                force_local=True,
            )

        assert result["success"] is True
        bundle_path = result.get("evidence_bundle_path")
        if bundle_path is not None:
            assert Path(bundle_path).is_dir()

    def test_force_local_runner_is_accessible(
        self,
        delegate_run_module: ModuleType,
    ) -> None:
        """InProcessDelegationRunner must be importable via the skill module's flag."""
        assert hasattr(delegate_run_module, "_HAS_INPROCESS_RUNNER")
        assert delegate_run_module._HAS_INPROCESS_RUNNER is True

    def test_non_delegatable_intent_returns_error_no_bundle(
        self,
        delegate_run_module: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Intent rejection runs BEFORE the runner — no bundle should be written."""
        monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path))

        with patch(
            "omniclaude.delegation.inprocess_runner._call_llm",  # fallback-removed
        ) as mock_call:
            result = delegate_run_module.classify_and_publish(
                prompt="debug the broken database connection",
                force_local=True,
            )

        assert result["success"] is False
        assert "not delegatable" in result["error"]
        assert mock_call.call_count == 0
        bundles_dir = tmp_path / "delegation" / "bundles"
        assert not bundles_dir.exists() or not any(bundles_dir.iterdir())
