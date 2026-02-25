# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for HallucinatedApiDetector (Tier 1).

Uses golden AST fixture diffs and in-memory symbol indexes.

Test coverage:
    Positive (4+ cases): hallucinated symbols detected correctly.
    Negative (3+ cases): valid references not flagged.
    Graceful degradation: malformed diffs, empty index handled.

Related:
    - OMN-2548: Tier 1 AST-based detectors
"""

from __future__ import annotations

import pytest

from omniclaude.quirks.detectors.context import DetectionContext
from omniclaude.quirks.detectors.tier1.hallucinated_api import (
    HallucinatedApiDetector,
    _levenshtein,
)
from omniclaude.quirks.enums import QuirkType
from omniclaude.quirks.tools.build_symbol_index import SymbolIndex

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ctx(diff: str) -> DetectionContext:
    return DetectionContext(session_id="test-session-hallucinated", diff=diff)


def _diff(added_source: str, file: str = "src/foo/bar.py") -> str:
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
# Levenshtein helper tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_levenshtein_identical() -> None:
    assert _levenshtein("abc", "abc") == 0


@pytest.mark.unit
def test_levenshtein_single_insertion() -> None:
    assert _levenshtein("abc", "abcd") == 1


@pytest.mark.unit
def test_levenshtein_single_deletion() -> None:
    assert _levenshtein("abcd", "abc") == 1


@pytest.mark.unit
def test_levenshtein_substitution() -> None:
    assert _levenshtein("cat", "bat") == 1


@pytest.mark.unit
def test_levenshtein_empty_strings() -> None:
    assert _levenshtein("", "") == 0
    assert _levenshtein("abc", "") == 3
    assert _levenshtein("", "abc") == 3


# ---------------------------------------------------------------------------
# Positive cases — detector SHOULD emit a signal
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_detects_hallucinated_attribute() -> None:
    """``mymod.nonexistent_fn()`` should produce a HALLUCINATED_API signal."""
    index: SymbolIndex = {"mymod": {"real_fn", "AnotherClass"}}
    src = "result = mymod.nonexistent_fn()\n"
    detector = HallucinatedApiDetector(symbol_index=index)
    signals = detector.detect(_ctx(_diff(src)))

    assert len(signals) == 1
    sig = signals[0]
    assert sig.quirk_type == QuirkType.HALLUCINATED_API
    assert sig.extraction_method == "AST"
    assert sig.confidence == 0.9
    assert "nonexistent_fn" in sig.evidence[1]


@pytest.mark.unit
def test_detects_close_alternative_in_evidence() -> None:
    """When a close symbol exists (distance ≤ 2), evidence includes suggestion."""
    index: SymbolIndex = {"utils": {"serialize", "deserialize", "parse_json"}}
    # "serialise" differs from "serialize" by 1 (British vs American spelling).
    src = "data = utils.serialise(payload)\n"
    detector = HallucinatedApiDetector(symbol_index=index)
    signals = detector.detect(_ctx(_diff(src)))

    assert len(signals) == 1
    evidence_text = " ".join(signals[0].evidence)
    assert "serialize" in evidence_text  # closest valid alternative


@pytest.mark.unit
def test_detects_no_close_alternative() -> None:
    """When no close symbol exists, evidence says so."""
    index: SymbolIndex = {"utils": {"foo", "bar"}}
    src = "utils.completely_different_name()\n"
    detector = HallucinatedApiDetector(symbol_index=index)
    signals = detector.detect(_ctx(_diff(src)))

    assert len(signals) == 1
    evidence_text = " ".join(signals[0].evidence)
    assert "No close alternative" in evidence_text


@pytest.mark.unit
def test_detects_multiple_hallucinations() -> None:
    """Multiple hallucinated symbols in one diff each produce a signal."""
    index: SymbolIndex = {"api": {"Client", "Request"}}
    src = (
        "x = api.Client()\n"  # valid
        "y = api.BadMethod()\n"  # hallucinated
        "z = api.AlsoMissing()\n"  # hallucinated
    )
    detector = HallucinatedApiDetector(symbol_index=index)
    signals = detector.detect(_ctx(_diff(src)))

    assert len(signals) == 2
    # evidence[1] is "Referenced symbol: api.BadMethod"
    referenced = {s.evidence[1] for s in signals}
    assert any("api.BadMethod" in r for r in referenced)
    assert any("api.AlsoMissing" in r for r in referenced)


@pytest.mark.unit
def test_detects_hallucination_in_deeper_context() -> None:
    """Hallucinated reference nested inside a function body is still detected."""
    index: SymbolIndex = {"db": {"connect", "disconnect"}}
    src = (
        "def setup():\n"
        "    conn = db.connect()\n"  # valid
        "    cursor = db.get_cursor()\n"  # hallucinated
        "    return cursor\n"
    )
    detector = HallucinatedApiDetector(symbol_index=index)
    signals = detector.detect(_ctx(_diff(src)))

    assert len(signals) == 1
    assert "get_cursor" in signals[0].evidence[1]


# ---------------------------------------------------------------------------
# Negative cases — detector should NOT emit a signal
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_no_signal_for_valid_symbol() -> None:
    """A reference that exists in the symbol index should not be flagged."""
    index: SymbolIndex = {"mymod": {"my_function", "MyClass"}}
    src = "obj = mymod.MyClass()\n"
    detector = HallucinatedApiDetector(symbol_index=index)
    signals = detector.detect(_ctx(_diff(src)))

    assert signals == []


@pytest.mark.unit
def test_no_signal_for_unknown_module() -> None:
    """References to modules not in the index are skipped (can't validate)."""
    index: SymbolIndex = {"known_mod": {"fn"}}
    src = "unknown_module.some_function()\n"
    detector = HallucinatedApiDetector(symbol_index=index)
    signals = detector.detect(_ctx(_diff(src)))

    assert signals == []


@pytest.mark.unit
def test_no_signal_with_empty_symbol_index() -> None:
    """Empty symbol index means the detector cannot validate — returns ``[]``."""
    src = "result = somemod.something()\n"
    detector = HallucinatedApiDetector(symbol_index={})
    signals = detector.detect(_ctx(_diff(src)))

    assert signals == []


@pytest.mark.unit
def test_no_signal_when_diff_is_none() -> None:
    """None diff must return an empty list."""
    index: SymbolIndex = {"mod": {"fn"}}
    ctx = DetectionContext(session_id="s1")
    detector = HallucinatedApiDetector(symbol_index=index)
    assert detector.detect(ctx) == []


@pytest.mark.unit
def test_no_signal_for_empty_diff() -> None:
    """Empty diff string must return an empty list."""
    index: SymbolIndex = {"mod": {"fn"}}
    detector = HallucinatedApiDetector(symbol_index=index)
    assert detector.detect(_ctx("")) == []


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_graceful_on_syntax_error(caplog: pytest.LogCaptureFixture) -> None:
    """Unparseable diff lines should return ``[]`` and emit a warning."""
    import logging

    index: SymbolIndex = {"mod": {"fn"}}
    bad_diff = (
        "diff --git a/foo.py b/foo.py\n"
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1,2 +1,3 @@\n"
        "+def broken(\n"
        "+    # unclosed\n"
    )
    detector = HallucinatedApiDetector(symbol_index=index)
    with caplog.at_level(
        logging.WARNING,
        logger="omniclaude.quirks.detectors.tier1.hallucinated_api",
    ):
        signals = detector.detect(_ctx(bad_diff))

    assert signals == []
    assert any("parse failure" in r.message for r in caplog.records)


@pytest.mark.unit
def test_default_constructor_no_op() -> None:
    """Instantiating without symbol_index (no args) should return ``[]``."""
    src = "result = mod.something()\n"
    detector = HallucinatedApiDetector()
    signals = detector.detect(_ctx(_diff(src)))
    assert signals == []
