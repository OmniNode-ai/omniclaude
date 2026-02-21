"""Unit tests for FixTransition detection and Kafka emission.

Tests:
- FixTransition model (frozen, fields)
- OpenFailure dataclass
- compute_fix_diff_hash (deterministic)
- extract_unique_files (union, deduplication)
- detect_fix_transition:
  - fail frame → no transition
  - pass frame, no prior failures → no transition
  - pass frame, one open failure → transition detected
  - pass frame, multiple open failures → first resolved
  - already-resolved failure → no duplicate transition
  - cross-session isolation (different trace_id → no match)
- serialize_fix_transition_event (JSON structure)
- emit_fix_transition_event (success, failure, exception)
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from omniclaude.trace.change_frame import (
    ChangeFrame,
    ModelCheckResult,
    ModelDelta,
    ModelEvidence,
    ModelFrameConfig,
    ModelIntentRef,
    ModelOutcome,
    ModelToolEvent,
    ModelWorkspaceRef,
)
from omniclaude.trace.fix_transition import (
    FIX_TRANSITION_TOPIC,
    FixTransition,
    OpenFailure,
    compute_fix_diff_hash,
    detect_fix_transition,
    emit_fix_transition_event,
    extract_unique_files,
    serialize_fix_transition_event,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TIMESTAMP = "2026-02-21T12:00:00Z"
TRACE_ID = "trace-abc-123"

DIFF_PATCH_FAIL = """\
--- a/src/router.py
+++ b/src/router.py
@@ -1,1 +1,2 @@
 original = True
+broken = True
"""

DIFF_PATCH_FIX = """\
--- a/src/router.py
+++ b/src/router.py
@@ -1,2 +1,2 @@
 original = True
-broken = True
+fixed = True
"""


def make_check_result(exit_code: int = 0) -> ModelCheckResult:
    from omniclaude.trace.frame_assembler import sha256_of

    return ModelCheckResult(
        command="ruff check src/",
        environment_hash="env-hash",
        exit_code=exit_code,
        output_hash=sha256_of("output"),
        truncated_output="",
    )


def make_change_frame(
    outcome_status: str = "pass",
    trace_id: str = TRACE_ID,
    diff_patch: str = DIFF_PATCH_FIX,
    files_changed: list[str] | None = None,
    failure_sig_id: str | None = None,
) -> ChangeFrame:
    from omniclaude.trace.frame_assembler import sha256_of

    if files_changed is None:
        files_changed = ["src/router.py"]

    check_exit = 0 if outcome_status == "pass" else 1
    failure_sig = failure_sig_id if outcome_status != "pass" else None

    return ChangeFrame(
        frame_id=uuid4(),
        parent_frame_id=None,
        trace_id=trace_id,
        timestamp_utc=TIMESTAMP,
        agent_id="agent-test",
        model_id="claude-sonnet-4-5",
        frame_config=ModelFrameConfig(),
        intent_ref=ModelIntentRef(prompt_hash=sha256_of("prompt")),
        workspace_ref=ModelWorkspaceRef(
            repo="OmniNode-ai/omniclaude",
            branch="feature/test",
            base_commit="abc" + "0" * 37,
        ),
        delta=ModelDelta(
            diff_patch=diff_patch,
            files_changed=files_changed,
            loc_added=1,
            loc_removed=0,
        ),
        tool_events=[
            ModelToolEvent(
                tool_name="Edit",
                input_hash=sha256_of("input"),
                output_hash=sha256_of("output"),
                raw_pointer=None,
            )
        ],
        checks=[make_check_result(check_exit)],
        outcome=ModelOutcome(
            status=outcome_status,  # type: ignore[arg-type]
            failure_signature_id=failure_sig,
        ),
        evidence=ModelEvidence(),
    )


def make_open_failure(
    trace_id: str = TRACE_ID,
    failure_signature_id: str = "sig-001",
    diff_patch: str = DIFF_PATCH_FAIL,
    files_changed: list[str] | None = None,
    already_resolved: bool = False,
) -> OpenFailure:
    if files_changed is None:
        files_changed = ["src/router.py"]
    return OpenFailure(
        frame_id=uuid4(),
        trace_id=trace_id,
        failure_signature_id=failure_signature_id,
        diff_patch=diff_patch,
        files_changed=files_changed,
        already_resolved=already_resolved,
    )


# ---------------------------------------------------------------------------
# FixTransition model tests
# ---------------------------------------------------------------------------


class TestFixTransition:
    def test_valid_transition(self) -> None:
        t = FixTransition(
            transition_id=uuid4(),
            failure_signature_id="sig-001",
            initial_frame_id=uuid4(),
            success_frame_id=uuid4(),
            delta_hash="a" * 64,
            files_involved=["src/router.py"],
        )
        assert t.failure_signature_id == "sig-001"
        assert len(t.files_involved) == 1

    def test_is_frozen(self) -> None:
        t = FixTransition(
            transition_id=uuid4(),
            failure_signature_id="sig-001",
            initial_frame_id=uuid4(),
            success_frame_id=uuid4(),
            delta_hash="a" * 64,
            files_involved=[],
        )
        with pytest.raises(Exception):
            t.failure_signature_id = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# compute_fix_diff_hash tests
# ---------------------------------------------------------------------------


class TestComputeFixDiffHash:
    def test_deterministic(self) -> None:
        h1 = compute_fix_diff_hash("patch-a", "patch-b")
        h2 = compute_fix_diff_hash("patch-a", "patch-b")
        assert h1 == h2

    def test_different_patches_different_hash(self) -> None:
        h1 = compute_fix_diff_hash("patch-a", "patch-b")
        h2 = compute_fix_diff_hash("patch-x", "patch-y")
        assert h1 != h2

    def test_order_matters(self) -> None:
        h1 = compute_fix_diff_hash("initial", "success")
        h2 = compute_fix_diff_hash("success", "initial")
        assert h1 != h2

    def test_returns_64_hex_chars(self) -> None:
        h = compute_fix_diff_hash("a", "b")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


# ---------------------------------------------------------------------------
# extract_unique_files tests
# ---------------------------------------------------------------------------


class TestExtractUniqueFiles:
    def test_union_of_disjoint_sets(self) -> None:
        result = extract_unique_files(["a.py"], ["b.py"])
        assert result == ["a.py", "b.py"]

    def test_deduplication(self) -> None:
        result = extract_unique_files(["a.py", "b.py"], ["b.py", "c.py"])
        assert result == ["a.py", "b.py", "c.py"]

    def test_sorted(self) -> None:
        result = extract_unique_files(["z.py", "a.py"], ["m.py"])
        assert result == ["a.py", "m.py", "z.py"]

    def test_empty_both(self) -> None:
        assert extract_unique_files([], []) == []

    def test_one_empty(self) -> None:
        assert extract_unique_files(["a.py"], []) == ["a.py"]


# ---------------------------------------------------------------------------
# detect_fix_transition tests
# ---------------------------------------------------------------------------


class TestDetectFixTransition:
    def test_fail_frame_returns_none(self) -> None:
        frame = make_change_frame(outcome_status="fail")
        failures = [make_open_failure()]
        result = detect_fix_transition(frame, failures)
        assert result is None

    def test_partial_frame_returns_none(self) -> None:
        frame = make_change_frame(outcome_status="partial")
        failures = [make_open_failure()]
        result = detect_fix_transition(frame, failures)
        assert result is None

    def test_pass_with_no_prior_failures_returns_none(self) -> None:
        frame = make_change_frame(outcome_status="pass")
        result = detect_fix_transition(frame, [])
        assert result is None

    def test_pass_resolves_open_failure(self) -> None:
        failure = make_open_failure(failure_signature_id="sig-42")
        frame = make_change_frame(outcome_status="pass")

        result = detect_fix_transition(frame, [failure])

        assert result is not None
        assert result.failure_signature_id == "sig-42"
        assert result.initial_frame_id == failure.frame_id
        assert result.success_frame_id == frame.frame_id

    def test_already_resolved_failure_skipped(self) -> None:
        failure = make_open_failure(already_resolved=True)
        frame = make_change_frame(outcome_status="pass")

        result = detect_fix_transition(frame, [failure])
        assert result is None

    def test_cross_session_isolation(self) -> None:
        """Failure from a different trace_id must not be resolved."""
        failure = make_open_failure(trace_id="other-trace")
        frame = make_change_frame(outcome_status="pass", trace_id=TRACE_ID)

        result = detect_fix_transition(frame, [failure])
        assert result is None

    def test_multiple_failures_first_resolved(self) -> None:
        """When multiple open failures exist, the first one is resolved."""
        failure1 = make_open_failure(failure_signature_id="sig-001")
        failure2 = make_open_failure(failure_signature_id="sig-002")
        frame = make_change_frame(outcome_status="pass")

        result = detect_fix_transition(frame, [failure1, failure2])

        assert result is not None
        assert result.initial_frame_id == failure1.frame_id
        assert result.failure_signature_id == "sig-001"

    def test_files_involved_is_union(self) -> None:
        failure = make_open_failure(files_changed=["src/a.py"])
        frame = make_change_frame(outcome_status="pass", files_changed=["src/b.py"])

        result = detect_fix_transition(frame, [failure])

        assert result is not None
        assert "src/a.py" in result.files_involved
        assert "src/b.py" in result.files_involved

    def test_delta_hash_is_deterministic(self) -> None:
        failure = make_open_failure()
        frame = make_change_frame(outcome_status="pass")

        result1 = detect_fix_transition(frame, [failure])
        result2 = detect_fix_transition(frame, [failure])

        assert result1 is not None
        assert result2 is not None
        assert result1.delta_hash == result2.delta_hash


# ---------------------------------------------------------------------------
# serialize_fix_transition_event tests
# ---------------------------------------------------------------------------


class TestSerializeFixTransitionEvent:
    def _make_transition(self) -> FixTransition:
        return FixTransition(
            transition_id=uuid4(),
            failure_signature_id="sig-001",
            initial_frame_id=uuid4(),
            success_frame_id=uuid4(),
            delta_hash="a" * 64,
            files_involved=["src/router.py"],
        )

    def test_returns_valid_json(self) -> None:
        t = self._make_transition()
        payload = serialize_fix_transition_event(
            t,
            failure_type="test_fail",
            primary_signal="AssertionError",
            timestamp_utc=TIMESTAMP,
        )
        data = json.loads(payload)
        assert isinstance(data, dict)

    def test_event_type_is_fix_transition(self) -> None:
        t = self._make_transition()
        payload = serialize_fix_transition_event(
            t, failure_type="test_fail", primary_signal="sig", timestamp_utc=TIMESTAMP
        )
        data = json.loads(payload)
        assert data["event_type"] == "fix_transition"

    def test_contains_all_required_fields(self) -> None:
        t = self._make_transition()
        payload = serialize_fix_transition_event(
            t, failure_type="lint_fail", primary_signal="E501", timestamp_utc=TIMESTAMP
        )
        data = json.loads(payload)
        required = [
            "event_type",
            "transition_id",
            "failure_signature_id",
            "initial_frame_id",
            "success_frame_id",
            "delta_hash",
            "files_involved",
            "failure_type",
            "primary_signal",
            "timestamp",
        ]
        for field in required:
            assert field in data, f"Missing field: {field}"

    def test_transition_id_is_string(self) -> None:
        t = self._make_transition()
        payload = serialize_fix_transition_event(
            t, failure_type="test_fail", primary_signal="err", timestamp_utc=TIMESTAMP
        )
        data = json.loads(payload)
        assert isinstance(data["transition_id"], str)


# ---------------------------------------------------------------------------
# emit_fix_transition_event tests
# ---------------------------------------------------------------------------


class TestEmitFixTransitionEvent:
    def _make_transition(self) -> FixTransition:
        return FixTransition(
            transition_id=uuid4(),
            failure_signature_id="sig-001",
            initial_frame_id=uuid4(),
            success_frame_id=uuid4(),
            delta_hash="a" * 64,
            files_involved=["src/router.py"],
        )

    def test_calls_emit_fn_with_correct_topic(self) -> None:
        t = self._make_transition()
        received_topic: list[str] = []

        def mock_emit(topic: str, payload: str) -> bool:
            received_topic.append(topic)
            return True

        emit_fix_transition_event(
            t,
            failure_type="test_fail",
            primary_signal="sig",
            timestamp_utc=TIMESTAMP,
            emit_fn=mock_emit,
        )
        assert received_topic == [FIX_TRANSITION_TOPIC]

    def test_returns_true_on_success(self) -> None:
        t = self._make_transition()
        result = emit_fix_transition_event(
            t,
            failure_type="test_fail",
            primary_signal="sig",
            timestamp_utc=TIMESTAMP,
            emit_fn=lambda _t, _p: True,
        )
        assert result is True

    def test_returns_false_on_emit_failure(self) -> None:
        t = self._make_transition()
        result = emit_fix_transition_event(
            t,
            failure_type="test_fail",
            primary_signal="sig",
            timestamp_utc=TIMESTAMP,
            emit_fn=lambda _t, _p: False,
        )
        assert result is False

    def test_returns_false_on_exception(self) -> None:
        t = self._make_transition()

        def exploding_emit(topic: str, payload: str) -> bool:
            raise RuntimeError("Kafka unavailable")

        # Must not propagate — returns False instead
        result = emit_fix_transition_event(
            t,
            failure_type="test_fail",
            primary_signal="sig",
            timestamp_utc=TIMESTAMP,
            emit_fn=exploding_emit,
        )
        assert result is False

    def test_payload_is_valid_json(self) -> None:
        t = self._make_transition()
        received_payload: list[str] = []

        def capture_emit(topic: str, payload: str) -> bool:
            received_payload.append(payload)
            return True

        emit_fix_transition_event(
            t,
            failure_type="lint_fail",
            primary_signal="E501",
            timestamp_utc=TIMESTAMP,
            emit_fn=capture_emit,
        )
        assert len(received_payload) == 1
        data = json.loads(received_payload[0])
        assert data["failure_type"] == "lint_fail"
