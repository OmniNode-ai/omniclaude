# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for FixTransition OmniIntelligence integration.

Tests:
- ContextItem model (frozen, fields)
- PatternPromotionCandidate model (frozen, fields)
- FixTransitionEvent dataclass
- build_context_item_from_fix_transition (content, metadata fields)
- score_file_touched_match (zero count, linear scaling, cap at 1.0)
- score_failure_signature_match (match, no match, None session)
- check_pattern_promotion (below threshold, at threshold, above threshold)
- parse_fix_transition_event (valid payload, missing fields, wrong event_type, invalid JSON)
- process_fix_transition_event:
  - valid event → stored → no promotion
  - valid event → stored → promotion triggered
  - store raises exception → error recorded
  - promotion lookup raises → error recorded, still returns result
  - promotion handler raises → error recorded, still returns result
  - malformed payload → returns None
"""

from __future__ import annotations

import json
from uuid import UUID, uuid4

import pytest

from omniclaude.trace.fix_transition import FixTransition
from omniclaude.trace.intelligence_integration import (
    CONTEXT_ITEM_TYPE,
    PATTERN_PROMOTION_THRESHOLD,
    ContextItem,
    FixTransitionEvent,
    FixTransitionProcessingResult,
    PatternPromotionCandidate,
    build_context_item_from_fix_transition,
    check_pattern_promotion,
    parse_fix_transition_event,
    process_fix_transition_event,
    score_failure_signature_match,
    score_file_touched_match,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TIMESTAMP = "2026-02-21T12:00:00Z"
SIG_ID = "sig-001"


def make_fix_transition(
    failure_sig: str = SIG_ID,
    files: list[str] | None = None,
    delta_hash: str | None = None,
) -> FixTransition:
    if files is None:
        files = ["src/router.py"]
    if delta_hash is None:
        delta_hash = "a" * 64
    return FixTransition(
        transition_id=uuid4(),
        failure_signature_id=failure_sig,
        initial_frame_id=uuid4(),
        success_frame_id=uuid4(),
        delta_hash=delta_hash,
        files_involved=files,
    )


def make_valid_payload(
    failure_sig: str = SIG_ID,
    files: list[str] | None = None,
    delta_hash: str | None = None,
    primary_signal: str = "AssertionError",
    failure_type: str = "test_fail",
) -> str:
    if files is None:
        files = ["src/router.py"]
    if delta_hash is None:
        delta_hash = "b" * 64
    return json.dumps(
        {
            "event_type": "fix_transition",
            "transition_id": str(uuid4()),
            "failure_signature_id": failure_sig,
            "initial_frame_id": str(uuid4()),
            "success_frame_id": str(uuid4()),
            "delta_hash": delta_hash,
            "files_involved": files,
            "failure_type": failure_type,
            "primary_signal": primary_signal,
            "timestamp": TIMESTAMP,
        }
    )


# ---------------------------------------------------------------------------
# TestContextItem
# ---------------------------------------------------------------------------


class TestContextItem:
    def test_valid_item(self) -> None:
        item = ContextItem(
            item_type=CONTEXT_ITEM_TYPE,
            content="Fix for AssertionError: changed src/a.py",
            failure_signature_id=SIG_ID,
            failure_type="test_fail",
            delta_hash="a" * 64,
            files_involved=["src/a.py"],
            initial_frame_id=str(uuid4()),
            success_frame_id=str(uuid4()),
            primary_signal="AssertionError",
        )
        assert item.item_type == "FAILURE_PATTERN"
        assert item.failure_signature_id == SIG_ID

    def test_is_frozen(self) -> None:
        item = ContextItem(
            item_type=CONTEXT_ITEM_TYPE,
            content="x",
            failure_signature_id=SIG_ID,
            failure_type="test_fail",
            delta_hash="a" * 64,
            files_involved=[],
            initial_frame_id=str(uuid4()),
            success_frame_id=str(uuid4()),
            primary_signal="err",
        )
        with pytest.raises(Exception):
            item.content = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# TestPatternPromotionCandidate
# ---------------------------------------------------------------------------


class TestPatternPromotionCandidate:
    def test_valid_candidate(self) -> None:
        c = PatternPromotionCandidate(
            failure_signature_id=SIG_ID,
            delta_hash="a" * 64,
            occurrence_count=5,
            files_involved=["src/a.py"],
            promotion_message="Consider automating.",
        )
        assert c.occurrence_count == 5
        assert "sig-001" in c.failure_signature_id

    def test_is_frozen(self) -> None:
        c = PatternPromotionCandidate(
            failure_signature_id=SIG_ID,
            delta_hash="a" * 64,
            occurrence_count=3,
            files_involved=[],
            promotion_message="msg",
        )
        with pytest.raises(Exception):
            c.occurrence_count = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# TestBuildContextItemFromFixTransition
# ---------------------------------------------------------------------------


class TestBuildContextItemFromFixTransition:
    def test_item_type_is_failure_pattern(self) -> None:
        ft = make_fix_transition()
        item = build_context_item_from_fix_transition(ft, "test_fail", "AssertionError")
        assert item.item_type == "FAILURE_PATTERN"

    def test_content_includes_primary_signal(self) -> None:
        ft = make_fix_transition()
        item = build_context_item_from_fix_transition(ft, "test_fail", "AssertionError")
        assert "AssertionError" in item.content

    def test_content_includes_files(self) -> None:
        ft = make_fix_transition(files=["src/alpha.py", "src/beta.py"])
        item = build_context_item_from_fix_transition(ft, "lint_fail", "E501")
        assert "src/alpha.py" in item.content
        assert "src/beta.py" in item.content

    def test_content_no_files_fallback(self) -> None:
        ft = make_fix_transition(files=[])
        item = build_context_item_from_fix_transition(ft, "test_fail", "Error")
        assert "Fix for Error" in item.content

    def test_failure_signature_id_copied(self) -> None:
        ft = make_fix_transition(failure_sig="sig-xyz")
        item = build_context_item_from_fix_transition(ft, "test_fail", "X")
        assert item.failure_signature_id == "sig-xyz"

    def test_delta_hash_copied(self) -> None:
        ft = make_fix_transition(delta_hash="c" * 64)
        item = build_context_item_from_fix_transition(ft, "test_fail", "X")
        assert item.delta_hash == "c" * 64

    def test_frame_ids_are_strings(self) -> None:
        ft = make_fix_transition()
        item = build_context_item_from_fix_transition(ft, "test_fail", "X")
        assert isinstance(item.initial_frame_id, str)
        assert isinstance(item.success_frame_id, str)
        # Verify they are valid UUIDs
        UUID(item.initial_frame_id)
        UUID(item.success_frame_id)

    def test_primary_signal_copied(self) -> None:
        ft = make_fix_transition()
        item = build_context_item_from_fix_transition(ft, "test_fail", "MyError")
        assert item.primary_signal == "MyError"

    def test_failure_type_copied(self) -> None:
        ft = make_fix_transition()
        item = build_context_item_from_fix_transition(ft, "lint_fail", "E501")
        assert item.failure_type == "lint_fail"


# ---------------------------------------------------------------------------
# TestScoreFileTouchedMatch
# ---------------------------------------------------------------------------


class TestScoreFileTouchedMatch:
    def test_zero_count_returns_zero(self) -> None:
        assert score_file_touched_match("src/a.py", 0) == 0.0

    def test_negative_count_returns_zero(self) -> None:
        assert score_file_touched_match("src/a.py", -1) == 0.0

    def test_one_fix_returns_0_2(self) -> None:
        assert score_file_touched_match("src/a.py", 1) == pytest.approx(0.2)

    def test_five_fixes_returns_1_0(self) -> None:
        assert score_file_touched_match("src/a.py", 5) == pytest.approx(1.0)

    def test_capped_at_1_0(self) -> None:
        assert score_file_touched_match("src/a.py", 100) == pytest.approx(1.0)

    def test_score_is_linear_up_to_cap(self) -> None:
        for count in range(1, 5):
            expected = count * 0.2
            assert score_file_touched_match("x.py", count) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# TestScoreFailureSignatureMatch
# ---------------------------------------------------------------------------


class TestScoreFailureSignatureMatch:
    def test_matching_signatures_returns_1_0(self) -> None:
        assert score_failure_signature_match("sig-001", "sig-001") == 1.0

    def test_non_matching_signatures_returns_0_0(self) -> None:
        assert score_failure_signature_match("sig-001", "sig-002") == 0.0

    def test_none_session_sig_returns_0_0(self) -> None:
        assert score_failure_signature_match(None, "sig-001") == 0.0

    def test_empty_string_mismatch(self) -> None:
        assert score_failure_signature_match("", "sig-001") == 0.0

    def test_empty_string_match(self) -> None:
        assert score_failure_signature_match("", "") == 1.0


# ---------------------------------------------------------------------------
# TestCheckPatternPromotion
# ---------------------------------------------------------------------------


class TestCheckPatternPromotion:
    def test_below_threshold_returns_none(self) -> None:
        result = check_pattern_promotion(SIG_ID, "a" * 64, 2, [], threshold=3)
        assert result is None

    def test_at_threshold_returns_candidate(self) -> None:
        result = check_pattern_promotion(SIG_ID, "a" * 64, 3, [], threshold=3)
        assert result is not None
        assert isinstance(result, PatternPromotionCandidate)

    def test_above_threshold_returns_candidate(self) -> None:
        result = check_pattern_promotion(SIG_ID, "a" * 64, 10, [], threshold=3)
        assert result is not None
        assert result.occurrence_count == 10

    def test_candidate_includes_failure_sig(self) -> None:
        result = check_pattern_promotion("sig-xyz", "a" * 64, 5, [], threshold=3)
        assert result is not None
        assert result.failure_signature_id == "sig-xyz"

    def test_candidate_includes_delta_hash(self) -> None:
        result = check_pattern_promotion(SIG_ID, "d" * 64, 5, [], threshold=3)
        assert result is not None
        assert result.delta_hash == "d" * 64

    def test_candidate_includes_files(self) -> None:
        files = ["src/a.py", "src/b.py"]
        result = check_pattern_promotion(SIG_ID, "a" * 64, 5, files, threshold=3)
        assert result is not None
        assert result.files_involved == files

    def test_promotion_message_contains_sig(self) -> None:
        result = check_pattern_promotion("sig-abc", "a" * 64, 5, [], threshold=3)
        assert result is not None
        assert "sig-abc" in result.promotion_message

    def test_custom_threshold(self) -> None:
        assert check_pattern_promotion(SIG_ID, "a" * 64, 9, [], threshold=10) is None
        assert (
            check_pattern_promotion(SIG_ID, "a" * 64, 10, [], threshold=10) is not None
        )

    def test_default_threshold_is_constant(self) -> None:
        # Without explicit threshold, uses PATTERN_PROMOTION_THRESHOLD
        below = check_pattern_promotion(
            SIG_ID, "a" * 64, PATTERN_PROMOTION_THRESHOLD - 1, []
        )
        at = check_pattern_promotion(SIG_ID, "a" * 64, PATTERN_PROMOTION_THRESHOLD, [])
        assert below is None
        assert at is not None


# ---------------------------------------------------------------------------
# TestParseFixTransitionEvent
# ---------------------------------------------------------------------------


class TestParseFixTransitionEvent:
    def test_valid_payload_returns_event(self) -> None:
        payload = make_valid_payload()
        event = parse_fix_transition_event(payload)
        assert event is not None
        assert isinstance(event, FixTransitionEvent)

    def test_event_fields_populated(self) -> None:
        payload = make_valid_payload(
            failure_sig="sig-xyz",
            files=["src/a.py"],
            primary_signal="E501",
            failure_type="lint_fail",
        )
        event = parse_fix_transition_event(payload)
        assert event is not None
        assert event.failure_signature_id == "sig-xyz"
        assert event.files_involved == ["src/a.py"]
        assert event.primary_signal == "E501"
        assert event.failure_type == "lint_fail"
        assert event.timestamp == TIMESTAMP

    def test_invalid_json_returns_none(self) -> None:
        assert parse_fix_transition_event("{not valid json") is None

    def test_missing_required_field_returns_none(self) -> None:
        data = json.loads(make_valid_payload())
        del data["failure_signature_id"]
        assert parse_fix_transition_event(json.dumps(data)) is None

    def test_wrong_event_type_returns_none(self) -> None:
        data = json.loads(make_valid_payload())
        data["event_type"] = "other_event"
        assert parse_fix_transition_event(json.dumps(data)) is None

    def test_non_list_files_returns_none(self) -> None:
        data = json.loads(make_valid_payload())
        data["files_involved"] = "src/a.py"  # not a list
        assert parse_fix_transition_event(json.dumps(data)) is None

    def test_empty_files_list_is_valid(self) -> None:
        payload = make_valid_payload(files=[])
        event = parse_fix_transition_event(payload)
        assert event is not None
        assert event.files_involved == []

    def test_files_are_coerced_to_strings(self) -> None:
        data = json.loads(make_valid_payload())
        data["files_involved"] = [1, 2, 3]  # ints, not strings
        event = parse_fix_transition_event(json.dumps(data))
        assert event is not None
        assert event.files_involved == ["1", "2", "3"]


# ---------------------------------------------------------------------------
# TestProcessFixTransitionEvent
# ---------------------------------------------------------------------------


class TestProcessFixTransitionEvent:
    def _make_stores(
        self,
        store_returns: bool = True,
        occurrence_count: int = 0,
        store_raises: Exception | None = None,
        lookup_raises: Exception | None = None,
    ) -> tuple[list[ContextItem], list[PatternPromotionCandidate]]:
        stored_items: list[ContextItem] = []
        promoted: list[PatternPromotionCandidate] = []

        def store(item: ContextItem) -> bool:
            if store_raises is not None:
                raise store_raises
            stored_items.append(item)
            return store_returns

        def lookup(sig_id: str, delta_hash: str) -> int:
            if lookup_raises is not None:
                raise lookup_raises
            return occurrence_count

        def handle_promo(candidate: PatternPromotionCandidate) -> None:
            promoted.append(candidate)

        self._store = store
        self._lookup = lookup
        self._handle = handle_promo
        return stored_items, promoted

    def test_valid_payload_returns_result(self) -> None:
        payload = make_valid_payload()
        _stored, _ = self._make_stores()
        result = process_fix_transition_event(payload, self._store, self._lookup)
        assert result is not None
        assert isinstance(result, FixTransitionProcessingResult)

    def test_context_item_stored(self) -> None:
        payload = make_valid_payload(failure_sig="sig-abc")
        stored, _ = self._make_stores()
        result = process_fix_transition_event(payload, self._store, self._lookup)
        assert result is not None
        assert result.context_item_stored is True
        assert len(stored) == 1
        assert stored[0].failure_signature_id == "sig-abc"

    def test_below_threshold_no_promotion(self) -> None:
        payload = make_valid_payload()
        _stored, promoted = self._make_stores(occurrence_count=2)
        result = process_fix_transition_event(
            payload, self._store, self._lookup, handle_promotion=self._handle
        )
        assert result is not None
        assert result.promotion_candidate is None
        assert len(promoted) == 0

    def test_at_threshold_promotion_triggered(self) -> None:
        payload = make_valid_payload()
        _stored, promoted = self._make_stores(
            occurrence_count=PATTERN_PROMOTION_THRESHOLD
        )
        result = process_fix_transition_event(
            payload, self._store, self._lookup, handle_promotion=self._handle
        )
        assert result is not None
        assert result.promotion_candidate is not None
        assert len(promoted) == 1

    def test_store_failure_recorded_in_errors(self) -> None:
        payload = make_valid_payload()
        self._make_stores(store_raises=RuntimeError("DB down"))
        result = process_fix_transition_event(payload, self._store, self._lookup)
        assert result is not None
        assert result.context_item_stored is False
        assert any("store" in e.lower() for e in result.errors)

    def test_lookup_failure_recorded_in_errors(self) -> None:
        payload = make_valid_payload()
        self._make_stores(lookup_raises=RuntimeError("lookup failed"))
        result = process_fix_transition_event(payload, self._store, self._lookup)
        assert result is not None
        assert any("promotion" in e.lower() for e in result.errors)

    def test_promotion_handler_failure_recorded(self) -> None:
        payload = make_valid_payload()
        self._make_stores(occurrence_count=PATTERN_PROMOTION_THRESHOLD)

        def bad_handler(c: PatternPromotionCandidate) -> None:
            raise RuntimeError("handler failed")

        result = process_fix_transition_event(
            payload, self._store, self._lookup, handle_promotion=bad_handler
        )
        assert result is not None
        assert any("promotion" in e.lower() for e in result.errors)

    def test_malformed_payload_returns_none(self) -> None:
        self._make_stores()
        result = process_fix_transition_event("{bad json", self._store, self._lookup)
        assert result is None

    def test_event_included_in_result(self) -> None:
        payload = make_valid_payload(failure_sig="sig-check")
        self._make_stores()
        result = process_fix_transition_event(payload, self._store, self._lookup)
        assert result is not None
        assert result.event.failure_signature_id == "sig-check"

    def test_context_item_included_in_result(self) -> None:
        payload = make_valid_payload(primary_signal="TypeError")
        self._make_stores()
        result = process_fix_transition_event(payload, self._store, self._lookup)
        assert result is not None
        assert result.context_item.primary_signal == "TypeError"

    def test_no_errors_on_clean_run(self) -> None:
        payload = make_valid_payload()
        self._make_stores()
        result = process_fix_transition_event(payload, self._store, self._lookup)
        assert result is not None
        assert result.errors == []

    def test_custom_promotion_threshold(self) -> None:
        payload = make_valid_payload()
        _, promoted = self._make_stores(occurrence_count=2)
        # With threshold=2, occurrence_count=2 should promote
        result = process_fix_transition_event(
            payload,
            self._store,
            self._lookup,
            handle_promotion=self._handle,
            promotion_threshold=2,
        )
        assert result is not None
        assert result.promotion_candidate is not None
        assert len(promoted) == 1
