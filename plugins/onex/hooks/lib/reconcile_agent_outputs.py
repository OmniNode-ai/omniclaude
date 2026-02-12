"""Reconcile parallel agent outputs using geometric conflict classification.

Provides a standalone helper for merging overlapping outputs from multiple
parallel agents. Uses ``GeometricConflictClassifier`` from omnibase_core when
available, falling back to a lightweight inline classifier otherwise.

Part of OMN-1855: Integrate GeometricConflictClassifier with parallel agent
dispatching.

Design constraints:
    - Zero imports from hook infrastructure (no emit_client_wrapper, no
      correlation_manager, etc.).
    - Importable standalone with no env vars or hook initialisation.
    - All Pydantic models use ``frozen=True``, ``extra="forbid"``.
    - ``emitted_at`` timestamps must be explicitly injected (no
      ``datetime.now()`` defaults).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

# ---------------------------------------------------------------------------
# Classifier import -- omnibase_core may not be installed
# ---------------------------------------------------------------------------

try:
    from omnibase_core.merge.geometric_conflict_classifier import (
        GeometricConflictClassifier,
    )

    _HAS_CLASSIFIER = True
except ImportError:
    _HAS_CLASSIFIER = False

# ---------------------------------------------------------------------------
# Conflict-type constants (used regardless of classifier backend)
# ---------------------------------------------------------------------------

IDENTICAL = "IDENTICAL"
UNCONTESTED = "UNCONTESTED"
ORTHOGONAL = "ORTHOGONAL"
LOW_CONFLICT = "LOW_CONFLICT"
CONFLICTING = "CONFLICTING"
OPPOSITE = "OPPOSITE"
AMBIGUOUS = "AMBIGUOUS"

ConflictType = Literal[
    "IDENTICAL",
    "UNCONTESTED",
    "ORTHOGONAL",
    "LOW_CONFLICT",
    "CONFLICTING",
    "OPPOSITE",
    "AMBIGUOUS",
]

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class FieldDecision(BaseModel):
    """Per-field reconciliation decision.

    Resolution status contract:
        Callers MUST check ``needs_approval`` to determine whether a field was
        resolved.  Do NOT use ``chosen_value is None`` as a proxy for
        "unresolved" -- ``chosen_value`` can legitimately be ``None`` when all
        agents agree on a ``None`` value (e.g. an IDENTICAL classification
        where every agent produced ``None``).

        - ``needs_approval is True``  -> field is unresolved, ``chosen_value``
          is meaningless (set to ``None`` by convention).
        - ``needs_approval is False`` -> field is resolved, ``chosen_value``
          holds the merged result (which may itself be ``None``).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    field: str
    """Dot-path, e.g. ``db.pool.max_size``."""

    conflict_type: ConflictType
    """One of: IDENTICAL, UNCONTESTED, ORTHOGONAL, LOW_CONFLICT, CONFLICTING, OPPOSITE, AMBIGUOUS."""

    sources: tuple[str, ...]
    """Agent names that touched this field."""

    chosen_value: Any | None = None
    """The auto-resolved value, or ``None`` when ``needs_approval`` is ``True``
    (GI-3 enforcement).  Note: a resolved field may also have ``None`` as its
    legitimate value -- always check ``needs_approval``, not this field, to
    determine resolution status."""

    rationale: str
    """Deterministic, short explanation."""

    needs_approval: bool
    """``True`` for OPPOSITE / AMBIGUOUS."""

    needs_review: bool
    """``True`` for CONFLICTING."""


class ReconciliationResult(BaseModel):
    """Aggregate reconciliation output."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    merged_values: dict[str, Any]
    """Only auto-resolved fields included (dot-paths as keys)."""

    field_decisions: dict[str, FieldDecision]
    """Every field gets a decision."""

    requires_approval: bool
    """``True`` if ANY field is OPPOSITE / AMBIGUOUS."""

    approval_fields: tuple[str, ...]
    """Dot-paths needing human approval."""

    optional_review_fields: tuple[str, ...]
    """Dot-paths worth reviewing — includes LOW_CONFLICT (auto-resolved but
    non-trivial) and CONFLICTING (needs human review).  Check the per-field
    FieldDecision.conflict_type to distinguish severity."""

    auto_resolved_fields: tuple[str, ...]
    """Dot-paths safely merged."""

    summary: str
    """Formatted report string."""


# ---------------------------------------------------------------------------
# Flatten / unflatten helpers
# ---------------------------------------------------------------------------


def flatten_to_paths(d: dict, prefix: str = "") -> dict[str, Any]:
    """Flatten nested dict to dot-separated path-value pairs.

    Example::

        {"db": {"pool": {"max_size": 10}}} -> {"db.pool.max_size": 10}

    Non-dict values at any level become leaf entries.

    .. note::

        Empty dicts are dropped during flattening (no leaf children to
        emit).  ``unflatten_paths(flatten_to_paths(d))`` may differ from
        ``d`` when ``d`` contains empty dict values.

    .. note::

        List values (including lists of dicts) are treated as atomic leaf
        values and are not recursed into.  Only ``dict`` values trigger
        recursive descent.

    .. note::

        Keys containing literal dots (e.g. ``{"a.b": 1}``) are
        indistinguishable from nested paths after flattening.  For example,
        ``{"a.b": 1}`` and ``{"a": {"b": 1}}`` both flatten to
        ``{"a.b": 1}``.  This is a known limitation; callers that may
        encounter dotted keys should pre-escape them before calling this
        function.
    """
    result: dict[str, Any] = {}
    for key, value in d.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            result.update(flatten_to_paths(value, full_key))
        else:
            result[full_key] = value
    return result


def unflatten_paths(d: dict[str, Any]) -> dict:
    """Reconstruct nested dict from dot-path keys.

    Example::

        {"db.pool.max_size": 10} -> {"db": {"pool": {"max_size": 10}}}

    This function assumes all paths represent leaf values (as produced by
    :func:`flatten_to_paths`).  Same-depth sibling overwrites of
    intermediate dicts are not detected; callers must ensure that the
    input does not contain paths that would silently overwrite previously
    set intermediate dicts at the same depth.

    Raises:
        ValueError: If paths conflict (e.g. ``{"a.b": 5, "a.b.c": 10}``
            where ``a.b`` is both a leaf value and an intermediate).
    """
    result: dict[str, Any] = {}
    for compound_key, value in sorted(d.items(), key=lambda kv: kv[0].count(".")):
        parts = compound_key.split(".")
        target = result
        for idx, part in enumerate(parts[:-1]):
            existing = target.get(part)
            if existing is not None and not isinstance(existing, dict):
                raise ValueError(
                    f"Conflicting paths: '{'.'.join(parts[: idx + 1])}' "
                    f"is both a leaf and an intermediate in key '{compound_key}'"
                )
            target = target.setdefault(part, {})
        target[parts[-1]] = value
    return result


# ---------------------------------------------------------------------------
# Fallback classifier (used when omnibase_core is not available)
# ---------------------------------------------------------------------------

_ANTONYM_PAIRS: frozenset[frozenset[str]] = frozenset(
    {
        frozenset({"true", "false"}),
        frozenset({"enable", "disable"}),
        frozenset({"enabled", "disabled"}),
        frozenset({"yes", "no"}),
        frozenset({"on", "off"}),
        frozenset({"allow", "deny"}),
        frozenset({"accept", "reject"}),
        frozenset({"open", "close"}),
        frozenset({"start", "stop"}),
    }
)


def _are_antonyms(a: Any, b: Any) -> bool:
    """Return ``True`` if *a* and *b* form a known antonym pair.

    Cross-type comparisons (e.g. ``True`` vs ``"false"``) are never
    antonyms -- they are a type mismatch and should fall through to
    AMBIGUOUS in the caller.
    """
    if type(a) is not type(b):
        return False
    if isinstance(a, bool) and isinstance(b, bool):
        return a != b
    pair = frozenset({str(a).lower().strip(), str(b).lower().strip()})
    return pair in _ANTONYM_PAIRS


def _fallback_classify(base_value: Any, agent_values: dict[str, Any]) -> ConflictType:
    """Lightweight conflict classifier -- no external deps.

    Rules (in order):
        1. All values equal -> IDENTICAL
        2. Contradictory booleans or known antonym pairs -> OPPOSITE
        3. All values are dicts with non-overlapping keys -> ORTHOGONAL
        4. Otherwise -> AMBIGUOUS

    Raises:
        ValueError: If fewer than 2 agent values are provided.
            Classification requires at least 2 agents to compare.
    """
    # Guard: classification is meaningless with fewer than 2 values.
    # Without this, a single-element list would pass the `all(... vals[1:])`
    # check vacuously and be misclassified as IDENTICAL.
    if len(agent_values) < 2:
        raise ValueError(
            f"_fallback_classify requires at least 2 agent values, "
            f"got {len(agent_values)}"
        )

    vals = list(agent_values.values())

    # 1. All identical
    if all(v == vals[0] for v in vals[1:]):
        return IDENTICAL

    # 2. Opposite (booleans / antonym strings) -- only meaningful for 2 values
    if len(vals) == 2 and _are_antonyms(vals[0], vals[1]):
        return OPPOSITE

    # 3. Orthogonal dicts (non-overlapping keys)
    if all(isinstance(v, dict) for v in vals):
        key_sets = [set(v.keys()) for v in vals]  # type: ignore[union-attr]
        all_disjoint = True
        for i in range(len(key_sets)):
            for j in range(i + 1, len(key_sets)):
                if key_sets[i] & key_sets[j]:
                    all_disjoint = False
                    break
            if not all_disjoint:
                break
        if all_disjoint:
            return ORTHOGONAL

    # 4. Everything else
    return AMBIGUOUS


def _classify(
    base_value: Any,
    agent_values: dict[str, Any],
    classifier: Any | None = None,
) -> ConflictType:
    """Dispatch to real classifier or fallback.

    Args:
        base_value: The original value before any agent modifications.
        agent_values: Map of agent_name -> value for this field.
        classifier: Pre-instantiated ``GeometricConflictClassifier``, or
            ``None`` to use the lightweight fallback.
    """
    if classifier is not None:
        # Real classifier expects list[tuple[str, object]], not dict
        values_list = [(name, val) for name, val in sorted(agent_values.items())]
        details = classifier.classify(base_value, values_list)
        # details is ModelGeometricConflictDetails; extract enum name
        return details.conflict_type.name  # type: ignore[return-value]
    return _fallback_classify(base_value, agent_values)


# ---------------------------------------------------------------------------
# Core reconciliation
# ---------------------------------------------------------------------------


def _build_summary(
    auto_resolved: list[str],
    review_fields: list[str],
    approval_fields: list[str],
    field_decisions: dict[str, FieldDecision],
) -> str:
    """Build human-readable reconciliation summary."""
    lines: list[str] = ["Reconciliation Summary:"]

    # Auto-resolved
    if auto_resolved:
        joined = ", ".join(auto_resolved)
        lines.append(f"- Auto-resolved: {len(auto_resolved)} fields [{joined}]")
    else:
        lines.append("- Auto-resolved: 0 fields")

    # Optional review
    if review_fields:
        details = []
        for f in review_fields:
            dec = field_decisions[f]
            details.append(f"{f} ({dec.conflict_type})")
        joined = ", ".join(details)
        lines.append(f"- Optional review: {len(review_fields)} fields [{joined}]")

    # Approval required
    if approval_fields:
        lines.append(f"- REQUIRES APPROVAL: {len(approval_fields)} field(s)")
        for f in approval_fields:
            dec = field_decisions[f]
            lines.append(f"  - {f} ({dec.conflict_type})")

    lines.append("")
    if approval_fields:
        lines.append("Status: REQUIRES HUMAN APPROVAL")
    else:
        lines.append("Status: SAFE TO APPLY")

    return "\n".join(lines)


def reconcile_outputs(
    base_values: dict[str, Any],
    agent_outputs: dict[str, dict[str, Any]],
    logger: Callable[[dict], None] | None = None,
) -> ReconciliationResult:
    """Reconcile parallel agent outputs using geometric conflict classification.

    Args:
        base_values: Original values before agent modifications (nested dict OK).
        agent_outputs: Map of ``agent_name`` -> output dict (nested dict OK).
            Must have at least 2 agents.
        logger: Optional callback for structured log entries. Receives dicts
            like ``{"event": "field_classified", "field": "db.host",
            "conflict_type": "IDENTICAL"}``.

    Returns:
        :class:`ReconciliationResult` with merged values and per-field decisions.

    Raises:
        ValueError: If fewer than 2 agent outputs are provided.

    Algorithm:
        1. Flatten all inputs to dot-paths.
        2. Identify fields touched by 2+ agents (overlapping fields).
        3. For each overlapping field, call classifier.
        4. Route based on ``conflict_type``:
           - IDENTICAL: pick the value (all equal).
           - ORTHOGONAL: dict-merge non-overlapping subkeys; else pick
             lexically-first agent.
           - LOW_CONFLICT: pick lexically-first agent name.
           - CONFLICTING: pick lexically-first agent, flag
             ``needs_review=True``.
           - OPPOSITE: ``chosen_value=None``, ``needs_approval=True``,
             EXCLUDED from ``merged_values``.
           - AMBIGUOUS: ``chosen_value=None``, ``needs_approval=True``,
             EXCLUDED from ``merged_values``.
        5. Fields touched by only 1 agent: auto-include in ``merged_values``.
        6. Generate summary.
    """
    if len(agent_outputs) < 2:
        raise ValueError(
            f"reconcile_outputs requires at least 2 agent outputs, "
            f"got {len(agent_outputs)}"
        )

    # Instantiate the classifier once for the entire reconciliation pass.
    # If omnibase_core is not installed, classifier stays None and _classify
    # will use the lightweight fallback path.
    classifier: Any | None = None
    if _HAS_CLASSIFIER:
        classifier = GeometricConflictClassifier()

    # 1. Flatten
    flat_base = flatten_to_paths(base_values)
    flat_agents: dict[str, dict[str, Any]] = {
        name: flatten_to_paths(output) for name, output in agent_outputs.items()
    }

    # Collect all fields each agent touched
    field_to_agents: dict[str, list[str]] = {}
    for agent_name, flat_output in flat_agents.items():
        for field in flat_output:
            field_to_agents.setdefault(field, []).append(agent_name)

    merged_values: dict[str, Any] = {}
    field_decisions: dict[str, FieldDecision] = {}
    approval_fields: list[str] = []
    review_fields: list[str] = []
    auto_resolved: list[str] = []

    for field, agents in sorted(field_to_agents.items()):
        if len(agents) == 1:
            # 5. Single-agent field -- auto-include (no conflict, uncontested)
            agent = agents[0]
            value = flat_agents[agent][field]
            merged_values[field] = value
            auto_resolved.append(field)
            field_decisions[field] = FieldDecision(
                field=field,
                conflict_type=UNCONTESTED,
                sources=(agent,),
                chosen_value=value,
                rationale=f"Only agent {agent} modified this field.",
                needs_approval=False,
                needs_review=False,
            )
            if logger:
                logger(
                    {
                        "event": "field_classified",
                        "field": field,
                        "conflict_type": UNCONTESTED,
                        "sources": [agent],
                    }
                )
            continue

        # 2-3. Overlapping field -- classify
        sorted_agents = sorted(agents)
        agent_values = {a: flat_agents[a][field] for a in sorted_agents}
        base_val = flat_base.get(field)
        conflict_type = _classify(base_val, agent_values, classifier=classifier)

        if logger:
            logger(
                {
                    "event": "field_classified",
                    "field": field,
                    "conflict_type": conflict_type,
                    "sources": sorted_agents,
                }
            )

        # 4. Route based on conflict_type
        first_agent = sorted_agents[0]

        if conflict_type == IDENTICAL:
            value = agent_values[first_agent]
            merged_values[field] = value
            auto_resolved.append(field)
            field_decisions[field] = FieldDecision(
                field=field,
                conflict_type=IDENTICAL,
                sources=tuple(sorted_agents),
                chosen_value=value,
                rationale="All agents produced the same value.",
                needs_approval=False,
                needs_review=False,
            )

        elif conflict_type == ORTHOGONAL:
            # Dict-merge non-overlapping subkeys when all values are dicts
            vals = list(agent_values.values())
            # Defensive: unreachable via reconcile_outputs (flatten produces
            # leaf values only), but guards against direct _classify callers
            # passing dict values.
            if all(isinstance(v, dict) for v in vals):
                merged: dict[str, Any] = {}
                for v in vals:
                    merged.update(v)  # type: ignore[union-attr]
                merged_values[field] = merged
                value = merged
                ortho_rationale = (
                    f"Agents modified non-overlapping aspects. "
                    f"Merged from: {', '.join(sorted_agents)}."
                )
            else:
                value = agent_values[first_agent]
                merged_values[field] = value
                ortho_rationale = (
                    f"Orthogonal non-dict values; selected from "
                    f"{first_agent} (lexically first)."
                )
            auto_resolved.append(field)
            field_decisions[field] = FieldDecision(
                field=field,
                conflict_type=ORTHOGONAL,
                sources=tuple(sorted_agents),
                chosen_value=value,
                rationale=ortho_rationale,
                needs_approval=False,
                needs_review=False,
            )

        elif conflict_type == LOW_CONFLICT:
            value = agent_values[first_agent]
            merged_values[field] = value
            auto_resolved.append(field)
            review_fields.append(field)
            field_decisions[field] = FieldDecision(
                field=field,
                conflict_type=LOW_CONFLICT,
                sources=tuple(sorted_agents),
                chosen_value=value,
                rationale=(
                    f"Minor difference. Chose value from lexically-first "
                    f"agent {first_agent}."
                ),
                needs_approval=False,
                needs_review=False,
            )

        elif conflict_type == CONFLICTING:
            value = agent_values[first_agent]
            merged_values[field] = value
            auto_resolved.append(field)
            review_fields.append(field)
            field_decisions[field] = FieldDecision(
                field=field,
                conflict_type=CONFLICTING,
                sources=tuple(sorted_agents),
                chosen_value=value,
                rationale=(
                    f"Significant difference. Chose value from lexically-first "
                    f"agent {first_agent}. Review recommended."
                ),
                needs_approval=False,
                needs_review=True,
            )

        elif conflict_type in (OPPOSITE, AMBIGUOUS):
            # GI-3 enforcement: chosen_value=None, excluded from merged_values
            value_descriptions = ", ".join(
                f"{a}={agent_values[a]!r}" for a in sorted_agents
            )
            approval_fields.append(field)
            field_decisions[field] = FieldDecision(
                field=field,
                conflict_type=conflict_type,
                sources=tuple(sorted_agents),
                chosen_value=None,
                rationale=(
                    f"Cannot auto-resolve. Candidate values: {value_descriptions}."
                ),
                needs_approval=True,
                needs_review=False,
            )

        else:
            # Unknown conflict type -- treat as AMBIGUOUS
            value_descriptions = ", ".join(
                f"{a}={agent_values[a]!r}" for a in sorted_agents
            )
            approval_fields.append(field)
            field_decisions[field] = FieldDecision(
                field=field,
                conflict_type=AMBIGUOUS,
                sources=tuple(sorted_agents),
                chosen_value=None,
                rationale=(
                    f"Unknown conflict type {conflict_type!r}. "
                    f"Candidate values: {value_descriptions}."
                ),
                needs_approval=True,
                needs_review=False,
            )

    summary = _build_summary(
        auto_resolved, review_fields, approval_fields, field_decisions
    )

    return ReconciliationResult(
        merged_values=merged_values,
        field_decisions=field_decisions,
        requires_approval=len(approval_fields) > 0,
        approval_fields=tuple(approval_fields),
        optional_review_fields=tuple(review_fields),
        auto_resolved_fields=tuple(auto_resolved),
        summary=summary,
    )


__all__ = [
    "ConflictType",
    "FieldDecision",
    "ReconciliationResult",
    "flatten_to_paths",
    "unflatten_paths",
    "reconcile_outputs",
    "IDENTICAL",
    "UNCONTESTED",
    "ORTHOGONAL",
    "LOW_CONFLICT",
    "CONFLICTING",
    "OPPOSITE",
    "AMBIGUOUS",
]
