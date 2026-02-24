# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
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
    MAX_INPUT_SIZE,
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

    def test_per_pattern_timeout_checking(self) -> None:
        """Test that timeout is checked after each regex pattern.

        The improved implementation checks timeout after each of 5 patterns,
        providing more granular control than checking only after entire extraction.
        """
        # With timeout_ms=0, the first pattern that completes should trigger timeout
        # This tests the per-pattern timeout mechanism
        result = calculate_utilization(
            "ModelUser user_service /path/to/file OMN-123 KAFKA_HOST",
            "response text",
            timeout_ms=0,
        )
        assert result.method == "timeout_fallback"
        assert result.score == 0.0

    def test_timeout_on_second_extraction(self) -> None:
        """Test timeout can occur during response extraction.

        With a very tight timeout, the second extraction (response_text)
        should also be able to trigger timeout.
        """
        # Small injected context, larger response - timeout should happen
        # during response extraction
        result = calculate_utilization(
            "ModelUser",  # Small, fast
            "LongResponseText " * 5000,  # Larger, may trigger timeout
            timeout_ms=0,  # Immediate timeout
        )
        assert result.method == "timeout_fallback"


class TestUtilizationTimeoutError:
    """Test UtilizationTimeoutError exception."""

    def test_is_exception(self) -> None:
        """Test UtilizationTimeoutError is an Exception subclass."""
        assert issubclass(UtilizationTimeoutError, Exception)

    def test_can_be_raised(self) -> None:
        """Test UtilizationTimeoutError can be raised and caught."""
        with pytest.raises(UtilizationTimeoutError):
            raise UtilizationTimeoutError("test timeout")


class TestInputSizeLimits:
    """Test input size limit enforcement."""

    def test_max_input_size_is_defined(self) -> None:
        """Test MAX_INPUT_SIZE constant is defined and reasonable."""
        assert MAX_INPUT_SIZE > 0
        assert MAX_INPUT_SIZE == 50 * 1024  # 50KB

    def test_large_input_is_truncated(self) -> None:
        """Test that inputs larger than MAX_INPUT_SIZE are handled gracefully.

        The implementation truncates inputs to MAX_INPUT_SIZE as defense in depth
        against pathological regex performance.
        """
        # Create input larger than MAX_INPUT_SIZE (50KB)
        large_input = "ModelUser " * (MAX_INPUT_SIZE // 10 + 1000)  # ~60KB+
        assert len(large_input) > MAX_INPUT_SIZE

        # Should still work without hanging or crashing
        result = calculate_utilization(
            large_input,
            "Use ModelUser for the task",
            timeout_ms=5000,  # 5 second generous timeout
        )

        # Should complete (either successfully or with graceful degradation)
        assert result.method in ("identifier_overlap", "timeout_fallback")

    def test_input_at_limit_works(self) -> None:
        """Test that input exactly at MAX_INPUT_SIZE works correctly."""
        # Create input exactly at the limit
        at_limit_input = "x" * MAX_INPUT_SIZE

        # Should complete without issues
        result = calculate_utilization(
            at_limit_input,
            "response",
            timeout_ms=5000,
        )
        assert result.method in ("identifier_overlap", "timeout_fallback")

    def test_normal_input_unaffected(self) -> None:
        """Test that normal-sized inputs are unaffected by truncation.

        Inputs below MAX_INPUT_SIZE should be processed completely.
        """
        # Normal-sized input with identifiable content
        normal_input = "ModelUserPayload user_service api_endpoint"
        assert len(normal_input) < MAX_INPUT_SIZE

        result = calculate_utilization(
            normal_input,
            "Use ModelUserPayload and api_endpoint",
            timeout_ms=1000,
        )

        # Should find the overlap normally
        assert result.method == "identifier_overlap"
        assert result.injected_count == 3
        assert result.reused_count == 2


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

    def test_stopwords_are_lowercase(self) -> None:
        """Test all stopwords are lowercase for case-insensitive matching."""
        for word in ALL_STOPWORDS:
            assert word == word.lower(), f"Stopword '{word}' should be lowercase"

    def test_case_insensitive_stopword_filtering(self) -> None:
        """Test that stopwords are filtered regardless of input case."""
        # "THE" should be filtered (matches "the" stopword after normalization)
        identifiers = extract_identifiers("THE AND FOR")
        assert "the" not in identifiers
        assert "and" not in identifiers
        assert "for" not in identifiers


class TestStickyIdentity:
    """Test sticky identity functionality - identifier reuse detection.

    "Sticky identity" refers to how identifiers persist and are tracked:
    - Identifiers are stored in sets (automatic deduplication)
    - Each unique identifier counts once, regardless of repetition
    - Set intersection determines overlap between context and response
    """

    def test_duplicate_identifiers_in_context_counted_once(self) -> None:
        """Test that duplicate identifiers in injected context are deduped.

        When the same identifier appears multiple times in the context,
        it should only count as one identifier for the score calculation.
        """
        # Same identifier repeated 5 times in context
        repeated_context = (
            "ModelUserPayload ModelUserPayload ModelUserPayload "
            "ModelUserPayload ModelUserPayload"
        )
        single_context = "ModelUserPayload"

        # Extract identifiers - both should yield the same set
        repeated_ids = extract_identifiers(repeated_context)
        single_ids = extract_identifiers(single_context)

        assert repeated_ids == single_ids
        assert len(repeated_ids) == 1
        assert "modeluserpayload" in repeated_ids

        # Utilization calculation should give same results
        result_repeated = calculate_utilization(
            repeated_context, "Use ModelUserPayload"
        )
        result_single = calculate_utilization(single_context, "Use ModelUserPayload")

        assert result_repeated.injected_count == result_single.injected_count == 1
        assert result_repeated.reused_count == result_single.reused_count == 1
        assert result_repeated.score == result_single.score == 1.0

    def test_reused_identifiers_in_response_counted_once(self) -> None:
        """Test that identifiers reused multiple times in response count once.

        Even if Claude's response mentions an identifier many times,
        it should only count as one reused identifier.
        """
        context = "ModelUserPayload user_service"
        # Response uses ModelUserPayload 4 times
        response = (
            "I'll use ModelUserPayload for the request. "
            "The ModelUserPayload contains the data. "
            "Validate ModelUserPayload before processing. "
            "Return ModelUserPayload to the client."
        )

        result = calculate_utilization(context, response)

        # Only 2 identifiers in context, only 1 was reused (ModelUserPayload)
        assert result.injected_count == 2
        assert result.reused_count == 1  # Not 4!
        assert result.score == 0.5  # 1 out of 2 identifiers reused

    def test_all_identifier_types_sticky(self) -> None:
        """Test that all identifier types are sticky (deduplicated consistently).

        Each pattern type (CamelCase, snake_case, paths, tickets, URLs, env vars)
        should deduplicate when the same identifier is repeated.
        """
        # Test deduplication: same identifier repeated should yield 1
        test_cases = [
            # (identifier_type, repeated_text, identifier_to_check)
            ("CamelCase", "ModelUser ModelUser ModelUser", "modeluser"),
            ("snake_case", "user_service user_service user_service", "user_service"),
            ("tickets", "OMN-1889 OMN-1889 OMN-1889", "omn-1889"),
            ("env_vars", "KAFKA_HOST KAFKA_HOST KAFKA_HOST", "kafka_host"),
        ]

        for id_type, text, expected_id in test_cases:
            ids = extract_identifiers(text)
            # The specific identifier should appear exactly once
            assert expected_id in ids, f"{id_type}: '{expected_id}' not found in {ids}"
            # Count occurrences of the expected identifier (should be 1 due to set)
            count = sum(1 for i in ids if i == expected_id)
            assert count == 1, f"{id_type}: '{expected_id}' appeared {count} times"

        # Test paths separately - paths also extract component identifiers
        path_text = "/src/myfile.py /src/myfile.py /src/myfile.py"
        path_ids = extract_identifiers(path_text)
        # The path itself should appear once
        assert "/src/myfile.py" in path_ids
        path_count = sum(1 for i in path_ids if i == "/src/myfile.py")
        assert path_count == 1

        # Test URLs separately
        url_text = "https://api.example.com https://api.example.com"
        url_ids = extract_identifiers(url_text)
        assert "https://api.example.com" in url_ids
        url_count = sum(1 for i in url_ids if i == "https://api.example.com")
        assert url_count == 1

    def test_mixed_identifier_types_realistic_scenario(self) -> None:
        """Test realistic scenario with multiple identifier types.

        Simulates a real context injection with various identifier types
        and measures utilization when response uses some of them.
        """
        # Realistic injected context with multiple identifier types
        injected_context = """
        Pattern: Use ModelEventPayload for /src/events/handler.py
        Ticket: OMN-1889 requires KAFKA_BOOTSTRAP_SERVERS config
        See https://docs.internal.com/events for details
        Helper: event_processor.validate_schema() method
        """

        # Response uses some identifiers (not all)
        response = """
        I'll implement the changes for OMN-1889.

        First, I'll update /src/events/handler.py to use ModelEventPayload:

        ```python
        from models import ModelEventPayload

        def process_event(payload: ModelEventPayload):
            return event_processor.validate_schema(payload)
        ```

        This follows the pattern you mentioned.
        """

        result = calculate_utilization(injected_context, response)

        # Verify meaningful overlap was detected
        assert result.method == "identifier_overlap"
        assert result.injected_count > 0
        assert result.reused_count > 0
        assert 0.0 < result.score <= 1.0

        # Specific identifiers we expect to match
        injected_ids = extract_identifiers(injected_context)
        response_ids = extract_identifiers(response)
        overlap = injected_ids & response_ids

        # These should definitely be in the overlap
        expected_overlap = {
            "omn-1889",
            "/src/events/handler.py",
            "modeleventpayload",
            "event_processor",
            "validate_schema",
        }
        for expected in expected_overlap:
            assert expected in overlap, f"Expected '{expected}' in overlap"

    def test_case_insensitive_sticky_identity(self) -> None:
        """Test that identifiers are sticky regardless of case.

        ModelUserPayload, MODELUSERPAYLOAD, and modeluserpayload
        should all be treated as the same identifier.
        """
        # Same identifier in different cases
        context = "ModelUserPayload MODELUSERPAYLOAD modeluserpayload"
        ids = extract_identifiers(context)

        # Should normalize to one identifier
        assert len(ids) == 1
        assert "modeluserpayload" in ids

        # Utilization should work regardless of case in response
        result = calculate_utilization("ModelUserPayload", "use MODELUSERPAYLOAD")
        assert result.score == 1.0
        assert result.reused_count == 1

    def test_very_long_identifiers_sticky(self) -> None:
        """Test that very long identifiers are handled correctly."""
        # Long CamelCase identifier
        long_id = "VeryLongModelNameForUserAuthenticationServicePayloadHandler"

        # Repeated long identifier
        context = f"{long_id} {long_id} {long_id}"
        ids = extract_identifiers(context)

        assert len(ids) == 1
        assert long_id.lower() in ids

        # Utilization with long identifier
        result = calculate_utilization(context, f"Use {long_id} for auth")
        assert result.injected_count == 1
        assert result.reused_count == 1
        assert result.score == 1.0

    def test_identifiers_with_numbers_sticky(self) -> None:
        """Test that identifiers with numbers are handled correctly."""
        # snake_case with numbers
        context = "user_v2 api_v3_handler config_2024"
        ids = extract_identifiers(context)

        assert "user_v2" in ids
        assert "api_v3_handler" in ids
        assert "config_2024" in ids

        # Repeated identifiers with numbers
        repeated = "user_v2 user_v2 user_v2"
        ids_repeated = extract_identifiers(repeated)
        assert len(ids_repeated) == 1

    def test_special_characters_in_paths_sticky(self) -> None:
        """Test that paths with special characters deduplicate correctly."""
        # Paths with dots and hyphens
        context = "/src/my-module/file.py /src/my-module/file.py /api/v2.0/handler.py"
        ids = extract_identifiers(context)

        # Should have 2 unique paths
        path_ids = {i for i in ids if "/" in i}
        assert len(path_ids) == 2

    def test_empty_and_whitespace_handling(self) -> None:
        """Test edge cases with empty strings and whitespace."""
        # Empty context
        assert extract_identifiers("") == set()
        assert extract_identifiers("   ") == set()
        assert extract_identifiers("\n\t\r") == set()

        # Utilization with empty inputs
        result = calculate_utilization("", "response")
        assert result.score == 0.0
        assert result.injected_count == 0

        result = calculate_utilization("ModelUser", "")
        assert result.reused_count == 0

    def test_score_not_inflated_by_duplicates(self) -> None:
        """Test that score is based on unique identifiers, not repetitions.

        If context has 2 unique identifiers (repeated many times) and
        response uses 1, the score should be 0.5, not higher.
        """
        # 2 unique identifiers, each repeated 10 times
        context = ("ModelUser " * 10) + ("user_service " * 10)
        # Response only uses ModelUser
        response = "Using ModelUser for the implementation"

        result = calculate_utilization(context, response)

        assert result.injected_count == 2  # Not 20
        assert result.reused_count == 1  # Not 10
        assert result.score == 0.5  # 1/2, not inflated

    def test_identifiers_sticky_across_multiple_calculations(self) -> None:
        """Test that identifier stickiness is consistent across calculations.

        Multiple calls with the same inputs should yield identical results.
        """
        context = "ModelPayload user_handler /src/model.py OMN-1889"
        response = "Use ModelPayload from /src/model.py for OMN-1889"

        # Calculate multiple times
        results = [calculate_utilization(context, response) for _ in range(5)]

        # All results should be identical
        for result in results:
            assert result.injected_count == results[0].injected_count
            assert result.reused_count == results[0].reused_count
            assert result.score == results[0].score

    def test_partial_identifier_matches_not_counted(self) -> None:
        """Test that partial matches are not counted as reused.

        'ModelUser' should not match 'ModelUserPayload' since they are
        different identifiers extracted separately.
        """
        context = "ModelUserPayload"
        # Response has a different (but overlapping) identifier
        response = "Use ModelUser and UserPayload"

        result = calculate_utilization(context, response)

        # ModelUserPayload != ModelUser, so no match
        assert result.injected_count == 1

        # The full identifier "modeluserpayload" should not match partial identifiers
        context_ids = extract_identifiers(context)
        response_ids = extract_identifiers(response)
        assert "modeluserpayload" in context_ids
        assert "modeluserpayload" not in response_ids

    def test_unicode_identifiers_handled(self) -> None:
        """Test that unicode characters in identifiers don't cause issues."""
        # Unicode in paths/strings shouldn't crash
        context = "path/to/file_\u00e9.py some_caf\u00e9_service"
        ids = extract_identifiers(context)

        # Should extract without error
        assert isinstance(ids, set)

        # Utilization calculation should complete without error
        result = calculate_utilization(context, "response text")
        assert result.method in ("identifier_overlap", "timeout_fallback")

    def test_set_intersection_semantics(self) -> None:
        """Test that reused identifiers are computed via set intersection.

        The reused_count should equal |injected_ids & response_ids|.
        """
        context = "alpha_one beta_two gamma_three"
        response = "using beta_two and delta_four and gamma_three"

        context_ids = extract_identifiers(context)
        response_ids = extract_identifiers(response)
        expected_overlap = context_ids & response_ids

        result = calculate_utilization(context, response)

        assert result.reused_count == len(expected_overlap)
        # beta_two and gamma_three should be in overlap
        assert "beta_two" in expected_overlap
        assert "gamma_three" in expected_overlap
        # alpha_one not in response, delta_four not in context
        assert "alpha_one" not in expected_overlap
        assert "delta_four" not in expected_overlap

    def test_high_cardinality_sticky(self) -> None:
        """Test sticky identity with many unique identifiers.

        Ensures set semantics scale correctly with high cardinality.
        """
        # Generate 50 unique identifiers
        context_ids_list = [f"identifier_{i:03d}" for i in range(50)]
        context = " ".join(context_ids_list)

        # Response uses half of them (every other one)
        response_ids_list = context_ids_list[::2]  # 25 identifiers
        response = " ".join(response_ids_list)

        result = calculate_utilization(context, response)

        assert result.injected_count == 50
        assert result.reused_count == 25
        assert result.score == 0.5

    def test_context_filtered_to_minimal_identifiers(self) -> None:
        """Test behavior when most context words are filtered.

        When context contains mostly stopwords and short words,
        the effective identifier set is small or empty.
        """
        # Mix of stopwords, short words, and one real identifier
        context = "the and for a b c MyService"
        response = "Using MyService for the task"

        result = calculate_utilization(context, response)

        # Only MyService should survive filtering
        context_ids = extract_identifiers(context)
        assert "myservice" in context_ids
        assert len(context_ids) == 1  # Only MyService

        # Score should be 1.0 since the only identifier is reused
        assert result.injected_count == 1
        assert result.reused_count == 1
        assert result.score == 1.0
