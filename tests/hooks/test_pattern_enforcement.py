"""Unit tests for pattern enforcement hook module.

Tests the pattern enforcement advisory system (OMN-2263):
- Feature flag gating
- Session cooldown logic (TTL-based dict)
- Pattern store querying
- Structural eligibility filter (_is_eligible_pattern)
- Async compliance.evaluate emission (_emit_compliance_evaluate)
- End-to-end enforce_patterns flow
- CLI entry point
- Topic and registry registration

All tests run without network access or external services.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest  # noqa: TC002

# Ensure hooks lib is importable
_HOOKS_LIB = (
    Path(__file__).resolve().parent.parent.parent / "plugins" / "onex" / "hooks" / "lib"
)
if str(_HOOKS_LIB) not in sys.path:
    sys.path.insert(0, str(_HOOKS_LIB))


from pattern_enforcement import (
    _COOLDOWN_TTL_S,
    _cleanup_stale_cooldown_files,
    _cooldown_path,
    _emit_compliance_evaluate,
    _emit_pattern_enforcement_event,
    _get_intelligence_url,
    _is_eligible_pattern,
    _load_cooldown,
    _save_cooldown,
    enforce_patterns,
    is_enforcement_enabled,
    main,
    query_patterns,
)

# ---------------------------------------------------------------------------
# Feature flag tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIsEnforcementEnabled:
    """Tests for feature flag gating."""

    def test_disabled_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ENABLE_LOCAL_INFERENCE_PIPELINE", raising=False)
        monkeypatch.delenv("ENABLE_PATTERN_ENFORCEMENT", raising=False)
        assert is_enforcement_enabled() is False

    def test_enabled_when_both_flags_true(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ENABLE_LOCAL_INFERENCE_PIPELINE", "true")
        monkeypatch.setenv("ENABLE_PATTERN_ENFORCEMENT", "true")
        assert is_enforcement_enabled() is True

    def test_disabled_when_parent_flag_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ENABLE_LOCAL_INFERENCE_PIPELINE", raising=False)
        monkeypatch.setenv("ENABLE_PATTERN_ENFORCEMENT", "true")
        assert is_enforcement_enabled() is False

    def test_disabled_when_enforcement_flag_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ENABLE_LOCAL_INFERENCE_PIPELINE", "true")
        monkeypatch.delenv("ENABLE_PATTERN_ENFORCEMENT", raising=False)
        assert is_enforcement_enabled() is False

    def test_case_insensitive_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ENABLE_LOCAL_INFERENCE_PIPELINE", "True")
        monkeypatch.setenv("ENABLE_PATTERN_ENFORCEMENT", "TRUE")
        assert is_enforcement_enabled() is True

    def test_accepts_1_as_truthy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ENABLE_LOCAL_INFERENCE_PIPELINE", "1")
        monkeypatch.setenv("ENABLE_PATTERN_ENFORCEMENT", "1")
        assert is_enforcement_enabled() is True

    def test_accepts_yes_as_truthy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ENABLE_LOCAL_INFERENCE_PIPELINE", "yes")
        monkeypatch.setenv("ENABLE_PATTERN_ENFORCEMENT", "yes")
        assert is_enforcement_enabled() is True

    def test_false_string_is_falsy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ENABLE_LOCAL_INFERENCE_PIPELINE", "false")
        monkeypatch.setenv("ENABLE_PATTERN_ENFORCEMENT", "true")
        assert is_enforcement_enabled() is False


# ---------------------------------------------------------------------------
# Session cooldown tests (TTL-based dict[str, float])
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSessionCooldown:
    """Tests for session-scoped cooldown persistence (TTL-based dict format)."""

    def test_load_empty_cooldown(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Loading cooldown for new session returns empty dict."""
        monkeypatch.setattr("pattern_enforcement._COOLDOWN_DIR", tmp_path)
        monkeypatch.setattr("pattern_enforcement._last_cleanup", 0.0)
        result = _load_cooldown("session-abc")
        assert result == {}

    def test_save_and_load_roundtrip(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Saved pattern IDs can be loaded back as dict with timestamps."""
        monkeypatch.setattr("pattern_enforcement._COOLDOWN_DIR", tmp_path)
        monkeypatch.setattr("pattern_enforcement._last_cleanup", 0.0)
        now = time.time()
        cooldown = {"p1": now, "p2": now, "p3": now}
        _save_cooldown("session-abc", cooldown)
        result = _load_cooldown("session-abc")
        assert set(result.keys()) == {"p1", "p2", "p3"}
        assert all(isinstance(ts, float) for ts in result.values())

    def test_corrupt_file_returns_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Corrupt cooldown file returns empty dict instead of crashing."""
        monkeypatch.setattr("pattern_enforcement._COOLDOWN_DIR", tmp_path)
        monkeypatch.setattr("pattern_enforcement._last_cleanup", 0.0)
        # Write corrupt data
        path = _cooldown_path("session-xyz")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not valid json {{{{", encoding="utf-8")
        result = _load_cooldown("session-xyz")
        assert result == {}

    def test_cooldown_path_is_sanitized(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Session IDs with special chars are safely hashed in the path."""
        monkeypatch.setattr("pattern_enforcement._COOLDOWN_DIR", tmp_path)
        path = _cooldown_path("../../etc/passwd")
        # Should be under tmp_path, not escape it
        assert str(path).startswith(str(tmp_path))
        assert "passwd" not in str(path)

    def test_save_failure_is_silent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Save to non-writable path doesn't raise."""
        monkeypatch.setattr(
            "pattern_enforcement._COOLDOWN_DIR", Path("/nonexistent/readonly/path")
        )
        # Should not raise
        _save_cooldown("session-abc", {"p1": time.time()})

    def test_incremental_cooldown(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cooldown accumulates across multiple saves."""
        monkeypatch.setattr("pattern_enforcement._COOLDOWN_DIR", tmp_path)
        monkeypatch.setattr("pattern_enforcement._last_cleanup", 0.0)
        now = time.time()
        _save_cooldown("session-inc", {"p1": now})
        existing = _load_cooldown("session-inc")
        _save_cooldown("session-inc", {**existing, "p2": now})
        result = _load_cooldown("session-inc")
        assert "p1" in result
        assert "p2" in result

    def test_expired_entries_excluded_on_load(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Entries older than _COOLDOWN_TTL_S are excluded on load."""
        monkeypatch.setattr("pattern_enforcement._COOLDOWN_DIR", tmp_path)
        monkeypatch.setattr("pattern_enforcement._last_cleanup", 0.0)
        now = time.time()
        old_ts = now - (_COOLDOWN_TTL_S + 10)  # expired
        cooldown = {"p-fresh": now, "p-stale": old_ts}
        _save_cooldown("session-ttl", cooldown)
        result = _load_cooldown("session-ttl")
        assert "p-fresh" in result
        assert "p-stale" not in result

    def test_legacy_list_format_discarded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Old list-format cooldown files are discarded (not parsed as dict)."""
        monkeypatch.setattr("pattern_enforcement._COOLDOWN_DIR", tmp_path)
        monkeypatch.setattr("pattern_enforcement._last_cleanup", 0.0)
        path = _cooldown_path("session-legacy")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('["p1", "p2", "p3"]', encoding="utf-8")
        result = _load_cooldown("session-legacy")
        assert result == {}


# ---------------------------------------------------------------------------
# Stale cooldown file cleanup tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCleanupStaleCooldownFiles:
    """Tests for _cleanup_stale_cooldown_files() housekeeping."""

    def test_removes_stale_keeps_fresh(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Files older than 24h are removed; recent files are kept."""
        monkeypatch.setattr("pattern_enforcement._COOLDOWN_DIR", tmp_path)

        stale_file = tmp_path / "stale.json"
        fresh_file = tmp_path / "fresh.json"
        stale_file.write_text('{"p-old": 0}', encoding="utf-8")
        fresh_file.write_text('{"p-new": 0}', encoding="utf-8")

        # Set stale file mtime to 25 hours ago
        stale_mtime = time.time() - (25 * 3600)
        os.utime(stale_file, (stale_mtime, stale_mtime))

        _cleanup_stale_cooldown_files()

        assert not stale_file.exists(), "stale file should have been removed"
        assert fresh_file.exists(), "fresh file should have been kept"

    def test_nonexistent_directory_does_not_crash(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Calling cleanup when cooldown directory doesn't exist is a no-op."""
        monkeypatch.setattr(
            "pattern_enforcement._COOLDOWN_DIR", tmp_path / "does-not-exist"
        )
        # Should return without error
        _cleanup_stale_cooldown_files()

    def test_cleanup_throttled_in_load_cooldown(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cleanup is skipped when called within the 5-minute throttle window."""
        monkeypatch.setattr("pattern_enforcement._COOLDOWN_DIR", tmp_path)

        stale_file = tmp_path / "stale.json"
        stale_file.write_text('{"old": 0}', encoding="utf-8")
        stale_mtime = time.time() - (25 * 3600)
        os.utime(stale_file, (stale_mtime, stale_mtime))

        # Simulate that cleanup ran very recently (within throttle window)
        monkeypatch.setattr("pattern_enforcement._last_cleanup", time.time())

        _load_cooldown("session-throttle")

        # Stale file should still exist because cleanup was throttled
        assert stale_file.exists(), "cleanup should have been throttled"

    def test_cleanup_runs_after_throttle_expires(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cleanup runs when the 5-minute throttle window has elapsed."""
        monkeypatch.setattr("pattern_enforcement._COOLDOWN_DIR", tmp_path)

        stale_file = tmp_path / "stale.json"
        stale_file.write_text('{"old": 0}', encoding="utf-8")
        stale_mtime = time.time() - (25 * 3600)
        os.utime(stale_file, (stale_mtime, stale_mtime))

        # Simulate that cleanup ran more than 5 minutes ago
        monkeypatch.setattr("pattern_enforcement._last_cleanup", time.time() - 301)

        _load_cooldown("session-expired-throttle")

        # Stale file should be cleaned up
        assert not stale_file.exists(), "cleanup should have run after throttle expired"


# ---------------------------------------------------------------------------
# Pattern query tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestQueryPatterns:
    """Tests for pattern store API querying."""

    def test_returns_empty_on_connection_error(self) -> None:
        """Network errors result in empty list, not exception."""
        # Use a port that won't be listening
        with patch.dict(os.environ, {"INTELLIGENCE_SERVICE_URL": "http://127.0.0.1:1"}):
            result = query_patterns(language="python", timeout_s=0.1)
        assert result == []

    def test_returns_empty_on_invalid_json(self) -> None:
        """Invalid JSON response returns empty list."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"not json"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch(
            "pattern_enforcement.urllib.request.urlopen", return_value=mock_resp
        ):
            result = query_patterns(language="python")
        assert result == []

    def test_returns_patterns_on_success(self) -> None:
        """Valid API response returns pattern list."""
        patterns = [
            {"id": "abc-123", "pattern_signature": "sig1", "confidence": 0.9},
            {"id": "def-456", "pattern_signature": "sig2", "confidence": 0.8},
        ]
        response_body = json.dumps({"patterns": patterns}).encode("utf-8")
        mock_resp = MagicMock()
        mock_resp.read.return_value = response_body
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch(
            "pattern_enforcement.urllib.request.urlopen", return_value=mock_resp
        ):
            result = query_patterns(language="python")
        assert len(result) == 2
        assert result[0]["id"] == "abc-123"

    def test_url_construction_with_language(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Language param is included in the query URL."""
        monkeypatch.setenv("INTELLIGENCE_SERVICE_URL", "http://test:8053")
        captured_url = []

        def mock_urlopen(req: Any, timeout: float = 0) -> MagicMock:
            captured_url.append(req.full_url if hasattr(req, "full_url") else str(req))
            raise urllib.error.URLError("test")

        with patch(
            "pattern_enforcement.urllib.request.urlopen", side_effect=mock_urlopen
        ):
            query_patterns(language="python", domain="code_quality")

        assert len(captured_url) == 1
        assert "language=python" in captured_url[0]
        assert "domain=code_quality" in captured_url[0]

    def test_url_falls_back_to_host_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When INTELLIGENCE_SERVICE_URL is not set, uses HOST + PORT."""
        monkeypatch.delenv("INTELLIGENCE_SERVICE_URL", raising=False)
        monkeypatch.setenv("INTELLIGENCE_SERVICE_HOST", "my-host")
        monkeypatch.setenv("INTELLIGENCE_SERVICE_PORT", "9999")
        captured_url = []

        def mock_urlopen(req: Any, timeout: float = 0) -> MagicMock:
            captured_url.append(req.full_url if hasattr(req, "full_url") else str(req))
            raise urllib.error.URLError("test")

        with patch(
            "pattern_enforcement.urllib.request.urlopen", side_effect=mock_urlopen
        ):
            query_patterns()

        assert len(captured_url) == 1
        assert "http://my-host:9999" in captured_url[0]

    def test_trailing_slash_stripped_from_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Trailing slashes on INTELLIGENCE_SERVICE_URL are stripped."""
        monkeypatch.setenv("INTELLIGENCE_SERVICE_URL", "http://test:8053/")
        result = _get_intelligence_url()
        assert result == "http://test:8053"
        # Multiple trailing slashes
        monkeypatch.setenv("INTELLIGENCE_SERVICE_URL", "http://test:8053///")
        result = _get_intelligence_url()
        assert not result.endswith("/")


# ---------------------------------------------------------------------------
# Structural eligibility filter tests (_is_eligible_pattern)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIsEligiblePattern:
    """Tests for structural eligibility filtering of patterns."""

    def test_valid_pattern_is_eligible(self) -> None:
        """Well-formed validated pattern passes eligibility."""
        pattern = {
            "id": "abc-123",
            "pattern_signature": "Use descriptive variable names",
            "domain_id": "code_quality",
            "confidence": 0.85,
            "status": "validated",
        }
        assert _is_eligible_pattern(pattern) is True

    def test_empty_pattern_id_is_ineligible(self) -> None:
        """Pattern without ID is ineligible."""
        pattern = {"pattern_signature": "sig", "confidence": 0.9, "status": "validated"}
        assert _is_eligible_pattern(pattern) is False

    def test_empty_signature_is_ineligible(self) -> None:
        """Pattern without signature is ineligible."""
        pattern = {
            "id": "abc-123",
            "pattern_signature": "",
            "confidence": 0.9,
            "status": "validated",
        }
        assert _is_eligible_pattern(pattern) is False

    def test_non_validated_status_is_ineligible(self) -> None:
        """Provisional patterns are ineligible."""
        pattern = {
            "id": "abc-123",
            "pattern_signature": "Use descriptive variable names",
            "domain_id": "code_quality",
            "confidence": 0.85,
            "status": "provisional",
        }
        assert _is_eligible_pattern(pattern) is False

    def test_draft_status_is_ineligible(self) -> None:
        """Draft patterns are ineligible."""
        pattern = {
            "id": "draft-001",
            "pattern_signature": "Avoid global mutable state",
            "domain_id": "code_quality",
            "confidence": 0.92,
            "status": "draft",
        }
        assert _is_eligible_pattern(pattern) is False

    def test_non_numeric_confidence_is_ineligible(self) -> None:
        """Non-numeric confidence is ineligible."""
        pattern = {
            "id": "bad-conf-001",
            "pattern_signature": "Use type hints",
            "domain_id": "code_quality",
            "confidence": "not-a-number",
            "status": "validated",
        }
        assert _is_eligible_pattern(pattern) is False

    def test_nan_confidence_is_ineligible(self) -> None:
        """NaN confidence is ineligible."""
        import math

        pattern = {
            "id": "nan-conf",
            "pattern_signature": "Some pattern",
            "domain_id": "code_quality",
            "confidence": math.nan,
            "status": "validated",
        }
        assert _is_eligible_pattern(pattern) is False

    def test_inf_confidence_is_ineligible(self) -> None:
        """Infinite confidence is ineligible."""
        import math

        pattern = {
            "id": "inf-conf",
            "pattern_signature": "Some pattern",
            "domain_id": "code_quality",
            "confidence": math.inf,
            "status": "validated",
        }
        assert _is_eligible_pattern(pattern) is False

    def test_exception_returns_false(self) -> None:
        """Malformed pattern input returns False, never raises."""
        assert _is_eligible_pattern(None) is False  # type: ignore[arg-type]
        assert _is_eligible_pattern("not a dict") is False  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Compliance evaluate emitter tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEmitComplianceEvaluate:
    """Tests for _emit_compliance_evaluate()."""

    def _make_patterns(self, count: int = 1) -> list[dict[str, Any]]:
        return [
            {
                "id": f"p-{i:03d}",
                "pattern_signature": f"sig-{i}",
                "domain_id": "code_quality",
                "confidence": 0.9,
                "status": "validated",
            }
            for i in range(count)
        ]

    def test_emits_with_correct_event_type(self) -> None:
        """emit_event is called with compliance.evaluate event type."""
        with patch("emit_client_wrapper.emit_event", return_value=True) as mock_emit:
            result = _emit_compliance_evaluate(
                file_path="/test/file.py",
                content="def foo(): pass\n",
                language="python",
                session_id="sess-001",
                content_sha256="abc123",
                patterns=self._make_patterns(1),
            )
        assert result is True
        mock_emit.assert_called_once()
        args, _ = mock_emit.call_args
        assert args[0] == "compliance.evaluate"

    def test_payload_has_required_keys(self) -> None:
        """Emitted payload contains all required fields."""
        with patch("emit_client_wrapper.emit_event", return_value=True) as mock_emit:
            _emit_compliance_evaluate(
                file_path="/test/file.py",
                content="def foo(): pass\n",
                language="python",
                session_id="sess-001",
                content_sha256="abc123",
                patterns=self._make_patterns(1),
            )
        payload = mock_emit.call_args[0][1]
        for key in (
            "correlation_id",
            "session_id",
            "source_path",
            "content",
            "content_sha256",
            "language",
            "applicable_patterns",
        ):
            assert key in payload, f"Missing key: {key}"

    def test_correlation_id_is_not_session_id(self) -> None:
        """correlation_id is a unique UUID per request, not session_id."""
        with patch("emit_client_wrapper.emit_event", return_value=True) as mock_emit:
            _emit_compliance_evaluate(
                file_path="/test/file.py",
                content="def foo(): pass\n",
                language="python",
                session_id="sess-001",
                content_sha256="abc123",
                patterns=self._make_patterns(1),
            )
        payload = mock_emit.call_args[0][1]
        assert payload["correlation_id"] != payload["session_id"]
        # Must be a valid UUID format
        import uuid

        uuid.UUID(str(payload["correlation_id"]))  # raises if invalid

    def test_two_calls_produce_different_correlation_ids(self) -> None:
        """Each call produces a unique correlation_id."""
        ids = []
        with patch("emit_client_wrapper.emit_event", return_value=True) as mock_emit:
            for _ in range(2):
                _emit_compliance_evaluate(
                    file_path="/test/file.py",
                    content="def foo(): pass\n",
                    language="python",
                    session_id="sess-001",
                    content_sha256="abc123",
                    patterns=self._make_patterns(1),
                )
                ids.append(mock_emit.call_args[0][1]["correlation_id"])
        assert ids[0] != ids[1]

    def test_empty_content_returns_false_no_emit(self) -> None:
        """Empty content string → no emit, returns False."""
        with patch("emit_client_wrapper.emit_event") as mock_emit:
            result = _emit_compliance_evaluate(
                file_path="/test/file.py",
                content="",
                language="python",
                session_id="sess-001",
                content_sha256="",
                patterns=self._make_patterns(1),
            )
        assert result is False
        mock_emit.assert_not_called()

    def test_whitespace_only_content_returns_false(self) -> None:
        """Whitespace-only content → no emit, returns False."""
        with patch("emit_client_wrapper.emit_event") as mock_emit:
            result = _emit_compliance_evaluate(
                file_path="/test/file.py",
                content="   \n\t  ",
                language="python",
                session_id="sess-001",
                content_sha256="",
                patterns=self._make_patterns(1),
            )
        assert result is False
        mock_emit.assert_not_called()

    def test_content_over_32kb_is_truncated(self) -> None:
        """Content exceeding 32KB is truncated before emit."""
        large_content = "x" * 40000  # 40KB
        with patch("emit_client_wrapper.emit_event", return_value=True) as mock_emit:
            result = _emit_compliance_evaluate(
                file_path="/test/file.py",
                content=large_content,
                language="python",
                session_id="sess-001",
                content_sha256="abc123",
                patterns=self._make_patterns(1),
            )
        assert result is True
        payload = mock_emit.call_args[0][1]
        assert len(payload["content"].encode("utf-8")) <= 32768

    def test_invalid_utf8_bytes_stripped(self) -> None:
        """Content with invalid UTF-8 sequences is stripped safely."""
        # Create content with invalid bytes then decode
        bad_bytes = b"valid text \xff\xfe more text"
        bad_str = bad_bytes.decode("utf-8", errors="replace")
        with patch("emit_client_wrapper.emit_event", return_value=True) as mock_emit:
            result = _emit_compliance_evaluate(
                file_path="/test/file.py",
                content=bad_str,
                language="python",
                session_id="sess-001",
                content_sha256="abc123",
                patterns=self._make_patterns(1),
            )
        assert result is True
        payload = mock_emit.call_args[0][1]
        # Must be valid UTF-8
        payload["content"].encode("utf-8")

    def test_exception_during_emit_returns_false(self) -> None:
        """Exceptions in emit_event are caught, returns False."""
        with patch("emit_client_wrapper.emit_event", side_effect=RuntimeError("boom")):
            result = _emit_compliance_evaluate(
                file_path="/test/file.py",
                content="def foo(): pass\n",
                language="python",
                session_id="sess-001",
                content_sha256="abc123",
                patterns=self._make_patterns(1),
            )
        assert result is False

    def test_applicable_patterns_structure(self) -> None:
        """applicable_patterns list has correct per-pattern fields."""
        patterns = [
            {
                "id": "p-001",
                "pattern_signature": "Use type hints",
                "domain_id": "python",
                "confidence": 0.9,
                "status": "validated",
            }
        ]
        with patch("emit_client_wrapper.emit_event", return_value=True) as mock_emit:
            _emit_compliance_evaluate(
                file_path="/test/file.py",
                content="def foo(): pass\n",
                language="python",
                session_id="sess-001",
                content_sha256="abc123",
                patterns=patterns,
            )
        payload = mock_emit.call_args[0][1]
        ap = payload["applicable_patterns"]
        assert len(ap) == 1
        assert ap[0]["pattern_id"] == "p-001"
        assert ap[0]["pattern_signature"] == "Use type hints"
        assert ap[0]["domain_id"] == "python"
        assert ap[0]["confidence"] == 0.9


# ---------------------------------------------------------------------------
# End-to-end enforce_patterns tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEnforcePatternsEmit:
    """Integration tests for the full enforcement pipeline (async-emit model)."""

    def _make_pattern(self, pid: str = "p-001") -> dict[str, Any]:
        return {
            "id": pid,
            "pattern_signature": f"sig-{pid}",
            "domain_id": "python",
            "confidence": 0.9,
            "status": "validated",
        }

    def test_returns_result_when_no_patterns(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No patterns from store results in empty advisories and no emit."""
        monkeypatch.setattr("pattern_enforcement._COOLDOWN_DIR", tmp_path)
        with patch("pattern_enforcement.query_patterns", return_value=[]):
            result = enforce_patterns(
                file_path="/test/file.py",
                session_id="session-1",
                language="python",
                emitted_at="2025-01-01T00:00:00+00:00",
            )
        assert result["enforced"] is True
        assert result["advisories"] == []
        assert result["patterns_queried"] == 0
        assert result["evaluation_submitted"] is False

    def test_advisories_always_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """advisories is always empty — results arrive asynchronously."""
        monkeypatch.setattr("pattern_enforcement._COOLDOWN_DIR", tmp_path)
        patterns = [self._make_pattern("p-001")]
        with (
            patch("pattern_enforcement.query_patterns", return_value=patterns),
            patch("pattern_enforcement._emit_compliance_evaluate", return_value=True),
        ):
            result = enforce_patterns(
                file_path="/test/file.py",
                session_id="session-2",
                language="python",
                content_preview="def foo(): pass\n",
                emitted_at="2025-01-01T00:00:00+00:00",
            )
        assert result["advisories"] == []
        assert result["evaluation_submitted"] is True

    def test_multiple_eligible_patterns_single_emit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Multiple eligible patterns trigger one emit with all in applicable_patterns."""
        monkeypatch.setattr("pattern_enforcement._COOLDOWN_DIR", tmp_path)
        patterns = [self._make_pattern("p-001"), self._make_pattern("p-002")]
        emitted_payloads: list[dict[str, Any]] = []

        def capture_emit(
            file_path: str,
            content: str,
            language: str,
            session_id: str,
            content_sha256: str,
            patterns: list[dict[str, Any]],
            correlation_id: str | None = None,
        ) -> bool:
            emitted_payloads.append({"patterns": patterns})
            return True

        with (
            patch("pattern_enforcement.query_patterns", return_value=patterns),
            patch(
                "pattern_enforcement._emit_compliance_evaluate",
                side_effect=capture_emit,
            ),
        ):
            result = enforce_patterns(
                file_path="/test/file.py",
                session_id="session-multi",
                language="python",
                content_preview="def foo(): pass\n",
                emitted_at="2025-01-01T00:00:00+00:00",
            )
        # Single emit
        assert len(emitted_payloads) == 1
        # Both patterns included
        assert len(emitted_payloads[0]["patterns"]) == 2
        assert result["evaluation_submitted"] is True

    def test_session_cooldown_skips_already_submitted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Patterns already submitted in this session are skipped on next call."""
        monkeypatch.setattr("pattern_enforcement._COOLDOWN_DIR", tmp_path)
        patterns = [self._make_pattern("p-001")]

        with (
            patch("pattern_enforcement.query_patterns", return_value=patterns),
            patch("pattern_enforcement._emit_compliance_evaluate", return_value=True),
        ):
            result1 = enforce_patterns(
                file_path="/test/file.py",
                session_id="session-3",
                language="python",
                content_preview="def foo(): pass\n",
                emitted_at="2025-01-01T00:00:00+00:00",
            )
        assert result1["evaluation_submitted"] is True
        assert result1["patterns_skipped_cooldown"] == 0

        with (
            patch("pattern_enforcement.query_patterns", return_value=patterns),
            patch(
                "pattern_enforcement._emit_compliance_evaluate", return_value=True
            ) as mock_emit,
        ):
            result2 = enforce_patterns(
                file_path="/test/other.py",
                session_id="session-3",
                language="python",
                content_preview="def bar(): pass\n",
                emitted_at="2025-01-01T00:00:00+00:00",
            )
        # Pattern already in cooldown, no emit
        mock_emit.assert_not_called()
        assert result2["patterns_skipped_cooldown"] == 1
        assert result2["evaluation_submitted"] is False

    def test_different_sessions_get_independent_cooldown(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Different sessions have independent cooldown state."""
        monkeypatch.setattr("pattern_enforcement._COOLDOWN_DIR", tmp_path)
        patterns = [self._make_pattern("p-001")]

        with (
            patch("pattern_enforcement.query_patterns", return_value=patterns),
            patch("pattern_enforcement._emit_compliance_evaluate", return_value=True),
        ):
            result_a = enforce_patterns(
                file_path="/test/file.py",
                session_id="session-A",
                language="python",
                content_preview="def foo(): pass\n",
                emitted_at="2025-01-01T00:00:00+00:00",
            )
            result_b = enforce_patterns(
                file_path="/test/file.py",
                session_id="session-B",
                language="python",
                content_preview="def foo(): pass\n",
                emitted_at="2025-01-01T00:00:00+00:00",
            )

        assert result_a["evaluation_submitted"] is True
        assert result_b["evaluation_submitted"] is True

    def test_cooldown_updated_for_all_submitted_patterns(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """All submitted pattern IDs are written to cooldown with timestamps."""
        monkeypatch.setattr("pattern_enforcement._COOLDOWN_DIR", tmp_path)
        monkeypatch.setattr("pattern_enforcement._last_cleanup", 0.0)
        patterns = [self._make_pattern("p-001"), self._make_pattern("p-002")]

        with (
            patch("pattern_enforcement.query_patterns", return_value=patterns),
            patch("pattern_enforcement._emit_compliance_evaluate", return_value=True),
        ):
            enforce_patterns(
                file_path="/test/file.py",
                session_id="session-cd",
                language="python",
                content_preview="def foo(): pass\n",
                emitted_at="2025-01-01T00:00:00+00:00",
            )

        cooldown = _load_cooldown("session-cd")
        assert "p-001" in cooldown
        assert "p-002" in cooldown
        assert isinstance(cooldown["p-001"], float)

    def test_cooldown_ttl_expiry_re_enables_pattern(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Patterns emitted >30min ago are re-eligible."""
        monkeypatch.setattr("pattern_enforcement._COOLDOWN_DIR", tmp_path)
        monkeypatch.setattr("pattern_enforcement._last_cleanup", 0.0)
        # Write an expired cooldown entry
        old_ts = time.time() - (_COOLDOWN_TTL_S + 10)
        _save_cooldown("session-ttl2", {"p-001": old_ts})

        patterns = [self._make_pattern("p-001")]
        with (
            patch("pattern_enforcement.query_patterns", return_value=patterns),
            patch("pattern_enforcement._emit_compliance_evaluate", return_value=True),
        ):
            result = enforce_patterns(
                file_path="/test/file.py",
                session_id="session-ttl2",
                language="python",
                content_preview="def foo(): pass\n",
                emitted_at="2025-01-01T00:00:00+00:00",
            )
        # Pattern was expired, so it should be re-submitted
        assert result["evaluation_submitted"] is True
        assert result["patterns_skipped_cooldown"] == 0

    def test_duplicate_pattern_ids_deduplicated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Duplicate pattern IDs in API response are deduplicated."""
        monkeypatch.setattr("pattern_enforcement._COOLDOWN_DIR", tmp_path)
        # API returns same pattern twice (defensive test for malformed API)
        patterns = [self._make_pattern("p-dup"), self._make_pattern("p-dup")]
        emitted_counts: list[int] = []

        def capture_emit(**kwargs: Any) -> bool:
            emitted_counts.append(len(kwargs["patterns"]))
            return True

        with (
            patch("pattern_enforcement.query_patterns", return_value=patterns),
            patch(
                "pattern_enforcement._emit_compliance_evaluate",
                side_effect=capture_emit,
            ),
        ):
            enforce_patterns(
                file_path="/test/file.py",
                session_id="session-dup",
                language="python",
                content_preview="def foo(): pass\n",
                emitted_at="2025-01-01T00:00:00+00:00",
            )
        assert len(emitted_counts) == 1
        assert emitted_counts[0] == 1  # deduplicated to one

    def test_exception_returns_safe_result(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unexpected exceptions return safe result, not crash."""
        monkeypatch.setattr("pattern_enforcement._COOLDOWN_DIR", tmp_path)
        with patch(
            "pattern_enforcement.query_patterns", side_effect=RuntimeError("boom")
        ):
            result = enforce_patterns(
                file_path="/test/file.py",
                session_id="session-err",
                language="python",
                emitted_at="2025-01-01T00:00:00+00:00",
            )
        assert result["enforced"] is False
        assert result["error"] == "boom"
        assert result["advisories"] == []
        assert result["evaluation_submitted"] is False

    def test_elapsed_ms_is_populated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Result includes elapsed_ms timing."""
        monkeypatch.setattr("pattern_enforcement._COOLDOWN_DIR", tmp_path)
        with patch("pattern_enforcement.query_patterns", return_value=[]):
            result = enforce_patterns(
                file_path="/test/file.py",
                session_id="session-time",
                language="python",
                emitted_at="2025-01-01T00:00:00+00:00",
            )
        assert result["elapsed_ms"] >= 0

    def test_empty_content_means_no_submit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Empty content_preview causes evaluation_submitted=False."""
        monkeypatch.setattr("pattern_enforcement._COOLDOWN_DIR", tmp_path)
        patterns = [self._make_pattern("p-001")]
        with patch("pattern_enforcement.query_patterns", return_value=patterns):
            result = enforce_patterns(
                file_path="/test/file.py",
                session_id="session-empty",
                language="python",
                content_preview="",  # empty
                emitted_at="2025-01-01T00:00:00+00:00",
            )
        assert result["evaluation_submitted"] is False

    def test_two_calls_different_correlation_ids(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two enforcement calls for different sessions produce different correlation_ids."""
        monkeypatch.setattr("pattern_enforcement._COOLDOWN_DIR", tmp_path)
        patterns = [self._make_pattern("p-001")]
        captured_cids: list[str] = []

        def capture_compliance_evaluate(**kwargs: Any) -> bool:
            cid = kwargs.get("correlation_id")
            assert cid is not None, (
                "_emit_compliance_evaluate must receive a correlation_id"
            )
            captured_cids.append(cid)
            return True

        with (
            patch("pattern_enforcement.query_patterns", return_value=patterns),
            patch(
                "pattern_enforcement._emit_compliance_evaluate",
                side_effect=capture_compliance_evaluate,
            ),
            patch("emit_client_wrapper.emit_event", return_value=True),
        ):
            enforce_patterns(
                file_path="/test/file.py",
                session_id="sess-cid-A",
                language="python",
                content_preview="def foo(): pass\n",
                emitted_at="2025-01-01T00:00:00+00:00",
            )
            enforce_patterns(
                file_path="/test/file.py",
                session_id="sess-cid-B",
                language="python",
                content_preview="def bar(): pass\n",
                emitted_at="2025-01-01T00:00:00+00:00",
            )

        assert len(captured_cids) == 2, (
            f"Expected 2 compliance.evaluate calls, got {len(captured_cids)}"
        )
        first_cid, second_cid = captured_cids
        assert first_cid is not None
        assert second_cid is not None
        assert first_cid != second_cid, (
            f"Two separate enforce_patterns calls must produce distinct correlation_ids, "
            f"got {first_cid!r} for both"
        )


# ---------------------------------------------------------------------------
# CLI main() tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMain:
    """Tests for the CLI entry point."""

    def test_outputs_json_when_disabled(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """When flags are off, outputs JSON with enforced=False."""
        monkeypatch.delenv("ENABLE_LOCAL_INFERENCE_PIPELINE", raising=False)
        monkeypatch.delenv("ENABLE_PATTERN_ENFORCEMENT", raising=False)

        from pattern_enforcement import main

        main()

        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["enforced"] is False
        assert "evaluation_submitted" in result

    def test_outputs_json_on_empty_stdin(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Empty stdin produces safe error output."""
        monkeypatch.setenv("ENABLE_LOCAL_INFERENCE_PIPELINE", "true")
        monkeypatch.setenv("ENABLE_PATTERN_ENFORCEMENT", "true")
        monkeypatch.setattr("sys.stdin", MagicMock(read=lambda: ""))

        from pattern_enforcement import main

        main()

        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["enforced"] is False
        assert result["error"] == "empty stdin"

    def test_outputs_json_on_invalid_stdin_json(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Invalid JSON on stdin produces safe error output, not a crash."""
        monkeypatch.setenv("ENABLE_LOCAL_INFERENCE_PIPELINE", "true")
        monkeypatch.setenv("ENABLE_PATTERN_ENFORCEMENT", "true")
        monkeypatch.setattr("sys.stdin", MagicMock(read=lambda: "not valid json {{{"))

        main()

        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["enforced"] is False
        assert result["error"] is not None
        assert "fatal:" in result["error"]

    def test_processes_valid_input(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ) -> None:
        """Valid JSON input runs enforcement and outputs result."""
        monkeypatch.setenv("ENABLE_LOCAL_INFERENCE_PIPELINE", "true")
        monkeypatch.setenv("ENABLE_PATTERN_ENFORCEMENT", "true")
        monkeypatch.setattr("pattern_enforcement._COOLDOWN_DIR", tmp_path)

        input_json = json.dumps(
            {
                "file_path": "/test/file.py",
                "session_id": "sess-cli",
                "language": "python",
                "content_preview": "def foo(): pass",
                "content_sha256": "abc123",
            }
        )
        monkeypatch.setattr("sys.stdin", MagicMock(read=lambda: input_json))

        with patch("pattern_enforcement.query_patterns", return_value=[]):
            main()

        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["enforced"] is True
        assert result["error"] is None
        assert "evaluation_submitted" in result


# ---------------------------------------------------------------------------
# Topic and registry registration tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTopicsCompliance:
    """Tests for compliance topic and event registry registration."""

    def test_compliance_evaluate_topic_exists(self) -> None:
        """COMPLIANCE_EVALUATE topic is defined in TopicBase."""
        from omniclaude.hooks.topics import TopicBase

        assert hasattr(TopicBase, "COMPLIANCE_EVALUATE")
        assert (
            TopicBase.COMPLIANCE_EVALUATE
            == "onex.cmd.omniintelligence.compliance-evaluate.v1"
        )

    def test_compliance_evaluated_topic_exists(self) -> None:
        """COMPLIANCE_EVALUATED topic is defined in TopicBase."""
        from omniclaude.hooks.topics import TopicBase

        assert hasattr(TopicBase, "COMPLIANCE_EVALUATED")
        assert (
            TopicBase.COMPLIANCE_EVALUATED
            == "onex.evt.omniintelligence.compliance-evaluated.v1"
        )

    def test_compliance_evaluate_registered_in_event_registry(self) -> None:
        """compliance.evaluate is registered in EVENT_REGISTRY."""
        from omniclaude.hooks.event_registry import EVENT_REGISTRY

        assert "compliance.evaluate" in EVENT_REGISTRY

    def test_compliance_evaluate_has_no_payload_transform(self) -> None:
        """compliance.evaluate has no payload transform — content must reach intelligence intact."""
        from omniclaude.hooks.event_registry import EVENT_REGISTRY

        reg = EVENT_REGISTRY["compliance.evaluate"]
        for rule in reg.fan_out:
            assert rule.transform is None, (
                f"compliance.evaluate must not have a transform (content must not be "
                f"stripped by daemon layer), but rule {rule.description!r} has one"
            )

    def test_compliance_evaluate_in_supported_event_types(self) -> None:
        """compliance.evaluate is in emit_client_wrapper.SUPPORTED_EVENT_TYPES."""
        from emit_client_wrapper import SUPPORTED_EVENT_TYPES

        assert "compliance.evaluate" in SUPPORTED_EVENT_TYPES

    def test_compliance_evaluate_routes_to_cmd_topic(self) -> None:
        """compliance.evaluate routes to the cmd (access-restricted) topic."""
        from omniclaude.hooks.event_registry import EVENT_REGISTRY
        from omniclaude.hooks.topics import TopicBase

        reg = EVENT_REGISTRY["compliance.evaluate"]
        topics = [rule.topic_base for rule in reg.fan_out]
        assert TopicBase.COMPLIANCE_EVALUATE in topics
        # Must route to cmd topic (access-restricted), not evt (observability)
        for topic in topics:
            assert topic.startswith("onex.cmd."), (
                f"compliance.evaluate must only route to cmd topics, got: {topic}"
            )

    def test_pattern_enforcement_topic_exists(self) -> None:
        """PATTERN_ENFORCEMENT topic is defined in TopicBase at the canonical wire address."""
        from omniclaude.hooks.topics import TopicBase

        assert hasattr(TopicBase, "PATTERN_ENFORCEMENT")
        assert (
            TopicBase.PATTERN_ENFORCEMENT
            == "onex.evt.omniclaude.pattern-enforcement.v1"
        )

    def test_pattern_enforcement_registered_in_event_registry(self) -> None:
        """pattern.enforcement is registered in EVENT_REGISTRY."""
        from omniclaude.hooks.event_registry import EVENT_REGISTRY

        assert "pattern.enforcement" in EVENT_REGISTRY

    def test_pattern_enforcement_has_no_payload_transform(self) -> None:
        """pattern.enforcement has no payload transform — metadata is safe for observability."""
        from omniclaude.hooks.event_registry import EVENT_REGISTRY

        reg = EVENT_REGISTRY["pattern.enforcement"]
        for rule in reg.fan_out:
            assert rule.transform is None, (
                f"pattern.enforcement must not have a transform, but rule "
                f"{rule.description!r} has one"
            )

    def test_pattern_enforcement_in_supported_event_types(self) -> None:
        """pattern.enforcement is in emit_client_wrapper.SUPPORTED_EVENT_TYPES."""
        from emit_client_wrapper import SUPPORTED_EVENT_TYPES

        assert "pattern.enforcement" in SUPPORTED_EVENT_TYPES

    def test_pattern_enforcement_routes_to_evt_topic(self) -> None:
        """pattern.enforcement routes to the evt (observability) topic — not cmd."""
        from omniclaude.hooks.event_registry import EVENT_REGISTRY
        from omniclaude.hooks.topics import TopicBase

        reg = EVENT_REGISTRY["pattern.enforcement"]
        topics = [rule.topic_base for rule in reg.fan_out]
        assert TopicBase.PATTERN_ENFORCEMENT in topics
        # Must route to evt topic (observability), not cmd (restricted)
        for topic in topics:
            assert topic.startswith("onex.evt."), (
                f"pattern.enforcement must only route to evt topics, got: {topic}"
            )

    def test_pattern_enforcement_required_fields(self) -> None:
        """pattern.enforcement requires the fields expected by omnidash."""
        from omniclaude.hooks.event_registry import EVENT_REGISTRY

        reg = EVENT_REGISTRY["pattern.enforcement"]
        required = set(reg.required_fields)
        # Fields consumed by omnidash read-model-consumer.ts projectEnforcementEvent()
        expected = {
            "correlation_id",
            "timestamp",
            "language",
            "domain",
            "pattern_name",
            "outcome",
        }
        assert expected.issubset(required), (
            f"Missing required fields: {expected - required}"
        )


# ---------------------------------------------------------------------------
# _emit_pattern_enforcement_event tests (OMN-2442)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEmitPatternEnforcementEvent:
    """Tests for _emit_pattern_enforcement_event — canonical evt topic emission."""

    def _make_pattern(self, pid: str, domain: str = "python") -> dict[str, Any]:
        return {
            "id": pid,
            "pattern_signature": f"sig-{pid}",
            "domain_id": domain,
            "confidence": 0.85,
            "status": "validated",
        }

    def test_emits_one_event_per_pattern(self) -> None:
        """Each eligible pattern produces one emission call."""
        import sys as _sys

        patterns = [self._make_pattern("p-001"), self._make_pattern("p-002")]
        captured: list[dict[str, Any]] = []

        def record_emit(event_type: str, payload: dict[str, Any]) -> bool:
            captured.append({"event_type": event_type, "payload": payload})
            return True

        mock_module = MagicMock()
        mock_module.emit_event = record_emit
        with patch.dict(_sys.modules, {"emit_client_wrapper": mock_module}):
            count = _emit_pattern_enforcement_event(
                session_id="sess-emit-test",
                correlation_id="corr-001",
                language="python",
                patterns=patterns,
                file_path="/some/repo/file.py",
                emitted_at="2026-01-01T00:00:00+00:00",
            )

        assert count == 2
        assert len(captured) == 2
        for call in captured:
            assert call["event_type"] == "pattern.enforcement"

    def test_payload_fields_match_omnidash_schema(self) -> None:
        """Emitted payload contains all fields expected by PatternEnforcementEvent."""
        pattern = self._make_pattern("p-003", domain="api")
        captured: list[dict[str, Any]] = []

        def record_emit(event_type: str, payload: dict[str, Any]) -> bool:
            captured.append(payload)
            return True

        import sys as _sys

        mock_module = MagicMock()
        mock_module.emit_event = record_emit
        with patch.dict(_sys.modules, {"emit_client_wrapper": mock_module}):
            _emit_pattern_enforcement_event(
                session_id="sess-schema-test",
                correlation_id="corr-schema",
                language="python",
                patterns=[pattern],
                file_path="/workspace/myrepo/src/api.py",
                emitted_at="2026-01-01T00:00:00+00:00",
            )

        assert len(captured) == 1
        payload = captured[0]

        # Required fields per PatternEnforcementEvent in omnidash
        assert "timestamp" in payload
        assert "correlation_id" in payload
        assert payload["correlation_id"] == "corr-schema"
        assert "session_id" in payload
        assert payload["session_id"] == "sess-schema-test"
        assert "language" in payload
        assert payload["language"] == "python"
        assert "domain" in payload
        assert payload["domain"] == "api"
        assert "pattern_name" in payload
        assert payload["pattern_name"] == "sig-p-003"
        assert "outcome" in payload
        assert payload["outcome"] == "hit"
        assert "confidence" in payload
        assert payload["confidence"] == 0.85
        assert "pattern_lifecycle_state" in payload
        assert payload["pattern_lifecycle_state"] == "validated"
        assert "pattern_id" in payload
        assert payload["pattern_id"] == "p-003"
        assert "repo" in payload

    def test_outcome_is_always_hit(self) -> None:
        """outcome field is always 'hit' — violations are resolved asynchronously."""
        captured: list[dict[str, Any]] = []

        def record_emit(event_type: str, payload: dict[str, Any]) -> bool:
            captured.append(payload)
            return True

        import sys as _sys

        mock_module = MagicMock()
        mock_module.emit_event = record_emit
        with patch.dict(_sys.modules, {"emit_client_wrapper": mock_module}):
            _emit_pattern_enforcement_event(
                session_id="sess-outcome",
                correlation_id="corr-outcome",
                language="typescript",
                patterns=[self._make_pattern("p-ts-001")],
                file_path="/repo/file.ts",
                emitted_at="2026-01-01T00:00:00+00:00",
            )

        assert captured[0]["outcome"] == "hit"

    def test_returns_zero_on_emit_failure(self) -> None:
        """Returns 0 when all emit calls fail."""
        import sys as _sys

        mock_module = MagicMock()
        mock_module.emit_event = MagicMock(return_value=False)
        with patch.dict(_sys.modules, {"emit_client_wrapper": mock_module}):
            count = _emit_pattern_enforcement_event(
                session_id="sess-fail",
                correlation_id="corr-fail",
                language="python",
                patterns=[self._make_pattern("p-fail")],
                file_path="/some/file.py",
                emitted_at="2026-01-01T00:00:00+00:00",
            )
        assert count == 0

    def test_returns_zero_on_import_error(self) -> None:
        """Returns 0 gracefully when emit_client_wrapper is unavailable."""
        import sys as _sys

        with patch.dict(_sys.modules, {"emit_client_wrapper": None}):
            count = _emit_pattern_enforcement_event(
                session_id="sess-import-err",
                correlation_id="corr-import-err",
                language="python",
                patterns=[self._make_pattern("p-import-err")],
                file_path="/file.py",
                emitted_at="2026-01-01T00:00:00+00:00",
            )
        assert count == 0

    def test_empty_patterns_returns_zero(self) -> None:
        """Empty pattern list emits nothing."""
        import sys as _sys

        mock_module = MagicMock()
        mock_module.emit_event = MagicMock(return_value=True)
        with patch.dict(_sys.modules, {"emit_client_wrapper": mock_module}):
            count = _emit_pattern_enforcement_event(
                session_id="sess-empty",
                correlation_id="corr-empty",
                language="python",
                patterns=[],
                file_path="/file.py",
                emitted_at="2026-01-01T00:00:00+00:00",
            )
        assert count == 0
        mock_module.emit_event.assert_not_called()

    def test_repo_derived_from_file_path(self) -> None:
        """repo field falls back to the penultimate path component when no repo marker is found.

        The path /workspace/omniclaude4/module.py is synthetic (does not exist on disk),
        so the marker-walk (looking for .git or pyproject.toml) exhausts without finding
        a match and falls back to the penultimate component "omniclaude4".
        """
        captured: list[dict[str, Any]] = []

        def record_emit(event_type: str, payload: dict[str, Any]) -> bool:
            captured.append(payload)
            return True

        import sys as _sys

        mock_module = MagicMock()
        mock_module.emit_event = record_emit
        with patch.dict(_sys.modules, {"emit_client_wrapper": mock_module}):
            _emit_pattern_enforcement_event(
                session_id="sess-repo",
                correlation_id="corr-repo",
                language="python",
                patterns=[self._make_pattern("p-repo")],
                file_path="/workspace/omniclaude4/module.py",
                emitted_at="2026-01-01T00:00:00+00:00",
            )

        assert captured[0]["repo"] == "omniclaude4"

    def test_repo_derived_from_nested_file_path_with_marker(
        self, tmp_path: Path
    ) -> None:
        """repo is derived from the git-root directory name for nested paths.

        When a file lives deep in a repo (e.g. <root>/src/module.py), the old
        penultimate-component approach returned "src" instead of the repo name.
        The fixed implementation walks up the directory tree looking for a .git
        or pyproject.toml marker and uses the containing directory's name.

        This test creates a real temporary directory tree with a pyproject.toml
        marker so the marker-walk finds the correct root.
        """
        # Create a realistic nested layout:  <tmp>/omniclaude4/src/module.py
        # with pyproject.toml at the repo root so the walker finds it.
        repo_root = tmp_path / "omniclaude4"
        src_dir = repo_root / "src"
        src_dir.mkdir(parents=True)
        (repo_root / "pyproject.toml").write_text("[project]\nname = 'omniclaude4'\n")
        nested_file = src_dir / "module.py"
        nested_file.write_text("# placeholder\n")

        captured: list[dict[str, Any]] = []

        def record_emit(event_type: str, payload: dict[str, Any]) -> bool:
            captured.append(payload)
            return True

        import sys as _sys

        mock_module = MagicMock()
        mock_module.emit_event = record_emit
        with patch.dict(_sys.modules, {"emit_client_wrapper": mock_module}):
            _emit_pattern_enforcement_event(
                session_id="sess-nested-repo",
                correlation_id="corr-nested",
                language="python",
                patterns=[self._make_pattern("p-nested")],
                file_path=str(nested_file),
                emitted_at="2026-01-01T00:00:00+00:00",
            )

        # The marker walk should resolve to the repo root directory name,
        # not the intermediate "src" directory.
        assert captured[0]["repo"] == "omniclaude4", (
            f"Expected repo='omniclaude4' (marker-walk result) but got "
            f"repo={captured[0]['repo']!r}. The penultimate component 'src' "
            "would indicate the old buggy behaviour is still active."
        )

    def test_repo_fallback_for_path_without_marker(self) -> None:
        """When no .git or pyproject.toml marker is found, falls back to penultimate component.

        Synthetic or test-only paths that don't exist on the real filesystem
        will exhaust the marker walk and use the penultimate path component as
        the repo identifier.  This preserves the existing best-effort behaviour
        for shallow paths like /workspace/myrepo/file.py (→ "myrepo").
        """
        captured: list[dict[str, Any]] = []

        def record_emit(event_type: str, payload: dict[str, Any]) -> bool:
            captured.append(payload)
            return True

        import sys as _sys

        mock_module = MagicMock()
        mock_module.emit_event = record_emit
        with patch.dict(_sys.modules, {"emit_client_wrapper": mock_module}):
            _emit_pattern_enforcement_event(
                session_id="sess-fallback",
                correlation_id="corr-fallback",
                language="python",
                patterns=[self._make_pattern("p-fallback")],
                # Path that doesn't exist on disk — walk exhausts, falls back
                # to penultimate component "myrepo".
                file_path="/nonexistent/myrepo/file.py",
                emitted_at="2026-01-01T00:00:00+00:00",
            )

        # Fallback: penultimate component is "myrepo" for this shallow path.
        assert captured[0]["repo"] == "myrepo", (
            f"Expected fallback repo='myrepo' (penultimate component) but got "
            f"repo={captured[0]['repo']!r}."
        )

    def test_enforcement_emits_pattern_enforcement_event_end_to_end(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """enforce_patterns() triggers _emit_pattern_enforcement_event for eligible patterns."""
        monkeypatch.setattr("pattern_enforcement._COOLDOWN_DIR", tmp_path)
        patterns = [
            {
                "id": "p-e2e-001",
                "pattern_signature": "sig-e2e",
                "domain_id": "validation",
                "confidence": 0.9,
                "status": "validated",
            }
        ]
        enforcement_events: list[dict[str, Any]] = []
        compliance_calls: list[dict[str, Any]] = []

        def capture_enforcement_emit(
            *,
            session_id: str,
            correlation_id: str,
            language: str,
            patterns: list[dict[str, Any]],
            file_path: str,
            emitted_at: str,
        ) -> int:
            enforcement_events.append(
                {
                    "session_id": session_id,
                    "correlation_id": correlation_id,
                    "language": language,
                    "patterns": patterns,
                    "file_path": file_path,
                    "emitted_at": emitted_at,
                }
            )
            return len(patterns)

        def capture_compliance_emit(**kwargs: Any) -> bool:
            compliance_calls.append(kwargs)
            return True

        with (
            patch("pattern_enforcement.query_patterns", return_value=patterns),
            patch(
                "pattern_enforcement._emit_compliance_evaluate",
                side_effect=capture_compliance_emit,
            ),
            patch(
                "pattern_enforcement._emit_pattern_enforcement_event",
                side_effect=capture_enforcement_emit,
            ),
        ):
            result = enforce_patterns(
                file_path="/test/repo/file.py",
                session_id="sess-e2e",
                language="python",
                content_preview="def foo(): pass\n",
                emitted_at="2026-01-01T00:00:00+00:00",
            )

        assert result["evaluation_submitted"] is True
        assert len(enforcement_events) == 1
        call = enforcement_events[0]
        assert call["session_id"] == "sess-e2e"
        assert call["language"] == "python"
        assert call["file_path"] == "/test/repo/file.py"
        assert len(call["patterns"]) == 1
        assert call["emitted_at"] == "2026-01-01T00:00:00+00:00", (
            f"emitted_at must be forwarded unchanged to _emit_pattern_enforcement_event, "
            f"got {call['emitted_at']!r}"
        )

        # Verify shared correlation_id: both events must carry the same ID for omnidash JOINs
        assert len(compliance_calls) == 1
        compliance_correlation_id = compliance_calls[0].get("correlation_id")
        enforcement_correlation_id = enforcement_events[0]["correlation_id"]
        assert compliance_correlation_id == enforcement_correlation_id, (
            f"compliance.evaluate correlation_id {compliance_correlation_id!r} must match "
            f"pattern.enforcement correlation_id {enforcement_correlation_id!r}"
        )

    def test_enforcement_emits_observability_even_when_compliance_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_emit_pattern_enforcement_event fires even when _emit_compliance_evaluate returns False."""
        monkeypatch.setattr("pattern_enforcement._COOLDOWN_DIR", tmp_path)
        patterns = [
            {
                "id": "p-fail-001",
                "pattern_signature": "sig-fail",
                "domain_id": "python",
                "confidence": 0.9,
                "status": "validated",
            }
        ]
        enforcement_events: list[dict[str, Any]] = []

        def capture_enforcement_emit(
            *,
            session_id: str,
            correlation_id: str,
            language: str,
            patterns: list[dict[str, Any]],
            file_path: str,
            emitted_at: str,
        ) -> int:
            enforcement_events.append({"session_id": session_id})
            return len(patterns)

        with (
            patch("pattern_enforcement.query_patterns", return_value=patterns),
            patch(
                "pattern_enforcement._emit_compliance_evaluate", return_value=False
            ),  # Simulate daemon down
            patch(
                "pattern_enforcement._emit_pattern_enforcement_event",
                side_effect=capture_enforcement_emit,
            ),
        ):
            result = enforce_patterns(
                file_path="/test/repo/file.py",
                session_id="sess-compliance-fail",
                language="python",
                content_preview="def foo(): pass\n",
                emitted_at="2026-01-01T00:00:00+00:00",
            )

        # evaluation_submitted is False (compliance evaluate failed)
        assert result["evaluation_submitted"] is False
        # But observability event still fires
        assert len(enforcement_events) == 1
        assert enforcement_events[0]["session_id"] == "sess-compliance-fail"
