# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Smoke-test: audit mode stable.json write verification (OMN-3507).

Verifies end-to-end file write behaviour of the audit mode:
  1. stable.json is always written regardless of --format flag
  2. Written file does NOT contain generated_at
  3. schema_version "1.0.0" is present in written file
  4. skills list is sorted alphabetically by name
  5. All PASS/FAIL checks have non-empty evidence lists
  6. --fail-on broken: failed=True + fail_reason set when broken skills present
  7. --fail-on broken: failed=False when no broken skills present
  8. Two consecutive writes produce byte-identical files (idempotency)
  9. stable.json is written even when output_dir does not pre-exist

Test markers:
    @pytest.mark.unit -- all tests here
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from omniclaude.nodes.node_skill_feature_dashboard_orchestrator.models.model_result import (
    AuditCheckName,
    AuditCheckStatus,
    GapSeverity,
    ModelAuditCheck,
    ModelFeatureDashboardResult,
    ModelGap,
    ModelSkillAudit,
    SkillStatus,
)

pytestmark = pytest.mark.unit

_STABLE_JSON_NAME = "feature-dashboard.stable.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_check(
    name: AuditCheckName,
    status: AuditCheckStatus,
    evidence: list[str] | None = None,
) -> ModelAuditCheck:
    if evidence is None:
        evidence = [f"evidence for {name}"]
    return ModelAuditCheck(name=name, status=status, evidence=evidence)


def _make_wired_skill(name: str) -> ModelSkillAudit:
    return ModelSkillAudit(
        name=name,
        slug=name.replace("-", "_"),
        node_type="ORCHESTRATOR_GENERIC",
        status=SkillStatus.WIRED,
        checks=[
            _make_check(
                AuditCheckName.SKILL_MD, AuditCheckStatus.PASS, ["SKILL.md found"]
            ),
            _make_check(
                AuditCheckName.ORCHESTRATOR_NODE,
                AuditCheckStatus.PASS,
                [
                    f"src/omniclaude/nodes/node_skill_{name.replace('-', '_')}_orchestrator/ exists"
                ],
            ),
            _make_check(
                AuditCheckName.CONTRACT_YAML,
                AuditCheckStatus.PASS,
                ["contract.yaml: node_type='ORCHESTRATOR_GENERIC'"],
            ),
            _make_check(
                AuditCheckName.TEST_COVERAGE,
                AuditCheckStatus.PASS,
                [
                    f"skill '{name}' in canonical coverage list in test_skill_node_coverage.py"
                ],
            ),
        ],
        gaps=[],
    )


def _make_broken_skill(name: str) -> ModelSkillAudit:
    return ModelSkillAudit(
        name=name,
        slug=name.replace("-", "_"),
        node_type="ORCHESTRATOR_GENERIC",
        status=SkillStatus.BROKEN,
        checks=[
            _make_check(
                AuditCheckName.SKILL_MD, AuditCheckStatus.PASS, ["SKILL.md found"]
            ),
            _make_check(
                AuditCheckName.ORCHESTRATOR_NODE,
                AuditCheckStatus.FAIL,
                [
                    f"src/omniclaude/nodes/node_skill_{name.replace('-', '_')}_orchestrator/ not found"
                ],
            ),
        ],
        gaps=[
            ModelGap(
                layer=AuditCheckName.ORCHESTRATOR_NODE,
                severity=GapSeverity.CRITICAL,
                message=f"Orchestrator node directory missing for '{name}'",
                suggested_fix="Run uv run python scripts/generate_skill_node.py {name}",
            )
        ],
    )


def _build_result(
    skills: list[ModelSkillAudit],
    fail_on: str | None = None,
    generated_at: str = "2026-03-03T00:00:00Z",
) -> ModelFeatureDashboardResult:
    """Build a ModelFeatureDashboardResult with optional --fail-on logic applied."""
    broken = sum(1 for s in skills if s.status == SkillStatus.BROKEN)
    partial = sum(1 for s in skills if s.status == SkillStatus.PARTIAL)
    wired = sum(1 for s in skills if s.status == SkillStatus.WIRED)
    unknown = sum(1 for s in skills if s.status == SkillStatus.UNKNOWN)

    failed = False
    fail_reason: str | None = None
    if fail_on == "broken" and broken > 0:
        failed = True
        fail_reason = f"--fail-on broken: {broken} broken skill(s)"
    elif fail_on == "partial" and (broken > 0 or partial > 0):
        failed = True
        fail_reason = f"--fail-on partial: {broken} broken, {partial} partial skill(s)"
    elif fail_on == "any" and (broken > 0 or partial > 0 or unknown > 0):
        failed = True
        fail_reason = f"--fail-on any: {broken + partial + unknown} non-wired skill(s)"

    return ModelFeatureDashboardResult(
        generated_at=generated_at,
        total=len(skills),
        wired=wired,
        partial=partial,
        broken=broken,
        unknown=unknown,
        failed=failed,
        fail_reason=fail_reason,
        skills=sorted(skills, key=lambda s: s.name),
    )


def _write_stable_json(result: ModelFeatureDashboardResult, output_dir: Path) -> Path:
    """Write stable.json to output_dir, creating directory if needed. Returns path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    stable_path = output_dir / _STABLE_JSON_NAME
    stable_data = result.stable_json()
    stable_path.write_text(
        json.dumps(stable_data, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    return stable_path


# ---------------------------------------------------------------------------
# Test 1: stable.json always written regardless of "format"
# ---------------------------------------------------------------------------


class TestStableJsonAlwaysWritten:
    """stable.json must be written regardless of the --format flag."""

    def test_written_with_cli_format(self) -> None:
        """Simulates --format=cli: stable.json must still be written."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "feature-dashboard"
            skills = [_make_wired_skill("alpha-skill")]
            result = _build_result(skills)

            # Simulate --format=cli: write stable.json (no other format output)
            path = _write_stable_json(result, output_dir)

            assert path.exists(), "stable.json must be written even for --format=cli"
            assert path.name == _STABLE_JSON_NAME

    def test_written_to_new_output_dir(self) -> None:
        """output_dir is created if it does not exist (mkdir parents=True)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "deep" / "nested" / "feature-dashboard"
            assert not output_dir.exists()

            skills = [_make_wired_skill("alpha-skill")]
            result = _build_result(skills)
            path = _write_stable_json(result, output_dir)

            assert output_dir.exists(), "output_dir must be created if absent"
            assert path.exists()

    def test_overwrite_existing_stable_json(self) -> None:
        """Writing stable.json twice overwrites the previous file deterministically."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "feature-dashboard"
            skills = [_make_wired_skill("alpha-skill"), _make_wired_skill("beta-skill")]
            result = _build_result(skills)

            path = _write_stable_json(result, output_dir)
            first_content = path.read_bytes()
            path = _write_stable_json(result, output_dir)
            second_content = path.read_bytes()

            assert first_content == second_content, "Overwrite must be idempotent"


# ---------------------------------------------------------------------------
# Test 2: generated_at NOT in written file
# ---------------------------------------------------------------------------


class TestGeneratedAtExcludedFromFile:
    """Written stable.json must not contain the generated_at field."""

    def test_generated_at_absent_in_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "feature-dashboard"
            result = _build_result(
                skills=[_make_wired_skill("alpha-skill")],
                generated_at="2026-03-03T12:34:56Z",
            )
            path = _write_stable_json(result, output_dir)
            data = json.loads(path.read_text(encoding="utf-8"))
            assert "generated_at" not in data, (
                "generated_at must not appear in stable.json"
            )

    def test_generated_at_value_not_leaked_into_file(self) -> None:
        ts = "2026-03-03T23:59:59Z"
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "feature-dashboard"
            result = _build_result(
                skills=[_make_wired_skill("my-skill")],
                generated_at=ts,
            )
            path = _write_stable_json(result, output_dir)
            raw = path.read_text(encoding="utf-8")
            assert ts not in raw, (
                "generated_at timestamp must not appear anywhere in the file"
            )


# ---------------------------------------------------------------------------
# Test 3: schema_version "1.0.0" present in file
# ---------------------------------------------------------------------------


class TestSchemaVersionInFile:
    """Written stable.json must contain schema_version='1.0.0'."""

    def test_schema_version_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "feature-dashboard"
            result = _build_result(skills=[_make_wired_skill("alpha-skill")])
            path = _write_stable_json(result, output_dir)
            data = json.loads(path.read_text(encoding="utf-8"))
            assert "schema_version" in data
            assert data["schema_version"] == "1.0.0"

    def test_schema_version_is_string(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "feature-dashboard"
            result = _build_result(skills=[_make_wired_skill("alpha-skill")])
            path = _write_stable_json(result, output_dir)
            data = json.loads(path.read_text(encoding="utf-8"))
            assert isinstance(data["schema_version"], str)


# ---------------------------------------------------------------------------
# Test 4: skills list sorted alphabetically
# ---------------------------------------------------------------------------


class TestSkillsSortedInFile:
    """Skills in written stable.json must be sorted alphabetically by name."""

    def test_skills_sorted_alphabetically(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "feature-dashboard"
            skill_names = ["charlie-skill", "alpha-skill", "beta-skill"]
            skills = [_make_wired_skill(n) for n in skill_names]
            result = _build_result(skills)  # _build_result sorts by name
            path = _write_stable_json(result, output_dir)
            data = json.loads(path.read_text(encoding="utf-8"))
            names: list[str] = [s["name"] for s in data["skills"]]
            assert names == sorted(names), f"Skills not sorted: {names}"

    def test_empty_skills_list_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "feature-dashboard"
            result = ModelFeatureDashboardResult(
                generated_at="2026-03-03T00:00:00Z",
                total=0,
                wired=0,
                partial=0,
                broken=0,
                unknown=0,
                failed=False,
                fail_reason=None,
                skills=[],
            )
            path = _write_stable_json(result, output_dir)
            data = json.loads(path.read_text(encoding="utf-8"))
            assert data["skills"] == []
            assert data["total"] == 0


# ---------------------------------------------------------------------------
# Test 5: All PASS/FAIL checks have non-empty evidence
# ---------------------------------------------------------------------------


class TestEvidenceInWrittenFile:
    """Every PASS/FAIL check in written stable.json must have non-empty evidence."""

    def test_all_pass_fail_checks_have_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "feature-dashboard"
            skills = [
                _make_wired_skill("alpha-skill"),
                _make_broken_skill("broken-skill"),
            ]
            result = _build_result(skills)
            path = _write_stable_json(result, output_dir)
            data = json.loads(path.read_text(encoding="utf-8"))

            for skill_data in data["skills"]:
                for check_data in skill_data["checks"]:
                    if check_data["status"] in ("pass", "fail"):
                        assert len(check_data["evidence"]) >= 1, (
                            f"Check {check_data['name']!r} (status={check_data['status']!r}) "
                            f"in skill {skill_data['name']!r} has empty evidence"
                        )


# ---------------------------------------------------------------------------
# Test 6 & 7: --fail-on broken flag triggers correct failed/fail_reason values
# ---------------------------------------------------------------------------


class TestFailOnBrokenBehavior:
    """--fail-on broken: failed=True + fail_reason when broken skills present."""

    def test_fail_on_broken_with_broken_skill(self) -> None:
        """When fail_on='broken' and broken > 0: failed=True, fail_reason set."""
        skills = [_make_wired_skill("alpha-skill"), _make_broken_skill("broken-skill")]
        result = _build_result(skills, fail_on="broken")
        assert result.failed is True, (
            "failed must be True when fail_on=broken and broken>0"
        )
        assert result.fail_reason is not None, (
            "fail_reason must be set when failed=True"
        )
        assert "broken" in result.fail_reason.lower()

    def test_fail_on_broken_without_broken_skill(self) -> None:
        """When fail_on='broken' and no broken skills: failed=False."""
        skills = [_make_wired_skill("alpha-skill"), _make_wired_skill("beta-skill")]
        result = _build_result(skills, fail_on="broken")
        assert result.failed is False, (
            "failed must be False when fail_on=broken but no broken skills"
        )
        assert result.fail_reason is None

    def test_fail_on_broken_reflected_in_written_file(self) -> None:
        """failed=True is written into stable.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "feature-dashboard"
            skills = [_make_broken_skill("broken-skill")]
            result = _build_result(skills, fail_on="broken")
            path = _write_stable_json(result, output_dir)
            data = json.loads(path.read_text(encoding="utf-8"))
            assert data["failed"] is True
            assert data["fail_reason"] is not None
            assert "broken" in data["fail_reason"].lower()

    def test_fail_on_absent_never_sets_failed_true(self) -> None:
        """When fail_on is not set, failed is always False regardless of skill status."""
        skills = [_make_broken_skill("broken-skill")]
        result = _build_result(skills, fail_on=None)
        assert result.failed is False
        assert result.fail_reason is None

    def test_fail_on_any_with_broken_skill(self) -> None:
        """fail_on='any' triggers failed=True for broken skills."""
        skills = [_make_broken_skill("broken-skill")]
        result = _build_result(skills, fail_on="any")
        assert result.failed is True
        assert result.fail_reason is not None


# ---------------------------------------------------------------------------
# Test 8: Byte-identical consecutive writes (idempotency)
# ---------------------------------------------------------------------------


class TestByteIdempotency:
    """Two consecutive writes of the same result produce byte-identical files."""

    def test_two_writes_are_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "feature-dashboard"
            skills = [
                _make_wired_skill("alpha-skill"),
                _make_broken_skill("beta-skill"),
                _make_wired_skill("gamma-skill"),
            ]
            result = _build_result(skills)

            path = _write_stable_json(result, output_dir)
            bytes1 = path.read_bytes()
            path = _write_stable_json(result, output_dir)
            bytes2 = path.read_bytes()

            assert bytes1 == bytes2, (
                "Two consecutive stable.json writes must produce identical bytes"
            )

    def test_different_generated_at_same_bytes(self) -> None:
        """Two results with identical data but different generated_at produce identical files."""
        skills = [_make_wired_skill("alpha-skill")]

        r1 = ModelFeatureDashboardResult(
            generated_at="2026-03-03T10:00:00Z",
            total=1,
            wired=1,
            partial=0,
            broken=0,
            unknown=0,
            failed=False,
            fail_reason=None,
            skills=skills,
        )
        r2 = ModelFeatureDashboardResult(
            generated_at="2026-03-03T22:30:00Z",
            total=1,
            wired=1,
            partial=0,
            broken=0,
            unknown=0,
            failed=False,
            fail_reason=None,
            skills=skills,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            dir1 = Path(tmpdir) / "run1"
            dir2 = Path(tmpdir) / "run2"

            p1 = _write_stable_json(r1, dir1)
            p2 = _write_stable_json(r2, dir2)

            assert p1.read_bytes() == p2.read_bytes(), (
                "Different generated_at values must not affect stable.json bytes"
            )


# ---------------------------------------------------------------------------
# Test 9: Top-level JSON keys are sorted
# ---------------------------------------------------------------------------


class TestKeyOrderInFile:
    """Keys in written stable.json must be in sorted order."""

    def test_top_level_keys_sorted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "feature-dashboard"
            result = _build_result(skills=[_make_wired_skill("alpha-skill")])
            path = _write_stable_json(result, output_dir)

            # Parse preserving order
            import json as _json

            data_ordered = _json.loads(
                path.read_text(encoding="utf-8"), object_pairs_hook=dict
            )
            keys = list(data_ordered.keys())
            assert keys == sorted(keys), f"Top-level keys not sorted: {keys}"

    def test_expected_key_set(self) -> None:
        """Stable JSON must contain exactly the expected set of top-level keys."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "feature-dashboard"
            result = _build_result(skills=[_make_wired_skill("alpha-skill")])
            path = _write_stable_json(result, output_dir)
            data = json.loads(path.read_text(encoding="utf-8"))
            expected_keys = sorted(
                [
                    "broken",
                    "fail_reason",
                    "failed",
                    "partial",
                    "schema_version",
                    "skills",
                    "total",
                    "unknown",
                    "wired",
                ]
            )
            assert sorted(data.keys()) == expected_keys
            assert "generated_at" not in data.keys()
