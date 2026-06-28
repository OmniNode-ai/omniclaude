# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for validate_no_blocking_primitive_without_tests (OMN-13047).

Covers:
  - GREEN: no blocking primitive in diff
  - GREEN: blocking primitive with concurrent tests/ change
  - GREEN: suppressed via # concurrency-ok
  - RED:   blocking primitive without tests/ change (seek_to_end)
  - RED:   blocking primitive without tests/ change (KafkaConsumer)
  - RED:   blocking primitive without tests/ change (.poll()
  - GREEN: blocking primitive only in test files (not a source violation)
  - GREEN: blocking primitive in --- (removed) line (not a new introduction)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "validation"))

from validate_no_blocking_primitive_without_tests import (  # noqa: E402
    BLOCKING_PATTERNS,
    _has_blocking_pattern,
    _is_test_path,
    _parse_diff,
    main,
)

# ---------------------------------------------------------------------------
# Helper: build a minimal unified diff string
# ---------------------------------------------------------------------------


def _make_diff(
    filename: str,
    added_lines: list[str],
    also_add_test: bool = False,
) -> str:
    """Build a minimal ``git diff`` output for *filename*."""
    parts: list[str] = []

    # Source file hunk
    parts.append(f"diff --git a/{filename} b/{filename}")
    parts.append(f"--- a/{filename}")
    parts.append(f"+++ b/{filename}")
    parts.append("@@ -1,0 +1 @@")
    for line in added_lines:
        parts.append(f"+{line}")

    # Optional test file hunk
    if also_add_test:
        parts.append("diff --git a/tests/test_new.py b/tests/test_new.py")
        parts.append("--- a/tests/test_new.py")
        parts.append("+++ b/tests/test_new.py")
        parts.append("@@ -1,0 +1 @@")
        parts.append("+def test_ordering(): assert True")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Unit tests for low-level helpers
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHasBlockingPattern:
    def test_seek_to_end_detected(self) -> None:
        assert _has_blocking_pattern("    consumer.seek_to_end()")

    def test_kafka_consumer_detected(self) -> None:
        assert _has_blocking_pattern("from kafka import KafkaConsumer")

    def test_poll_detected(self) -> None:
        assert _has_blocking_pattern("    records = consumer.poll(timeout_ms=100)")

    def test_suppressed_seek_to_end(self) -> None:
        assert not _has_blocking_pattern("    consumer.seek_to_end()  # concurrency-ok")

    def test_suppressed_kafka_consumer(self) -> None:
        assert not _has_blocking_pattern(
            "from kafka import KafkaConsumer  # concurrency-ok"
        )

    def test_clean_line(self) -> None:
        assert not _has_blocking_pattern("    result = compute(x)")

    def test_poll_without_dot_not_flagged(self) -> None:
        # ``poll_timeout`` should NOT trigger the ``.poll(`` pattern.
        assert not _has_blocking_pattern("    poll_timeout = 100")


@pytest.mark.unit
class TestIsTestPath:
    def test_test_path_detected(self) -> None:
        assert _is_test_path("tests/unit/test_foo.py")

    def test_nested_test_path(self) -> None:
        assert _is_test_path("src/tests/test_bar.py")

    def test_non_test_path(self) -> None:
        assert not _is_test_path("src/omniclaude/hooks/consumer.py")

    def test_file_named_tests_no_slash(self) -> None:
        # Edge case: ``tests.py`` top-level — not a ``tests/`` subtree.
        assert not _is_test_path("src/tests.py")


# ---------------------------------------------------------------------------
# Integration tests for _parse_diff
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestParseDiffClean:
    def test_no_primitives_clean(self) -> None:
        diff = _make_diff("src/foo.py", ["    result = compute(x)"])
        violations, has_tests = _parse_diff(diff)
        assert violations == []
        assert not has_tests

    def test_removed_primitive_not_flagged(self) -> None:
        """Removed lines (starting with -) should not be flagged."""
        diff = (
            "diff --git a/src/foo.py b/src/foo.py\n"
            "--- a/src/foo.py\n"
            "+++ b/src/foo.py\n"
            "@@ -1,1 +0,0 @@\n"
            "-    consumer.seek_to_end()\n"
        )
        violations, _ = _parse_diff(diff)
        assert violations == []

    def test_primitive_in_test_file_not_a_violation(self) -> None:
        """Blocking primitive added only inside tests/ is not a source violation."""
        diff = (
            "diff --git a/tests/test_consumer.py b/tests/test_consumer.py\n"
            "--- a/tests/test_consumer.py\n"
            "+++ b/tests/test_consumer.py\n"
            "@@ -1,0 +1 @@\n"
            "+    consumer.seek_to_end()  # test setup\n"
        )
        violations, has_tests = _parse_diff(diff)
        assert violations == []
        assert has_tests


@pytest.mark.unit
class TestParseDiffViolations:
    def test_seek_to_end_without_tests_fails(self) -> None:
        diff = _make_diff(
            "src/omniclaude/hooks/subscriber.py", ["    consumer.seek_to_end()"]
        )
        violations, has_tests = _parse_diff(diff)
        assert len(violations) == 1
        assert "seek_to_end" in violations[0]
        assert not has_tests

    def test_kafka_consumer_without_tests_fails(self) -> None:
        diff = _make_diff(
            "src/omniclaude/hooks/handler.py",
            ["from kafka import KafkaConsumer"],
        )
        violations, has_tests = _parse_diff(diff)
        assert len(violations) == 1
        assert "KafkaConsumer" in violations[0]
        assert not has_tests

    def test_poll_without_tests_fails(self) -> None:
        diff = _make_diff(
            "src/omniclaude/hooks/runner.py",
            ["    records = consumer.poll(timeout_ms=100)"],
        )
        violations, has_tests = _parse_diff(diff)
        assert len(violations) == 1
        assert ".poll(" in violations[0]
        assert not has_tests

    def test_multiple_primitives_reported(self) -> None:
        diff = _make_diff(
            "src/omniclaude/hooks/multi.py",
            [
                "from kafka import KafkaConsumer",
                "    consumer.seek_to_end()",
            ],
        )
        violations, _ = _parse_diff(diff)
        assert len(violations) == 2


@pytest.mark.unit
class TestParseDiffCompliant:
    def test_primitive_with_tests_change_is_ok(self) -> None:
        diff = _make_diff(
            "src/omniclaude/hooks/subscriber.py",
            ["    consumer.seek_to_end()"],
            also_add_test=True,
        )
        violations, has_tests = _parse_diff(diff)
        assert len(violations) == 1  # violation exists…
        assert has_tests  # …but tests/ was also touched — compliant

    def test_suppressed_primitive_no_violation(self) -> None:
        diff = _make_diff(
            "src/omniclaude/hooks/subscriber.py",
            ["    consumer.seek_to_end()  # concurrency-ok"],
        )
        violations, _ = _parse_diff(diff)
        assert violations == []


# ---------------------------------------------------------------------------
# Integration tests for main() via synthetic diff injection
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMainReturnCodes:
    """Run main() with a mocked diff source to verify exit codes."""

    def _run_main_with_diff(
        self,
        diff_text: str,
        monkeypatch: pytest.MonkeyPatch,
        *,
        ci: bool = False,
    ) -> int:
        """Patch diff acquisition so main() returns based on synthetic diff."""
        import validate_no_blocking_primitive_without_tests as mod

        if ci:
            monkeypatch.setattr(mod, "_get_ci_diff", lambda _base: diff_text)
            return main(["--ci"])
        else:
            monkeypatch.setattr(mod, "_get_staged_diff", lambda: diff_text)
            return main([])

    def test_clean_diff_returns_0(self, monkeypatch: pytest.MonkeyPatch) -> None:
        diff = _make_diff("src/foo.py", ["    result = x + 1"])
        assert self._run_main_with_diff(diff, monkeypatch) == 0

    def test_blocking_without_tests_returns_1(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        diff = _make_diff("src/foo.py", ["    consumer.seek_to_end()"])
        assert self._run_main_with_diff(diff, monkeypatch) == 1

    def test_blocking_with_tests_returns_0(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        diff = _make_diff(
            "src/foo.py",
            ["    consumer.seek_to_end()"],
            also_add_test=True,
        )
        assert self._run_main_with_diff(diff, monkeypatch) == 0

    def test_suppressed_blocking_returns_0(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        diff = _make_diff(
            "src/foo.py",
            ["    consumer.seek_to_end()  # concurrency-ok"],
        )
        assert self._run_main_with_diff(diff, monkeypatch) == 0

    def test_empty_diff_returns_0(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert self._run_main_with_diff("", monkeypatch) == 0

    def test_ci_mode_blocking_without_tests_returns_1(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        diff = _make_diff("src/bar.py", ["from kafka import KafkaConsumer"])
        assert self._run_main_with_diff(diff, monkeypatch, ci=True) == 1

    def test_ci_mode_blocking_with_tests_returns_0(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        diff = _make_diff(
            "src/bar.py",
            ["from kafka import KafkaConsumer"],
            also_add_test=True,
        )
        assert self._run_main_with_diff(diff, monkeypatch, ci=True) == 0


# ---------------------------------------------------------------------------
# Smoke test: blocking patterns constant is non-empty
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_blocking_patterns_non_empty() -> None:
    assert len(BLOCKING_PATTERNS) >= 3
    assert "seek_to_end" in BLOCKING_PATTERNS
    assert "KafkaConsumer" in BLOCKING_PATTERNS
    assert ".poll(" in BLOCKING_PATTERNS
