# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Node type classifier and applicability matrix for the Feature Dashboard orchestrator.

This module determines which audit checks apply to each skill, preventing the dashboard
from making incorrect assessments by applying topic checks to non-event-driven nodes.

**Source**: Plan section "Node Type Classifier and Applicability Rules" (OMN-3500)
"""

from __future__ import annotations

from collections import defaultdict

from omniclaude.nodes.node_skill_feature_dashboard_orchestrator.models.model_result import (
    BATCH_SEVERITY_THRESHOLD,
    AuditCheckName,
    AuditCheckStatus,
    GapSeverity,
    ModelBatchedGapTicket,
    ModelEventBus,
    ModelGap,
    ModelSkillAudit,
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

    Unknown node types: universal checks apply normally; orchestrator-only and
    event-bus-required checks are included with WARN overrides.

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


# ---------------------------------------------------------------------------
# Ticketize gap batching (OMN-6163)
# ---------------------------------------------------------------------------

# Severity ordering for worst-severity computation (lower index = higher severity)
_SEVERITY_ORDER: dict[GapSeverity, int] = {
    GapSeverity.CRITICAL: 0,
    GapSeverity.HIGH: 1,
    GapSeverity.MEDIUM: 2,
    GapSeverity.LOW: 3,
}


def _worst_severity(severities: set[GapSeverity]) -> GapSeverity:
    """Return the most severe severity from a set.

    Args:
        severities: Non-empty set of gap severities.

    Returns:
        The highest (most severe) severity value.
    """
    return min(severities, key=lambda s: _SEVERITY_ORDER[s])


def batch_gaps_for_ticketize(
    skills: list[ModelSkillAudit],
    *,
    batch: bool = True,
) -> list[ModelBatchedGapTicket]:
    """Produce ticket descriptors from audit results, optionally batching identical low-severity gaps.

    When ``batch=True`` (default):
    - CRITICAL and HIGH gaps produce one ticket per skill (unchanged from original behavior).
    - MEDIUM and LOW gaps with identical ``(layer, message)`` across multiple skills are grouped
      into a single batched ticket listing all affected skills.
    - MEDIUM and LOW gaps that are unique to a single skill still produce a per-skill ticket.

    When ``batch=False``:
    - Original behavior: one ticket per skill with gaps, regardless of severity.

    Args:
        skills: List of ``ModelSkillAudit`` results (typically from ``ModelFeatureDashboardResult.skills``).
        batch: Whether to batch identical low-severity gaps. Defaults to ``True``.

    Returns:
        List of ``ModelBatchedGapTicket`` descriptors, sorted by worst severity then title.
    """
    # Filter to skills that have gaps (partial or broken)
    skills_with_gaps = [s for s in skills if s.gaps]

    if not skills_with_gaps:
        return []

    if not batch:
        # Original behavior: one ticket per skill
        return _unbatched_tickets(skills_with_gaps)

    # Split gaps into high-severity (per-skill) and low-severity (batchable)
    per_skill_tickets: list[ModelBatchedGapTicket] = []
    # Key: (layer, message) -> list of (skill_name, gap)
    batchable: dict[tuple[AuditCheckName, str], list[tuple[str, ModelGap]]] = (
        defaultdict(list)
    )

    for skill in skills_with_gaps:
        high_gaps = [g for g in skill.gaps if g.severity in BATCH_SEVERITY_THRESHOLD]
        low_gaps = [g for g in skill.gaps if g.severity not in BATCH_SEVERITY_THRESHOLD]

        # Per-skill ticket for CRITICAL/HIGH gaps
        if high_gaps:
            severities = {g.severity for g in high_gaps}
            worst = _worst_severity(severities)
            gap_lines = _format_gap_lines(high_gaps)
            per_skill_tickets.append(
                ModelBatchedGapTicket(
                    title=f"[Feature Dashboard] {skill.name}: {worst} gaps ({len(high_gaps)} total)",
                    description=gap_lines,
                    is_batched=False,
                    affected_skills=[skill.name],
                    gap_count=len(high_gaps),
                    worst_severity=worst,
                ),
            )

        # Collect batchable gaps
        for gap in low_gaps:
            batchable[(gap.layer, gap.message)].append((skill.name, gap))

    # Build batched tickets from collected low-severity gaps
    batched_tickets: list[ModelBatchedGapTicket] = []
    for (layer, message), entries in sorted(batchable.items()):
        skill_names = sorted({name for name, _ in entries})
        severities = {gap.severity for _, gap in entries}
        worst = _worst_severity(severities)
        representative_gap = entries[0][1]

        if len(skill_names) == 1:
            # Single skill -- not really a batch, but still a separate ticket
            gap_lines = _format_gap_lines([gap for _, gap in entries])
            batched_tickets.append(
                ModelBatchedGapTicket(
                    title=f"[Feature Dashboard] {skill_names[0]}: {worst} gap — {message}",
                    description=gap_lines,
                    is_batched=False,
                    affected_skills=skill_names,
                    gap_count=len(entries),
                    worst_severity=worst,
                ),
            )
        else:
            # Batched ticket for identical gap across multiple skills
            skill_list_md = "\n".join(f"- `{name}`" for name in skill_names)
            fix_line = (
                f"\n\n**Suggested fix:** {representative_gap.suggested_fix}"
                if representative_gap.suggested_fix
                else ""
            )
            description = (
                f"## Gap: {message}\n\n"
                f"**Layer:** `{layer}`  \n"
                f"**Severity:** {worst}  \n"
                f"**Affected skills ({len(skill_names)}):**\n\n"
                f"{skill_list_md}"
                f"{fix_line}"
            )
            batched_tickets.append(
                ModelBatchedGapTicket(
                    title=(
                        f"[Feature Dashboard] {worst} gap: {message} "
                        f"({len(skill_names)} skills)"
                    ),
                    description=description,
                    is_batched=True,
                    affected_skills=skill_names,
                    gap_count=len(entries),
                    worst_severity=worst,
                ),
            )

    all_tickets = per_skill_tickets + batched_tickets
    # Sort by severity (worst first), then by title for determinism
    all_tickets.sort(key=lambda t: (_SEVERITY_ORDER[t.worst_severity], t.title))
    return all_tickets


def _unbatched_tickets(
    skills_with_gaps: list[ModelSkillAudit],
) -> list[ModelBatchedGapTicket]:
    """Original (pre-OMN-6163) behavior: one ticket per skill with gaps."""
    tickets: list[ModelBatchedGapTicket] = []
    for skill in skills_with_gaps:
        severities = {g.severity for g in skill.gaps}
        worst = _worst_severity(severities)
        gap_lines = _format_gap_lines(list(skill.gaps))
        tickets.append(
            ModelBatchedGapTicket(
                title=f"[Feature Dashboard] {skill.name}: {worst} gaps ({len(skill.gaps)} total)",
                description=gap_lines,
                is_batched=False,
                affected_skills=[skill.name],
                gap_count=len(skill.gaps),
                worst_severity=worst,
            ),
        )
    tickets.sort(key=lambda t: (_SEVERITY_ORDER[t.worst_severity], t.title))
    return tickets


def _format_gap_lines(gaps: list[ModelGap]) -> str:
    """Format a list of gaps as a Markdown description for a ticket."""
    lines: list[str] = []
    for gap in gaps:
        line = f"- **{gap.severity}** (`{gap.layer}`): {gap.message}"
        if gap.suggested_fix:
            line += f"\n  - **Fix:** {gap.suggested_fix}"
        lines.append(line)
    return "\n".join(lines)


__all__ = [
    "EFFECT_TYPES",
    "ORCHESTRATOR_TYPES",
    "UNKNOWN_TYPE",
    "applicable_checks",
    "batch_gaps_for_ticketize",
    "requires_event_bus",
]
