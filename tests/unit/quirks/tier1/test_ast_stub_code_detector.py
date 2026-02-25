# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for AstStubCodeDetector (Tier 1).

Uses golden AST fixture diffs — minimal unified diff snippets that exercise
the detector in isolation.

Test coverage:
    Positive (4+ cases): stub bodies detected correctly.
    Negative (3+ cases): non-stub bodies not flagged.
    Graceful degradation: malformed diffs handled without error.

Related:
    - OMN-2548: Tier 1 AST-based detectors
"""

from __future__ import annotations

import pytest

from omniclaude.quirks.detectors.context import DetectionContext
from omniclaude.quirks.detectors.tier1.ast_stub_code import AstStubCodeDetector
from omniclaude.quirks.enums import QuirkStage, QuirkType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ctx(diff: str, file_paths: list[str] | None = None) -> DetectionContext:
    return DetectionContext(
        session_id="test-session-ast-stub",
        diff=diff,
        file_paths=file_paths or [],
    )


def _diff(added_source: str, file: str = "src/foo/bar.py") -> str:
    """Wrap *added_source* in a minimal unified diff block."""
    lines = added_source.splitlines()
    added = "\n".join(f"+{line}" for line in lines)
    return (
        f"diff --git a/{file} b/{file}\n"
        f"--- a/{file}\n"
        f"+++ b/{file}\n"
        "@@ -1,3 +1,10 @@\n"
        f"{added}\n"
    )


# ---------------------------------------------------------------------------
# Positive cases — detector SHOULD emit a signal
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_detects_pass_only_body() -> None:
    """Function with only ``pass`` in body should be detected as STUB_CODE."""
    src = "def do_something():\n    pass\n"
    detector = AstStubCodeDetector()
    signals = detector.detect(_ctx(_diff(src)))

    assert len(signals) == 1
    sig = signals[0]
    assert sig.quirk_type == QuirkType.STUB_CODE
    assert sig.confidence == 0.95
    assert sig.extraction_method == "AST"
    assert sig.stage == QuirkStage.WARN
    assert sig.ast_span is not None
    assert "do_something" in sig.evidence[1]


@pytest.mark.unit
def test_detects_ellipsis_only_body() -> None:
    """Function with only ``...`` in body should be detected as STUB_CODE."""
    src = "def placeholder():\n    ...\n"
    detector = AstStubCodeDetector()
    signals = detector.detect(_ctx(_diff(src)))

    assert len(signals) == 1
    sig = signals[0]
    assert sig.quirk_type == QuirkType.STUB_CODE
    assert sig.confidence == 0.95
    assert sig.extraction_method == "AST"
    assert "placeholder" in sig.evidence[1]


@pytest.mark.unit
def test_detects_raise_not_implemented_body() -> None:
    """Function raising ``NotImplementedError`` only should be detected."""
    src = "def not_done():\n    raise NotImplementedError\n"
    detector = AstStubCodeDetector()
    signals = detector.detect(_ctx(_diff(src)))

    assert len(signals) == 1
    assert signals[0].confidence == 0.95
    assert "not_done" in signals[0].evidence[1]


@pytest.mark.unit
def test_detects_raise_not_implemented_with_message() -> None:
    """``raise NotImplementedError('msg')`` body should also be detected."""
    src = "def not_done():\n    raise NotImplementedError('not yet')\n"
    detector = AstStubCodeDetector()
    signals = detector.detect(_ctx(_diff(src)))

    assert len(signals) == 1
    assert signals[0].extraction_method == "AST"


@pytest.mark.unit
def test_detects_multiple_stub_functions() -> None:
    """Multiple stub functions in one diff should each produce a signal."""
    src = (
        "def alpha():\n"
        "    pass\n"
        "\n"
        "def beta():\n"
        "    ...\n"
        "\n"
        "def gamma():\n"
        "    raise NotImplementedError\n"
    )
    detector = AstStubCodeDetector()
    signals = detector.detect(_ctx(_diff(src)))

    assert len(signals) == 3
    names = {s.evidence[1].split(": ", 1)[1] for s in signals}
    assert names == {"alpha", "beta", "gamma"}


@pytest.mark.unit
def test_detects_async_stub_function() -> None:
    """``async def`` with only ``pass`` should also be detected."""
    src = "async def fetch():\n    pass\n"
    detector = AstStubCodeDetector()
    signals = detector.detect(_ctx(_diff(src)))

    assert len(signals) == 1
    assert "fetch" in signals[0].evidence[1]


# ---------------------------------------------------------------------------
# Negative cases — detector should NOT emit a signal
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_no_signal_for_real_implementation() -> None:
    """A function with a real return statement should not be flagged."""
    src = "def compute(x: int) -> int:\n    return x * 2\n"
    detector = AstStubCodeDetector()
    signals = detector.detect(_ctx(_diff(src)))

    assert signals == []


@pytest.mark.unit
def test_no_signal_for_function_with_docstring_and_body() -> None:
    """A function with a docstring plus real implementation is not a stub."""
    src = (
        "def greet(name: str) -> str:\n"
        '    """Return a greeting."""\n'
        "    return f'Hello, {name}!'\n"
    )
    detector = AstStubCodeDetector()
    signals = detector.detect(_ctx(_diff(src)))

    assert signals == []


@pytest.mark.unit
def test_no_signal_for_empty_diff() -> None:
    """Empty diff must return an empty list."""
    detector = AstStubCodeDetector()
    assert detector.detect(_ctx("")) == []


@pytest.mark.unit
def test_no_signal_when_diff_is_none() -> None:
    """None diff must return an empty list."""
    ctx = DetectionContext(session_id="s1")
    detector = AstStubCodeDetector()
    assert detector.detect(ctx) == []


# ---------------------------------------------------------------------------
# Graceful degradation — malformed / non-parseable diffs
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_graceful_on_syntax_error(caplog: pytest.LogCaptureFixture) -> None:
    """Unparseable diff lines should return ``[]`` and emit a warning log."""
    import logging

    bad_diff = (
        "diff --git a/foo.py b/foo.py\n"
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1,2 +1,3 @@\n"
        "+def broken(\n"
        "+    # unclosed paren\n"
    )
    detector = AstStubCodeDetector()
    with caplog.at_level(
        logging.WARNING, logger="omniclaude.quirks.detectors.tier1.ast_stub_code"
    ):
        signals = detector.detect(_ctx(bad_diff))

    assert signals == []
    assert any("parse failure" in r.message for r in caplog.records)


@pytest.mark.unit
def test_no_signal_for_removed_lines_only() -> None:
    """A diff with only removed lines (no ``+`` lines) should return ``[]``."""
    diff_only_removed = (
        "diff --git a/foo.py b/foo.py\n"
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1,3 +1,2 @@\n"
        "-def old():\n"
        "-    pass\n"
        "+\n"
    )
    detector = AstStubCodeDetector()
    # The only added line is a blank line — no functions to detect.
    signals = detector.detect(_ctx(diff_only_removed))
    assert signals == []


@pytest.mark.unit
def test_ast_span_in_signal() -> None:
    """ast_span should be populated with valid (start, end) line numbers."""
    src = "def stub_fn():\n    pass\n"
    detector = AstStubCodeDetector()
    signals = detector.detect(_ctx(_diff(src)))

    assert len(signals) == 1
    span = signals[0].ast_span
    assert span is not None
    start, end = span
    assert start >= 1
    assert end >= start
