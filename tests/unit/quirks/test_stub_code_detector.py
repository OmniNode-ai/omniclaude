# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for StubCodeDetector.

False-positive rate (design target):
    - NotImplementedError in docstring examples: ~2%
    - pass/... in abstract/protocol stubs: ~8%
    - TODO/FIXME comments that are genuine reminders: ~15%

Each test function uses a golden diff fixture (minimal unified diff snippet)
to exercise the detector in isolation.

Related:
    - OMN-2539: Tier 0 heuristic detectors
"""

from __future__ import annotations

import pytest

from omniclaude.quirks.detectors.context import DetectionContext
from omniclaude.quirks.detectors.tier0.stub_code import StubCodeDetector
from omniclaude.quirks.enums import QuirkType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context(diff: str, file_paths: list[str] | None = None) -> DetectionContext:
    return DetectionContext(
        session_id="test-session-stub",
        diff=diff,
        file_paths=file_paths or [],
    )


def _diff_with_added_line(content: str, file: str = "src/foo/bar.py") -> str:
    return (
        f"diff --git a/{file} b/{file}\n"
        "--- a/{file}\n"
        "+++ b/{file}\n"
        "@@ -1,3 +1,4 @@\n"
        f"+{content}\n"
    )


# ---------------------------------------------------------------------------
# Positive cases (detector SHOULD emit a signal)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_detects_not_implemented_error() -> None:
    """NotImplementedError in added line should produce a signal with confidence 0.9."""
    diff = _diff_with_added_line("    raise NotImplementedError")
    detector = StubCodeDetector()
    signals = detector.detect(_make_context(diff))

    assert len(signals) == 1
    sig = signals[0]
    assert sig.quirk_type == QuirkType.STUB_CODE
    assert sig.confidence == 0.9
    assert sig.extraction_method == "regex"
    assert "NotImplementedError" in sig.evidence[0]


@pytest.mark.unit
def test_detects_bare_pass() -> None:
    """``pass`` inside an added function body should produce a signal with confidence 0.75."""
    diff = _diff_with_added_line("    pass")
    detector = StubCodeDetector()
    signals = detector.detect(_make_context(diff))

    assert len(signals) == 1
    sig = signals[0]
    assert sig.quirk_type == QuirkType.STUB_CODE
    assert sig.confidence == 0.75
    assert sig.extraction_method == "heuristic"


@pytest.mark.unit
def test_detects_ellipsis_stub() -> None:
    """``...`` as a function body stub should produce a signal with confidence 0.75."""
    diff = _diff_with_added_line("    ...")
    detector = StubCodeDetector()
    signals = detector.detect(_make_context(diff))

    assert len(signals) == 1
    sig = signals[0]
    assert sig.quirk_type == QuirkType.STUB_CODE
    assert sig.confidence == 0.75


@pytest.mark.unit
def test_detects_todo_comment() -> None:
    """``# TODO: implement this`` should produce a signal with confidence 0.5."""
    diff = _diff_with_added_line("    # TODO: implement this")
    detector = StubCodeDetector()
    signals = detector.detect(_make_context(diff))

    assert len(signals) == 1
    sig = signals[0]
    assert sig.quirk_type == QuirkType.STUB_CODE
    assert sig.confidence == 0.5
    assert sig.extraction_method == "regex"


@pytest.mark.unit
def test_detects_fixme_comment() -> None:
    """``# FIXME: broken`` should produce a signal with confidence 0.5."""
    diff = _diff_with_added_line("    # FIXME: broken implementation")
    detector = StubCodeDetector()
    signals = detector.detect(_make_context(diff))

    assert len(signals) == 1
    assert signals[0].confidence == 0.5


@pytest.mark.unit
def test_detects_multiple_stubs_in_one_diff() -> None:
    """Multiple stub patterns in a single diff should yield multiple signals."""
    diff = (
        "diff --git a/src/foo/bar.py b/src/foo/bar.py\n"
        "--- a/src/foo/bar.py\n"
        "+++ b/src/foo/bar.py\n"
        "@@ -1,5 +1,8 @@\n"
        "+def foo():\n"
        "+    raise NotImplementedError\n"
        "+def bar():\n"
        "+    pass\n"
        "+    # TODO: fix bar\n"
    )
    detector = StubCodeDetector()
    signals = detector.detect(_make_context(diff))

    # NotImplementedError + pass + TODO = 3 signals
    assert len(signals) >= 2
    quirk_types = {s.quirk_type for s in signals}
    assert QuirkType.STUB_CODE in quirk_types


# ---------------------------------------------------------------------------
# Negative cases (detector should NOT emit a signal)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_ignores_pass_in_removed_line() -> None:
    """Removed lines (``-``) should not trigger detection."""
    diff = (
        "diff --git a/src/foo/bar.py b/src/foo/bar.py\n"
        "--- a/src/foo/bar.py\n"
        "+++ b/src/foo/bar.py\n"
        "@@ -1,3 +1,3 @@\n"
        "-    pass\n"
        "+    return 42\n"
    )
    detector = StubCodeDetector()
    signals = detector.detect(_make_context(diff))
    pass_signals = [s for s in signals if "pass" in str(s.evidence).lower()]
    assert len(pass_signals) == 0


@pytest.mark.unit
def test_ignores_not_implemented_in_docstring() -> None:
    """NotImplementedError inside a triple-quoted docstring should not fire."""
    diff = (
        "diff --git a/src/foo/bar.py b/src/foo/bar.py\n"
        "--- a/src/foo/bar.py\n"
        "+++ b/src/foo/bar.py\n"
        "@@ -1,5 +1,8 @@\n"
        "+def foo():\n"
        '+    """Example: raise NotImplementedError when not overridden."""\n'
        "+    return 1\n"
    )
    detector = StubCodeDetector()
    signals = detector.detect(_make_context(diff))
    # Line starts with a quote — classified as inside string literal.
    nie_signals = [s for s in signals if s.confidence == 0.9]
    assert len(nie_signals) == 0


@pytest.mark.unit
def test_no_signal_for_empty_diff() -> None:
    """Empty diff should return an empty signal list."""
    detector = StubCodeDetector()
    signals = detector.detect(_make_context(""))
    assert signals == []


@pytest.mark.unit
def test_no_signal_when_diff_is_none() -> None:
    """None diff should return an empty signal list."""
    ctx = DetectionContext(session_id="s1")
    detector = StubCodeDetector()
    signals = detector.detect(ctx)
    assert signals == []


@pytest.mark.unit
def test_pass_in_test_file_has_lower_confidence() -> None:
    """``pass`` in a test file should have confidence capped at 0.5."""
    diff = _diff_with_added_line("    pass", file="src/foo/test_bar.py")
    detector = StubCodeDetector()
    signals = detector.detect(_make_context(diff, file_paths=["src/foo/test_bar.py"]))
    assert len(signals) == 1
    assert signals[0].confidence == 0.5


@pytest.mark.unit
def test_no_signal_for_context_lines() -> None:
    """Context lines (no leading ``+`` or ``-``) should not trigger detection."""
    diff = (
        "diff --git a/src/foo/bar.py b/src/foo/bar.py\n"
        "--- a/src/foo/bar.py\n"
        "+++ b/src/foo/bar.py\n"
        "@@ -1,3 +1,3 @@\n"
        "     pass\n"  # context line (space prefix)
        "+    return True\n"
    )
    detector = StubCodeDetector()
    signals = detector.detect(_make_context(diff))
    assert all(s.diff_hunk != "     pass" for s in signals)
