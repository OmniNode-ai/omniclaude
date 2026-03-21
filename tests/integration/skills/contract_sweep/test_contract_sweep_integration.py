# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Integration tests for the contract-sweep skill.

Tests verify skill spec completeness via static analysis.
All tests are @pytest.mark.unit (no live scanning, network calls, or repo access).
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

    def test_all_checks_documented(self) -> None:
        content = _read(_SKILL_MD)
        checks = [
            "Contract class identification",
            "ambiguous loader directories",
            "superseded scaffolds",
            "Required fields present",
            "Node-specific fields",
            "Handler-specific fields",
            "node-only fields on handlers",
            "duplicate contracts",
            "orphaned contracts",
            "Package contract location",
        ]
        for check in checks:
            assert check.lower() in content.lower(), f"SKILL.md missing check: {check}"

    def test_severity_levels_documented(self) -> None:
        content = _read(_SKILL_MD)
        for level in ("CRITICAL", "ERROR", "WARNING", "INFO"):
            assert level in content, f"SKILL.md missing severity level: {level}"

    def test_contract_class_doctrine_documented(self) -> None:
        content = _read(_SKILL_MD)
        assert "Contract Class Doctrine" in content
        assert "Node contract" in content
        assert "Handler contract" in content
        assert "Package-level" in content

    def test_exception_policy_documented(self) -> None:
        content = _read(_SKILL_MD)
        assert "Exception Policy" in content
        assert (
            "explanatory comment" in content.lower()
            or "minimality comment" in content.lower()
        )

    def test_repos_arg_documented(self) -> None:
        content = _read(_SKILL_MD)
        assert "--repos" in content

    def test_severity_threshold_arg_documented(self) -> None:
        content = _read(_SKILL_MD)
        assert "--severity-threshold" in content


@pytest.mark.unit
class TestPromptMd:
    def test_all_phases_present(self) -> None:
        content = _read(_PROMPT_MD)
        phases = [
            "Announce",
            "Parse arguments",
            "Discovery",
            "Validation",
            "Triage",
            "Report",
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

    def test_scan_exclusions_present(self) -> None:
        content = _read(_PROMPT_MD)
        assert "Exception policy" in content or "exception policy" in content.lower()
        assert "tests/" in content
        assert "fixtures/" in content
        assert "examples/" in content

    def test_output_path_uses_onex_state_dir(self) -> None:
        content = _read(_PROMPT_MD)
        assert "$ONEX_STATE_DIR" in content
        assert "contract-sweep" in content

    def test_ticket_dedup_documented(self) -> None:
        content = _read(_PROMPT_MD)
        assert "dedup" in content.lower() or "Ticket dedup" in content

    def test_severity_escalation_rule_present(self) -> None:
        content = _read(_PROMPT_MD)
        assert "escalation" in content.lower()

    def test_ten_checks_referenced(self) -> None:
        content = _read(_PROMPT_MD)
        # All 10 checks should be referenced
        check_names = [
            "Check 1",
            "Check 2",
            "Check 3",
            "Check 4",
            "Check 5",
            "Check 6",
            "Check 7",
            "Check 8",
            "Check 9",
            "Check 10",
        ]
        for check in check_names:
            assert check in content, f"prompt.md missing: {check}"
