# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for instructional-skill routing enforcement (OMN-8766, S19)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = (
    REPO_ROOT / "scripts" / "validation" / "validate_instructional_skill_routing.py"
)

sys.path.insert(0, str(REPO_ROOT / "scripts" / "validation"))
from validate_instructional_skill_routing import (  # noqa: E402
    CHECK_MISSING_SKILL_MD,
    CHECK_ONEX_RUN_DISPATCH,
    CHECK_RENDERED_OUTPUT,
    ENFORCED_SKILLS,
    TIER3_INSTRUCTIONAL_SKILLS,
    scan_skill,
    scan_skills_root,
)


def _write_skill(tmp_path: Path, skill_name: str, body: str) -> Path:
    skill_dir = tmp_path / skill_name
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(body)
    return skill_file


@pytest.fixture
def compliant_skill(tmp_path: Path) -> Path:
    return _write_skill(
        tmp_path,
        "authorize",
        (
            "---\ndescription: test\n---\n\n"
            "# Authorize\n\n"
            "This is a pure-prose instructional skill explaining authorization.\n"
            "No dispatch commands. No receipt assertions.\n"
        ),
    )


@pytest.mark.unit
class TestCompliantSkill:
    def test_pure_prose_passes(self, compliant_skill: Path) -> None:
        violations = scan_skill(compliant_skill)
        assert violations == [], (
            f"Expected 0 violations, got: {[v.format_line() for v in violations]}"
        )


@pytest.mark.unit
class TestOnexRunRejection:
    def test_onex_run_node_flagged(self, tmp_path: Path) -> None:
        skill_file = _write_skill(
            tmp_path,
            "authorize",
            (
                "---\n---\n\n# Authorize\n\n"
                "```bash\nuv run onex run node_authorize -- --scope all\n```\n"
            ),
        )
        violations = scan_skill(skill_file)
        checks = {v.check for v in violations}
        assert CHECK_ONEX_RUN_DISPATCH in checks, (
            f"Expected ONEX_RUN dispatch violation, got: "
            f"{[v.format_line() for v in violations]}"
        )

    def test_onex_run_hyphen_node_flagged(self, tmp_path: Path) -> None:
        skill_file = _write_skill(
            tmp_path,
            "handoff",
            (
                "---\n---\n\n# Handoff\n\n"
                "```bash\nuv run onex run-node node_handoff\n```\n"
            ),
        )
        violations = scan_skill(skill_file)
        assert any(v.check == CHECK_ONEX_RUN_DISPATCH for v in violations)

    def test_onex_run_line_number_reported(self, tmp_path: Path) -> None:
        skill_file = _write_skill(
            tmp_path,
            "authorize",
            "line1\nline2\nline3 onex run node_authorize\nline4\n",
        )
        violations = [
            v for v in scan_skill(skill_file) if v.check == CHECK_ONEX_RUN_DISPATCH
        ]
        assert violations, "expected dispatch violation"
        assert violations[0].line_number == 3

    def test_onex_runbook_not_flagged(self, tmp_path: Path) -> None:
        # ``onex runbook`` and ``onex runtime`` are prose tokens, not dispatch.
        skill_file = _write_skill(
            tmp_path,
            "observability",
            (
                "---\n---\n\n# Observability\n\n"
                "See the onex runbook for escalation guidance.\n"
                "The onex runtime emits traces.\n"
            ),
        )
        violations = [
            v for v in scan_skill(skill_file) if v.check == CHECK_ONEX_RUN_DISPATCH
        ]
        assert violations == [], (
            f"Prose references to 'onex runbook'/'onex runtime' must not "
            f"match dispatch; got: {[v.format_line() for v in violations]}"
        )

    def test_prose_run_without_onex_not_flagged(self, tmp_path: Path) -> None:
        skill_file = _write_skill(
            tmp_path,
            "onboarding",
            "---\n---\n\nYou can run the tutorial; it will walk you through login.\n",
        )
        violations = [
            v for v in scan_skill(skill_file) if v.check == CHECK_ONEX_RUN_DISPATCH
        ]
        assert violations == []


@pytest.mark.unit
class TestRenderedOutputRejection:
    def test_rendered_output_in_code_flagged(self, tmp_path: Path) -> None:
        skill_file = _write_skill(
            tmp_path,
            "onboarding",
            (
                "---\n---\n\n# Onboarding\n\n"
                "```python\nprint(result['rendered_output'])\n```\n"
            ),
        )
        violations = [
            v for v in scan_skill(skill_file) if v.check == CHECK_RENDERED_OUTPUT
        ]
        assert violations, "expected rendered_output violation"

    def test_rendered_output_in_prose_flagged(self, tmp_path: Path) -> None:
        skill_file = _write_skill(
            tmp_path,
            "onboarding",
            (
                "---\n---\n\n# Onboarding\n\n"
                "Render the `rendered_output` field from the handler result directly.\n"
            ),
        )
        violations = [
            v for v in scan_skill(skill_file) if v.check == CHECK_RENDERED_OUTPUT
        ]
        assert violations

    def test_rendered_output_line_number_reported(self, tmp_path: Path) -> None:
        skill_file = _write_skill(
            tmp_path,
            "onboarding",
            "line1\nline2\nprint(result['rendered_output'])\nline4\n",
        )
        violations = [
            v for v in scan_skill(skill_file) if v.check == CHECK_RENDERED_OUTPUT
        ]
        assert violations
        assert violations[0].line_number == 3

    def test_word_rendered_without_output_not_flagged(self, tmp_path: Path) -> None:
        skill_file = _write_skill(
            tmp_path,
            "observability",
            "---\n---\n\nThe dashboard is rendered in the browser as output.\n",
        )
        violations = [
            v for v in scan_skill(skill_file) if v.check == CHECK_RENDERED_OUTPUT
        ]
        assert violations == []


@pytest.mark.unit
class TestEnforcedSkillsSet:
    def test_has_fifteen_instructional_skills(self) -> None:
        # OMN-8766 DoD: all 15 instructional skills enforced.
        assert len(TIER3_INSTRUCTIONAL_SKILLS) == 15

    def test_expected_skills_present(self) -> None:
        for skill in (
            "using_git_worktrees",
            "onboarding",
            "systematic_debugging",
            "multi_agent",
            "observability",
            "login",
            "authorize",
            "handoff",
            "resume_session",
            "set_session",
            "recall",
            "rewind",
            "crash_recovery",
            "checkpoint",
            "writing_skills",
        ):
            assert skill in TIER3_INSTRUCTIONAL_SKILLS, (
                f"{skill} missing from Tier 3 instructional set"
            )

    def test_tier1_skills_not_in_instructional(self) -> None:
        # Deterministic skills must not double-register as instructional.
        for skill in (
            "autopilot",
            "compliance_sweep",
            "merge_sweep",
            "pr_review",
            "pr_review_bot",
            "session",
            "release",
            "redeploy",
        ):
            assert skill not in TIER3_INSTRUCTIONAL_SKILLS


@pytest.mark.unit
class TestScanSkillsRoot:
    def test_scan_compliant_tree(self, tmp_path: Path) -> None:
        _write_skill(
            tmp_path,
            "authorize",
            "---\n---\n\nPure prose. No dispatch.\n",
        )

        import validate_instructional_skill_routing as mod

        original = mod.ENFORCED_SKILLS
        mod.ENFORCED_SKILLS = {"authorize"}
        try:
            result = scan_skills_root(tmp_path)
        finally:
            mod.ENFORCED_SKILLS = original

        assert result.skills_scanned == 1
        assert result.total_violations == 0

    def test_scan_missing_skill_md(self, tmp_path: Path) -> None:
        import validate_instructional_skill_routing as mod

        original = mod.ENFORCED_SKILLS
        mod.ENFORCED_SKILLS = {"nonexistent_skill"}
        try:
            result = scan_skills_root(tmp_path)
        finally:
            mod.ENFORCED_SKILLS = original

        assert result.skills_scanned == 1
        assert result.total_violations == 1
        assert result.violations[0].check == CHECK_MISSING_SKILL_MD

    def test_scan_violating_tree(self, tmp_path: Path) -> None:
        _write_skill(
            tmp_path,
            "authorize",
            "---\n---\n\n```bash\nonex run node_authorize\n```\n",
        )

        import validate_instructional_skill_routing as mod

        original = mod.ENFORCED_SKILLS
        mod.ENFORCED_SKILLS = {"authorize"}
        try:
            result = scan_skills_root(tmp_path)
        finally:
            mod.ENFORCED_SKILLS = original

        assert result.skills_scanned == 1
        assert result.total_violations >= 1
        assert any(v.check == CHECK_ONEX_RUN_DISPATCH for v in result.violations)


@pytest.mark.unit
class TestAllInstructionalSkillsEnforced:
    """Sanity: ENFORCED_SKILLS == TIER3_INSTRUCTIONAL_SKILLS."""

    def test_enforced_equals_tier3(self) -> None:
        assert ENFORCED_SKILLS == TIER3_INSTRUCTIONAL_SKILLS


@pytest.mark.unit
class TestCliInterface:
    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(VALIDATOR), *args],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_report_mode_exits_zero_on_violations(self, tmp_path: Path) -> None:
        _write_skill(
            tmp_path,
            "authorize",
            "---\n---\n\n```bash\nonex run node_authorize\n```\n",
        )
        result = self._run(
            "--skills-root",
            str(tmp_path),
            "--skill",
            "authorize",
            "--report",
        )
        assert result.returncode == 0, (
            f"--report must exit 0 even on violations. "
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_violating_skill_exits_one(self, tmp_path: Path) -> None:
        _write_skill(
            tmp_path,
            "authorize",
            "---\n---\n\n```bash\nonex run node_authorize\n```\n",
        )
        result = self._run(
            "--skills-root",
            str(tmp_path),
            "--skill",
            "authorize",
        )
        assert result.returncode == 1, (
            f"Expected exit 1 on violating skill, got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_compliant_skill_exits_zero(self, compliant_skill: Path) -> None:
        skills_root = compliant_skill.parent.parent
        result = self._run(
            "--skills-root",
            str(skills_root),
            "--skill",
            "authorize",
        )
        assert result.returncode == 0, (
            f"Expected exit 0, got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_missing_skill_md_exits_one(self, tmp_path: Path) -> None:
        result = self._run(
            "--skills-root",
            str(tmp_path),
            "--skill",
            "authorize",
        )
        assert result.returncode == 1
