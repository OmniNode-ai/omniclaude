"""QPM Priority Scorer — compute 5-dimension net score for classified PRs.

Dimensions: acceleration_value - dependency_risk - blast_radius - flakiness_penalty - queue_disruption_cost.
Classification dominates scoring; title keywords only refine within a class.
"""

from __future__ import annotations

import fnmatch
import re

from merge_planner.classifier import (
    MODERATE_ACCELERATOR_PATTERNS,
    STRONG_ACCELERATOR_PATTERNS,
    PRContext,
)
from merge_planner.models import EnumPRQueueClass, ModelPRQueueScore

PROMOTION_THRESHOLD: float = 0.3

_CI_FIX_PATTERN = re.compile(
    r"(fix|chore)\(ci\)|ci[:/]|workflow|lint|ruff|mypy|bandit", re.IGNORECASE
)
_WORKFLOW_PATTERN = re.compile(r"\.github/workflows/")


def _accelerator_tier(ctx: PRContext) -> str:
    """Determine accelerator tier from file patterns. Returns 'strong', 'moderate', or 'weak'."""
    has_strong = any(
        fnmatch.fnmatch(f, pat)
        for f in ctx.changed_files
        for pat in STRONG_ACCELERATOR_PATTERNS
    )
    has_moderate = any(
        fnmatch.fnmatch(f, pat)
        for f in ctx.changed_files
        for pat in MODERATE_ACCELERATOR_PATTERNS
    )
    if has_strong:
        return "strong"
    if has_moderate:
        return "moderate"
    return "weak"


def score_pr(
    ctx: PRContext, queue_class: EnumPRQueueClass, queue_depth: int
) -> ModelPRQueueScore:
    """Compute 5-dimension priority score. Deterministic, no I/O.

    Classification dominates scoring. Title keywords only refine within a class.
    net_score is a computed @property on the model, not a constructor arg.
    """
    # Acceleration value -- tiered by accelerator strength
    if queue_class == EnumPRQueueClass.BLOCKED:
        accel = 0.0
    elif queue_class == EnumPRQueueClass.ACCELERATOR:
        tier = _accelerator_tier(ctx)
        base = {"strong": 0.8, "moderate": 0.6, "weak": 0.3}[tier]
        # Title keyword bonus (capped at +0.1) -- weak signal, classification dominates
        title_bonus = 0.1 if _CI_FIX_PATTERN.search(ctx.title) else 0.0
        accel = min(1.0, base + title_bonus)
    else:
        accel = 0.2

    # Dependency risk (MVP: path-based heuristic)
    dep_risk = 0.0
    has_pyproject = any(f.endswith("pyproject.toml") for f in ctx.changed_files)
    has_workflow = any(_WORKFLOW_PATTERN.search(f) for f in ctx.changed_files)
    if has_pyproject:
        dep_risk += 0.3
    if has_workflow:
        dep_risk += 0.2
    dep_risk = min(dep_risk, 1.0)

    # Blast radius: linear scale, 50+ files = max
    blast = min(1.0, len(ctx.changed_files) / 50)

    # Flakiness penalty: 0.0 for MVP (Phase 3 adds historical data)
    flake = 0.0

    # Queue disruption cost: 0.1 * depth, capped at 0.5
    disruption = min(0.5, 0.1 * queue_depth)

    return ModelPRQueueScore(
        acceleration_value=round(accel, 4),
        dependency_risk=round(dep_risk, 4),
        blast_radius=round(blast, 4),
        flakiness_penalty=round(flake, 4),
        queue_disruption_cost=round(disruption, 4),
    )
