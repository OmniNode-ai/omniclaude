# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Integration tests for the contract-sweep skill.

Tests verify skill spec completeness via static analysis.
All tests are @pytest.mark.unit (no live scanning, network calls, or repo access).

Updated for v2.0.0: skill now wraps the check-drift CLI from onex_change_control
for contract drift detection and boundary staleness validation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).parent.parent.parent.parent.parent
_SKILLS_ROOT = _REPO_ROOT / "plugins" / "onex" / "skills"
_CONTRACT_SWEEP_DIR = _SKILLS_ROOT / "contract_sweep"
_SKILL_MD = _CONTRACT_SWEEP_DIR / "SKILL.md"
_PROMPT_MD = _CONTRACT_SWEEP_DIR / "prompt.md"


def _read(path: Path) -> str:
    if not path.exists():
        pytest.skip(f"File not found: {path}")
    return path.read_text(encoding="utf-8")


@pytest.mark.unit
class TestSkillMd:
    def test_frontmatter_complete(self) -> None:
        content = _read(_SKILL_MD)
        for field in (
            "description:",
            "version:",
            "mode:",
            "category:",
            "args:",
        ):
            assert field in content, f"SKILL.md missing frontmatter field: {field}"

    def test_dry_run_documented(self) -> None:
        content = _read(_SKILL_MD)
        assert "--dry-run" in content

    def test_drift_classification_documented(self) -> None:
        content = _read(_SKILL_MD)
        classifications = [
            "BREAKING",
            "ADDITIVE",
            "NON_BREAKING",
        ]
        for classification in classifications:
            assert classification in content, (
                f"SKILL.md missing drift classification: {classification}"
            )

    def test_severity_and_ticket_creation_documented(self) -> None:
        content = _read(_SKILL_MD)
        assert "Ticket Priority" in content or "ticket creation" in content.lower()
        assert "Critical" in content
        assert "Major" in content

    def test_drift_detection_pipeline_documented(self) -> None:
        content = _read(_SKILL_MD)
        assert "check-drift" in content or "check_contract_drift" in content
        assert "handler_drift_analysis" in content
        assert "NodeContractDriftCompute" in content

    def test_boundary_staleness_documented(self) -> None:
        content = _read(_SKILL_MD)
        assert "boundary" in content.lower()
        assert "kafka_boundaries.yaml" in content
        assert "staleness" in content.lower() or "stale" in content.lower()

    def test_sensitivity_levels_documented(self) -> None:
        content = _read(_SKILL_MD)
        for level in ("STRICT", "STANDARD", "LAX"):
            assert level in content, f"SKILL.md missing sensitivity level: {level}"

    def test_repos_arg_documented(self) -> None:
        content = _read(_SKILL_MD)
        assert "--repos" in content

    def test_severity_threshold_arg_documented(self) -> None:
        content = _read(_SKILL_MD)
        assert "--severity-threshold" in content

    def test_sensitivity_arg_documented(self) -> None:
        content = _read(_SKILL_MD)
        assert "--sensitivity" in content

    def test_check_boundaries_arg_documented(self) -> None:
        content = _read(_SKILL_MD)
        assert "--check-boundaries" in content

    def test_output_format_documented(self) -> None:
        content = _read(_SKILL_MD)
        assert "report.yaml" in content
        assert "drift_findings" in content
        assert "boundary_findings" in content

    def test_status_determination_documented(self) -> None:
        content = _read(_SKILL_MD)
        assert "clean" in content
        assert "drifted" in content
        assert "breaking" in content.lower()


@pytest.mark.unit
class TestPromptMd:
    def test_all_phases_present(self) -> None:
        content = _read(_PROMPT_MD)
        phases = [
            "Announce",
            "Parse arguments",
            "Phase 1",
            "Phase 2",
            "Phase 3",
            "Phase 4",
            "Phase 5",
            "Phase 6",
        ]
        for phase in phases:
            assert phase in content, f"prompt.md missing phase: {phase}"

    def test_repo_list_complete(self) -> None:
        content = _read(_PROMPT_MD)
        repos = [
            "omnibase_core",
            "omnibase_infra",
            "omniclaude",
            "omniintelligence",
            "omnimemory",
            "omninode_infra",
            "omnibase_spi",
            "onex_change_control",
        ]
        for repo in repos:
            assert repo in content, f"prompt.md missing repo: {repo}"

    def test_check_drift_cli_referenced(self) -> None:
        content = _read(_PROMPT_MD)
        assert "check_contract_drift.py" in content
        assert "handler_drift_analysis" in content or "field-level" in content.lower()

    def test_boundary_validation_present(self) -> None:
        content = _read(_PROMPT_MD)
        assert "kafka_boundaries.yaml" in content
        assert "producer_file" in content.lower() or "Producer file" in content
        assert "consumer_file" in content.lower() or "Consumer file" in content

    def test_output_path_uses_onex_state_dir(self) -> None:
        content = _read(_PROMPT_MD)
        assert "$ONEX_STATE_DIR" in content
        assert "contract-sweep" in content

    def test_ticket_dedup_documented(self) -> None:
        content = _read(_PROMPT_MD)
        assert "dedup" in content.lower() or "Ticket dedup" in content

    def test_drift_classification_in_prompt(self) -> None:
        content = _read(_PROMPT_MD)
        assert "BREAKING" in content
        assert "ADDITIVE" in content
        assert "NON_BREAKING" in content

    def test_error_handling_present(self) -> None:
        content = _read(_PROMPT_MD)
        assert "Error handling" in content or "error handling" in content.lower()

    def test_ticket_format_documented(self) -> None:
        content = _read(_PROMPT_MD)
        assert "Drift ticket format" in content or "drift ticket" in content.lower()
        assert (
            "Boundary ticket format" in content or "boundary ticket" in content.lower()
        )
