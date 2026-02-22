# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Unit tests for OmniMemory Pattern Promotion (OMN-2506).

Test markers:
    @pytest.mark.unit  — all tests here

Coverage:
- R1: Promotion criteria
  - Criteria are typed (ModelPromotionCriteria)
  - Minimum evidence count is configurable
  - Only patterns with >= N successful bundles are eligible
  - Patterns below threshold are SKIPPED
- R2: Promote pattern to OmniMemory
  - Promoted pattern is written to store (PROMOTED status)
  - Pattern includes intent_type, unit_specs, dep_specs, evidence_bundle_ids
  - Promotion is idempotent (ALREADY_CURRENT when same evidence count)
  - Re-promotion with higher evidence count is a VERSION_BUMP
- R3: Promoted patterns are retrievable at compile time
  - Pattern retrievable by pattern_key
  - Cache hit logged (observability)
  - Cache miss returns None (fallback to full generation)
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from omniclaude.nodes.node_omnimemory_promotion.enums.enum_promotion_status import (
    EnumPromotionStatus,
)
from omniclaude.nodes.node_omnimemory_promotion.handler_pattern_promotion_default import (
    HandlerPatternPromotionDefault,
    _derive_pattern_key,
)
from omniclaude.nodes.node_omnimemory_promotion.models.model_pattern_promotion_request import (
    ModelPatternPromotionRequest,
)
from omniclaude.nodes.node_omnimemory_promotion.models.model_promoted_pattern import (
    ModelPromotedPattern,
)
from omniclaude.nodes.node_omnimemory_promotion.models.model_promotion_criteria import (
    ModelPromotionCriteria,
)
from omniclaude.nodes.node_omnimemory_promotion.store_pattern_in_memory import (
    StorePatternInMemory,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UNIT_SPECS: tuple[tuple[str, str, str, str], ...] = (
    ("wu-1", "Implement OAuth2 login", "FEATURE_IMPLEMENTATION", "M"),
    ("wu-2", "Add OAuth2 tests", "TEST_SUITE", "S"),
)

_DEP_SPECS: tuple[tuple[str, str], ...] = (("wu-1", "wu-2"),)

_BUNDLE_IDS: tuple[str, ...] = (
    f"bundle-{uuid.uuid4()}",
    f"bundle-{uuid.uuid4()}",
    f"bundle-{uuid.uuid4()}",
)


def _request(
    intent_type: str = "FEATURE",
    evidence_count: int = 3,
    min_evidence_count: int = 3,
    **kwargs: object,
) -> ModelPatternPromotionRequest:
    defaults: dict[str, object] = {
        "intent_type": intent_type,
        "unit_specs": _UNIT_SPECS,
        "dep_specs": _DEP_SPECS,
        "evidence_bundle_ids": _BUNDLE_IDS[:evidence_count],
        "evidence_count": evidence_count,
        "criteria": ModelPromotionCriteria(min_evidence_count=min_evidence_count),
        "correlation_id": uuid.uuid4(),
    }
    defaults.update(kwargs)
    return ModelPatternPromotionRequest(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# R1: ModelPromotionCriteria
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestModelPromotionCriteria:
    def test_default_criteria_min_evidence_is_3(self) -> None:
        criteria = ModelPromotionCriteria()
        assert criteria.min_evidence_count == 3

    def test_custom_min_evidence_accepted(self) -> None:
        criteria = ModelPromotionCriteria(min_evidence_count=5)
        assert criteria.min_evidence_count == 5

    def test_zero_min_evidence_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ModelPromotionCriteria(min_evidence_count=0)

    def test_criteria_is_frozen(self) -> None:
        criteria = ModelPromotionCriteria()
        with pytest.raises(ValidationError):
            criteria.min_evidence_count = 10  # type: ignore[misc]

    def test_require_all_acs_passing_defaults_true(self) -> None:
        criteria = ModelPromotionCriteria()
        assert criteria.require_all_acs_passing is True


# ---------------------------------------------------------------------------
# R1: ModelPromotedPattern
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestModelPromotedPattern:
    def test_valid_pattern_accepted(self) -> None:
        pattern = ModelPromotedPattern(
            pattern_id=str(uuid.uuid4()),
            pattern_key="FEATURE:abc123",
            intent_type="FEATURE",
            unit_specs=_UNIT_SPECS,
            evidence_bundle_ids=_BUNDLE_IDS,
            evidence_count=3,
        )
        assert pattern.version == 1
        assert pattern.evidence_count == 3

    def test_pattern_is_frozen(self) -> None:
        pattern = ModelPromotedPattern(
            pattern_id=str(uuid.uuid4()),
            pattern_key="FEATURE:abc123",
            intent_type="FEATURE",
            unit_specs=_UNIT_SPECS,
            evidence_bundle_ids=_BUNDLE_IDS,
            evidence_count=3,
        )
        with pytest.raises(ValidationError):
            pattern.version = 2  # type: ignore[misc]

    def test_zero_evidence_count_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ModelPromotedPattern(
                pattern_id=str(uuid.uuid4()),
                pattern_key="FEATURE:abc123",
                intent_type="FEATURE",
                unit_specs=_UNIT_SPECS,
                evidence_bundle_ids=(),
                evidence_count=0,
            )

    def test_version_defaults_to_1(self) -> None:
        pattern = ModelPromotedPattern(
            pattern_id=str(uuid.uuid4()),
            pattern_key="FEATURE:abc123",
            intent_type="FEATURE",
            unit_specs=_UNIT_SPECS,
            evidence_bundle_ids=_BUNDLE_IDS,
            evidence_count=3,
        )
        assert pattern.version == 1

    def test_dep_specs_default_empty(self) -> None:
        pattern = ModelPromotedPattern(
            pattern_id=str(uuid.uuid4()),
            pattern_key="FEATURE:abc123",
            intent_type="FEATURE",
            unit_specs=_UNIT_SPECS,
            evidence_bundle_ids=_BUNDLE_IDS,
            evidence_count=3,
        )
        assert pattern.dep_specs == ()


# ---------------------------------------------------------------------------
# Helpers: _derive_pattern_key
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDerivePatternKey:
    def test_key_includes_intent_type(self) -> None:
        key = _derive_pattern_key("FEATURE", _UNIT_SPECS)
        assert key.startswith("FEATURE:")

    def test_key_is_uppercase_intent(self) -> None:
        key = _derive_pattern_key("feature", _UNIT_SPECS)
        assert key.startswith("FEATURE:")

    def test_same_specs_same_key(self) -> None:
        key1 = _derive_pattern_key("FEATURE", _UNIT_SPECS)
        key2 = _derive_pattern_key("FEATURE", _UNIT_SPECS)
        assert key1 == key2

    def test_different_intent_different_key(self) -> None:
        key1 = _derive_pattern_key("FEATURE", _UNIT_SPECS)
        key2 = _derive_pattern_key("BUG", _UNIT_SPECS)
        assert key1 != key2

    def test_different_unit_types_different_key(self) -> None:
        alt_specs: tuple[tuple[str, str, str, str], ...] = (
            ("wu-1", "Fix bug", "BUG_FIX", "S"),
        )
        key1 = _derive_pattern_key("FEATURE", _UNIT_SPECS)
        key2 = _derive_pattern_key("FEATURE", alt_specs)
        assert key1 != key2

    def test_key_order_independent(self) -> None:
        specs_a = (
            ("wu-1", "Implement", "FEATURE_IMPLEMENTATION", "M"),
            ("wu-2", "Test", "TEST_SUITE", "S"),
        )
        specs_b = (
            ("wu-2", "Test", "TEST_SUITE", "S"),
            ("wu-1", "Implement", "FEATURE_IMPLEMENTATION", "M"),
        )
        key_a = _derive_pattern_key("FEATURE", specs_a)
        key_b = _derive_pattern_key("FEATURE", specs_b)
        assert key_a == key_b


# ---------------------------------------------------------------------------
# R2: HandlerPatternPromotionDefault — promotion logic
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandlerPatternPromotionDefault:
    def setup_method(self) -> None:
        self.store = StorePatternInMemory()
        self.handler = HandlerPatternPromotionDefault(self.store)

    def test_handler_key_is_default(self) -> None:
        assert self.handler.handler_key == "default"

    def test_promote_below_threshold_returns_skipped(self) -> None:
        req = _request(evidence_count=2, min_evidence_count=3)
        result = self.handler.promote(req)
        assert result.status == EnumPromotionStatus.SKIPPED
        assert result.promoted_pattern is None
        assert result.criteria_met is False

    def test_promote_at_threshold_returns_promoted(self) -> None:
        req = _request(evidence_count=3, min_evidence_count=3)
        result = self.handler.promote(req)
        assert result.status == EnumPromotionStatus.PROMOTED
        assert result.promoted_pattern is not None
        assert result.criteria_met is True

    def test_promoted_pattern_has_correct_intent_type(self) -> None:
        extra_bundles = tuple(f"bundle-{uuid.uuid4()}" for _ in range(2))
        req = _request(
            intent_type="SECURITY",
            evidence_count=5,
            min_evidence_count=3,
            evidence_bundle_ids=_BUNDLE_IDS + extra_bundles,
        )
        result = self.handler.promote(req)
        assert result.promoted_pattern is not None
        assert result.promoted_pattern.intent_type == "SECURITY"

    def test_promoted_pattern_has_unit_and_dep_specs(self) -> None:
        req = _request(evidence_count=3, min_evidence_count=3)
        result = self.handler.promote(req)
        assert result.promoted_pattern is not None
        assert result.promoted_pattern.unit_specs == _UNIT_SPECS
        assert result.promoted_pattern.dep_specs == _DEP_SPECS

    def test_promoted_pattern_has_evidence_bundle_ids(self) -> None:
        req = _request(evidence_count=3, min_evidence_count=3)
        result = self.handler.promote(req)
        assert result.promoted_pattern is not None
        assert len(result.promoted_pattern.evidence_bundle_ids) == 3

    def test_promoted_pattern_starts_at_version_1(self) -> None:
        req = _request(evidence_count=3, min_evidence_count=3)
        result = self.handler.promote(req)
        assert result.promoted_pattern is not None
        assert result.promoted_pattern.version == 1

    def test_idempotent_promotion_returns_already_current(self) -> None:
        req = _request(evidence_count=3, min_evidence_count=3)
        self.handler.promote(req)
        result = self.handler.promote(req)
        assert result.status == EnumPromotionStatus.ALREADY_CURRENT

    def test_version_bump_on_higher_evidence(self) -> None:
        req1 = _request(evidence_count=3, min_evidence_count=3)
        self.handler.promote(req1)

        extra_bundle = f"bundle-{uuid.uuid4()}"
        req2 = _request(
            evidence_count=4,
            min_evidence_count=3,
            evidence_bundle_ids=_BUNDLE_IDS + (extra_bundle,),
        )
        result = self.handler.promote(req2)
        assert result.status == EnumPromotionStatus.VERSION_BUMPED
        assert result.promoted_pattern is not None
        assert result.promoted_pattern.version == 2

    def test_version_bump_preserves_pattern_id(self) -> None:
        req1 = _request(evidence_count=3, min_evidence_count=3)
        r1 = self.handler.promote(req1)

        extra_bundle = f"bundle-{uuid.uuid4()}"
        req2 = _request(
            evidence_count=4,
            min_evidence_count=3,
            evidence_bundle_ids=_BUNDLE_IDS + (extra_bundle,),
        )
        r2 = self.handler.promote(req2)

        assert r1.promoted_pattern is not None
        assert r2.promoted_pattern is not None
        assert r1.promoted_pattern.pattern_id == r2.promoted_pattern.pattern_id

    def test_lower_evidence_does_not_version_bump(self) -> None:
        # First promotion at evidence_count=4
        extra_bundle = f"bundle-{uuid.uuid4()}"
        req1 = _request(
            evidence_count=4,
            min_evidence_count=3,
            evidence_bundle_ids=_BUNDLE_IDS + (extra_bundle,),
        )
        r1 = self.handler.promote(req1)
        assert r1.status == EnumPromotionStatus.PROMOTED

        # Re-promote with lower evidence_count=3 — must not bump version
        req2 = _request(evidence_count=3, min_evidence_count=3)
        r2 = self.handler.promote(req2)

        assert r2.status == EnumPromotionStatus.ALREADY_CURRENT
        assert r1.promoted_pattern is not None
        assert r2.promoted_pattern is not None
        assert r2.promoted_pattern.version == 1
        assert (
            r2.promoted_pattern.evidence_count == 4
        )  # higher-evidence pattern preserved

    def test_result_contains_evidence_count(self) -> None:
        extra_bundles = tuple(f"bundle-{uuid.uuid4()}" for _ in range(2))
        req = _request(
            evidence_count=5,
            min_evidence_count=3,
            evidence_bundle_ids=_BUNDLE_IDS + extra_bundles,
        )
        result = self.handler.promote(req)
        assert result.evidence_count == 5

    def test_result_contains_min_evidence_required(self) -> None:
        req = _request(evidence_count=3, min_evidence_count=4)
        result = self.handler.promote(req)
        assert result.min_evidence_required == 4

    def test_skipped_pattern_not_stored(self) -> None:
        req = _request(evidence_count=1, min_evidence_count=5)
        self.handler.promote(req)
        key = _derive_pattern_key(req.intent_type, req.unit_specs)
        assert self.store.get_by_key(key) is None


# ---------------------------------------------------------------------------
# R3: Pattern retrieval (cache hit / miss)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPatternRetrieval:
    def setup_method(self) -> None:
        self.store = StorePatternInMemory()
        self.handler = HandlerPatternPromotionDefault(self.store)

    def test_lookup_returns_none_for_unknown_pattern(self) -> None:
        result = self.handler.lookup("UNKNOWN_INTENT", _UNIT_SPECS)
        assert result is None

    def test_lookup_returns_pattern_after_promotion(self) -> None:
        req = _request(evidence_count=3, min_evidence_count=3)
        self.handler.promote(req)
        result = self.handler.lookup(req.intent_type, req.unit_specs)
        assert result is not None
        assert result.intent_type == req.intent_type

    def test_cache_miss_does_not_raise(self) -> None:
        result = self.handler.lookup("NONEXISTENT", _UNIT_SPECS)
        assert result is None

    def test_store_get_by_key_returns_none_for_unknown(self) -> None:
        result = self.store.get_by_key("nonexistent-key")
        assert result is None

    def test_store_get_by_id_raises_for_unknown(self) -> None:
        with pytest.raises(KeyError):
            self.store.get_by_id("nonexistent-id")

    def test_store_get_by_id_returns_pattern(self) -> None:
        req = _request(evidence_count=3, min_evidence_count=3)
        result = self.handler.promote(req)
        assert result.promoted_pattern is not None
        pattern_id = result.promoted_pattern.pattern_id
        retrieved = self.store.get_by_id(pattern_id)
        assert retrieved.pattern_id == pattern_id

    def test_different_intents_different_patterns(self) -> None:
        req1 = _request(intent_type="FEATURE", evidence_count=3)
        req2 = _request(intent_type="BUG", evidence_count=3)
        r1 = self.handler.promote(req1)
        r2 = self.handler.promote(req2)
        assert r1.pattern_key != r2.pattern_key
        assert r1.promoted_pattern is not None
        assert r2.promoted_pattern is not None
        assert r1.promoted_pattern.pattern_id != r2.promoted_pattern.pattern_id
