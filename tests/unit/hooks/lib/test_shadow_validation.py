# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Tests for shadow_validation.py (OMN-2283).

Covers:
- Feature flag gating (ENABLE_SHADOW_VALIDATION, auto-disable via exit criteria)
- Sampling decision (_should_sample determinism and edge cases)
- Output comparison (compare_responses: length divergence, keyword overlap, structural match)
- Quality gate pass/fail for each metric
- Background thread dispatch (run_shadow_validation returns True when thread started)
- Non-blocking contract (run_shadow_validation never raises)
- Shadow event schema (ModelDelegationShadowComparisonPayload)
- Integration: delegation_orchestrator calls shadow validation after success
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError

# Insert hooks/lib so shadow_validation can be imported directly.
_HOOKS_LIB = (
    Path(__file__).parent.parent.parent.parent.parent
    / "plugins"
    / "onex"
    / "hooks"
    / "lib"
)
if str(_HOOKS_LIB) not in sys.path:
    sys.path.insert(0, str(_HOOKS_LIB))

import shadow_validation as sv  # noqa: E402 I001


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FIXED_EMITTED_AT = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)
_FIXED_CORR_ID = str(uuid4())


def _enable_shadow(monkeypatch: pytest.MonkeyPatch, rate: str = "1.0") -> None:
    """Enable shadow validation with sampling rate 100% (sample everything)."""
    monkeypatch.setenv("ENABLE_SHADOW_VALIDATION", "true")
    monkeypatch.setenv("SHADOW_SAMPLE_RATE", rate)
    monkeypatch.setenv("SHADOW_CONSECUTIVE_PASSING_DAYS", "0")
    monkeypatch.setenv("SHADOW_EXIT_WINDOW_DAYS", "30")


# ---------------------------------------------------------------------------
# Feature flag tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFeatureFlags:
    """Shadow validation is disabled unless ENABLE_SHADOW_VALIDATION=true."""

    def test_disabled_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Flag not set → _is_shadow_validation_enabled returns False."""
        monkeypatch.delenv("ENABLE_SHADOW_VALIDATION", raising=False)
        assert sv._is_shadow_validation_enabled() is False

    def test_enabled_when_flag_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Flag set to 'true' → returns True."""
        monkeypatch.setenv("ENABLE_SHADOW_VALIDATION", "true")
        monkeypatch.setenv("SHADOW_CONSECUTIVE_PASSING_DAYS", "0")
        monkeypatch.setenv("SHADOW_EXIT_WINDOW_DAYS", "30")
        assert sv._is_shadow_validation_enabled() is True

    def test_truthy_variants(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """All truthy variants (1, yes, on) enable shadow validation."""
        monkeypatch.setenv("SHADOW_CONSECUTIVE_PASSING_DAYS", "0")
        monkeypatch.setenv("SHADOW_EXIT_WINDOW_DAYS", "30")
        for value in ("1", "yes", "on", "TRUE"):
            monkeypatch.setenv("ENABLE_SHADOW_VALIDATION", value)
            assert sv._is_shadow_validation_enabled() is True

    def test_falsy_values_disable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Falsy values (false, 0, no, off) disable shadow validation."""
        for value in ("false", "0", "no", "off", ""):
            monkeypatch.setenv("ENABLE_SHADOW_VALIDATION", value)
            assert sv._is_shadow_validation_enabled() is False


# ---------------------------------------------------------------------------
# Exit criteria / auto-disable tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExitCriteria:
    """Auto-disable triggers when consecutive_passing_days >= exit_window_days."""

    def test_auto_disable_when_window_met(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """30 consecutive passing days with 30-day window → auto-disabled."""
        monkeypatch.setenv("ENABLE_SHADOW_VALIDATION", "true")
        monkeypatch.setenv("SHADOW_CONSECUTIVE_PASSING_DAYS", "30")
        monkeypatch.setenv("SHADOW_EXIT_WINDOW_DAYS", "30")
        assert sv._is_shadow_validation_enabled() is False

    def test_auto_disable_when_window_exceeded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """More than window days → auto-disabled."""
        monkeypatch.setenv("ENABLE_SHADOW_VALIDATION", "true")
        monkeypatch.setenv("SHADOW_CONSECUTIVE_PASSING_DAYS", "45")
        monkeypatch.setenv("SHADOW_EXIT_WINDOW_DAYS", "30")
        assert sv._is_shadow_validation_enabled() is False

    def test_not_auto_disabled_below_window(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """29 consecutive days with 30-day window → still enabled."""
        monkeypatch.setenv("ENABLE_SHADOW_VALIDATION", "true")
        monkeypatch.setenv("SHADOW_CONSECUTIVE_PASSING_DAYS", "29")
        monkeypatch.setenv("SHADOW_EXIT_WINDOW_DAYS", "30")
        assert sv._is_shadow_validation_enabled() is True

    def test_auto_disable_overrides_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Even with flag=true, auto-disable condition suppresses shadow validation."""
        monkeypatch.setenv("ENABLE_SHADOW_VALIDATION", "true")
        monkeypatch.setenv("SHADOW_CONSECUTIVE_PASSING_DAYS", "30")
        monkeypatch.setenv("SHADOW_EXIT_WINDOW_DAYS", "30")
        # run_shadow_validation should return False without starting a thread
        result = sv.run_shadow_validation(
            prompt="generate tests for my module",
            local_response="def test_foo(): assert True",
            local_model="qwen-14b",
            session_id="sess-1",
            correlation_id=_FIXED_CORR_ID,
            task_type="test",
            emitted_at=_FIXED_EMITTED_AT,
        )
        assert result is False


# ---------------------------------------------------------------------------
# Sampling tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSamplingDecision:
    """_should_sample returns deterministic results for the same correlation_id."""

    def test_always_sampled_at_rate_1(self) -> None:
        """Sample rate 1.0 always returns True."""
        assert sv._should_sample("any-correlation-id", 1.0) is True

    def test_never_sampled_at_rate_0(self) -> None:
        """Sample rate 0.0 always returns False."""
        assert sv._should_sample("any-correlation-id", 0.0) is False

    def test_deterministic_for_same_correlation_id(self) -> None:
        """Same correlation_id always produces the same sampling decision."""
        corr_id = str(uuid4())
        rate = 0.5
        first = sv._should_sample(corr_id, rate)
        second = sv._should_sample(corr_id, rate)
        assert first is second

    def test_different_correlation_ids_may_differ(self) -> None:
        """Different correlation_ids at 50% rate produce a mix of True/False."""
        rate = 0.5
        results = {sv._should_sample(str(uuid4()), rate) for _ in range(100)}
        # With 100 samples at 50% rate, we expect both True and False to appear
        assert len(results) == 2, (
            "Expected both True and False in 100 samples at 50% rate"
        )

    def test_rate_clamped_above_1(self) -> None:
        """Sample rate > 1.0 is treated as 1.0 (always sample)."""
        assert sv._should_sample("corr-1", 2.0) is True

    def test_rate_clamped_below_0(self) -> None:
        """Sample rate < 0.0 is treated as 0.0 (never sample)."""
        assert sv._should_sample("corr-1", -0.5) is False

    def test_approximate_rate_distribution(self) -> None:
        """At 10% rate, approximately 10% of 1000 unique IDs are sampled."""
        rate = 0.10
        sampled = sum(sv._should_sample(str(uuid4()), rate) for _ in range(1000))
        # Allow generous tolerance: expect 50-150 samples
        assert 50 <= sampled <= 150, f"Expected ~100 samples at 10% rate, got {sampled}"


# ---------------------------------------------------------------------------
# Keyword extraction tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestKeywordExtraction:
    """_extract_keywords filters stop-words and short tokens."""

    def test_extracts_significant_words(self) -> None:
        """Common technical words are returned."""
        kw = sv._extract_keywords("def process_data returns string")
        assert "process_data" in kw
        assert "returns" in kw
        assert "string" in kw

    def test_excludes_stop_words(self) -> None:
        """Stop-words (a, the, and, is) are excluded."""
        kw = sv._extract_keywords("the quick and the slow")
        assert "the" not in kw
        assert "and" not in kw

    def test_excludes_single_char_tokens(self) -> None:
        """Single-character tokens are excluded."""
        kw = sv._extract_keywords("a b c d def")
        assert "a" not in kw
        assert "b" not in kw
        # Multi-char token remains
        assert "def" in kw

    def test_case_insensitive(self) -> None:
        """Extraction is case-insensitive."""
        kw = sv._extract_keywords("Class Function Method")
        assert "class" in kw
        assert "function" in kw
        assert "method" in kw


# ---------------------------------------------------------------------------
# Jaccard similarity tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestJaccardSimilarity:
    """_jaccard_similarity computes correct Jaccard index."""

    def test_identical_sets(self) -> None:
        """Identical sets return 1.0."""
        s = frozenset({"a", "b", "c"})
        assert sv._jaccard_similarity(s, s) == pytest.approx(1.0)

    def test_disjoint_sets(self) -> None:
        """Completely disjoint sets return 0.0."""
        a = frozenset({"x", "y"})
        b = frozenset({"p", "q"})
        assert sv._jaccard_similarity(a, b) == pytest.approx(0.0)

    def test_empty_sets(self) -> None:
        """Both empty sets return 1.0 (vacuously identical)."""
        assert sv._jaccard_similarity(frozenset(), frozenset()) == pytest.approx(1.0)

    def test_partial_overlap(self) -> None:
        """Sets with 2 common out of 4 total → 0.5."""
        a = frozenset({"a", "b"})
        b = frozenset({"a", "c"})
        # intersection=1, union=3 → 1/3
        assert sv._jaccard_similarity(a, b) == pytest.approx(1 / 3)


# ---------------------------------------------------------------------------
# Code block detection tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCodeBlockDetection:
    """_has_code_block detects code fences and 4-space indented code."""

    def test_detects_triple_backtick(self) -> None:
        """Triple backtick fence detected."""
        assert sv._has_code_block("Some text\n```python\ncode\n```") is True

    def test_detects_four_space_def(self) -> None:
        """4-space indented def keyword detected."""
        assert sv._has_code_block("Here:\n    def my_func():\n        pass") is True

    def test_plain_prose_not_detected(self) -> None:
        """Plain prose without code markers → False."""
        assert sv._has_code_block("This is just prose text with no code.") is False

    def test_two_space_indent_not_detected(self) -> None:
        """2-space indent is not 4-space code block."""
        assert sv._has_code_block("  def not_a_block():") is False


# ---------------------------------------------------------------------------
# compare_responses tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCompareResponses:
    """compare_responses correctly evaluates all three metrics."""

    def test_identical_responses_pass_gate(self) -> None:
        """Identical responses: zero divergence, full overlap, same structure."""
        text = (
            "def process_data(items: list) -> str:\n"
            '    """Process items and return result."""\n'
            "    return str(items)\n"
        )
        result = sv.compare_responses(text, text)
        assert result["quality_gate_passed"] is True
        assert result["length_divergence_ratio"] == pytest.approx(0.0)
        assert result["keyword_overlap_score"] == pytest.approx(1.0)
        assert result["structural_match"] is True
        assert result["divergence_reason"] is None

    def test_high_length_divergence_fails_gate(self) -> None:
        """Local response much shorter than shadow → length divergence gate fails."""
        local = "Short response."
        shadow = "x" * 200  # Very long shadow response
        result = sv.compare_responses(local, shadow)
        assert result["quality_gate_passed"] is False
        assert "length_divergence" in (result["divergence_reason"] or "")
        assert result["length_divergence_ratio"] > sv._MAX_LENGTH_DIVERGENCE

    def test_low_keyword_overlap_fails_gate(self) -> None:
        """Completely different content → keyword overlap gate fails."""
        local = "banana mango pineapple tropical fruit salad delicious"
        shadow = "quantum physics neutron proton electron atomic molecular orbital"
        result = sv.compare_responses(local, shadow)
        assert result["quality_gate_passed"] is False
        assert "keyword_overlap" in (result["divergence_reason"] or "")

    def test_structural_mismatch_fails_gate(self) -> None:
        """One response has code block, other is prose → structural gate fails."""
        local = "Here is the documentation for the function."
        shadow = "```python\ndef process(): pass\n```\nDocumentation follows."
        result = sv.compare_responses(local, shadow)
        # Structural mismatch should be detected
        assert result["structural_match"] is False
        # Gate fails when structural match fails (may also fail on other criteria)
        assert result["quality_gate_passed"] is False

    def test_response_lengths_captured(self) -> None:
        """local_response_length and shadow_response_length are populated correctly."""
        local = "abc"
        shadow = "abcde"
        result = sv.compare_responses(local, shadow)
        assert result["local_response_length"] == 3
        assert result["shadow_response_length"] == 5

    def test_multiple_failure_reasons_joined(self) -> None:
        """When multiple gates fail, all reasons appear in divergence_reason."""
        local = "x"  # too short, no content overlap, no code
        shadow = "```python\n" + "import pytest\n" * 30 + "```\n"
        result = sv.compare_responses(local, shadow)
        assert result["quality_gate_passed"] is False
        reason = result["divergence_reason"] or ""
        # At least two failure reasons should be present
        assert reason.count(";") >= 1


# ---------------------------------------------------------------------------
# run_shadow_validation tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRunShadowValidation:
    """run_shadow_validation dispatches a thread when conditions are met."""

    def test_returns_false_when_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Feature flag off → returns False, no thread started."""
        monkeypatch.delenv("ENABLE_SHADOW_VALIDATION", raising=False)
        result = sv.run_shadow_validation(
            prompt="document this",
            local_response="response",
            local_model="qwen",
            session_id="sess-1",
            correlation_id=_FIXED_CORR_ID,
            task_type="document",
            emitted_at=_FIXED_EMITTED_AT,
        )
        assert result is False

    def test_returns_false_when_not_sampled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sample rate 0.0 → never sampled, returns False."""
        monkeypatch.setenv("ENABLE_SHADOW_VALIDATION", "true")
        monkeypatch.setenv("SHADOW_SAMPLE_RATE", "0.0")
        monkeypatch.setenv("SHADOW_CONSECUTIVE_PASSING_DAYS", "0")
        monkeypatch.setenv("SHADOW_EXIT_WINDOW_DAYS", "30")
        result = sv.run_shadow_validation(
            prompt="document this",
            local_response="response",
            local_model="qwen",
            session_id="sess-1",
            correlation_id=_FIXED_CORR_ID,
            task_type="document",
            emitted_at=_FIXED_EMITTED_AT,
        )
        assert result is False

    def test_returns_false_when_api_key_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No SHADOW_CLAUDE_API_KEY → returns False."""
        _enable_shadow(monkeypatch)
        monkeypatch.delenv("SHADOW_CLAUDE_API_KEY", raising=False)
        result = sv.run_shadow_validation(
            prompt="document this",
            local_response="response",
            local_model="qwen",
            session_id="sess-1",
            correlation_id=_FIXED_CORR_ID,
            task_type="document",
            emitted_at=_FIXED_EMITTED_AT,
        )
        assert result is False

    def test_returns_true_when_thread_started(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With all config present, a thread is started and True is returned."""
        _enable_shadow(monkeypatch)
        monkeypatch.setenv("SHADOW_CLAUDE_API_KEY", "test-api-key")
        monkeypatch.setenv("SHADOW_MODEL", "claude-test-model")

        started_threads: list[Any] = []

        def _mock_start(self: Any) -> None:  # type: ignore[no-untyped-def]
            started_threads.append(self)
            # Do not actually start; capture the thread object

        with patch("threading.Thread.start", _mock_start):
            result = sv.run_shadow_validation(
                prompt="document this function",
                local_response="def fn(): pass",
                local_model="qwen-14b",
                session_id="sess-1",
                correlation_id=_FIXED_CORR_ID,
                task_type="document",
                emitted_at=_FIXED_EMITTED_AT,
            )

        assert result is True
        assert len(started_threads) == 1
        assert "shadow-validation" in started_threads[0].name

    def test_never_raises_on_unexpected_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """run_shadow_validation never raises even when threading.Thread raises."""
        _enable_shadow(monkeypatch)
        monkeypatch.setenv("SHADOW_CLAUDE_API_KEY", "test-api-key")

        with patch("threading.Thread", side_effect=RuntimeError("boom")):
            # Must not raise
            result = sv.run_shadow_validation(
                prompt="document this",
                local_response="response",
                local_model="qwen",
                session_id="sess-1",
                correlation_id=_FIXED_CORR_ID,
                task_type="document",
                emitted_at=_FIXED_EMITTED_AT,
            )
        # Returns False (thread start failed) without raising
        assert result is False

    def test_raises_when_emitted_at_is_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Passing emitted_at=None raises ValueError (no silent datetime.now fallback)."""
        monkeypatch.delenv("ENABLE_SHADOW_VALIDATION", raising=False)
        with pytest.raises(ValueError, match="emitted_at must be provided explicitly"):
            sv.run_shadow_validation(
                prompt="document this",
                local_response="response",
                local_model="qwen",
                session_id="sess-1",
                correlation_id=_FIXED_CORR_ID,
                task_type="document",
                emitted_at=None,  # type: ignore[arg-type]
            )


# ---------------------------------------------------------------------------
# Schema tests (ModelDelegationShadowComparisonPayload)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestShadowComparisonSchema:
    """ModelDelegationShadowComparisonPayload field constraints."""

    def _valid_kwargs(self) -> dict[str, Any]:
        """Return minimal valid kwargs for the schema."""
        return {
            "session_id": "abc12345-1234-5678-abcd-1234567890ab",
            "correlation_id": uuid4(),
            "emitted_at": _FIXED_EMITTED_AT,
            "task_type": "document",
            "local_model": "qwen-14b",
            "shadow_model": "claude-sonnet-4-6",
            "local_response_length": 450,
            "shadow_response_length": 520,
            "length_divergence_ratio": 0.135,
            "keyword_overlap_score": 0.82,
            "structural_match": True,
            "quality_gate_passed": True,
            "divergence_reason": None,
            "shadow_latency_ms": 1240,
            "sample_rate": 0.07,
            "consecutive_passing_days": 12,
            "exit_threshold": 0.95,
            "exit_window_days": 30,
            "auto_disable_triggered": False,
        }

    def test_valid_construction(self) -> None:
        """Valid kwargs produce a well-formed frozen payload."""
        from omniclaude.hooks.schemas import ModelDelegationShadowComparisonPayload

        kwargs = self._valid_kwargs()
        payload = ModelDelegationShadowComparisonPayload(**kwargs)
        assert payload.task_type == "document"
        assert payload.keyword_overlap_score == pytest.approx(0.82)
        assert payload.quality_gate_passed is True
        assert payload.auto_disable_triggered is False

    def test_frozen_model_raises_on_mutation(self) -> None:
        """Frozen model rejects attribute assignment."""
        from omniclaude.hooks.schemas import ModelDelegationShadowComparisonPayload

        payload = ModelDelegationShadowComparisonPayload(**self._valid_kwargs())
        with pytest.raises((TypeError, ValidationError)):
            payload.task_type = "test"  # type: ignore[misc]

    def test_sample_rate_max_length_1(self) -> None:
        """sample_rate > 1.0 raises ValidationError."""
        from omniclaude.hooks.schemas import ModelDelegationShadowComparisonPayload

        kwargs = self._valid_kwargs()
        kwargs["sample_rate"] = 1.5
        with pytest.raises(ValidationError):
            ModelDelegationShadowComparisonPayload(**kwargs)

    def test_sample_rate_min_0(self) -> None:
        """sample_rate < 0.0 raises ValidationError."""
        from omniclaude.hooks.schemas import ModelDelegationShadowComparisonPayload

        kwargs = self._valid_kwargs()
        kwargs["sample_rate"] = -0.1
        with pytest.raises(ValidationError):
            ModelDelegationShadowComparisonPayload(**kwargs)

    def test_divergence_reason_max_length(self) -> None:
        """divergence_reason longer than 500 chars raises ValidationError."""
        from omniclaude.hooks.schemas import ModelDelegationShadowComparisonPayload

        kwargs = self._valid_kwargs()
        kwargs["quality_gate_passed"] = False
        kwargs["divergence_reason"] = "x" * 501
        with pytest.raises(ValidationError):
            ModelDelegationShadowComparisonPayload(**kwargs)

    def test_session_id_min_length(self) -> None:
        """Empty session_id raises ValidationError."""
        from omniclaude.hooks.schemas import ModelDelegationShadowComparisonPayload

        kwargs = self._valid_kwargs()
        kwargs["session_id"] = ""
        with pytest.raises(ValidationError):
            ModelDelegationShadowComparisonPayload(**kwargs)

    def test_keyword_overlap_bounded(self) -> None:
        """keyword_overlap_score must be between 0.0 and 1.0."""
        from omniclaude.hooks.schemas import ModelDelegationShadowComparisonPayload

        kwargs = self._valid_kwargs()
        kwargs["keyword_overlap_score"] = 1.1
        with pytest.raises(ValidationError):
            ModelDelegationShadowComparisonPayload(**kwargs)

    def test_length_divergence_non_negative(self) -> None:
        """length_divergence_ratio must be >= 0."""
        from omniclaude.hooks.schemas import ModelDelegationShadowComparisonPayload

        kwargs = self._valid_kwargs()
        kwargs["length_divergence_ratio"] = -0.1
        with pytest.raises(ValidationError):
            ModelDelegationShadowComparisonPayload(**kwargs)

    def test_auto_disable_triggered_when_window_met(self) -> None:
        """auto_disable_triggered=True is accepted for window-met scenario."""
        from omniclaude.hooks.schemas import ModelDelegationShadowComparisonPayload

        kwargs = self._valid_kwargs()
        kwargs["consecutive_passing_days"] = 30
        kwargs["exit_window_days"] = 30
        kwargs["auto_disable_triggered"] = True
        payload = ModelDelegationShadowComparisonPayload(**kwargs)
        assert payload.auto_disable_triggered is True

    def test_topic_name_registered(self) -> None:
        """TopicBase.DELEGATION_SHADOW_COMPARISON has the expected wire name."""
        from omniclaude.hooks.topics import TopicBase

        assert (
            TopicBase.DELEGATION_SHADOW_COMPARISON
            == "onex.evt.omniclaude.delegation-shadow-comparison.v1"
        )


# ---------------------------------------------------------------------------
# Integration: delegation_orchestrator calls shadow validation on success
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDelegationOrchestratorIntegration:
    """delegation_orchestrator.orchestrate_delegation calls shadow validation after success."""

    def _make_score(
        self,
        delegatable: bool = True,
        confidence: float = 0.95,
        estimated_savings_usd: float = 0.01,
        reasons: list[str] | None = None,
    ) -> Any:
        score = MagicMock()
        score.delegatable = delegatable
        score.confidence = confidence
        score.estimated_savings_usd = estimated_savings_usd
        score.reasons = reasons or ["intent 'document' is in allow-list"]
        return score

    def _make_context(self, intent_value: str = "document") -> Any:
        ctx = MagicMock()
        intent = MagicMock()
        intent.value = intent_value
        ctx.primary_intent = intent
        return ctx

    def test_shadow_validation_called_on_successful_delegation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When delegation succeeds, shadow validation is invoked."""
        import delegation_orchestrator as do

        score = self._make_score()
        ctx = self._make_context("document")
        classifier_mock = MagicMock()
        classifier_mock.is_delegatable.return_value = score
        classifier_mock.classify.return_value = ctx

        shadow_calls: list[dict[str, Any]] = []

        def _fake_shadow(**kwargs: Any) -> bool:
            shadow_calls.append(kwargs)
            return True

        monkeypatch.setenv("ENABLE_LOCAL_INFERENCE_PIPELINE", "true")
        monkeypatch.setenv("ENABLE_LOCAL_DELEGATION", "true")

        with (
            patch(
                "delegation_orchestrator.TaskClassifier", return_value=classifier_mock
            ),
            patch("delegation_orchestrator._cached_classifier", None),
            patch(
                "delegation_orchestrator._select_handler_endpoint",
                return_value=(
                    "http://localhost:8000",
                    "test-model",
                    "You are a doc expert.",
                    "doc_gen",
                ),
            ),
            patch(
                "delegation_orchestrator._call_llm_with_system_prompt",
                return_value=(
                    '"""Process function.\n\nArgs:\n    x: input.\n\nReturns:\n    result."""\n'
                    + "x" * 80,  # Ensure min length
                    "test-model",
                ),
            ),
            patch("delegation_orchestrator._emit_compliance_advisory"),
            patch("delegation_orchestrator._emit_delegation_event"),
            patch("delegation_orchestrator._run_shadow_validation", _fake_shadow),
        ):
            result = do.orchestrate_delegation(
                prompt="document this function",
                session_id="sess-1",
                correlation_id=str(uuid4()),
                emitted_at=_FIXED_EMITTED_AT,
            )

        assert result["delegated"] is True
        assert len(shadow_calls) == 1
        shadow_kwargs = shadow_calls[0]
        assert shadow_kwargs["task_type"] == "document"
        assert "prompt" in shadow_kwargs
        assert "local_response" in shadow_kwargs

    def test_shadow_validation_not_called_when_delegation_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Shadow validation is NOT called when delegation fails (e.g., feature disabled)."""
        import delegation_orchestrator as do

        shadow_calls: list[dict[str, Any]] = []

        def _fake_shadow(**kwargs: Any) -> bool:
            shadow_calls.append(kwargs)
            return True

        monkeypatch.delenv("ENABLE_LOCAL_INFERENCE_PIPELINE", raising=False)
        monkeypatch.delenv("ENABLE_LOCAL_DELEGATION", raising=False)

        with patch("delegation_orchestrator._run_shadow_validation", _fake_shadow):
            result = do.orchestrate_delegation(
                prompt="document this function",
                session_id="sess-1",
                correlation_id=str(uuid4()),
                emitted_at=_FIXED_EMITTED_AT,
            )

        assert result["delegated"] is False
        assert len(shadow_calls) == 0

    def test_shadow_validation_error_does_not_fail_delegation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If shadow validation raises, delegation result is still returned."""
        import delegation_orchestrator as do

        score = self._make_score()
        ctx = self._make_context("document")
        classifier_mock = MagicMock()
        classifier_mock.is_delegatable.return_value = score
        classifier_mock.classify.return_value = ctx

        def _raising_shadow(**kwargs: Any) -> bool:
            raise RuntimeError("shadow exploded")

        monkeypatch.setenv("ENABLE_LOCAL_INFERENCE_PIPELINE", "true")
        monkeypatch.setenv("ENABLE_LOCAL_DELEGATION", "true")

        with (
            patch(
                "delegation_orchestrator.TaskClassifier", return_value=classifier_mock
            ),
            patch("delegation_orchestrator._cached_classifier", None),
            patch(
                "delegation_orchestrator._select_handler_endpoint",
                return_value=(
                    "http://localhost:8000",
                    "test-model",
                    "You are a doc expert.",
                    "doc_gen",
                ),
            ),
            patch(
                "delegation_orchestrator._call_llm_with_system_prompt",
                return_value=(
                    '"""Good doc.\n\nArgs:\n    x: input.\n\nReturns:\n    result."""\n'
                    + "y" * 80,
                    "test-model",
                ),
            ),
            patch("delegation_orchestrator._emit_compliance_advisory"),
            patch("delegation_orchestrator._emit_delegation_event"),
            patch("delegation_orchestrator._run_shadow_validation", _raising_shadow),
        ):
            result = do.orchestrate_delegation(
                prompt="document this function",
                session_id="sess-1",
                correlation_id=str(uuid4()),
                emitted_at=_FIXED_EMITTED_AT,
            )

        # Delegation succeeds despite shadow error
        assert result["delegated"] is True

    def test_shadow_validation_skipped_when_module_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When _run_shadow_validation is None (import failed), delegation still works."""
        import delegation_orchestrator as do

        score = self._make_score()
        ctx = self._make_context("test")
        classifier_mock = MagicMock()
        classifier_mock.is_delegatable.return_value = score
        classifier_mock.classify.return_value = ctx

        monkeypatch.setenv("ENABLE_LOCAL_INFERENCE_PIPELINE", "true")
        monkeypatch.setenv("ENABLE_LOCAL_DELEGATION", "true")

        with (
            patch(
                "delegation_orchestrator.TaskClassifier", return_value=classifier_mock
            ),
            patch("delegation_orchestrator._cached_classifier", None),
            patch(
                "delegation_orchestrator._select_handler_endpoint",
                return_value=(
                    "http://localhost:8000",
                    "test-model",
                    "You are a test expert.",
                    "test_boilerplate",
                ),
            ),
            patch(
                "delegation_orchestrator._call_llm_with_system_prompt",
                return_value=(
                    "def test_foo():\n    assert True\n\n@pytest.mark.unit\n"
                    + "a" * 80,
                    "test-model",
                ),
            ),
            patch("delegation_orchestrator._emit_compliance_advisory"),
            patch("delegation_orchestrator._emit_delegation_event"),
            # Simulate failed import: _run_shadow_validation = None
            patch("delegation_orchestrator._run_shadow_validation", None),
        ):
            result = do.orchestrate_delegation(
                prompt="generate tests for my_module",
                session_id="sess-1",
                correlation_id=str(uuid4()),
                emitted_at=_FIXED_EMITTED_AT,
            )

        # Delegation still succeeds
        assert result["delegated"] is True
