# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for /onex:delegate dispatch behavior.

Verifies that:
- force_local=True uses the explicit in-process local path
- Market adapter unavailability returns explicit error
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


class TestDelegateDispatch:
    def test_force_local_returns_explicit_pipeline_error(
        self,
        delegate_run: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """OMN-10604: --local errors are reported from the explicit local path."""
        monkeypatch.setattr(
            delegate_run.InProcessDelegationRunner,
            "run",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("routing unavailable")
            ),
        )

        result = delegate_run.classify_and_publish(
            prompt="write unit tests for handler_event_emitter.py",
            force_local=True,
        )

        assert result.get("success") is False
        assert result.get("path") == "inprocess"
        assert "In-process delegation pipeline failed" in result["error"]
        assert "routing unavailable" in result["error"]

    def test_force_local_error_includes_correlation_id(
        self,
        delegate_run: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            delegate_run.InProcessDelegationRunner,
            "run",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("routing unavailable")
            ),
        )

        corr = str(uuid.uuid4())
        result = delegate_run.classify_and_publish(
            prompt="write unit tests for handler_event_emitter.py",
            force_local=True,
            correlation_id=corr,
        )

        assert result.get("success") is False
        assert result.get("correlation_id") == corr
        assert result.get("path") == "inprocess"

    def test_market_adapter_import_error_returns_explicit_error(
        self,
        delegate_run: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Market adapter unavailable → explicit error, no silent fallback."""
        monkeypatch.setattr(delegate_run, "_HAS_MARKET_ADAPTER", False)
        monkeypatch.setattr(
            delegate_run,
            "_MARKET_ADAPTER_IMPORT_ERROR",
            ImportError("omnimarket not installed"),
        )

        result = delegate_run.classify_and_publish(
            prompt="write unit tests for handler_event_emitter.py",
        )

        assert result.get("success") is False
        assert "omnimarket not installed" in result["error"]
        assert result.get("path") == "market_adapter"

    def test_non_delegatable_intent_rejected(
        self,
        delegate_run: ModuleType,
    ) -> None:
        result = delegate_run.classify_and_publish(
            prompt="debug the database connection failure",
        )

        assert result.get("success") is False
        assert "not delegatable" in result["error"]

    def test_inprocess_runner_attribute_available(
        self,
        delegate_run: ModuleType,
    ) -> None:
        """The explicit local path exposes the in-process runner, not fallback hooks."""
        assert hasattr(delegate_run, "InProcessDelegationRunner")
        assert delegate_run._HAS_INPROCESS_RUNNER is True
        assert not hasattr(delegate_run, "_HAS_DELEGATION_RUNNER")
        assert not hasattr(delegate_run, "_inprocess_fallback")
