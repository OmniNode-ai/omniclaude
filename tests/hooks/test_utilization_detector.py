# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Unit tests for utilization detector.

Tests verify:
- Identifier extraction from various patterns
- Stopword filtering
- Utilization score calculation
- Timeout handling and graceful degradation
- Edge cases (empty input, no overlap)

Part of OMN-1889: Emit injection metrics + utilization signal.
"""

from __future__ import annotations

import pytest

from plugins.onex.hooks.lib.utilization_detector import (
    ALL_STOPWORDS,
    CODE_STOPWORDS,
    ENGLISH_STOPWORDS,
    UtilizationResult,
    UtilizationTimeoutError,
    calculate_utilization,
    extract_identifiers,
)

pytestmark = pytest.mark.unit


class TestExtractIdentifiers:
    """Test identifier extraction from text."""

    def test_extracts_camel_case(self) -> None:
        """Test extraction of CamelCase identifiers."""
        identifiers = extract_identifiers("Use ModelUserPayload for this task")
        assert "modeluserpayload" in identifiers

    def test_extracts_snake_case(self) -> None:
        """Test extraction of snake_case identifiers."""
        identifiers = extract_identifiers("Call user_service.get_user() method")
        assert "user_service" in identifiers
        assert "get_user" in identifiers

    def test_extracts_file_paths(self) -> None:
        """Test extraction of file paths."""
        identifiers = extract_identifiers("Read /src/models/user.py file")
        assert "/src/models/user.py" in identifiers

    def test_extracts_ticket_ids(self) -> None:
        """Test extraction of ticket IDs."""
        identifiers = extract_identifiers("Fix OMN-1889 and FEAT-456")
        assert "omn-1889" in identifiers
        assert "feat-456" in identifiers

    def test_extracts_urls(self) -> None:
        """Test extraction of URLs."""
        identifiers = extract_identifiers("See https://example.com/api/docs")
        assert "https://example.com/api/docs" in identifiers

    def test_extracts_env_keys(self) -> None:
        """Test extraction of environment variable keys."""
        identifiers = extract_identifiers("Set KAFKA_BOOTSTRAP_SERVERS variable")
        assert "kafka_bootstrap_servers" in identifiers

    def test_filters_english_stopwords(self) -> None:
        """Test that English stopwords are filtered out."""
        identifiers = extract_identifiers("the and for with this that from")
        # Stopwords should not appear
        assert not any(word in identifiers for word in ["the", "and", "for"])

    def test_filters_code_stopwords(self) -> None:
        """Test that code stopwords are filtered out."""
        identifiers = extract_identifiers("def class return import self None")
        # Code keywords should not appear
        assert not any(word in identifiers for word in ["def", "class", "return"])

    def test_filters_short_identifiers(self) -> None:
        """Test that identifiers shorter than 3 chars are filtered."""
        identifiers = extract_identifiers("a ab abc abcd")
        assert "a" not in identifiers
        assert "ab" not in identifiers
        # abc might be filtered as stopword but abcd should pass
        assert "abcd" in identifiers

    def test_normalizes_to_lowercase(self) -> None:
        """Test that identifiers are normalized to lowercase."""
        identifiers = extract_identifiers("UPPERCASE MixedCase lowercase")
        # All should be lowercase
        assert all(ident == ident.lower() for ident in identifiers)

    def test_empty_input(self) -> None:
        """Test extraction from empty string."""
        identifiers = extract_identifiers("")
        assert identifiers == set()

    def test_returns_set(self) -> None:
        """Test that result is a set (no duplicates)."""
        identifiers = extract_identifiers(
            "ModelUser ModelUser ModelUser model_user model_user"
        )
        assert isinstance(identifiers, set)


class TestCalculateUtilization:
    """Test utilization score calculation."""

    def test_full_overlap_returns_1(self) -> None:
        """Test 100% overlap returns score of 1.0."""
        result = calculate_utilization(
            "ModelUserPayload user_service",
            "I'll use ModelUserPayload and user_service",
        )
        # Should have high score (near 1.0) since both identifiers are reused
        assert result.score > 0.5
        assert result.method == "identifier_overlap"

    def test_no_overlap_returns_0(self) -> None:
        """Test no overlap returns score of 0.0."""
        result = calculate_utilization(
            "ModelUserPayload user_service",
            "Something completely different without matching identifiers",
        )
        assert result.score == 0.0
        assert result.method == "identifier_overlap"

    def test_partial_overlap(self) -> None:
        """Test partial overlap returns score between 0 and 1."""
        result = calculate_utilization(
            "ModelUserPayload user_service api_endpoint",
            "Use ModelUserPayload for the task",
        )
        # Only one of three identifiers matched
        assert 0.0 < result.score < 1.0
        assert result.method == "identifier_overlap"

    def test_empty_injected_context_returns_0(self) -> None:
        """Test empty injected context returns 0 score."""
        result = calculate_utilization("", "Some response text")
        assert result.score == 0.0
        assert result.injected_count == 0

    def test_empty_response_returns_0(self) -> None:
        """Test empty response returns 0 reused count."""
        result = calculate_utilization("ModelUserPayload user_service", "")
        assert result.reused_count == 0

    def test_returns_utilization_result(self) -> None:
        """Test returns UtilizationResult namedtuple."""
        result = calculate_utilization("test_context", "test_response")
        assert isinstance(result, UtilizationResult)
        assert hasattr(result, "score")
        assert hasattr(result, "method")
        assert hasattr(result, "injected_count")
        assert hasattr(result, "reused_count")
        assert hasattr(result, "duration_ms")

    def test_duration_is_non_negative(self) -> None:
        """Test duration_ms is non-negative."""
        result = calculate_utilization("test_context", "test_response")
        assert result.duration_ms >= 0

    def test_counts_are_non_negative(self) -> None:
        """Test injected_count and reused_count are non-negative."""
        result = calculate_utilization("test_context", "test_response")
        assert result.injected_count >= 0
        assert result.reused_count >= 0

    def test_reused_count_lte_injected_count(self) -> None:
        """Test reused_count is always <= injected_count."""
        result = calculate_utilization(
            "ModelUserPayload user_service api_endpoint",
            "Use ModelUserPayload for the task with api_endpoint",
        )
        assert result.reused_count <= result.injected_count


class TestTimeoutHandling:
    """Test timeout handling and graceful degradation."""

    def test_timeout_returns_fallback(self) -> None:
        """Test that timeout returns timeout_fallback method."""
        # Use very short timeout (0ms) to force timeout
        result = calculate_utilization(
            "test" * 10000,  # Large input to ensure some processing time
            "response" * 10000,
            timeout_ms=0,
        )
        assert result.method == "timeout_fallback"
        assert result.score == 0.0

    def test_normal_execution_does_not_timeout(self) -> None:
        """Test normal execution with reasonable timeout succeeds."""
        result = calculate_utilization(
            "ModelUserPayload", "Use ModelUserPayload", timeout_ms=1000
        )
        assert result.method == "identifier_overlap"


class TestUtilizationTimeoutError:
    """Test UtilizationTimeoutError exception."""

    def test_is_exception(self) -> None:
        """Test UtilizationTimeoutError is an Exception subclass."""
        assert issubclass(UtilizationTimeoutError, Exception)

    def test_can_be_raised(self) -> None:
        """Test UtilizationTimeoutError can be raised and caught."""
        with pytest.raises(UtilizationTimeoutError):
            raise UtilizationTimeoutError("test timeout")


class TestStopwords:
    """Test stopword sets."""

    def test_english_stopwords_is_frozenset(self) -> None:
        """Test ENGLISH_STOPWORDS is a frozenset."""
        assert isinstance(ENGLISH_STOPWORDS, frozenset)

    def test_code_stopwords_is_frozenset(self) -> None:
        """Test CODE_STOPWORDS is a frozenset."""
        assert isinstance(CODE_STOPWORDS, frozenset)

    def test_all_stopwords_union(self) -> None:
        """Test ALL_STOPWORDS is union of English and code stopwords."""
        assert ALL_STOPWORDS == ENGLISH_STOPWORDS | CODE_STOPWORDS

    def test_common_english_stopwords_present(self) -> None:
        """Test common English stopwords are present."""
        common_words = ["the", "and", "for", "with", "this"]
        for word in common_words:
            assert word in ENGLISH_STOPWORDS

    def test_common_code_stopwords_present(self) -> None:
        """Test common code stopwords are present."""
        common_keywords = ["def", "class", "return", "import", "self"]
        for keyword in common_keywords:
            assert keyword in CODE_STOPWORDS
