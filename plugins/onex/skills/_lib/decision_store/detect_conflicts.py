"""
detect_conflicts.py — Structural conflict scoring for decision-store skill.

Pure functions only. No I/O. No side effects.
Called inline by the agent (not via subprocess) when checking for conflicts.

Usage:
    from detect_conflicts import structural_confidence, compute_severity, BASE_SEVERITY

    conf = structural_confidence(entry_a, entry_b)
    if conf >= 0.6:
        # proceed to semantic_check.py
        severity = compute_severity(entry_a, entry_b, conf)
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Minimal data contract (mirrors ModelDecisionStoreEntry from omnibase_core)
# ---------------------------------------------------------------------------


@dataclass
class DecisionEntry:
    """Lightweight mirror of ModelDecisionStoreEntry for pure structural checks.

    In production the agent passes actual ModelDecisionStoreEntry objects;
    this dataclass is used for unit tests and standalone script use.
    """

    decision_type: str  # "TECH_STACK_CHOICE" | "DESIGN_PATTERN" | "API_CONTRACT" |
    # "SCOPE_BOUNDARY" | "REQUIREMENT_CHOICE"
    scope_domain: str  # e.g. "infrastructure", "api", "frontend"
    scope_layer: str  # "architecture" | "design" | "planning"
    scope_services: list[str]  # empty = platform-wide


# ---------------------------------------------------------------------------
# Severity matrix
# ---------------------------------------------------------------------------

SEVERITY_ORDER: dict[str, int] = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}

BASE_SEVERITY: dict[tuple[str, str], str] = {
    # decision_type           scope_layer       severity
    ("TECH_STACK_CHOICE", "architecture"): "HIGH",
    ("TECH_STACK_CHOICE", "design"): "HIGH",
    ("TECH_STACK_CHOICE", "planning"): "MEDIUM",
    ("DESIGN_PATTERN", "architecture"): "HIGH",
    ("DESIGN_PATTERN", "design"): "MEDIUM",
    ("DESIGN_PATTERN", "planning"): "LOW",
    ("API_CONTRACT", "architecture"): "HIGH",
    ("API_CONTRACT", "design"): "MEDIUM",
    ("API_CONTRACT", "planning"): "LOW",
    ("SCOPE_BOUNDARY", "architecture"): "MEDIUM",
    ("SCOPE_BOUNDARY", "design"): "MEDIUM",
    ("SCOPE_BOUNDARY", "planning"): "LOW",
    ("REQUIREMENT_CHOICE", "architecture"): "MEDIUM",
    ("REQUIREMENT_CHOICE", "design"): "LOW",
    ("REQUIREMENT_CHOICE", "planning"): "LOW",
}


# ---------------------------------------------------------------------------
# structural_confidence — pure function
# ---------------------------------------------------------------------------


def structural_confidence(
    a: DecisionEntry,
    b: DecisionEntry,
) -> float:
    """Return a [0.0, 1.0] structural confidence score for two decision entries.

    Confidence reflects the probability that two entries are in genuine conflict
    based on their scope fields alone, without consulting an LLM.

    Threshold rules (enforced by caller):
    - 0.0  → cross-domain hard rule; semantic check MUST NOT run
    - <0.6 → semantic check is skipped (not worth the cost)
    - >=0.6 → semantic check MAY run (see semantic_check.py)
    - 0.3  → disjoint services; semantic check CANNOT escalate beyond MEDIUM

    Args:
        a: First decision entry.
        b: Second decision entry.

    Returns:
        float in [0.0, 1.0].
    """
    # Cross-domain: hard rule, no possible conflict
    if a.scope_domain != b.scope_domain:
        return 0.0

    # Same domain but different layer: low confidence
    if a.scope_layer != b.scope_layer:
        return 0.4

    # Same domain + same layer — service overlap analysis
    a_svc = set(a.scope_services)
    b_svc = set(b.scope_services)

    if not a_svc and not b_svc:
        return 0.9  # both platform-wide: very likely conflict

    if not a_svc or not b_svc:
        return 0.8  # one platform-wide vs specific: likely conflict

    if a_svc == b_svc:
        return 1.0  # identical service scope: definite conflict

    if a_svc & b_svc:
        return 0.7  # overlapping services: probable conflict

    return 0.3  # disjoint services: low probability, cap semantic at MEDIUM


# ---------------------------------------------------------------------------
# compute_severity — pure function
# ---------------------------------------------------------------------------


def compute_severity(
    a: DecisionEntry,
    b: DecisionEntry,
    structural_conf: float,
    semantic_shift: int = 0,
) -> str:
    """Compute final conflict severity from the severity matrix + modifiers.

    Args:
        a: First decision entry.
        b: Second decision entry.
        structural_conf: Output of structural_confidence(a, b).
        semantic_shift: Integer shift from semantic check: -1, 0, or +1.
                        Clamped so result stays within [LOW, HIGH].
                        semantic_shift MUST be 0 when structural_conf == 0.0.

    Returns:
        "LOW" | "MEDIUM" | "HIGH"

    Raises:
        ValueError: If semantic_shift is non-zero when structural_conf == 0.0
                    (cross-domain hard rule: semantic never runs).
        ValueError: If structural_conf == 0.3 and semantic_shift > 0
                    (disjoint-service cap: cannot escalate beyond MEDIUM).
    """
    if structural_conf == 0.0 and semantic_shift != 0:
        raise ValueError(
            "semantic_shift must be 0 for cross-domain entries "
            "(structural_confidence == 0.0 means semantic check must not run)"
        )

    if structural_conf == 0.3 and semantic_shift > 0:
        raise ValueError(
            "disjoint-service entries (structural_confidence == 0.3) "
            "cannot be escalated by semantic check beyond MEDIUM"
        )

    # Base severity: take the higher of the two entries' base severities
    type_a_key = (a.decision_type, a.scope_layer)
    type_b_key = (b.decision_type, b.scope_layer)
    base_a = BASE_SEVERITY.get(type_a_key, "LOW")
    base_b = BASE_SEVERITY.get(type_b_key, "LOW")
    base = max(base_a, base_b, key=lambda s: SEVERITY_ORDER[s])

    # Modifier 1: platform-wide scope → floor at MEDIUM
    if not a.scope_services or not b.scope_services:
        base = max(base, "MEDIUM", key=lambda s: SEVERITY_ORDER[s])

    # Modifier 2: architecture layer → floor at HIGH
    if a.scope_layer == "architecture" or b.scope_layer == "architecture":
        base = max(base, "HIGH", key=lambda s: SEVERITY_ORDER[s])

    # Modifier 3: semantic shift ±1, clamped to [LOW, HIGH]
    final_idx = max(0, min(2, SEVERITY_ORDER[base] + semantic_shift))
    return ["LOW", "MEDIUM", "HIGH"][final_idx]


# ---------------------------------------------------------------------------
# check_conflicts_batch — convenience helper
# ---------------------------------------------------------------------------


def check_conflicts_batch(
    candidate: DecisionEntry,
    existing: list[DecisionEntry],
    semantic_threshold: float = 0.6,
) -> list[dict]:
    """Run structural conflict check of candidate against all existing entries.

    Returns a list of conflict dicts (only entries with confidence > 0.0).
    Entries with confidence >= semantic_threshold are flagged for semantic check.

    Args:
        candidate: The new decision entry being evaluated.
        existing: All existing entries to check against.
        semantic_threshold: Minimum structural confidence to trigger semantic check.
                            Default 0.6 per spec.

    Returns:
        List of dicts: {
            "entry": DecisionEntry,
            "structural_confidence": float,
            "base_severity": str,
            "needs_semantic": bool,
        }
    """
    results = []
    for entry in existing:
        conf = structural_confidence(candidate, entry)
        if conf == 0.0:
            continue  # cross-domain: no conflict possible
        severity = compute_severity(candidate, entry, conf)
        results.append(
            {
                "entry": entry,
                "structural_confidence": conf,
                "base_severity": severity,
                "needs_semantic": conf >= semantic_threshold,
            }
        )
    return results
