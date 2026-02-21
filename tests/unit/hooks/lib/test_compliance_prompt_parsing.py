"""Compliance prompt regression tests (OMN-2258).

Snapshot-tests the JSON schema of compliance output (EnforcementResult,
PatternAdvisory), validates structural eligibility filtering of patterns,
and exercises bad-output recovery paths (malformed JSON, empty stdin,
unexpected fields, None values).

All tests run without network access or external services.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# sys.path setup: plugin lib modules live outside the normal package tree
# ---------------------------------------------------------------------------

sys.path.insert(
    0,
    str(
        Path(__file__).parent.parent.parent.parent.parent
        / "plugins"
        / "onex"
        / "hooks"
        / "lib"
    ),
)

from pattern_enforcement import (
    EnforcementResult,
    PatternAdvisory,
    _is_eligible_pattern,
    enforce_patterns,
    main,
)

# All tests in this module are unit tests
pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pattern(
    *,
    pattern_id: str = "pat-001",
    signature: str = "Use descriptive names",
    domain_id: str = "code_quality",
    confidence: float = 0.85,
    status: str = "validated",
    **extras: Any,
) -> dict[str, Any]:
    """Build a pattern dict matching the pattern store API shape."""
    base: dict[str, Any] = {
        "id": pattern_id,
        "pattern_signature": signature,
        "domain_id": domain_id,
        "confidence": confidence,
        "status": status,
    }
    base.update(extras)
    return base


def _enforcement_result_keys() -> set[str]:
    """Canonical set of top-level keys in an EnforcementResult."""
    return {
        "enforced",
        "advisories",
        "patterns_queried",
        "patterns_skipped_cooldown",
        "patterns_skipped_ineligible",
        "elapsed_ms",
        "error",
        "evaluation_submitted",
    }


def _advisory_keys() -> set[str]:
    """Canonical set of keys in a PatternAdvisory."""
    return {
        "pattern_id",
        "pattern_signature",
        "domain_id",
        "confidence",
        "status",
        "message",
    }


# ============================================================================
# 1. Schema Snapshot Tests
# ============================================================================


class TestEnforcementResultSchema:
    """Snapshot tests ensuring the EnforcementResult schema is stable."""

    def test_enforcement_result_has_all_expected_keys(self) -> None:
        """EnforcementResult TypedDict declares exactly the expected keys."""
        result = EnforcementResult(
            enforced=True,
            advisories=[],
            patterns_queried=0,
            patterns_skipped_cooldown=0,
            patterns_skipped_ineligible=0,
            elapsed_ms=0.0,
            error=None,
            evaluation_submitted=False,
        )
        assert set(result.keys()) == _enforcement_result_keys()

    def test_enforcement_result_roundtrips_through_json(self) -> None:
        """EnforcementResult can be serialized and deserialized via JSON."""
        original = EnforcementResult(
            enforced=True,
            advisories=[],
            patterns_queried=5,
            patterns_skipped_cooldown=2,
            patterns_skipped_ineligible=1,
            elapsed_ms=42.5,
            error=None,
            evaluation_submitted=True,
        )
        serialized = json.dumps(original)
        deserialized = json.loads(serialized)

        assert deserialized["enforced"] is True
        assert deserialized["advisories"] == []
        assert deserialized["patterns_queried"] == 5
        assert deserialized["patterns_skipped_cooldown"] == 2
        assert deserialized["elapsed_ms"] == 42.5
        assert deserialized["error"] is None
        assert deserialized["evaluation_submitted"] is True

    def test_enforcement_result_with_error_roundtrips(self) -> None:
        """EnforcementResult with a non-None error string round-trips correctly."""
        original = EnforcementResult(
            enforced=False,
            advisories=[],
            patterns_queried=0,
            patterns_skipped_cooldown=0,
            patterns_skipped_ineligible=0,
            elapsed_ms=1.0,
            error="connection refused",
            evaluation_submitted=False,
        )
        deserialized = json.loads(json.dumps(original))
        assert deserialized["enforced"] is False
        assert deserialized["error"] == "connection refused"
        assert deserialized["evaluation_submitted"] is False

    def test_enforcement_result_enforced_types(self) -> None:
        """Type constraints: enforced is bool, elapsed_ms is float, etc."""
        result = EnforcementResult(
            enforced=True,
            advisories=[],
            patterns_queried=0,
            patterns_skipped_cooldown=0,
            patterns_skipped_ineligible=0,
            elapsed_ms=0.0,
            error=None,
            evaluation_submitted=False,
        )
        assert isinstance(result["enforced"], bool)
        assert isinstance(result["advisories"], list)
        assert isinstance(result["patterns_queried"], int)
        assert isinstance(result["patterns_skipped_cooldown"], int)
        assert isinstance(result["elapsed_ms"], float)
        assert isinstance(result["evaluation_submitted"], bool)


class TestPatternAdvisorySchema:
    """Snapshot tests ensuring the PatternAdvisory schema is stable.

    PatternAdvisory TypedDict is still defined for use when Ticket 4
    (compliance result subscriber) writes advisories back to storage.
    """

    def test_advisory_has_all_expected_keys(self) -> None:
        """PatternAdvisory TypedDict declares exactly the expected keys."""
        advisory = PatternAdvisory(
            pattern_id="p-001",
            pattern_signature="sig",
            domain_id="domain",
            confidence=0.9,
            status="validated",
            message="test message",
        )
        assert set(advisory.keys()) == _advisory_keys()

    def test_advisory_roundtrips_through_json(self) -> None:
        """PatternAdvisory can be serialized and deserialized via JSON."""
        original = PatternAdvisory(
            pattern_id="abc-123",
            pattern_signature="Use type hints",
            domain_id="python",
            confidence=0.92,
            status="validated",
            message="Pattern 'Use type hints' (confidence: 0.92) may apply.",
        )
        deserialized = json.loads(json.dumps(original))

        assert deserialized["pattern_id"] == "abc-123"
        assert deserialized["pattern_signature"] == "Use type hints"
        assert deserialized["domain_id"] == "python"
        assert deserialized["confidence"] == 0.92
        assert deserialized["status"] == "validated"
        assert "Use type hints" in deserialized["message"]


# ============================================================================
# 2. Eligibility Filtering Tests
# ============================================================================


class TestEligibilityFiltering:
    """Tests for _is_eligible_pattern() structural filtering."""

    def test_valid_pattern_is_eligible(self) -> None:
        """Validated pattern with all fields passes eligibility."""
        pattern = _make_pattern()
        assert _is_eligible_pattern(pattern) is True

    def test_multiple_patterns_eligibility_is_independent(self) -> None:
        """Each pattern's eligibility is evaluated independently."""
        patterns = [
            _make_pattern(pattern_id="p1", signature="sig-1", confidence=0.9),
            _make_pattern(pattern_id="p2", signature="sig-2", confidence=0.8),
            _make_pattern(pattern_id="p3", signature="sig-3", confidence=0.7),
        ]
        results = [_is_eligible_pattern(p) for p in patterns]
        assert all(results)

    def test_draft_status_is_ineligible(self) -> None:
        """Draft patterns are not eligible."""
        pattern = _make_pattern(status="draft")
        assert _is_eligible_pattern(pattern) is False

    def test_provisional_status_is_ineligible(self) -> None:
        """Provisional patterns are not eligible."""
        pattern = _make_pattern(status="provisional")
        assert _is_eligible_pattern(pattern) is False

    def test_enforce_patterns_advisories_always_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """enforce_patterns returns advisories=[] always — results arrive async."""
        monkeypatch.setattr("pattern_enforcement._COOLDOWN_DIR", tmp_path)
        patterns = [
            _make_pattern(pattern_id="p1"),
            _make_pattern(pattern_id="p2"),
        ]
        with (
            patch("pattern_enforcement.query_patterns", return_value=patterns),
            patch("pattern_enforcement._emit_compliance_evaluate", return_value=True),
        ):
            result = enforce_patterns(
                file_path="/test/file.py",
                session_id="sess-parse",
                language="python",
                content_preview="def foo(): pass\n",
                emitted_at="2024-01-01T00:00:00Z",
            )
        assert result["enforced"] is True
        assert result["advisories"] == []  # always empty — async model
        assert result["evaluation_submitted"] is True


# ============================================================================
# 3. Bad Output Recovery Tests
# ============================================================================


class TestBadOutputRecovery:
    """Tests for handling no-violations, parse failures, and bad data."""

    # --- No violations found (empty list) ---

    def test_no_patterns_returns_empty_advisories(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Zero patterns from the store produces an empty advisory list."""
        monkeypatch.setattr("pattern_enforcement._COOLDOWN_DIR", tmp_path)
        with patch("pattern_enforcement.query_patterns", return_value=[]):
            result = enforce_patterns(
                file_path="/test/file.py",
                session_id="sess-empty",
                language="python",
                emitted_at="2024-01-01T00:00:00Z",
            )
        assert result["enforced"] is True
        assert result["advisories"] == []
        assert result["error"] is None
        assert result["evaluation_submitted"] is False

    def test_all_patterns_filtered_returns_empty_advisories(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Patterns that are all non-validated produce empty advisories and no emit."""
        monkeypatch.setattr("pattern_enforcement._COOLDOWN_DIR", tmp_path)
        patterns = [
            _make_pattern(pattern_id="draft-1", status="draft"),
            _make_pattern(pattern_id="prov-1", status="provisional"),
            _make_pattern(pattern_id="unknown-1", status="unknown"),
        ]
        with (
            patch("pattern_enforcement.query_patterns", return_value=patterns),
            patch("pattern_enforcement._emit_compliance_evaluate") as mock_emit,
        ):
            result = enforce_patterns(
                file_path="/test/file.py",
                session_id="sess-filtered",
                language="python",
                content_preview="def foo(): pass\n",
                emitted_at="2024-01-01T00:00:00Z",
            )
        assert result["enforced"] is True
        assert result["advisories"] == []
        mock_emit.assert_not_called()

    # --- Parse failure (malformed JSON in CLI) ---

    def test_main_malformed_json_stdin_returns_safe_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Malformed JSON on stdin produces a safe error, not a crash."""
        monkeypatch.setenv("ENABLE_LOCAL_INFERENCE_PIPELINE", "true")
        monkeypatch.setenv("ENABLE_PATTERN_ENFORCEMENT", "true")
        monkeypatch.setattr("sys.stdin", MagicMock(read=lambda: "{invalid json"))

        main()

        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["enforced"] is False
        assert result["error"] is not None
        assert len(result["error"]) > 0

    def test_main_partial_json_stdin_returns_safe_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Truncated JSON on stdin still produces valid JSON output."""
        monkeypatch.setenv("ENABLE_LOCAL_INFERENCE_PIPELINE", "true")
        monkeypatch.setenv("ENABLE_PATTERN_ENFORCEMENT", "true")
        monkeypatch.setattr(
            "sys.stdin", MagicMock(read=lambda: '{"file_path": "/test.py"')
        )

        main()

        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["enforced"] is False
        assert set(result.keys()) == _enforcement_result_keys()

    # --- Empty response ---

    def test_main_empty_stdin_returns_safe_result(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Empty stdin produces safe JSON output with error field set."""
        monkeypatch.setenv("ENABLE_LOCAL_INFERENCE_PIPELINE", "true")
        monkeypatch.setenv("ENABLE_PATTERN_ENFORCEMENT", "true")
        monkeypatch.setattr("sys.stdin", MagicMock(read=lambda: ""))

        main()

        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["enforced"] is False
        assert result["error"] == "empty stdin"

    def test_main_whitespace_only_stdin_returns_safe_result(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Whitespace-only stdin is treated as empty input."""
        monkeypatch.setenv("ENABLE_LOCAL_INFERENCE_PIPELINE", "true")
        monkeypatch.setenv("ENABLE_PATTERN_ENFORCEMENT", "true")
        monkeypatch.setattr("sys.stdin", MagicMock(read=lambda: "   \n\t  "))

        main()

        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["enforced"] is False
        assert result["error"] == "empty stdin"

    # --- None/null response ---

    def test_main_null_json_stdin_returns_safe_result(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """JSON null on stdin produces a safe result (params will be None).

        Code path: json.loads("null") returns Python None, then
        params.get("session_id") raises AttributeError on NoneType,
        which is caught by main()'s outer exception handler.
        _COOLDOWN_DIR is never reached.
        """
        monkeypatch.setenv("ENABLE_LOCAL_INFERENCE_PIPELINE", "true")
        monkeypatch.setenv("ENABLE_PATTERN_ENFORCEMENT", "true")
        monkeypatch.setattr("sys.stdin", MagicMock(read=lambda: "null"))

        main()

        captured = capsys.readouterr()
        result = json.loads(captured.out)
        # Should produce valid JSON output (safe error or empty enforcement result)
        assert set(result.keys()) == _enforcement_result_keys()

    # --- Unexpected fields in pattern ---

    def test_is_eligible_pattern_ignores_extra_pattern_fields(self) -> None:
        """Extra fields in the pattern dict are silently ignored."""
        pattern = _make_pattern(
            extra_field_1="unexpected",
            extra_field_2=42,
            nested_extra={"key": "value"},
        )
        assert _is_eligible_pattern(pattern) is True

    def test_enforce_patterns_handles_exception_safely(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unexpected exceptions in enforcement produce safe error result."""
        monkeypatch.setattr("pattern_enforcement._COOLDOWN_DIR", tmp_path)
        with patch(
            "pattern_enforcement.query_patterns",
            side_effect=RuntimeError("unexpected crash"),
        ):
            result = enforce_patterns(
                file_path="/test/file.py",
                session_id="sess-crash",
                language="python",
                emitted_at="2024-01-01T00:00:00Z",
            )
        assert result["enforced"] is False
        assert result["error"] == "unexpected crash"
        assert result["advisories"] == []
        assert result["evaluation_submitted"] is False
        assert set(result.keys()) == _enforcement_result_keys()


# ============================================================================
# 4. Edge Cases
# ============================================================================


class TestEdgeCases:
    """Edge cases for compliance eligibility and enforcement pipeline."""

    # --- Domain/signature field handling ---

    def test_unicode_in_pattern_signature(self) -> None:
        """Unicode characters in pattern signature are preserved in eligibility check."""
        unicode_sig = "Use descriptive names (beschreibende Namen verwenden)"
        pattern = _make_pattern(signature=unicode_sig)
        assert _is_eligible_pattern(pattern) is True

    def test_domain_id_preserved_in_eligible_pattern(self) -> None:
        """domain_id is present in eligible patterns."""
        pattern = _make_pattern(domain_id="code_quality")
        assert _is_eligible_pattern(pattern) is True

    def test_emoji_in_pattern_signature(self) -> None:
        """Emoji characters in pattern signatures are handled without error."""
        pattern = _make_pattern(signature="Always add docstrings 📝 to classes ✅")
        assert _is_eligible_pattern(pattern) is True

    def test_cjk_characters_in_fields(self) -> None:
        """CJK characters in pattern fields do not affect eligibility."""
        pattern = _make_pattern(
            signature="型注釈が必要です",  # "Type annotations required" in Japanese
            domain_id="代码质量",  # "code_quality" in Chinese
        )
        assert _is_eligible_pattern(pattern) is True

    # --- Duplicate / boundary confidence ---

    def test_duplicate_pattern_ids_eligible_independently(self) -> None:
        """Same pattern ID appearing in two separate dicts is eligible independently."""
        p1 = _make_pattern(pattern_id="dup-001")
        p2 = _make_pattern(pattern_id="dup-001")
        assert _is_eligible_pattern(p1) is True
        assert _is_eligible_pattern(p2) is True

    def test_confidence_zero_is_eligible(self) -> None:
        """Confidence of 0.0 is structurally eligible (semantic filtering in intelligence)."""
        pattern = _make_pattern(confidence=0.0)
        assert _is_eligible_pattern(pattern) is True

    def test_confidence_one_is_eligible(self) -> None:
        """Confidence of 1.0 is eligible."""
        pattern = _make_pattern(confidence=1.0)
        assert _is_eligible_pattern(pattern) is True

    def test_confidence_negative_is_eligible(self) -> None:
        """Negative confidence is structurally valid (clamping is in query_patterns)."""
        pattern = _make_pattern(confidence=-0.5)
        assert _is_eligible_pattern(pattern) is True

    # --- Missing or empty pattern fields ---

    def test_missing_id_is_ineligible(self) -> None:
        """Pattern without 'id' key is ineligible."""
        pattern = {"pattern_signature": "sig", "confidence": 0.9, "status": "validated"}
        assert _is_eligible_pattern(pattern) is False

    def test_empty_id_is_ineligible(self) -> None:
        """Pattern with empty string 'id' is ineligible."""
        pattern = _make_pattern(pattern_id="")
        assert _is_eligible_pattern(pattern) is False

    def test_missing_signature_is_ineligible(self) -> None:
        """Pattern without 'pattern_signature' key is ineligible."""
        pattern = {"id": "p-001", "confidence": 0.9, "status": "validated"}
        assert _is_eligible_pattern(pattern) is False

    def test_empty_signature_is_ineligible(self) -> None:
        """Pattern with empty string signature is ineligible."""
        pattern = _make_pattern(signature="")
        assert _is_eligible_pattern(pattern) is False

    def test_missing_confidence_defaults_to_zero_and_is_eligible(self) -> None:
        """Pattern without confidence key defaults to 0.0 (structurally valid)."""
        pattern = {
            "id": "p-001",
            "pattern_signature": "sig",
            "status": "validated",
        }
        assert _is_eligible_pattern(pattern) is True

    def test_missing_domain_id_is_eligible(self) -> None:
        """Pattern without domain_id is still structurally eligible."""
        pattern = {
            "id": "p-001",
            "pattern_signature": "sig",
            "confidence": 0.9,
            "status": "validated",
        }
        assert _is_eligible_pattern(pattern) is True

    def test_missing_status_defaults_to_unknown_and_is_ineligible(self) -> None:
        """Pattern without status defaults to 'unknown' and is ineligible."""
        pattern = {
            "id": "p-001",
            "pattern_signature": "sig",
            "confidence": 0.9,
        }
        assert _is_eligible_pattern(pattern) is False

    # --- Non-numeric and unusual confidence values ---

    def test_non_numeric_confidence_is_ineligible(self) -> None:
        """Non-numeric confidence value is ineligible."""
        pattern = _make_pattern(confidence="not-a-number")  # type: ignore[arg-type]
        assert _is_eligible_pattern(pattern) is False

    def test_none_confidence_is_ineligible(self) -> None:
        """None confidence value is ineligible (float(None) raises TypeError)."""
        pattern = _make_pattern(confidence=None)  # type: ignore[arg-type]
        assert _is_eligible_pattern(pattern) is False

    def test_boolean_confidence_is_eligible(self) -> None:
        """Boolean confidence values are converted via float() (True -> 1.0)."""
        pattern = _make_pattern(confidence=True)  # type: ignore[arg-type]
        assert _is_eligible_pattern(pattern) is True

    # --- Nested / complex pattern structures ---

    def test_pattern_with_nested_metadata_is_eligible(self) -> None:
        """Extra nested metadata in pattern doesn't affect eligibility."""
        pattern = _make_pattern(
            metadata={"created_by": "system", "version": 2},
            tags=["python", "naming"],
            rules=[{"type": "naming", "severity": "warning"}],
        )
        assert _is_eligible_pattern(pattern) is True

    # --- Empty pattern dict ---

    def test_empty_pattern_dict_is_ineligible(self) -> None:
        """Completely empty pattern dict is ineligible."""
        assert _is_eligible_pattern({}) is False

    # --- CLI main() with valid but edge-case inputs ---

    def test_main_valid_input_missing_optional_fields(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ) -> None:
        """Valid JSON with only file_path (missing optional fields) still works."""
        monkeypatch.setenv("ENABLE_LOCAL_INFERENCE_PIPELINE", "true")
        monkeypatch.setenv("ENABLE_PATTERN_ENFORCEMENT", "true")
        monkeypatch.setattr("pattern_enforcement._COOLDOWN_DIR", tmp_path)

        input_json = json.dumps({"file_path": "/test/file.py"})
        monkeypatch.setattr("sys.stdin", MagicMock(read=lambda: input_json))

        with patch("pattern_enforcement.query_patterns", return_value=[]):
            main()

        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["enforced"] is True
        assert set(result.keys()) == _enforcement_result_keys()

    def test_main_disabled_outputs_enforced_false(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """When feature flags are off, main() outputs enforced=False."""
        monkeypatch.delenv("ENABLE_LOCAL_INFERENCE_PIPELINE", raising=False)
        monkeypatch.delenv("ENABLE_PATTERN_ENFORCEMENT", raising=False)

        main()

        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["enforced"] is False
        assert result["error"] is None
        assert set(result.keys()) == _enforcement_result_keys()

    def test_main_outputs_valid_json_on_all_code_paths(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Every code path in main() produces valid JSON on stdout."""
        # Path 1: disabled
        monkeypatch.delenv("ENABLE_LOCAL_INFERENCE_PIPELINE", raising=False)
        monkeypatch.delenv("ENABLE_PATTERN_ENFORCEMENT", raising=False)
        main()
        out1 = capsys.readouterr().out
        json.loads(out1)  # Must not raise

        # Path 2: enabled, empty stdin
        monkeypatch.setenv("ENABLE_LOCAL_INFERENCE_PIPELINE", "true")
        monkeypatch.setenv("ENABLE_PATTERN_ENFORCEMENT", "true")
        monkeypatch.setattr("sys.stdin", MagicMock(read=lambda: ""))
        main()
        out2 = capsys.readouterr().out
        json.loads(out2)  # Must not raise

        # Path 3: enabled, malformed JSON
        monkeypatch.setattr("sys.stdin", MagicMock(read=lambda: "{{bad"))
        main()
        out3 = capsys.readouterr().out
        json.loads(out3)  # Must not raise

    # --- Timing metadata ---

    def test_elapsed_ms_is_non_negative(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """elapsed_ms is always a non-negative float."""
        monkeypatch.setattr("pattern_enforcement._COOLDOWN_DIR", tmp_path)
        with patch("pattern_enforcement.query_patterns", return_value=[]):
            result = enforce_patterns(
                file_path="/test/file.py",
                session_id="sess-timing",
                language="python",
                emitted_at="2024-01-01T00:00:00Z",
            )
        assert isinstance(result["elapsed_ms"], float)
        assert result["elapsed_ms"] >= 0.0

    def test_patterns_queried_matches_input_count(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """patterns_queried reflects the number of patterns from the store."""
        monkeypatch.setattr("pattern_enforcement._COOLDOWN_DIR", tmp_path)
        patterns = [_make_pattern(pattern_id=f"p-{i}") for i in range(7)]
        with (
            patch("pattern_enforcement.query_patterns", return_value=patterns),
            patch("pattern_enforcement._emit_compliance_evaluate", return_value=True),
        ):
            result = enforce_patterns(
                file_path="/test/file.py",
                session_id="sess-count",
                language="python",
                content_preview="def foo(): pass\n",
                emitted_at="2024-01-01T00:00:00Z",
            )
        assert result["patterns_queried"] == 7

    # --- JSON array on stdin ---

    def test_main_json_array_stdin_returns_safe_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """JSON array on stdin (instead of object) produces safe error."""
        monkeypatch.setenv("ENABLE_LOCAL_INFERENCE_PIPELINE", "true")
        monkeypatch.setenv("ENABLE_PATTERN_ENFORCEMENT", "true")
        monkeypatch.setattr("sys.stdin", MagicMock(read=lambda: "[1, 2, 3]"))

        with patch("pattern_enforcement.query_patterns", return_value=[]):
            main()

        captured = capsys.readouterr()
        result = json.loads(captured.out)
        # A JSON array has no .get() method, so parsing it as an object
        # produces an error -- the hook handles this gracefully.
        assert set(result.keys()) == _enforcement_result_keys()
        assert result["enforced"] is False
        assert result["error"] is not None

    # --- Large number of patterns ---

    def test_many_eligible_patterns_emit_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A large number of eligible patterns triggers a single emit."""
        monkeypatch.setattr("pattern_enforcement._COOLDOWN_DIR", tmp_path)
        count = 50
        patterns = [
            _make_pattern(pattern_id=f"p-{i}", confidence=0.7 + (i % 30) * 0.01)
            for i in range(count)
        ]
        emit_call_count = [0]

        def count_emit(**kwargs: Any) -> bool:
            emit_call_count[0] += 1
            return True

        with (
            patch("pattern_enforcement.query_patterns", return_value=patterns),
            patch(
                "pattern_enforcement._emit_compliance_evaluate", side_effect=count_emit
            ),
        ):
            result = enforce_patterns(
                file_path="/test/file.py",
                session_id="sess-many",
                language="python",
                content_preview="def foo(): pass\n",
                emitted_at="2024-01-01T00:00:00Z",
            )
        assert result["enforced"] is True
        assert result["advisories"] == []  # always empty
        assert result["patterns_queried"] == count
        # Single emit, not one per pattern
        assert emit_call_count[0] == 1
