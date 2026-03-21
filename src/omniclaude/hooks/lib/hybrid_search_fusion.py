# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Hybrid search fusion combining Qdrant semantic and Memgraph structural results.

Implements Reciprocal Rank Fusion (RRF) for combining rankings from
multiple search sources. Algorithm:
    score(d) = sum( weight_i / (k + rank_i(d)) ) for each source i

Deduplicates by entity_id, applies min_combined_score threshold.
Falls back to single-source results if the other source is unavailable.

Reference: OMN-5682
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class HybridSearchFusion:
    """Fuses results from Qdrant semantic search and Memgraph structural traversal.

    All parameters are read from config (contract YAML).
    """

    def __init__(self, config: dict[str, Any]) -> None:
        """Initialize from contract config.

        Args:
            config: The ``config.code_context.search_fusion`` dict.
        """
        self._enabled: bool = config.get("enabled", True)
        self._strategy: str = config.get("strategy", "reciprocal_rank_fusion")
        self._qdrant_weight: float = config.get("qdrant_weight", 0.6)
        self._memgraph_weight: float = config.get("memgraph_weight", 0.4)
        self._rrf_k: int = config.get("rrf_k", 60)
        self._dedup_key: str = config.get("dedup_key", "entity_id")
        self._min_combined_score: float = config.get("min_combined_score", 0.3)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def fuse(
        self,
        qdrant_results: list[dict[str, Any]] | None = None,
        memgraph_results: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Fuse results from Qdrant and Memgraph using configured strategy.

        Args:
            qdrant_results: Ranked results from Qdrant semantic search.
                Each dict must have entity_id and optionally a score.
            memgraph_results: Ranked results from Memgraph structural traversal.
                Each dict must have entity_id and optionally a score.

        Returns:
            Fused, deduplicated, and thresholded results sorted by combined score.
        """
        if not self._enabled:
            return (qdrant_results or []) + (memgraph_results or [])

        qdrant_results = qdrant_results or []
        memgraph_results = memgraph_results or []

        # Handle single-source fallback
        if not qdrant_results and not memgraph_results:
            return []

        if not qdrant_results:
            logger.warning(
                "HybridSearchFusion: Qdrant results unavailable, using Memgraph only"
            )
            return self._single_source_results(memgraph_results, self._memgraph_weight)

        if not memgraph_results:
            logger.warning(
                "HybridSearchFusion: Memgraph results unavailable, using Qdrant only"
            )
            return self._single_source_results(qdrant_results, self._qdrant_weight)

        if self._strategy == "reciprocal_rank_fusion":
            return self._reciprocal_rank_fusion(qdrant_results, memgraph_results)

        # Default to RRF
        return self._reciprocal_rank_fusion(qdrant_results, memgraph_results)

    def _reciprocal_rank_fusion(
        self,
        qdrant_results: list[dict[str, Any]],
        memgraph_results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Reciprocal Rank Fusion: score(d) = sum(weight_i / (k + rank_i(d)))."""
        # Build entity_id -> result mapping and RRF scores
        scores: dict[str, float] = {}
        entities: dict[str, dict[str, Any]] = {}
        sources: dict[str, list[str]] = {}

        # Process Qdrant results (ranked by semantic similarity)
        for rank, result in enumerate(qdrant_results):
            eid = str(result.get(self._dedup_key, ""))
            if not eid:
                continue
            rrf_score = self._qdrant_weight / (self._rrf_k + rank + 1)
            scores[eid] = scores.get(eid, 0.0) + rrf_score
            if eid not in entities:
                entities[eid] = dict(result)
            sources.setdefault(eid, []).append("qdrant")

        # Process Memgraph results (ranked by structural proximity)
        for rank, result in enumerate(memgraph_results):
            eid = str(result.get(self._dedup_key, ""))
            if not eid:
                continue
            rrf_score = self._memgraph_weight / (self._rrf_k + rank + 1)
            scores[eid] = scores.get(eid, 0.0) + rrf_score
            if eid not in entities:
                entities[eid] = dict(result)
            sources.setdefault(eid, []).append("memgraph")

        # Build fused results
        fused: list[dict[str, Any]] = []
        for eid, combined_score in scores.items():
            if combined_score < self._min_combined_score:
                continue
            result = entities[eid]
            result["combined_score"] = combined_score
            result["fusion_sources"] = sources.get(eid, [])
            fused.append(result)

        # Sort by combined score descending
        fused.sort(key=lambda r: r.get("combined_score", 0.0), reverse=True)
        return fused

    def _single_source_results(
        self,
        results: list[dict[str, Any]],
        weight: float,
    ) -> list[dict[str, Any]]:
        """Apply RRF scoring to single-source results."""
        scored: list[dict[str, Any]] = []
        for rank, result in enumerate(results):
            r = dict(result)
            r["combined_score"] = weight / (self._rrf_k + rank + 1)
            r["fusion_sources"] = ["single_source"]
            if r["combined_score"] >= self._min_combined_score:
                scored.append(r)
        return scored


__all__ = ["HybridSearchFusion"]
