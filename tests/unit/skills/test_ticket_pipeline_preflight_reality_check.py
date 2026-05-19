# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Contract test: ticket_pipeline dispatch-only shim (S20 thinning).

S20 thinned ticket_pipeline/prompt.md to a dispatch-only shim routing to
node_ticket_pipeline. Pre-flight reality check and all phase logic lives in
the node handler. The shim must not contain inline imports or phase logic.
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


def _assert_node_owned_preflight_contract(content: str, expected_clause: str) -> None:
    assert "onex run-node node_ticket_pipeline" in content
    assert expected_clause in content
    assert "preflight_reality_check" not in content
    assert "write_diagnosis" not in content
    assert "emit_friction" not in content


@pytest.mark.unit
class TestPreflightRealityCheckWiring:
    def test_prompt_imports_reality_check_module(self) -> None:
        """S20: shim dispatches to node — no inline preflight_reality_check import."""
        content = PROMPT_MD.read_text()
        _assert_node_owned_preflight_contract(
            content,
            "All FSM logic",
        )

    def test_preflight_halts_on_mismatch(self) -> None:
        """S20: halt-on-mismatch logic lives in node_ticket_pipeline, not the shim."""
        content = PROMPT_MD.read_text()
        _assert_node_owned_preflight_contract(
            content,
            "If the pipeline reached FAILED state, display the failure reason",
        )

    def test_preflight_writes_diagnosis(self) -> None:
        """S20: diagnosis writing is owned by node_ticket_pipeline."""
        content = PROMPT_MD.read_text()
        _assert_node_owned_preflight_contract(
            content,
            "Phase results: <phase_results summary>",
        )

    def test_preflight_emits_friction(self) -> None:
        """S20: friction emission is owned by node_ticket_pipeline."""
        content = PROMPT_MD.read_text()
        _assert_node_owned_preflight_contract(
            content,
            "Do not attempt inline recovery",
        )
