# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Classify friction aggregates as FIXABLE or ESCALATE.

Classification rules:
  FIXABLE surfaces: config/*, ci/* (non-security), tooling/*, permissions/read-only-*
  ESCALATE surfaces: network/*, auth/*, permissions/* (security-sensitive), unknown/*

Within FIXABLE, the fix_category is derived from the surface specific part
and description keywords.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from friction_aggregator import FrictionAggregate

from friction_autofix.models import (
    EnumFixCategory,
    EnumFrictionDisposition,
    ModelFrictionClassification,
)

# Surface categories that are always escalated (need human judgment)
_ESCALATE_CATEGORIES: frozenset[str] = frozenset({"network", "auth", "unknown"})

# Keyword -> fix category mapping for fixable surfaces
_KEYWORD_TO_CATEGORY: list[tuple[list[str], EnumFixCategory]] = [
    (
        ["config", "missing-entry", "missing-sidebar", "yaml"],
        EnumFixCategory.CONFIG,
    ),
    (
        ["import", "ImportError", "ModuleNotFoundError", "re-export"],
        EnumFixCategory.IMPORT,
    ),
    (
        ["wiring", "handler", "registration", "route"],
        EnumFixCategory.WIRING,
    ),
    (
        ["stale", "renamed", "deleted", "obsolete", "dead-ref"],
        EnumFixCategory.STALE_REF,
    ),
    (["marker", "@pytest.mark", "test_marker"], EnumFixCategory.TEST_MARKER),
    (
        ["env", "env_var", "environment", "OMNIBASE_", "KAFKA_"],
        EnumFixCategory.ENV_VAR,
    ),
]


def _infer_fix_category(
    surface: str, descriptions: list[str]
) -> EnumFixCategory | None:
    """Infer fix category from surface specific part and description keywords."""
    search_text = f"{surface} {' '.join(descriptions)}".lower()
    for keywords, category in _KEYWORD_TO_CATEGORY:
        for kw in keywords:
            if kw.lower() in search_text:
                return category
    # Default by surface category
    category_part = surface.split("/")[0] if "/" in surface else surface
    defaults: dict[str, EnumFixCategory] = {
        "config": EnumFixCategory.CONFIG,
        "ci": EnumFixCategory.WIRING,
        "tooling": EnumFixCategory.CONFIG,
    }
    return defaults.get(category_part)


def classify_friction(
    aggregate: FrictionAggregate,
) -> ModelFrictionClassification:
    """Classify a single FrictionAggregate as FIXABLE or ESCALATE."""
    category_part = (
        aggregate.surface.split("/")[0]
        if "/" in aggregate.surface
        else aggregate.surface
    )

    if category_part in _ESCALATE_CATEGORIES:
        return ModelFrictionClassification(
            surface_key=aggregate.surface_key,
            skill=aggregate.skill,
            surface=aggregate.surface,
            disposition=EnumFrictionDisposition.ESCALATE,
            fix_category=None,
            escalation_reason=f"Surface category '{category_part}' requires human judgment",
            description=aggregate.descriptions[-1] if aggregate.descriptions else "",
            most_recent_ticket=aggregate.most_recent_ticket,
            count=aggregate.count,
            severity_score=aggregate.severity_score,
        )

    fix_cat = _infer_fix_category(aggregate.surface, aggregate.descriptions)
    return ModelFrictionClassification(
        surface_key=aggregate.surface_key,
        skill=aggregate.skill,
        surface=aggregate.surface,
        disposition=EnumFrictionDisposition.FIXABLE,
        fix_category=fix_cat,
        escalation_reason=None,
        description=aggregate.descriptions[-1] if aggregate.descriptions else "",
        most_recent_ticket=aggregate.most_recent_ticket,
        count=aggregate.count,
        severity_score=aggregate.severity_score,
    )


def classify_friction_batch(
    aggregates: list[FrictionAggregate],
) -> list[ModelFrictionClassification]:
    """Classify a batch of FrictionAggregate objects."""
    return [classify_friction(agg) for agg in aggregates]
