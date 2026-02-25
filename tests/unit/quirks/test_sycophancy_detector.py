# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for SycophancyDetector.

False-positive rate (design target):
    - Opener phrases (polite affirmations that aren't sycophantic): ~12%
    - Position reversal (legitimate corrections after new information): ~18%

Each test function uses a golden fixture for the model output and session
history to exercise the detector in isolation.

Related:
    - OMN-2539: Tier 0 heuristic detectors
"""

from __future__ import annotations

import pytest

from omniclaude.quirks.detectors.context import DetectionContext
from omniclaude.quirks.detectors.tier0.sycophancy import SycophancyDetector
from omniclaude.quirks.enums import QuirkType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SESSION = "test-session-syco"


def _ctx(
    output: str,
    history: list[str] | None = None,
) -> DetectionContext:
    return DetectionContext(
        session_id=_SESSION,
        model_output=output,
        session_history=history or [],
    )


# ---------------------------------------------------------------------------
# Positive cases — opener phrases
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_detects_great_question_opener() -> None:
    """'Great question' at the start of output should produce a signal."""
    detector = SycophancyDetector()
    signals = detector.detect(_ctx("Great question! Let me explain..."))
    assert len(signals) >= 1
    sig = signals[0]
    assert sig.quirk_type == QuirkType.SYCOPHANCY
    assert sig.confidence == 0.85
    assert sig.extraction_method == "regex"


@pytest.mark.unit
def test_detects_absolutely_opener() -> None:
    """'Absolutely!' opener should produce a signal."""
    detector = SycophancyDetector()
    signals = detector.detect(_ctx("Absolutely! Here is how you do it."))
    assert len(signals) >= 1
    assert signals[0].confidence == 0.85


@pytest.mark.unit
def test_detects_of_course_opener() -> None:
    """'Of course!' opener should produce a signal."""
    detector = SycophancyDetector()
    signals = detector.detect(_ctx("Of course! I will fix that right away."))
    assert len(signals) >= 1


@pytest.mark.unit
def test_detects_certainly_opener() -> None:
    """'Certainly!' opener should produce a signal."""
    detector = SycophancyDetector()
    signals = detector.detect(_ctx("Certainly! Let me address that."))
    assert len(signals) >= 1


@pytest.mark.unit
def test_detects_happy_to_help_opener() -> None:
    """'Happy to help' opener should produce a signal."""
    detector = SycophancyDetector()
    signals = detector.detect(_ctx("Happy to help! Here's my answer."))
    assert len(signals) >= 1


# ---------------------------------------------------------------------------
# Positive cases — position reversal
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_detects_you_are_right_reversal() -> None:
    """'You're right, I was wrong' after an assertive turn should flag reversal."""
    history = ["The answer is definitely 42. I'm certain about this."]
    output = "You're right, I was incorrect. The answer is actually 24."
    detector = SycophancyDetector()
    signals = detector.detect(_ctx(output, history=history))
    reversal_sigs = [s for s in signals if s.confidence == 0.7]
    assert len(reversal_sigs) >= 1
    assert reversal_sigs[0].extraction_method == "heuristic"


@pytest.mark.unit
def test_detects_i_was_wrong_reversal() -> None:
    """'I was wrong' after a confident assertion should trigger a reversal signal."""
    history = ["I believe the function should be called foo(), not bar()."]
    output = "Actually, I was wrong. You should use bar() instead."
    detector = SycophancyDetector()
    signals = detector.detect(_ctx(output, history=history))
    reversal_sigs = [s for s in signals if s.confidence == 0.7]
    assert len(reversal_sigs) >= 1


@pytest.mark.unit
def test_detects_stand_corrected_reversal() -> None:
    """'I stand corrected' after a prior assertion should produce a reversal signal."""
    history = ["Definitely use Python 3.10 syntax here, I'm certain."]
    output = "I stand corrected — Python 3.12 is actually required."
    detector = SycophancyDetector()
    signals = detector.detect(_ctx(output, history=history))
    reversal_sigs = [s for s in signals if s.confidence == 0.7]
    assert len(reversal_sigs) >= 1


# ---------------------------------------------------------------------------
# Negative cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_no_signal_for_neutral_opener() -> None:
    """A neutral opening sentence should not produce a signal."""
    detector = SycophancyDetector()
    signals = detector.detect(_ctx("Here is my analysis of the issue."))
    assert signals == []


@pytest.mark.unit
def test_no_signal_for_empty_output() -> None:
    """Empty model output should return an empty signal list."""
    detector = SycophancyDetector()
    signals = detector.detect(_ctx(""))
    assert signals == []


@pytest.mark.unit
def test_no_signal_when_model_output_is_none() -> None:
    """None model output should return an empty signal list."""
    detector = SycophancyDetector()
    ctx = DetectionContext(session_id=_SESSION)
    signals = detector.detect(ctx)
    assert signals == []


@pytest.mark.unit
def test_no_reversal_signal_without_prior_assertion() -> None:
    """Reversal phrase without a prior assertive turn in history should not fire."""
    history = ["Let me know if you have any questions."]  # No assertive claim.
    output = "You're right, I apologize for the confusion."
    detector = SycophancyDetector()
    signals = detector.detect(_ctx(output, history=history))
    reversal_sigs = [s for s in signals if s.confidence == 0.7]
    assert len(reversal_sigs) == 0


@pytest.mark.unit
def test_no_reversal_signal_with_empty_history() -> None:
    """Reversal phrase with no session history should not produce a reversal signal."""
    output = "Actually, I was wrong. Let me correct that."
    detector = SycophancyDetector()
    signals = detector.detect(_ctx(output, history=[]))
    reversal_sigs = [s for s in signals if s.confidence == 0.7]
    assert len(reversal_sigs) == 0


@pytest.mark.unit
def test_opener_phrase_mid_sentence_does_not_match() -> None:
    """Sycophantic phrase NOT at the start of output should not produce a signal."""
    detector = SycophancyDetector()
    # Phrase is not at the beginning of the text.
    signals = detector.detect(
        _ctx("I think the approach is wrong, but great question is not a phrase I use.")
    )
    # The opener pattern requires match at start — should not fire.
    opener_sigs = [s for s in signals if s.confidence == 0.85]
    assert len(opener_sigs) == 0
