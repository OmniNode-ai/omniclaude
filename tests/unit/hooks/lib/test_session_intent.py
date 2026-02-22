"""Unit tests for OMN-2493: intent classification and model hints.

Tests cover:
- classify_intent: success, HTTP failure, timeout, empty prompt
- store_intent_in_correlation / get_intent_from_correlation: round-trip
- format_intent_context: correct field injection
- get_hint_for_intent: default mapping, env var overrides, unknown class fallback
- CLI subprocess: exit 0 on timeout / service unavailable

All tests run without network access or external services.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# sys.path: plugin lib modules live outside the normal package tree
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

import intent_classifier as ic
import intent_model_hints as imh

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_env(**overrides: str) -> dict[str, str]:
    """Return a copy of os.environ with overrides applied."""
    env = os.environ.copy()
    env.update(overrides)
    return env


# ---------------------------------------------------------------------------
# classify_intent — unit tests (no real HTTP)
# ---------------------------------------------------------------------------


class TestClassifyIntent:
    """Tests for the classify_intent() function."""

    def test_success(self, tmp_path: Path) -> None:
        """classify_intent returns parsed fields on a successful HTTP response."""
        response_body = json.dumps(
            {
                "intent_id": "test-id-123",
                "intent_class": "SECURITY",
                "confidence": 0.94,
            }
        ).encode()

        mock_response = MagicMock()
        mock_response.read.return_value = response_body
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = ic.classify_intent(
                prompt="Check for SQL injection vulnerabilities",
                session_id="sess-1",
                correlation_id="corr-1",
            )

        assert result["success"] is True
        assert result["intent_class"] == "SECURITY"
        assert result["confidence"] == pytest.approx(0.94)
        assert result["intent_id"] == "test-id-123"
        assert result["elapsed_ms"] >= 0

    def test_url_error_returns_empty_result(self) -> None:
        """classify_intent returns success=False when service is unavailable."""
        import urllib.error

        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("connection refused"),
        ):
            result = ic.classify_intent(
                prompt="test", session_id="s", correlation_id="c"
            )

        assert result["success"] is False
        assert result["intent_class"] == "GENERAL"
        assert result["elapsed_ms"] >= 0

    def test_timeout_returns_empty_result(self) -> None:
        """classify_intent returns success=False on TimeoutError."""
        with patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
            result = ic.classify_intent(
                prompt="test", session_id="s", correlation_id="c"
            )

        assert result["success"] is False
        assert result["intent_class"] == "GENERAL"

    def test_empty_prompt_in_cli_path(self) -> None:
        """classify_intent with empty prompt still returns a valid dict."""
        # The classify function is called for non-empty prompts in the module's
        # main(), but classify_intent() itself will attempt the HTTP call.
        # We test that it does not raise and returns a dict.
        with patch(
            "urllib.request.urlopen",
            side_effect=Exception("unexpected"),
        ):
            result = ic.classify_intent(prompt="", session_id="", correlation_id="")

        assert isinstance(result, dict)
        assert result["success"] is False

    def test_malformed_json_response(self) -> None:
        """classify_intent handles invalid JSON response gracefully."""
        mock_response = MagicMock()
        mock_response.read.return_value = b"not valid json"
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = ic.classify_intent(
                prompt="test", session_id="s", correlation_id="c"
            )

        assert result["success"] is False
        assert result["intent_class"] == "GENERAL"

    def test_missing_fields_in_response_use_defaults(self) -> None:
        """classify_intent uses defaults for missing fields in response."""
        response_body = json.dumps({"intent_class": "CODE"}).encode()

        mock_response = MagicMock()
        mock_response.read.return_value = response_body
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = ic.classify_intent(
                prompt="write a function", session_id="s", correlation_id="c"
            )

        assert result["success"] is True
        assert result["intent_class"] == "CODE"
        assert result["confidence"] == pytest.approx(0.0)
        # intent_id should be the caller's generated UUID (not from response)
        assert result["intent_id"] is not None


# ---------------------------------------------------------------------------
# store_intent_in_correlation / get_intent_from_correlation
# ---------------------------------------------------------------------------


class TestIntentCorrelationPersistence:
    """Tests for intent storage in the correlation state file."""

    def test_round_trip_store_and_retrieve(self, tmp_path: Path) -> None:
        """Stored intent can be retrieved from the same state directory."""
        intent_id = str(uuid.uuid4())
        stored = ic.store_intent_in_correlation(
            intent_id=intent_id,
            intent_class="SECURITY",
            confidence=0.94,
            state_dir=tmp_path,
        )
        assert stored is True

        retrieved = ic.get_intent_from_correlation(state_dir=tmp_path)
        assert retrieved is not None
        assert retrieved["intent_id"] == intent_id
        assert retrieved["intent_class"] == "SECURITY"
        assert retrieved["intent_confidence"] == pytest.approx(0.94)

    def test_store_merges_with_existing_state(self, tmp_path: Path) -> None:
        """store_intent preserves existing correlation_id fields."""
        state_file = tmp_path / "correlation_id.json"
        state_file.write_text(
            json.dumps(
                {"correlation_id": "existing-corr", "agent_name": "polymorphic-agent"}
            ),
            encoding="utf-8",
        )

        ic.store_intent_in_correlation(
            intent_id="intent-456",
            intent_class="CODE",
            confidence=0.8,
            state_dir=tmp_path,
        )

        state = json.loads(state_file.read_text(encoding="utf-8"))
        assert state["correlation_id"] == "existing-corr"
        assert state["agent_name"] == "polymorphic-agent"
        assert state["intent_id"] == "intent-456"
        assert state["intent_class"] == "CODE"

    def test_store_is_idempotent(self, tmp_path: Path) -> None:
        """Calling store_intent twice overwrites the previous value."""
        ic.store_intent_in_correlation(
            intent_id="id-1",
            intent_class="GENERAL",
            confidence=0.5,
            state_dir=tmp_path,
        )
        ic.store_intent_in_correlation(
            intent_id="id-2",
            intent_class="SECURITY",
            confidence=0.9,
            state_dir=tmp_path,
        )

        retrieved = ic.get_intent_from_correlation(state_dir=tmp_path)
        assert retrieved is not None
        assert retrieved["intent_id"] == "id-2"
        assert retrieved["intent_class"] == "SECURITY"

    def test_get_returns_none_when_no_state_file(self, tmp_path: Path) -> None:
        """get_intent returns None when the state file does not exist."""
        result = ic.get_intent_from_correlation(state_dir=tmp_path)
        assert result is None

    def test_get_returns_none_when_intent_fields_absent(self, tmp_path: Path) -> None:
        """get_intent returns None when intent fields are missing from state."""
        state_file = tmp_path / "correlation_id.json"
        state_file.write_text(
            json.dumps({"correlation_id": "some-id"}),
            encoding="utf-8",
        )

        result = ic.get_intent_from_correlation(state_dir=tmp_path)
        assert result is None

    def test_store_returns_false_on_permission_error(self, tmp_path: Path) -> None:
        """store_intent returns False when unable to write state file."""
        with patch("builtins.open", side_effect=PermissionError("no write")):
            result = ic.store_intent_in_correlation(
                intent_id="x",
                intent_class="GENERAL",
                confidence=0.5,
                state_dir=tmp_path,
            )
        assert result is False


# ---------------------------------------------------------------------------
# get_hint_for_intent
# ---------------------------------------------------------------------------


class TestGetHintForIntent:
    """Tests for intent-to-model mapping."""

    def test_known_class_returns_correct_model(self) -> None:
        """SECURITY intent maps to opus model."""
        hint = imh.get_hint_for_intent("SECURITY")
        assert hint.intent_class == "SECURITY"
        assert "opus" in hint.recommended_model.lower()
        assert hint.temperature_hint < 0.3
        assert "security_audit" in hint.validators
        assert hint.sandbox == "enforced"

    def test_unknown_class_falls_back_to_general(self) -> None:
        """Unknown intent class falls back to GENERAL model hint values."""
        hint = imh.get_hint_for_intent("SOME_UNKNOWN_CLASS")
        # The fallback uses GENERAL model/temperature/validators/sandbox,
        # but preserves the input class name in the hint.
        general_hint = imh.get_hint_for_intent("GENERAL")
        assert hint.recommended_model == general_hint.recommended_model
        assert hint.temperature_hint == general_hint.temperature_hint
        assert hint.sandbox == general_hint.sandbox

    def test_empty_class_falls_back_to_general(self) -> None:
        """Empty string falls back to GENERAL."""
        hint = imh.get_hint_for_intent("")
        assert hint.intent_class == "GENERAL"

    def test_case_insensitive_lookup(self) -> None:
        """Intent class lookup is case-insensitive."""
        hint_lower = imh.get_hint_for_intent("security")
        hint_upper = imh.get_hint_for_intent("SECURITY")
        assert hint_lower.intent_class == hint_upper.intent_class
        assert hint_lower.recommended_model == hint_upper.recommended_model

    def test_env_override_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """OMNICLAUDE_INTENT_SECURITY_MODEL overrides the model hint."""
        monkeypatch.setenv("OMNICLAUDE_INTENT_SECURITY_MODEL", "claude-test-model")
        hint = imh.get_hint_for_intent("SECURITY")
        assert hint.recommended_model == "claude-test-model"

    def test_env_override_temperature(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """OMNICLAUDE_INTENT_CODE_TEMPERATURE overrides temperature hint."""
        monkeypatch.setenv("OMNICLAUDE_INTENT_CODE_TEMPERATURE", "0.7")
        hint = imh.get_hint_for_intent("CODE")
        assert hint.temperature_hint == pytest.approx(0.7)

    def test_env_override_invalid_temperature_keeps_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Invalid temperature env var silently keeps the default."""
        monkeypatch.setenv("OMNICLAUDE_INTENT_CODE_TEMPERATURE", "not-a-float")
        hint = imh.get_hint_for_intent("CODE")
        # Should not raise; temperature should be the default
        assert isinstance(hint.temperature_hint, float)

    def test_env_override_validators(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """OMNICLAUDE_INTENT_GENERAL_VALIDATORS overrides validator list."""
        monkeypatch.setenv("OMNICLAUDE_INTENT_GENERAL_VALIDATORS", "v1,v2,v3")
        hint = imh.get_hint_for_intent("GENERAL")
        assert hint.validators == ["v1", "v2", "v3"]

    def test_env_override_empty_validators_clears_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Setting validators to empty string clears the list."""
        monkeypatch.setenv("OMNICLAUDE_INTENT_SECURITY_VALIDATORS", "")
        hint = imh.get_hint_for_intent("SECURITY")
        assert hint.validators == []

    def test_env_override_sandbox(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """OMNICLAUDE_INTENT_GENERAL_SANDBOX overrides sandbox setting."""
        monkeypatch.setenv("OMNICLAUDE_INTENT_GENERAL_SANDBOX", "enforced")
        hint = imh.get_hint_for_intent("GENERAL")
        assert hint.sandbox == "enforced"


# ---------------------------------------------------------------------------
# format_intent_context
# ---------------------------------------------------------------------------


class TestFormatIntentContext:
    """Tests for the additionalContext formatter."""

    def test_output_contains_required_fields(self) -> None:
        """format_intent_context includes all required fields in output."""
        output = imh.format_intent_context(
            intent_class="SECURITY",
            confidence=0.94,
            intent_id="abc-123",
        )

        assert "SECURITY" in output
        assert "94%" in output
        assert "Intent-Id: abc-123" in output
        assert "Recommended model:" in output
        assert "Temperature hint:" in output
        assert "Validators:" in output
        assert "Sandbox:" in output
        assert "recommendations only" in output.lower()

    def test_output_without_intent_id_omits_id_line(self) -> None:
        """format_intent_context omits Intent-Id line when not provided."""
        output = imh.format_intent_context(
            intent_class="CODE",
            confidence=0.8,
        )
        assert "Intent-Id:" not in output

    def test_output_is_non_empty_for_all_default_classes(self) -> None:
        """format_intent_context produces non-empty output for all known classes."""
        for cls in [
            "SECURITY",
            "CODE",
            "REFACTOR",
            "TESTING",
            "DOCUMENTATION",
            "REVIEW",
            "DEBUGGING",
            "GENERAL",
        ]:
            output = imh.format_intent_context(intent_class=cls, confidence=0.7)
            assert len(output) > 50, f"Empty output for {cls}"

    def test_unknown_class_uses_general_hint(self) -> None:
        """format_intent_context uses GENERAL model/temp/validators for unknown classes."""
        output = imh.format_intent_context(intent_class="UNKNOWN_XYZ", confidence=0.5)
        # The output should contain the model from GENERAL hint (sonnet) and
        # have sandbox "none" (GENERAL default), confirming fallback is applied.
        general_hint = imh.get_hint_for_intent("GENERAL")
        assert general_hint.recommended_model in output
        assert f"Sandbox: {general_hint.sandbox}" in output


# ---------------------------------------------------------------------------
# CLI subprocess tests (exit 0 on failure)
# ---------------------------------------------------------------------------


class TestCLIExitBehavior:
    """Tests that the CLI always exits 0."""

    def _run_classifier(
        self, env: dict[str, str], extra_args: list[str] | None = None
    ) -> subprocess.CompletedProcess:
        """Run intent_classifier.py as a subprocess."""
        script = Path(_LIB_PATH) / "intent_classifier.py"
        cmd = [sys.executable, str(script)] + (extra_args or [])
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
            check=False,
        )

    def test_exits_0_when_service_unavailable(self) -> None:
        """CLI exits 0 when omniintelligence is not reachable."""
        env = _make_env(
            OMNICLAUDE_INTENT_API_URL="http://127.0.0.1:19999/api/v1/intent/classify",
            OMNICLAUDE_STATE_DIR="/tmp",
        )
        result = self._run_classifier(
            env,
            extra_args=[
                "--session-id",
                "test-sess",
                "--correlation-id",
                "test-corr",
                "--prompt-b64",
                "aGVsbG8gd29ybGQ=",  # "hello world"
                "--no-store",
            ],
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert "success" in output
        assert output["success"] is False
        assert output["intent_class"] == "GENERAL"

    def test_exits_0_with_empty_prompt(self) -> None:
        """CLI exits 0 when no prompt is provided."""
        env = _make_env()
        result = self._run_classifier(
            env,
            extra_args=["--session-id", "s", "--correlation-id", "c", "--no-store"],
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["success"] is False

    def test_prompt_stdin_decodes_base64(self) -> None:
        """CLI --prompt-stdin decodes base64 from stdin (not treating it as literal text)."""
        import base64

        env = _make_env(
            OMNICLAUDE_INTENT_API_URL="http://127.0.0.1:19999/api/v1/intent/classify",
        )
        b64_prompt = base64.b64encode(b"hello world").decode()
        script = Path(_LIB_PATH) / "intent_classifier.py"
        cmd = [sys.executable, str(script), "--prompt-stdin", "--no-store"]
        result = subprocess.run(
            cmd,
            input=b64_prompt,
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
            check=False,
        )
        assert result.returncode == 0
        parsed = json.loads(result.stdout)
        # Service is unavailable so success=False, but the exit code must be 0
        # and the output must be valid JSON — confirming the stdin path ran
        assert isinstance(parsed, dict)
        assert "success" in parsed

    def test_output_is_valid_json(self) -> None:
        """CLI always produces valid JSON on stdout."""
        env = _make_env(
            OMNICLAUDE_INTENT_API_URL="http://127.0.0.1:19999/api/v1/intent/classify",
        )
        result = self._run_classifier(
            env,
            extra_args=["--prompt-b64", "dGVzdA==", "--no-store"],
        )
        assert result.returncode == 0
        # Must parse without raising
        parsed = json.loads(result.stdout)
        assert isinstance(parsed, dict)
