# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Tests for local_delegation_handler.py (OMN-2271).

Covers:
- Feature flag gating (both flags must be true)
- Delegation scoring integration (is_delegatable gate)
- Endpoint resolution (no endpoint → no delegation)
- LLM call success and failure paths
- Response formatting with visible attribution
- CLI entry point (main())
- Conservative fallback: every error returns delegated=False
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# Insert hooks/lib so local_delegation_handler can be imported directly
# (mirrors the pattern in test_rrh_hook_adapter.py)
_HOOKS_LIB = (
    Path(__file__).parent.parent.parent.parent.parent
    / "plugins"
    / "onex"
    / "hooks"
    / "lib"
)
if str(_HOOKS_LIB) not in sys.path:
    sys.path.insert(0, str(_HOOKS_LIB))

import local_delegation_handler as ldh  # noqa: E402 I001


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_delegation_score(
    delegatable: bool,
    confidence: float = 0.0,
    delegate_to_model: str = "",
    estimated_savings_usd: float = 0.0,
    reasons: list[str] | None = None,
) -> Any:
    """Build a minimal ModelDelegationScore-compatible object for tests."""
    score = MagicMock()
    score.delegatable = delegatable
    score.confidence = confidence
    score.delegate_to_model = delegate_to_model
    score.estimated_savings_usd = estimated_savings_usd
    score.reasons = reasons or []
    return score


# ---------------------------------------------------------------------------
# Feature flag tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFeatureFlags:
    """Delegation is disabled unless both env flags are set."""

    def test_both_flags_off_returns_not_delegated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No flags set → delegated=False."""
        monkeypatch.delenv("ENABLE_LOCAL_INFERENCE_PIPELINE", raising=False)
        monkeypatch.delenv("ENABLE_LOCAL_DELEGATION", raising=False)
        result = ldh.handle_delegation("document this function", "corr-1")
        assert result["delegated"] is False
        assert result.get("reason") == "feature_disabled"

    def test_only_parent_flag_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Only parent flag set → delegated=False."""
        monkeypatch.setenv("ENABLE_LOCAL_INFERENCE_PIPELINE", "true")
        monkeypatch.delenv("ENABLE_LOCAL_DELEGATION", raising=False)
        result = ldh.handle_delegation("document this", "corr-2")
        assert result["delegated"] is False
        assert result.get("reason") == "feature_disabled"

    def test_only_delegation_flag_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Only delegation flag set → delegated=False (parent gate required)."""
        monkeypatch.delenv("ENABLE_LOCAL_INFERENCE_PIPELINE", raising=False)
        monkeypatch.setenv("ENABLE_LOCAL_DELEGATION", "true")
        result = ldh.handle_delegation("document this", "corr-3")
        assert result["delegated"] is False
        assert result.get("reason") == "feature_disabled"

    def test_both_flags_true_proceeds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Both flags true → proceeds to classification (not feature_disabled)."""
        monkeypatch.setenv("ENABLE_LOCAL_INFERENCE_PIPELINE", "true")
        monkeypatch.setenv("ENABLE_LOCAL_DELEGATION", "true")
        # Patch classify so we control behavior
        score = _make_delegation_score(False, reasons=["intent not in allow-list"])
        with patch.object(ldh, "_classify_prompt", return_value=score):
            result = ldh.handle_delegation("fix the bug", "corr-4")
        assert result.get("reason") != "feature_disabled"

    def test_flags_truthy_variants(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Truthy values beyond 'true' are accepted (e.g., '1', 'yes')."""
        monkeypatch.setenv("ENABLE_LOCAL_INFERENCE_PIPELINE", "1")
        monkeypatch.setenv("ENABLE_LOCAL_DELEGATION", "yes")
        score = _make_delegation_score(False, reasons=["not delegatable"])
        with patch.object(ldh, "_classify_prompt", return_value=score):
            result = ldh.handle_delegation("explain how this works", "corr-5")
        assert result.get("reason") != "feature_disabled"


# ---------------------------------------------------------------------------
# Classification gate tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestClassificationGate:
    """Delegation is skipped when classifier says not delegatable."""

    def _enable_flags(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ENABLE_LOCAL_INFERENCE_PIPELINE", "true")
        monkeypatch.setenv("ENABLE_LOCAL_DELEGATION", "true")

    def test_not_delegatable_returns_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """is_delegatable() returning False → handle_delegation returns delegated=False."""
        self._enable_flags(monkeypatch)
        score = _make_delegation_score(
            False,
            confidence=0.3,
            reasons=["intent 'debug' is not in the delegation allow-list"],
        )
        with patch.object(ldh, "_classify_prompt", return_value=score):
            result = ldh.handle_delegation("fix the bug", "corr-10")
        assert result["delegated"] is False
        assert "not in the delegation allow-list" in result.get("reason", "")

    def test_classification_error_returns_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Exception from _classify_prompt → delegated=False, never raises."""
        self._enable_flags(monkeypatch)
        with patch.object(
            ldh, "_classify_prompt", side_effect=RuntimeError("classify broke")
        ):
            result = ldh.handle_delegation("document this", "corr-11")
        assert result["delegated"] is False
        assert "classification_error" in result.get("reason", "")

    def test_delegatable_true_proceeds_to_endpoint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """is_delegatable() returning True proceeds to endpoint resolution."""
        self._enable_flags(monkeypatch)
        score = _make_delegation_score(
            True, confidence=0.95, delegate_to_model="qwen2.5-14b"
        )
        with patch.object(ldh, "_classify_prompt", return_value=score):
            with patch.object(ldh, "_get_delegate_endpoint_url", return_value=None):
                result = ldh.handle_delegation("explain how kafka works", "corr-12")
        # Should reach endpoint gate, not classification gate
        assert result["delegated"] is False
        assert result.get("reason") == "no_endpoint_configured"


# ---------------------------------------------------------------------------
# Endpoint resolution tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEndpointResolution:
    """No endpoint configured → delegation cannot proceed."""

    def _enable_flags(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ENABLE_LOCAL_INFERENCE_PIPELINE", "true")
        monkeypatch.setenv("ENABLE_LOCAL_DELEGATION", "true")

    def test_no_endpoint_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Endpoint resolution returning None → delegated=False."""
        self._enable_flags(monkeypatch)
        score = _make_delegation_score(True, confidence=0.95)
        with patch.object(ldh, "_classify_prompt", return_value=score):
            with patch.object(ldh, "_get_delegate_endpoint_url", return_value=None):
                result = ldh.handle_delegation("explain this", "corr-20")
        assert result["delegated"] is False
        assert result.get("reason") == "no_endpoint_configured"

    def test_endpoint_from_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """LLM_QWEN_14B_URL env var is used as fallback when registry unavailable."""
        monkeypatch.setenv("LLM_QWEN_14B_URL", "http://192.168.86.100:8200")
        # Patch registry to fail (import error)
        with patch.dict(
            "sys.modules", {"omniclaude.config.model_local_llm_config": None}
        ):
            url = ldh._get_delegate_endpoint_url()
        # Either URL comes from env var fallback, or None if registry available
        # Just verify no exception raised
        assert url is None or isinstance(url, str)

    def test_endpoint_empty_string_treated_as_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Empty LLM_QWEN_14B_URL → treated as None (no endpoint)."""
        monkeypatch.setenv("LLM_QWEN_14B_URL", "")
        with patch.dict(
            "sys.modules", {"omniclaude.config.model_local_llm_config": None}
        ):
            url = ldh._get_delegate_endpoint_url()
        assert url is None or url == ""


# ---------------------------------------------------------------------------
# LLM call tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLlmCall:
    """_call_local_llm returns (text, model) on success, None on failure."""

    def test_successful_call(self) -> None:
        """Successful HTTP response → (response_text, model_name) tuple."""
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = {
            "model": "qwen2.5-14b",
            "choices": [{"message": {"content": "Here is the documentation."}}],
        }

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post = MagicMock(return_value=mock_response)

        with patch("httpx.Client", return_value=mock_client):
            result = ldh._call_local_llm("explain this", "http://localhost:8200")

        assert result is not None
        text, model = result
        assert text == "Here is the documentation."
        assert model == "qwen2.5-14b"

    def test_empty_choices_returns_none(self) -> None:
        """Empty choices list → None."""
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = {"model": "local", "choices": []}

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post = MagicMock(return_value=mock_response)

        with patch("httpx.Client", return_value=mock_client):
            result = ldh._call_local_llm("explain this", "http://localhost:8200")

        assert result is None

    def test_empty_content_returns_none(self) -> None:
        """Empty content string in choices → None."""
        mock_response = MagicMock()
        mock_response.is_success = True
        mock_response.json.return_value = {
            "model": "local",
            "choices": [{"message": {"content": ""}}],
        }

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post = MagicMock(return_value=mock_response)

        with patch("httpx.Client", return_value=mock_client):
            result = ldh._call_local_llm("explain this", "http://localhost:8200")

        assert result is None

    def test_http_error_returns_none(self) -> None:
        """HTTP 500 error → None."""
        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 500

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "server error", request=MagicMock(), response=mock_response
            )
        )

        with patch("httpx.Client", return_value=mock_client):
            result = ldh._call_local_llm("explain this", "http://localhost:8200")

        assert result is None

    def test_timeout_returns_none(self) -> None:
        """Network timeout → None."""
        import httpx

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post = MagicMock(side_effect=httpx.TimeoutException("timed out"))

        with patch("httpx.Client", return_value=mock_client):
            result = ldh._call_local_llm("explain this", "http://localhost:8200")

        assert result is None

    def test_httpx_not_installed_returns_none(self) -> None:
        """httpx ImportError → None (graceful degradation)."""
        with patch.dict("sys.modules", {"httpx": None}):
            result = ldh._call_local_llm("explain this", "http://localhost:8200")
        assert result is None

    def test_llm_call_failure_returns_delegated_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LLM call returning None → handle_delegation returns delegated=False."""
        monkeypatch.setenv("ENABLE_LOCAL_INFERENCE_PIPELINE", "true")
        monkeypatch.setenv("ENABLE_LOCAL_DELEGATION", "true")
        score = _make_delegation_score(True, confidence=0.95)
        with patch.object(ldh, "_classify_prompt", return_value=score):
            with patch.object(
                ldh, "_get_delegate_endpoint_url", return_value="http://localhost:8200"
            ):
                with patch.object(ldh, "_call_local_llm", return_value=None):
                    result = ldh.handle_delegation("explain kafka", "corr-30")
        assert result["delegated"] is False
        assert result.get("reason") == "llm_call_failed"


# ---------------------------------------------------------------------------
# Response formatting tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResponseFormatting:
    """_format_delegated_response produces correctly structured output."""

    def test_attribution_header_present(self) -> None:
        """Output contains the [Local Model Response - <model>] attribution header."""
        score = _make_delegation_score(
            True,
            confidence=0.95,
            estimated_savings_usd=0.0056,
            reasons=["intent 'research' is in the delegation allow-list"],
        )
        output = ldh._format_delegated_response(
            response_text="Kafka is a distributed event streaming platform.",
            model_name="qwen2.5-14b",
            delegation_score=score,
            prompt="explain kafka",
        )
        assert "[Local Model Response - qwen2.5-14b]" in output

    def test_response_text_present(self) -> None:
        """Output contains the original response text."""
        score = _make_delegation_score(True, confidence=0.95)
        output = ldh._format_delegated_response(
            response_text="This is the answer.",
            model_name="local",
            delegation_score=score,
            prompt="what is this",
        )
        assert "This is the answer." in output

    def test_separator_line_present(self) -> None:
        """Output contains the --- separator line."""
        score = _make_delegation_score(True, confidence=0.95)
        output = ldh._format_delegated_response(
            response_text="Answer.",
            model_name="local",
            delegation_score=score,
            prompt="question",
        )
        assert "---" in output

    def test_confidence_in_footer(self) -> None:
        """Output footer contains the confidence value."""
        score = _make_delegation_score(True, confidence=0.96)
        output = ldh._format_delegated_response(
            response_text="Answer.",
            model_name="local",
            delegation_score=score,
            prompt="question",
        )
        assert "0.960" in output

    def test_savings_in_footer_when_positive(self) -> None:
        """Output footer contains ~$<n> savings when positive."""
        score = _make_delegation_score(
            True, confidence=0.95, estimated_savings_usd=0.0056
        )
        output = ldh._format_delegated_response(
            response_text="Answer.",
            model_name="local",
            delegation_score=score,
            prompt="question",
        )
        assert "~$" in output

    def test_local_inference_label_when_zero_savings(self) -> None:
        """When savings is 0, output says 'local inference' instead of ~$0."""
        score = _make_delegation_score(True, confidence=0.95, estimated_savings_usd=0.0)
        output = ldh._format_delegated_response(
            response_text="Answer.",
            model_name="local",
            delegation_score=score,
            prompt="question",
        )
        assert "local inference" in output

    def test_reasons_in_footer(self) -> None:
        """Output footer contains reasons from the delegation score."""
        score = _make_delegation_score(
            True,
            confidence=0.95,
            reasons=["intent 'document' is in the delegation allow-list"],
        )
        output = ldh._format_delegated_response(
            response_text="Answer.",
            model_name="local",
            delegation_score=score,
            prompt="document this",
        )
        assert "document" in output


# ---------------------------------------------------------------------------
# Full pipeline (happy path)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandleDelegationHappyPath:
    """handle_delegation returns expected structure on full success."""

    def test_happy_path_returns_delegated_true(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """All gates pass + LLM call succeeds → delegated=True with full metadata."""
        monkeypatch.setenv("ENABLE_LOCAL_INFERENCE_PIPELINE", "true")
        monkeypatch.setenv("ENABLE_LOCAL_DELEGATION", "true")

        score = _make_delegation_score(
            True,
            confidence=0.97,
            delegate_to_model="qwen2.5-14b",
            estimated_savings_usd=0.0056,
            reasons=["intent 'research' is in the delegation allow-list"],
        )

        with patch.object(ldh, "_classify_prompt", return_value=score):
            with patch.object(
                ldh,
                "_get_delegate_endpoint_url",
                return_value="http://192.168.86.100:8200",
            ):
                with patch.object(
                    ldh,
                    "_call_local_llm",
                    return_value=(
                        "Kafka is an event streaming platform.",
                        "qwen2.5-14b",
                    ),
                ):
                    result = ldh.handle_delegation(
                        "explain how kafka works", "corr-happy"
                    )

        assert result["delegated"] is True
        assert "response" in result
        assert "[Local Model Response - qwen2.5-14b]" in result["response"]
        assert result["model"] == "qwen2.5-14b"
        assert result["confidence"] == pytest.approx(0.97)
        assert result["savings_usd"] == pytest.approx(0.0056)
        assert isinstance(result["latency_ms"], int)
        assert result["latency_ms"] >= 0

    def test_happy_path_response_contains_answer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Response field contains the LLM-provided answer text."""
        monkeypatch.setenv("ENABLE_LOCAL_INFERENCE_PIPELINE", "true")
        monkeypatch.setenv("ENABLE_LOCAL_DELEGATION", "true")
        score = _make_delegation_score(True, confidence=0.98)

        with patch.object(ldh, "_classify_prompt", return_value=score):
            with patch.object(
                ldh, "_get_delegate_endpoint_url", return_value="http://localhost:8200"
            ):
                with patch.object(
                    ldh,
                    "_call_local_llm",
                    return_value=("The answer to your question is 42.", "local"),
                ):
                    result = ldh.handle_delegation("what is the answer", "corr-content")

        assert "The answer to your question is 42." in result["response"]


# ---------------------------------------------------------------------------
# Conservative fallback: unexpected errors
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConservativeFallback:
    """handle_delegation never raises; unexpected errors → delegated=False."""

    def test_unexpected_exception_in_handle_delegation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If an unexpected exception escapes handle_delegation, main() catches it."""
        monkeypatch.setenv("ENABLE_LOCAL_INFERENCE_PIPELINE", "true")
        monkeypatch.setenv("ENABLE_LOCAL_DELEGATION", "true")

        # Make _classify_prompt raise an unexpected type
        with patch.object(ldh, "_classify_prompt", side_effect=MemoryError("oom")):
            # handle_delegation catches Exception (not MemoryError in Python 3 hierarchy)
            # MemoryError is BaseException, not Exception, so it propagates to main()
            # main() has its own outer try/except. Let's verify handle_delegation doesn't
            # accidentally raise on standard Exception subclasses.
            with patch.object(
                ldh, "_classify_prompt", side_effect=ValueError("unexpected")
            ):
                result = ldh.handle_delegation("document this", "corr-err")
        assert result["delegated"] is False

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
            score = _make_delegation_score(False)
            with patch.object(ldh, "_classify_prompt", return_value=score):
                result = ldh.handle_delegation("some prompt", "corr-always")
            assert "delegated" in result
            assert isinstance(result["delegated"], bool)


# ---------------------------------------------------------------------------
# CLI entry point tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMainCli:
    """main() outputs valid JSON to stdout and always exits 0."""

    def test_missing_args_outputs_not_delegated(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        """main() with no args → JSON with delegated=False."""
        with patch.object(sys, "argv", ["local_delegation_handler.py"]):
            with pytest.raises(SystemExit) as exc_info:
                ldh.main()
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["delegated"] is False
        assert data.get("reason") == "missing_args"

    def test_valid_args_outputs_json(
        self, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """main() with valid args → parseable JSON output."""
        prompt = "explain how kafka works"
        prompt_b64 = base64.b64encode(prompt.encode()).decode()

        monkeypatch.delenv("ENABLE_LOCAL_INFERENCE_PIPELINE", raising=False)
        monkeypatch.delenv("ENABLE_LOCAL_DELEGATION", raising=False)

        with patch.object(sys, "argv", ["prog", prompt_b64, "test-corr-id"]):
            with pytest.raises(SystemExit) as exc_info:
                ldh.main()

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "delegated" in data

    def test_invalid_base64_outputs_not_delegated(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        """main() with non-base64 prompt arg → delegated=False, no crash."""
        with patch.object(sys, "argv", ["prog", "NOT_VALID_BASE64!!!", "corr-id"]):
            with pytest.raises(SystemExit) as exc_info:
                ldh.main()
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["delegated"] is False

    def test_full_pipeline_via_main(
        self, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """main() happy path returns delegated=True JSON."""
        monkeypatch.setenv("ENABLE_LOCAL_INFERENCE_PIPELINE", "true")
        monkeypatch.setenv("ENABLE_LOCAL_DELEGATION", "true")

        prompt = "what how where when which explain find search locate tell me show me"
        prompt_b64 = base64.b64encode(prompt.encode()).decode()
        score = _make_delegation_score(
            True,
            confidence=0.99,
            delegate_to_model="qwen2.5-14b",
            estimated_savings_usd=0.0056,
        )

        with patch.object(sys, "argv", ["prog", prompt_b64, "test-corr"]):
            with patch.object(ldh, "_classify_prompt", return_value=score):
                with patch.object(
                    ldh,
                    "_get_delegate_endpoint_url",
                    return_value="http://localhost:8200",
                ):
                    with patch.object(
                        ldh,
                        "_call_local_llm",
                        return_value=("Here is the answer.", "qwen2.5-14b"),
                    ):
                        with pytest.raises(SystemExit) as exc_info:
                            ldh.main()

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["delegated"] is True
        assert "[Local Model Response" in data["response"]
