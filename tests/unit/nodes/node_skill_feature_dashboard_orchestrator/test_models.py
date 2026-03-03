# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Unit tests for canonical result models for NodeSkillFeatureDashboardOrchestrator (OMN-3499).

Test markers:
    @pytest.mark.unit -- all tests here

Coverage:
    1. All enums are StrEnum subclasses with correct values
    2. ModelAuditCheck is frozen, evidence required (no default)
    3. ModelGap is frozen
    4. ModelSkillAudit is frozen
    5. ModelFeatureDashboardResult is frozen
    6. ModelFeatureDashboardResult.stable_json excludes generated_at
    7. ModelContractYaml parses correctly (including event_bus and metadata)
    8. ModelEventBus defaults to empty lists
    9. ModelContractMetadata defaults ticket to None
    10. Package-level __init__ re-exports all symbols
"""

from __future__ import annotations

import pytest

from omniclaude.nodes.node_skill_feature_dashboard_orchestrator.models import (
    AuditCheckName,
    AuditCheckStatus,
    GapSeverity,
    ModelAuditCheck,
    ModelContractMetadata,
    ModelContractYaml,
    ModelEventBus,
    ModelFeatureDashboardResult,
    ModelGap,
    ModelSkillAudit,
    SkillStatus,
)

# All tests in this module are unit tests
pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Enum Tests
# ---------------------------------------------------------------------------


class TestAuditCheckName:
    def test_is_str_enum(self) -> None:
        from enum import StrEnum

        assert issubclass(AuditCheckName, StrEnum)

    def test_values(self) -> None:
        assert AuditCheckName.SKILL_MD == "skill_md"
        assert AuditCheckName.ORCHESTRATOR_NODE == "orchestrator_node"
        assert AuditCheckName.CONTRACT_YAML == "contract_yaml"
        assert AuditCheckName.EVENT_BUS_PRESENT == "event_bus_present"
        assert AuditCheckName.TOPICS_NONEMPTY == "topics_nonempty"
        assert AuditCheckName.TOPICS_NAMESPACED == "topics_namespaced"
        assert AuditCheckName.TEST_COVERAGE == "test_coverage"
        assert AuditCheckName.LINEAR_TICKET == "linear_ticket"

    def test_all_members(self) -> None:
        members = {m.value for m in AuditCheckName}
        assert members == {
            "skill_md",
            "orchestrator_node",
            "contract_yaml",
            "event_bus_present",
            "topics_nonempty",
            "topics_namespaced",
            "test_coverage",
            "linear_ticket",
        }


class TestAuditCheckStatus:
    def test_is_str_enum(self) -> None:
        from enum import StrEnum

        assert issubclass(AuditCheckStatus, StrEnum)

    def test_values(self) -> None:
        assert AuditCheckStatus.PASS == "pass"
        assert AuditCheckStatus.FAIL == "fail"
        assert AuditCheckStatus.WARN == "warn"


class TestSkillStatus:
    def test_is_str_enum(self) -> None:
        from enum import StrEnum

        assert issubclass(SkillStatus, StrEnum)

    def test_values(self) -> None:
        assert SkillStatus.WIRED == "wired"
        assert SkillStatus.PARTIAL == "partial"
        assert SkillStatus.BROKEN == "broken"
        assert SkillStatus.UNKNOWN == "unknown"


class TestGapSeverity:
    def test_is_str_enum(self) -> None:
        from enum import StrEnum

        assert issubclass(GapSeverity, StrEnum)

    def test_values(self) -> None:
        assert GapSeverity.CRITICAL == "critical"
        assert GapSeverity.HIGH == "high"
        assert GapSeverity.MEDIUM == "medium"
        assert GapSeverity.LOW == "low"


# ---------------------------------------------------------------------------
# ModelAuditCheck
# ---------------------------------------------------------------------------


class TestModelAuditCheck:
    def test_frozen(self) -> None:
        check = ModelAuditCheck(
            name=AuditCheckName.SKILL_MD,
            status=AuditCheckStatus.PASS,
            evidence=["found skill.md at path/to/skill.md"],
        )
        with pytest.raises(Exception):
            check.status = AuditCheckStatus.FAIL  # type: ignore[misc]

    def test_evidence_required(self) -> None:
        """evidence has no default — omitting it raises a ValidationError."""
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            ModelAuditCheck(  # type: ignore[call-arg]
                name=AuditCheckName.SKILL_MD,
                status=AuditCheckStatus.PASS,
            )

    def test_message_defaults_to_none(self) -> None:
        check = ModelAuditCheck(
            name=AuditCheckName.CONTRACT_YAML,
            status=AuditCheckStatus.FAIL,
            evidence=["contract.yaml not found"],
        )
        assert check.message is None

    def test_message_set(self) -> None:
        check = ModelAuditCheck(
            name=AuditCheckName.TEST_COVERAGE,
            status=AuditCheckStatus.WARN,
            message="coverage below threshold",
            evidence=["coverage: 72%"],
        )
        assert check.message == "coverage below threshold"

    def test_evidence_multiple_entries(self) -> None:
        check = ModelAuditCheck(
            name=AuditCheckName.TOPICS_NAMESPACED,
            status=AuditCheckStatus.PASS,
            evidence=["topic: omniclaude.events.v1", "topic: omniclaude.commands.v1"],
        )
        assert len(check.evidence) == 2


# ---------------------------------------------------------------------------
# ModelGap
# ---------------------------------------------------------------------------


class TestModelGap:
    def test_frozen(self) -> None:
        gap = ModelGap(
            layer=AuditCheckName.EVENT_BUS_PRESENT,
            severity=GapSeverity.HIGH,
            message="no event_bus section in contract.yaml",
        )
        with pytest.raises(Exception):
            gap.severity = GapSeverity.LOW  # type: ignore[misc]

    def test_suggested_fix_defaults_to_none(self) -> None:
        gap = ModelGap(
            layer=AuditCheckName.LINEAR_TICKET,
            severity=GapSeverity.MEDIUM,
            message="no ticket field in contract metadata",
        )
        assert gap.suggested_fix is None

    def test_suggested_fix_set(self) -> None:
        gap = ModelGap(
            layer=AuditCheckName.LINEAR_TICKET,
            severity=GapSeverity.LOW,
            message="ticket field missing",
            suggested_fix="Add metadata.ticket: OMN-XXXX to contract.yaml",
        )
        assert gap.suggested_fix == "Add metadata.ticket: OMN-XXXX to contract.yaml"


# ---------------------------------------------------------------------------
# ModelSkillAudit
# ---------------------------------------------------------------------------


class TestModelSkillAudit:
    def _make_check(self, name: AuditCheckName, status: AuditCheckStatus) -> ModelAuditCheck:
        return ModelAuditCheck(name=name, status=status, evidence=["ok"])

    def test_frozen(self) -> None:
        audit = ModelSkillAudit(
            name="my-skill",
            slug="my_skill",
            node_type="orchestrator",
            status=SkillStatus.WIRED,
            checks=[self._make_check(AuditCheckName.SKILL_MD, AuditCheckStatus.PASS)],
            gaps=[],
        )
        with pytest.raises(Exception):
            audit.status = SkillStatus.BROKEN  # type: ignore[misc]

    def test_node_type_unknown_string(self) -> None:
        """node_type is a free string; 'unknown' is a valid value."""
        audit = ModelSkillAudit(
            name="orphan-skill",
            slug="orphan_skill",
            node_type="unknown",
            status=SkillStatus.UNKNOWN,
            checks=[],
            gaps=[],
        )
        assert audit.node_type == "unknown"

    def test_name_and_slug_preserved(self) -> None:
        audit = ModelSkillAudit(
            name="ticket-pipeline",
            slug="ticket_pipeline",
            node_type="orchestrator",
            status=SkillStatus.PARTIAL,
            checks=[],
            gaps=[],
        )
        assert audit.name == "ticket-pipeline"
        assert audit.slug == "ticket_pipeline"


# ---------------------------------------------------------------------------
# ModelFeatureDashboardResult
# ---------------------------------------------------------------------------


class TestModelFeatureDashboardResult:
    def _make_skill_audit(self, name: str) -> ModelSkillAudit:
        return ModelSkillAudit(
            name=name,
            slug=name.replace("-", "_"),
            node_type="orchestrator",
            status=SkillStatus.WIRED,
            checks=[
                ModelAuditCheck(
                    name=AuditCheckName.SKILL_MD,
                    status=AuditCheckStatus.PASS,
                    evidence=["found"],
                )
            ],
            gaps=[],
        )

    def test_frozen(self) -> None:
        result = ModelFeatureDashboardResult(
            generated_at="2026-03-03T00:00:00Z",
            total=1,
            wired=1,
            partial=0,
            broken=0,
            unknown=0,
            failed=False,
            fail_reason=None,
            skills=[self._make_skill_audit("alpha-skill")],
        )
        with pytest.raises(Exception):
            result.total = 99  # type: ignore[misc]

    def test_schema_version_default(self) -> None:
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
        assert result.schema_version == "1.0.0"

    def test_stable_json_excludes_generated_at(self) -> None:
        result = ModelFeatureDashboardResult(
            generated_at="2026-03-03T12:34:56Z",
            total=2,
            wired=1,
            partial=1,
            broken=0,
            unknown=0,
            failed=False,
            fail_reason=None,
            skills=[
                self._make_skill_audit("alpha-skill"),
                self._make_skill_audit("beta-skill"),
            ],
        )
        stable = result.stable_json()
        assert "generated_at" not in stable
        assert "total" in stable
        assert "skills" in stable

    def test_stable_json_is_sorted_by_key(self) -> None:
        result = ModelFeatureDashboardResult(
            generated_at="2026-03-03T00:00:00Z",
            total=1,
            wired=1,
            partial=0,
            broken=0,
            unknown=0,
            failed=False,
            fail_reason=None,
            skills=[self._make_skill_audit("alpha-skill")],
        )
        stable = result.stable_json()
        keys = list(stable.keys())
        assert keys == sorted(keys)

    def test_fail_reason_none(self) -> None:
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
        assert result.fail_reason is None

    def test_fail_reason_set(self) -> None:
        result = ModelFeatureDashboardResult(
            generated_at="2026-03-03T00:00:00Z",
            total=3,
            wired=0,
            partial=0,
            broken=3,
            unknown=0,
            failed=True,
            fail_reason="broken count 3 exceeds threshold 0",
            skills=[],
        )
        assert result.failed is True
        assert result.fail_reason == "broken count 3 exceeds threshold 0"

    def test_skills_alphabetical_ordering_preserved(self) -> None:
        """The model stores skills in whatever order it receives them;
        callers are responsible for sorting alphabetically before construction."""
        skills = [
            self._make_skill_audit("alpha-skill"),
            self._make_skill_audit("beta-skill"),
            self._make_skill_audit("charlie-skill"),
        ]
        result = ModelFeatureDashboardResult(
            generated_at="2026-03-03T00:00:00Z",
            total=3,
            wired=3,
            partial=0,
            broken=0,
            unknown=0,
            failed=False,
            fail_reason=None,
            skills=skills,
        )
        names = [s.name for s in result.skills]
        assert names == ["alpha-skill", "beta-skill", "charlie-skill"]


# ---------------------------------------------------------------------------
# ModelContractYaml helpers
# ---------------------------------------------------------------------------


class TestModelContractYaml:
    def test_minimal_parse(self) -> None:
        contract = ModelContractYaml(name="my-skill", node_type="orchestrator")
        assert contract.name == "my-skill"
        assert contract.node_type == "orchestrator"
        assert contract.event_bus is None
        assert contract.metadata is None

    def test_with_event_bus(self) -> None:
        contract = ModelContractYaml(
            name="my-skill",
            node_type="effect",
            event_bus={"subscribe_topics": ["onex.cmd.foo.v1"], "publish_topics": ["onex.evt.foo.v1"]},
        )
        assert contract.event_bus is not None
        assert contract.event_bus.subscribe_topics == ["onex.cmd.foo.v1"]
        assert contract.event_bus.publish_topics == ["onex.evt.foo.v1"]

    def test_with_metadata_ticket(self) -> None:
        contract = ModelContractYaml(
            name="my-skill",
            node_type="compute",
            metadata={"ticket": "OMN-1234"},
        )
        assert contract.metadata is not None
        assert contract.metadata.ticket == "OMN-1234"

    def test_extra_fields_allowed(self) -> None:
        """extra='allow' means unknown fields are stored, not rejected."""
        contract = ModelContractYaml(
            name="my-skill",
            node_type="reducer",
            some_future_field="future_value",  # type: ignore[call-arg]
        )
        assert contract.name == "my-skill"


class TestModelEventBus:
    def test_defaults_to_empty_lists(self) -> None:
        bus = ModelEventBus()
        assert bus.subscribe_topics == []
        assert bus.publish_topics == []

    def test_extra_fields_allowed(self) -> None:
        bus = ModelEventBus(
            subscribe_topics=["onex.cmd.x.v1"],
            consumer_group="my-group",  # type: ignore[call-arg]
        )
        assert bus.subscribe_topics == ["onex.cmd.x.v1"]


class TestModelContractMetadata:
    def test_ticket_defaults_to_none(self) -> None:
        meta = ModelContractMetadata()
        assert meta.ticket is None

    def test_ticket_set(self) -> None:
        meta = ModelContractMetadata(ticket="OMN-9999")
        assert meta.ticket == "OMN-9999"

    def test_extra_fields_allowed(self) -> None:
        meta = ModelContractMetadata(ticket="OMN-1234", owner="team-x")  # type: ignore[call-arg]
        assert meta.ticket == "OMN-1234"
