# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for codex sandbox config in contract.yaml — OMN-10135 Task 13."""

from __future__ import annotations

from pathlib import Path

import yaml


def test_codex_config_in_contract_yaml() -> None:
    contract = yaml.safe_load(
        (
            Path(__file__).parents[3]
            / "src/omniclaude/nodes/node_delegation_orchestrator/contract.yaml"
        ).read_text()
    )
    assert "codex_config" in contract
    assert "sandbox_modes" in contract["codex_config"]
    modes = contract["codex_config"]["sandbox_modes"]
    assert "read-only" in modes
    assert "workspace-write" in modes
    assert "danger-full-access" in modes


def test_codex_sandbox_modes_have_use_for_and_description() -> None:
    contract = yaml.safe_load(
        (
            Path(__file__).parents[3]
            / "src/omniclaude/nodes/node_delegation_orchestrator/contract.yaml"
        ).read_text()
    )
    modes = contract["codex_config"]["sandbox_modes"]
    for mode_name, mode_data in modes.items():
        assert "use_for" in mode_data, f"mode {mode_name!r} missing use_for"
        assert "description" in mode_data, f"mode {mode_name!r} missing description"
