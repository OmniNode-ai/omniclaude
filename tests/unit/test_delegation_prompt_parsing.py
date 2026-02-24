# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2026 OmniNode Team
"""Delegation prompt regression tests (OMN-2282).

Snapshot-tests the output format produced by the local delegation handler
(_format_delegated_response) for the three delegatable task types:

  1. Doc gen   (TaskIntent.DOCUMENT)  — "Write documentation for …"
  2. Boilerplate (TaskIntent.TEST)    — "Write unit tests for …"
  3. Code review (TaskIntent.RESEARCH) — "Review this code for issues"

Validates:

  1. Output schema snapshot — structural sections present in each delegation type
  2. ModelDelegatedResponse parsing — extract fields from the formatted string
  3. Bad output recovery — malformed / missing sections handled without crashing

All tests run without network access.  The handler module is imported directly
(not via the installed package) using the same sys.path trick as
test_local_delegation_handler.py.  No live LLM calls are made; all outbound
calls are replaced by return_value stubs.

Note on ``ModelDelegatedResponse``:
    There is no Pydantic class with this name in the current codebase — the
    delegation response is a plain formatted string produced by
    ``_format_delegated_response()``.  This file defines an inline
    ``ModelDelegatedResponse`` dataclass that **parses** that string format,
    acting as the schema specification.  If the format changes, the parser
    must be updated here deliberately (same "no silent schema changes" pattern
    used in test_enrichment_prompt_parsing.py).

Format being snapshotted (verbatim from _format_delegated_response):

    [Local Model Response - {model_name}]

    {response_text}

    ---
    Delegated via local model: confidence={confidence:.3f}, savings={savings_str}. Reason: {reasons}
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# sys.path setup: plugin lib modules live outside the normal package tree
# ---------------------------------------------------------------------------

_HOOKS_LIB = Path(__file__).parent.parent.parent / "plugins" / "onex" / "hooks" / "lib"
if str(_HOOKS_LIB) not in sys.path:
    sys.path.insert(0, str(_HOOKS_LIB))

import local_delegation_handler as ldh  # noqa: E402 I001

# All tests in this module are unit tests.
pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Inline ModelDelegatedResponse schema
# ---------------------------------------------------------------------------
# This dataclass is the schema specification for the formatted delegation
# response string.  It acts as an inline replica so tests remain stable even
# if the omniclaude package is refactored.  Any change to _format_delegated_response
# MUST be reflected here as a deliberate, reviewed update.
#
# SYNC REQUIRED (manual): Verify the regex patterns below match the format
# produced by _format_delegated_response() in local_delegation_handler.py
# (verified 2026-02-19 against the merged OMN-2271 implementation).


@dataclass
class ModelDelegatedResponse:
    """Parsed representation of a _format_delegated_response() output string.

    Fields extracted from the formatted delegation string:
        attribution_line: "[Local Model Response - {model}]" (first non-blank line)
        model_name:       model identifier extracted from attribution_line
        body:             the LLM response body (text between header and separator)
        confidence:       float extracted from footer (confidence=X.XXX)
        savings_str:      raw savings string (~$X.XXXX or "local inference")
        reasons:          raw reasons string from footer (after "Reason: ")
    """

    attribution_line: str
    model_name: str
    body: str
    confidence: float
    savings_str: str
    reasons: str


# ---------------------------------------------------------------------------
# Parser for ModelDelegatedResponse
# ---------------------------------------------------------------------------

# Canonical regex patterns snapshotted from the _format_delegated_response output.
# If these need updating, it means the prompt format changed — bump the prompt
# version annotation in the handler too.
_ATTRIBUTION_RE = re.compile(r"^\[Local Model Response - (.+?)\]$", re.MULTILINE)
_CONFIDENCE_RE = re.compile(r"confidence=(\d+\.\d+)")
# The production format is: savings=~$0.0112. Reason: ...
# The literal "." after the savings amount is the sentence separator, not part
# of the number.  [\d.]+ would greedily consume it (matching "0.0112." instead
# of "0.0112"), so we use [0-9]+\.[0-9]+ which requires an integer-dot-integer
# structure and stops before any trailing punctuation.
_SAVINGS_RE = re.compile(r"savings=(~\$[0-9]+\.[0-9]+|local inference)")
# re.DOTALL is required because delegation reasons can span multiple lines
# (e.g., a reasons list joined by "; " may contain embedded newlines if a reason
# string itself contains a newline), and "." must match newlines to capture the
# entire reason text in a single group up to end-of-string.
_REASON_RE = re.compile(r"Reason: (.+)$", re.DOTALL)
# The production code always emits "\n---\n" as the separator (see
# _format_delegated_response: f"---\n" preceded by f"{response_text}\n\n").
# Using the full "\n---\n" form prevents a false match on "---" that appears
# mid-line in the body (e.g., inside a markdown table or inline usage), and
# also means len(_SEPARATOR) correctly advances past the trailing newline when
# slicing the footer, so the footer string begins at the "Delegated" line.
_SEPARATOR = "\n---\n"


def parse_delegated_response(text: str) -> ModelDelegatedResponse | None:
    """Parse a _format_delegated_response() output string into ModelDelegatedResponse.

    Returns None if the text is missing required structural elements (attribution
    header, separator, or confidence value in footer).

    Args:
        text: Raw formatted string from _format_delegated_response().

    Returns:
        Parsed ModelDelegatedResponse, or None for malformed input.
    """
    # Require attribution line
    attr_match = _ATTRIBUTION_RE.search(text)
    if not attr_match:
        return None

    attribution_line = attr_match.group(0)
    model_name = attr_match.group(1)

    # Require separator
    if _SEPARATOR not in text:
        return None

    # Extract body: text between end of attribution line and separator
    after_header = text[attr_match.end() :]
    sep_idx = after_header.find(_SEPARATOR)
    if sep_idx == -1:
        return None
    body = after_header[:sep_idx].strip()

    # Extract footer (after separator)
    footer = after_header[sep_idx + len(_SEPARATOR) :]

    # Require confidence in footer
    conf_match = _CONFIDENCE_RE.search(footer)
    if not conf_match:
        return None
    confidence = float(conf_match.group(1))

    # Savings (optional but expected)
    savings_match = _SAVINGS_RE.search(footer)
    savings_str = savings_match.group(1) if savings_match else ""

    # Reasons (optional)
    reason_match = _REASON_RE.search(footer)
    reasons = reason_match.group(1).strip() if reason_match else ""

    return ModelDelegatedResponse(
        attribution_line=attribution_line,
        model_name=model_name,
        body=body,
        confidence=confidence,
        savings_str=savings_str,
        reasons=reasons,
    )


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

# Canonical representative prompts for each delegatable intent type.
# Chosen to reliably trigger classification above the 0.9 confidence threshold.
_DOC_GEN_PROMPT = (
    "Document the handle_delegation function with a detailed docstring. "
    "Include parameters, return value, and description."
)
_BOILERPLATE_PROMPT = (
    "Write pytest unit tests for the TaskClassifier.classify method. "
    "Test all intent categories with representative inputs."
)
_CODE_REVIEW_PROMPT = (
    "What are the potential issues in this code? "
    "Explain how the delegation gate logic works and where it might fail."
)


def _make_delegation_score(
    delegatable: bool,
    confidence: float = 0.95,
    delegate_to_model: str = "qwen2.5-14b",
    estimated_savings_usd: float = 0.0084,
    reasons: list[str] | None = None,
) -> Any:
    """Build a minimal ModelDelegationScore-compatible mock for formatting tests."""
    score = MagicMock()
    score.delegatable = delegatable
    score.confidence = confidence
    score.delegate_to_model = delegate_to_model
    score.estimated_savings_usd = estimated_savings_usd
    score.reasons = reasons or []
    return score


def _doc_gen_score() -> Any:
    return _make_delegation_score(
        delegatable=True,
        confidence=0.950,
        delegate_to_model="qwen2.5-14b",
        estimated_savings_usd=0.0112,  # DOCUMENT: 800 avg tokens
        reasons=[
            "intent 'document' is in the delegation allow-list",
            "confidence 0.950 exceeds threshold 0.900",
        ],
    )


def _boilerplate_score() -> Any:
    return _make_delegation_score(
        delegatable=True,
        confidence=0.920,
        delegate_to_model="qwen2.5-14b",
        estimated_savings_usd=0.0084,  # TEST: 600 avg tokens
        reasons=[
            "intent 'test' is in the delegation allow-list",
            "confidence 0.920 exceeds threshold 0.900",
        ],
    )


def _code_review_score() -> Any:
    return _make_delegation_score(
        delegatable=True,
        confidence=0.910,
        delegate_to_model="qwen2.5-14b",
        estimated_savings_usd=0.0056,  # RESEARCH: 400 avg tokens
        reasons=[
            "intent 'research' is in the delegation allow-list",
            "confidence 0.910 exceeds threshold 0.900",
        ],
    )


# ---------------------------------------------------------------------------
# 1. Output schema snapshot tests — one class per delegation type
# ---------------------------------------------------------------------------


class TestDocGenOutputSchema:
    """Snapshot the output schema for doc gen (TaskIntent.DOCUMENT) delegation."""

    def _make_output(self) -> str:
        return ldh._format_delegated_response(
            response_text=(
                "```python\ndef handle_delegation(prompt: str, ...) -> dict:\n"
                '    """Entry point: attempt local delegation for the given prompt."""\n'
                "```"
            ),
            model_name="qwen2.5-14b",
            delegation_score=_doc_gen_score(),
            prompt=_DOC_GEN_PROMPT,
        )

    def test_attribution_header_present(self) -> None:
        """Output starts with [Local Model Response - <model>] attribution line."""
        output = self._make_output()
        assert output.startswith("[Local Model Response - qwen2.5-14b]")

    def test_attribution_header_exact_format(self) -> None:
        """Attribution line matches the canonical bracket format."""
        output = self._make_output()
        first_line = output.splitlines()[0]
        assert re.match(r"^\[Local Model Response - .+\]$", first_line), (
            f"First line did not match attribution format: {first_line!r}"
        )

    def test_body_section_present(self) -> None:
        """Output contains the LLM response body text."""
        output = self._make_output()
        assert "handle_delegation" in output

    def test_separator_line_present(self) -> None:
        """'---' separator line separates body from footer."""
        output = self._make_output()
        assert "\n---\n" in output

    def test_footer_contains_delegated_prefix(self) -> None:
        """Footer starts with 'Delegated via local model:'."""
        output = self._make_output()
        assert "Delegated via local model:" in output

    def test_footer_contains_confidence(self) -> None:
        """Footer includes confidence=X.XXX value."""
        output = self._make_output()
        assert "confidence=0.950" in output

    def test_footer_contains_savings_amount(self) -> None:
        """Footer includes savings dollar amount for doc gen (has positive savings)."""
        output = self._make_output()
        assert "~$" in output

    def test_footer_contains_reason(self) -> None:
        """Footer includes the 'document' intent reason."""
        output = self._make_output()
        assert "document" in output

    def test_output_structure_order(self) -> None:
        """Attribution header appears before body, body before separator, separator before footer."""
        output = self._make_output()
        attr_pos = output.index("[Local Model Response")
        sep_pos = output.index("\n---\n")
        footer_pos = output.index("Delegated via local model:")
        assert attr_pos < sep_pos < footer_pos


class TestBoilerplateOutputSchema:
    """Snapshot the output schema for test boilerplate (TaskIntent.TEST) delegation."""

    def _make_output(self) -> str:
        return ldh._format_delegated_response(
            response_text=(
                "```python\nimport pytest\n\n"
                "class TestTaskClassifier:\n"
                "    def test_classify_debug(self) -> None:\n"
                "        ...\n```"
            ),
            model_name="qwen2.5-14b",
            delegation_score=_boilerplate_score(),
            prompt=_BOILERPLATE_PROMPT,
        )

    def test_attribution_header_present(self) -> None:
        """Output starts with [Local Model Response - <model>] attribution line."""
        output = self._make_output()
        assert output.startswith("[Local Model Response - qwen2.5-14b]")

    def test_body_contains_test_code(self) -> None:
        """LLM response body containing pytest boilerplate is preserved."""
        output = self._make_output()
        assert "pytest" in output

    def test_separator_present(self) -> None:
        """'---' separator line is present."""
        output = self._make_output()
        assert "\n---\n" in output

    def test_footer_confidence_reflects_boilerplate_score(self) -> None:
        """Footer confidence matches the boilerplate delegation score (0.920)."""
        output = self._make_output()
        assert "confidence=0.920" in output

    def test_footer_contains_test_intent_reason(self) -> None:
        """Footer includes the 'test' intent delegation reason."""
        output = self._make_output()
        assert "test" in output.split("\n---\n")[-1]

    def test_savings_present_for_test_intent(self) -> None:
        """Savings line present; TEST intent has positive estimated savings."""
        output = self._make_output()
        assert "~$" in output


class TestCodeReviewOutputSchema:
    """Snapshot the output schema for code review (TaskIntent.RESEARCH) delegation."""

    def _make_output(self) -> str:
        return ldh._format_delegated_response(
            response_text=(
                "The delegation gate uses four sequential checks. "
                "A potential issue: if _classify_prompt raises, the handler "
                "catches it and returns delegated=False, which is correct."
            ),
            model_name="qwen2.5-14b",
            delegation_score=_code_review_score(),
            prompt=_CODE_REVIEW_PROMPT,
        )

    def test_attribution_header_present(self) -> None:
        """Output starts with [Local Model Response - <model>] attribution line."""
        output = self._make_output()
        assert output.startswith("[Local Model Response - qwen2.5-14b]")

    def test_body_contains_review_content(self) -> None:
        """Review analysis text is preserved in body."""
        output = self._make_output()
        assert "delegation gate" in output

    def test_separator_present(self) -> None:
        """'---' separator line is present."""
        output = self._make_output()
        assert "\n---\n" in output

    def test_footer_confidence_reflects_research_score(self) -> None:
        """Footer confidence matches research delegation score (0.910)."""
        output = self._make_output()
        assert "confidence=0.910" in output

    def test_footer_contains_research_intent_reason(self) -> None:
        """Footer includes the 'research' intent delegation reason."""
        output = self._make_output()
        assert "research" in output.split("\n---\n")[-1]

    def test_savings_present_for_research_intent(self) -> None:
        """Savings present; RESEARCH intent has lower but positive savings vs. doc gen."""
        output = self._make_output()
        assert "~$" in output

    def test_savings_lower_than_doc_gen(self) -> None:
        """RESEARCH savings < DOCUMENT savings (400 vs 800 avg tokens)."""
        doc_output = ldh._format_delegated_response(
            response_text="doc",
            model_name="qwen2.5-14b",
            delegation_score=_doc_gen_score(),
            prompt=_DOC_GEN_PROMPT,
        )
        review_output = self._make_output()
        # Use precise pattern: digits + dot + digits, no trailing sentence period.
        doc_savings_match = re.search(r"~\$([0-9]+\.[0-9]+)", doc_output)
        review_savings_match = re.search(r"~\$([0-9]+\.[0-9]+)", review_output)
        assert doc_savings_match and review_savings_match
        doc_savings = float(doc_savings_match.group(1))
        review_savings = float(review_savings_match.group(1))
        assert review_savings < doc_savings, (
            f"Expected RESEARCH savings ({review_savings}) < DOCUMENT savings ({doc_savings})"
        )


# ---------------------------------------------------------------------------
# 2. ModelDelegatedResponse parsing tests
# ---------------------------------------------------------------------------


class TestModelDelegatedResponseParsing:
    """Validate that parse_delegated_response() extracts all fields correctly."""

    def _canonical_output(
        self,
        response_text: str = "The answer.",
        model_name: str = "qwen2.5-14b",
        confidence: float = 0.950,
        savings_usd: float = 0.0112,
        reasons: list[str] | None = None,
    ) -> str:
        score = _make_delegation_score(
            delegatable=True,
            confidence=confidence,
            delegate_to_model=model_name,
            estimated_savings_usd=savings_usd,
            reasons=reasons or ["intent 'document' is in the delegation allow-list"],
        )
        return ldh._format_delegated_response(
            response_text=response_text,
            model_name=model_name,
            delegation_score=score,
            prompt="document this function",
        )

    def test_parse_returns_model_delegated_response(self) -> None:
        """parse_delegated_response returns a ModelDelegatedResponse for valid input."""
        output = self._canonical_output()
        parsed = parse_delegated_response(output)
        assert parsed is not None
        assert isinstance(parsed, ModelDelegatedResponse)

    def test_parse_attribution_line(self) -> None:
        """Parsed attribution_line matches the full bracket format."""
        output = self._canonical_output(model_name="qwen2.5-14b")
        parsed = parse_delegated_response(output)
        assert parsed is not None
        assert parsed.attribution_line == "[Local Model Response - qwen2.5-14b]"

    def test_parse_model_name_extracted(self) -> None:
        """model_name is extracted from the attribution line."""
        output = self._canonical_output(model_name="deepseek-r1-32b")
        parsed = parse_delegated_response(output)
        assert parsed is not None
        assert parsed.model_name == "deepseek-r1-32b"

    def test_parse_body_contains_response_text(self) -> None:
        """Body field contains the LLM-provided response text."""
        output = self._canonical_output(response_text="Kafka is a streaming platform.")
        parsed = parse_delegated_response(output)
        assert parsed is not None
        assert "Kafka is a streaming platform." in parsed.body

    def test_parse_body_does_not_contain_footer(self) -> None:
        """Body field is clean — does not bleed into footer content."""
        output = self._canonical_output()
        parsed = parse_delegated_response(output)
        assert parsed is not None
        assert "Delegated via local model" not in parsed.body

    def test_parse_confidence_extracted_as_float(self) -> None:
        """confidence field is extracted as a float matching the source score."""
        output = self._canonical_output(confidence=0.975)
        parsed = parse_delegated_response(output)
        assert parsed is not None
        assert abs(parsed.confidence - 0.975) < 1e-6

    def test_parse_savings_dollar_amount(self) -> None:
        """savings_str contains exact ~$X.XXXX value for positive savings.

        Pins the exact extracted value so a trailing-period regression (where
        _SAVINGS_RE consumes the sentence-separator "." and returns "~$0.0112."
        instead of "~$0.0112") would be caught immediately.
        """
        output = self._canonical_output(savings_usd=0.0112)
        parsed = parse_delegated_response(output)
        assert parsed is not None
        assert parsed.savings_str == "~$0.0112"

    def test_parse_savings_local_inference_when_zero(self) -> None:
        """savings_str contains 'local inference' when estimated_savings_usd is 0."""
        output = self._canonical_output(savings_usd=0.0)
        parsed = parse_delegated_response(output)
        assert parsed is not None
        assert parsed.savings_str == "local inference"

    def test_parse_reasons_extracted(self) -> None:
        """reasons field is extracted from the footer Reason: clause."""
        output = self._canonical_output(
            reasons=[
                "intent 'document' is in the delegation allow-list",
                "confidence 0.950 exceeds threshold 0.900",
            ]
        )
        parsed = parse_delegated_response(output)
        assert parsed is not None
        assert "document" in parsed.reasons

    def test_parse_all_three_delegation_types(self) -> None:
        """parse_delegated_response succeeds for all three delegatable intent types."""
        for score_fn, prompt, tag in [
            (_doc_gen_score, _DOC_GEN_PROMPT, "document"),
            (_boilerplate_score, _BOILERPLATE_PROMPT, "test"),
            (_code_review_score, _CODE_REVIEW_PROMPT, "research"),
        ]:
            output = ldh._format_delegated_response(
                response_text=f"Answer for {tag}.",
                model_name="qwen2.5-14b",
                delegation_score=score_fn(),
                prompt=prompt,
            )
            parsed = parse_delegated_response(output)
            assert parsed is not None, f"Parsing failed for intent={tag}"
            assert parsed.model_name == "qwen2.5-14b"

    def test_parse_multiline_body_preserved(self) -> None:
        """Body field preserves multiline content (code blocks, markdown)."""
        multiline = "Line 1\nLine 2\n```python\ncode here\n```"
        output = self._canonical_output(response_text=multiline)
        parsed = parse_delegated_response(output)
        assert parsed is not None
        assert "Line 1" in parsed.body
        assert "Line 2" in parsed.body
        assert "code here" in parsed.body

    def test_roundtrip_confidence_precision(self) -> None:
        """Confidence value roundtrips with three decimal places precision."""
        for conf in (0.900, 0.950, 0.975, 1.000):
            output = self._canonical_output(confidence=conf)
            parsed = parse_delegated_response(output)
            assert parsed is not None
            assert abs(parsed.confidence - conf) < 0.001, (
                f"Confidence roundtrip failed for {conf}: got {parsed.confidence}"
            )


# ---------------------------------------------------------------------------
# 3. Bad output recovery tests
# ---------------------------------------------------------------------------


class TestBadOutputRecovery:
    """parse_delegated_response handles malformed/missing sections gracefully."""

    def test_missing_attribution_returns_none(self) -> None:
        """Input without [Local Model Response - ...] header → None."""
        text = "Just a response body.\n\n---\nDelegated via local model: confidence=0.950, savings=local inference. Reason: ok"
        result = parse_delegated_response(text)
        assert result is None

    def test_missing_separator_returns_none(self) -> None:
        """Input without '---' separator → None (body/footer boundary ambiguous)."""
        text = "[Local Model Response - qwen2.5-14b]\n\nHere is the answer.\nDelegated via local model: confidence=0.950, savings=local inference. Reason: ok"
        result = parse_delegated_response(text)
        assert result is None

    def test_missing_confidence_returns_none(self) -> None:
        """Footer without confidence=X.XXX → None (cannot populate required field)."""
        text = "[Local Model Response - qwen2.5-14b]\n\nHere is the answer.\n\n---\nDelegated via local model: savings=local inference. Reason: ok"
        result = parse_delegated_response(text)
        assert result is None

    def test_empty_string_returns_none(self) -> None:
        """Completely empty input → None."""
        result = parse_delegated_response("")
        assert result is None

    def test_only_whitespace_returns_none(self) -> None:
        """Whitespace-only input → None."""
        result = parse_delegated_response("   \n\n\t  ")
        assert result is None

    def test_truncated_mid_body_returns_none(self) -> None:
        """Input truncated after header (no separator) → None."""
        text = "[Local Model Response - qwen2.5-14b]\n\nThis response was truncated"
        result = parse_delegated_response(text)
        assert result is None

    def test_empty_body_still_parses(self) -> None:
        """Empty body (no text between header and separator) is valid — body='', not None."""
        text = (
            "[Local Model Response - qwen2.5-14b]\n\n"
            "\n\n---\n"
            "Delegated via local model: confidence=0.950, savings=local inference. Reason: ok"
        )
        result = parse_delegated_response(text)
        # Should parse successfully with empty body
        assert result is not None
        assert result.body == ""

    def test_malformed_confidence_value_returns_none(self) -> None:
        """Non-numeric confidence value → None (regex does not match)."""
        text = (
            "[Local Model Response - qwen2.5-14b]\n\nAnswer.\n\n---\n"
            "Delegated via local model: confidence=N/A, savings=local inference. Reason: ok"
        )
        result = parse_delegated_response(text)
        assert result is None

    def test_model_name_with_special_chars_parses(self) -> None:
        """Model names containing hyphens and dots are extracted correctly."""
        text = (
            "[Local Model Response - qwen2.5-coder-14b-instruct]\n\n"
            "Answer body.\n\n---\n"
            "Delegated via local model: confidence=0.950, savings=local inference. Reason: ok"
        )
        result = parse_delegated_response(text)
        assert result is not None
        assert result.model_name == "qwen2.5-coder-14b-instruct"

    def test_braces_in_model_name_are_escaped_in_output(self) -> None:
        """Model names with braces do not crash _format_delegated_response.

        Regression guard: _format_delegated_response escapes braces in model_name
        via .replace("{", "{{") before passing to str.format().  The escaping
        doubles the braces in the OUTPUT (str.format() only collapses {{ → {
        when they appear in the FORMAT TEMPLATE, not in substituted values).
        So a model_name of "local{test}" produces "local{{test}}" in the output.

        KNOWN DISPLAY ARTIFACT: If a model name contains braces, end-users will
        literally see the doubled braces in their UI (e.g., "local{{test}}" rather
        than "local{test}").  This is an accepted side-effect of the escaping
        strategy; model names with braces are not expected in normal usage.

        What matters here:
          1. The handler does not raise KeyError/ValueError.
          2. The output contains the (escaped) model name.

        The assertion below asserting "{{" is intentional — it snapshots this
        known display artifact, not a typo.
        """
        score = _make_delegation_score(
            delegatable=True,
            confidence=0.950,
            reasons=["intent 'research' is in the delegation allow-list"],
        )
        # Model name containing braces (would break str.format() without escaping)
        output = ldh._format_delegated_response(
            response_text="answer",
            model_name="local{test}",
            delegation_score=score,
            prompt="what is this",
        )
        # Braces are doubled in the output because str.format() only un-doubles
        # {{ when it appears in the template string, not in substituted values.
        # known limitation: accepted, not tracked separately – brace-containing model names are not expected in production
        assert "[Local Model Response - local{{test}}]" in output
        # Confidence and savings still appear correctly
        assert "confidence=0.950" in output

    def test_llm_response_containing_separator_string(self) -> None:
        """Body text containing '---' is handled: parse finds the FIRST separator."""
        score = _make_delegation_score(
            delegatable=True,
            confidence=0.920,
            reasons=["intent 'test' is in the delegation allow-list"],
        )
        # Body text itself contains '---' (common in Markdown)
        body_with_dashes = (
            "Here is a markdown separator:\n\n---\n\nBut this is still body."
        )
        output = ldh._format_delegated_response(
            response_text=body_with_dashes,
            model_name="qwen2.5-14b",
            delegation_score=score,
            prompt="document this",
        )
        # The presence of '---' in the body does not prevent successful parsing
        # (confidence appears after the first separator)
        result = parse_delegated_response(output)
        assert result is not None
        # Confidence is still extracted correctly
        assert abs(result.confidence - 0.920) < 0.001
        # Known limitation: the parser uses find() which matches the FIRST '---'.
        # When the LLM body itself contains '---', everything after that embedded
        # separator is silently dropped from parsed.body and treated as footer text.
        # The body is truncated at the first separator, not the last.
        assert result.body == "Here is a markdown separator:"
        assert "But this is still body." not in result.body

    def test_llm_response_with_separator_and_no_trailing_body(self) -> None:
        """Degenerate case: LLM body ends with '---' and confidence-like text immediately after.

        This tests the worst-case scenario where the LLM body itself contains '---'
        followed by fake footer-like content (e.g., confidence=X.XXX), with NO
        additional real body text after the embedded separator.  The real footer
        produced by _format_delegated_response is still appended after the body.

        KNOWN LIMITATION: The parser uses find() which matches the FIRST '---'.
        When the LLM body contains an embedded '---' followed by a confidence-like
        value, parse_delegated_response() treats that embedded confidence as the
        real one.  The actual confidence from the real footer (0.920 below) is NOT
        extracted — the fake embedded confidence (0.850) is returned instead.

        This is an accepted design trade-off: the parser does not search for the
        LAST separator or try to validate which confidence value belongs to the
        real footer.  Callers should treat the extracted confidence as approximate
        when the LLM body may contain Markdown separators followed by numeric values.
        """
        score = _make_delegation_score(
            delegatable=True,
            confidence=0.920,
            reasons=["intent 'test' is in the delegation allow-list"],
        )
        # LLM body contains '---' with confidence-like text and NO trailing content
        # after the embedded separator — the degenerate case where the real footer
        # confidence is shadowed by the embedded fake one.
        body_with_fake_footer = "Main body.\n---\nconfidence=0.850\nsavings=local inference\nreason=Test reason"
        output = ldh._format_delegated_response(
            response_text=body_with_fake_footer,
            model_name="qwen2.5-14b",
            delegation_score=score,
            prompt="document this",
        )
        result = parse_delegated_response(output)
        # Parsing still succeeds (does not return None) because a confidence value
        # IS found in the "footer" region (the embedded fake one).
        assert result is not None
        # KNOWN LIMITATION: the extracted confidence is the embedded fake value
        # (0.850), NOT the real delegation confidence (0.920), because the parser
        # finds the first '---' separator and the first confidence= value after it.
        # known limitation: accepted, not tracked separately – rfind()-based fix deferred; callers treat confidence as approximate when body contains embedded separators
        assert abs(result.confidence - 0.850) < 0.001, (
            f"Expected embedded fake confidence 0.850, got {result.confidence:.3f}. "
            "If this assertion fails, the parser was improved to find the real footer."
        )

    def test_handle_delegation_never_raises_on_any_prompt_type(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """handle_delegation returns dict (never raises) for all three prompt types.

        This is the end-to-end recovery guard: even if the LLM returns garbage,
        the handler exits cleanly.
        """
        monkeypatch.setenv("ENABLE_LOCAL_INFERENCE_PIPELINE", "true")
        monkeypatch.setenv("ENABLE_LOCAL_DELEGATION", "true")

        # TODO: refactor to pytest.mark.parametrize (deferred, low priority)
        for prompt, score_fn in [
            (_DOC_GEN_PROMPT, _doc_gen_score),
            (_BOILERPLATE_PROMPT, _boilerplate_score),
            (_CODE_REVIEW_PROMPT, _code_review_score),
        ]:
            with patch.object(ldh, "_classify_prompt", return_value=score_fn()):
                with patch.object(
                    ldh,
                    "_get_delegate_endpoint_url",
                    return_value="http://localhost:8200",
                ):
                    # Intentional design: the outer patch.object contexts for
                    # _classify_prompt and _get_delegate_endpoint_url are shared
                    # across all bad_response iterations below.  This is correct
                    # because both mocks represent configuration/static behavior
                    # (classification result and endpoint URL) that does not vary
                    # between LLM response scenarios — they are set once per
                    # (prompt, score_fn) pair and remain stable.  If handle_delegation
                    # were ever refactored to re-call _classify_prompt multiple times
                    # per invocation, the outer mock would need to be moved inside
                    # the bad_response loop.  The current design is intentional,
                    # not an oversight.
                    #
                    # Cases where the handler must return delegated=False explicitly:
                    # empty or whitespace response_text triggers the empty_response guard.
                    for bad_response in [
                        ("", "local"),
                        ("   ", "local"),
                    ]:
                        with patch.object(
                            ldh, "_call_local_llm", return_value=bad_response
                        ):
                            result = ldh.handle_delegation(prompt, "corr-bad")
                        assert "delegated" in result, (
                            f"'delegated' key missing for prompt={prompt!r}, "
                            f"response={bad_response!r}"
                        )
                        assert result["delegated"] is False, (
                            f"Expected delegated=False for empty/whitespace response, "
                            f"prompt={prompt!r}, response={bad_response!r}"
                        )

                    # Cases where we only require the handler not to raise and
                    # return a bool — the exact value depends on handler heuristics.
                    # ("some response text", None) covers the case where the
                    # LLM returns a non-empty body but a None model name — the
                    # handler must not raise even when model_name is None.
                    for bad_response in [
                        None,
                        ("some response text", None),
                    ]:
                        with patch.object(
                            ldh, "_call_local_llm", return_value=bad_response
                        ):
                            result = ldh.handle_delegation(prompt, "corr-bad")
                        assert "delegated" in result, (
                            f"'delegated' key missing for prompt={prompt!r}, "
                            f"response={bad_response!r}"
                        )
                        assert isinstance(result["delegated"], bool)
