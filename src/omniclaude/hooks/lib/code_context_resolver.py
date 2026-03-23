# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Code context resolver for semantic code entity lookup.

Queries Qdrant code_patterns collection for semantic similarity, fetches
1-hop structural neighbors from Memgraph, and formats results for context
injection into Claude Code sessions.

Graceful degradation:
- Qdrant down -> empty results
- Memgraph down -> Qdrant-only results (no neighbor expansion)

Does NOT wire into existing pattern injection pipeline — Part 2 Task 10
does hybrid fusion.

Related:
    - OMN-5719: CodeContextResolver
    - OMN-5720: AST-based code pattern extraction (epic)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import httpx

logger = logging.getLogger(__name__)

QDRANT_COLLECTION = "code_patterns"
"""Qdrant collection name for code entity embeddings."""


# =============================================================================
# Protocols
# =============================================================================


@runtime_checkable
class ProtocolQdrantSearch(Protocol):
    """Minimal protocol for Qdrant search operations."""

    async def search(
        self,
        collection_name: str,
        query_vector: list[float],
        limit: int = 10,
    ) -> list[Any]: ...


@runtime_checkable
class ProtocolBoltQuery(Protocol):
    """Minimal protocol for Memgraph read operations."""

    async def query(
        self, cypher: str, parameters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]: ...


# =============================================================================
# Result Model
# =============================================================================


@dataclass
class CodeContextResult:
    """A single resolved code entity with context."""

    entity_name: str
    entity_type: str
    file_path: str
    line_start: int
    source_repo: str
    similarity_score: float
    bases: list[str] = field(default_factory=list)
    methods: list[str] = field(default_factory=list)
    docstring_preview: str | None = None
    neighbors: list[str] = field(default_factory=list)


# =============================================================================
# Resolver
# =============================================================================


class CodeContextResolver:
    """Resolves code context from Qdrant embeddings and Memgraph graph.

    Usage:
        resolver = CodeContextResolver(qdrant_client=..., bolt_handler=...)
        results = await resolver.resolve("NodePatternStorageEffect")
        for r in results:
            print(f"{r.entity_name} ({r.entity_type}) @ {r.file_path}:{r.line_start}")
    """

    def __init__(
        self,
        *,
        qdrant_client: ProtocolQdrantSearch | None = None,
        bolt_handler: ProtocolBoltQuery | None = None,
        embedding_url: str | None = None,
    ) -> None:
        self._qdrant = qdrant_client
        self._bolt = bolt_handler
        resolved_url = embedding_url or os.environ.get("LLM_EMBEDDING_URL", "")
        if not resolved_url:
            logger.warning(
                "LLM_EMBEDDING_URL is not set. "
                "Semantic code context resolution will be unavailable. "
                "Set LLM_EMBEDDING_URL in ~/.omnibase/.env to enable."
            )
        self._embedding_url = resolved_url

    async def resolve(
        self,
        query: str,
        max_entities: int = 10,
    ) -> list[CodeContextResult]:
        """Resolve code entities matching a semantic query.

        Args:
            query: Natural language or code identifier query.
            max_entities: Maximum number of results to return.

        Returns:
            List of CodeContextResult ordered by similarity score.
        """
        if not self._embedding_url:
            logger.warning(
                "CodeContextResolver: no embedding URL configured, returning empty results"
            )
            return []

        if self._qdrant is None:
            logger.warning(
                "CodeContextResolver: no Qdrant client, returning empty results"
            )
            return []

        # Step 1: Embed query text
        query_vector = await self._get_embedding(query)
        if query_vector is None:
            logger.warning(
                "CodeContextResolver: embedding failed, returning empty results"
            )
            return []

        # Step 2: Qdrant search
        try:
            hits = await self._qdrant.search(
                collection_name=QDRANT_COLLECTION,
                query_vector=query_vector,
                limit=max_entities,
            )
        except Exception:  # noqa: BLE001 — boundary: Qdrant search must degrade gracefully
            logger.warning(
                "CodeContextResolver: Qdrant search failed (graceful degradation)",
                exc_info=True,
            )
            return []

        # Step 3: Build results from hits
        results: list[CodeContextResult] = []
        seen_entity_ids: set[str] = set()

        for hit in hits:
            payload = getattr(hit, "payload", None) or (
                hit if isinstance(hit, dict) else {}
            )
            if isinstance(payload, dict):
                entity_id = str(payload.get("entity_id", ""))
            else:
                entity_id = str(getattr(payload, "entity_id", ""))

            if entity_id in seen_entity_ids:
                continue
            seen_entity_ids.add(entity_id)

            score = getattr(hit, "score", 0.0)
            if isinstance(hit, dict):
                score = hit.get("score", 0.0)

            result = CodeContextResult(
                entity_name=str(
                    payload.get("name", "")
                    if isinstance(payload, dict)
                    else getattr(payload, "name", "")
                ),
                entity_type=str(
                    payload.get("entity_type", "")
                    if isinstance(payload, dict)
                    else getattr(payload, "entity_type", "")
                ),
                file_path=str(
                    payload.get("file_path", "")
                    if isinstance(payload, dict)
                    else getattr(payload, "file_path", "")
                ),
                line_start=int(
                    payload.get("line_start", 0)
                    if isinstance(payload, dict)
                    else getattr(payload, "line_start", 0)
                ),
                source_repo=str(
                    payload.get("source_repo", "")
                    if isinstance(payload, dict)
                    else getattr(payload, "source_repo", "")
                ),
                similarity_score=float(score),
            )
            results.append(result)

        # Step 4: Fetch 1-hop neighbors from Memgraph
        if self._bolt is not None:
            for result in results:
                neighbors = await self._fetch_neighbors(result.entity_name)
                result.neighbors = neighbors

        # Step 5: Sort by similarity score (descending)
        results.sort(key=lambda r: r.similarity_score, reverse=True)

        return results[:max_entities]

    def format_as_markdown(self, results: list[CodeContextResult]) -> str:
        """Format results as a markdown context block for injection."""
        if not results:
            return ""

        lines = ["## Code Context (Semantic Search)\n"]
        for r in results:
            lines.append(f"### {r.entity_name} ({r.entity_type})")
            lines.append(f"- **File**: `{r.source_repo}/{r.file_path}:{r.line_start}`")
            lines.append(f"- **Score**: {r.similarity_score:.3f}")
            if r.docstring_preview:
                lines.append(f"- **Description**: {r.docstring_preview}")
            if r.bases:
                lines.append(f"- **Bases**: {', '.join(r.bases)}")
            if r.methods:
                lines.append(f"- **Methods**: {', '.join(r.methods[:10])}")
            if r.neighbors:
                lines.append(f"- **Related**: {', '.join(r.neighbors[:5])}")
            lines.append("")

        return "\n".join(lines)

    async def _get_embedding(self, text: str) -> list[float] | None:
        """Get embedding vector from LLM endpoint."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self._embedding_url}/v1/embeddings",
                    json={"input": text, "model": "default"},
                )
                response.raise_for_status()
                data: dict[str, object] = response.json()
                embedding: list[float] = data["data"][0]["embedding"]  # type: ignore[index]
                return embedding
        except Exception:  # noqa: BLE001 — boundary: embedding request must degrade gracefully
            logger.warning("CodeContextResolver: embedding request failed")
            return None

    async def _fetch_neighbors(self, entity_name: str) -> list[str]:
        """Fetch 1-hop neighbors from Memgraph."""
        if self._bolt is None:
            return []

        try:
            records = await self._bolt.query(
                "MATCH (s:CodeEntity {name: $name})-[:INHERITS|IMPORTS]->(t:CodeEntity) "
                "RETURN t.name AS neighbor LIMIT 10",
                parameters={"name": entity_name},
            )
            return [str(r.get("neighbor", "")) for r in records if r.get("neighbor")]
        except Exception:  # noqa: BLE001 — boundary: Memgraph query must degrade gracefully
            logger.warning(
                "CodeContextResolver: Memgraph query failed for %s (graceful degradation)",
                entity_name,
                exc_info=True,
            )
            return []


__all__ = ["CodeContextResolver", "CodeContextResult"]
