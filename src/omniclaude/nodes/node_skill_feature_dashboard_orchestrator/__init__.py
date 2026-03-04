# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""NodeSkillFeatureDashboardOrchestrator - Feature dashboard skill audit node.

This package provides the orchestrator node, node type classifier, applicability
matrix, and result models for the feature-dashboard skill orchestrator.

Exported Components:
    Node:
        NodeSkillFeatureDashboardOrchestrator - Thin orchestrator shell node
    Classifier:
        ORCHESTRATOR_TYPES  - Set of orchestrator node type strings
        EFFECT_TYPES        - Set of effect node type strings
        UNKNOWN_TYPE        - Sentinel string for unrecognized node types
        requires_event_bus  - Predicate: is this node event-driven?
        applicable_checks   - Returns the applicability map for a node's audit checks
"""

from omniclaude.nodes.node_skill_feature_dashboard_orchestrator.classifier import (
    EFFECT_TYPES,
    ORCHESTRATOR_TYPES,
    UNKNOWN_TYPE,
    applicable_checks,
    requires_event_bus,
)
from omniclaude.nodes.node_skill_feature_dashboard_orchestrator.node import (
    NodeSkillFeatureDashboardOrchestrator,
)

__all__ = [
    "EFFECT_TYPES",
    "NodeSkillFeatureDashboardOrchestrator",
    "ORCHESTRATOR_TYPES",
    "UNKNOWN_TYPE",
    "applicable_checks",
    "requires_event_bus",
]
