# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest


@pytest.mark.unit
class TestClassifyToPlanIntegration:
    def _write_friction_events(self, path: Path, events: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            for event in events:
                f.write(json.dumps(event) + "\n")

    def test_end_to_end_fixable_flow(self, tmp_path: Path) -> None:
        from friction_aggregator import aggregate_friction
        from friction_autofix.classifier import classify_friction_batch
        from friction_autofix.models import EnumFrictionDisposition
        from friction_autofix.plan_generator import generate_micro_plan

        registry = tmp_path / "friction.ndjson"
        now = datetime.now(UTC).isoformat()
        self._write_friction_events(
            registry,
            [
                {
                    "skill": "gap",
                    "surface": "config/missing-sidebar",
                    "severity": "high",
                    "description": "Missing sidebar entry for /analytics",
                    "session_id": "s1",
                    "timestamp": now,
                },
                {
                    "skill": "gap",
                    "surface": "config/missing-sidebar",
                    "severity": "medium",
                    "description": "Missing sidebar entry for /analytics",
                    "session_id": "s2",
                    "timestamp": now,
                },
                {
                    "skill": "gap",
                    "surface": "config/missing-sidebar",
                    "severity": "medium",
                    "description": "Missing sidebar entry for /analytics",
                    "session_id": "s3",
                    "timestamp": now,
                },
            ],
        )

        aggregates = aggregate_friction(registry_path=registry)
        crossed = [a for a in aggregates if a.threshold_crossed]
        assert len(crossed) == 1
        assert crossed[0].count == 3
        assert crossed[0].severity_score == 15  # 9 + 3 + 3

        classifications = classify_friction_batch(crossed)
        assert len(classifications) == 1
        assert classifications[0].disposition == EnumFrictionDisposition.FIXABLE

        plan = generate_micro_plan(classifications[0])
        assert plan.surface_key == "gap:config/missing-sidebar"
        assert len(plan.tasks) >= 1
        assert len(plan.tasks) <= 3

    def test_end_to_end_escalation_flow(self, tmp_path: Path) -> None:
        from friction_aggregator import aggregate_friction
        from friction_autofix.classifier import classify_friction_batch
        from friction_autofix.models import EnumFrictionDisposition

        registry = tmp_path / "friction.ndjson"
        now = datetime.now(UTC).isoformat()
        self._write_friction_events(
            registry,
            [
                {
                    "skill": "deploy",
                    "surface": "auth/token-expired",
                    "severity": "high",
                    "description": "Auth token expired during deploy",
                    "session_id": "s1",
                    "timestamp": now,
                },
            ],
        )

        aggregates = aggregate_friction(registry_path=registry)
        crossed = [a for a in aggregates if a.threshold_crossed]
        assert len(crossed) == 1  # high severity = score 9 >= threshold

        classifications = classify_friction_batch(crossed)
        assert len(classifications) == 1
        assert classifications[0].disposition == EnumFrictionDisposition.ESCALATE

    def test_mixed_fixable_and_escalate(self, tmp_path: Path) -> None:
        from friction_aggregator import aggregate_friction
        from friction_autofix.classifier import classify_friction_batch
        from friction_autofix.models import EnumFrictionDisposition

        registry = tmp_path / "friction.ndjson"
        now = datetime.now(UTC).isoformat()
        events = []
        # 3 config events -> fixable
        for i in range(3):
            events.append(
                {
                    "skill": "sweep",
                    "surface": "config/missing-route",
                    "severity": "medium",
                    "description": "Route not registered",
                    "session_id": f"s{i}",
                    "timestamp": now,
                }
            )
        # 1 high auth event -> escalate
        events.append(
            {
                "skill": "deploy",
                "surface": "auth/expired",
                "severity": "high",
                "description": "Token expired",
                "session_id": "s10",
                "timestamp": now,
            }
        )
        self._write_friction_events(registry, events)

        aggregates = aggregate_friction(registry_path=registry)
        crossed = [a for a in aggregates if a.threshold_crossed]
        assert len(crossed) == 2

        classifications = classify_friction_batch(crossed)
        fixable = [
            c
            for c in classifications
            if c.disposition == EnumFrictionDisposition.FIXABLE
        ]
        escalate = [
            c
            for c in classifications
            if c.disposition == EnumFrictionDisposition.ESCALATE
        ]
        assert len(fixable) == 1
        assert len(escalate) == 1
