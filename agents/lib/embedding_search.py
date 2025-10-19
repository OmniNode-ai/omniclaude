"""
Embedding-based Similarity Search for Error Patterns

Implements semantic search for error patterns to enable intelligent STF recommendations
based on historical data. Uses embeddings to find similar errors and their successful fixes.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import numpy as np

from .db import get_pg_pool


@dataclass
class SimilarityResult:
    """Result of similarity search."""

    error_id: str
    similarity_score: float
    error_type: str
    message: str
    details: Dict[str, Any]
    created_at: datetime
    success_correlations: List[Dict[str, Any]]


class EmbeddingSearch:
    """Semantic search engine for error patterns and STF recommendations."""

    def __init__(self):
        self.pool = None
        self._embedding_cache = {}

    async def _get_pool(self):
        """Get database pool."""
        if self.pool is None:
            self.pool = await get_pg_pool()
        return self.pool

    async def _get_error_embedding(self, error_text: str) -> np.ndarray:
        """
        Get embedding for error text.

        For now, uses a simple TF-IDF-like approach.
        In production, this would use a proper embedding model like OpenAI embeddings.
        """
        # Simple text-based similarity for MVP
        # In production, replace with actual embedding model
        words = error_text.lower().split()
        word_counts = {}
        for word in words:
            word_counts[word] = word_counts.get(word, 0) + 1

        # Create a simple vector representation
        all_words = set(word_counts.keys())
        vector = np.array([word_counts.get(word, 0) for word in sorted(all_words)])

        # Normalize
        if np.linalg.norm(vector) > 0:
            vector = vector / np.linalg.norm(vector)

        return vector

    async def _calculate_similarity(
        self, embedding1: np.ndarray, embedding2: np.ndarray
    ) -> float:
        """Calculate cosine similarity between two embeddings."""
        if len(embedding1) == 0 or len(embedding2) == 0:
            return 0.0

        # Pad or truncate to same length
        max_len = max(len(embedding1), len(embedding2))
        if len(embedding1) < max_len:
            embedding1 = np.pad(embedding1, (0, max_len - len(embedding1)))
        if len(embedding2) < max_len:
            embedding2 = np.pad(embedding2, (0, max_len - len(embedding2)))

        # Calculate cosine similarity
        dot_product = np.dot(embedding1, embedding2)
        norm1 = np.linalg.norm(embedding1)
        norm2 = np.linalg.norm(embedding2)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot_product / (norm1 * norm2)

    async def find_similar_errors(
        self,
        error_text: str,
        error_type: Optional[str] = None,
        limit: int = 10,
        min_similarity: float = 0.3,
    ) -> List[SimilarityResult]:
        """
        Find similar errors based on semantic similarity.

        Args:
            error_text: The error text to find similarities for
            error_type: Optional error type filter
            limit: Maximum number of results
            min_similarity: Minimum similarity score threshold

        Returns:
            List of similar errors with scores
        """
        pool = await self._get_pool()
        if pool is None:
            return []

        # Get embedding for the query error
        query_embedding = await self._get_error_embedding(error_text)

        # Build query for error events
        where_conditions = []
        params = []
        param_count = 0

        if error_type:
            param_count += 1
            where_conditions.append(f"error_type = ${param_count}")
            params.append(error_type)

        # Add time filter to focus on recent errors
        param_count += 1
        where_conditions.append(f"created_at >= ${param_count}")
        params.append(datetime.now() - timedelta(days=30))  # Last 30 days

        query = f"""
            SELECT id, error_type, message, details, created_at
            FROM error_events
            WHERE {' AND '.join(where_conditions)}
            ORDER BY created_at DESC
            LIMIT 100
        """

        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

            similarities = []
            for row in rows:
                # Get embedding for this error
                error_embedding = await self._get_error_embedding(row["message"])

                # Calculate similarity
                similarity = await self._calculate_similarity(
                    query_embedding, error_embedding
                )

                if similarity >= min_similarity:
                    # Get success correlations for this error
                    success_correlations = await self._get_success_correlations(
                        row["id"], conn
                    )

                    similarities.append(
                        SimilarityResult(
                            error_id=row["id"],
                            similarity_score=similarity,
                            error_type=row["error_type"],
                            message=row["message"],
                            details=row["details"],
                            created_at=row["created_at"],
                            success_correlations=success_correlations,
                        )
                    )

            # Sort by similarity score and return top results
            similarities.sort(key=lambda x: x.similarity_score, reverse=True)
            return similarities[:limit]

    async def _get_success_correlations(
        self, error_id: str, conn
    ) -> List[Dict[str, Any]]:
        """Get success correlations for an error."""
        try:
            rows = await conn.fetch(
                """
                SELECT esm.id, esm.uplift_ms, esm.uplift_cost_usd, esm.n_trials, esm.n_success,
                       dtf.name as stf_name, dtf.version as stf_version
                FROM error_success_maps esm
                LEFT JOIN debug_transform_functions dtf ON esm.tf_id = dtf.id
                WHERE esm.error_id = $1
                ORDER BY esm.n_success DESC, esm.last_seen_at DESC
                """,
                error_id,
            )

            return [dict(row) for row in rows]
        except Exception:
            return []

    async def recommend_stfs(
        self, error_text: str, error_type: Optional[str] = None, limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Recommend STFs based on similar error patterns.

        Args:
            error_text: The error text to find recommendations for
            error_type: Optional error type filter
            limit: Maximum number of recommendations

        Returns:
            List of recommended STFs with confidence scores
        """
        # Find similar errors
        similar_errors = await self.find_similar_errors(
            error_text=error_text, error_type=error_type, limit=20, min_similarity=0.2
        )

        if not similar_errors:
            return []

        # Aggregate STF recommendations from similar errors
        stf_scores = {}

        for similar_error in similar_errors:
            for correlation in similar_error.success_correlations:
                if correlation.get("stf_name"):
                    stf_key = f"{correlation['stf_name']}:{correlation.get('stf_version', 'unknown')}"

                    if stf_key not in stf_scores:
                        stf_scores[stf_key] = {
                            "stf_name": correlation["stf_name"],
                            "stf_version": correlation.get("stf_version", "unknown"),
                            "total_similarity": 0.0,
                            "total_successes": 0,
                            "total_trials": 0,
                            "avg_uplift_ms": 0.0,
                            "avg_uplift_cost_usd": 0.0,
                            "confidence": 0.0,
                        }

                    # Weight by similarity score
                    weight = similar_error.similarity_score
                    stf_scores[stf_key]["total_similarity"] += weight
                    stf_scores[stf_key]["total_successes"] += (
                        correlation.get("n_success", 0) * weight
                    )
                    stf_scores[stf_key]["total_trials"] += (
                        correlation.get("n_trials", 0) * weight
                    )
                    stf_scores[stf_key]["avg_uplift_ms"] += (
                        correlation.get("uplift_ms", 0) * weight
                    )
                    stf_scores[stf_key]["avg_uplift_cost_usd"] += (
                        float(correlation.get("uplift_cost_usd", 0)) * weight
                    )

        # Calculate confidence scores
        recommendations = []
        for stf_key, data in stf_scores.items():
            if data["total_trials"] > 0:
                success_rate = data["total_successes"] / data["total_trials"]
                confidence = (
                    data["total_similarity"] / len(similar_errors)
                ) * success_rate

                recommendations.append(
                    {
                        "stf_name": data["stf_name"],
                        "stf_version": data["stf_version"],
                        "confidence": confidence,
                        "success_rate": success_rate,
                        "total_similarities": data["total_similarity"],
                        "total_successes": data["total_successes"],
                        "total_trials": data["total_trials"],
                        "avg_uplift_ms": data["avg_uplift_ms"]
                        / max(1, data["total_similarity"]),
                        "avg_uplift_cost_usd": data["avg_uplift_cost_usd"]
                        / max(1, data["total_similarity"]),
                    }
                )

        # Sort by confidence and return top recommendations
        recommendations.sort(key=lambda x: x["confidence"], reverse=True)
        return recommendations[:limit]

    async def get_error_patterns(
        self, days: int = 7, min_frequency: int = 2
    ) -> List[Dict[str, Any]]:
        """
        Get common error patterns from recent data.

        Args:
            days: Number of days to analyze
            min_frequency: Minimum frequency for pattern inclusion

        Returns:
            List of error patterns with statistics
        """
        pool = await self._get_pool()
        if pool is None:
            return []

        since_date = datetime.now() - timedelta(days=days)

        async with pool.acquire() as conn:
            # Get error frequency by type and message pattern
            rows = await conn.fetch(
                """
                SELECT
                    error_type,
                    message,
                    COUNT(*) as frequency,
                    COUNT(DISTINCT run_id) as affected_runs
                FROM error_events
                WHERE created_at >= $1
                GROUP BY error_type, message
                HAVING COUNT(*) >= $2
                ORDER BY frequency DESC
                """,
                since_date,
                min_frequency,
            )

            patterns = []
            for row in rows:
                # Get success correlations for this pattern
                success_correlations = await self._get_success_correlations_for_pattern(
                    row["error_type"], row["message"], conn
                )

                patterns.append(
                    {
                        "error_type": row["error_type"],
                        "message": row["message"],
                        "frequency": row["frequency"],
                        "affected_runs": row["affected_runs"],
                        "success_correlations": success_correlations,
                    }
                )

            return patterns

    async def _get_success_correlations_for_pattern(
        self, error_type: str, message: str, conn
    ) -> List[Dict[str, Any]]:
        """Get success correlations for a specific error pattern."""
        try:
            rows = await conn.fetch(
                """
                SELECT esm.id, esm.uplift_ms, esm.uplift_cost_usd, esm.n_trials, esm.n_success,
                       dtf.name as stf_name, dtf.version as stf_version
                FROM error_events e
                JOIN error_success_maps esm ON e.id = esm.error_id
                LEFT JOIN debug_transform_functions dtf ON esm.tf_id = dtf.id
                WHERE e.error_type = $1 AND e.message = $2
                ORDER BY esm.n_success DESC
                """,
                error_type,
                message,
            )

            return [dict(row) for row in rows]
        except Exception:
            return []


# Global embedding search instance
embedding_search = EmbeddingSearch()


async def find_similar_errors(
    error_text: str, error_type: Optional[str] = None, limit: int = 10
) -> List[SimilarityResult]:
    """Find similar errors based on semantic similarity."""
    return await embedding_search.find_similar_errors(
        error_text=error_text, error_type=error_type, limit=limit
    )


async def recommend_stfs_for_error(
    error_text: str, error_type: Optional[str] = None, limit: int = 5
) -> List[Dict[str, Any]]:
    """Recommend STFs based on similar error patterns."""
    return await embedding_search.recommend_stfs(
        error_text=error_text, error_type=error_type, limit=limit
    )


async def get_error_patterns_analysis(
    days: int = 7, min_frequency: int = 2
) -> List[Dict[str, Any]]:
    """Get common error patterns from recent data."""
    return await embedding_search.get_error_patterns(
        days=days, min_frequency=min_frequency
    )
