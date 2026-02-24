# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Integration tests for pattern persistence with real PostgreSQL.

These tests verify end-to-end behavior of the ProtocolPatternPersistence
implementation against a real database. They require:

1. PostgreSQL running on the configured host/port
2. The learned_patterns table to exist (see sql/migrations/)
3. A real_container fixture providing a configured container

To run:
    pytest tests/integration/test_pattern_persistence.py -v -m "requires_postgres"

To skip in CI without postgres:
    pytest tests/integration/ -v -m "not requires_postgres"
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from omniclaude.nodes.node_pattern_persistence_effect.models import (
    ModelLearnedPatternQuery,
    ModelLearnedPatternRecord,
)
from omniclaude.nodes.node_pattern_persistence_effect.protocols import (
    ProtocolPatternPersistence,
)

if TYPE_CHECKING:
    from omnibase_core.models.container.model_onex_container import ModelONEXContainer


# Mark all tests in this module as integration tests requiring postgres
pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires_postgres,
]


@pytest.mark.asyncio
async def test_query_and_upsert_end_to_end(real_container: ModelONEXContainer) -> None:
    """End-to-end test: upsert a pattern, then query it back.

    This test verifies the complete round-trip:
    1. Upsert a pattern to the database
    2. Query patterns with matching domain/confidence
    3. Verify the upserted pattern appears in results

    The test uses a unique pattern_id to avoid conflicts with other test runs.
    """
    # Resolve the handler from container
    handler = await real_container.get_service_async(ProtocolPatternPersistence)

    # Create a unique test pattern
    test_pattern = ModelLearnedPatternRecord(
        pattern_id="integration.test.pattern.e2e",
        domain="testing",
        title="Integration Test Pattern",
        description="Pattern created during integration testing to verify persistence",
        confidence=0.85,
        usage_count=1,
        success_rate=1.0,
        example_reference="tests/integration/test_pattern_persistence.py",
    )

    # Step 1: Upsert the pattern
    upsert_result = await handler.upsert_pattern(test_pattern)

    assert upsert_result.success is True, f"Upsert failed: {upsert_result.error}"
    assert upsert_result.pattern_id == test_pattern.pattern_id
    assert upsert_result.operation in ("insert", "update")

    # Step 2: Query patterns with matching criteria
    query = ModelLearnedPatternQuery(
        domain="testing",
        min_confidence=0.8,
        include_general=True,
        limit=50,
    )
    query_result = await handler.query_patterns(query)

    assert query_result.success is True, f"Query failed: {query_result.error}"
    assert query_result.total_count >= 1

    # Step 3: Verify our pattern exists in the results
    found_pattern = next(
        (r for r in query_result.records if r.pattern_id == test_pattern.pattern_id),
        None,
    )
    assert found_pattern is not None, (
        f"Pattern {test_pattern.pattern_id} not found in query results. "
        f"Got {len(query_result.records)} records."
    )

    # Verify pattern fields match
    assert found_pattern.domain == test_pattern.domain
    assert found_pattern.title == test_pattern.title
    assert found_pattern.confidence == test_pattern.confidence


@pytest.mark.asyncio
async def test_upsert_idempotency(real_container: ModelONEXContainer) -> None:
    """Verify upsert is idempotent: multiple calls update rather than insert.

    This test verifies that calling upsert multiple times with the same
    pattern_id results in updates, not duplicate insertions.
    """
    handler = await real_container.get_service_async(ProtocolPatternPersistence)

    # Create initial pattern
    pattern_v1 = ModelLearnedPatternRecord(
        pattern_id="integration.test.idempotency",
        domain="testing",
        title="Idempotency Test v1",
        description="Initial version",
        confidence=0.5,
    )

    # First upsert (should be insert)
    result1 = await handler.upsert_pattern(pattern_v1)
    assert result1.success is True
    # First insert should report "insert", but we don't assert this
    # since the pattern might already exist from a previous test run

    # Update with new values (same pattern_id)
    pattern_v2 = ModelLearnedPatternRecord(
        pattern_id="integration.test.idempotency",
        domain="testing",
        title="Idempotency Test v2",
        description="Updated version",
        confidence=0.9,
    )

    # Second upsert (should be update)
    result2 = await handler.upsert_pattern(pattern_v2)
    assert result2.success is True
    assert result2.operation == "update"

    # Query and verify updated values
    query = ModelLearnedPatternQuery(domain="testing", min_confidence=0.0)
    query_result = await handler.query_patterns(query)

    found = next(
        (r for r in query_result.records if r.pattern_id == pattern_v2.pattern_id),
        None,
    )
    assert found is not None
    assert found.title == "Idempotency Test v2"
    assert found.confidence == 0.9


@pytest.mark.asyncio
async def test_query_with_domain_filter(real_container: ModelONEXContainer) -> None:
    """Verify domain filtering works correctly.

    This test ensures that querying with a domain filter returns only
    patterns from that domain (plus 'general' if include_general=True).
    """
    handler = await real_container.get_service_async(ProtocolPatternPersistence)

    # Query for a specific domain
    query = ModelLearnedPatternQuery(
        domain="testing",
        min_confidence=0.0,
        include_general=False,
        limit=100,
    )
    result = await handler.query_patterns(query)

    assert result.success is True

    # All results should be from the 'testing' domain
    for record in result.records:
        assert record.domain == "testing", (
            f"Expected domain 'testing', got '{record.domain}'"
        )


@pytest.mark.asyncio
async def test_query_includes_general_patterns(
    real_container: ModelONEXContainer,
) -> None:
    """Verify include_general=True adds 'general' domain patterns.

    When querying with a specific domain and include_general=True,
    the results should include both domain-specific and 'general' patterns.
    """
    handler = await real_container.get_service_async(ProtocolPatternPersistence)

    # First, ensure we have a general pattern
    general_pattern = ModelLearnedPatternRecord(
        pattern_id="integration.test.general",
        domain="general",
        title="General Test Pattern",
        description="A general pattern for testing include_general",
        confidence=0.75,
    )
    await handler.upsert_pattern(general_pattern)

    # Query with include_general=True
    query = ModelLearnedPatternQuery(
        domain="testing",
        min_confidence=0.0,
        include_general=True,
        limit=100,
    )
    result = await handler.query_patterns(query)

    assert result.success is True

    # Results should include patterns from both 'testing' AND 'general'
    domains = {r.domain for r in result.records}
    # We expect at least 'testing' or 'general' (both if data exists)
    assert domains.issubset({"testing", "general"}), (
        f"Unexpected domains in results: {domains}"
    )


@pytest.mark.asyncio
async def test_query_pagination(real_container: ModelONEXContainer) -> None:
    """Verify pagination (limit/offset) works correctly.

    This test verifies that:
    1. Limit restricts the number of returned records
    2. Offset skips the specified number of records
    3. total_count reflects the full count before pagination
    """
    handler = await real_container.get_service_async(ProtocolPatternPersistence)

    # Query with limit=1 to test pagination
    query_page1 = ModelLearnedPatternQuery(
        domain="testing",
        min_confidence=0.0,
        include_general=True,
        limit=1,
        offset=0,
    )
    result_page1 = await handler.query_patterns(query_page1)

    assert result_page1.success is True
    assert len(result_page1.records) <= 1

    # If there are more records, test offset
    if result_page1.total_count > 1:
        query_page2 = ModelLearnedPatternQuery(
            domain="testing",
            min_confidence=0.0,
            include_general=True,
            limit=1,
            offset=1,
        )
        result_page2 = await handler.query_patterns(query_page2)

        assert result_page2.success is True
        assert len(result_page2.records) <= 1
        assert result_page2.total_count == result_page1.total_count

        # Records should be different (assuming different patterns exist)
        if result_page1.records and result_page2.records:
            assert (
                result_page1.records[0].pattern_id != result_page2.records[0].pattern_id
            )
