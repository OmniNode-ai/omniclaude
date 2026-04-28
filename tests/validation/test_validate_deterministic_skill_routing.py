# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for deterministic skill routing enforcement validator (OMN-8749, S2)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = (
    REPO_ROOT / "scripts" / "validation" / "validate_deterministic_skill_routing.py"
)
FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "deterministic_skill_routing"

sys.path.insert(0, str(REPO_ROOT / "scripts" / "validation"))
from validate_deterministic_skill_routing import (  # noqa: E402
    CHECK_DISPATCH,
    CHECK_PROSE_FALLBACK,
    CHECK_ROUTING_ERROR,
    ENFORCED_SKILLS,
    scan_skill,
    scan_skills_root,
)


@pytest.fixture
def compliant_skill(tmp_path: Path) -> Path:
    skill_dir = tmp_path / "compliance_sweep"
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        "---\ndescription: test\n---\n\n# Test\n\n"
        "```bash\nonex run-node node_compliance_sweep --input '{}'\n```\n\n"
        "On non-zero exit, a `SkillRoutingError` JSON envelope is returned "
        "-- surface it directly, do not produce prose.\n"
    )
    return skill_file


@pytest.fixture
def compliant_local_skill(tmp_path: Path) -> Path:
    skill_dir = tmp_path / "runtime_sweep"
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        "---\ndescription: test\n---\n\n# Test\n\n"
        "```bash\nonex node node_runtime_sweep -- --scope all-repos\n```\n\n"
        "On non-zero exit, a `SkillRoutingError` JSON envelope is returned "
        "-- surface it directly, do not produce prose.\n"
    )
    return skill_file


@pytest.mark.unit
class TestCompliantSkill:
    def test_compliant_run_node(self, compliant_skill: Path) -> None:
        violations = scan_skill(compliant_skill)
        assert violations == [], (
            f"Expected 0 violations, got: {[v.format_line() for v in violations]}"
        )

    def test_compliant_local_dispatch(self, compliant_local_skill: Path) -> None:
        violations = scan_skill(compliant_local_skill)
        assert violations == [], (
            f"Expected 0 violations, got: {[v.format_line() for v in violations]}"
        )


@pytest.mark.unit
class TestMissingDispatch:
    def test_no_dispatch_flagged(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "test_skill"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(
            "---\ndescription: test\n---\n\n# Test\n"
            "Just a prose skill with no dispatch.\n"
        )
        violations = scan_skill(skill_file)
        checks = {v.check for v in violations}
        assert CHECK_DISPATCH in checks


@pytest.mark.unit
class TestPassiveTopicMentionIsNotDispatch:
    """Regression for CodeRabbit finding: `onex.cmd.*` alone must not satisfy CHECK_DISPATCH.

    A skill that only documents a command topic without stating that something
    publishes or sends to it does not contain an executable route. Before the fix,
    _DISPATCH_RE accepted any substring match on `onex.cmd.\\w+`, which let a
    passive mention like "Command topic: onex.cmd.x.v1" pass validation.
    """

    def test_bare_topic_mention_flags_missing_dispatch(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "test_skill"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(
            "---\ndescription: test\n---\n\n# Test\n\n"
            "Command topic: `onex.cmd.omnimarket.session.v1`\n\n"
            "On routing failure, a `SkillRoutingError` JSON envelope is returned "
            "-- surface it directly, do not produce prose.\n"
        )
        violations = scan_skill(skill_file)
        checks = {v.check for v in violations}
        assert CHECK_DISPATCH in checks, (
            "Passive topic mention must NOT satisfy CHECK_DISPATCH; "
            f"violations were: {[v.format_line() for v in violations]}"
        )

    def test_publish_to_topic_satisfies_dispatch(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "test_skill"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(
            "---\ndescription: test\n---\n\n# Test\n\n"
            "Dispatch: Kafka publish to `onex.cmd.omnimarket.pr-lifecycle.v1`\n\n"
            "On routing failure, a `SkillRoutingError` JSON envelope is returned "
            "-- surface it directly, do not produce prose.\n"
        )
        violations = scan_skill(skill_file)
        checks = {v.check for v in violations}
        assert CHECK_DISPATCH not in checks, (
            "'Kafka publish to <topic>' must satisfy CHECK_DISPATCH; "
            f"violations were: {[v.format_line() for v in violations]}"
        )

    def test_publishes_to_topic_satisfies_dispatch(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "test_skill"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(
            "---\ndescription: test\n---\n\n# Test\n\n"
            "The orchestrator publishes to onex.cmd.omnimarket.session.v1 on start.\n\n"
            "On routing failure, a `SkillRoutingError` JSON envelope is returned "
            "-- surface it directly, do not produce prose.\n"
        )
        violations = scan_skill(skill_file)
        checks = {v.check for v in violations}
        assert CHECK_DISPATCH not in checks, (
            "'publishes to <topic>' must satisfy CHECK_DISPATCH; "
            f"violations were: {[v.format_line() for v in violations]}"
        )


@pytest.mark.unit
class TestMissingRoutingError:
    def test_no_routing_error_flagged(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "test_skill"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(
            "---\ndescription: test\n---\n\n# Test\n\n"
            "```bash\nonex node node_test -- --scope all\n```\n"
        )
        violations = scan_skill(skill_file)
        checks = {v.check for v in violations}
        assert CHECK_ROUTING_ERROR in checks


@pytest.mark.unit
class TestProseFallback:
    def test_prose_fallback_flagged(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "test_skill"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(
            "---\ndescription: test\n---\n\n# Test\n\n"
            "```bash\nonex node node_test -- --scope all\n```\n\n"
            "If node unavailable, fallback to Claude prose advisory.\n"
        )
        violations = scan_skill(skill_file)
        checks = {v.check for v in violations}
        assert CHECK_PROSE_FALLBACK in checks


@pytest.mark.unit
class TestRoutingErrorWithoutNoProse:
    def test_routing_error_without_no_prose_instruction(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "test_skill"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(
            "---\ndescription: test\n---\n\n# Test\n\n"
            "```bash\nonex node node_test -- --scope all\n```\n\n"
            "A `SkillRoutingError` JSON envelope is returned on failure.\n"
        )
        violations = scan_skill(skill_file)
        checks = {v.check for v in violations}
        assert CHECK_PROSE_FALLBACK in checks


@pytest.mark.unit
class TestEnforcedSkillsSet:
    def test_session_in_enforced(self) -> None:
        assert "session" in ENFORCED_SKILLS

    def test_overnight_in_enforced(self) -> None:
        # OMN-8751: overnight is now a thin dispatch-only shim and must
        # satisfy the deterministic routing enforcement gate.
        assert "overnight" in ENFORCED_SKILLS

    def test_pr_review_bot_in_enforced(self) -> None:
        # OMN-10269: pr_review_bot is a thin runtime-backed skill surface over
        # node_pr_review_bot and must satisfy deterministic routing enforcement.
        assert "pr_review_bot" in ENFORCED_SKILLS

    def test_pr_review_in_enforced(self) -> None:
        # OMN-10268: pr_review is now a thin runtime-backed skill surface over
        # node_pr_review_bot and must satisfy deterministic routing enforcement.
        assert "pr_review" in ENFORCED_SKILLS

    def test_missing_node_skills_not_in_enforced(self) -> None:
        for s in (
            "bus_audit",
            "dod_sweep",
            "env_parity",
            "gap",
            "integration_sweep",
            "pr_watch",
        ):
            assert s not in ENFORCED_SKILLS, f"{s} should not be in ENFORCED_SKILLS"


@pytest.mark.unit
class TestScanSkillsRoot:
    def test_scan_with_compliant_skill(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "compliance_sweep"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\n---\n\n"
            "```bash\nonex run-node node_compliance_sweep --input '{}'\n```\n\n"
            "On non-zero exit, a `SkillRoutingError` JSON envelope is returned "
            "-- surface it directly, do not produce prose.\n"
        )

        import validate_deterministic_skill_routing as mod

        original = mod.ENFORCED_SKILLS
        mod.ENFORCED_SKILLS = {"compliance_sweep"}
        try:
            result = scan_skills_root(tmp_path)
        finally:
            mod.ENFORCED_SKILLS = original

        assert result.skills_scanned == 1
        assert result.total_violations == 0

    def test_scan_with_missing_skill(self, tmp_path: Path) -> None:
        import validate_deterministic_skill_routing as mod

        original = mod.ENFORCED_SKILLS
        mod.ENFORCED_SKILLS = {"nonexistent_skill"}
        try:
            result = scan_skills_root(tmp_path)
        finally:
            mod.ENFORCED_SKILLS = original

        assert result.skills_scanned == 1
        assert result.total_violations == 1
        assert result.violations[0].check == "MISSING_SKILL_MD"


@pytest.mark.unit
class TestCliInterface:
    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(VALIDATOR), *args],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_report_mode_exits_zero(self, tmp_path: Path) -> None:
        result = self._run(
            "--skills-root",
            str(tmp_path),
            "--skill",
            "nonexistent",
            "--report",
        )
        assert result.returncode == 0

    def test_nonexistent_skill_exits_one(self, tmp_path: Path) -> None:
        result = self._run(
            "--skills-root",
            str(tmp_path),
            "--skill",
            "nonexistent",
        )
        assert result.returncode == 1

    def test_compliant_skill_exits_zero(self, compliant_skill: Path) -> None:
        skills_root = compliant_skill.parent.parent
        result = self._run(
            "--skills-root",
            str(skills_root),
            "--skill",
            "compliance_sweep",
        )
        assert result.returncode == 0, (
            f"Expected exit 0, got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
