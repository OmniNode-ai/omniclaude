# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for hybrid search fusion (OMN-5682)."""

from __future__ import annotations

import pytest

from omniclaude.hooks.lib.hybrid_search_fusion import HybridSearchFusion

DEFAULT_CONFIG = {
    "enabled": True,
    "strategy": "reciprocal_rank_fusion",
    "qdrant_weight": 0.6,
    "memgraph_weight": 0.4,
    "rrf_k": 60,
    "dedup_key": "entity_id",
    "min_combined_score": 0.0,  # No threshold for test clarity
}


@pytest.mark.unit
class TestHybridSearchFusion:
    """Tests for HybridSearchFusion."""

    def test_rrf_fusion_ranking(self) -> None:
        """Entities in both sources rank higher than single-source."""
        fusion = HybridSearchFusion(DEFAULT_CONFIG)

        qdrant = [
            {"entity_id": "A", "name": "A"},
            {"entity_id": "B", "name": "B"},
            {"entity_id": "C", "name": "C"},
        ]
        memgraph = [
            {"entity_id": "B", "name": "B"},
            {"entity_id": "D", "name": "D"},
            {"entity_id": "A", "name": "A"},
        ]

        fused = fusion.fuse(qdrant, memgraph)

        # A and B appear in both sources, should rank highest
        entity_ids = [r["entity_id"] for r in fused]
        assert len(fused) == 4  # A, B, C, D
        # A: rank 1 in qdrant (0.6/61) + rank 3 in memgraph (0.4/63)
        # B: rank 2 in qdrant (0.6/62) + rank 1 in memgraph (0.4/61)
        # Both A and B should be in top 2 (both in two sources)
        assert set(entity_ids[:2]) == {"A", "B"}
        # C and D are single-source
        assert set(entity_ids[2:]) == {"C", "D"}

        # Verify deduplication — no duplicate entity_ids
        assert len(entity_ids) == len(set(entity_ids))

        # Verify combined_score present
        for r in fused:
            assert "combined_score" in r
            assert r["combined_score"] > 0

    def test_single_source_fallback_qdrant_only(self) -> None:
        """When Memgraph unavailable, returns Qdrant-only results."""
        fusion = HybridSearchFusion(DEFAULT_CONFIG)

        qdrant = [
            {"entity_id": "A", "name": "A"},
            {"entity_id": "B", "name": "B"},
        ]

        fused = fusion.fuse(qdrant_results=qdrant, memgraph_results=None)

        assert len(fused) == 2
        assert fused[0]["entity_id"] == "A"
        assert fused[0]["fusion_sources"] == ["single_source"]

    def test_single_source_fallback_memgraph_only(self) -> None:
        """When Qdrant unavailable, returns Memgraph-only results."""
        fusion = HybridSearchFusion(DEFAULT_CONFIG)

        memgraph = [
            {"entity_id": "X", "name": "X"},
        ]

        fused = fusion.fuse(qdrant_results=None, memgraph_results=memgraph)

        assert len(fused) == 1
        assert fused[0]["entity_id"] == "X"

    def test_min_score_threshold(self) -> None:
        """Results below min_combined_score are discarded."""
        config = {**DEFAULT_CONFIG, "min_combined_score": 0.02}
        fusion = HybridSearchFusion(config)

        # With k=60, single-source score for rank 1 = 0.6/61 ≈ 0.0098
        # This should be below the threshold
        qdrant = [{"entity_id": "A", "name": "A"}]
        fused = fusion.fuse(qdrant_results=qdrant, memgraph_results=[])

        # Single-source results should be filtered out by threshold
        assert len(fused) == 0

    def test_empty_both_sources(self) -> None:
        """Both sources empty returns empty list."""
        fusion = HybridSearchFusion(DEFAULT_CONFIG)
        assert fusion.fuse([], []) == []
