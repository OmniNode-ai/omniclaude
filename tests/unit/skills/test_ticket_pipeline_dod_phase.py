# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for execute_dod_verify implementation in ticket-pipeline prompt.md.

Validates that the Phase 2.5 (dod_verify) handler is fully defined — not just
referenced in the handler dict, but contains a concrete implementation body
that invokes the evidence runner, reads policy mode, writes receipts, and
branches on hard/soft/advisory enforcement.
"""

from __future__ import annotations

import re
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
    """Smoke tests: execute_dod_verify body exists in prompt.md."""

    def test_prompt_md_exists(self) -> None:
        assert PROMPT_MD.exists(), f"prompt.md not found at {PROMPT_MD}"

    def test_handler_dict_references_execute_dod_verify(self) -> None:
        content = PROMPT_MD.read_text()
        assert '"dod_verify": execute_dod_verify' in content, (
            "Handler dict must reference execute_dod_verify"
        )

    def test_execute_dod_verify_has_implementation_body(self) -> None:
        """The function must have a real body — not just a handler dict ref."""
        content = PROMPT_MD.read_text()
        # There must be a def or function heading for execute_dod_verify
        # beyond just the handler dict line
        handler_dict_line = '"dod_verify": execute_dod_verify'
        occurrences = [
            i
            for i, line in enumerate(content.splitlines())
            if "execute_dod_verify" in line and handler_dict_line not in line
        ]
        assert len(occurrences) >= 1, (
            "execute_dod_verify must appear outside the handler dict "
            "(i.e., have an implementation body)"
        )


@pytest.mark.unit
class TestExecuteDodVerifyPromptContract:
    """Prompt-contract tests: implementation invokes evidence runner,
    reads policy mode, writes receipt path, branches on enforcement modes."""

    @pytest.fixture(autouse=True)
    def _load_content(self) -> None:
        self.content = PROMPT_MD.read_text()
        # Extract the Phase 2.5 section through the next phase heading
        lines = self.content.splitlines()
        start = None
        end = None
        for i, line in enumerate(lines):
            if "Phase 2.5" in line and "DOD VERIFY" in line:
                start = i
            elif start is not None and re.match(r"^###\s+Phase\s+\d", line):
                end = i
                break
        if start is not None:
            self.phase_section = "\n".join(lines[start : end if end else len(lines)])
        else:
            self.phase_section = ""

    def test_phase_section_exists(self) -> None:
        assert self.phase_section, "Phase 2.5 DOD VERIFY section not found"

    def test_invokes_evidence_runner(self) -> None:
        assert (
            "dod_evidence_runner" in self.phase_section
            or "run_dod_evidence" in self.phase_section
        ), "Phase 2.5 must invoke the DoD evidence runner"

    def test_reads_policy_mode(self) -> None:
        assert (
            "dod_enforcement" in self.phase_section
            or "policy_mode" in self.phase_section
        ), "Phase 2.5 must read DoD enforcement policy mode"

    def test_writes_receipt_path(self) -> None:
        assert (
            "receipt_path" in self.phase_section
            or "dod_report.json" in self.phase_section
        ), "Phase 2.5 must write/reference evidence receipt path"

    def test_branches_on_hard_soft_advisory(self) -> None:
        assert "hard" in self.phase_section, "Phase 2.5 must handle hard mode"
        assert "soft" in self.phase_section, "Phase 2.5 must handle soft mode"
        assert "advisory" in self.phase_section, "Phase 2.5 must handle advisory mode"

    def test_returns_stable_result_codes(self) -> None:
        """Implementation must define stable result codes."""
        assert "VERIFIED_PASS" in self.phase_section, "Must return VERIFIED_PASS result"
        assert "VERIFIED_FAIL" in self.phase_section, "Must return VERIFIED_FAIL result"
        assert "SKIPPED_NO_CONTRACT" in self.phase_section, (
            "Must return SKIPPED_NO_CONTRACT result"
        )
        assert "SKIPPED_NO_DOD_EVIDENCE" in self.phase_section, (
            "Must return SKIPPED_NO_DOD_EVIDENCE result"
        )
        assert "ERROR_RUNNER_FAILURE" in self.phase_section, (
            "Must return ERROR_RUNNER_FAILURE result"
        )

    def test_includes_artifact_paths(self) -> None:
        """Implementation must include receipt_path and contract_path in artifacts."""
        assert "receipt_path" in self.phase_section, (
            "Must include receipt_path in artifacts"
        )
        assert "contract_path" in self.phase_section, (
            "Must include contract_path in artifacts"
        )
