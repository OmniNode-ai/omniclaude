# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Tests for delegation_orchestrator.py (OMN-2281).

Covers:
- Quality gate: pass/fail for each task type
- Handler endpoint selection: routing by intent, fallback when no endpoint
- Feature flag gating
- orchestrate_delegation: full success path, each failure mode
- Event emission: called on success and quality gate failure
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# Insert hooks/lib so delegation_orchestrator can be imported directly.
# Mirrors the pattern used by test_local_delegation_handler.py.
_HOOKS_LIB = (
    Path(__file__).parent.parent.parent.parent.parent
    / "plugins"
    / "onex"
    / "hooks"
    / "lib"
)
if str(_HOOKS_LIB) not in sys.path:
    sys.path.insert(0, str(_HOOKS_LIB))

import delegation_orchestrator as do  # noqa: E402 I001


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_score(
    delegatable: bool,
    confidence: float = 0.95,
    delegate_to_model: str = "qwen2.5-14b",
    estimated_savings_usd: float = 0.0112,
    reasons: list[str] | None = None,
) -> Any:
    """Build a minimal ModelDelegationScore-compatible mock object."""
    score = MagicMock()
    score.delegatable = delegatable
    score.confidence = confidence
    score.delegate_to_model = delegate_to_model
    score.estimated_savings_usd = estimated_savings_usd
    score.reasons = reasons or ["intent 'document' is in the delegation allow-list"]
    return score


def _make_context(primary_intent_value: str) -> Any:
    """Build a minimal TaskContext-compatible mock object."""
    ctx = MagicMock()
    intent = MagicMock()
    intent.value = primary_intent_value
    ctx.primary_intent = intent
    return ctx


def _make_classifier_mock(
    score: Any,
    intent_value: str,
) -> Any:
    """Build a TaskClassifier mock that returns the given score and context."""
    ctx = _make_context(intent_value)
    mock = MagicMock()
    mock.is_delegatable.return_value = score
    mock.classify.return_value = ctx
    return mock


# ---------------------------------------------------------------------------
# Quality gate tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestQualityGate:
    """_run_quality_gate correctly accepts and rejects responses per task type."""

    # --- DOCUMENT ---

    def test_document_passes_with_valid_response(self) -> None:
        """Doc response with docstring markers passes the gate."""
        response = (
            "def process(data: dict) -> str:\n"
            '    """Process the input data.\n\n'
            "    Args:\n"
            "        data: Input dictionary.\n\n"
            "    Returns:\n"
            "        str: Processed result.\n"
            '    """\n'
            "    return str(data)"
        )
        passed, reason = do._run_quality_gate(response, "document")
        assert passed is True
        assert reason == ""

    def test_document_fails_too_short(self) -> None:
        """Doc response shorter than 100 chars fails."""
        passed, reason = do._run_quality_gate("Short.", "document")
        assert passed is False
        assert "too short" in reason

    def test_document_fails_missing_markers(self) -> None:
        """Doc response of adequate length but no docstring markers fails."""
        # 100+ chars but no Args:/Returns:/'""' markers
        response = "x" * 120  # No markers at all
        passed, reason = do._run_quality_gate(response, "document")
        assert passed is False
        assert "missing expected markers" in reason

    def test_document_fails_error_indicator(self) -> None:
        """Doc response starting with refusal phrase fails."""
        response = (
            "I cannot provide documentation for this code as it "
            'contains sensitive information.\n\n"""Args:\n    x: value.\n"""'
        )
        passed, reason = do._run_quality_gate(response, "document")
        assert passed is False
        assert "refusal indicator" in reason

    # --- TEST ---

    def test_test_passes_with_pytest_function(self) -> None:
        """Test response with def test_ and assert passes."""
        response = (
            "import pytest\n\n"
            "def test_process_returns_string():\n"
            "    result = process({'key': 'value'})\n"
            "    assert isinstance(result, str)\n"
        )
        passed, reason = do._run_quality_gate(response, "test")
        assert passed is True
        assert reason == ""

    def test_test_passes_with_class_test(self) -> None:
        """Test response with class Test... structure passes."""
        response = (
            "@pytest.mark.unit\n"
            "class TestMyModule:\n"
            "    def test_something(self):\n"
            "        assert 1 + 1 == 2\n"
        )
        passed, reason = do._run_quality_gate(response, "test")
        assert passed is True
        assert reason == ""

    def test_test_fails_too_short(self) -> None:
        """Test response shorter than 80 chars fails."""
        passed, reason = do._run_quality_gate("def test_foo(): pass", "test")
        assert passed is False
        assert "too short" in reason

    def test_test_fails_no_test_markers(self) -> None:
        """Test response of adequate length but no test markers fails."""
        # 80+ chars, no def test_ / class Test / @pytest / assert
        response = "This is a test plan document that explains how to manually verify the system behavior by inspection.\n"
        passed, reason = do._run_quality_gate(response, "test")
        assert passed is False
        assert "missing expected markers" in reason

    def test_test_fails_error_indicator(self) -> None:
        """Test response with 'As an AI' in first 200 chars fails."""
        response = (
            "As an AI, I can help you write tests.\n"
            "def test_example():\n"
            "    assert True\n"
            "# " + "x" * 80
        )
        passed, reason = do._run_quality_gate(response, "test")
        assert passed is False
        assert "refusal indicator" in reason

    # --- RESEARCH ---

    def test_research_passes_with_adequate_response(self) -> None:
        """Research response >= 60 chars with no error indicators passes."""
        response = (
            "Kafka is a distributed event streaming platform that handles "
            "high-throughput data pipelines. It uses topics, producers, and consumers."
        )
        passed, reason = do._run_quality_gate(response, "research")
        assert passed is True
        assert reason == ""

    def test_research_fails_too_short(self) -> None:
        """Research response shorter than 60 chars fails."""
        passed, reason = do._run_quality_gate("Kafka is a tool.", "research")
        assert passed is False
        assert "too short" in reason

    def test_research_fails_error_indicator(self) -> None:
        """Research response starting with "I'm unable" fails."""
        response = (
            "I'm unable to answer questions about proprietary systems. "
            "Please consult the official documentation for more information."
        )
        passed, reason = do._run_quality_gate(response, "research")
        assert passed is False
        assert "refusal indicator" in reason

    def test_research_no_markers_required(self) -> None:
        """Research task does not require content markers (no entry in _TASK_MARKERS)."""
        # Research is not in _TASK_MARKERS so any 60+ char response without refusal passes
        response = "a" * 70
        passed, reason = do._run_quality_gate(response, "research")
        assert passed is True
        assert reason == ""

    # --- Unknown task type ---

    def test_unknown_task_type_uses_default_min_length(self) -> None:
        """Unknown task type falls back to 60-char minimum."""
        passed, _ = do._run_quality_gate("x" * 65, "unknown_task")
        assert passed is True

        passed, reason = do._run_quality_gate("x" * 50, "unknown_task")
        assert passed is False
        assert "too short" in reason


# ---------------------------------------------------------------------------
# Handler endpoint selection tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSelectHandlerEndpoint:
    """_select_handler_endpoint returns correct metadata or None."""

    def test_document_routes_to_reasoning(self) -> None:
        """'document' intent routes to REASONING endpoint (doc_gen handler)."""
        mock_endpoint = MagicMock()
        mock_endpoint.url = "http://192.168.86.200:8101"
        mock_endpoint.model_name = "Qwen2.5-72B"

        mock_registry_instance = MagicMock()
        mock_registry_instance.get_endpoint.return_value = mock_endpoint

        with patch.object(
            do, "LocalLlmEndpointRegistry", return_value=mock_registry_instance
        ):
            with patch.object(do, "LlmEndpointPurpose") as mock_purpose_cls:
                mock_purpose_cls.return_value = MagicMock()
                result = do._select_handler_endpoint("document")

        assert result is not None
        _url, model_name, system_prompt, handler_name = result
        assert handler_name == "doc_gen"
        assert "documentation" in system_prompt.lower()
        assert model_name == "Qwen2.5-72B"

    def test_test_routes_to_code_analysis(self) -> None:
        """'test' intent routes to CODE_ANALYSIS endpoint (test_boilerplate handler)."""
        mock_endpoint = MagicMock()
        mock_endpoint.url = "http://192.168.86.201:8000"
        mock_endpoint.model_name = "Qwen3-Coder-30B"

        mock_registry_instance = MagicMock()
        mock_registry_instance.get_endpoint.return_value = mock_endpoint

        with patch.object(
            do, "LocalLlmEndpointRegistry", return_value=mock_registry_instance
        ):
            with patch.object(do, "LlmEndpointPurpose") as mock_purpose_cls:
                mock_purpose_cls.return_value = MagicMock()
                result = do._select_handler_endpoint("test")

        assert result is not None
        _, _, system_prompt, handler_name = result
        assert handler_name == "test_boilerplate"
        assert "pytest" in system_prompt.lower()

    def test_research_routes_to_code_analysis(self) -> None:
        """'research' intent routes to CODE_ANALYSIS endpoint (code_review handler)."""
        mock_endpoint = MagicMock()
        mock_endpoint.url = "http://192.168.86.201:8000"
        mock_endpoint.model_name = "Qwen3-Coder-30B"

        mock_registry_instance = MagicMock()
        mock_registry_instance.get_endpoint.return_value = mock_endpoint

        with patch.object(
            do, "LocalLlmEndpointRegistry", return_value=mock_registry_instance
        ):
            with patch.object(do, "LlmEndpointPurpose") as mock_purpose_cls:
                mock_purpose_cls.return_value = MagicMock()
                result = do._select_handler_endpoint("research")

        assert result is not None
        _, _, system_prompt, handler_name = result
        assert handler_name == "code_review"
        assert "review" in system_prompt.lower()

    def test_unknown_intent_returns_none(self) -> None:
        """Intent not in _HANDLER_ROUTING returns None without calling registry."""
        result = do._select_handler_endpoint("debug")
        assert result is None

    def test_no_endpoint_configured_returns_none(self) -> None:
        """Registry returning None endpoint -> _select_handler_endpoint returns None."""
        mock_registry_instance = MagicMock()
        mock_registry_instance.get_endpoint.return_value = None

        with patch.object(
            do, "LocalLlmEndpointRegistry", return_value=mock_registry_instance
        ):
            result = do._select_handler_endpoint("document")

        assert result is None

    def test_registry_exception_returns_none(self) -> None:
        """Exception from registry -> returns None, never raises."""
        with patch.object(
            do,
            "LocalLlmEndpointRegistry",
            side_effect=RuntimeError("registry unavailable"),
        ):
            result = do._select_handler_endpoint("test")

        assert result is None

    def test_unavailable_registry_returns_none(self) -> None:
        """When LocalLlmEndpointRegistry is None (import failed) -> returns None."""
        with patch.object(do, "LocalLlmEndpointRegistry", None):
            result = do._select_handler_endpoint("document")
        assert result is None

    def test_unavailable_purpose_returns_none(self) -> None:
        """When LlmEndpointPurpose is None (import failed) -> returns None."""
        with patch.object(do, "LlmEndpointPurpose", None):
            result = do._select_handler_endpoint("document")
        assert result is None


# ---------------------------------------------------------------------------
# Handler routing table contract test
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_handler_routing_purpose_names_match_enum() -> None:
    """Every purpose string in _HANDLER_ROUTING must match an LlmEndpointPurpose value.

    This acts as a contract check: if LlmEndpointPurpose enum values are
    renamed, the routing table must be updated accordingly.  A mismatch
    silently causes _select_handler_endpoint() to return None at runtime,
    so catching it in a test is essential.
    """
    from omniclaude.config.model_local_llm_config import LlmEndpointPurpose

    valid_purpose_values = {p.value for p in LlmEndpointPurpose}

    for intent_key, routing_tuple in do._HANDLER_ROUTING.items():
        purpose_name = routing_tuple[0]
        assert purpose_name in valid_purpose_values, (
            f"_HANDLER_ROUTING[{intent_key!r}] purpose {purpose_name!r} is not a "
            f"valid LlmEndpointPurpose value. Valid values: {sorted(valid_purpose_values)}"
        )


# ---------------------------------------------------------------------------
# Feature flag tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFeatureFlags:
    """orchestrate_delegation respects ENABLE_LOCAL_INFERENCE_PIPELINE and ENABLE_LOCAL_DELEGATION."""

    def test_both_flags_off_returns_not_delegated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ENABLE_LOCAL_INFERENCE_PIPELINE", raising=False)
        monkeypatch.delenv("ENABLE_LOCAL_DELEGATION", raising=False)
        result = do.orchestrate_delegation("document this function", "corr-1")
        assert result["delegated"] is False
        assert result.get("reason") == "feature_disabled"

    def test_only_parent_flag_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ENABLE_LOCAL_INFERENCE_PIPELINE", "true")
        monkeypatch.delenv("ENABLE_LOCAL_DELEGATION", raising=False)
        result = do.orchestrate_delegation("document this", "corr-2")
        assert result["delegated"] is False
        assert result.get("reason") == "feature_disabled"

    def test_only_delegation_flag_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ENABLE_LOCAL_INFERENCE_PIPELINE", raising=False)
        monkeypatch.setenv("ENABLE_LOCAL_DELEGATION", "true")
        result = do.orchestrate_delegation("document this", "corr-3")
        assert result["delegated"] is False
        assert result.get("reason") == "feature_disabled"

    def test_both_flags_true_proceeds_past_feature_gate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Both flags true -> proceeds to classification (not feature_disabled)."""
        monkeypatch.setenv("ENABLE_LOCAL_INFERENCE_PIPELINE", "true")
        monkeypatch.setenv("ENABLE_LOCAL_DELEGATION", "true")
        score = _make_score(False, reasons=["not delegatable"])
        classifier_mock = _make_classifier_mock(score, "debug")

        with patch.object(do, "TaskClassifier", return_value=classifier_mock):
            result = do.orchestrate_delegation("fix the bug", "corr-4")
        assert result.get("reason") != "feature_disabled"

    def test_unavailable_classifier_returns_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When TaskClassifier is None (import failed) -> classification_error."""
        monkeypatch.setenv("ENABLE_LOCAL_INFERENCE_PIPELINE", "true")
        monkeypatch.setenv("ENABLE_LOCAL_DELEGATION", "true")
        with patch.object(do, "TaskClassifier", None):
            result = do.orchestrate_delegation("document this", "corr-null-cls")
        assert result["delegated"] is False
        assert "classification_error" in result.get("reason", "")


# ---------------------------------------------------------------------------
# Classification gate tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestClassificationGate:
    """orchestrate_delegation skips when classifier says not delegatable."""

    def _enable_flags(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ENABLE_LOCAL_INFERENCE_PIPELINE", "true")
        monkeypatch.setenv("ENABLE_LOCAL_DELEGATION", "true")

    def test_not_delegatable_returns_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._enable_flags(monkeypatch)
        score = _make_score(
            False, confidence=0.3, reasons=["intent 'debug' not in allow-list"]
        )
        classifier_mock = _make_classifier_mock(score, "debug")

        with patch.object(do, "TaskClassifier", return_value=classifier_mock):
            result = do.orchestrate_delegation("fix the bug", "corr-10")
        assert result["delegated"] is False
        assert "not in allow-list" in result.get("reason", "")

    def test_classification_exception_returns_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._enable_flags(monkeypatch)
        with patch.object(
            do, "TaskClassifier", side_effect=RuntimeError("classify broke")
        ):
            result = do.orchestrate_delegation("document this", "corr-11")
        assert result["delegated"] is False
        assert "classification_error" in result.get("reason", "")


# ---------------------------------------------------------------------------
# Endpoint resolution tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEndpointResolution:
    """orchestrate_delegation fails gracefully when no endpoint is configured."""

    def _enable_flags(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ENABLE_LOCAL_INFERENCE_PIPELINE", "true")
        monkeypatch.setenv("ENABLE_LOCAL_DELEGATION", "true")

    def test_no_endpoint_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._enable_flags(monkeypatch)
        score = _make_score(True)
        classifier_mock = _make_classifier_mock(score, "document")

        with patch.object(do, "TaskClassifier", return_value=classifier_mock):
            with patch.object(do, "_select_handler_endpoint", return_value=None):
                result = do.orchestrate_delegation("document this", "corr-20")

        assert result["delegated"] is False
        assert result.get("reason") == "no_endpoint_configured"

    def test_delegation_proceeds_when_endpoint_available(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._enable_flags(monkeypatch)
        score = _make_score(True)
        classifier_mock = _make_classifier_mock(score, "document")

        endpoint_tuple = (
            "http://localhost:8100",
            "Qwen2.5-72B",
            "You are a doc expert.",
            "doc_gen",
        )

        with patch.object(do, "TaskClassifier", return_value=classifier_mock):
            with patch.object(
                do, "_select_handler_endpoint", return_value=endpoint_tuple
            ):
                with patch.object(
                    do, "_call_llm_with_system_prompt", return_value=None
                ):
                    result = do.orchestrate_delegation("document func", "corr-21")

        # Should reach the LLM call gate, not endpoint gate
        assert result.get("reason") == "llm_call_failed"


# ---------------------------------------------------------------------------
# LLM call failure tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLlmCallFailure:
    """orchestrate_delegation handles LLM call failures gracefully."""

    def _setup(
        self, monkeypatch: pytest.MonkeyPatch, intent: str = "document"
    ) -> tuple[Any, Any, tuple[str, str, str, str]]:
        monkeypatch.setenv("ENABLE_LOCAL_INFERENCE_PIPELINE", "true")
        monkeypatch.setenv("ENABLE_LOCAL_DELEGATION", "true")
        score = _make_score(True, confidence=0.95)
        classifier_mock = _make_classifier_mock(score, intent)
        endpoint_tuple: tuple[str, str, str, str] = (
            "http://localhost:8100",
            "Qwen2.5-72B",
            "system prompt",
            "doc_gen",
        )
        return score, classifier_mock, endpoint_tuple

    def test_llm_call_failure_returns_delegated_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _score, classifier_mock, endpoint_tuple = self._setup(monkeypatch)

        with patch.object(do, "TaskClassifier", return_value=classifier_mock):
            with patch.object(
                do, "_select_handler_endpoint", return_value=endpoint_tuple
            ):
                with patch.object(
                    do, "_call_llm_with_system_prompt", return_value=None
                ):
                    result = do.orchestrate_delegation(
                        "document this function", "corr-30"
                    )

        assert result["delegated"] is False
        assert result.get("reason") == "llm_call_failed"

    def test_llm_call_failure_emits_delegation_event(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Delegation event must be emitted even when LLM call fails."""
        _score, classifier_mock, endpoint_tuple = self._setup(monkeypatch)

        with patch.object(do, "TaskClassifier", return_value=classifier_mock):
            with patch.object(
                do, "_select_handler_endpoint", return_value=endpoint_tuple
            ):
                with patch.object(
                    do, "_call_llm_with_system_prompt", return_value=None
                ):
                    with patch.object(do, "_emit_delegation_event") as mock_emit:
                        do.orchestrate_delegation("document this function", "corr-31")

        mock_emit.assert_called_once()
        call_kwargs = mock_emit.call_args.kwargs
        assert call_kwargs.get("delegation_success") is False
        assert call_kwargs.get("quality_gate_passed") is False

    def test_empty_response_returns_delegated_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Empty response string from LLM -> delegated=False."""
        _score, classifier_mock, endpoint_tuple = self._setup(monkeypatch)

        with patch.object(do, "TaskClassifier", return_value=classifier_mock):
            with patch.object(
                do, "_select_handler_endpoint", return_value=endpoint_tuple
            ):
                with patch.object(
                    do,
                    "_call_llm_with_system_prompt",
                    return_value=("   ", "Qwen2.5-72B"),
                ):
                    result = do.orchestrate_delegation(
                        "document this function", "corr-32"
                    )

        assert result["delegated"] is False
        assert result.get("reason") == "empty_response"

    def test_intent_extraction_error_emits_delegation_event(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """classify() raising -> delegated=False with intent_extraction_error and event emitted."""
        from uuid import uuid4

        monkeypatch.setenv("ENABLE_LOCAL_INFERENCE_PIPELINE", "true")
        monkeypatch.setenv("ENABLE_LOCAL_DELEGATION", "true")

        score = _make_score(True, confidence=0.92)
        classifier_instance = MagicMock()
        classifier_instance.is_delegatable.return_value = score
        classifier_instance.classify.side_effect = RuntimeError("classification failed")

        with patch.object(do, "TaskClassifier", return_value=classifier_instance):
            with patch.object(do, "_emit_delegation_event") as mock_emit:
                result = do.orchestrate_delegation(
                    prompt="write tests",
                    session_id="s1",
                    correlation_id=str(uuid4()),
                )

        assert result["delegated"] is False
        assert "intent_extraction_error" in result.get("reason", "")

        mock_emit.assert_called_once()
        call_kwargs = mock_emit.call_args.kwargs
        assert call_kwargs.get("delegation_success") is False


# ---------------------------------------------------------------------------
# Quality gate failure tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestQualityGateFailure:
    """orchestrate_delegation falls back to Claude when quality gate fails."""

    def _setup(
        self, monkeypatch: pytest.MonkeyPatch, intent: str = "document"
    ) -> tuple[Any, Any, tuple[str, str, str, str]]:
        monkeypatch.setenv("ENABLE_LOCAL_INFERENCE_PIPELINE", "true")
        monkeypatch.setenv("ENABLE_LOCAL_DELEGATION", "true")
        score = _make_score(True, confidence=0.95)
        classifier_mock = _make_classifier_mock(score, intent)
        endpoint_tuple: tuple[str, str, str, str] = (
            "http://localhost:8100",
            "Qwen2.5-72B",
            "system prompt",
            "doc_gen",
        )
        return score, classifier_mock, endpoint_tuple

    def test_quality_gate_failure_returns_delegated_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _score, classifier_mock, endpoint_tuple = self._setup(monkeypatch)

        # LLM returns a response that will fail the doc quality gate (no markers)
        bad_response = "x" * 120  # Long enough but no docstring markers

        with patch.object(do, "TaskClassifier", return_value=classifier_mock):
            with patch.object(
                do, "_select_handler_endpoint", return_value=endpoint_tuple
            ):
                with patch.object(
                    do,
                    "_call_llm_with_system_prompt",
                    return_value=(bad_response, "Qwen2.5-72B"),
                ):
                    result = do.orchestrate_delegation(
                        "document this function", "corr-40"
                    )

        assert result["delegated"] is False
        assert result.get("reason") == "quality_gate_failed"
        assert "quality_gate_reason" in result

    def test_quality_gate_failure_emits_delegation_event(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Delegation event must be emitted when quality gate fails."""
        _score, classifier_mock, endpoint_tuple = self._setup(monkeypatch)
        bad_response = "x" * 120  # No docstring markers

        with patch.object(do, "TaskClassifier", return_value=classifier_mock):
            with patch.object(
                do, "_select_handler_endpoint", return_value=endpoint_tuple
            ):
                with patch.object(
                    do,
                    "_call_llm_with_system_prompt",
                    return_value=(bad_response, "Qwen2.5-72B"),
                ):
                    with patch.object(do, "_emit_delegation_event") as mock_emit:
                        do.orchestrate_delegation("document this function", "corr-41")

        mock_emit.assert_called_once()
        call_kwargs = mock_emit.call_args.kwargs
        assert call_kwargs["quality_gate_passed"] is False
        assert call_kwargs["delegation_success"] is False
        assert call_kwargs["task_type"] == "document"


# ---------------------------------------------------------------------------
# Full success path tests
# ---------------------------------------------------------------------------

# A doc LLM response that passes the quality gate
_GOOD_DOC_RESPONSE = (
    "def calculate(x: int) -> int:\n"
    '    """Calculate the result.\n\n'
    "    Args:\n"
    "        x: Input integer.\n\n"
    "    Returns:\n"
    "        int: The result.\n"
    '    """\n'
    "    return x * 2"
)

# A test LLM response that passes the quality gate
_GOOD_TEST_RESPONSE = (
    "@pytest.mark.unit\n"
    "def test_calculate_returns_correct_value():\n"
    "    result = calculate(5)\n"
    "    assert result == 10\n"
)

# A research LLM response that passes the quality gate
_GOOD_RESEARCH_RESPONSE = (
    "Kafka is a distributed event streaming platform designed for high-throughput, "
    "fault-tolerant, and scalable data pipelines. It uses a publish-subscribe model "
    "where producers write to topics and consumers read from them."
)


@pytest.mark.unit
class TestOrchestratedDelegationSuccess:
    """orchestrate_delegation returns correct structure on full success."""

    def _setup_all_gates(
        self,
        monkeypatch: pytest.MonkeyPatch,
        intent: str = "document",
        llm_response: str | None = None,
        handler_name: str = "doc_gen",
        model_name: str = "Qwen2.5-72B",
        endpoint_url: str = "http://192.168.86.200:8100",
    ) -> tuple[Any, Any, tuple[str, str, str, str], str]:
        monkeypatch.setenv("ENABLE_LOCAL_INFERENCE_PIPELINE", "true")
        monkeypatch.setenv("ENABLE_LOCAL_DELEGATION", "true")
        score = _make_score(
            True,
            confidence=0.97,
            estimated_savings_usd=0.0112,
            reasons=["intent 'document' is in the delegation allow-list"],
        )
        classifier_mock = _make_classifier_mock(score, intent)
        endpoint_tuple: tuple[str, str, str, str] = (
            endpoint_url,
            model_name,
            "You are a documentation expert.",
            handler_name,
        )
        if llm_response is None:
            llm_response = _GOOD_DOC_RESPONSE
        return score, classifier_mock, endpoint_tuple, llm_response

    def test_happy_path_returns_delegated_true(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """All gates pass -> delegated=True with full metadata."""
        _score, classifier_mock, endpoint_tuple, llm_response = self._setup_all_gates(
            monkeypatch
        )

        with patch.object(do, "TaskClassifier", return_value=classifier_mock):
            with patch.object(
                do, "_select_handler_endpoint", return_value=endpoint_tuple
            ):
                with patch.object(
                    do,
                    "_call_llm_with_system_prompt",
                    return_value=(llm_response, "Qwen2.5-72B"),
                ):
                    with patch.object(do, "_emit_delegation_event"):
                        with patch.object(do, "_emit_compliance_advisory"):
                            result = do.orchestrate_delegation(
                                "document this function", "corr-50"
                            )

        assert result["delegated"] is True
        assert "response" in result
        assert "[Local Model Response - Qwen2.5-72B]" in result["response"]
        assert result["model"] == "Qwen2.5-72B"
        assert result["confidence"] == pytest.approx(0.97)
        assert result["savings_usd"] == pytest.approx(0.0112)
        assert result["handler"] == "doc_gen"
        assert result["quality_gate_passed"] is True
        assert result["intent"] == "document"
        assert isinstance(result["latency_ms"], int)
        assert result["latency_ms"] >= 0

    def test_happy_path_emits_delegation_event(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Delegation event is emitted with delegation_success=True on success."""
        _score, classifier_mock, endpoint_tuple, llm_response = self._setup_all_gates(
            monkeypatch
        )

        with patch.object(do, "TaskClassifier", return_value=classifier_mock):
            with patch.object(
                do, "_select_handler_endpoint", return_value=endpoint_tuple
            ):
                with patch.object(
                    do,
                    "_call_llm_with_system_prompt",
                    return_value=(llm_response, "Qwen2.5-72B"),
                ):
                    with patch.object(do, "_emit_delegation_event") as mock_emit:
                        with patch.object(do, "_emit_compliance_advisory"):
                            do.orchestrate_delegation("document func", "corr-51")

        mock_emit.assert_called_once()
        call_kwargs = mock_emit.call_args.kwargs
        assert call_kwargs["delegation_success"] is True
        assert call_kwargs["quality_gate_passed"] is True
        assert call_kwargs["task_type"] == "document"
        assert call_kwargs["handler_name"] == "doc_gen"

    def test_happy_path_emits_compliance_advisory(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Compliance advisory is emitted on successful delegation."""
        _score, classifier_mock, endpoint_tuple, llm_response = self._setup_all_gates(
            monkeypatch
        )

        with patch.object(do, "TaskClassifier", return_value=classifier_mock):
            with patch.object(
                do, "_select_handler_endpoint", return_value=endpoint_tuple
            ):
                with patch.object(
                    do,
                    "_call_llm_with_system_prompt",
                    return_value=(llm_response, "Qwen2.5-72B"),
                ):
                    with patch.object(do, "_emit_delegation_event"):
                        with patch.object(
                            do, "_emit_compliance_advisory"
                        ) as mock_advisory:
                            do.orchestrate_delegation("document func", "corr-52")

        mock_advisory.assert_called_once()

    def test_response_contains_attribution_and_reasons(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Formatted response includes attribution header and reasons footer."""
        _score, classifier_mock, endpoint_tuple, llm_response = self._setup_all_gates(
            monkeypatch
        )

        with patch.object(do, "TaskClassifier", return_value=classifier_mock):
            with patch.object(
                do, "_select_handler_endpoint", return_value=endpoint_tuple
            ):
                with patch.object(
                    do,
                    "_call_llm_with_system_prompt",
                    return_value=(llm_response, "Qwen2.5-72B"),
                ):
                    with patch.object(do, "_emit_delegation_event"):
                        with patch.object(do, "_emit_compliance_advisory"):
                            result = do.orchestrate_delegation(
                                "document this function", "corr-53"
                            )

        assert "---" in result["response"]
        assert "delegation allow-list" in result["response"]

    def test_never_raises_on_unexpected_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """orchestrate_delegation never raises; any error -> delegated=False."""
        monkeypatch.setenv("ENABLE_LOCAL_INFERENCE_PIPELINE", "true")
        monkeypatch.setenv("ENABLE_LOCAL_DELEGATION", "true")

        with patch.object(
            do, "TaskClassifier", side_effect=SystemError("unrecoverable")
        ):
            result = do.orchestrate_delegation("document this", "corr-err")

        assert result["delegated"] is False
        assert "classification_error" in result.get("reason", "")

    def test_result_always_has_delegated_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Every code path returns a dict with 'delegated' key."""
        for env_pip, env_del in [
            ("false", "false"),
            ("true", "false"),
            ("false", "true"),
            ("true", "true"),
        ]:
            monkeypatch.setenv("ENABLE_LOCAL_INFERENCE_PIPELINE", env_pip)
            monkeypatch.setenv("ENABLE_LOCAL_DELEGATION", env_del)
            score = _make_score(False)
            classifier_mock = _make_classifier_mock(score, "debug")
            with patch.object(do, "TaskClassifier", return_value=classifier_mock):
                result = do.orchestrate_delegation("some prompt", "corr-always")
            assert "delegated" in result
            assert isinstance(result["delegated"], bool)

    def test_test_intent_routes_to_test_boilerplate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEST intent uses test_boilerplate handler and passes quality gate."""
        _score, classifier_mock, endpoint_tuple, _llm = self._setup_all_gates(
            monkeypatch,
            intent="test",
            llm_response=_GOOD_TEST_RESPONSE,
            handler_name="test_boilerplate",
            model_name="Qwen3-Coder-30B",
            endpoint_url="http://192.168.86.201:8000",
        )
        # Override the reasons to reflect test intent
        classifier_mock.is_delegatable.return_value.reasons = [
            "intent 'test' is in the delegation allow-list"
        ]

        with patch.object(do, "TaskClassifier", return_value=classifier_mock):
            with patch.object(
                do, "_select_handler_endpoint", return_value=endpoint_tuple
            ):
                with patch.object(
                    do,
                    "_call_llm_with_system_prompt",
                    return_value=(_GOOD_TEST_RESPONSE, "Qwen3-Coder-30B"),
                ):
                    with patch.object(do, "_emit_delegation_event"):
                        with patch.object(do, "_emit_compliance_advisory"):
                            result = do.orchestrate_delegation(
                                "write tests for calculate", "corr-test"
                            )

        assert result["delegated"] is True
        assert result["handler"] == "test_boilerplate"
        assert result["intent"] == "test"

    def test_research_intent_routes_to_code_review(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """RESEARCH intent uses code_review handler and passes quality gate."""
        _score, classifier_mock, endpoint_tuple, _llm = self._setup_all_gates(
            monkeypatch,
            intent="research",
            llm_response=_GOOD_RESEARCH_RESPONSE,
            handler_name="code_review",
            model_name="Qwen3-Coder-30B",
            endpoint_url="http://192.168.86.201:8000",
        )
        classifier_mock.is_delegatable.return_value.reasons = [
            "intent 'research' is in the delegation allow-list"
        ]

        with patch.object(do, "TaskClassifier", return_value=classifier_mock):
            with patch.object(
                do, "_select_handler_endpoint", return_value=endpoint_tuple
            ):
                with patch.object(
                    do,
                    "_call_llm_with_system_prompt",
                    return_value=(_GOOD_RESEARCH_RESPONSE, "Qwen3-Coder-30B"),
                ):
                    with patch.object(do, "_emit_delegation_event"):
                        with patch.object(do, "_emit_compliance_advisory"):
                            result = do.orchestrate_delegation(
                                "explain how kafka works", "corr-research"
                            )

        assert result["delegated"] is True
        assert result["handler"] == "code_review"
        assert result["intent"] == "research"


# ---------------------------------------------------------------------------
# orchestrate_delegation alias test
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_orchestrate_delegation_returns_feature_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """orchestrate_delegation returns feature_disabled when both flags are off."""
    monkeypatch.delenv("ENABLE_LOCAL_INFERENCE_PIPELINE", raising=False)
    monkeypatch.delenv("ENABLE_LOCAL_DELEGATION", raising=False)
    result = do.orchestrate_delegation("test prompt", "corr-alias")
    assert result["delegated"] is False
    assert result.get("reason") == "feature_disabled"
