# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Regression tests for removing skill-local delegate execution paths."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType

import pytest

_TESTS_DIR = Path(__file__).parent
_REPO_ROOT = _TESTS_DIR.parent.parent.parent.parent
_DELEGATE_LIB = _REPO_ROOT / "plugins" / "onex" / "skills" / "delegate" / "_lib"

if _DELEGATE_LIB.exists() and str(_DELEGATE_LIB) not in sys.path:
    sys.path.insert(0, str(_DELEGATE_LIB))


@pytest.fixture
def delegate_run() -> ModuleType:
    sys.modules.pop("run", None)
    import run as delegate_run_module  # noqa: PLC0415

    return importlib.reload(delegate_run_module)


def test_classify_and_publish_no_longer_accepts_force_local(
    delegate_run: ModuleType,
) -> None:
    with pytest.raises(TypeError):
        delegate_run.classify_and_publish(
            prompt="write unit tests for handler_event_emitter.py",
            force_local=True,
        )


def test_inprocess_runner_symbols_are_absent(delegate_run: ModuleType) -> None:
    assert not hasattr(delegate_run, "InProcessDelegationRunner")
    assert not hasattr(delegate_run, "_HAS_INPROCESS_RUNNER")
    assert not hasattr(delegate_run, "_run_inprocess")


def test_invalid_timeout_fails_before_adapter_load(delegate_run: ModuleType) -> None:
    result = delegate_run.classify_and_publish(
        prompt="write unit tests for handler_event_emitter.py",
        timeout_ms=0,
    )

    assert result.get("success") is False
    assert "timeout_ms must be positive" in result["error"]


def test_invalid_max_tokens_fails_before_adapter_load(delegate_run: ModuleType) -> None:
    result = delegate_run.classify_and_publish(
        prompt="write unit tests for handler_event_emitter.py",
        max_tokens=0,
    )

    assert result.get("success") is False
    assert "max_tokens must be positive" in result["error"]
