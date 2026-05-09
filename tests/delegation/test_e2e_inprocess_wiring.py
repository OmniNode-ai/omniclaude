# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for delegate skill runtime-only dispatch (OMN-10723).

The in-process path (force_local=True) was removed in OMN-10723. These tests
verify the removal is complete: force_local returns an explicit error and the
runtime path is the only supported dispatch route.

Non-delegatable intent rejection is tested here as well since it runs before
any dispatch attempt and is not affected by the removal.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest

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


@pytest.mark.unit
class TestInprocessWiringEndToEnd:
    """OMN-10723: force_local returns explicit error; runtime is the only path."""

    def test_force_local_returns_error_not_success(
        self,
        delegate_run_module: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """force_local=True returns success=False, not in-process execution."""
        monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path))
        monkeypatch.setenv("LLM_CODER_URL", "http://test-backend.invalid:8000")

        result = delegate_run_module.classify_and_publish(
            prompt="write unit tests for handler_event_emitter.py",
            source_file="src/foo.py",
            max_tokens=512,
            force_local=True,
        )

        assert result["success"] is False
        assert "OMN-10723" in result["error"]
        assert "runtime" in result["error"].lower()

    def test_force_local_error_includes_socket_path(
        self,
        delegate_run_module: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Error message includes the resolved ONEX_LOCAL_RUNTIME_SOCKET_PATH value."""
        monkeypatch.setenv("ONEX_LOCAL_RUNTIME_SOCKET_PATH", "/tmp/onex-runtime.sock")

        result = delegate_run_module.classify_and_publish(
            prompt="write unit tests for handler_event_emitter.py",
            force_local=True,
        )

        assert result["success"] is False
        assert "/tmp/onex-runtime.sock" in result["error"]

    def test_force_local_error_shows_unset_when_socket_not_configured(
        self,
        delegate_run_module: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Error message includes <unset> when ONEX_LOCAL_RUNTIME_SOCKET_PATH is absent."""
        monkeypatch.delenv("ONEX_LOCAL_RUNTIME_SOCKET_PATH", raising=False)

        result = delegate_run_module.classify_and_publish(
            prompt="write unit tests for handler_event_emitter.py",
            force_local=True,
        )

        assert result["success"] is False
        assert "<unset>" in result["error"]

    def test_force_local_error_includes_correlation_id(
        self,
        delegate_run_module: ModuleType,
    ) -> None:
        """force_local error dict includes the caller-supplied correlation_id."""
        corr = str(uuid.uuid4())
        result = delegate_run_module.classify_and_publish(
            prompt="write unit tests for handler_event_emitter.py",
            force_local=True,
            correlation_id=corr,
        )

        assert result["success"] is False
        assert result.get("correlation_id") == corr

    def test_force_local_does_not_write_evidence_bundle(
        self,
        delegate_run_module: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """force_local=True returns before any bundle write — no artifacts on disk."""
        monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path))

        result = delegate_run_module.classify_and_publish(
            prompt="write unit tests for handler_event_emitter.py",
            force_local=True,
        )

        assert result["success"] is False
        bundles_dir = tmp_path / "delegation" / "bundles"
        assert not bundles_dir.exists() or not any(bundles_dir.iterdir())

    def test_no_inprocess_runner_attribute(
        self,
        delegate_run_module: ModuleType,
    ) -> None:
        """InProcessDelegationRunner must not be importable from the skill module."""
        assert not hasattr(delegate_run_module, "InProcessDelegationRunner")
        assert not hasattr(delegate_run_module, "_HAS_DELEGATION_RUNNER")
        assert not hasattr(delegate_run_module, "_inprocess_fallback")

    def test_non_delegatable_intent_returns_error_no_bundle(
        self,
        delegate_run_module: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Intent rejection runs BEFORE the runner — no bundle should be written."""
        monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path))

        with patch(
            "omniclaude.delegation.inprocess_runner._call_llm",
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
