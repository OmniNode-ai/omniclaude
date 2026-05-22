# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for the delegate shim's market-owned contract boundary."""

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
    sys.modules.pop("handler_delegate_skill", None)
    import handler_delegate_skill as m  # noqa: PLC0415

    return importlib.reload(m)


def test_command_identity_points_at_market_delegate_skill(
    delegate_run: ModuleType,
) -> None:
    assert delegate_run._DELEGATION_COMMAND_NAME == "delegate_skill.orchestrate"
    assert delegate_run._DELEGATION_NODE_NAME == "node_delegate_skill_orchestrator"


def test_load_adapter_class_uses_market_adapter_when_available(
    delegate_run: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Adapter:
        pass

    monkeypatch.setattr(delegate_run, "DelegationDispatchAdapter", _Adapter)

    adapter_cls, error = delegate_run._load_adapter_class()

    assert adapter_cls is _Adapter
    assert error is None


def test_load_adapter_class_reports_import_error(
    delegate_run: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fail_import(name: str, *_args: object, **_kwargs: object) -> object:
        if name == "omnimarket.adapters.claude_code.delegate":
            raise ImportError("adapter unavailable")
        return original_import(name, *_args, **_kwargs)

    original_import = __import__
    monkeypatch.setattr("builtins.__import__", _fail_import)

    adapter_cls, error = delegate_run._load_adapter_class()

    assert adapter_cls is None
    assert isinstance(error, ImportError)
    assert "adapter unavailable" in str(error)


def test_runtime_task_type_maps_classifier_intents(
    delegate_run: ModuleType,
) -> None:
    assert delegate_run._resolve_runtime_task_type("test", "anything") == "test"
    assert delegate_run._resolve_runtime_task_type("document", "anything") == "document"
    assert delegate_run._resolve_runtime_task_type("research", "anything") == "research"
    assert (
        delegate_run._resolve_runtime_task_type("implement", "write unit tests")
        == "test"
    )
    assert (
        delegate_run._resolve_runtime_task_type("implement", "add README docs")
        == "document"
    )
    assert (
        delegate_run._resolve_runtime_task_type("implement", "analyze this module")
        == "research"
    )
