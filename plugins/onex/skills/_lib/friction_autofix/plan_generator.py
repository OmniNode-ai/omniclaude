# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Generate micro-plans from classified friction events.

Each micro-plan is 1-3 tasks that fix a single structurally-resolvable
friction point. This is design-to-plan Phase 2 in miniature -- no brainstorm
needed since the friction event IS the spec.
"""

from __future__ import annotations

from friction_autofix.models import (
    EnumFixCategory,
    EnumFrictionDisposition,
    ModelFrictionClassification,
    ModelMicroPlan,
    ModelMicroPlanTask,
)

# Default repo when classification does not provide one
_DEFAULT_REPO = "omniclaude"

# Category-specific plan templates
_CATEGORY_TEMPLATES: dict[EnumFixCategory, list[ModelMicroPlanTask]] = {
    EnumFixCategory.CONFIG: [
        ModelMicroPlanTask(
            description="Locate the configuration file and add the missing entry",
            file_path="<determined from friction description>",
            action="modify",
        ),
        ModelMicroPlanTask(
            description="Verify the configuration change resolves the friction",
            file_path="<test or validation command>",
            action="modify",
        ),
    ],
    EnumFixCategory.WIRING: [
        ModelMicroPlanTask(
            description="Add missing handler/route/topic wiring",
            file_path="<determined from friction description>",
            action="modify",
        ),
        ModelMicroPlanTask(
            description="Add or update test for the new wiring",
            file_path="<test file>",
            action="modify",
        ),
    ],
    EnumFixCategory.IMPORT: [
        ModelMicroPlanTask(
            description="Fix broken import or add missing re-export to __init__.py",
            file_path="<determined from friction description>",
            action="modify",
        ),
    ],
    EnumFixCategory.STALE_REF: [
        ModelMicroPlanTask(
            description="Update or remove stale reference",
            file_path="<determined from friction description>",
            action="modify",
        ),
    ],
    EnumFixCategory.TEST_MARKER: [
        ModelMicroPlanTask(
            description="Add missing pytest marker to test file",
            file_path="<determined from friction description>",
            action="modify",
        ),
    ],
    EnumFixCategory.ENV_VAR: [
        ModelMicroPlanTask(
            description="Add or fix environment variable configuration",
            file_path="<determined from friction description>",
            action="modify",
        ),
    ],
}


def _infer_repo_from_description(description: str) -> str:
    """Infer target repo from friction description keywords."""
    repo_keywords: dict[str, str] = {
        "omnidash": "omnidash",
        "omnibase_core": "omnibase_core",
        "omnibase_infra": "omnibase_infra",
        "omniintelligence": "omniintelligence",
        "omnimemory": "omnimemory",
        "omniclaude": "omniclaude",
        "onex_change_control": "onex_change_control",
    }
    desc_lower = description.lower()
    for keyword, repo in repo_keywords.items():
        if keyword in desc_lower:
            return repo
    return _DEFAULT_REPO


def generate_micro_plan(
    classification: ModelFrictionClassification,
) -> ModelMicroPlan:
    """Generate a micro-plan from a FIXABLE friction classification.

    Raises:
        ValueError: If classification disposition is ESCALATE.
    """
    if classification.disposition == EnumFrictionDisposition.ESCALATE:
        raise ValueError(
            f"Cannot generate micro-plan for ESCALATE disposition: "
            f"{classification.surface_key}"
        )

    fix_category = classification.fix_category or EnumFixCategory.CONFIG
    template_tasks = _CATEGORY_TEMPLATES.get(
        fix_category, _CATEGORY_TEMPLATES[EnumFixCategory.CONFIG]
    )
    target_repo = _infer_repo_from_description(classification.description)

    return ModelMicroPlan(
        surface_key=classification.surface_key,
        title=f"Fix friction: {classification.skill} — {classification.surface}",
        tasks=list(template_tasks),
        target_repo=target_repo,
    )
