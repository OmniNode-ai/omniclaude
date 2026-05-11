# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for /onex:delegate runtime-only dispatch (OMN-10723).

Verifies that:
- force_local=True returns an explicit error (inprocess fallback removed)
- Runtime socket failure returns explicit error, no silent fallback
- Runtime import error returns explicit error
- Non-delegatable intents are still rejected before any dispatch attempt
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


@pytest.fixture
def delegate_run(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    sys.modules.pop("run", None)
    import run as delegate_run_module  # noqa: PLC0415

    return importlib.reload(delegate_run_module)


class TestDelegateRuntimeOnly:
    def test_force_local_returns_explicit_error(
        self,
        delegate_run: ModuleType,
    ) -> None:
        """OMN-10723: --local flag returns error, not silent in-process execution."""
        result = delegate_run.classify_and_publish(
            prompt="write unit tests for handler_event_emitter.py",
            force_local=True,
        )

        assert result.get("success") is False
        assert "OMN-10723" in result["error"]
        assert "runtime" in result["error"].lower()

    def test_force_local_error_includes_correlation_id(
        self,
        delegate_run: ModuleType,
    ) -> None:
        corr = str(uuid.uuid4())
        result = delegate_run.classify_and_publish(
            prompt="write unit tests for handler_event_emitter.py",
            force_local=True,
            correlation_id=corr,
        )

        assert result.get("success") is False
        assert result.get("correlation_id") == corr

    def test_runtime_socket_failure_returns_explicit_error(
        self,
        delegate_run: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """SSH socket failure → explicit error, no silent fallback."""
        monkeypatch.setenv("ONEX_RUNTIME_SSH_HOST", "user@testhost")
        monkeypatch.setenv("ONEX_RUNTIME_SOCKET_PATH", "/tmp/onex.sock")

        def _bad_ssh_dispatch(
            payload_json: str,
            ssh_host: str,
            socket_path: str,
            timeout_seconds: float,
        ) -> dict:  # type: ignore[type-arg]
            raise OSError("socket unavailable")

        monkeypatch.setattr(delegate_run, "_dispatch_via_ssh_socket", _bad_ssh_dispatch)

        result = delegate_run.classify_and_publish(
            prompt="write unit tests for handler_event_emitter.py",
        )

        assert result.get("success") is False
        assert "socket unavailable" in result["error"]
        assert result.get("path") == "ssh"

    def test_runtime_import_error_returns_explicit_error(
        self,
        delegate_run: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """HTTP path import error → explicit error, no silent fallback."""
        monkeypatch.setenv("ONEX_RUNTIME_URL", "http://localhost:8085")
        monkeypatch.setattr(
            delegate_run,
            "_RUNTIME_IMPORT_ERROR",
            ImportError("omnibase_infra not installed"),
        )
        monkeypatch.setattr(delegate_run, "ModelRuntimeSkillRequest", None)
        monkeypatch.setattr(delegate_run, "LocalRuntimeSkillClient", None)

        result = delegate_run.classify_and_publish(
            prompt="write unit tests for handler_event_emitter.py",
        )

        assert result.get("success") is False
        assert "omnibase_infra not installed" in result["error"]

    def test_non_delegatable_intent_rejected(
        self,
        delegate_run: ModuleType,
    ) -> None:
        result = delegate_run.classify_and_publish(
            prompt="debug the database connection failure",
        )

        assert result.get("success") is False
        assert "not delegatable" in result["error"]

    def test_no_inprocess_runner_attribute(
        self,
        delegate_run: ModuleType,
    ) -> None:
        """InProcessDelegationRunner must not be importable from the skill module."""
        assert not hasattr(delegate_run, "InProcessDelegationRunner")
        assert not hasattr(delegate_run, "_HAS_DELEGATION_RUNNER")
        assert not hasattr(delegate_run, "_inprocess_fallback")
