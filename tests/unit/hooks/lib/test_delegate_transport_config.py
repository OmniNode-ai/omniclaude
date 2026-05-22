# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for legacy /onex:delegate option mapping."""

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


def test_build_metadata_preserves_legacy_cli_options(
    delegate_run: ModuleType,
) -> None:
    metadata = delegate_run._build_metadata(
        source_file="src/example.py",
        session_id="session-1",
        recipient="codex",
        wait_for_result=True,
        working_directory="/tmp/work",
        codex_sandbox_mode="workspace-write",
        timeout_ms=12345,
    )

    assert metadata == {
        "adapter": "omniclaude.delegate-skill",
        "session_id": "session-1",
        "recipient": "codex",
        "wait_for_result": "true",
        "timeout_ms": "12345",
        "source_file_path": "src/example.py",
        "working_directory": "/tmp/work",
        "codex_sandbox_mode": "workspace-write",
    }


def test_build_metadata_omits_absent_optional_values(delegate_run: ModuleType) -> None:
    metadata = delegate_run._build_metadata(
        source_file=None,
        session_id="",
        recipient="auto",
        wait_for_result=False,
        working_directory=None,
        codex_sandbox_mode=None,
        timeout_ms=300000,
    )

    assert metadata == {
        "adapter": "omniclaude.delegate-skill",
        "session_id": "",
        "recipient": "auto",
        "wait_for_result": "false",
        "timeout_ms": "300000",
    }


def test_result_normalization_preserves_adapter_fields(
    delegate_run: ModuleType,
) -> None:
    result = delegate_run._normalize_adapter_result(
        {
            "ok": True,
            "correlation_id": "11111111-1111-1111-1111-111111111111",
            "command_topic": "onex.cmd.omnimarket.delegate-skill.v1",
        },
        correlation_id="22222222-2222-2222-2222-222222222222",
        task_type="test",
    )

    assert result["success"] is True
    assert result["ok"] is True
    assert result["correlation_id"] == "11111111-1111-1111-1111-111111111111"
    assert result["command_topic"] == "onex.cmd.omnimarket.delegate-skill.v1"
    assert result["command_name"] == "delegate_skill.orchestrate"
    assert result["resolved_node_name"] == "node_delegate_skill_orchestrator"
    assert result["path"] == "omnimarket_adapter"
    assert result["task_type"] == "test"
