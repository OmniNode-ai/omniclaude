"""Unit tests for pattern enforcement hook module.

Tests the pattern enforcement advisory system (OMN-2263):
- Feature flag gating
- Session cooldown logic
- Pattern store querying
- Compliance checking
- End-to-end enforce_patterns flow
- CLI entry point

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
    _cleanup_stale_cooldown_files,
    _cooldown_path,
    _get_intelligence_url,
    _load_cooldown,
    _save_cooldown,
    check_compliance,
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
# Session cooldown tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSessionCooldown:
    """Tests for session-scoped cooldown persistence."""

    def test_load_empty_cooldown(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Loading cooldown for new session returns empty set."""
        monkeypatch.setattr("pattern_enforcement._COOLDOWN_DIR", tmp_path)
        monkeypatch.setattr("pattern_enforcement._last_cleanup", 0.0)
        result = _load_cooldown("session-abc")
        assert result == set()

    def test_save_and_load_roundtrip(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Saved pattern IDs can be loaded back."""
        monkeypatch.setattr("pattern_enforcement._COOLDOWN_DIR", tmp_path)
        monkeypatch.setattr("pattern_enforcement._last_cleanup", 0.0)
        _save_cooldown("session-abc", {"p1", "p2", "p3"})
        result = _load_cooldown("session-abc")
        assert result == {"p1", "p2", "p3"}

    def test_corrupt_file_returns_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Corrupt cooldown file returns empty set instead of crashing."""
        monkeypatch.setattr("pattern_enforcement._COOLDOWN_DIR", tmp_path)
        monkeypatch.setattr("pattern_enforcement._last_cleanup", 0.0)
        # Write corrupt data
        path = _cooldown_path("session-xyz")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not valid json {{{{", encoding="utf-8")
        result = _load_cooldown("session-xyz")
        assert result == set()

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
        _save_cooldown("session-abc", {"p1"})

    def test_incremental_cooldown(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cooldown accumulates across multiple saves."""
        monkeypatch.setattr("pattern_enforcement._COOLDOWN_DIR", tmp_path)
        monkeypatch.setattr("pattern_enforcement._last_cleanup", 0.0)
        _save_cooldown("session-inc", {"p1"})
        existing = _load_cooldown("session-inc")
        _save_cooldown("session-inc", existing | {"p2"})
        result = _load_cooldown("session-inc")
        assert result == {"p1", "p2"}


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
        stale_file.write_text('["p-old"]', encoding="utf-8")
        fresh_file.write_text('["p-new"]', encoding="utf-8")

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
        stale_file.write_text('["old"]', encoding="utf-8")
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
        stale_file.write_text('["old"]', encoding="utf-8")
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
# Compliance check tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckCompliance:
    """Tests for compliance checking against individual patterns."""

    def test_returns_advisory_for_valid_pattern(self) -> None:
        """Valid pattern produces an advisory."""
        pattern = {
            "id": "abc-123",
            "pattern_signature": "Use descriptive variable names",
            "domain_id": "code_quality",
            "confidence": 0.85,
            "status": "validated",
        }
        result = check_compliance(
            file_path="/test/file.py",
            content_preview="x = 1\ny = 2\n",
            pattern=pattern,
        )
        assert result is not None
        assert result["pattern_id"] == "abc-123"
        assert result["confidence"] == 0.85
        assert result["status"] == "validated"

    def test_returns_none_for_empty_pattern_id(self) -> None:
        """Pattern without ID returns None."""
        pattern = {"pattern_signature": "sig", "confidence": 0.9}
        result = check_compliance(
            file_path="/test/file.py",
            content_preview="",
            pattern=pattern,
        )
        assert result is None

    def test_returns_none_for_empty_signature(self) -> None:
        """Pattern without signature returns None."""
        pattern = {"id": "abc-123", "pattern_signature": "", "confidence": 0.9}
        result = check_compliance(
            file_path="/test/file.py",
            content_preview="",
            pattern=pattern,
        )
        assert result is None

    def test_returns_none_for_non_validated_status(self) -> None:
        """Provisional patterns should not produce advisories."""
        pattern = {
            "id": "abc-123",
            "pattern_signature": "Use descriptive variable names",
            "domain_id": "code_quality",
            "confidence": 0.85,
            "status": "provisional",
        }
        result = check_compliance(
            file_path="test.py",
            content_preview="",
            pattern=pattern,
        )
        assert result is None

    def test_returns_none_for_draft_status(self) -> None:
        """Draft patterns are filtered out by the status != 'validated' guard."""
        pattern = {
            "id": "draft-001",
            "pattern_signature": "Avoid global mutable state",
            "domain_id": "code_quality",
            "confidence": 0.92,
            "status": "draft",
        }
        result = check_compliance(
            file_path="/test/file.py",
            content_preview="GLOBAL_LIST = []\n",
            pattern=pattern,
        )
        assert result is None

    def test_returns_none_for_non_numeric_confidence(self) -> None:
        """Non-numeric confidence value returns None instead of crashing."""
        pattern = {
            "id": "bad-conf-001",
            "pattern_signature": "Use type hints",
            "domain_id": "code_quality",
            "confidence": "not-a-number",
            "status": "validated",
        }
        result = check_compliance(
            file_path="/test/file.py",
            content_preview="x = 1\n",
            pattern=pattern,
        )
        assert result is None


# ---------------------------------------------------------------------------
# End-to-end enforce_patterns tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEnforcePatterns:
    """Integration tests for the full enforcement pipeline."""

    def test_returns_result_when_no_patterns(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No patterns from store results in empty advisories."""
        monkeypatch.setattr("pattern_enforcement._COOLDOWN_DIR", tmp_path)
        with patch("pattern_enforcement.query_patterns", return_value=[]):
            result = enforce_patterns(
                file_path="/test/file.py",
                session_id="session-1",
                language="python",
            )
        assert result["enforced"] is True
        assert result["advisories"] == []
        assert result["patterns_queried"] == 0

    def test_produces_advisories_for_matching_patterns(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Matching patterns produce advisories."""
        monkeypatch.setattr("pattern_enforcement._COOLDOWN_DIR", tmp_path)
        patterns = [
            {
                "id": "p-001",
                "pattern_signature": "Use type hints",
                "domain_id": "python",
                "confidence": 0.9,
                "status": "validated",
            },
        ]
        with patch("pattern_enforcement.query_patterns", return_value=patterns):
            result = enforce_patterns(
                file_path="/test/file.py",
                session_id="session-2",
                language="python",
            )
        assert result["enforced"] is True
        assert len(result["advisories"]) == 1
        assert result["advisories"][0]["pattern_id"] == "p-001"
        assert result["patterns_queried"] == 1

    def test_session_cooldown_skips_already_advised(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Patterns already advised in this session are skipped."""
        monkeypatch.setattr("pattern_enforcement._COOLDOWN_DIR", tmp_path)
        patterns = [
            {
                "id": "p-001",
                "pattern_signature": "Use type hints",
                "domain_id": "python",
                "confidence": 0.9,
                "status": "validated",
            },
        ]

        # First call: should get advisory
        with patch("pattern_enforcement.query_patterns", return_value=patterns):
            result1 = enforce_patterns(
                file_path="/test/file.py",
                session_id="session-3",
                language="python",
            )
        assert len(result1["advisories"]) == 1
        assert result1["patterns_skipped_cooldown"] == 0

        # Second call: same session, same pattern -> cooldown skips it
        with patch("pattern_enforcement.query_patterns", return_value=patterns):
            result2 = enforce_patterns(
                file_path="/test/other.py",
                session_id="session-3",
                language="python",
            )
        assert len(result2["advisories"]) == 0
        assert result2["patterns_skipped_cooldown"] == 1

    def test_different_sessions_get_independent_cooldown(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Different sessions have independent cooldown state."""
        monkeypatch.setattr("pattern_enforcement._COOLDOWN_DIR", tmp_path)
        patterns = [
            {
                "id": "p-001",
                "pattern_signature": "Use type hints",
                "domain_id": "python",
                "confidence": 0.9,
                "status": "validated",
            },
        ]

        with patch("pattern_enforcement.query_patterns", return_value=patterns):
            result_a = enforce_patterns(
                file_path="/test/file.py",
                session_id="session-A",
                language="python",
            )
            result_b = enforce_patterns(
                file_path="/test/file.py",
                session_id="session-B",
                language="python",
            )

        # Both sessions should get the advisory independently
        assert len(result_a["advisories"]) == 1
        assert len(result_b["advisories"]) == 1

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
            )
        assert result["enforced"] is False
        assert result["error"] == "boom"
        assert result["advisories"] == []

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
            )
        assert result["elapsed_ms"] >= 0


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
            }
        )
        monkeypatch.setattr("sys.stdin", MagicMock(read=lambda: input_json))

        with patch("pattern_enforcement.query_patterns", return_value=[]):
            main()

        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["enforced"] is True
        assert result["error"] is None
