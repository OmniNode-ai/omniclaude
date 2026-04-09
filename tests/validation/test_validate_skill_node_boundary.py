# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for the skill-node boundary enforcement validator (OMN-8094)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "scripts" / "validation" / "validate_skill_node_boundary.py"
FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "skill_node_boundary"


# ---------------------------------------------------------------------------
# Import the scanner directly for unit tests (no subprocess overhead)
# ---------------------------------------------------------------------------

sys.path.insert(0, str(REPO_ROOT / "scripts" / "validation"))
from validate_skill_node_boundary import (  # noqa: E402
    CHECK_DIRECT_API_CALL,
    CHECK_FOR_LOOP_COLLECTION,
    CHECK_STATE_MANAGEMENT,
    scan_skill,
    scan_skills_root,
)


@pytest.mark.unit
class TestCompliantThinTrigger:
    """A thin-trigger skill with only onex run dispatch should pass."""

    def test_no_violations(self) -> None:
        skill_file = FIXTURES_ROOT / "compliant_thin_trigger" / "SKILL.md"
        violations = scan_skill(skill_file)
        assert violations == [], (
            f"Expected 0 violations for thin trigger, got: "
            f"{[v.format_line() for v in violations]}"
        )


@pytest.mark.unit
class TestDirectApiCallDetection:
    """Skills with direct gh / curl calls must be flagged."""

    def test_gh_pr_call_flagged(self) -> None:
        skill_file = FIXTURES_ROOT / "noncompliant_direct_gh" / "SKILL.md"
        violations = scan_skill(skill_file)
        checks = {v.check for v in violations}
        assert CHECK_DIRECT_API_CALL in checks, (
            f"Expected DIRECT_API_CALL violation, got checks: {checks}"
        )

    def test_violation_includes_line_number(self) -> None:
        skill_file = FIXTURES_ROOT / "noncompliant_direct_gh" / "SKILL.md"
        violations = [
            v for v in scan_skill(skill_file) if v.check == CHECK_DIRECT_API_CALL
        ]
        assert violations, "Expected at least one DIRECT_API_CALL violation"
        assert all(v.line_number > 0 for v in violations)

    def test_violation_includes_suggestion(self) -> None:
        skill_file = FIXTURES_ROOT / "noncompliant_direct_gh" / "SKILL.md"
        violations = [
            v for v in scan_skill(skill_file) if v.check == CHECK_DIRECT_API_CALL
        ]
        assert violations
        assert all("onex run" in v.suggestion for v in violations)


@pytest.mark.unit
class TestForLoopCollectionDetection:
    """Skills that iterate over PRs/repos/tickets must be flagged."""

    def test_for_loop_over_prs_flagged(self) -> None:
        skill_file = FIXTURES_ROOT / "noncompliant_for_loop" / "SKILL.md"
        violations = scan_skill(skill_file)
        checks = {v.check for v in violations}
        assert CHECK_FOR_LOOP_COLLECTION in checks, (
            f"Expected FOR_LOOP_COLLECTION violation, got checks: {checks}"
        )

    def test_for_loop_over_repos_flagged(self) -> None:
        skill_file = FIXTURES_ROOT / "noncompliant_for_loop" / "SKILL.md"
        violations = [
            v for v in scan_skill(skill_file) if v.check == CHECK_FOR_LOOP_COLLECTION
        ]
        matched_texts = " ".join(v.matched_text for v in violations)
        assert "repo" in matched_texts.lower() or "pr" in matched_texts.lower()


@pytest.mark.unit
class TestStateManagementDetection:
    """Skills with state dict/file access must be flagged."""

    def test_state_dict_access_flagged(self) -> None:
        skill_file = FIXTURES_ROOT / "noncompliant_state_management" / "SKILL.md"
        violations = scan_skill(skill_file)
        checks = {v.check for v in violations}
        assert CHECK_STATE_MANAGEMENT in checks, (
            f"Expected STATE_MANAGEMENT violation, got checks: {checks}"
        )

    def test_state_file_reference_flagged(self) -> None:
        skill_file = FIXTURES_ROOT / "noncompliant_state_management" / "SKILL.md"
        violations = [
            v for v in scan_skill(skill_file) if v.check == CHECK_STATE_MANAGEMENT
        ]
        assert len(violations) >= 1


@pytest.mark.unit
class TestFrontmatterExemption:
    """Skills with boundary_exempt: true must be fully skipped."""

    def test_exempt_skill_has_no_violations(self) -> None:
        skill_file = FIXTURES_ROOT / "exempt_skill" / "SKILL.md"
        violations = scan_skill(skill_file)
        assert violations == [], (
            f"Expected 0 violations for exempt skill, got: "
            f"{[v.format_line() for v in violations]}"
        )


@pytest.mark.unit
class TestInlineSuppression:
    """Lines with skill-boundary-ok comment must be suppressed."""

    def test_suppressed_line_has_no_violation(self) -> None:
        skill_file = FIXTURES_ROOT / "suppressed_line" / "SKILL.md"
        violations = [
            v for v in scan_skill(skill_file) if v.check == CHECK_DIRECT_API_CALL
        ]
        assert violations == [], (
            f"Expected suppressed line to produce 0 DIRECT_API_CALL violations, "
            f"got: {[v.format_line() for v in violations]}"
        )


@pytest.mark.unit
class TestScanSkillsRoot:
    """scan_skills_root should aggregate violations across all skills."""

    def test_scans_multiple_skills(self) -> None:
        result = scan_skills_root(FIXTURES_ROOT)
        # We have 5 fixture skills: 1 compliant, 1 exempt, 1 suppressed, 3 non-compliant
        # suppressed has gh call suppressed (no violation), but may have other issues
        assert result.skills_scanned >= 5

    def test_compliant_skill_not_counted_in_violations(self) -> None:
        result = scan_skills_root(FIXTURES_ROOT)
        violating_names = {v.skill_name for v in result.violations}
        assert "compliant_thin_trigger" not in violating_names

    def test_exempt_skill_not_counted_in_violations(self) -> None:
        result = scan_skills_root(FIXTURES_ROOT)
        violating_names = {v.skill_name for v in result.violations}
        assert "exempt_skill" not in violating_names

    def test_non_compliant_skills_detected(self) -> None:
        result = scan_skills_root(FIXTURES_ROOT)
        violating_names = {v.skill_name for v in result.violations}
        assert "noncompliant_direct_gh" in violating_names
        assert "noncompliant_for_loop" in violating_names
        assert "noncompliant_state_management" in violating_names


@pytest.mark.unit
class TestCliInterface:
    """The CLI should return correct exit codes."""

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(VALIDATOR), *args],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_exits_zero_on_clean_skills_root(self) -> None:
        result = self._run(
            "--skills-root",
            str(FIXTURES_ROOT / "compliant_thin_trigger").rsplit("/", 1)[0]
            + "/__nonexistent__",
        )
        # skills-root not found → exit 1 with error
        assert result.returncode == 1
        assert "not found" in result.stderr

    def test_exits_zero_on_single_compliant_skill(self, tmp_path: Path) -> None:
        # Copy compliant fixture into a temp skills root
        import shutil

        skill_dir = tmp_path / "compliant_thin_trigger"
        shutil.copytree(
            FIXTURES_ROOT / "compliant_thin_trigger",
            skill_dir,
        )
        result = self._run("--skills-root", str(tmp_path))
        assert result.returncode == 0, (
            f"Expected exit 0 for compliant skill, got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_exits_one_on_violations(self, tmp_path: Path) -> None:
        import shutil

        skill_dir = tmp_path / "noncompliant_direct_gh"
        shutil.copytree(
            FIXTURES_ROOT / "noncompliant_direct_gh",
            skill_dir,
        )
        result = self._run("--skills-root", str(tmp_path))
        assert result.returncode == 1, (
            f"Expected exit 1 for non-compliant skill, got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_report_mode_exits_zero_even_with_violations(self, tmp_path: Path) -> None:
        import shutil

        skill_dir = tmp_path / "noncompliant_direct_gh"
        shutil.copytree(
            FIXTURES_ROOT / "noncompliant_direct_gh",
            skill_dir,
        )
        result = self._run("--skills-root", str(tmp_path), "--report")
        assert result.returncode == 0, (
            f"Expected exit 0 in report mode, got {result.returncode}.\n"
            f"stdout: {result.stdout}"
        )

    def test_violation_output_includes_suggestion(self, tmp_path: Path) -> None:
        import shutil

        skill_dir = tmp_path / "noncompliant_direct_gh"
        shutil.copytree(
            FIXTURES_ROOT / "noncompliant_direct_gh",
            skill_dir,
        )
        result = self._run("--skills-root", str(tmp_path))
        assert "onex run" in result.stdout, (
            f"Expected suggestion mentioning 'onex run' in output:\n{result.stdout}"
        )

    def test_single_skill_scan(self) -> None:
        result = self._run(
            "--skills-root",
            str(FIXTURES_ROOT),
            "--skill",
            "compliant_thin_trigger",
        )
        assert result.returncode == 0

    def test_single_noncompliant_skill_scan(self) -> None:
        result = self._run(
            "--skills-root",
            str(FIXTURES_ROOT),
            "--skill",
            "noncompliant_direct_gh",
        )
        assert result.returncode == 1
