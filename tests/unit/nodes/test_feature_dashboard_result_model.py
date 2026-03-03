# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Model validation tests for the canonical Feature Dashboard result model (OMN-3501).

Verifies the contract invariants that callers must uphold:
  1. Evidence populated: every ModelAuditCheck with PASS or FAIL has len(evidence) >= 1
  2. Sort order: stable_json() output has keys in alphabetical order
  3. Byte-stable: calling stable_json() twice on the same result produces identical bytes
  4. generated_at excluded from stable JSON
  5. schema_version present in stable JSON
  6. ModelContractYaml parse failure maps to a contract_yaml FAIL check with CRITICAL severity

Test markers:
    @pytest.mark.unit -- all tests here
"""

from __future__ import annotations

import json
from typing import cast

import pydantic
import pytest

from omniclaude.nodes.node_skill_feature_dashboard_orchestrator.models.model_result import (
    AuditCheckName,
    AuditCheckStatus,
    GapSeverity,
    ModelAuditCheck,
    ModelContractYaml,
    ModelFeatureDashboardResult,
    ModelGap,
    ModelSkillAudit,
    SkillStatus,
)

# All tests in this module are unit tests
pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_check(
    name: AuditCheckName,
    status: AuditCheckStatus,
    evidence: list[str] | None = None,
) -> ModelAuditCheck:
    if evidence is None:
        evidence = [f"evidence for {name}"]
    return ModelAuditCheck(name=name, status=status, evidence=evidence)


def _make_skill(
    name: str, checks: list[ModelAuditCheck] | None = None
) -> ModelSkillAudit:
    if checks is None:
        checks = [
            _make_check(AuditCheckName.SKILL_MD, AuditCheckStatus.PASS),
        ]
    return ModelSkillAudit(
        name=name,
        slug=name.replace("-", "_"),
        node_type="ORCHESTRATOR_GENERIC",
        status=SkillStatus.WIRED,
        checks=checks,
        gaps=[],
    )


def _make_result(
    skills: list[ModelSkillAudit] | None = None,
    generated_at: str = "2026-03-03T00:00:00Z",
) -> ModelFeatureDashboardResult:
    if skills is None:
        skills = [_make_skill("alpha-skill")]
    return ModelFeatureDashboardResult(
        generated_at=generated_at,
        total=len(skills),
        wired=len(skills),
        partial=0,
        broken=0,
        unknown=0,
        failed=False,
        fail_reason=None,
        skills=skills,
    )


# ---------------------------------------------------------------------------
# Test 1: Evidence populated for PASS and FAIL checks
# ---------------------------------------------------------------------------


class TestEvidencePopulated:
    """Every ModelAuditCheck with status PASS or FAIL must have len(evidence) >= 1."""

    def test_pass_check_requires_at_least_one_evidence_entry(self) -> None:
        check = _make_check(
            AuditCheckName.SKILL_MD,
            AuditCheckStatus.PASS,
            ["skill.md found at plugins/onex/skills/my-skill/SKILL.md"],
        )
        assert len(check.evidence) >= 1

    def test_fail_check_requires_at_least_one_evidence_entry(self) -> None:
        check = _make_check(
            AuditCheckName.CONTRACT_YAML,
            AuditCheckStatus.FAIL,
            ["contract.yaml not found"],
        )
        assert len(check.evidence) >= 1

    def test_warn_check_may_have_evidence(self) -> None:
        """WARN checks can have evidence (no min requirement enforced by model)."""
        check = _make_check(
            AuditCheckName.TEST_COVERAGE, AuditCheckStatus.WARN, ["coverage: 72%"]
        )
        assert len(check.evidence) == 1

    def test_pass_check_with_multiple_evidence_entries(self) -> None:
        check = _make_check(
            AuditCheckName.TOPICS_NAMESPACED,
            AuditCheckStatus.PASS,
            ["onex.cmd.foo.v1 matches pattern", "onex.evt.foo.v1 matches pattern"],
        )
        assert len(check.evidence) >= 1

    def test_all_pass_and_fail_checks_in_result_have_evidence(self) -> None:
        """Integration-style: build a full result and verify all PASS/FAIL checks have evidence."""
        checks = [
            _make_check(AuditCheckName.SKILL_MD, AuditCheckStatus.PASS, ["found"]),
            _make_check(
                AuditCheckName.ORCHESTRATOR_NODE, AuditCheckStatus.FAIL, ["dir missing"]
            ),
            _make_check(
                AuditCheckName.CONTRACT_YAML, AuditCheckStatus.PASS, ["parsed ok"]
            ),
            _make_check(
                AuditCheckName.TEST_COVERAGE, AuditCheckStatus.WARN, ["below threshold"]
            ),
            _make_check(
                AuditCheckName.LINEAR_TICKET, AuditCheckStatus.FAIL, ["no ticket field"]
            ),
        ]
        skill = ModelSkillAudit(
            name="my-skill",
            slug="my_skill",
            node_type="ORCHESTRATOR_GENERIC",
            status=SkillStatus.BROKEN,
            checks=checks,
            gaps=[],
        )
        result = _make_result(skills=[skill])

        for audit in result.skills:
            for check in audit.checks:
                if check.status in (AuditCheckStatus.PASS, AuditCheckStatus.FAIL):
                    assert len(check.evidence) >= 1, (
                        f"Check {check.name!r} with status {check.status!r} has empty evidence"
                    )

    def test_evidence_is_nonempty_list_of_strings(self) -> None:
        check = _make_check(
            AuditCheckName.EVENT_BUS_PRESENT,
            AuditCheckStatus.PASS,
            ["event_bus key present"],
        )
        assert isinstance(check.evidence, list)
        assert all(isinstance(e, str) for e in check.evidence)
        assert len(check.evidence) >= 1


# ---------------------------------------------------------------------------
# Test 2: Keys sorted in stable_json() output
# ---------------------------------------------------------------------------


class TestKeysSorted:
    """stable_json() must return a dict whose top-level keys are in alphabetical order."""

    def test_top_level_keys_are_sorted(self) -> None:
        result = _make_result()
        stable = result.stable_json()
        keys = list(stable.keys())
        assert keys == sorted(keys), f"Keys not sorted: {keys}"

    def test_sorted_with_multiple_skills(self) -> None:
        skills = [
            _make_skill("alpha-skill"),
            _make_skill("beta-skill"),
            _make_skill("charlie-skill"),
        ]
        result = _make_result(skills=skills)
        stable = result.stable_json()
        keys = list(stable.keys())
        assert keys == sorted(keys)

    def test_sorted_with_empty_skills(self) -> None:
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
        stable = result.stable_json()
        keys = list(stable.keys())
        assert keys == sorted(keys)

    def test_known_key_order(self) -> None:
        """Verify the expected sorted key order for a typical result."""
        result = _make_result()
        stable = result.stable_json()
        keys = list(stable.keys())
        # These are all keys except generated_at, sorted alphabetically
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
        assert keys == expected_keys


# ---------------------------------------------------------------------------
# Test 3: Byte-stable stable_json()
# ---------------------------------------------------------------------------


class TestByteStable:
    """stable_json() called twice on the same result produces identical bytes when serialized."""

    def test_same_dict_on_two_calls(self) -> None:
        result = _make_result()
        s1 = result.stable_json()
        s2 = result.stable_json()
        assert s1 == s2

    def test_identical_bytes_when_json_serialized(self) -> None:
        result = _make_result()
        s1 = result.stable_json()
        s2 = result.stable_json()
        bytes1 = json.dumps(s1, sort_keys=True).encode("utf-8")
        bytes2 = json.dumps(s2, sort_keys=True).encode("utf-8")
        assert bytes1 == bytes2

    def test_identical_bytes_with_multiple_skills(self) -> None:
        skills = [_make_skill(n) for n in ["alpha-skill", "beta-skill", "delta-skill"]]
        result = _make_result(skills=skills)
        bytes1 = json.dumps(result.stable_json(), sort_keys=True).encode("utf-8")
        bytes2 = json.dumps(result.stable_json(), sort_keys=True).encode("utf-8")
        assert bytes1 == bytes2

    def test_byte_stability_independent_of_generated_at(self) -> None:
        """Two results with different generated_at but same data must produce identical stable bytes."""
        skills = [_make_skill("my-skill")]
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
            generated_at="2026-03-03T11:30:00Z",
            total=1,
            wired=1,
            partial=0,
            broken=0,
            unknown=0,
            failed=False,
            fail_reason=None,
            skills=skills,
        )
        bytes1 = json.dumps(r1.stable_json(), sort_keys=True).encode("utf-8")
        bytes2 = json.dumps(r2.stable_json(), sort_keys=True).encode("utf-8")
        assert bytes1 == bytes2

    def test_different_data_produces_different_bytes(self) -> None:
        """Sanity: two results with different skill counts produce different stable bytes."""
        r1 = _make_result(skills=[_make_skill("alpha-skill")])
        r2 = _make_result(
            skills=[_make_skill("alpha-skill"), _make_skill("beta-skill")]
        )
        bytes1 = json.dumps(r1.stable_json(), sort_keys=True).encode("utf-8")
        bytes2 = json.dumps(r2.stable_json(), sort_keys=True).encode("utf-8")
        assert bytes1 != bytes2


# ---------------------------------------------------------------------------
# Test 4: generated_at excluded from stable JSON
# ---------------------------------------------------------------------------


class TestGeneratedAtExcluded:
    """stable_json() must NOT include generated_at in its output."""

    def test_generated_at_not_in_stable_json(self) -> None:
        result = _make_result(generated_at="2026-03-03T12:34:56Z")
        stable = result.stable_json()
        assert "generated_at" not in stable

    def test_generated_at_different_values_excluded(self) -> None:
        for ts in [
            "2026-01-01T00:00:00Z",
            "2024-12-31T23:59:59Z",
            "2025-06-15T08:30:00+00:00",
        ]:
            result = _make_result(generated_at=ts)
            stable = result.stable_json()
            assert "generated_at" not in stable, (
                f"generated_at leaked into stable_json for ts={ts!r}"
            )

    def test_generated_at_still_accessible_on_model(self) -> None:
        """generated_at is excluded from stable_json but remains accessible on the model instance."""
        ts = "2026-03-03T12:00:00Z"
        result = _make_result(generated_at=ts)
        assert result.generated_at == ts
        assert "generated_at" not in result.stable_json()


# ---------------------------------------------------------------------------
# Test 5: schema_version present in stable JSON
# ---------------------------------------------------------------------------


class TestSchemaVersionPresent:
    """stable_json() must include schema_version."""

    def test_schema_version_in_stable_json(self) -> None:
        result = _make_result()
        stable = result.stable_json()
        assert "schema_version" in stable

    def test_schema_version_value(self) -> None:
        result = _make_result()
        stable = result.stable_json()
        assert stable["schema_version"] == "1.0.0"

    def test_schema_version_is_string(self) -> None:
        result = _make_result()
        stable = result.stable_json()
        assert isinstance(stable["schema_version"], str)


# ---------------------------------------------------------------------------
# Test 6: ModelContractYaml parse failure maps to contract_yaml FAIL / CRITICAL
# ---------------------------------------------------------------------------


class TestContractYamlParseFailure:
    """Verify that ModelContractYaml parse failures and the corresponding check objects
    follow the expected contract: FAIL status + CRITICAL severity."""

    def test_missing_required_field_raises_validation_error(self) -> None:
        """ModelContractYaml requires 'name' and 'node_type'; omitting them raises ValidationError."""
        with pytest.raises(pydantic.ValidationError):
            ModelContractYaml()  # type: ignore[call-arg]

    def test_missing_name_raises_validation_error(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            ModelContractYaml(node_type="ORCHESTRATOR_GENERIC")  # type: ignore[call-arg]

    def test_missing_node_type_raises_validation_error(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            ModelContractYaml(name="my-skill")  # type: ignore[call-arg]

    def test_parse_failure_maps_to_fail_check(self) -> None:
        """When contract.yaml cannot be parsed, the audit check should be FAIL."""
        # Simulate what the orchestrator would create on parse failure
        check = ModelAuditCheck(
            name=AuditCheckName.CONTRACT_YAML,
            status=AuditCheckStatus.FAIL,
            message="ValidationError: field required: node_type",
            evidence=[
                "contract.yaml parse error: 1 validation error for ModelContractYaml"
            ],
        )
        assert check.name == AuditCheckName.CONTRACT_YAML
        assert check.status == AuditCheckStatus.FAIL
        assert len(check.evidence) >= 1

    def test_parse_failure_maps_to_critical_gap(self) -> None:
        """When contract.yaml cannot be parsed, the gap should have CRITICAL severity."""
        gap = ModelGap(
            layer=AuditCheckName.CONTRACT_YAML,
            severity=GapSeverity.CRITICAL,
            message="contract.yaml failed to parse as ModelContractYaml",
            suggested_fix="Ensure contract.yaml has required 'name' and 'node_type' fields",
        )
        assert gap.layer == AuditCheckName.CONTRACT_YAML
        assert gap.severity == GapSeverity.CRITICAL

    def test_parse_failure_check_and_gap_can_be_assembled_into_skill_audit(
        self,
    ) -> None:
        """A skill audit for a parse-failure skill is constructible with BROKEN status."""
        check = ModelAuditCheck(
            name=AuditCheckName.CONTRACT_YAML,
            status=AuditCheckStatus.FAIL,
            evidence=["parse error: missing required field 'node_type'"],
        )
        gap = ModelGap(
            layer=AuditCheckName.CONTRACT_YAML,
            severity=GapSeverity.CRITICAL,
            message="contract.yaml failed to parse",
        )
        audit = ModelSkillAudit(
            name="broken-skill",
            slug="broken_skill",
            node_type="unknown",
            status=SkillStatus.BROKEN,
            checks=[check],
            gaps=[gap],
        )
        assert audit.status == SkillStatus.BROKEN
        assert audit.checks[0].status == AuditCheckStatus.FAIL
        assert audit.gaps[0].severity == GapSeverity.CRITICAL

    def test_valid_contract_yaml_does_not_raise(self) -> None:
        """Valid YAML data parses without error."""
        contract = ModelContractYaml(name="my-skill", node_type="ORCHESTRATOR_GENERIC")
        assert contract.name == "my-skill"
        assert contract.node_type == "ORCHESTRATOR_GENERIC"


# ---------------------------------------------------------------------------
# Test 7: Skills sorted alphabetically in ModelFeatureDashboardResult
# ---------------------------------------------------------------------------


class TestSkillsSortedAlphabetically:
    """Callers must pass skills pre-sorted; the model preserves insertion order."""

    def test_alphabetical_order_preserved(self) -> None:
        skills = [
            _make_skill(n) for n in ["alpha-skill", "beta-skill", "charlie-skill"]
        ]
        result = _make_result(skills=skills)
        names = [s.name for s in result.skills]
        assert names == sorted(names)

    def test_single_skill_trivially_sorted(self) -> None:
        result = _make_result(skills=[_make_skill("only-skill")])
        names = [s.name for s in result.skills]
        assert names == sorted(names)

    def test_empty_skills_list_trivially_sorted(self) -> None:
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
        names = [s.name for s in result.skills]
        assert names == sorted(names)

    def test_skills_order_reflected_in_stable_json(self) -> None:
        """Skills in stable_json preserve the insertion order (which callers set alphabetically)."""
        skill_names = ["alpha-skill", "beta-skill", "zeta-skill"]
        skills = [_make_skill(n) for n in skill_names]
        result = _make_result(skills=skills)
        stable = result.stable_json()
        skills_list = cast("list[dict[str, object]]", stable["skills"])
        serialized_names = [s["name"] for s in skills_list]
        assert serialized_names == skill_names
