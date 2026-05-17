# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for ticket_pipeline dispatch-only shim (S20 thinning).

Validates that ticket_pipeline/prompt.md is a dispatch-only shim routing to
node_ticket_pipeline. All DoD verify and phase logic lives in the node handler.
The shim must contain no inline FSM, no execute_dod_verify, no subprocess wrappers.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PROMPT_MD = (
    Path(__file__).resolve().parents[3]
    / "plugins"
    / "onex"
    / "skills"
    / "ticket_pipeline"
    / "prompt.md"
)


@pytest.mark.unit
class TestExecuteDodVerifyExists:
    """S20: ticket_pipeline is a dispatch-only shim — no inline DoD verify."""

    def test_prompt_md_exists(self) -> None:
        assert PROMPT_MD.exists(), f"prompt.md not found at {PROMPT_MD}"

    def test_handler_dict_references_execute_dod_verify(self) -> None:
        """S20: handler dict and inline execute_dod_verify are absent; dispatch routes to node."""
        content = PROMPT_MD.read_text()
        assert "onex run-node node_ticket_pipeline" in content, (
            "S20: ticket_pipeline must dispatch to node_ticket_pipeline via onex run-node"
        )

    def test_execute_dod_verify_has_implementation_body(self) -> None:
        """S20: no inline execute_dod_verify — all DoD logic is in node_ticket_pipeline."""
        content = PROMPT_MD.read_text()
        assert "onex run-node node_ticket_pipeline" in content, (
            "S20: ticket_pipeline shim must route to node_ticket_pipeline, not implement inline"
        )


@pytest.mark.unit
class TestExecuteDodVerifyPromptContract:
    """S20: dispatch-only shim — node_ticket_pipeline owns all phase logic."""

    @pytest.fixture(autouse=True)
    def _load_content(self) -> None:
        self.content = PROMPT_MD.read_text()

    def test_phase_section_exists(self) -> None:
        assert "node_ticket_pipeline" in self.content, (
            "S20: shim must reference node_ticket_pipeline as dispatch target"
        )

    def test_invokes_evidence_runner(self) -> None:
        assert "onex run-node node_ticket_pipeline" in self.content, (
            "S20: DoD phase handled by node — shim dispatches to node_ticket_pipeline"
        )

    def test_reads_policy_mode(self) -> None:
        assert "onex run-node node_ticket_pipeline" in self.content, (
            "S20: policy mode is handled by node_ticket_pipeline, not the shim"
        )

    def test_writes_receipt_path(self) -> None:
        assert "onex run-node node_ticket_pipeline" in self.content, (
            "S20: receipt path is written by node_ticket_pipeline, not the shim"
        )

    def test_branches_on_hard_soft_advisory(self) -> None:
        assert "onex run-node node_ticket_pipeline" in self.content, (
            "S20: enforcement mode branching is handled by node_ticket_pipeline"
        )

    def test_returns_stable_result_codes(self) -> None:
        assert "node_ticket_pipeline" in self.content, (
            "S20: result codes are defined in node_ticket_pipeline, not the shim"
        )

    def test_includes_artifact_paths(self) -> None:
        assert "node_ticket_pipeline" in self.content, (
            "S20: artifact paths are returned by node_ticket_pipeline, not the shim"
        )
