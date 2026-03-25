# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

import pytest


@pytest.mark.unit
class TestMicroPlanGenerator:
    def test_generate_config_fix_plan(self) -> None:
        from friction_autofix.models import (
            EnumFixCategory,
            EnumFrictionDisposition,
            ModelFrictionClassification,
        )
        from friction_autofix.plan_generator import generate_micro_plan

        clf = ModelFrictionClassification(
            surface_key="merge_sweep:config/missing-sidebar-entry",
            skill="merge_sweep",
            surface="config/missing-sidebar-entry",
            disposition=EnumFrictionDisposition.FIXABLE,
            fix_category=EnumFixCategory.CONFIG,
            escalation_reason=None,
            description="Sidebar entry missing for /compliance page in omnidash",
            most_recent_ticket=None,
            count=3,
            severity_score=9,
        )
        plan = generate_micro_plan(clf)
        assert plan.surface_key == clf.surface_key
        assert len(plan.tasks) >= 1
        assert len(plan.tasks) <= 3
        assert plan.target_repo is not None

    def test_generate_import_fix_plan(self) -> None:
        from friction_autofix.models import (
            EnumFixCategory,
            EnumFrictionDisposition,
            ModelFrictionClassification,
        )
        from friction_autofix.plan_generator import generate_micro_plan

        clf = ModelFrictionClassification(
            surface_key="ticket_pipeline:ci/broken-import",
            skill="ticket_pipeline",
            surface="ci/broken-import",
            disposition=EnumFrictionDisposition.FIXABLE,
            fix_category=EnumFixCategory.IMPORT,
            escalation_reason=None,
            description="ImportError: cannot import name 'ModelFoo' from 'omniclaude.models'",
            most_recent_ticket=None,
            count=4,
            severity_score=12,
        )
        plan = generate_micro_plan(clf)
        assert plan.surface_key == clf.surface_key
        assert len(plan.tasks) >= 1

    def test_escalate_raises(self) -> None:
        from friction_autofix.models import (
            EnumFrictionDisposition,
            ModelFrictionClassification,
        )
        from friction_autofix.plan_generator import generate_micro_plan

        clf = ModelFrictionClassification(
            surface_key="x:auth/expired",
            skill="x",
            surface="auth/expired",
            disposition=EnumFrictionDisposition.ESCALATE,
            fix_category=None,
            escalation_reason="Needs human",
            description="",
            most_recent_ticket=None,
            count=1,
            severity_score=9,
        )
        with pytest.raises(ValueError, match="Cannot generate micro-plan for ESCALATE"):
            generate_micro_plan(clf)

    def test_plan_title_contains_surface(self) -> None:
        from friction_autofix.models import (
            EnumFixCategory,
            EnumFrictionDisposition,
            ModelFrictionClassification,
        )
        from friction_autofix.plan_generator import generate_micro_plan

        clf = ModelFrictionClassification(
            surface_key="gap:tooling/missing-script",
            skill="gap",
            surface="tooling/missing-script",
            disposition=EnumFrictionDisposition.FIXABLE,
            fix_category=EnumFixCategory.CONFIG,
            escalation_reason=None,
            description="Script not found",
            most_recent_ticket=None,
            count=3,
            severity_score=3,
        )
        plan = generate_micro_plan(clf)
        assert "tooling/missing-script" in plan.title or "gap" in plan.title
