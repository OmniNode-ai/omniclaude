# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests verifying the delegate skill shim stays thin."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType

import pytest

_TESTS_DIR = Path(__file__).parent
_REPO_ROOT = _TESTS_DIR.parent.parent.parent.parent
_DELEGATE_LIB = _REPO_ROOT / "plugins" / "onex" / "skills" / "delegate" / "_lib"
_HANDLER_PATH = _DELEGATE_LIB / "handler_delegate_skill.py"

if _DELEGATE_LIB.exists() and str(_DELEGATE_LIB) not in sys.path:
    sys.path.insert(0, str(_DELEGATE_LIB))


@pytest.fixture
def delegate_run() -> ModuleType:
    sys.modules.pop("handler_delegate_skill", None)
    import handler_delegate_skill as m  # noqa: PLC0415

    return importlib.reload(m)


def test_delegate_handler_has_no_legacy_transport_tokens() -> None:
    source = _HANDLER_PATH.read_text(encoding="utf-8")
    forbidden = (
        "confluent_kafka",
        "urllib.request",
        "ssh",
        "pandaproxy",
        "InProcessDelegationRunner",
        "_call_llm_via_curl",
        "emit_event",
    )

    for token in forbidden:
        assert token not in source


def test_delegate_handler_has_no_legacy_dispatch_helpers() -> None:
    source = _HANDLER_PATH.read_text(encoding="utf-8")
    forbidden_helpers = (
        "_dispatch_via_",
        "_run_inprocess",
        "_resolve_transport_config",
        "_resolve_command_topic",
        "_DELEGATION_REQUEST_TOPIC",
        "_HAS_INPROCESS_RUNNER",
    )

    for helper in forbidden_helpers:
        assert helper not in source


def test_adapter_import_is_lazy(delegate_run: ModuleType) -> None:
    assert hasattr(delegate_run, "_load_adapter_class")
    assert delegate_run.DelegationDispatchAdapter is None


def test_no_runtime_transport_env_vars_read_at_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "KAFKA_BOOTSTRAP_SERVERS",
        "ONEX_RUNTIME_URL",
        "ONEX_PANDAPROXY_URL",
        "ONEX_RUNTIME_SSH_HOST",
        "LLM_CODER_URL",
        "LLM_DEEPSEEK_R1_URL",
    ):
        monkeypatch.delenv(name, raising=False)

    sys.modules.pop("handler_delegate_skill", None)
    import handler_delegate_skill as m  # noqa: PLC0415

    importlib.reload(m)
