"""Unit tests for enrichment_observability_emitter.py (OMN-2274).

Tests cover:
- build_enrichment_event_payload: all required fields present with correct types
- emit_enrichment_events: per-channel event emission with mock emit_event
- was_dropped logic (produced but excluded by token cap)
- tokens_saved calculation (summarization channel only)
- Graceful degradation when emit_client_wrapper is unavailable
- No-op when results list is empty
- Optional handler metadata fields (model_used, relevance_score, etc.)

All tests run without network access or external services.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# sys.path setup: plugin lib modules live outside the normal package tree
# ---------------------------------------------------------------------------
_LIB_PATH = str(
    Path(__file__).parent.parent.parent.parent.parent
    / "plugins"
    / "onex"
    / "hooks"
    / "lib"
)
if _LIB_PATH not in sys.path:
    sys.path.insert(0, _LIB_PATH)

import enrichment_observability_emitter as eoe

# All tests in this module are unit tests
pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeResult:
    """Minimal _EnrichmentResult-compatible object for testing."""

    def __init__(
        self,
        name: str = "summarization",
        tokens: int = 50,
        success: bool = True,
        *,
        latency_ms: float = 12.5,
        model_used: str = "",
        relevance_score: float | None = None,
        fallback_used: bool = False,
        prompt_version: str = "",
    ) -> None:
        self.name = name
        self.tokens = tokens
        self.success = success
        self.latency_ms = latency_ms
        self.model_used = model_used
        self.relevance_score = relevance_score
        self.fallback_used = fallback_used
        self.prompt_version = prompt_version


def _make_emit_event_mock(return_value: bool = True) -> MagicMock:
    """Return a mock that behaves like emit_event."""
    return MagicMock(return_value=return_value)


# ---------------------------------------------------------------------------
# 1. build_enrichment_event_payload
# ---------------------------------------------------------------------------


class TestBuildEnrichmentEventPayload:
    """Tests for build_enrichment_event_payload()."""

    def test_all_required_fields_present(self) -> None:
        """Payload must contain all required event fields."""
        payload = eoe.build_enrichment_event_payload(
            session_id="sess-001",
            correlation_id="corr-abc",
            enrichment_type="summarization",
            model_used="qwen2.5-14b",
            latency_ms=42.7,
            result_token_count=150,
            relevance_score=0.87,
            fallback_used=False,
            tokens_saved=300,
            was_dropped=False,
            prompt_version="v2",
        )

        required_keys = {
            "session_id",
            "correlation_id",
            "enrichment_type",
            "model_used",
            "latency_ms",
            "result_token_count",
            "relevance_score",
            "fallback_used",
            "tokens_saved",
            "was_dropped",
            "prompt_version",
        }
        assert required_keys <= set(payload.keys())

    def test_field_values_match_inputs(self) -> None:
        """Payload values must exactly match the inputs."""
        payload = eoe.build_enrichment_event_payload(
            session_id="sid",
            correlation_id="cid",
            enrichment_type="code_analysis",
            model_used="coder-14b",
            latency_ms=100.0,
            result_token_count=200,
            relevance_score=0.5,
            fallback_used=True,
            tokens_saved=0,
            was_dropped=True,
            prompt_version="v1",
        )

        assert payload["session_id"] == "sid"
        assert payload["correlation_id"] == "cid"
        assert payload["enrichment_type"] == "code_analysis"
        assert payload["model_used"] == "coder-14b"
        assert payload["latency_ms"] == 100.0
        assert payload["result_token_count"] == 200
        assert payload["relevance_score"] == 0.5
        assert payload["fallback_used"] is True
        assert payload["tokens_saved"] == 0
        assert payload["was_dropped"] is True
        assert payload["prompt_version"] == "v1"

    def test_relevance_score_none_allowed(self) -> None:
        """relevance_score may be None (handler did not report it)."""
        payload = eoe.build_enrichment_event_payload(
            session_id="s",
            correlation_id="c",
            enrichment_type="similarity",
            model_used="",
            latency_ms=0.0,
            result_token_count=0,
            relevance_score=None,
            fallback_used=False,
            tokens_saved=0,
            was_dropped=False,
            prompt_version="",
        )
        assert payload["relevance_score"] is None

    def test_latency_ms_rounded_to_three_places(self) -> None:
        """latency_ms is rounded to 3 decimal places."""
        payload = eoe.build_enrichment_event_payload(
            session_id="s",
            correlation_id="c",
            enrichment_type="summarization",
            model_used="",
            latency_ms=12.3456789,
            result_token_count=0,
            relevance_score=None,
            fallback_used=False,
            tokens_saved=0,
            was_dropped=False,
            prompt_version="",
        )
        assert payload["latency_ms"] == round(12.3456789, 3)


# ---------------------------------------------------------------------------
# 2. emit_enrichment_events — basic emission
# ---------------------------------------------------------------------------


class TestEmitEnrichmentEventsBasic:
    """Tests for the primary emit_enrichment_events() flow."""

    def test_emits_one_event_per_result(self) -> None:
        """One event is emitted per _EnrichmentResult in the list."""
        mock_emit = _make_emit_event_mock(True)
        results = [
            _FakeResult(name="summarization", tokens=100, success=True),
            _FakeResult(name="code_analysis", tokens=80, success=True),
            _FakeResult(name="similarity", tokens=60, success=True),
        ]
        kept_names = {"summarization", "code_analysis", "similarity"}

        with patch.object(eoe, "emit_event", mock_emit):
            count = eoe.emit_enrichment_events(
                session_id="sess",
                correlation_id="corr",
                results=results,
                kept_names=kept_names,
            )

        assert count == 3
        assert mock_emit.call_count == 3

    def test_empty_results_emits_nothing(self) -> None:
        """When results list is empty, no events are emitted."""
        mock_emit = _make_emit_event_mock(True)
        with patch.object(eoe, "emit_event", mock_emit):
            count = eoe.emit_enrichment_events(
                session_id="sess",
                correlation_id="corr",
                results=[],
                kept_names=set(),
            )
        assert count == 0
        mock_emit.assert_not_called()

    def test_uses_context_enrichment_event_type(self) -> None:
        """Emitted event_type must be 'context.enrichment'."""
        called_types: list[str] = []

        def _capture_emit(event_type: str, payload: Any) -> bool:
            called_types.append(event_type)
            return True

        results = [_FakeResult(name="summarization", success=True, tokens=10)]
        with patch.object(eoe, "emit_event", _capture_emit):
            eoe.emit_enrichment_events(
                session_id="sess",
                correlation_id="corr",
                results=results,
                kept_names={"summarization"},
            )

        assert called_types == ["context.enrichment"]

    def test_result_with_no_name_is_skipped(self) -> None:
        """Results with empty name are skipped (no event emitted)."""
        mock_emit = _make_emit_event_mock(True)
        results = [_FakeResult(name="", success=True, tokens=10)]
        with patch.object(eoe, "emit_event", mock_emit):
            count = eoe.emit_enrichment_events(
                session_id="sess",
                correlation_id="corr",
                results=results,
                kept_names=set(),
            )
        assert count == 0
        mock_emit.assert_not_called()

    def test_failed_emit_not_counted(self) -> None:
        """When emit_event returns False, the event is not counted."""
        mock_emit = _make_emit_event_mock(False)
        results = [_FakeResult(name="summarization", success=True, tokens=50)]
        with patch.object(eoe, "emit_event", mock_emit):
            count = eoe.emit_enrichment_events(
                session_id="sess",
                correlation_id="corr",
                results=results,
                kept_names={"summarization"},
            )
        assert count == 0


# ---------------------------------------------------------------------------
# 3. was_dropped logic
# ---------------------------------------------------------------------------


class TestWasDropped:
    """Tests for the was_dropped field in emitted events."""

    def test_was_dropped_false_when_in_kept_names(self) -> None:
        """Enrichment in kept_names has was_dropped=False."""
        payloads: list[dict[str, Any]] = []

        def _capture(event_type: str, payload: dict[str, Any]) -> bool:
            payloads.append(payload)
            return True

        results = [_FakeResult(name="summarization", success=True, tokens=100)]
        with patch.object(eoe, "emit_event", _capture):
            eoe.emit_enrichment_events(
                session_id="sess",
                correlation_id="corr",
                results=results,
                kept_names={"summarization"},
            )

        assert len(payloads) == 1
        assert payloads[0]["was_dropped"] is False

    def test_was_dropped_true_when_excluded_by_token_cap(self) -> None:
        """Enrichment not in kept_names (dropped by token cap) has was_dropped=True."""
        payloads: list[dict[str, Any]] = []

        def _capture(event_type: str, payload: dict[str, Any]) -> bool:
            payloads.append(payload)
            return True

        # similarity ran successfully but was dropped by token cap
        results = [
            _FakeResult(name="summarization", success=True, tokens=1500),
            _FakeResult(name="similarity", success=True, tokens=1000),
        ]
        # Only summarization kept
        with patch.object(eoe, "emit_event", _capture):
            eoe.emit_enrichment_events(
                session_id="sess",
                correlation_id="corr",
                results=results,
                kept_names={"summarization"},
            )

        assert len(payloads) == 2
        by_type = {p["enrichment_type"]: p for p in payloads}
        assert by_type["summarization"]["was_dropped"] is False
        assert by_type["similarity"]["was_dropped"] is True

    def test_failed_result_not_marked_as_dropped(self) -> None:
        """A failed enrichment (success=False) has was_dropped=False even if absent from kept."""
        payloads: list[dict[str, Any]] = []

        def _capture(event_type: str, payload: dict[str, Any]) -> bool:
            payloads.append(payload)
            return True

        results = [_FakeResult(name="code_analysis", success=False, tokens=0)]
        with patch.object(eoe, "emit_event", _capture):
            eoe.emit_enrichment_events(
                session_id="sess",
                correlation_id="corr",
                results=results,
                kept_names=set(),
            )

        assert len(payloads) == 1
        assert payloads[0]["was_dropped"] is False


# ---------------------------------------------------------------------------
# 4. tokens_saved calculation
# ---------------------------------------------------------------------------


class TestTokensSaved:
    """Tests for the tokens_saved field (summarization channel only)."""

    def test_tokens_saved_computed_for_summarization(self) -> None:
        """tokens_saved = original_prompt_token_count - result tokens (summarization)."""
        payloads: list[dict[str, Any]] = []

        def _capture(event_type: str, payload: dict[str, Any]) -> bool:
            payloads.append(payload)
            return True

        results = [_FakeResult(name="summarization", success=True, tokens=200)]
        with patch.object(eoe, "emit_event", _capture):
            eoe.emit_enrichment_events(
                session_id="sess",
                correlation_id="corr",
                results=results,
                kept_names={"summarization"},
                original_prompt_token_count=800,
            )

        assert payloads[0]["tokens_saved"] == 600  # 800 - 200

    def test_tokens_saved_zero_for_non_summarization_channels(self) -> None:
        """tokens_saved is always 0 for code_analysis and similarity channels."""
        payloads: list[dict[str, Any]] = []

        def _capture(event_type: str, payload: dict[str, Any]) -> bool:
            payloads.append(payload)
            return True

        results = [
            _FakeResult(name="code_analysis", success=True, tokens=300),
            _FakeResult(name="similarity", success=True, tokens=150),
        ]
        with patch.object(eoe, "emit_event", _capture):
            eoe.emit_enrichment_events(
                session_id="sess",
                correlation_id="corr",
                results=results,
                kept_names={"code_analysis", "similarity"},
                original_prompt_token_count=1000,
            )

        by_type = {p["enrichment_type"]: p for p in payloads}
        assert by_type["code_analysis"]["tokens_saved"] == 0
        assert by_type["similarity"]["tokens_saved"] == 0

    def test_tokens_saved_zero_when_summarization_fails(self) -> None:
        """When summarization fails (success=False), tokens_saved=0."""
        payloads: list[dict[str, Any]] = []

        def _capture(event_type: str, payload: dict[str, Any]) -> bool:
            payloads.append(payload)
            return True

        results = [_FakeResult(name="summarization", success=False, tokens=0)]
        with patch.object(eoe, "emit_event", _capture):
            eoe.emit_enrichment_events(
                session_id="sess",
                correlation_id="corr",
                results=results,
                kept_names=set(),
                original_prompt_token_count=500,
            )

        assert payloads[0]["tokens_saved"] == 0

    def test_tokens_saved_clamped_to_zero_minimum(self) -> None:
        """tokens_saved is clamped to >= 0 (never negative)."""
        payloads: list[dict[str, Any]] = []

        def _capture(event_type: str, payload: dict[str, Any]) -> bool:
            payloads.append(payload)
            return True

        # result tokens LARGER than original prompt tokens (edge case: very short prompt)
        results = [_FakeResult(name="summarization", success=True, tokens=500)]
        with patch.object(eoe, "emit_event", _capture):
            eoe.emit_enrichment_events(
                session_id="sess",
                correlation_id="corr",
                results=results,
                kept_names={"summarization"},
                original_prompt_token_count=100,  # less than result tokens
            )

        assert payloads[0]["tokens_saved"] == 0


# ---------------------------------------------------------------------------
# 5. Optional handler metadata fields
# ---------------------------------------------------------------------------


class TestOptionalHandlerMetadata:
    """Tests for optional observability metadata propagated from handlers."""

    def test_model_used_propagated(self) -> None:
        """model_used from the handler result is included in the event."""
        payloads: list[dict[str, Any]] = []

        def _capture(event_type: str, payload: dict[str, Any]) -> bool:
            payloads.append(payload)
            return True

        results = [
            _FakeResult(
                name="code_analysis", success=True, tokens=50, model_used="coder-14b"
            )
        ]
        with patch.object(eoe, "emit_event", _capture):
            eoe.emit_enrichment_events(
                session_id="s",
                correlation_id="c",
                results=results,
                kept_names={"code_analysis"},
            )

        assert payloads[0]["model_used"] == "coder-14b"

    def test_relevance_score_propagated(self) -> None:
        """relevance_score from the handler result is included in the event."""
        payloads: list[dict[str, Any]] = []

        def _capture(event_type: str, payload: dict[str, Any]) -> bool:
            payloads.append(payload)
            return True

        results = [
            _FakeResult(
                name="similarity", success=True, tokens=40, relevance_score=0.91
            )
        ]
        with patch.object(eoe, "emit_event", _capture):
            eoe.emit_enrichment_events(
                session_id="s",
                correlation_id="c",
                results=results,
                kept_names={"similarity"},
            )

        assert payloads[0]["relevance_score"] == pytest.approx(0.91, abs=1e-6)

    def test_fallback_used_propagated(self) -> None:
        """fallback_used=True is propagated when handler reports it."""
        payloads: list[dict[str, Any]] = []

        def _capture(event_type: str, payload: dict[str, Any]) -> bool:
            payloads.append(payload)
            return True

        results = [
            _FakeResult(
                name="summarization", success=True, tokens=50, fallback_used=True
            )
        ]
        with patch.object(eoe, "emit_event", _capture):
            eoe.emit_enrichment_events(
                session_id="s",
                correlation_id="c",
                results=results,
                kept_names={"summarization"},
            )

        assert payloads[0]["fallback_used"] is True

    def test_prompt_version_propagated(self) -> None:
        """prompt_version from the handler result is included in the event."""
        payloads: list[dict[str, Any]] = []

        def _capture(event_type: str, payload: dict[str, Any]) -> bool:
            payloads.append(payload)
            return True

        results = [
            _FakeResult(
                name="code_analysis", success=True, tokens=50, prompt_version="v3"
            )
        ]
        with patch.object(eoe, "emit_event", _capture):
            eoe.emit_enrichment_events(
                session_id="s",
                correlation_id="c",
                results=results,
                kept_names={"code_analysis"},
            )

        assert payloads[0]["prompt_version"] == "v3"

    def test_defaults_when_handler_has_no_metadata_attrs(self) -> None:
        """Handler results without metadata attributes default to safe empty values."""
        payloads: list[dict[str, Any]] = []

        def _capture(event_type: str, payload: dict[str, Any]) -> bool:
            payloads.append(payload)
            return True

        # Bare object with only name/tokens/success
        class _Bare:
            name = "code_analysis"
            tokens = 30
            success = True

        results = [_Bare()]
        with patch.object(eoe, "emit_event", _capture):
            eoe.emit_enrichment_events(
                session_id="s",
                correlation_id="c",
                results=results,
                kept_names={"code_analysis"},
            )

        assert payloads[0]["model_used"] == ""
        assert payloads[0]["relevance_score"] is None
        assert payloads[0]["fallback_used"] is False
        assert payloads[0]["prompt_version"] == ""
        assert payloads[0]["latency_ms"] == 0.0


# ---------------------------------------------------------------------------
# 6. Graceful degradation when emit_client_wrapper is unavailable
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    """Tests that emission failures never propagate to callers."""

    def test_returns_zero_when_emit_event_is_none(self) -> None:
        """When emit_event is None (import failed), returns 0 silently."""
        results = [_FakeResult(name="summarization", success=True, tokens=50)]

        # Simulate the case where emit_client_wrapper was not importable at module load
        with patch.object(eoe, "emit_event", None):
            count = eoe.emit_enrichment_events(
                session_id="s",
                correlation_id="c",
                results=results,
                kept_names={"summarization"},
            )

        assert count == 0

    def test_exception_in_emit_event_does_not_propagate(self) -> None:
        """emit_event raising an exception is caught and counted as failed."""

        def _raise_emit(event_type: str, payload: Any) -> bool:
            raise RuntimeError("daemon down")

        results = [_FakeResult(name="summarization", success=True, tokens=50)]
        with patch.object(eoe, "emit_event", _raise_emit):
            # Should not raise
            count = eoe.emit_enrichment_events(
                session_id="s",
                correlation_id="c",
                results=results,
                kept_names={"summarization"},
            )
        assert count == 0


# ---------------------------------------------------------------------------
# 7. _extract_* helper functions
# ---------------------------------------------------------------------------


class TestExtractHelpers:
    """Unit tests for internal extraction helpers."""

    def test_extract_model_used_from_attr(self) -> None:
        """_extract_model_used reads the model_used attribute."""
        r = _FakeResult(model_used="qwen-72b")
        assert eoe._extract_model_used(r) == "qwen-72b"

    def test_extract_model_used_fallback_when_attr_missing(self) -> None:
        """_extract_model_used returns '' when attribute is absent."""

        class _No:
            pass

        assert eoe._extract_model_used(_No()) == ""

    def test_extract_relevance_score_returns_float(self) -> None:
        """_extract_relevance_score converts to float when present."""
        r = _FakeResult(relevance_score=0.75)
        assert eoe._extract_relevance_score(r) == pytest.approx(0.75)

    def test_extract_relevance_score_returns_none_on_absence(self) -> None:
        """_extract_relevance_score returns None when attribute is missing."""

        class _No:
            pass

        assert eoe._extract_relevance_score(_No()) is None

    def test_extract_relevance_score_returns_none_on_bad_type(self) -> None:
        """_extract_relevance_score returns None on unconvertible values."""
        r = _FakeResult(relevance_score="bad")  # type: ignore[arg-type]
        # "bad" cannot be converted to float
        result = eoe._extract_relevance_score(r)
        # "bad" can't convert
        assert result is None

    def test_extract_fallback_used_true(self) -> None:
        r = _FakeResult(fallback_used=True)
        assert eoe._extract_fallback_used(r) is True

    def test_extract_fallback_used_default_false(self) -> None:
        class _No:
            pass

        assert eoe._extract_fallback_used(_No()) is False

    def test_extract_prompt_version_reads_attr(self) -> None:
        r = _FakeResult(prompt_version="v42")
        assert eoe._extract_prompt_version(r) == "v42"

    def test_extract_prompt_version_returns_empty_when_missing(self) -> None:
        class _No:
            pass

        assert eoe._extract_prompt_version(_No()) == ""

    def test_extract_latency_ms_reads_attr(self) -> None:
        r = _FakeResult(latency_ms=99.5)
        assert eoe._extract_latency_ms(r) == pytest.approx(99.5)

    def test_extract_latency_ms_returns_zero_when_missing(self) -> None:
        class _No:
            pass

        assert eoe._extract_latency_ms(_No()) == 0.0
