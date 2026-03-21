# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for CodeContextResolver.

Validates:
    - Basic resolution: Qdrant returns hits, resolver formats them
    - Memgraph fallback: Memgraph unavailable, Qdrant-only results returned

Related:
    - OMN-5719: CodeContextResolver
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

import pytest

from omniclaude.hooks.lib.code_context_resolver import (
    CodeContextResolver,
)


@dataclass
class _MockQdrantHit:
    """Mock Qdrant search result."""

    payload: dict[str, object]
    score: float


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolve_basic() -> None:
    """Resolver with mock Qdrant returning 3 entities returns 3 CodeContextResult."""
    qdrant_client = AsyncMock()
    qdrant_client.search = AsyncMock(
        return_value=[
            _MockQdrantHit(
                payload={
                    "entity_id": "cls_ModelCodeEntity",
                    "name": "ModelCodeEntity",
                    "entity_type": "CLASS",
                    "file_path": "src/models/model_code_entity.py",
                    "source_repo": "omniintelligence",
                    "line_start": 15,
                },
                score=0.95,
            ),
            _MockQdrantHit(
                payload={
                    "entity_id": "cls_ModelCodeRelationship",
                    "name": "ModelCodeRelationship",
                    "entity_type": "CLASS",
                    "file_path": "src/models/model_code_relationship.py",
                    "source_repo": "omniintelligence",
                    "line_start": 10,
                },
                score=0.88,
            ),
            _MockQdrantHit(
                payload={
                    "entity_id": "fn_extract_entities",
                    "name": "extract_entities_from_source",
                    "entity_type": "FUNCTION",
                    "file_path": "src/handlers/handler_extract_ast.py",
                    "source_repo": "omniintelligence",
                    "line_start": 84,
                },
                score=0.72,
            ),
        ]
    )

    mock_embedding = [0.1] * 128

    resolver = CodeContextResolver(
        qdrant_client=qdrant_client,
        bolt_handler=None,
        embedding_url="http://test:8100",
    )

    with patch.object(
        resolver, "_get_embedding", AsyncMock(return_value=mock_embedding)
    ):
        results = await resolver.resolve("code entity models")

    assert len(results) == 3
    assert results[0].entity_name == "ModelCodeEntity"
    assert results[0].similarity_score == 0.95
    assert results[0].source_repo == "omniintelligence"
    assert results[2].entity_name == "extract_entities_from_source"

    # Verify markdown formatting
    md = resolver.format_as_markdown(results)
    assert "ModelCodeEntity" in md
    assert "CLASS" in md
    assert "0.950" in md


@pytest.mark.unit
@pytest.mark.asyncio
async def test_memgraph_unavailable_returns_qdrant_only() -> None:
    """Memgraph down -> returns Qdrant-only results with no neighbors."""
    qdrant_client = AsyncMock()
    qdrant_client.search = AsyncMock(
        return_value=[
            _MockQdrantHit(
                payload={
                    "entity_id": "cls_Test",
                    "name": "TestEntity",
                    "entity_type": "CLASS",
                    "file_path": "src/test.py",
                    "source_repo": "test_repo",
                    "line_start": 1,
                },
                score=0.9,
            ),
        ]
    )

    # Bolt handler that raises on query
    bolt_handler = AsyncMock()
    bolt_handler.query = AsyncMock(side_effect=ConnectionError("Memgraph unavailable"))

    mock_embedding = [0.1] * 128

    resolver = CodeContextResolver(
        qdrant_client=qdrant_client,
        bolt_handler=bolt_handler,
        embedding_url="http://test:8100",
    )

    with patch.object(
        resolver, "_get_embedding", AsyncMock(return_value=mock_embedding)
    ):
        results = await resolver.resolve("test query")

    assert len(results) == 1
    assert results[0].entity_name == "TestEntity"
    assert results[0].neighbors == []  # Memgraph failed, no neighbors
