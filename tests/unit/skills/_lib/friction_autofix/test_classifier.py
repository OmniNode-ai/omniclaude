# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

from datetime import UTC, datetime

import pytest


@pytest.mark.unit
class TestFrictionClassifier:
    def _make_aggregate(
        self,
        *,
        surface_key: str,
        skill: str,
        surface: str,
        count: int = 3,
        severity_score: int = 9,
        descriptions: list[str] | None = None,
    ):  # type: ignore[no-untyped-def]
        """Helper to create FrictionAggregate-like objects for testing."""
        from friction_aggregator import FrictionAggregate

        agg = FrictionAggregate(
            surface_key=surface_key,
            skill=skill,
            surface=surface,
            count=count,
            severity_score=severity_score,
            descriptions=descriptions or [],
        )
        agg.latest_timestamp = datetime.now(UTC)
        return agg

    def test_config_surface_classified_fixable(self) -> None:
        from friction_autofix.classifier import classify_friction
        from friction_autofix.models import EnumFixCategory, EnumFrictionDisposition

        agg = self._make_aggregate(
            surface_key="merge_sweep:config/missing-sidebar-entry",
            skill="merge_sweep",
            surface="config/missing-sidebar-entry",
            descriptions=["Sidebar entry missing for /compliance"],
        )
        result = classify_friction(agg)
        assert result.disposition == EnumFrictionDisposition.FIXABLE
        assert result.fix_category == EnumFixCategory.CONFIG

    def test_ci_import_surface_classified_fixable(self) -> None:
        from friction_autofix.classifier import classify_friction
        from friction_autofix.models import EnumFixCategory, EnumFrictionDisposition

        agg = self._make_aggregate(
            surface_key="ticket_pipeline:ci/broken-import",
            skill="ticket_pipeline",
            surface="ci/broken-import",
            descriptions=["ImportError: cannot import name 'ModelFoo'"],
        )
        result = classify_friction(agg)
        assert result.disposition == EnumFrictionDisposition.FIXABLE
        assert result.fix_category == EnumFixCategory.IMPORT

    def test_network_surface_escalated(self) -> None:
        from friction_autofix.classifier import classify_friction
        from friction_autofix.models import EnumFrictionDisposition

        agg = self._make_aggregate(
            surface_key="release:network/timeout",
            skill="release",
            surface="network/timeout",
            descriptions=["Connection to registry timed out"],
        )
        result = classify_friction(agg)
        assert result.disposition == EnumFrictionDisposition.ESCALATE
        assert result.escalation_reason is not None

    def test_auth_surface_escalated(self) -> None:
        from friction_autofix.classifier import classify_friction
        from friction_autofix.models import EnumFrictionDisposition

        agg = self._make_aggregate(
            surface_key="deploy:auth/token-expired",
            skill="deploy",
            surface="auth/token-expired",
        )
        result = classify_friction(agg)
        assert result.disposition == EnumFrictionDisposition.ESCALATE

    def test_classify_batch(self) -> None:
        from friction_autofix.classifier import classify_friction_batch

        aggregates = [
            self._make_aggregate(
                surface_key="a:config/missing-entry",
                skill="a",
                surface="config/missing-entry",
            ),
            self._make_aggregate(
                surface_key="b:auth/expired",
                skill="b",
                surface="auth/expired",
            ),
        ]
        results = classify_friction_batch(aggregates)
        assert len(results) == 2
        fixable = [r for r in results if r.disposition.value == "fixable"]
        escalate = [r for r in results if r.disposition.value == "escalate"]
        assert len(fixable) == 1
        assert len(escalate) == 1
