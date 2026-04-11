# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Contract test: ticket_pipeline PRE_FLIGHT phase wires the reality-check gate.

Validates that the ticket_pipeline skill's prompt.md references the
preflight_reality_check library and documents the halt-on-mismatch behavior.
Mirrors the test_ticket_pipeline_dod_phase.py pattern.
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
class TestPreflightRealityCheckWiring:
    def test_prompt_imports_reality_check_module(self) -> None:
        content = PROMPT_MD.read_text()
        assert (
            "from plugins.onex.hooks.lib.preflight_reality_check import" in content
        ), "prompt.md must import the preflight_reality_check library"
        assert "run_reality_check" in content
        assert "write_diagnosis" in content

    def test_preflight_halts_on_mismatch(self) -> None:
        content = PROMPT_MD.read_text()
        assert "report.halted" in content, (
            "preflight must branch on reality check halt flag"
        )
        assert "reality_check_mismatch" in content, (
            "halted preflight must return block_kind=reality_check_mismatch"
        )

    def test_preflight_writes_diagnosis(self) -> None:
        content = PROMPT_MD.read_text()
        assert "write_diagnosis(report" in content, (
            "halted preflight must write a Two-Strike diagnosis doc"
        )

    def test_preflight_emits_friction(self) -> None:
        content = PROMPT_MD.read_text()
        assert "record_friction" in content, (
            "halted preflight must record a friction event"
        )
        assert "tooling/preflight-reality-check" in content, (
            "friction surface must be tooling/preflight-reality-check"
        )
