# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for QPM Pydantic models.

Covers: frozen immutability, extra=forbid, serialization round-trip,
net_score computation, enum membership.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from plugins.onex.skills._lib.merge_planner.models import (
    EnumAcceleratorTier,
    EnumPromotionDecision,
    EnumPRQueueClass,
    ModelPromotionRecord,
    ModelPRQueueScore,
    ModelQPMAuditEntry,
)

# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------


class TestEnumPRQueueClass:
    def test_members(self) -> None:
        assert set(EnumPRQueueClass) == {
            EnumPRQueueClass.ACCELERATOR,
            EnumPRQueueClass.NORMAL,
            EnumPRQueueClass.BLOCKED,
        }

    def test_string_values(self) -> None:
        assert EnumPRQueueClass.ACCELERATOR == "accelerator"
        assert EnumPRQueueClass.NORMAL == "normal"
        assert EnumPRQueueClass.BLOCKED == "blocked"


class TestEnumAcceleratorTier:
    def test_members(self) -> None:
        assert set(EnumAcceleratorTier) == {
            EnumAcceleratorTier.STRONG,
            EnumAcceleratorTier.MODERATE,
            EnumAcceleratorTier.WEAK,
        }


class TestEnumPromotionDecision:
    def test_members(self) -> None:
        assert set(EnumPromotionDecision) == {
            EnumPromotionDecision.PROMOTE,
            EnumPromotionDecision.HOLD,
            EnumPromotionDecision.SKIP,
            EnumPromotionDecision.BLOCK,
        }


# ---------------------------------------------------------------------------
# ModelPRQueueScore tests
# ---------------------------------------------------------------------------


def _make_score(**overrides: float) -> ModelPRQueueScore:
    defaults: dict[str, float] = {
        "acceleration_value": 0.8,
        "dependency_risk": 0.1,
        "blast_radius": 0.1,
        "flakiness_penalty": 0.0,
        "queue_disruption_cost": 0.05,
    }
    defaults.update(overrides)
    return ModelPRQueueScore(**defaults)


class TestModelPRQueueScore:
    def test_frozen_immutability(self) -> None:
        score = _make_score()
        with pytest.raises(ValidationError):
            score.acceleration_value = 0.5  # type: ignore[misc]

    def test_extra_forbid(self) -> None:
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            ModelPRQueueScore(
                acceleration_value=0.8,
                dependency_risk=0.1,
                blast_radius=0.1,
                flakiness_penalty=0.0,
                queue_disruption_cost=0.05,
                bogus_field=0.9,  # type: ignore[call-arg]
            )

    def test_net_score_computation(self) -> None:
        score = _make_score(
            acceleration_value=0.8,
            dependency_risk=0.1,
            blast_radius=0.1,
            flakiness_penalty=0.0,
            queue_disruption_cost=0.05,
        )
        expected = 0.8 - 0.1 - 0.1 - 0.0 - 0.05
        assert abs(score.net_score - expected) < 1e-9

    def test_net_score_negative(self) -> None:
        score = _make_score(
            acceleration_value=0.1,
            dependency_risk=0.3,
            blast_radius=0.3,
            flakiness_penalty=0.2,
            queue_disruption_cost=0.1,
        )
        assert score.net_score < 0

    def test_bounds_validation_lower(self) -> None:
        with pytest.raises(ValidationError):
            _make_score(acceleration_value=-0.1)

    def test_bounds_validation_upper(self) -> None:
        with pytest.raises(ValidationError):
            _make_score(acceleration_value=1.1)

    def test_serialization_round_trip(self) -> None:
        score = _make_score()
        data = score.model_dump()
        restored = ModelPRQueueScore(**data)
        assert restored == score

    def test_json_round_trip(self) -> None:
        score = _make_score()
        json_str = score.model_dump_json()
        restored = ModelPRQueueScore.model_validate_json(json_str)
        assert restored == score


# ---------------------------------------------------------------------------
# ModelPromotionRecord tests
# ---------------------------------------------------------------------------


def _make_record(**overrides: object) -> ModelPromotionRecord:
    defaults: dict[str, object] = {
        "repo": "OmniNode-ai/omniclaude",
        "pr_number": 42,
        "pr_title": "fix: ci workflow",
        "classification": EnumPRQueueClass.ACCELERATOR,
        "accelerator_tier": EnumAcceleratorTier.STRONG,
        "score": _make_score(),
        "decision": EnumPromotionDecision.PROMOTE,
        "reason": "Strong accelerator above threshold",
    }
    defaults.update(overrides)
    return ModelPromotionRecord(**defaults)  # type: ignore[arg-type]


class TestModelPromotionRecord:
    def test_frozen_immutability(self) -> None:
        record = _make_record()
        with pytest.raises(ValidationError):
            record.pr_number = 99  # type: ignore[misc]

    def test_extra_forbid(self) -> None:
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            _make_record(bogus=True)

    def test_would_promote_default_false(self) -> None:
        record = _make_record()
        assert record.would_promote is False

    def test_accelerator_tier_none_for_normal(self) -> None:
        record = _make_record(
            classification=EnumPRQueueClass.NORMAL,
            accelerator_tier=None,
            decision=EnumPromotionDecision.HOLD,
        )
        assert record.accelerator_tier is None

    def test_serialization_round_trip(self) -> None:
        record = _make_record()
        data = record.model_dump()
        restored = ModelPromotionRecord(**data)
        assert restored == record

    def test_json_round_trip(self) -> None:
        record = _make_record()
        json_str = record.model_dump_json()
        restored = ModelPromotionRecord.model_validate_json(json_str)
        assert restored == record

    def test_pr_number_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            _make_record(pr_number=0)


# ---------------------------------------------------------------------------
# ModelQPMAuditEntry tests
# ---------------------------------------------------------------------------


def _make_audit(**overrides: object) -> ModelQPMAuditEntry:
    defaults: dict[str, object] = {
        "run_id": "run-abc123",
        "timestamp": datetime(2026, 3, 24, 12, 0, 0, tzinfo=UTC),
        "mode": "shadow",
        "repos_queried": ["OmniNode-ai/omniclaude"],
        "promotion_threshold": 0.3,
        "max_promotions": 3,
        "records": [_make_record()],
        "promotions_executed": 0,
        "promotions_held": 1,
    }
    defaults.update(overrides)
    return ModelQPMAuditEntry(**defaults)  # type: ignore[arg-type]


class TestModelQPMAuditEntry:
    def test_frozen_immutability(self) -> None:
        audit = _make_audit()
        with pytest.raises(ValidationError):
            audit.run_id = "different"  # type: ignore[misc]

    def test_extra_forbid(self) -> None:
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            _make_audit(bogus=True)

    def test_repo_fetch_errors_default_empty(self) -> None:
        audit = _make_audit()
        assert audit.repo_fetch_errors == {}

    def test_repo_fetch_errors_populated(self) -> None:
        audit = _make_audit(
            repo_fetch_errors={"OmniNode-ai/omnibase_core": "rate limit exceeded"}
        )
        assert "OmniNode-ai/omnibase_core" in audit.repo_fetch_errors

    def test_serialization_round_trip(self) -> None:
        audit = _make_audit()
        data = audit.model_dump()
        restored = ModelQPMAuditEntry(**data)
        assert restored == audit

    def test_json_round_trip(self) -> None:
        audit = _make_audit()
        json_str = audit.model_dump_json()
        restored = ModelQPMAuditEntry.model_validate_json(json_str)
        assert restored == audit

    def test_max_promotions_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            _make_audit(max_promotions=0)

    def test_mode_values(self) -> None:
        for mode in ("shadow", "label_gated", "auto"):
            audit = _make_audit(mode=mode)
            assert audit.mode == mode
