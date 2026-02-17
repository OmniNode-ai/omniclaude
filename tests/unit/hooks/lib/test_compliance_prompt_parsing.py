"""Compliance prompt regression tests (OMN-2258).

Snapshot-tests the JSON schema of compliance prompt output (EnforcementResult,
PatternAdvisory), validates parsing of violation lists from LLM/API responses,
and exercises bad-output recovery paths (malformed JSON, empty stdin, unexpected
fields, None values).

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
    check_compliance,
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
        "elapsed_ms",
        "error",
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
            elapsed_ms=0.0,
            error=None,
        )
        assert set(result.keys()) == _enforcement_result_keys()

    def test_enforcement_result_roundtrips_through_json(self) -> None:
        """EnforcementResult can be serialized and deserialized via JSON."""
        original = EnforcementResult(
            enforced=True,
            advisories=[],
            patterns_queried=5,
            patterns_skipped_cooldown=2,
            elapsed_ms=42.5,
            error=None,
        )
        serialized = json.dumps(original)
        deserialized = json.loads(serialized)

        assert deserialized["enforced"] is True
        assert deserialized["advisories"] == []
        assert deserialized["patterns_queried"] == 5
        assert deserialized["patterns_skipped_cooldown"] == 2
        assert deserialized["elapsed_ms"] == 42.5
        assert deserialized["error"] is None

    def test_enforcement_result_with_error_roundtrips(self) -> None:
        """EnforcementResult with a non-None error string round-trips correctly."""
        original = EnforcementResult(
            enforced=False,
            advisories=[],
            patterns_queried=0,
            patterns_skipped_cooldown=0,
            elapsed_ms=1.0,
            error="connection refused",
        )
        deserialized = json.loads(json.dumps(original))
        assert deserialized["enforced"] is False
        assert deserialized["error"] == "connection refused"

    def test_enforcement_result_enforced_types(self) -> None:
        """Type constraints: enforced is bool, elapsed_ms is float, etc."""
        result = EnforcementResult(
            enforced=True,
            advisories=[],
            patterns_queried=0,
            patterns_skipped_cooldown=0,
            elapsed_ms=0.0,
            error=None,
        )
        assert isinstance(result["enforced"], bool)
        assert isinstance(result["advisories"], list)
        assert isinstance(result["patterns_queried"], int)
        assert isinstance(result["patterns_skipped_cooldown"], int)
        assert isinstance(result["elapsed_ms"], float)


class TestPatternAdvisorySchema:
    """Snapshot tests ensuring the PatternAdvisory schema is stable."""

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

    def test_enforcement_result_with_advisories_roundtrips(self) -> None:
        """Full EnforcementResult containing advisories round-trips via JSON."""
        advisories = [
            PatternAdvisory(
                pattern_id="p-001",
                pattern_signature="Use descriptive names",
                domain_id="python",
                confidence=0.88,
                status="validated",
                message="Descriptive names advisory",
            ),
            PatternAdvisory(
                pattern_id="p-002",
                pattern_signature="Add docstrings",
                domain_id="python",
                confidence=0.75,
                status="validated",
                message="Docstring advisory",
            ),
        ]
        result = EnforcementResult(
            enforced=True,
            advisories=advisories,
            patterns_queried=10,
            patterns_skipped_cooldown=3,
            elapsed_ms=150.0,
            error=None,
        )
        deserialized = json.loads(json.dumps(result))
        assert len(deserialized["advisories"]) == 2
        assert deserialized["advisories"][0]["pattern_id"] == "p-001"
        assert deserialized["advisories"][1]["pattern_id"] == "p-002"
        for adv in deserialized["advisories"]:
            assert set(adv.keys()) == _advisory_keys()


# ============================================================================
# 2. Violation List Parsing Tests
# ============================================================================


class TestViolationListParsing:
    """Tests for check_compliance() parsing pattern data into advisories."""

    def test_valid_pattern_produces_advisory(self) -> None:
        """Validated pattern with all fields returns a well-formed advisory."""
        pattern = _make_pattern()
        result = check_compliance(
            file_path="/test/file.py",
            content_preview="x = 1\n",
            pattern=pattern,
        )
        assert result is not None
        assert set(result.keys()) == _advisory_keys()
        assert result["pattern_id"] == "pat-001"
        assert result["confidence"] == 0.85
        assert result["status"] == "validated"

    def test_multiple_patterns_produce_independent_advisories(self) -> None:
        """Each pattern produces its own advisory independently."""
        patterns = [
            _make_pattern(pattern_id="p1", signature="sig-1", confidence=0.9),
            _make_pattern(pattern_id="p2", signature="sig-2", confidence=0.8),
            _make_pattern(pattern_id="p3", signature="sig-3", confidence=0.7),
        ]
        results = [
            check_compliance(file_path="f.py", content_preview="", pattern=p)
            for p in patterns
        ]
        assert all(r is not None for r in results)
        ids = [r["pattern_id"] for r in results if r is not None]
        assert ids == ["p1", "p2", "p3"]

    def test_advisory_message_contains_signature(self) -> None:
        """Advisory message includes the pattern signature."""
        pattern = _make_pattern(signature="Always use type annotations")
        result = check_compliance(
            file_path="test.py", content_preview="", pattern=pattern
        )
        assert result is not None
        # This assertion passes because the signature (28 chars) is shorter than
        # the 80-char truncation threshold applied in check_compliance().
        assert "Always use type annotations" in result["message"]

    def test_advisory_message_contains_confidence(self) -> None:
        """Advisory message includes the confidence value."""
        pattern = _make_pattern(confidence=0.93)
        result = check_compliance(
            file_path="test.py", content_preview="", pattern=pattern
        )
        assert result is not None
        assert "0.93" in result["message"]

    def test_enforce_patterns_produces_advisory_list(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """enforce_patterns returns a list of advisories from matching patterns."""
        monkeypatch.setattr("pattern_enforcement._COOLDOWN_DIR", tmp_path)
        patterns = [
            _make_pattern(pattern_id="p1"),
            _make_pattern(pattern_id="p2"),
        ]
        with patch("pattern_enforcement.query_patterns", return_value=patterns):
            result = enforce_patterns(
                file_path="/test/file.py",
                session_id="sess-parse",
                language="python",
            )
        assert result["enforced"] is True
        assert len(result["advisories"]) == 2
        for adv in result["advisories"]:
            assert set(adv.keys()) == _advisory_keys()


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
            )
        assert result["enforced"] is True
        assert result["advisories"] == []
        assert result["error"] is None

    def test_all_patterns_filtered_returns_empty_advisories(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Patterns that are all non-validated produce an empty advisory list."""
        monkeypatch.setattr("pattern_enforcement._COOLDOWN_DIR", tmp_path)
        patterns = [
            _make_pattern(pattern_id="draft-1", status="draft"),
            _make_pattern(pattern_id="prov-1", status="provisional"),
            _make_pattern(pattern_id="unknown-1", status="unknown"),
        ]
        with patch("pattern_enforcement.query_patterns", return_value=patterns):
            result = enforce_patterns(
                file_path="/test/file.py",
                session_id="sess-filtered",
                language="python",
            )
        assert result["enforced"] is True
        assert result["advisories"] == []

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

    def test_check_compliance_ignores_extra_pattern_fields(self) -> None:
        """Extra fields in the pattern dict are silently ignored."""
        pattern = _make_pattern(
            extra_field_1="unexpected",
            extra_field_2=42,
            nested_extra={"key": "value"},
        )
        result = check_compliance(
            file_path="test.py", content_preview="", pattern=pattern
        )
        assert result is not None
        assert set(result.keys()) == _advisory_keys()

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
            )
        assert result["enforced"] is False
        assert result["error"] == "unexpected crash"
        assert result["advisories"] == []
        assert set(result.keys()) == _enforcement_result_keys()


# ============================================================================
# 4. Edge Cases
# ============================================================================


class TestEdgeCases:
    """Edge cases for compliance prompt parsing."""

    # --- Very long violation descriptions ---

    def test_long_signature_is_truncated_in_message(self) -> None:
        """Very long pattern signatures are truncated in the advisory message."""
        long_sig = "A" * 200
        pattern = _make_pattern(signature=long_sig)
        result = check_compliance(
            file_path="test.py", content_preview="", pattern=pattern
        )
        assert result is not None
        # The signature is truncated to 80 chars in the message
        assert result["pattern_signature"] == long_sig  # Full in the field
        assert long_sig[:80] in result["message"]  # Truncated version appears
        assert long_sig[:81] not in result["message"]  # Confirms truncation at 80 chars

    # --- Unicode in violation messages ---

    def test_unicode_in_pattern_signature(self) -> None:
        """Unicode characters in pattern signature are preserved."""
        unicode_sig = "Use descriptive names (beschreibende Namen verwenden)"
        pattern = _make_pattern(signature=unicode_sig)
        result = check_compliance(
            file_path="test.py", content_preview="", pattern=pattern
        )
        assert result is not None
        assert result["pattern_signature"] == unicode_sig
        assert unicode_sig[:80] in result["message"]

    def test_domain_id_preserved_in_match(self) -> None:
        """domain_id is correctly passed through in the pattern matching result."""
        pattern = _make_pattern(domain_id="code_quality")
        result = check_compliance(
            file_path="test.py", content_preview="", pattern=pattern
        )
        assert result is not None
        assert result["domain_id"] == "code_quality"

    def test_emoji_in_pattern_signature(self) -> None:
        """Emoji characters in pattern signatures are handled without error."""
        pattern = _make_pattern(signature="Always add docstrings 📝 to classes ✅")
        result = check_compliance(
            file_path="test.py", content_preview="", pattern=pattern
        )
        assert result is not None
        assert "📝" in result["message"]

    def test_cjk_characters_in_fields(self) -> None:
        """CJK characters in pattern fields are preserved through round-trip."""
        pattern = _make_pattern(
            signature="型注釈が必要です",  # "Type annotations required" in Japanese
            domain_id="代码质量",  # "code_quality" in Chinese
        )
        result = check_compliance(
            file_path="test.py", content_preview="", pattern=pattern
        )
        assert result is not None
        serialized = json.dumps(result, ensure_ascii=False)
        deserialized = json.loads(serialized)
        assert deserialized["domain_id"] == "代码质量"
        assert deserialized["pattern_signature"] == "型注釈が必要です"

    # --- Multiple violations of the same type ---

    def test_duplicate_pattern_ids_produce_separate_advisories(self) -> None:
        """Same pattern ID appearing twice produces two independent advisories."""
        pattern = _make_pattern(pattern_id="dup-001")
        r1 = check_compliance(file_path="a.py", content_preview="", pattern=pattern)
        r2 = check_compliance(file_path="b.py", content_preview="", pattern=pattern)
        assert r1 is not None and r2 is not None
        assert r1["pattern_id"] == r2["pattern_id"] == "dup-001"

    def test_same_status_multiple_patterns(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Multiple patterns with same status all produce advisories."""
        monkeypatch.setattr("pattern_enforcement._COOLDOWN_DIR", tmp_path)
        patterns = [
            _make_pattern(pattern_id=f"p-{i}", confidence=0.8 + i * 0.01)
            for i in range(5)
        ]
        with patch("pattern_enforcement.query_patterns", return_value=patterns):
            result = enforce_patterns(
                file_path="/test/file.py",
                session_id="sess-multi",
                language="python",
            )
        assert len(result["advisories"]) == 5

    # --- Boundary confidence values ---

    def test_confidence_zero(self) -> None:
        """Confidence of 0.0 produces a valid advisory."""
        pattern = _make_pattern(confidence=0.0)
        result = check_compliance(
            file_path="test.py", content_preview="", pattern=pattern
        )
        assert result is not None
        assert result["confidence"] == 0.0

    def test_confidence_one(self) -> None:
        """Confidence of 1.0 produces a valid advisory."""
        pattern = _make_pattern(confidence=1.0)
        result = check_compliance(
            file_path="test.py", content_preview="", pattern=pattern
        )
        assert result is not None
        assert result["confidence"] == 1.0

    def test_confidence_negative_clamped(self) -> None:
        """Negative confidence is accepted by check_compliance (clamping is in query_patterns)."""
        pattern = _make_pattern(confidence=-0.5)
        result = check_compliance(
            file_path="test.py", content_preview="", pattern=pattern
        )
        assert result is not None
        assert result["confidence"] == -0.5  # check_compliance does not clamp

    # --- Missing or empty pattern fields ---

    def test_missing_id_returns_none(self) -> None:
        """Pattern without 'id' key returns None."""
        pattern = {"pattern_signature": "sig", "confidence": 0.9, "status": "validated"}
        result = check_compliance(
            file_path="test.py", content_preview="", pattern=pattern
        )
        assert result is None

    def test_empty_id_returns_none(self) -> None:
        """Pattern with empty string 'id' returns None."""
        pattern = _make_pattern(pattern_id="")
        result = check_compliance(
            file_path="test.py", content_preview="", pattern=pattern
        )
        assert result is None

    def test_missing_signature_returns_none(self) -> None:
        """Pattern without 'pattern_signature' key returns None."""
        pattern = {"id": "p-001", "confidence": 0.9, "status": "validated"}
        result = check_compliance(
            file_path="test.py", content_preview="", pattern=pattern
        )
        assert result is None

    def test_empty_signature_returns_none(self) -> None:
        """Pattern with empty string signature returns None."""
        pattern = _make_pattern(signature="")
        result = check_compliance(
            file_path="test.py", content_preview="", pattern=pattern
        )
        assert result is None

    def test_missing_confidence_defaults_to_zero(self) -> None:
        """Pattern without confidence key defaults to 0.0."""
        pattern = {
            "id": "p-001",
            "pattern_signature": "sig",
            "status": "validated",
        }
        result = check_compliance(
            file_path="test.py", content_preview="", pattern=pattern
        )
        assert result is not None
        assert result["confidence"] == 0.0

    def test_missing_domain_id_defaults_to_empty(self) -> None:
        """Pattern without domain_id key defaults to empty string."""
        pattern = {
            "id": "p-001",
            "pattern_signature": "sig",
            "confidence": 0.9,
            "status": "validated",
        }
        result = check_compliance(
            file_path="test.py", content_preview="", pattern=pattern
        )
        assert result is not None
        assert result["domain_id"] == ""

    def test_missing_status_defaults_to_unknown_and_filters(self) -> None:
        """Pattern without status defaults to 'unknown' and is filtered out."""
        pattern = {
            "id": "p-001",
            "pattern_signature": "sig",
            "confidence": 0.9,
        }
        result = check_compliance(
            file_path="test.py", content_preview="", pattern=pattern
        )
        assert result is None  # status != "validated"

    # --- Non-numeric and unusual confidence values ---

    def test_non_numeric_confidence_returns_none(self) -> None:
        """Non-numeric confidence value returns None instead of crashing."""
        pattern = _make_pattern(confidence="not-a-number")  # type: ignore[arg-type]
        result = check_compliance(
            file_path="test.py", content_preview="", pattern=pattern
        )
        assert result is None

    def test_none_confidence_returns_none(self) -> None:
        """None confidence value returns None (float(None) raises TypeError)."""
        pattern = _make_pattern(confidence=None)  # type: ignore[arg-type]
        result = check_compliance(
            file_path="test.py", content_preview="", pattern=pattern
        )
        assert result is None

    def test_boolean_confidence_converts_to_float(self) -> None:
        """Boolean confidence values are converted via float() (True -> 1.0)."""
        pattern = _make_pattern(confidence=True)  # type: ignore[arg-type]
        result = check_compliance(
            file_path="test.py", content_preview="", pattern=pattern
        )
        assert result is not None
        assert result["confidence"] == 1.0

    # --- Nested / complex pattern structures ---

    def test_pattern_with_nested_metadata_ignored(self) -> None:
        """Extra nested metadata in pattern is silently ignored."""
        pattern = _make_pattern(
            metadata={"created_by": "system", "version": 2},
            tags=["python", "naming"],
            rules=[{"type": "naming", "severity": "warning"}],
        )
        result = check_compliance(
            file_path="test.py", content_preview="", pattern=pattern
        )
        assert result is not None
        assert set(result.keys()) == _advisory_keys()

    # --- Empty pattern dict ---

    def test_empty_pattern_dict_returns_none(self) -> None:
        """Completely empty pattern dict returns None."""
        result = check_compliance(file_path="test.py", content_preview="", pattern={})
        assert result is None

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
            )
        assert isinstance(result["elapsed_ms"], float)
        assert result["elapsed_ms"] >= 0.0

    def test_patterns_queried_matches_input_count(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """patterns_queried reflects the number of patterns from the store."""
        monkeypatch.setattr("pattern_enforcement._COOLDOWN_DIR", tmp_path)
        patterns = [_make_pattern(pattern_id=f"p-{i}") for i in range(7)]
        with patch("pattern_enforcement.query_patterns", return_value=patterns):
            result = enforce_patterns(
                file_path="/test/file.py",
                session_id="sess-count",
                language="python",
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

    # --- Large number of advisories ---

    def test_many_patterns_produce_many_advisories(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A large number of patterns are all processed into advisories."""
        monkeypatch.setattr("pattern_enforcement._COOLDOWN_DIR", tmp_path)
        count = 50
        patterns = [
            _make_pattern(pattern_id=f"p-{i}", confidence=0.7 + (i % 30) * 0.01)
            for i in range(count)
        ]
        with patch("pattern_enforcement.query_patterns", return_value=patterns):
            result = enforce_patterns(
                file_path="/test/file.py",
                session_id="sess-many",
                language="python",
            )
        assert result["enforced"] is True
        assert len(result["advisories"]) == count
        assert result["patterns_queried"] == count
