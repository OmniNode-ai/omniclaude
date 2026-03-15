# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for node type classifier and applicability matrix (OMN-3500).

Test markers:
    @pytest.mark.unit -- all tests here

Coverage:
    1. Constants: ORCHESTRATOR_TYPES, EFFECT_TYPES, UNKNOWN_TYPE correct values
    2. requires_event_bus: orchestrator + event_bus present → True
    3. requires_event_bus: orchestrator + event_bus absent → False
    4. requires_event_bus: effect node + event_bus present → False
    5. requires_event_bus: effect node + event_bus absent → False
    6. requires_event_bus: unknown node + event_bus present → False
    7. applicable_checks: orchestrator with event_bus → all checks apply (no overrides)
    8. applicable_checks: orchestrator without event_bus → no topic checks
    9. applicable_checks: effect node → only universal checks apply
    10. applicable_checks: unknown node → universal checks apply, topic checks WARN
    11. applicable_checks: unknown node → event_bus_present check WARN
    12. applicable_checks: check ordering is deterministic
    13. applicable_checks: ORCHESTRATOR_GENERIC is in ORCHESTRATOR_TYPES
    14. applicable_checks: EFFECT_GENERIC is in EFFECT_TYPES
    15. Package-level __init__ re-exports all classifier symbols
"""

from __future__ import annotations

import pytest

import omniclaude.nodes.node_skill_feature_dashboard_orchestrator as pkg
from omniclaude.nodes.node_skill_feature_dashboard_orchestrator.classifier import (
    EFFECT_TYPES,
    ORCHESTRATOR_TYPES,
    UNKNOWN_TYPE,
    applicable_checks,
    requires_event_bus,
)
from omniclaude.nodes.node_skill_feature_dashboard_orchestrator.models.model_result import (
    AuditCheckName,
    AuditCheckStatus,
    ModelEventBus,
)

# All tests in this module are unit tests
pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def empty_event_bus() -> ModelEventBus:
    """An event_bus block with empty topic lists (key present, lists empty)."""
    return ModelEventBus(subscribe_topics=[], publish_topics=[])


@pytest.fixture
def populated_event_bus() -> ModelEventBus:
    """An event_bus block with non-empty topic lists."""
    return ModelEventBus(
        subscribe_topics=["omni.cmd.skill.invoke.v1"],
        publish_topics=["omni.evt.skill.completed.v1"],
    )


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_orchestrator_types_contains_generic(self) -> None:
        assert "ORCHESTRATOR_GENERIC" in ORCHESTRATOR_TYPES

    def test_effect_types_contains_generic(self) -> None:
        assert "EFFECT_GENERIC" in EFFECT_TYPES

    def test_unknown_type_sentinel(self) -> None:
        assert UNKNOWN_TYPE == "unknown"

    def test_orchestrator_types_is_frozenset(self) -> None:
        assert isinstance(ORCHESTRATOR_TYPES, frozenset)

    def test_effect_types_is_frozenset(self) -> None:
        assert isinstance(EFFECT_TYPES, frozenset)

    def test_orchestrator_and_effect_types_are_disjoint(self) -> None:
        assert ORCHESTRATOR_TYPES.isdisjoint(EFFECT_TYPES)

    def test_unknown_not_in_orchestrator_types(self) -> None:
        assert UNKNOWN_TYPE not in ORCHESTRATOR_TYPES

    def test_unknown_not_in_effect_types(self) -> None:
        assert UNKNOWN_TYPE not in EFFECT_TYPES


# ---------------------------------------------------------------------------
# requires_event_bus
# ---------------------------------------------------------------------------


class TestRequiresEventBus:
    def test_orchestrator_with_event_bus_block(
        self, empty_event_bus: ModelEventBus
    ) -> None:
        """Orchestrator + event_bus key present → True (even if lists are empty)."""
        assert requires_event_bus("ORCHESTRATOR_GENERIC", empty_event_bus) is True

    def test_orchestrator_with_populated_event_bus(
        self, populated_event_bus: ModelEventBus
    ) -> None:
        assert requires_event_bus("ORCHESTRATOR_GENERIC", populated_event_bus) is True

    def test_orchestrator_without_event_bus_block(self) -> None:
        """Orchestrator + event_bus key absent → False."""
        assert requires_event_bus("ORCHESTRATOR_GENERIC", None) is False

    def test_effect_with_event_bus_block(self, empty_event_bus: ModelEventBus) -> None:
        """Effect node + event_bus key present → False (effects are not event-driven)."""
        assert requires_event_bus("EFFECT_GENERIC", empty_event_bus) is False

    def test_effect_without_event_bus_block(self) -> None:
        assert requires_event_bus("EFFECT_GENERIC", None) is False

    def test_unknown_with_event_bus_block(self, empty_event_bus: ModelEventBus) -> None:
        """Unknown node + event_bus key present → False."""
        assert requires_event_bus("SOMETHING_UNKNOWN", empty_event_bus) is False

    def test_unknown_without_event_bus_block(self) -> None:
        assert requires_event_bus("SOMETHING_UNKNOWN", None) is False

    def test_empty_string_node_type(self) -> None:
        assert requires_event_bus("", None) is False

    def test_case_sensitive_node_type(self, empty_event_bus: ModelEventBus) -> None:
        """Node type matching is case-sensitive."""
        assert requires_event_bus("orchestrator_generic", empty_event_bus) is False


# ---------------------------------------------------------------------------
# applicable_checks — Orchestrator + event_bus present
# ---------------------------------------------------------------------------


class TestApplicableChecksOrchestratorWithEventBus:
    def test_all_checks_present(self, empty_event_bus: ModelEventBus) -> None:
        checks = applicable_checks("ORCHESTRATOR_GENERIC", empty_event_bus)
        for check in AuditCheckName:
            assert check in checks, f"Expected {check} to be in applicable_checks"

    def test_no_status_overrides(self, empty_event_bus: ModelEventBus) -> None:
        """All checks should have None override (no downgrade)."""
        checks = applicable_checks("ORCHESTRATOR_GENERIC", empty_event_bus)
        for check, override in checks.items():
            assert override is None, f"Expected no override for {check}, got {override}"

    def test_universal_checks_present(self, empty_event_bus: ModelEventBus) -> None:
        checks = applicable_checks("ORCHESTRATOR_GENERIC", empty_event_bus)
        assert AuditCheckName.SKILL_MD in checks
        assert AuditCheckName.ORCHESTRATOR_NODE in checks
        assert AuditCheckName.CONTRACT_YAML in checks
        assert AuditCheckName.TEST_COVERAGE in checks
        assert AuditCheckName.LINEAR_TICKET in checks

    def test_orchestrator_checks_present(self, empty_event_bus: ModelEventBus) -> None:
        checks = applicable_checks("ORCHESTRATOR_GENERIC", empty_event_bus)
        assert AuditCheckName.EVENT_BUS_PRESENT in checks

    def test_topic_checks_present(self, empty_event_bus: ModelEventBus) -> None:
        checks = applicable_checks("ORCHESTRATOR_GENERIC", empty_event_bus)
        assert AuditCheckName.TOPICS_NONEMPTY in checks
        assert AuditCheckName.TOPICS_NAMESPACED in checks


# ---------------------------------------------------------------------------
# applicable_checks — Orchestrator without event_bus
# ---------------------------------------------------------------------------


class TestApplicableChecksOrchestratorWithoutEventBus:
    def test_event_bus_present_check_included(self) -> None:
        """event_bus_present check still applies to orchestrators (even without event_bus)."""
        checks = applicable_checks("ORCHESTRATOR_GENERIC", None)
        # The event_bus_present check should be present (it checks *whether* event_bus is declared)
        assert AuditCheckName.EVENT_BUS_PRESENT in checks

    def test_topic_checks_absent(self) -> None:
        """topics_nonempty and topics_namespaced do NOT apply when event_bus is absent."""
        checks = applicable_checks("ORCHESTRATOR_GENERIC", None)
        assert AuditCheckName.TOPICS_NONEMPTY not in checks
        assert AuditCheckName.TOPICS_NAMESPACED not in checks

    def test_universal_checks_present(self) -> None:
        checks = applicable_checks("ORCHESTRATOR_GENERIC", None)
        assert AuditCheckName.SKILL_MD in checks
        assert AuditCheckName.ORCHESTRATOR_NODE in checks
        assert AuditCheckName.CONTRACT_YAML in checks
        assert AuditCheckName.TEST_COVERAGE in checks
        assert AuditCheckName.LINEAR_TICKET in checks

    def test_no_overrides_on_present_checks(self) -> None:
        checks = applicable_checks("ORCHESTRATOR_GENERIC", None)
        for check, override in checks.items():
            assert override is None, f"Expected no override for {check}, got {override}"


# ---------------------------------------------------------------------------
# applicable_checks — Effect node
# ---------------------------------------------------------------------------


class TestApplicableChecksEffectNode:
    def test_only_universal_checks_apply(self) -> None:
        checks = applicable_checks("EFFECT_GENERIC", None)
        expected = {
            AuditCheckName.SKILL_MD,
            AuditCheckName.ORCHESTRATOR_NODE,
            AuditCheckName.CONTRACT_YAML,
            AuditCheckName.TEST_COVERAGE,
            AuditCheckName.LINEAR_TICKET,
        }
        assert set(checks.keys()) == expected

    def test_event_bus_checks_absent(self) -> None:
        checks = applicable_checks("EFFECT_GENERIC", None)
        assert AuditCheckName.EVENT_BUS_PRESENT not in checks
        assert AuditCheckName.TOPICS_NONEMPTY not in checks
        assert AuditCheckName.TOPICS_NAMESPACED not in checks

    def test_effect_with_event_bus_block_no_topic_checks(
        self, empty_event_bus: ModelEventBus
    ) -> None:
        """Even if event_bus block is present, effect nodes don't get topic checks."""
        checks = applicable_checks("EFFECT_GENERIC", empty_event_bus)
        assert AuditCheckName.TOPICS_NONEMPTY not in checks
        assert AuditCheckName.TOPICS_NAMESPACED not in checks
        assert AuditCheckName.EVENT_BUS_PRESENT not in checks

    def test_no_overrides(self) -> None:
        checks = applicable_checks("EFFECT_GENERIC", None)
        for check, override in checks.items():
            assert override is None, f"Expected no override for {check}, got {override}"


# ---------------------------------------------------------------------------
# applicable_checks — Unknown node type
# ---------------------------------------------------------------------------


class TestApplicableChecksUnknownNode:
    def test_universal_checks_present_with_no_override(self) -> None:
        """Universal checks apply to unknown types with no override."""
        checks = applicable_checks("SOMETHING_UNKNOWN", None)
        for check in [
            AuditCheckName.SKILL_MD,
            AuditCheckName.ORCHESTRATOR_NODE,
            AuditCheckName.CONTRACT_YAML,
            AuditCheckName.TEST_COVERAGE,
            AuditCheckName.LINEAR_TICKET,
        ]:
            assert check in checks
            assert checks[check] is None

    def test_event_bus_present_downgraded_to_warn(self) -> None:
        """Unknown type: event_bus_present check is present but downgraded to WARN."""
        checks = applicable_checks("SOMETHING_UNKNOWN", None)
        assert AuditCheckName.EVENT_BUS_PRESENT in checks
        assert checks[AuditCheckName.EVENT_BUS_PRESENT] == AuditCheckStatus.WARN

    def test_topic_checks_downgraded_to_warn(self) -> None:
        """Unknown type: topic checks are present but downgraded to WARN."""
        checks = applicable_checks("SOMETHING_UNKNOWN", None)
        assert AuditCheckName.TOPICS_NONEMPTY in checks
        assert checks[AuditCheckName.TOPICS_NONEMPTY] == AuditCheckStatus.WARN
        assert AuditCheckName.TOPICS_NAMESPACED in checks
        assert checks[AuditCheckName.TOPICS_NAMESPACED] == AuditCheckStatus.WARN

    def test_unknown_with_event_bus_block_topic_checks_still_warn(
        self, empty_event_bus: ModelEventBus
    ) -> None:
        """Even with event_bus block, unknown node topic checks are WARN."""
        checks = applicable_checks("SOMETHING_UNKNOWN", empty_event_bus)
        assert checks[AuditCheckName.TOPICS_NONEMPTY] == AuditCheckStatus.WARN
        assert checks[AuditCheckName.TOPICS_NAMESPACED] == AuditCheckStatus.WARN

    def test_unknown_type_sentinel_downgrades(self) -> None:
        """The UNKNOWN_TYPE constant itself is treated as an unknown node type."""
        checks = applicable_checks(UNKNOWN_TYPE, None)
        assert checks[AuditCheckName.EVENT_BUS_PRESENT] == AuditCheckStatus.WARN
        assert checks[AuditCheckName.TOPICS_NONEMPTY] == AuditCheckStatus.WARN
        assert checks[AuditCheckName.TOPICS_NAMESPACED] == AuditCheckStatus.WARN

    def test_all_eight_checks_present_for_unknown(self) -> None:
        """Unknown type should still have all 8 checks, some with WARN overrides."""
        checks = applicable_checks("SOMETHING_UNKNOWN", None)
        for check in AuditCheckName:
            assert check in checks, (
                f"Expected {check} to be present for unknown node type"
            )


# ---------------------------------------------------------------------------
# Return type and determinism
# ---------------------------------------------------------------------------


class TestApplicableChecksContract:
    def test_returns_dict(self, empty_event_bus: ModelEventBus) -> None:
        result = applicable_checks("ORCHESTRATOR_GENERIC", empty_event_bus)
        assert isinstance(result, dict)

    def test_keys_are_audit_check_names(self, empty_event_bus: ModelEventBus) -> None:
        checks = applicable_checks("ORCHESTRATOR_GENERIC", empty_event_bus)
        for key in checks:
            assert isinstance(key, AuditCheckName)

    def test_values_are_none_or_audit_check_status(self) -> None:
        checks = applicable_checks("SOMETHING_UNKNOWN", None)
        for value in checks.values():
            assert value is None or isinstance(value, AuditCheckStatus)

    def test_deterministic_for_same_inputs(
        self, empty_event_bus: ModelEventBus
    ) -> None:
        """Calling applicable_checks twice with same inputs returns same dict."""
        checks1 = applicable_checks("ORCHESTRATOR_GENERIC", empty_event_bus)
        checks2 = applicable_checks("ORCHESTRATOR_GENERIC", empty_event_bus)
        assert checks1 == checks2

    def test_deterministic_for_none_event_bus(self) -> None:
        checks1 = applicable_checks("EFFECT_GENERIC", None)
        checks2 = applicable_checks("EFFECT_GENERIC", None)
        assert checks1 == checks2


# ---------------------------------------------------------------------------
# Package-level re-exports
# ---------------------------------------------------------------------------


class TestPackageReExports:
    def test_orchestrator_types_exported(self) -> None:
        assert hasattr(pkg, "ORCHESTRATOR_TYPES")
        assert pkg.ORCHESTRATOR_TYPES is ORCHESTRATOR_TYPES

    def test_effect_types_exported(self) -> None:
        assert hasattr(pkg, "EFFECT_TYPES")
        assert pkg.EFFECT_TYPES is EFFECT_TYPES

    def test_unknown_type_exported(self) -> None:
        assert hasattr(pkg, "UNKNOWN_TYPE")
        assert pkg.UNKNOWN_TYPE is UNKNOWN_TYPE

    def test_requires_event_bus_exported(self) -> None:
        assert hasattr(pkg, "requires_event_bus")
        assert pkg.requires_event_bus is requires_event_bus

    def test_applicable_checks_exported(self) -> None:
        assert hasattr(pkg, "applicable_checks")
        assert pkg.applicable_checks is applicable_checks
