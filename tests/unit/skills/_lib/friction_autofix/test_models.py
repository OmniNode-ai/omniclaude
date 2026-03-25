# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

import pytest


@pytest.mark.unit
class TestFrictionAutofixModels:
    def test_model_friction_classification_fixable(self) -> None:
        from friction_autofix.models import (
            EnumFixCategory,
            EnumFrictionDisposition,
            ModelFrictionClassification,
        )

        clf = ModelFrictionClassification(
            surface_key="merge_sweep:config/missing-sidebar-entry",
            skill="merge_sweep",
            surface="config/missing-sidebar-entry",
            disposition=EnumFrictionDisposition.FIXABLE,
            fix_category=EnumFixCategory.CONFIG,
            escalation_reason=None,
            description="Sidebar entry missing for /compliance page",
            most_recent_ticket=None,
            count=3,
            severity_score=9,
        )
        assert clf.disposition == EnumFrictionDisposition.FIXABLE
        assert clf.fix_category == EnumFixCategory.CONFIG
        assert clf.escalation_reason is None

    def test_model_friction_classification_escalate(self) -> None:
        from friction_autofix.models import (
            EnumFrictionDisposition,
            ModelFrictionClassification,
        )

        clf = ModelFrictionClassification(
            surface_key="ticket_pipeline:ci/cross-repo-boundary",
            skill="ticket_pipeline",
            surface="ci/cross-repo-boundary",
            disposition=EnumFrictionDisposition.ESCALATE,
            fix_category=None,
            escalation_reason="Requires cross-repo architectural change",
            description="CI boundary check fails across omnibase_core and omniclaude",
            most_recent_ticket="OMN-5500",
            count=5,
            severity_score=15,
        )
        assert clf.disposition == EnumFrictionDisposition.ESCALATE
        assert clf.fix_category is None
        assert clf.escalation_reason is not None

    def test_model_friction_classification_frozen(self) -> None:
        from friction_autofix.models import (
            EnumFrictionDisposition,
            ModelFrictionClassification,
        )

        clf = ModelFrictionClassification(
            surface_key="x:y",
            skill="x",
            surface="y",
            disposition=EnumFrictionDisposition.FIXABLE,
            fix_category=None,
            escalation_reason=None,
            description="",
            most_recent_ticket=None,
            count=1,
            severity_score=1,
        )
        with pytest.raises(Exception):
            clf.disposition = EnumFrictionDisposition.ESCALATE  # type: ignore[misc]

    def test_model_micro_plan(self) -> None:
        from friction_autofix.models import ModelMicroPlan, ModelMicroPlanTask

        plan = ModelMicroPlan(
            surface_key="gap:ci/missing-workflow",
            title="Fix missing CI workflow for gap skill",
            tasks=[
                ModelMicroPlanTask(
                    description="Add workflow file",
                    file_path=".github/workflows/gap.yml",
                    action="create",
                ),
            ],
            target_repo="omniclaude",
        )
        assert len(plan.tasks) == 1
        assert plan.tasks[0].action == "create"

    def test_model_micro_plan_max_tasks(self) -> None:
        from friction_autofix.models import ModelMicroPlan, ModelMicroPlanTask

        tasks = [
            ModelMicroPlanTask(
                description=f"t{i}", file_path=f"f{i}.py", action="modify"
            )
            for i in range(4)
        ]
        with pytest.raises(Exception):
            ModelMicroPlan(
                surface_key="x:y",
                title="Too many tasks",
                tasks=tasks,
                target_repo="omniclaude",
            )

    def test_model_friction_fix_result(self) -> None:
        from friction_autofix.models import EnumFixOutcome, ModelFrictionFixResult

        result = ModelFrictionFixResult(
            surface_key="gap:ci/missing-workflow",
            outcome=EnumFixOutcome.RESOLVED,
            ticket_id="OMN-6700",
            pr_number=42,
            verification_passed=True,
        )
        assert result.outcome == EnumFixOutcome.RESOLVED
        assert result.verification_passed is True

    def test_enum_fix_category_members(self) -> None:
        from friction_autofix.models import EnumFixCategory

        assert set(EnumFixCategory) == {
            EnumFixCategory.CONFIG,
            EnumFixCategory.WIRING,
            EnumFixCategory.IMPORT,
            EnumFixCategory.STALE_REF,
            EnumFixCategory.TEST_MARKER,
            EnumFixCategory.ENV_VAR,
        }

    def test_enum_fix_outcome_members(self) -> None:
        from friction_autofix.models import EnumFixOutcome

        assert set(EnumFixOutcome) == {
            EnumFixOutcome.RESOLVED,
            EnumFixOutcome.FAILED,
            EnumFixOutcome.ESCALATED,
            EnumFixOutcome.SKIPPED,
        }

    def test_model_friction_fix_result_frozen(self) -> None:
        from friction_autofix.models import EnumFixOutcome, ModelFrictionFixResult

        result = ModelFrictionFixResult(
            surface_key="x:y",
            outcome=EnumFixOutcome.RESOLVED,
        )
        with pytest.raises(Exception):
            result.outcome = EnumFixOutcome.FAILED  # type: ignore[misc]
