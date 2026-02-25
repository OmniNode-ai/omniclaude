# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for NoTestsDetector.

False-positive rate (design target):
    - Refactoring-only changes that add lines but don't need new tests: ~10%
    - Infrastructure / config files under src/ (e.g. __init__.py): ~5%

Each test function uses a golden diff fixture (minimal unified diff snippet)
to exercise the detector in isolation.

Related:
    - OMN-2539: Tier 0 heuristic detectors
"""

from __future__ import annotations

import pytest

from omniclaude.quirks.detectors.context import DetectionContext
from omniclaude.quirks.detectors.tier0.no_tests import NoTestsDetector
from omniclaude.quirks.enums import QuirkType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SESSION = "test-session-notests"


def _make_diff(
    source_added: int = 25,
    test_added: int = 0,
    source_file: str = "src/omniclaude/hooks/tool_logger.py",
    test_file: str | None = None,
) -> str:
    """Build a minimal unified diff with the given number of added lines."""
    added_src_lines = "".join(f"+    line_{i} = {i}\n" for i in range(source_added))
    removed_src_lines = ""

    diff = (
        f"diff --git a/{source_file} b/{source_file}\n"
        f"--- a/{source_file}\n"
        f"+++ b/{source_file}\n"
        f"@@ -1,5 +1,{5 + source_added} @@\n"
        f" existing_line = 1\n"
        f"{added_src_lines}"
        f"{removed_src_lines}"
    )

    if test_file and test_added > 0:
        added_test_lines = "".join(
            f"+    assert thing_{i}\n" for i in range(test_added)
        )
        diff += (
            f"\ndiff --git a/{test_file} b/{test_file}\n"
            f"--- a/{test_file}\n"
            f"+++ b/{test_file}\n"
            f"@@ -1,2 +1,{2 + test_added} @@\n"
            f" import pytest\n"
            f"{added_test_lines}"
        )

    return diff


# ---------------------------------------------------------------------------
# Positive cases (detector SHOULD emit a signal)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_detects_no_tests_for_source_with_many_added_lines() -> None:
    """Source file with 25+ added lines and no test changes should produce a signal."""
    diff = _make_diff(source_added=25)
    detector = NoTestsDetector()
    ctx = DetectionContext(session_id=_SESSION, diff=diff)
    signals = detector.detect(ctx)

    assert len(signals) == 1
    sig = signals[0]
    assert sig.quirk_type == QuirkType.NO_TESTS
    assert sig.confidence == 0.8
    assert sig.extraction_method == "heuristic"
    assert "tool_logger" in (sig.file_path or "")


@pytest.mark.unit
def test_detects_no_tests_multiple_source_files() -> None:
    """Two source files with 25+ lines added and no tests → two signals."""
    diff = _make_diff(source_added=25, source_file="src/omniclaude/hooks/a.py")
    diff += "\n" + _make_diff(source_added=30, source_file="src/omniclaude/hooks/b.py")

    detector = NoTestsDetector()
    ctx = DetectionContext(session_id=_SESSION, diff=diff)
    signals = detector.detect(ctx)

    assert len(signals) == 2
    file_paths = {s.file_path for s in signals}
    assert "src/omniclaude/hooks/a.py" in file_paths
    assert "src/omniclaude/hooks/b.py" in file_paths


@pytest.mark.unit
def test_detects_no_tests_only_source_file_added() -> None:
    """Single newly added source file with no tests → signal."""
    diff = _make_diff(source_added=50)
    detector = NoTestsDetector()
    ctx = DetectionContext(session_id=_SESSION, diff=diff)
    signals = detector.detect(ctx)
    assert len(signals) >= 1
    assert all(s.quirk_type == QuirkType.NO_TESTS for s in signals)


@pytest.mark.unit
def test_expected_test_path_mentioned_in_evidence() -> None:
    """The expected test path should appear in the signal evidence."""
    diff = _make_diff(
        source_added=25, source_file="src/omniclaude/hooks/tool_logger.py"
    )
    detector = NoTestsDetector()
    ctx = DetectionContext(session_id=_SESSION, diff=diff)
    signals = detector.detect(ctx)
    assert len(signals) == 1
    evidence_text = " ".join(signals[0].evidence)
    assert "test_tool_logger" in evidence_text


@pytest.mark.unit
def test_custom_threshold_emits_signal() -> None:
    """Using a low custom threshold (5 lines) triggers detection on small diffs."""
    diff = _make_diff(source_added=8)
    detector = NoTestsDetector(min_lines_threshold=5)
    ctx = DetectionContext(session_id=_SESSION, diff=diff)
    signals = detector.detect(ctx)
    assert len(signals) == 1


# ---------------------------------------------------------------------------
# Negative cases (detector should NOT emit a signal)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_no_signal_when_test_file_present() -> None:
    """When a matching test file has added lines, no signal should be emitted."""
    diff = _make_diff(
        source_added=25,
        test_added=10,
        source_file="src/omniclaude/hooks/tool_logger.py",
        test_file="tests/unit/omniclaude/hooks/test_tool_logger.py",
    )
    detector = NoTestsDetector()
    ctx = DetectionContext(session_id=_SESSION, diff=diff)
    signals = detector.detect(ctx)
    assert signals == []


@pytest.mark.unit
def test_no_signal_below_threshold() -> None:
    """Source file with fewer added lines than threshold should NOT produce a signal."""
    diff = _make_diff(source_added=10)  # default threshold is 20
    detector = NoTestsDetector()
    ctx = DetectionContext(session_id=_SESSION, diff=diff)
    signals = detector.detect(ctx)
    assert signals == []


@pytest.mark.unit
def test_no_signal_for_init_files() -> None:
    """Changes to __init__.py should not produce a signal."""
    diff = (
        "diff --git a/src/omniclaude/hooks/__init__.py b/src/omniclaude/hooks/__init__.py\n"
        "--- a/src/omniclaude/hooks/__init__.py\n"
        "+++ b/src/omniclaude/hooks/__init__.py\n"
        "@@ -1,2 +1,30 @@\n"
    ) + "".join(
        f"+from omniclaude.hooks.module_{i} import thing_{i}\n" for i in range(28)
    )

    detector = NoTestsDetector()
    ctx = DetectionContext(session_id=_SESSION, diff=diff)
    signals = detector.detect(ctx)
    assert signals == []


@pytest.mark.unit
def test_no_signal_for_empty_diff() -> None:
    """Empty diff should return an empty signal list."""
    detector = NoTestsDetector()
    ctx = DetectionContext(session_id=_SESSION, diff="")
    signals = detector.detect(ctx)
    assert signals == []


@pytest.mark.unit
def test_no_signal_when_diff_is_none() -> None:
    """None diff should return an empty signal list."""
    detector = NoTestsDetector()
    ctx = DetectionContext(session_id=_SESSION)
    signals = detector.detect(ctx)
    assert signals == []


@pytest.mark.unit
def test_no_signal_for_test_only_changes() -> None:
    """Changes only to test files (no source) should not produce a signal."""
    diff = _make_diff(
        source_added=0,
        test_added=30,
        source_file="src/omniclaude/hooks/tool_logger.py",
        test_file="tests/unit/omniclaude/hooks/test_tool_logger.py",
    )
    # Override: make source have 0 net added by using few lines.
    diff2 = _make_diff(
        source_added=5,  # Below threshold
        test_added=30,
        source_file="src/omniclaude/hooks/tool_logger.py",
        test_file="tests/unit/omniclaude/hooks/test_tool_logger.py",
    )
    detector = NoTestsDetector()
    ctx = DetectionContext(session_id=_SESSION, diff=diff2)
    signals = detector.detect(ctx)
    assert signals == []
