# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Synchronous wrapper for CodeContextResolver.

Provides a timeout-bounded, gracefully-degrading entry point for the
UserPromptSubmit hook pipeline. Returns a markdown string or empty string
on any failure (Qdrant unreachable, embedding service down, timeout, etc).

Reference: OMN-7217 (Task 2 of OMN-7215 Phase 2D agent serving).
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx

from omniclaude.hooks.lib.code_context_resolver import (
    CodeContextResolver,
    ProtocolQdrantSearch,
)

logger = logging.getLogger(__name__)


class _HttpQdrantClient:
    """Minimal httpx-based Qdrant client implementing ProtocolQdrantSearch.

    The CodeContextResolver accepts any object implementing ProtocolQdrantSearch.
    We use raw HTTP instead of qdrant-client to avoid pulling a heavy dependency
    into the hook pipeline.
    """

    def __init__(self, qdrant_url: str, *, timeout: float = 1.0) -> None:
        self._url = qdrant_url.rstrip("/")
        self._timeout = timeout

    async def search(
        self,
        collection_name: str,
        query_vector: list[float],
        limit: int = 10,
    ) -> list[Any]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._url}/collections/{collection_name}/points/search",
                json={
                    "vector": query_vector,
                    "limit": limit,
                    "with_payload": True,
                },
            )
            response.raise_for_status()
            data = response.json()
        return list(data.get("result", []))


def resolve_code_context_sync(
    query: str,
    *,
    max_entities: int = 5,
    qdrant_url: str | None = None,
    embedding_url: str | None = None,
    timeout_seconds: float = 1.5,
) -> str:
    """Resolve code context synchronously with timeout and graceful degradation.

    Args:
        query: User prompt or search query.
        max_entities: Maximum entities to return.
        qdrant_url: Qdrant server URL (defaults to QDRANT_URL env var).
        embedding_url: Embedding model URL (defaults to LLM_EMBEDDING_URL env var).
        timeout_seconds: Maximum wall-clock budget for resolution.

    Returns:
        Markdown-formatted context string, or empty string on any failure.
    """
    if not query or not query.strip():
        return ""

    try:
        return asyncio.run(
            _resolve_with_timeout(
                query=query,
                max_entities=max_entities,
                qdrant_url=qdrant_url,
                embedding_url=embedding_url,
                timeout_seconds=timeout_seconds,
            )
        )
    except Exception:  # noqa: BLE001 — boundary: hook must never raise
        logger.debug(
            "resolve_code_context_sync: failed (graceful degradation)",
            exc_info=True,
        )
        return ""


async def _resolve_with_timeout(
    *,
    query: str,
    max_entities: int,
    qdrant_url: str | None,
    embedding_url: str | None,
    timeout_seconds: float,
) -> str:
    qdrant_url = qdrant_url or os.environ.get("QDRANT_URL") or "http://localhost:6333"
    embedding_url = embedding_url or os.environ.get("LLM_EMBEDDING_URL")

    if not embedding_url:
        return ""

    qdrant_client: ProtocolQdrantSearch = _HttpQdrantClient(
        qdrant_url, timeout=timeout_seconds
    )

    resolver = CodeContextResolver(
        qdrant_client=qdrant_client,
        bolt_handler=None,
        embedding_url=embedding_url,
    )

    try:
        results = await asyncio.wait_for(
            resolver.resolve(query, max_entities=max_entities),
            timeout=timeout_seconds,
        )
    except TimeoutError:
        logger.debug("resolve_code_context_sync: timeout after %.1fs", timeout_seconds)
        return ""

    if not results:
        return ""

    return resolver.format_as_markdown(results)


__all__ = ["resolve_code_context_sync"]
