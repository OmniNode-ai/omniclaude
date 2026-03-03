# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Node type classifier and applicability matrix for the Feature Dashboard orchestrator.

This module determines which audit checks apply to each skill, preventing the dashboard
from making incorrect assessments by applying topic checks to non-event-driven nodes.

**Source**: Plan section "Node Type Classifier and Applicability Rules" (OMN-3500)
"""

from __future__ import annotations

from omniclaude.nodes.node_skill_feature_dashboard_orchestrator.models.model_result import (
    AuditCheckName,
    AuditCheckStatus,
    ModelEventBus,
)

# ---------------------------------------------------------------------------
# Node type constants
# ---------------------------------------------------------------------------

ORCHESTRATOR_TYPES: frozenset[str] = frozenset({"ORCHESTRATOR_GENERIC"})
EFFECT_TYPES: frozenset[str] = frozenset({"EFFECT_GENERIC"})
UNKNOWN_TYPE: str = "unknown"

# All audit check names (in definition order)
_ALL_CHECKS: tuple[AuditCheckName, ...] = (
    AuditCheckName.SKILL_MD,
    AuditCheckName.ORCHESTRATOR_NODE,
    AuditCheckName.CONTRACT_YAML,
    AuditCheckName.EVENT_BUS_PRESENT,
    AuditCheckName.TOPICS_NONEMPTY,
    AuditCheckName.TOPICS_NAMESPACED,
    AuditCheckName.TEST_COVERAGE,
    AuditCheckName.LINEAR_TICKET,
)

# Checks that apply to ALL skills regardless of node type
_UNIVERSAL_CHECKS: frozenset[AuditCheckName] = frozenset(
    {
        AuditCheckName.SKILL_MD,
        AuditCheckName.ORCHESTRATOR_NODE,
        AuditCheckName.CONTRACT_YAML,
        AuditCheckName.TEST_COVERAGE,
        AuditCheckName.LINEAR_TICKET,
    }
)

# Checks that apply ONLY to orchestrator nodes (regardless of event bus)
_ORCHESTRATOR_ONLY_CHECKS: frozenset[AuditCheckName] = frozenset(
    {
        AuditCheckName.EVENT_BUS_PRESENT,
    }
)

# Checks that apply ONLY to orchestrator nodes where requires_event_bus = True
_EVENT_BUS_REQUIRED_CHECKS: frozenset[AuditCheckName] = frozenset(
    {
        AuditCheckName.TOPICS_NONEMPTY,
        AuditCheckName.TOPICS_NAMESPACED,
    }
)


# ---------------------------------------------------------------------------
# Event bus detection
# ---------------------------------------------------------------------------


def requires_event_bus(node_type: str, event_bus_block: ModelEventBus | None) -> bool:
    """Return True if this node is expected to declare event bus topics.

    An event-driven node is one that:
    - Has ``node_type`` in ``ORCHESTRATOR_TYPES``, AND
    - Has the ``event_bus`` key present in contract.yaml (even if lists are empty).

    Non-event-driven nodes (effects, helpers) are not required to declare topics.

    Args:
        node_type: The ``node_type`` value from contract.yaml (e.g. ``"ORCHESTRATOR_GENERIC"``).
        event_bus_block: The parsed ``event_bus`` section from contract.yaml, or ``None`` if
            the key was absent.

    Returns:
        ``True`` if the node is an orchestrator with an event_bus block present;
        ``False`` otherwise.
    """
    return node_type in ORCHESTRATOR_TYPES and event_bus_block is not None


# ---------------------------------------------------------------------------
# Applicability matrix
# ---------------------------------------------------------------------------


def applicable_checks(
    node_type: str,
    event_bus_block: ModelEventBus | None,
) -> dict[AuditCheckName, AuditCheckStatus | None]:
    """Return the applicability map for this skill's audit checks.

    The returned dict maps each ``AuditCheckName`` to:
    - ``None``   — check applies normally (no status override)
    - ``AuditCheckStatus.WARN`` — check applies but result is downgraded to WARN
      (used for unknown node types where topic checks are unreliable)

    Applicability matrix (check → applies to):

    - skill_md: All skills
    - orchestrator_node: All skills
    - contract_yaml: All skills
    - event_bus_present: Orchestrator nodes only
    - topics_nonempty: Orchestrator nodes where requires_event_bus=True
    - topics_namespaced: Orchestrator nodes where requires_event_bus=True
    - test_coverage: All skills
    - linear_ticket: All skills

    Unknown node types: only universal checks apply; topic checks are downgraded to WARN.

    Args:
        node_type: The ``node_type`` value from contract.yaml.
        event_bus_block: The parsed ``event_bus`` section from contract.yaml, or ``None``
            if the key was absent.

    Returns:
        Dict mapping each ``AuditCheckName`` to its applicability override status (or None).
        Checks NOT present in the returned dict are NOT applicable and should be skipped.
    """
    is_orchestrator = node_type in ORCHESTRATOR_TYPES
    is_unknown = node_type not in ORCHESTRATOR_TYPES and node_type not in EFFECT_TYPES
    event_driven = requires_event_bus(node_type, event_bus_block)

    result: dict[AuditCheckName, AuditCheckStatus | None] = {}

    # Universal checks always apply
    for check in _UNIVERSAL_CHECKS:
        if is_unknown and check not in {
            AuditCheckName.SKILL_MD,
            AuditCheckName.ORCHESTRATOR_NODE,
            AuditCheckName.CONTRACT_YAML,
            AuditCheckName.TEST_COVERAGE,
            AuditCheckName.LINEAR_TICKET,
        }:
            # All universal checks apply even for unknown types — no status override needed
            result[check] = None
        else:
            result[check] = None

    # Orchestrator-only checks
    if is_orchestrator:
        for check in _ORCHESTRATOR_ONLY_CHECKS:
            result[check] = None
    elif is_unknown:
        # Unknown type: downgrade orchestrator-only checks to WARN
        for check in _ORCHESTRATOR_ONLY_CHECKS:
            result[check] = AuditCheckStatus.WARN

    # Event-bus-required checks
    if event_driven:
        for check in _EVENT_BUS_REQUIRED_CHECKS:
            result[check] = None
    elif is_unknown:
        # Unknown type: downgrade topic checks to WARN
        for check in _EVENT_BUS_REQUIRED_CHECKS:
            result[check] = AuditCheckStatus.WARN

    return result


__all__ = [
    "EFFECT_TYPES",
    "ORCHESTRATOR_TYPES",
    "UNKNOWN_TYPE",
    "applicable_checks",
    "requires_event_bus",
]
