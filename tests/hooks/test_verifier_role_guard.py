# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for verifier_role_guard.py (OMN-8925)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_lib_path = str(
    Path(__file__).parent.parent.parent / "plugins" / "onex" / "hooks" / "lib"
)
if _lib_path not in sys.path:
    sys.path.insert(0, _lib_path)

from verifier_role_guard import check_agent_is_verifier


def _write_yaml(agents_dir: Path, filename: str, content: str) -> Path:
    f = agents_dir / filename
    f.write_text(content)
    return f


@pytest.mark.unit
def test_non_verifier_agent_passes(tmp_path: Path) -> None:
    _write_yaml(
        tmp_path,
        "agent-worker.yaml",
        "schema_version: '1.0.0'\nagent_type: worker\nis_verifier: false\nagent_identity:\n  name: agent-worker\n",
    )
    verdict, reason = check_agent_is_verifier("agent-worker", tmp_path)
    assert verdict == "PASS"
    assert reason == "not_verifier"


@pytest.mark.unit
def test_verifier_agent_is_blocked(tmp_path: Path) -> None:
    _write_yaml(
        tmp_path,
        "agent-task-verifier.yaml",
        "schema_version: '1.0.0'\nagent_type: task_verifier\nis_verifier: true\nagent_identity:\n  name: agent-task-verifier\n",
    )
    verdict, reason = check_agent_is_verifier("agent-task-verifier", tmp_path)
    assert verdict == "BLOCK"
    assert reason == "is_verifier"


@pytest.mark.unit
def test_missing_yaml_blocks_fail_safe(tmp_path: Path) -> None:
    verdict, reason = check_agent_is_verifier("unknown-agent", tmp_path)
    assert verdict == "BLOCK"
    assert reason == "yaml_not_found"


@pytest.mark.unit
def test_agent_found_by_identity_name(tmp_path: Path) -> None:
    _write_yaml(
        tmp_path,
        "some-other-filename.yaml",
        "schema_version: '1.0.0'\nagent_type: impl\nis_verifier: false\nagent_identity:\n  name: impl-agent\n",
    )
    verdict, reason = check_agent_is_verifier("impl-agent", tmp_path)
    assert verdict == "PASS"
    assert reason == "not_verifier"


@pytest.mark.unit
def test_is_verifier_absent_defaults_to_pass(tmp_path: Path) -> None:
    _write_yaml(
        tmp_path,
        "agent-no-flag.yaml",
        "schema_version: '1.0.0'\nagent_type: worker\nagent_identity:\n  name: agent-no-flag\n",
    )
    verdict, reason = check_agent_is_verifier("agent-no-flag", tmp_path)
    assert verdict == "PASS"
    assert reason == "not_verifier"
