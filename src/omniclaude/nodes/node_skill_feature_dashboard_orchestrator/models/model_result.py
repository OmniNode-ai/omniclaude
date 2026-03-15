# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Canonical result model for the Feature Dashboard orchestrator node.

This module defines all enums, audit check models, gap models, and the
top-level result model used by the feature-dashboard skill.

Model Ownership:
    These models are PRIVATE to omniclaude.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class AuditCheckName(StrEnum):
    SKILL_MD = "skill_md"
    ORCHESTRATOR_NODE = "orchestrator_node"
    CONTRACT_YAML = "contract_yaml"
    EVENT_BUS_PRESENT = "event_bus_present"
    TOPICS_NONEMPTY = "topics_nonempty"
    TOPICS_NAMESPACED = "topics_namespaced"
    TEST_COVERAGE = "test_coverage"
    LINEAR_TICKET = "linear_ticket"


class AuditCheckStatus(StrEnum):
    PASS = "pass"  # noqa: S105
    FAIL = "fail"
    WARN = "warn"


class SkillStatus(StrEnum):
    WIRED = "wired"
    PARTIAL = "partial"
    BROKEN = "broken"
    UNKNOWN = "unknown"


class GapSeverity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ModelAuditCheck(BaseModel, frozen=True):
    """A single audit check result for a skill."""

    name: AuditCheckName
    status: AuditCheckStatus
    message: str | None = None
    evidence: list[str]  # REQUIRED: >=1 entry for every PASS or FAIL


class ModelGap(BaseModel, frozen=True):
    """A gap identified in a skill audit."""

    layer: AuditCheckName
    severity: GapSeverity
    message: str
    suggested_fix: str | None = None


class ModelSkillAudit(BaseModel, frozen=True):
    """Audit result for a single skill."""

    name: str  # kebab-case
    slug: str  # snake_case
    node_type: str  # from contract.yaml node_type field, or "unknown"
    status: SkillStatus
    checks: list[ModelAuditCheck]
    gaps: list[ModelGap]


class ModelFeatureDashboardResult(BaseModel, frozen=True):
    """Top-level result model for the feature dashboard.

    Stable JSON rule: model dump excluding ``generated_at``, with ``sort_keys=True``.
    Skills are sorted alphabetically by name (deterministic ordering).
    """

    schema_version: str = "1.0.0"
    generated_at: str  # ISO-8601; EXCLUDED from stable JSON
    total: int
    wired: int
    partial: int
    broken: int
    unknown: int
    failed: bool  # True if --fail-on threshold exceeded
    fail_reason: str | None
    skills: list[ModelSkillAudit]  # sorted by name (alphabetical, deterministic)

    def stable_json(self) -> dict[str, object]:
        """Return a stable JSON-serializable dict, excluding ``generated_at``."""
        data = self.model_dump(exclude={"generated_at"})
        return dict(sorted(data.items()))


# ---------------------------------------------------------------------------
# Contract YAML parsing helpers
# These are NOT committed nodes; they exist solely to parse contract.yaml files.
# ---------------------------------------------------------------------------


class ModelEventBus(BaseModel, extra="allow"):
    """Parsed event_bus section from a contract.yaml file."""

    subscribe_topics: list[str] = Field(default_factory=list)
    publish_topics: list[str] = Field(default_factory=list)


class ModelContractMetadata(BaseModel, extra="allow"):
    """Parsed metadata section from a contract.yaml file."""

    ticket: str | None = None


class ModelContractYaml(BaseModel, extra="allow"):
    """Parsed representation of a skill contract.yaml file."""

    name: str
    node_type: str
    event_bus: ModelEventBus | None = None
    metadata: ModelContractMetadata | None = None


__all__ = [
    "AuditCheckName",
    "AuditCheckStatus",
    "GapSeverity",
    "ModelAuditCheck",
    "ModelContractMetadata",
    "ModelContractYaml",
    "ModelEventBus",
    "ModelFeatureDashboardResult",
    "ModelGap",
    "ModelSkillAudit",
    "SkillStatus",
]
