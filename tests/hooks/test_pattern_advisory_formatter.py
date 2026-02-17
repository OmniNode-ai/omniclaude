"""Unit tests for pattern advisory formatter module (OMN-2269).

Tests the pattern violation context injection system:
- Advisory persistence (save/load/clear)
- Markdown formatting
- Staleness handling
- Deduplication
- CLI entry points
- Edge cases and error handling

All tests run without network access or external services.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Ensure hooks lib is importable
_HOOKS_LIB = (
    Path(__file__).resolve().parent.parent.parent / "plugins" / "onex" / "hooks" / "lib"
)
if str(_HOOKS_LIB) not in sys.path:
    sys.path.insert(0, str(_HOOKS_LIB))


from pattern_advisory_formatter import (
    _ADVISORY_HEADER,
    _MAX_ADVISORIES_PER_TURN,
    _advisory_path,
    cleanup_stale_files,
    format_advisories_markdown,
    get_advisory_context,
    load_and_clear_advisories,
    main,
    save_advisories,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_advisory(
    pattern_id: str = "p-001",
    signature: str = "Use type hints",
    confidence: float = 0.85,
    message: str = "Pattern 'Use type hints' (confidence: 0.85) may apply to this file.",
) -> dict[str, object]:
    """Create a test PatternAdvisory dict."""
    return {
        "pattern_id": pattern_id,
        "pattern_signature": signature,
        "domain_id": "code_quality",
        "confidence": confidence,
        "status": "validated",
        "message": message,
    }


# ---------------------------------------------------------------------------
# Advisory path tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAdvisoryPath:
    """Tests for advisory file path generation."""

    def test_path_is_sanitized(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Session IDs with special chars are safely hashed."""
        monkeypatch.setattr("pattern_advisory_formatter._ADVISORY_DIR", tmp_path)
        path = _advisory_path("../../etc/passwd")
        assert str(path).startswith(str(tmp_path))
        assert "passwd" not in str(path)

    def test_different_sessions_different_paths(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Different session IDs produce different file paths."""
        monkeypatch.setattr("pattern_advisory_formatter._ADVISORY_DIR", tmp_path)
        path_a = _advisory_path("session-A")
        path_b = _advisory_path("session-B")
        assert path_a != path_b

    def test_same_session_same_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Same session ID always produces the same file path."""
        monkeypatch.setattr("pattern_advisory_formatter._ADVISORY_DIR", tmp_path)
        path1 = _advisory_path("session-X")
        path2 = _advisory_path("session-X")
        assert path1 == path2


# ---------------------------------------------------------------------------
# Save/load roundtrip tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSaveAndLoadAdvisories:
    """Tests for advisory persistence."""

    def test_save_and_load_roundtrip(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Saved advisories can be loaded back."""
        monkeypatch.setattr("pattern_advisory_formatter._ADVISORY_DIR", tmp_path)
        advisories = [_make_advisory("p-001"), _make_advisory("p-002")]

        assert save_advisories("session-rt", advisories) is True
        loaded = load_and_clear_advisories("session-rt")

        assert len(loaded) == 2
        assert loaded[0]["pattern_id"] == "p-001"
        assert loaded[1]["pattern_id"] == "p-002"

    def test_load_clears_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Loading advisories clears the file (one-shot delivery)."""
        monkeypatch.setattr("pattern_advisory_formatter._ADVISORY_DIR", tmp_path)
        save_advisories("session-clr", [_make_advisory()])

        # First load returns data
        loaded1 = load_and_clear_advisories("session-clr")
        assert len(loaded1) == 1

        # Second load returns empty (file was cleared)
        loaded2 = load_and_clear_advisories("session-clr")
        assert loaded2 == []

    def test_empty_advisories_no_file_created(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Saving empty advisories does not create a file."""
        monkeypatch.setattr("pattern_advisory_formatter._ADVISORY_DIR", tmp_path)
        assert save_advisories("session-empty", []) is True
        path = _advisory_path("session-empty")
        assert not path.exists()

    def test_load_nonexistent_session(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Loading from nonexistent session returns empty list."""
        monkeypatch.setattr("pattern_advisory_formatter._ADVISORY_DIR", tmp_path)
        result = load_and_clear_advisories("session-nope")
        assert result == []

    def test_accumulation_across_saves(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Multiple saves accumulate advisories (multiple tool uses between prompts)."""
        monkeypatch.setattr("pattern_advisory_formatter._ADVISORY_DIR", tmp_path)
        save_advisories("session-acc", [_make_advisory("p-001")])
        save_advisories("session-acc", [_make_advisory("p-002")])

        loaded = load_and_clear_advisories("session-acc")
        assert len(loaded) == 2
        pattern_ids = {a["pattern_id"] for a in loaded}
        assert pattern_ids == {"p-001", "p-002"}

    def test_deduplication_by_pattern_id(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Duplicate pattern_ids are deduplicated across saves."""
        monkeypatch.setattr("pattern_advisory_formatter._ADVISORY_DIR", tmp_path)
        save_advisories("session-dup", [_make_advisory("p-001")])
        save_advisories("session-dup", [_make_advisory("p-001")])  # duplicate

        loaded = load_and_clear_advisories("session-dup")
        assert len(loaded) == 1
        assert loaded[0]["pattern_id"] == "p-001"

    def test_corrupt_file_returns_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Corrupt advisory file returns empty list and is cleaned up."""
        monkeypatch.setattr("pattern_advisory_formatter._ADVISORY_DIR", tmp_path)
        path = _advisory_path("session-corrupt")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not valid json {{{{", encoding="utf-8")

        result = load_and_clear_advisories("session-corrupt")
        assert result == []
        # Corrupt file should be cleaned up
        assert not path.exists()

    def test_stale_advisories_discarded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Advisories older than 1 hour are discarded."""
        monkeypatch.setattr("pattern_advisory_formatter._ADVISORY_DIR", tmp_path)
        path = _advisory_path("session-stale")
        path.parent.mkdir(parents=True, exist_ok=True)

        stale_data = {
            "advisories": [_make_advisory()],
            "written_at": time.time() - 3700,  # > 1 hour ago
        }
        path.write_text(json.dumps(stale_data), encoding="utf-8")

        result = load_and_clear_advisories("session-stale")
        assert result == []

    def test_different_sessions_independent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Different sessions have independent advisory files."""
        monkeypatch.setattr("pattern_advisory_formatter._ADVISORY_DIR", tmp_path)
        save_advisories("session-A", [_make_advisory("p-A")])
        save_advisories("session-B", [_make_advisory("p-B")])

        loaded_a = load_and_clear_advisories("session-A")
        loaded_b = load_and_clear_advisories("session-B")

        assert len(loaded_a) == 1
        assert loaded_a[0]["pattern_id"] == "p-A"
        assert len(loaded_b) == 1
        assert loaded_b[0]["pattern_id"] == "p-B"

    def test_save_to_nonwritable_path_returns_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Save to non-writable path returns False without raising."""
        monkeypatch.setattr(
            "pattern_advisory_formatter._ADVISORY_DIR",
            Path("/nonexistent/readonly/path"),
        )
        result = save_advisories("session-err", [_make_advisory()])
        assert result is False

    def test_max_advisories_capped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Load returns at most MAX_ADVISORIES_PER_TURN advisories."""
        monkeypatch.setattr("pattern_advisory_formatter._ADVISORY_DIR", tmp_path)
        # Save more than the max
        many = [_make_advisory(f"p-{i:03d}") for i in range(20)]
        save_advisories("session-cap", many)

        loaded = load_and_clear_advisories("session-cap")
        assert len(loaded) <= _MAX_ADVISORIES_PER_TURN


# ---------------------------------------------------------------------------
# Formatting tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFormatAdvisoriesMarkdown:
    """Tests for markdown formatting of advisories."""

    def test_empty_list_returns_empty_string(self) -> None:
        """No advisories produces empty string."""
        assert format_advisories_markdown([]) == ""

    def test_single_advisory_format(self) -> None:
        """Single advisory produces expected markdown format."""
        advisories = [_make_advisory()]
        result = format_advisories_markdown(advisories)

        assert result.startswith("## Pattern Advisory")
        assert "Use type hints" in result
        assert "85% confidence" in result
        assert "informational suggestions" in result

    def test_multiple_advisories(self) -> None:
        """Multiple advisories are all included."""
        advisories = [
            _make_advisory("p-001", "Use type hints", 0.85),
            _make_advisory("p-002", "Prefer dataclasses", 0.72),
        ]
        result = format_advisories_markdown(advisories)

        assert "Use type hints" in result
        assert "Prefer dataclasses" in result
        assert "85% confidence" in result
        assert "72% confidence" in result

    def test_long_signature_truncated(self) -> None:
        """Signatures longer than 80 chars are truncated."""
        long_sig = "A" * 100
        advisories = [_make_advisory("p-long", long_sig)]
        result = format_advisories_markdown(advisories)

        # Should contain truncated version with "..."
        assert "..." in result
        assert long_sig not in result

    def test_advisory_without_message(self) -> None:
        """Advisory without message still formats correctly."""
        advisory = _make_advisory()
        advisory["message"] = ""
        result = format_advisories_markdown([advisory])

        assert "Use type hints" in result
        assert "85% confidence" in result

    def test_header_present(self) -> None:
        """Output includes the advisory header."""
        result = format_advisories_markdown([_make_advisory()])
        assert _ADVISORY_HEADER in result

    def test_confidence_percentage_formatting(self) -> None:
        """Confidence is formatted as integer percentage."""
        advisory = _make_advisory(confidence=0.934)
        result = format_advisories_markdown([advisory])
        assert "93% confidence" in result

    def test_zero_confidence(self) -> None:
        """Zero confidence formats correctly."""
        advisory = _make_advisory(confidence=0.0)
        result = format_advisories_markdown([advisory])
        assert "0% confidence" in result

    def test_max_advisories_respected(self) -> None:
        """At most MAX_ADVISORIES_PER_TURN are formatted."""
        many = [_make_advisory(f"p-{i:03d}", f"Pattern {i}") for i in range(20)]
        result = format_advisories_markdown(many)

        # Count bullet points
        bullet_count = result.count("- **")
        assert bullet_count <= _MAX_ADVISORIES_PER_TURN


# ---------------------------------------------------------------------------
# get_advisory_context integration tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetAdvisoryContext:
    """Tests for the combined load + format entry point."""

    def test_returns_empty_for_no_session(self) -> None:
        """Empty session_id returns empty string."""
        assert get_advisory_context("") == ""

    def test_returns_empty_when_no_advisories(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No pending advisories returns empty string."""
        monkeypatch.setattr("pattern_advisory_formatter._ADVISORY_DIR", tmp_path)
        result = get_advisory_context("session-none")
        assert result == ""

    def test_returns_formatted_markdown(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pending advisories are returned as formatted markdown."""
        monkeypatch.setattr("pattern_advisory_formatter._ADVISORY_DIR", tmp_path)
        save_advisories("session-ctx", [_make_advisory()])

        result = get_advisory_context("session-ctx")

        assert "## Pattern Advisory" in result
        assert "Use type hints" in result

    def test_clears_after_read(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Advisories are cleared after first read."""
        monkeypatch.setattr("pattern_advisory_formatter._ADVISORY_DIR", tmp_path)
        save_advisories("session-once", [_make_advisory()])

        result1 = get_advisory_context("session-once")
        result2 = get_advisory_context("session-once")

        assert result1 != ""
        assert result2 == ""


# ---------------------------------------------------------------------------
# Cleanup tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCleanupStaleFiles:
    """Tests for stale file cleanup."""

    def test_removes_old_keeps_fresh(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Files older than 24h are removed; fresh files are kept."""
        monkeypatch.setattr("pattern_advisory_formatter._ADVISORY_DIR", tmp_path)

        stale = tmp_path / "stale.json"
        fresh = tmp_path / "fresh.json"
        stale.write_text("{}", encoding="utf-8")
        fresh.write_text("{}", encoding="utf-8")

        stale_mtime = time.time() - (25 * 3600)
        os.utime(stale, (stale_mtime, stale_mtime))

        cleanup_stale_files()

        assert not stale.exists()
        assert fresh.exists()

    def test_nonexistent_dir_no_crash(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cleanup with nonexistent directory is a no-op."""
        monkeypatch.setattr(
            "pattern_advisory_formatter._ADVISORY_DIR", tmp_path / "nope"
        )
        cleanup_stale_files()  # Should not raise


# ---------------------------------------------------------------------------
# CLI main() tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMain:
    """Tests for the CLI entry point."""

    def test_save_mode(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Save mode persists advisories from stdin."""
        monkeypatch.setattr("pattern_advisory_formatter._ADVISORY_DIR", tmp_path)
        monkeypatch.setattr("sys.argv", ["prog", "save"])

        input_data = json.dumps(
            {
                "session_id": "session-cli-save",
                "advisories": [_make_advisory()],
            }
        )
        monkeypatch.setattr("sys.stdin", MagicMock(read=lambda: input_data))

        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0

        # Verify it was saved
        loaded = load_and_clear_advisories("session-cli-save")
        assert len(loaded) == 1

    def test_load_mode(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Load mode outputs formatted markdown."""
        monkeypatch.setattr("pattern_advisory_formatter._ADVISORY_DIR", tmp_path)
        save_advisories("session-cli-load", [_make_advisory()])

        monkeypatch.setattr("sys.argv", ["prog", "load"])
        input_data = json.dumps({"session_id": "session-cli-load"})
        monkeypatch.setattr("sys.stdin", MagicMock(read=lambda: input_data))

        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0

        captured = capsys.readouterr()
        assert "## Pattern Advisory" in captured.out
        assert "Use type hints" in captured.out

    def test_load_empty_stdin(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Load mode with empty stdin outputs empty string."""
        monkeypatch.setattr("sys.argv", ["prog", "load"])
        monkeypatch.setattr("sys.stdin", MagicMock(read=lambda: ""))

        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0

        captured = capsys.readouterr()
        assert captured.out == "\n"  # print("") adds newline

    def test_no_args_exits_0(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """No arguments exits with code 0."""
        monkeypatch.setattr("sys.argv", ["prog"])

        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0

    def test_unknown_mode_exits_0(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Unknown mode exits with code 0 (never blocks)."""
        monkeypatch.setattr("sys.argv", ["prog", "bogus"])

        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0

    def test_cleanup_mode(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Cleanup mode removes stale files."""
        monkeypatch.setattr("pattern_advisory_formatter._ADVISORY_DIR", tmp_path)
        monkeypatch.setattr("sys.argv", ["prog", "cleanup"])

        stale = tmp_path / "stale.json"
        stale.write_text("{}", encoding="utf-8")
        stale_mtime = time.time() - (25 * 3600)
        os.utime(stale, (stale_mtime, stale_mtime))

        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0

        assert not stale.exists()
