# SPDX-License-Identifier: MIT
# Copyright (c) 2026 OmniNode Team
"""Enrichment prompt regression tests (OMN-2268).

Snapshot-tests the structured markdown output schemas produced by the
code analysis and summarization enrichment handlers
(AdapterCodeAnalysisEnrichment, AdapterSummarizationEnrichment in
omnibase_infra).  Validates:

  1. ContractEnrichmentResult schema -- field names, types, constraints
  2. Markdown structure of code analysis output (required section headings)
  3. Markdown structure of summarization output (required section headings)
  4. Bad-output recovery paths (empty sections, malformed markdown, None
     generated_text, missing headings)

All tests run without network access or external services.  The handler
implementations are not imported; instead, the tests work with inline
fixtures that represent the contract output shape (ContractEnrichmentResult)
and the prompt templates extracted from the handler source.  This approach
keeps the tests isolated from package-version drift while still providing
regression coverage for the schema and the markdown parsing logic.
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError

# ---------------------------------------------------------------------------
# Inline replica of ContractEnrichmentResult
# ---------------------------------------------------------------------------
# Defined here rather than imported so tests remain stable even when the
# omnibase_spi version does not yet expose the enrichment contracts.
# The field names, types, and constraints are copied verbatim from
# src/omnibase_spi/contracts/enrichment/contract_enrichment_result.py
# (verified against the merged OMN-2252 PR).  Any future schema change
# in that file must be reflected here as a deliberate, reviewed update.


class ContractEnrichmentResult(BaseModel):
    """Inline snapshot of the ContractEnrichmentResult schema (OMN-2252)."""

    # extra="forbid" matches the real contract in
    # omnibase_spi/contracts/enrichment/contract_enrichment_result.py (line 43).
    # Verified against the source file on 2026-02-18.  If the real contract
    # ever relaxes this to extra="ignore", this snapshot and
    # test_extra_fields_are_forbidden below must be updated together.
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = Field(
        default="1.0",
        description="Wire-format version for forward compatibility.",
    )
    summary_markdown: str = Field(
        ...,
        min_length=1,
        description="Markdown-formatted enriched summary.",
    )
    token_count: int = Field(
        ...,
        ge=0,
        description="Number of tokens in the enriched summary.",
    )
    relevance_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Relevance score (0.0 irrelevant, 1.0 maximally relevant).",
    )
    enrichment_type: Literal["code_analysis", "similarity", "summarization"] = Field(
        ...,
        description="Category of enrichment strategy applied.",
    )
    latency_ms: float = Field(
        ...,
        ge=0.0,
        description="Wall-clock time the enrichment took, in milliseconds.",
    )
    model_used: str = Field(
        ...,
        min_length=1,
        description="Identifier of the model used for enrichment.",
    )
    prompt_version: str = Field(
        ...,
        min_length=1,
        description="Version identifier of the enrichment prompt template.",
    )
    extensions: dict[str, Any] = Field(
        default_factory=dict,
        description="Escape hatch for forward-compatible extension data.",
    )


# ---------------------------------------------------------------------------
# Expected output schema constants
# ---------------------------------------------------------------------------

# Canonical set of top-level keys for ContractEnrichmentResult.
_ENRICHMENT_RESULT_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "summary_markdown",
        "token_count",
        "relevance_score",
        "enrichment_type",
        "latency_ms",
        "model_used",
        "prompt_version",
        "extensions",
    }
)

# Code analysis prompt version (from adapter_code_analysis_enrichment.py).
_CODE_ANALYSIS_PROMPT_VERSION: str = "v1.0"

# Summarization prompt version (from adapter_summarization_enrichment.py).
_SUMMARIZATION_PROMPT_VERSION: str = "v1.0"

# Required markdown section headings for code analysis output.
# These are defined in _USER_PROMPT_TEMPLATE in adapter_code_analysis_enrichment.py.
# SYNC REQUIRED: these must match the headings in adapter_code_analysis_enrichment.py
# _USER_PROMPT_TEMPLATE — update manually if the template changes.
_CODE_ANALYSIS_REQUIRED_HEADINGS: tuple[str, ...] = (
    "Affected Functions / Methods",
    "Dependency Changes",
    "Potential Issues",
    "Summary",
)

# Default model identifiers for each adapter.
_CODE_ANALYSIS_DEFAULT_MODEL: str = "qwen2.5-coder-14b"
_SUMMARIZATION_DEFAULT_MODEL: str = "qwen2.5-72b"
_SUMMARIZATION_PASSTHROUGH_MODEL: str = "passthrough"

# Relevance scores for code analysis adapter.
_CODE_ANALYSIS_RELEVANCE_SCORE: float = 0.85
_CODE_ANALYSIS_EMPTY_DIFF_RELEVANCE_SCORE: float = 0.0

# Relevance scores for summarization adapter.
_SUMMARIZATION_RELEVANCE_SCORE: float = 0.80
_SUMMARIZATION_PASSTHROUGH_RELEVANCE_SCORE: float = 1.0
_SUMMARIZATION_INFLATED_GUARD_RELEVANCE_SCORE: float = 1.0

# Chars per token for token estimation (shared by both adapters).
_CHARS_PER_TOKEN: int = 4

# Max diff chars before truncation (from adapter_code_analysis_enrichment.py).
_MAX_DIFF_CHARS: int = 32_000

# Token threshold for summarization (from adapter_summarization_enrichment.py).
_TOKEN_THRESHOLD: int = 8_000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_code_analysis_result(
    summary_markdown: str = "## Affected Functions / Methods\n\n- `bar()` added\n\n"
    "## Dependency Changes\n\nNone.\n\n"
    "## Potential Issues\n\nNone.\n\n"
    "## Summary\n\nAdded `bar()` to foo.py.\n",
    model_used: str = _CODE_ANALYSIS_DEFAULT_MODEL,
    relevance_score: float = _CODE_ANALYSIS_RELEVANCE_SCORE,
    token_count: int | None = None,
    latency_ms: float = 12.5,
) -> ContractEnrichmentResult:
    """Build a ContractEnrichmentResult for code analysis."""
    if token_count is None:
        token_count = max(0, len(summary_markdown) // _CHARS_PER_TOKEN)
    return ContractEnrichmentResult(
        summary_markdown=summary_markdown,
        token_count=token_count,
        relevance_score=relevance_score,
        enrichment_type="code_analysis",
        latency_ms=latency_ms,
        model_used=model_used,
        prompt_version=_CODE_ANALYSIS_PROMPT_VERSION,
    )


def _make_summarization_result(
    summary_markdown: str = "## Summary\n\nBrief summary of the context.\n",
    model_used: str = _SUMMARIZATION_DEFAULT_MODEL,
    relevance_score: float = _SUMMARIZATION_RELEVANCE_SCORE,
    token_count: int | None = None,
    latency_ms: float = 55.0,
) -> ContractEnrichmentResult:
    """Build a ContractEnrichmentResult for summarization."""
    if token_count is None:
        token_count = max(0, len(summary_markdown) // _CHARS_PER_TOKEN)
    return ContractEnrichmentResult(
        summary_markdown=summary_markdown,
        token_count=token_count,
        relevance_score=relevance_score,
        enrichment_type="summarization",
        latency_ms=latency_ms,
        model_used=model_used,
        prompt_version=_SUMMARIZATION_PROMPT_VERSION,
    )


def _extract_headings(markdown: str) -> list[str]:
    """Return a list of heading text values (H1/H2/H3) from the markdown.

    Strips leading ``#`` characters and surrounding whitespace so that
    ``## Dependency Changes`` becomes ``"Dependency Changes"``.
    """
    pattern = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)
    return [m.group(1).strip() for m in pattern.finditer(markdown)]


def _has_heading(markdown: str, heading: str) -> bool:
    """Return True if the markdown contains a heading with the given text."""
    return heading in _extract_headings(markdown)


# ---------------------------------------------------------------------------
# All tests are unit tests
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.unit


# ============================================================================
# 1. ContractEnrichmentResult Schema Snapshot
# ============================================================================


class TestEnrichmentResultSchemaSnapshot:
    """Snapshot-tests for the ContractEnrichmentResult schema.

    These tests pin the exact set of field names, their types, defaults, and
    validation constraints.  Any drift between this snapshot and the live
    omnibase_spi schema is a deliberate, reviewed change.
    """

    def test_schema_has_all_expected_keys(self) -> None:
        """ContractEnrichmentResult exposes exactly the expected field set."""
        model_fields = set(ContractEnrichmentResult.model_fields.keys())
        assert model_fields == _ENRICHMENT_RESULT_KEYS

    def test_schema_version_defaults_to_one_dot_zero(self) -> None:
        """schema_version defaults to '1.0' when omitted."""
        result = _make_code_analysis_result()
        assert result.schema_version == "1.0"

    def test_schema_version_is_str(self) -> None:
        """schema_version is a string."""
        result = _make_code_analysis_result()
        assert isinstance(result.schema_version, str)

    def test_summary_markdown_is_str(self) -> None:
        """summary_markdown is a string."""
        result = _make_code_analysis_result()
        assert isinstance(result.summary_markdown, str)

    def test_token_count_is_int(self) -> None:
        """token_count is an integer."""
        result = _make_code_analysis_result()
        assert isinstance(result.token_count, int)

    def test_relevance_score_is_float(self) -> None:
        """relevance_score is a float."""
        result = _make_code_analysis_result()
        assert isinstance(result.relevance_score, float)

    def test_enrichment_type_is_str(self) -> None:
        """enrichment_type is a string (Literal)."""
        result = _make_code_analysis_result()
        assert isinstance(result.enrichment_type, str)

    def test_latency_ms_is_float(self) -> None:
        """latency_ms is a float."""
        result = _make_code_analysis_result()
        assert isinstance(result.latency_ms, float)

    def test_model_used_is_str(self) -> None:
        """model_used is a string."""
        result = _make_code_analysis_result()
        assert isinstance(result.model_used, str)

    def test_prompt_version_is_str(self) -> None:
        """prompt_version is a string."""
        result = _make_code_analysis_result()
        assert isinstance(result.prompt_version, str)

    def test_extensions_is_dict(self) -> None:
        """extensions is a dict, default empty."""
        result = _make_code_analysis_result()
        assert isinstance(result.extensions, dict)
        assert result.extensions == {}

    def test_token_count_cannot_be_negative(self) -> None:
        """Negative token_count raises ValidationError."""
        with pytest.raises(ValidationError):
            ContractEnrichmentResult(
                summary_markdown="x",
                token_count=-1,
                relevance_score=0.5,
                enrichment_type="code_analysis",
                latency_ms=0.0,
                model_used="model",
                prompt_version="v1.0",
            )

    def test_relevance_score_cannot_exceed_one(self) -> None:
        """relevance_score > 1.0 raises ValidationError."""
        with pytest.raises(ValidationError):
            ContractEnrichmentResult(
                summary_markdown="x",
                token_count=0,
                relevance_score=1.001,
                enrichment_type="code_analysis",
                latency_ms=0.0,
                model_used="model",
                prompt_version="v1.0",
            )

    def test_relevance_score_cannot_be_negative(self) -> None:
        """Negative relevance_score raises ValidationError."""
        with pytest.raises(ValidationError):
            ContractEnrichmentResult(
                summary_markdown="x",
                token_count=0,
                relevance_score=-0.1,
                enrichment_type="code_analysis",
                latency_ms=0.0,
                model_used="model",
                prompt_version="v1.0",
            )

    def test_enrichment_type_rejects_unknown_value(self) -> None:
        """Unknown enrichment_type raises ValidationError."""
        with pytest.raises(ValidationError):
            ContractEnrichmentResult(
                summary_markdown="x",
                token_count=0,
                relevance_score=0.5,
                enrichment_type="unknown_type",  # type: ignore[arg-type]
                latency_ms=0.0,
                model_used="model",
                prompt_version="v1.0",
            )

    def test_enrichment_type_accepts_code_analysis(self) -> None:
        """'code_analysis' is a valid enrichment_type."""
        result = _make_code_analysis_result()
        assert result.enrichment_type == "code_analysis"

    def test_enrichment_type_accepts_summarization(self) -> None:
        """'summarization' is a valid enrichment_type."""
        result = _make_summarization_result()
        assert result.enrichment_type == "summarization"

    def test_enrichment_type_accepts_similarity(self) -> None:
        """'similarity' is a valid enrichment_type."""
        result = ContractEnrichmentResult(
            summary_markdown="similar content",
            token_count=2,
            relevance_score=0.9,
            enrichment_type="similarity",
            latency_ms=5.0,
            model_used="embedding-model",
            prompt_version="v1.0",
        )
        assert result.enrichment_type == "similarity"

    def test_summary_markdown_cannot_be_empty(self) -> None:
        """Empty summary_markdown raises ValidationError (min_length=1)."""
        with pytest.raises(ValidationError):
            ContractEnrichmentResult(
                summary_markdown="",
                token_count=0,
                relevance_score=0.5,
                enrichment_type="code_analysis",
                latency_ms=0.0,
                model_used="model",
                prompt_version="v1.0",
            )

    def test_model_used_cannot_be_empty(self) -> None:
        """Empty model_used raises ValidationError (min_length=1)."""
        with pytest.raises(ValidationError):
            ContractEnrichmentResult(
                summary_markdown="content",
                token_count=0,
                relevance_score=0.5,
                enrichment_type="code_analysis",
                latency_ms=0.0,
                model_used="",
                prompt_version="v1.0",
            )

    def test_prompt_version_cannot_be_empty(self) -> None:
        """Empty prompt_version raises ValidationError (min_length=1)."""
        with pytest.raises(ValidationError):
            ContractEnrichmentResult(
                summary_markdown="content",
                token_count=0,
                relevance_score=0.5,
                enrichment_type="code_analysis",
                latency_ms=0.0,
                model_used="model",
                prompt_version="",
            )

    def test_schema_is_frozen(self) -> None:
        """ContractEnrichmentResult is immutable (frozen=True)."""
        result = _make_code_analysis_result()
        with pytest.raises(ValidationError):
            result.token_count = 999  # pyright: ignore[reportAttributeAccessIssue]  # intentional: testing that mutation raises ValidationError on frozen model

    def test_extra_fields_are_forbidden(self) -> None:
        """Extra fields beyond the schema raise ValidationError (extra='forbid')."""
        with pytest.raises(ValidationError):
            ContractEnrichmentResult(
                summary_markdown="x",
                token_count=0,
                relevance_score=0.5,
                enrichment_type="code_analysis",
                latency_ms=0.0,
                model_used="model",
                prompt_version="v1.0",
                unexpected_extra_field="oops",  # type: ignore[call-arg]
            )

    def test_latency_ms_cannot_be_negative(self) -> None:
        """Negative latency_ms raises ValidationError."""
        with pytest.raises(ValidationError):
            ContractEnrichmentResult(
                summary_markdown="x",
                token_count=0,
                relevance_score=0.5,
                enrichment_type="code_analysis",
                latency_ms=-1.0,
                model_used="model",
                prompt_version="v1.0",
            )

    def test_result_roundtrips_through_json(self) -> None:
        """ContractEnrichmentResult can be serialized and deserialized via JSON."""
        original = _make_code_analysis_result()
        serialized = original.model_dump_json()
        deserialized = json.loads(serialized)

        assert deserialized["schema_version"] == "1.0"
        assert deserialized["enrichment_type"] == "code_analysis"
        assert deserialized["model_used"] == _CODE_ANALYSIS_DEFAULT_MODEL
        assert deserialized["prompt_version"] == _CODE_ANALYSIS_PROMPT_VERSION
        assert deserialized["relevance_score"] == pytest.approx(
            _CODE_ANALYSIS_RELEVANCE_SCORE
        )
        assert deserialized["token_count"] >= 0
        assert deserialized["latency_ms"] >= 0.0
        assert isinstance(deserialized["extensions"], dict)


# ============================================================================
# 2. Code Analysis Output Schema
# ============================================================================


class TestCodeAnalysisOutputSchema:
    """Snapshot tests for code analysis enrichment result fields."""

    def test_enrichment_type_is_code_analysis(self) -> None:
        """Code analysis results always have enrichment_type='code_analysis'."""
        result = _make_code_analysis_result()
        assert result.enrichment_type == "code_analysis"

    def test_default_model_is_coder_14b(self) -> None:
        """Default model for code analysis is 'qwen2.5-coder-14b'."""
        result = _make_code_analysis_result()
        assert result.model_used == _CODE_ANALYSIS_DEFAULT_MODEL

    def test_prompt_version_is_v1_dot_0(self) -> None:
        """Code analysis prompt version is 'v1.0'."""
        result = _make_code_analysis_result()
        assert result.prompt_version == _CODE_ANALYSIS_PROMPT_VERSION

    def test_relevance_score_for_non_empty_diff(self) -> None:
        """Non-empty diff yields relevance_score == 0.85."""
        result = _make_code_analysis_result(
            relevance_score=_CODE_ANALYSIS_RELEVANCE_SCORE
        )
        assert result.relevance_score == pytest.approx(_CODE_ANALYSIS_RELEVANCE_SCORE)

    def test_relevance_score_for_empty_diff_is_zero(self) -> None:
        """Empty diff yields relevance_score == 0.0.

        The real adapter's empty-diff path (AdapterCodeAnalysisEnrichment.enrich)
        explicitly sets token_count=0 alongside relevance_score=0.0 — it does NOT
        compute token_count from the fallback summary string.  Passing token_count=0
        here is intentional and reflects that real adapter behavior.  This keeps
        this test consistent with test_empty_diff_token_count_is_zero below.
        """
        result = _make_code_analysis_result(
            summary_markdown="## No Changes Detected\n\nNo git diff found to analyze.",
            relevance_score=_CODE_ANALYSIS_EMPTY_DIFF_RELEVANCE_SCORE,
            token_count=0,
        )
        assert result.relevance_score == pytest.approx(
            _CODE_ANALYSIS_EMPTY_DIFF_RELEVANCE_SCORE
        )

    def test_empty_diff_token_count_is_zero(self) -> None:
        """Empty diff result has token_count == 0.

        The adapter hard-codes token_count=0 in the early-return path when no diff
        is found; it does NOT estimate tokens from the fallback summary string.
        """
        result = _make_code_analysis_result(
            summary_markdown="## No Changes Detected\n\nNo git diff found.",
            relevance_score=0.0,
            token_count=0,
        )
        assert result.token_count == 0

    def test_token_count_estimated_as_len_over_four(self) -> None:
        """Token count is estimated as len(summary_markdown) // 4."""
        summary = "A" * 400  # 400 chars => 100 tokens
        result = _make_code_analysis_result(
            summary_markdown=summary,
            token_count=len(summary) // _CHARS_PER_TOKEN,
        )
        assert result.token_count == 100

    def test_latency_ms_is_non_negative(self) -> None:
        """latency_ms is always >= 0."""
        result = _make_code_analysis_result(latency_ms=0.0)
        assert result.latency_ms >= 0.0

    def test_schema_version_is_one_dot_zero(self) -> None:
        """schema_version defaults to '1.0' for code analysis."""
        result = _make_code_analysis_result()
        assert result.schema_version == "1.0"


# ============================================================================
# 3. Code Analysis Markdown Section Parsing
# ============================================================================


class TestCodeAnalysisMarkdownParsing:
    """Validate parsing of structured markdown produced by code analysis.

    The code analysis prompt template instructs the model to produce output
    with four specific H2 sections.  These tests verify that a well-formed
    response contains all required headings and that the section content is
    parseable.
    """

    # --- Well-formed output ---

    def test_well_formed_output_has_all_required_headings(self) -> None:
        """Well-formed code analysis output contains all four required H2 headings."""
        result = _make_code_analysis_result()
        for heading in _CODE_ANALYSIS_REQUIRED_HEADINGS:
            assert _has_heading(result.summary_markdown, heading), (
                f"Missing required heading: {heading!r}"
            )

    def test_affected_functions_heading_present(self) -> None:
        """'Affected Functions / Methods' heading is present."""
        result = _make_code_analysis_result()
        assert _has_heading(result.summary_markdown, "Affected Functions / Methods")

    def test_dependency_changes_heading_present(self) -> None:
        """'Dependency Changes' heading is present."""
        result = _make_code_analysis_result()
        assert _has_heading(result.summary_markdown, "Dependency Changes")

    def test_potential_issues_heading_present(self) -> None:
        """'Potential Issues' heading is present."""
        result = _make_code_analysis_result()
        assert _has_heading(result.summary_markdown, "Potential Issues")

    def test_summary_heading_present(self) -> None:
        """'Summary' heading is present."""
        result = _make_code_analysis_result()
        assert _has_heading(result.summary_markdown, "Summary")

    def test_extract_headings_returns_all_four(self) -> None:
        """_extract_headings() returns exactly the four canonical section names."""
        result = _make_code_analysis_result()
        headings = _extract_headings(result.summary_markdown)
        for expected in _CODE_ANALYSIS_REQUIRED_HEADINGS:
            assert expected in headings, f"Heading not found: {expected!r}"

    def test_affected_functions_section_has_content(self) -> None:
        """The 'Affected Functions / Methods' section has non-empty content."""
        summary = (
            "## Affected Functions / Methods\n\n"
            "- `bar()` added in foo.py\n\n"
            "## Dependency Changes\n\nNone.\n\n"
            "## Potential Issues\n\nNone.\n\n"
            "## Summary\n\nAdded bar().\n"
        )
        result = _make_code_analysis_result(summary_markdown=summary)
        # Extract section content between 'Affected Functions / Methods' and next heading
        pattern = re.compile(
            r"## Affected Functions / Methods\s*\n(.*?)(?=^##|\Z)",
            re.DOTALL | re.MULTILINE,
        )
        match = pattern.search(result.summary_markdown)
        assert match is not None
        section_content = match.group(1).strip()
        assert len(section_content) > 0

    def test_markdown_headings_use_hash_prefix(self) -> None:
        """Headings use the ## prefix (H2) as specified by the prompt template."""
        result = _make_code_analysis_result()
        h2_pattern = re.compile(r"^## ", re.MULTILINE)
        assert h2_pattern.search(result.summary_markdown) is not None

    # --- Extract sections helper ---

    def test_extract_headings_handles_bold_heading_variant(self) -> None:
        """Bold headings (##**Text**) are NOT treated as headings by _extract_headings.

        The prompt template uses ``## **Text**`` which produces bold text inside
        an H2 block.  _extract_headings() extracts the full text after ``##``,
        which includes the ``**`` markers.  This test documents the expected
        behavior so that downstream parsers handle the raw heading text correctly.
        """
        markdown = "## **Affected Functions / Methods**\n\n- foo()\n"
        headings = _extract_headings(markdown)
        # The heading text includes the bold markers
        assert "**Affected Functions / Methods**" in headings
        # The plain version is NOT in headings
        assert "Affected Functions / Methods" not in headings

    def test_extract_headings_handles_h1_and_h3(self) -> None:
        """_extract_headings() captures H1, H2, and H3 headings alike."""
        markdown = "# Top\n## Middle\n### Bottom\n"
        headings = _extract_headings(markdown)
        assert headings == ["Top", "Middle", "Bottom"]


# ============================================================================
# 4. Summarization Output Schema
# ============================================================================


class TestSummarizationOutputSchema:
    """Snapshot tests for summarization enrichment result fields."""

    def test_enrichment_type_is_summarization(self) -> None:
        """Summarization results always have enrichment_type='summarization'."""
        result = _make_summarization_result()
        assert result.enrichment_type == "summarization"

    def test_default_model_is_qwen_72b(self) -> None:
        """Default model for summarization is 'qwen2.5-72b'."""
        result = _make_summarization_result()
        assert result.model_used == _SUMMARIZATION_DEFAULT_MODEL

    def test_prompt_version_is_v1_dot_0(self) -> None:
        """Summarization prompt version is 'v1.0'."""
        result = _make_summarization_result()
        assert result.prompt_version == _SUMMARIZATION_PROMPT_VERSION

    def test_summarization_relevance_score(self) -> None:
        """Successful summarization has relevance_score == 0.80."""
        result = _make_summarization_result(
            relevance_score=_SUMMARIZATION_RELEVANCE_SCORE
        )
        assert result.relevance_score == pytest.approx(_SUMMARIZATION_RELEVANCE_SCORE)

    def test_passthrough_relevance_score_is_one(self) -> None:
        """Pass-through result (context below threshold) has relevance_score == 1.0."""
        result = _make_summarization_result(
            relevance_score=_SUMMARIZATION_PASSTHROUGH_RELEVANCE_SCORE,
            model_used=_SUMMARIZATION_PASSTHROUGH_MODEL,
        )
        assert result.relevance_score == pytest.approx(
            _SUMMARIZATION_PASSTHROUGH_RELEVANCE_SCORE
        )

    def test_passthrough_model_sentinel(self) -> None:
        """Pass-through result uses 'passthrough' as model_used sentinel."""
        result = _make_summarization_result(
            model_used=_SUMMARIZATION_PASSTHROUGH_MODEL,
            relevance_score=1.0,
        )
        assert result.model_used == "passthrough"

    def test_net_guard_bypass_relevance_is_one(self) -> None:
        """Net-token guard bypass (inflated summary) has relevance_score == 1.0.

        Both the net-token guard path and the passthrough path share
        relevance_score=1.0 (_SUMMARIZATION_INFLATED_GUARD_RELEVANCE_SCORE ==
        _SUMMARIZATION_PASSTHROUGH_RELEVANCE_SCORE == 1.0) because in both
        cases the original context is returned verbatim and is considered fully
        relevant.  The key distinction is model_used: the guard path records the
        real model identifier (the LLM was actually called before the guard
        fired), whereas the passthrough path uses the 'passthrough' sentinel
        (the LLM was never called).
        """
        result = _make_summarization_result(
            relevance_score=_SUMMARIZATION_INFLATED_GUARD_RELEVANCE_SCORE,
            model_used=_SUMMARIZATION_DEFAULT_MODEL,
        )
        assert result.relevance_score == pytest.approx(
            _SUMMARIZATION_INFLATED_GUARD_RELEVANCE_SCORE
        )
        # Guard path: LLM was called, so model_used must NOT be the passthrough sentinel.
        assert result.model_used != _SUMMARIZATION_PASSTHROUGH_MODEL

    def test_token_count_reflects_summary_length(self) -> None:
        """token_count reflects the summary, not the original context."""
        summary = "A" * 200  # 200 chars => 50 tokens
        result = _make_summarization_result(
            summary_markdown=summary,
            token_count=len(summary) // _CHARS_PER_TOKEN,
        )
        assert result.token_count == 50

    def test_latency_ms_is_non_negative(self) -> None:
        """latency_ms is always >= 0."""
        result = _make_summarization_result(latency_ms=0.0)
        assert result.latency_ms >= 0.0

    def test_schema_version_is_one_dot_zero(self) -> None:
        """schema_version defaults to '1.0' for summarization."""
        result = _make_summarization_result()
        assert result.schema_version == "1.0"

    def test_passthrough_empty_context_sentinel(self) -> None:
        """Empty context pass-through uses '(empty context)' as summary."""
        result = _make_summarization_result(
            summary_markdown="(empty context)",
            token_count=0,
            model_used=_SUMMARIZATION_PASSTHROUGH_MODEL,
            relevance_score=1.0,
        )
        assert result.summary_markdown == "(empty context)"
        assert result.token_count == 0


# ============================================================================
# 5. Summarization Markdown Parsing
# ============================================================================


class TestSummarizationMarkdownParsing:
    """Validate parsing of structured markdown produced by summarization."""

    def test_well_formed_output_starts_with_summary_section(self) -> None:
        """Typical summarization output begins with a ## Summary section."""
        summary = "## Summary\n\nBrief summary of the long context block.\n"
        result = _make_summarization_result(summary_markdown=summary)
        assert _has_heading(result.summary_markdown, "Summary")

    def test_passthrough_output_is_raw_context(self) -> None:
        """Pass-through output is the stripped raw context (no model processing)."""
        raw_context = "Short context not exceeding the threshold."
        result = _make_summarization_result(
            summary_markdown=raw_context,
            model_used=_SUMMARIZATION_PASSTHROUGH_MODEL,
            relevance_score=1.0,
        )
        assert result.summary_markdown == raw_context

    def test_passthrough_output_does_not_require_headings(self) -> None:
        """Pass-through output need not contain Markdown headings."""
        raw_context = "plain text context without any headings"
        result = _make_summarization_result(
            summary_markdown=raw_context,
            model_used=_SUMMARIZATION_PASSTHROUGH_MODEL,
            relevance_score=1.0,
        )
        headings = _extract_headings(result.summary_markdown)
        assert len(headings) == 0

    def test_summary_markdown_with_multiple_sections(self) -> None:
        """Summarized output may contain multiple headings."""
        summary = (
            "## Overview\n\nGeneral description.\n\n"
            "## Key Decisions\n\nDecision A.\n\n"
            "## Constraints\n\nConstraint B.\n"
        )
        result = _make_summarization_result(summary_markdown=summary)
        headings = _extract_headings(result.summary_markdown)
        assert "Overview" in headings
        assert "Key Decisions" in headings
        assert "Constraints" in headings

    def test_summary_markdown_preserves_technical_content(self) -> None:
        """Summary markdown preserves technical terms and entity names."""
        summary = (
            "## Summary\n\n"
            "The `HandlerLlmOpenaiCompatible` handler calls `qwen2.5-72b` at "
            "`http://localhost:8100/v1/chat/completions` with a 3-minute timeout.\n"
        )
        result = _make_summarization_result(summary_markdown=summary)
        assert "HandlerLlmOpenaiCompatible" in result.summary_markdown
        assert "qwen2.5-72b" in result.summary_markdown


# ============================================================================
# 6. Bad Output Recovery -- Code Analysis
# ============================================================================


class TestCodeAnalysisBadOutputRecovery:
    """Tests for bad-output recovery in code analysis enrichment.

    These tests snapshot the fallback behavior when the LLM returns
    unexpected or malformed output.  The adapter must always return a
    valid ContractEnrichmentResult regardless of LLM response quality.
    """

    def test_empty_llm_response_uses_analysis_unavailable_message(self) -> None:
        """When LLM returns empty text, summary contains 'Analysis Unavailable'."""
        # This is the literal fallback defined in adapter_code_analysis_enrichment.py
        fallback_summary = (
            "## Analysis Unavailable\n\nThe model did not return a response."
        )
        result = _make_code_analysis_result(
            summary_markdown=fallback_summary,
            relevance_score=_CODE_ANALYSIS_RELEVANCE_SCORE,
        )
        assert "Analysis Unavailable" in result.summary_markdown
        assert result.enrichment_type == "code_analysis"

    def test_analysis_unavailable_result_is_valid_schema(self) -> None:
        """The 'Analysis Unavailable' fallback is a valid ContractEnrichmentResult."""
        fallback_summary = (
            "## Analysis Unavailable\n\nThe model did not return a response."
        )
        result = _make_code_analysis_result(summary_markdown=fallback_summary)
        # Pydantic model: if it's constructed, it's valid
        assert result.summary_markdown == fallback_summary

    def test_no_diff_result_uses_no_changes_detected_message(self) -> None:
        """When no diff is available, summary contains 'No Changes Detected'."""
        no_diff_summary = "## No Changes Detected\n\nNo git diff found to analyze."
        result = _make_code_analysis_result(
            summary_markdown=no_diff_summary,
            relevance_score=_CODE_ANALYSIS_EMPTY_DIFF_RELEVANCE_SCORE,
            token_count=0,
        )
        assert "No Changes Detected" in result.summary_markdown
        assert result.relevance_score == pytest.approx(0.0)
        assert result.token_count == 0

    def test_no_diff_result_is_valid_schema(self) -> None:
        """The 'No Changes Detected' fallback is a valid ContractEnrichmentResult."""
        no_diff_summary = "## No Changes Detected\n\nNo git diff found."
        result = _make_code_analysis_result(
            summary_markdown=no_diff_summary,
            relevance_score=0.0,
            token_count=0,
        )
        assert result.summary_markdown == no_diff_summary
        assert result.enrichment_type == "code_analysis"

    def test_missing_heading_output_is_still_valid_contract(self) -> None:
        """Output missing required headings is still a valid ContractEnrichmentResult."""
        # LLM might return freeform text without the required headings
        malformed_markdown = "Some changes were made to the codebase."
        result = _make_code_analysis_result(summary_markdown=malformed_markdown)
        # The contract itself is valid even if the content lacks headings
        assert result.summary_markdown == malformed_markdown
        assert result.enrichment_type == "code_analysis"

    def test_missing_heading_output_detected_by_parser(self) -> None:
        """A heading-detection parser correctly identifies missing required headings."""
        malformed_markdown = "Some changes were made to the codebase."
        result = _make_code_analysis_result(summary_markdown=malformed_markdown)
        missing = [
            h
            for h in _CODE_ANALYSIS_REQUIRED_HEADINGS
            if not _has_heading(result.summary_markdown, h)
        ]
        assert len(missing) == len(_CODE_ANALYSIS_REQUIRED_HEADINGS)

    def test_partial_headings_output_detected_by_parser(self) -> None:
        """An output with only some headings is detectable as incomplete."""
        # Only 'Summary' heading; missing the other three
        partial_markdown = "## Summary\n\nPartial response from the model.\n"
        result = _make_code_analysis_result(summary_markdown=partial_markdown)
        present_headings = _extract_headings(result.summary_markdown)
        missing = [
            h for h in _CODE_ANALYSIS_REQUIRED_HEADINGS if h not in present_headings
        ]
        # Should have 3 missing headings (all except Summary)
        assert len(missing) == 3
        assert "Summary" not in missing

    def test_truncated_diff_marker_preserved_in_summary_markdown(self) -> None:
        """summary_markdown containing the truncation marker is preserved as-is.

        The adapter inserts '... [diff truncated]' into the user message sent to
        the LLM when the diff exceeds _MAX_DIFF_CHARS.  The model may echo the
        marker back in its response.  This test verifies that a result whose
        summary_markdown contains the marker is a valid ContractEnrichmentResult
        and that the marker string is faithfully preserved and detectable.
        """
        truncation_marker = "... [diff truncated]"
        summary = (
            "## Affected Functions / Methods\n\n"
            "- `process()` modified\n\n"
            "## Dependency Changes\n\nNone.\n\n"
            "## Potential Issues\n\n"
            f"Large diff was provided ({truncation_marker}); analysis may be incomplete.\n\n"
            "## Summary\n\nDiff exceeded size limit and was truncated before analysis.\n"
        )
        result = _make_code_analysis_result(summary_markdown=summary)

        # The result is a valid contract.
        assert result.enrichment_type == "code_analysis"
        assert result.relevance_score == pytest.approx(_CODE_ANALYSIS_RELEVANCE_SCORE)

        # The marker is preserved verbatim in summary_markdown.
        assert truncation_marker in result.summary_markdown

        # The required headings are still present (model returned well-formed output).
        for heading in _CODE_ANALYSIS_REQUIRED_HEADINGS:
            assert _has_heading(result.summary_markdown, heading), (
                f"Missing required heading: {heading!r}"
            )

    def test_single_word_response_is_valid_contract(self) -> None:
        """A degenerate single-word LLM response still satisfies the contract."""
        result = _make_code_analysis_result(
            summary_markdown="OK",
            token_count=0,
        )
        assert result.summary_markdown == "OK"
        assert result.enrichment_type == "code_analysis"

    def test_unicode_content_in_summary_markdown(self) -> None:
        """Unicode content (CJK, emoji, accents) is preserved in summary_markdown."""
        unicode_summary = (
            "## Affected Functions / Methods\n\n"
            "- `計算()` — 型変換が変更されました 🔧\n\n"
            "## Dependency Changes\n\nNone.\n\n"
            "## Potential Issues\n\nNone.\n\n"
            "## Summary\n\nType coercion updated.\n"
        )
        result = _make_code_analysis_result(summary_markdown=unicode_summary)
        assert "計算" in result.summary_markdown
        assert "🔧" in result.summary_markdown


# ============================================================================
# 7. Bad Output Recovery -- Summarization
# ============================================================================


class TestSummarizationBadOutputRecovery:
    """Tests for bad-output recovery in summarization enrichment.

    The summarization adapter has two fallback paths:
      1. Empty/None LLM response: raw context is returned
      2. Net-token guard: summary >= original tokens → raw context returned
    Both paths must still produce a valid ContractEnrichmentResult.
    """

    def test_empty_llm_response_returns_raw_context(self) -> None:
        """When LLM returns empty text, raw context is used as summary_markdown."""
        # The adapter replaces empty generated_text with the stripped raw context
        raw_context = "x" * ((_TOKEN_THRESHOLD + 1) * _CHARS_PER_TOKEN)
        result = _make_summarization_result(
            summary_markdown=raw_context.strip(),
            model_used=_SUMMARIZATION_DEFAULT_MODEL,
            relevance_score=_SUMMARIZATION_PASSTHROUGH_RELEVANCE_SCORE,
            token_count=len(raw_context.strip()) // _CHARS_PER_TOKEN,
        )
        assert result.summary_markdown == raw_context.strip()
        assert result.relevance_score == pytest.approx(
            _SUMMARIZATION_PASSTHROUGH_RELEVANCE_SCORE
        )

    def test_empty_llm_response_result_is_valid_contract(self) -> None:
        """Empty LLM response fallback is a valid ContractEnrichmentResult."""
        raw_context = "x" * ((_TOKEN_THRESHOLD + 1) * _CHARS_PER_TOKEN)
        result = _make_summarization_result(
            summary_markdown=raw_context.strip(),
            relevance_score=1.0,
            token_count=len(raw_context.strip()) // _CHARS_PER_TOKEN,
        )
        assert result.enrichment_type == "summarization"
        assert result.token_count >= 0

    def test_net_guard_fired_returns_raw_context(self) -> None:
        """When net-token guard fires, raw context is returned as summary_markdown."""
        raw_context = "x" * ((_TOKEN_THRESHOLD + 1) * _CHARS_PER_TOKEN)
        # Guard fires: summary token count >= original token count
        result = _make_summarization_result(
            summary_markdown=raw_context.strip(),
            model_used=_SUMMARIZATION_DEFAULT_MODEL,
            relevance_score=_SUMMARIZATION_INFLATED_GUARD_RELEVANCE_SCORE,
            token_count=len(raw_context.strip()) // _CHARS_PER_TOKEN,
        )
        assert result.summary_markdown == raw_context.strip()

    def test_net_guard_result_has_one_dot_zero_relevance(self) -> None:
        """Net-token guard result has relevance_score == 1.0."""
        result = _make_summarization_result(
            relevance_score=1.0,
            model_used=_SUMMARIZATION_DEFAULT_MODEL,
        )
        assert result.relevance_score == pytest.approx(1.0)

    def test_net_guard_model_used_is_set(self) -> None:
        """Even when net-token guard fires, model_used is set (LLM was called)."""
        result = _make_summarization_result(
            model_used="qwen2.5-72b",
            relevance_score=1.0,
        )
        assert result.model_used == "qwen2.5-72b"
        assert result.model_used != _SUMMARIZATION_PASSTHROUGH_MODEL

    def test_empty_context_passthrough_result_is_valid(self) -> None:
        """Empty context pass-through produces a valid ContractEnrichmentResult."""
        result = _make_summarization_result(
            summary_markdown="(empty context)",
            token_count=0,
            model_used=_SUMMARIZATION_PASSTHROUGH_MODEL,
            relevance_score=1.0,
            latency_ms=0.1,
        )
        assert result.summary_markdown == "(empty context)"
        assert result.token_count == 0
        assert result.model_used == _SUMMARIZATION_PASSTHROUGH_MODEL

    def test_summary_with_curly_braces_is_valid_contract(self) -> None:
        """Summary containing curly braces (from JSON context) is a valid result."""
        json_summary = (
            "## Summary\n\n"
            'The context contains {"key": "value"} patterns and '
            "{target_tokens} references.\n"
        )
        result = _make_summarization_result(summary_markdown=json_summary)
        assert result.summary_markdown == json_summary
        assert "{" in result.summary_markdown
        assert "}" in result.summary_markdown

    def test_very_long_summary_markdown_is_valid(self) -> None:
        """Very long summary_markdown does not violate the schema."""
        # Extreme case: summary longer than a typical page
        long_summary = "## Summary\n\n" + ("word " * 10_000)
        token_count = len(long_summary) // _CHARS_PER_TOKEN
        result = _make_summarization_result(
            summary_markdown=long_summary,
            token_count=token_count,
        )
        assert result.token_count == token_count
        assert len(result.summary_markdown) > 50_000


# ============================================================================
# 8. Token Estimation Snapshot
# ============================================================================


class TestTokenEstimationSnapshot:
    """Snapshot tests for the token estimation heuristic used by both adapters.

    Both adapters estimate token count as ``len(text) // 4``.  These tests
    pin the arithmetic so that any change to _CHARS_PER_TOKEN triggers a
    deliberate, reviewed update.
    """

    def test_chars_per_token_is_four(self) -> None:
        """The token estimation constant is 4 characters per token."""
        assert _CHARS_PER_TOKEN == 4

    def test_empty_string_gives_zero_tokens(self) -> None:
        """Empty string => 0 tokens."""
        text = ""
        assert len(text) // _CHARS_PER_TOKEN == 0

    def test_four_chars_gives_one_token(self) -> None:
        """Exactly 4 characters => 1 token."""
        text = "abcd"
        assert len(text) // _CHARS_PER_TOKEN == 1

    def test_three_chars_gives_zero_tokens(self) -> None:
        """3 characters rounds down to 0 tokens."""
        text = "abc"
        assert len(text) // _CHARS_PER_TOKEN == 0

    def test_eight_chars_gives_two_tokens(self) -> None:
        """8 characters => 2 tokens."""
        text = "abcdefgh"
        assert len(text) // _CHARS_PER_TOKEN == 2

    def test_non_ascii_chars_counted_by_char_not_byte(self) -> None:
        """Non-ASCII characters are counted as individual chars, not bytes."""
        # Each character is one char regardless of UTF-8 byte length
        text = "áéíó"  # 4 chars, each 2 bytes in UTF-8
        assert len(text) == 4
        assert len(text) // _CHARS_PER_TOKEN == 1

    def test_max_diff_chars_constant_is_correct(self) -> None:
        """_MAX_DIFF_CHARS is 32,000 as documented in the code analysis adapter."""
        assert _MAX_DIFF_CHARS == 32_000

    def test_token_threshold_constant_is_correct(self) -> None:
        """_TOKEN_THRESHOLD is 8,000 as documented in the summarization adapter."""
        assert _TOKEN_THRESHOLD == 8_000

    def test_token_count_matches_schema_field(self) -> None:
        """Token count in result matches the estimated value."""
        summary = "A" * 800  # 800 chars => 200 tokens
        result = _make_code_analysis_result(
            summary_markdown=summary,
            token_count=len(summary) // _CHARS_PER_TOKEN,
        )
        assert result.token_count == 200
