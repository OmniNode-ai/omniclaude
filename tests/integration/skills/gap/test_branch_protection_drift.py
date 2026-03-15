# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Integration tests for BRANCH_PROTECTION_DRIFT failure class (OMN-3787).

Tests verify:
- INTEGRATION_HEALTH category exists in EnumGapCategory
- gh_api evidence method is accepted by ModelGapFinding
- branch_protection probe (2.12) is documented in prompt.md
- branch_protection failure class is in FAILURE_TAXONOMY.md
- branch_protection auto-dispatch entry exists in fix phase
- merge-sweep documents the BLOCKED+green pre-scan diagnostic

All tests are static analysis / structural tests that run without external
credentials, live GitHub access, or live PRs. Safe for CI.

Test markers:
    @pytest.mark.unit  -- pure static analysis, no external services required
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent.parent.parent.parent
_SKILLS_ROOT = _REPO_ROOT / "plugins" / "onex" / "skills"
_GAP_DIR = _SKILLS_ROOT / "gap"
_GAP_PROMPT = _GAP_DIR / "prompt.md"
_GAP_SKILL = _GAP_DIR / "SKILL.md"
_TAXONOMY = _GAP_DIR / "docs" / "FAILURE_TAXONOMY.md"
_MODELS_DIR = _GAP_DIR / "models"
_ENUM_FILE = _MODELS_DIR / "enum_gap_category.py"
_FINDING_FILE = _MODELS_DIR / "model_gap_finding.py"
_MERGE_SWEEP_DIR = _SKILLS_ROOT / "merge-sweep"
_MERGE_SWEEP_PROMPT = _MERGE_SWEEP_DIR / "prompt.md"
_MERGE_SWEEP_SKILL = _MERGE_SWEEP_DIR / "SKILL.md"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read(path: Path) -> str:
    if not path.exists():
        pytest.skip(f"File not found: {path}")
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Test case 1: INTEGRATION_HEALTH category in enum
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIntegrationHealthCategory:
    """The INTEGRATION_HEALTH category must exist in EnumGapCategory."""

    def test_enum_has_integration_health(self) -> None:
        content = _read(_ENUM_FILE)
        assert "INTEGRATION_HEALTH" in content, (
            "EnumGapCategory must include INTEGRATION_HEALTH member"
        )

    def test_enum_integration_health_is_string_value(self) -> None:
        content = _read(_ENUM_FILE)
        assert re.search(r'INTEGRATION_HEALTH\s*=\s*"INTEGRATION_HEALTH"', content), (
            "INTEGRATION_HEALTH must be a str enum with value 'INTEGRATION_HEALTH'"
        )


# ---------------------------------------------------------------------------
# Test case 2: gh_api evidence method in ModelGapFinding
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGhApiEvidenceMethod:
    """ModelGapFinding must accept gh_api as an evidence_method."""

    def test_finding_model_accepts_gh_api(self) -> None:
        content = _read(_FINDING_FILE)
        assert "gh_api" in content, (
            "ModelGapFinding.evidence_method Literal must include 'gh_api'"
        )

    def test_finding_model_has_branch_protection_in_boundary_kind_description(
        self,
    ) -> None:
        content = _read(_FINDING_FILE)
        assert "branch_protection" in content, (
            "ModelGapFinding.boundary_kind description must mention branch_protection"
        )


# ---------------------------------------------------------------------------
# Test case 3: Probe 2.12 in prompt.md
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBranchProtectionProbe:
    """Probe 2.12 (branch_protection) must be documented in prompt.md."""

    def test_prompt_has_probe_2_12(self) -> None:
        content = _read(_GAP_PROMPT)
        assert "2.12" in content, "prompt.md must contain probe 2.12"

    def test_prompt_has_branch_protection_boundary_kind(self) -> None:
        content = _read(_GAP_PROMPT)
        assert "branch_protection" in content, (
            "prompt.md must document branch_protection boundary_kind"
        )

    def test_prompt_has_required_check_name_stale_rule(self) -> None:
        content = _read(_GAP_PROMPT)
        assert "required_check_name_stale" in content, (
            "prompt.md must document required_check_name_stale rule_name"
        )

    def test_prompt_has_integration_health_category(self) -> None:
        content = _read(_GAP_PROMPT)
        assert "INTEGRATION_HEALTH" in content, (
            "prompt.md must reference INTEGRATION_HEALTH category for probe 2.12"
        )

    def test_prompt_has_gh_api_evidence(self) -> None:
        content = _read(_GAP_PROMPT)
        assert "gh api" in content or "gh_api" in content, (
            "prompt.md must document gh api as the evidence method for probe 2.12"
        )

    def test_prompt_documents_stale_checks_proof_blob(self) -> None:
        content = _read(_GAP_PROMPT)
        assert "stale_checks" in content, (
            "prompt.md must document stale_checks in the proof blob schema"
        )

    def test_prompt_documents_auto_fix_for_branch_protection(self) -> None:
        content = _read(_GAP_PROMPT)
        # Must document the PATCH API call for auto-fix
        assert "PATCH" in content and "required_status_checks" in content, (
            "prompt.md must document the gh api PATCH call for auto-fixing "
            "stale branch protection checks"
        )

    def test_prompt_documents_12_probe_categories(self) -> None:
        content = _read(_GAP_PROMPT)
        assert "12 probe categories" in content, (
            "prompt.md must reference 12 probe categories (was 11 before OMN-3787)"
        )


# ---------------------------------------------------------------------------
# Test case 4: FAILURE_TAXONOMY.md includes class 12
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFailureTaxonomy:
    """FAILURE_TAXONOMY.md must include branch_protection as failure class 12."""

    def test_taxonomy_has_12_classes(self) -> None:
        content = _read(_TAXONOMY)
        assert "12 failure classes" in content, (
            "FAILURE_TAXONOMY.md must reference 12 failure classes"
        )

    def test_taxonomy_has_branch_protection_row(self) -> None:
        content = _read(_TAXONOMY)
        assert "branch_protection" in content, (
            "FAILURE_TAXONOMY.md must include branch_protection in the failure classes table"
        )

    def test_taxonomy_has_integration_health_category(self) -> None:
        content = _read(_TAXONOMY)
        assert "INTEGRATION_HEALTH" in content, (
            "FAILURE_TAXONOMY.md must include INTEGRATION_HEALTH in the categories section"
        )

    def test_taxonomy_has_probe_2_12_mapping(self) -> None:
        content = _read(_TAXONOMY)
        # Probe-to-class mapping table must include 2.12
        assert re.search(r"2\.12.*branch_protection", content), (
            "FAILURE_TAXONOMY.md must map probe 2.12 to branch_protection"
        )

    def test_taxonomy_branch_protection_severity_critical(self) -> None:
        content = _read(_TAXONOMY)
        # branch_protection must appear in severity defaults with CRITICAL
        lines = [
            line
            for line in content.splitlines()
            if "branch_protection" in line and "CRITICAL" in line
        ]
        assert lines, (
            "FAILURE_TAXONOMY.md must list branch_protection severity as CRITICAL"
        )

    def test_taxonomy_has_gh_api_auto_fix_policy(self) -> None:
        content = _read(_TAXONOMY)
        lower = content.lower()
        assert "gh api" in lower or "gh_api" in content or "github api" in lower, (
            "FAILURE_TAXONOMY.md must document YES (GitHub API) auto-fix policy"
        )


# ---------------------------------------------------------------------------
# Test case 5: Auto-dispatch entry in fix phase
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAutoDispatchEntry:
    """The auto-dispatch table must include branch_protection."""

    def test_skill_has_branch_protection_auto_dispatch(self) -> None:
        content = _read(_GAP_SKILL)
        assert (
            "branch_protection" in content and "required_check_name_stale" in content
        ), (
            "SKILL.md auto-dispatch table must include branch_protection / "
            "required_check_name_stale"
        )

    def test_prompt_has_branch_protection_auto_dispatch(self) -> None:
        content = _read(_GAP_PROMPT)
        # The dispatch table in prompt.md must include the entry
        lines = [
            line
            for line in content.splitlines()
            if "branch_protection" in line and "AUTO" in line
        ]
        assert lines, (
            "prompt.md auto-dispatch table must include branch_protection as AUTO"
        )

    def test_skill_documents_12_probes(self) -> None:
        content = _read(_GAP_SKILL)
        assert "12 probe categories" in content or "12." in content, (
            "SKILL.md must reference 12 probe categories"
        )


# ---------------------------------------------------------------------------
# Test case 6: Merge-sweep BLOCKED+green pre-scan diagnostic
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMergeSweepBranchProtectionDiagnostic:
    """Merge-sweep must detect BLOCKED+green PRs as potential branch protection drift."""

    def test_merge_sweep_prompt_has_branch_protection_diagnostic(self) -> None:
        content = _read(_MERGE_SWEEP_PROMPT)
        assert (
            "branch_protection" in content.lower() or "BRANCH_PROTECTION" in content
        ), "merge-sweep prompt.md must reference branch protection drift diagnostic"

    def test_merge_sweep_prompt_detects_blocked_green(self) -> None:
        content = _read(_MERGE_SWEEP_PROMPT)
        assert "BLOCKED" in content and "green" in content.lower(), (
            "merge-sweep prompt.md must document BLOCKED + green detection"
        )

    def test_merge_sweep_skill_mentions_branch_protection(self) -> None:
        content = _read(_MERGE_SWEEP_SKILL)
        assert (
            "branch protection" in content.lower() or "BRANCH_PROTECTION" in content
        ), "merge-sweep SKILL.md must mention branch protection drift"

    def test_merge_sweep_prompt_references_audit_script(self) -> None:
        content = _read(_MERGE_SWEEP_PROMPT)
        assert "audit-branch-protection" in content, (
            "merge-sweep prompt.md must reference audit-branch-protection.py as "
            "the diagnostic tool for BLOCKED+green PRs"
        )
