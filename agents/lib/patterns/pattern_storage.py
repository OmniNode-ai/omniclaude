#!/usr/bin/env python3
"""
Pattern Storage - Store and retrieve patterns using Qdrant vector database.

Part of KV-002 (Pattern Recognition) quality gate integration.
Provides vector similarity search for intelligent pattern reuse.

Storage Strategy:
- Qdrant for vector embeddings and similarity search
- Metadata filtering for pattern_type, confidence, etc.
- Usage statistics tracking (usage_count, last_used)
- In-memory fallback for testing/development

ONEX v2.0 Compliance:
- Type-safe Qdrant integration
- Performance tracking (<300ms target)
- Graceful degradation without Qdrant
"""

import hashlib
import logging
from datetime import datetime
from typing import Any

# Import Pydantic Settings for type-safe configuration
from config import settings

from ..models.model_code_pattern import ModelCodePattern, ModelPatternMatch

logger = logging.getLogger(__name__)


class PatternStorage:
    """
    Store and retrieve patterns using Qdrant vector database.

    Provides:
    - Pattern storage with vector embeddings
    - Similarity search by embedding
    - Metadata filtering (pattern_type, confidence)
    - Usage statistics tracking
    - In-memory fallback when Qdrant unavailable

    Example:
        storage = PatternStorage()
        await storage.store_pattern(pattern, embedding)
        matches = await storage.query_similar_patterns(
            query_embedding,
            pattern_type="workflow",
            min_confidence=0.7
        )
    """

    def __init__(
        self,
        qdrant_url: str | None = None,
        collection_name: str = "code_generation_patterns",
        use_in_memory: bool = False,
    ) -> None:
        """
        Initialize pattern storage.

        Args:
            qdrant_url: Qdrant server URL (defaults to settings.qdrant_url if not provided)
            collection_name: Collection name for patterns
            use_in_memory: Use in-memory storage instead of Qdrant
        """
        # Use Pydantic settings if qdrant_url not explicitly provided
        if qdrant_url is None:
            qdrant_url = settings.qdrant_url
        self.qdrant_url = qdrant_url
        self.collection_name = collection_name
        self.use_in_memory = use_in_memory

        # In-memory storage for testing/fallback
        self._memory_storage: dict[str, tuple[ModelCodePattern, list[float]]] = {}

        # Try to initialize Qdrant client
        self.client = None
        if not use_in_memory:
            try:
                from qdrant_client import QdrantClient

                self.client = QdrantClient(url=qdrant_url)
                self._ensure_collection()
                logger.info(f"Connected to Qdrant at {qdrant_url}")
            except Exception as e:
                logger.warning(
                    f"Failed to connect to Qdrant: {e}. Using in-memory storage."
                )
                self.use_in_memory = True

    def _ensure_collection(self) -> None:
        """
        Ensure collection exists in Qdrant.

        Creates collection if it doesn't exist with:
        - Vector size: 384 (sentence-transformers default)
        - Distance metric: Cosine
        - Metadata: pattern_type, confidence_score, usage_count
        """
        if not self.client:
            return

        try:
            from qdrant_client.models import Distance, VectorParams

            # Check if collection exists
            collections = self.client.get_collections().collections
            collection_names = [c.name for c in collections]

            if self.collection_name not in collection_names:
                # Create collection
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(
                        size=384,  # sentence-transformers/all-MiniLM-L6-v2
                        distance=Distance.COSINE,
                    ),
                )
                logger.info(f"Created Qdrant collection: {self.collection_name}")
        except Exception as e:
            logger.error(f"Failed to ensure collection: {e}")
            raise

    async def store_pattern(
        self, pattern: ModelCodePattern, embedding: list[float]
    ) -> str:
        """
        Store pattern with vector embedding.

        Args:
            pattern: Pattern to store
            embedding: Vector embedding for similarity search

        Returns:
            Pattern ID

        Raises:
            Exception: If storage fails
        """
        if self.use_in_memory or not self.client:
            # In-memory storage
            self._memory_storage[pattern.pattern_id] = (pattern, embedding)
            logger.debug(f"Stored pattern {pattern.pattern_id} in memory")
            return pattern.pattern_id

        try:
            from qdrant_client.models import PointStruct

            # Create point with metadata
            point = PointStruct(
                id=self._id_to_int(pattern.pattern_id),
                vector=embedding,
                payload={
                    "pattern_id": pattern.pattern_id,
                    "pattern_type": pattern.pattern_type.value,
                    "pattern_name": pattern.pattern_name,
                    "pattern_description": pattern.pattern_description,
                    "confidence_score": pattern.confidence_score,
                    "pattern_template": pattern.pattern_template,
                    "example_usage": pattern.example_usage,
                    "source_context": pattern.source_context,
                    "reuse_conditions": pattern.reuse_conditions,
                    "created_at": pattern.created_at.isoformat(),
                    "last_used": (
                        pattern.last_used.isoformat() if pattern.last_used else None
                    ),
                    "usage_count": pattern.usage_count,
                    "success_rate": pattern.success_rate,
                    "average_quality_score": pattern.average_quality_score,
                },
            )

            # Store in Qdrant
            self.client.upsert(
                collection_name=self.collection_name, points=[point], wait=True
            )

            # Also cache in memory for faster updates
            self._memory_storage[pattern.pattern_id] = (pattern, embedding)

            logger.info(
                f"Stored pattern {pattern.pattern_id} ({pattern.pattern_type.value})"
            )
            return pattern.pattern_id

        except Exception as e:
            logger.error(f"Failed to store pattern: {e}")
            # Fallback to in-memory
            self._memory_storage[pattern.pattern_id] = (pattern, embedding)
            return pattern.pattern_id

    async def query_similar_patterns(
        self,
        query_embedding: list[float],
        pattern_type: str | None = None,
        limit: int = 5,
        min_confidence: float = 0.7,
    ) -> list[ModelPatternMatch]:
        """
        Query similar patterns by embedding.

        Args:
            query_embedding: Query vector embedding
            pattern_type: Optional filter by pattern type
            limit: Maximum number of results
            min_confidence: Minimum confidence score filter

        Returns:
            List of pattern matches sorted by similarity
        """
        if self.use_in_memory or not self.client:
            # In-memory similarity search
            return self._memory_search(
                query_embedding, pattern_type, limit, min_confidence
            )

        try:
            from qdrant_client.models import FieldCondition, Filter, MatchValue

            # Build filter
            must_conditions = []
            if pattern_type:
                must_conditions.append(
                    FieldCondition(
                        key="pattern_type", match=MatchValue(value=pattern_type)
                    )
                )

            # Add confidence filter
            must_conditions.append(
                FieldCondition(
                    key="confidence_score",
                    range={
                        "gte": min_confidence,
                    },
                )
            )

            query_filter = Filter(must=must_conditions) if must_conditions else None

            # Search
            results = self.client.search(
                collection_name=self.collection_name,
                query_vector=query_embedding,
                query_filter=query_filter,
                limit=limit,
                with_payload=True,
            )

            # Convert to ModelPatternMatch
            matches: list[ModelPatternMatch] = []
            for result in results:
                payload = result.payload
                pattern = ModelCodePattern(
                    pattern_id=payload["pattern_id"],
                    pattern_type=payload["pattern_type"],
                    pattern_name=payload["pattern_name"],
                    pattern_description=payload["pattern_description"],
                    confidence_score=payload["confidence_score"],
                    pattern_template=payload["pattern_template"],
                    example_usage=payload["example_usage"],
                    source_context=payload["source_context"],
                    reuse_conditions=payload["reuse_conditions"],
                    created_at=datetime.fromisoformat(payload["created_at"]),
                    last_used=(
                        datetime.fromisoformat(payload["last_used"])
                        if payload["last_used"]
                        else None
                    ),
                    usage_count=payload["usage_count"],
                    success_rate=payload["success_rate"],
                    average_quality_score=payload["average_quality_score"],
                )

                matches.append(
                    ModelPatternMatch(
                        pattern=pattern,
                        similarity_score=result.score,
                        match_reason=f"Vector similarity: {result.score:.2f}",
                        applicable=True,  # Could add more logic here
                    )
                )

            logger.debug(f"Found {len(matches)} similar patterns")
            return matches

        except Exception as e:
            logger.error(f"Failed to query patterns: {e}")
            # Fallback to in-memory search
            return self._memory_search(
                query_embedding, pattern_type, limit, min_confidence
            )

    async def get_pattern_by_id(self, pattern_id: str) -> ModelCodePattern | None:
        """
        Retrieve specific pattern by ID.

        Args:
            pattern_id: Pattern ID to retrieve

        Returns:
            Pattern if found, None otherwise
        """
        if self.use_in_memory or not self.client:
            # In-memory lookup
            result = self._memory_storage.get(pattern_id)
            return result[0] if result else None

        try:
            from qdrant_client.models import FieldCondition, Filter, MatchValue

            # Search by pattern_id
            results = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=Filter(
                    must=[
                        FieldCondition(
                            key="pattern_id", match=MatchValue(value=pattern_id)
                        )
                    ]
                ),
                limit=1,
                with_payload=True,
            )

            if not results[0]:
                return None

            payload = results[0][0].payload
            return ModelCodePattern(
                pattern_id=payload["pattern_id"],
                pattern_type=payload["pattern_type"],
                pattern_name=payload["pattern_name"],
                pattern_description=payload["pattern_description"],
                confidence_score=payload["confidence_score"],
                pattern_template=payload["pattern_template"],
                example_usage=payload["example_usage"],
                source_context=payload["source_context"],
                reuse_conditions=payload["reuse_conditions"],
                created_at=datetime.fromisoformat(payload["created_at"]),
                last_used=(
                    datetime.fromisoformat(payload["last_used"])
                    if payload["last_used"]
                    else None
                ),
                usage_count=payload["usage_count"],
                success_rate=payload["success_rate"],
                average_quality_score=payload["average_quality_score"],
            )

        except Exception as e:
            logger.error(f"Failed to get pattern by ID: {e}")
            return None

    async def update_pattern_usage(
        self, pattern_id: str, success: bool = True, quality_score: float = 0.0
    ) -> None:
        """
        Update pattern usage statistics.

        Args:
            pattern_id: Pattern to update
            success: Whether pattern application succeeded
            quality_score: Quality score of generated code (0.0-1.0)
        """
        pattern = await self.get_pattern_by_id(pattern_id)
        if not pattern:
            logger.warning(f"Pattern {pattern_id} not found for update")
            return

        # Update statistics
        pattern.update_usage(success=success, quality_score=quality_score)

        # Re-store with updated stats (if using Qdrant)
        if not self.use_in_memory and self.client:
            try:
                # Get existing embedding
                if pattern_id in self._memory_storage:
                    embedding = self._memory_storage[pattern_id][1]
                else:
                    # Need to retrieve embedding - for simplicity, skip update
                    logger.warning(
                        f"Cannot update {pattern_id} in Qdrant: embedding not cached"
                    )
                    return

                await self.store_pattern(pattern, embedding)
                logger.debug(f"Updated usage stats for pattern {pattern_id}")

            except Exception as e:
                logger.error(f"Failed to update pattern usage: {e}")
        else:
            # Update in-memory storage
            if pattern_id in self._memory_storage:
                embedding = self._memory_storage[pattern_id][1]
                self._memory_storage[pattern_id] = (pattern, embedding)

    def _memory_search(
        self,
        query_embedding: list[float],
        pattern_type: str | None,
        limit: int,
        min_confidence: float,
    ) -> list[ModelPatternMatch]:
        """
        In-memory similarity search using cosine similarity.

        Args:
            query_embedding: Query vector
            pattern_type: Optional type filter
            limit: Max results
            min_confidence: Min confidence filter

        Returns:
            List of pattern matches
        """
        matches: list[ModelPatternMatch] = []

        for pattern_id, (pattern, embedding) in self._memory_storage.items():
            # Filter by pattern type
            if pattern_type and pattern.pattern_type.value != pattern_type:
                continue

            # Filter by confidence
            if pattern.confidence_score < min_confidence:
                continue

            # Calculate cosine similarity
            similarity = self._cosine_similarity(query_embedding, embedding)

            matches.append(
                ModelPatternMatch(
                    pattern=pattern,
                    similarity_score=similarity,
                    match_reason=f"In-memory cosine similarity: {similarity:.2f}",
                    applicable=True,
                )
            )

        # Sort by similarity (descending)
        matches.sort(key=lambda m: m.similarity_score, reverse=True)

        return matches[:limit]

    @staticmethod
    def _cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
        """
        Calculate cosine similarity between two vectors.

        Args:
            vec1: First vector
            vec2: Second vector

        Returns:
            Cosine similarity (0.0-1.0)
        """
        import math

        # Dot product
        dot_product = sum(a * b for a, b in zip(vec1, vec2))

        # Magnitudes
        magnitude1 = math.sqrt(sum(a * a for a in vec1))
        magnitude2 = math.sqrt(sum(b * b for b in vec2))

        if magnitude1 == 0 or magnitude2 == 0:
            return 0.0

        # Clamp to [0.0, 1.0] to handle floating point precision issues
        similarity = dot_product / (magnitude1 * magnitude2)
        return max(0.0, min(1.0, similarity))

    @staticmethod
    def _id_to_int(pattern_id: str) -> int:
        """
        Convert UUID pattern_id to integer for Qdrant.

        Qdrant requires integer IDs, so we hash the UUID.

        Args:
            pattern_id: UUID string

        Returns:
            Integer ID
        """
        # Use first 8 bytes of SHA256 hash (B324 fix - replaced MD5 with SHA256)
        # This is non-cryptographic use (just deterministic ID generation)
        hash_bytes = hashlib.sha256(pattern_id.encode()).digest()[:8]
        return int.from_bytes(hash_bytes, byteorder="big") % (2**63 - 1)

    async def get_storage_stats(self) -> dict[str, Any]:
        """
        Get storage statistics.

        Returns:
            Dictionary with storage metrics
        """
        if self.use_in_memory or not self.client:
            return {
                "storage_type": "in_memory",
                "total_patterns": len(self._memory_storage),
                "patterns_by_type": self._count_patterns_by_type(self._memory_storage),
            }

        try:
            collection_info = self.client.get_collection(self.collection_name)
            return {
                "storage_type": "qdrant",
                "qdrant_url": self.qdrant_url,
                "collection_name": self.collection_name,
                "total_patterns": collection_info.points_count,
                "vector_size": collection_info.config.params.vectors.size,
            }
        except Exception as e:
            logger.error(f"Failed to get storage stats: {e}")
            return {"storage_type": "error", "error": str(e)}

    @staticmethod
    def _count_patterns_by_type(
        storage: dict[str, tuple[ModelCodePattern, list[float]]]
    ) -> dict[str, int]:
        """Count patterns by type in in-memory storage."""
        counts: dict[str, int] = {}
        for pattern, _ in storage.values():
            pattern_type = pattern.pattern_type.value
            counts[pattern_type] = counts.get(pattern_type, 0) + 1
        return counts
