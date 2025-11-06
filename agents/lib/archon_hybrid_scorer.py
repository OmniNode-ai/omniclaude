"""
Archon Hybrid Pattern Scorer

Integrates with Archon Intelligence Service to score patterns using hybrid multi-dimensional scoring.
This replaces the local RelevanceScorer with Archon's production-ready hybrid scoring API.

Performance:
- <1ms per pattern (Archon API)
- Parallel scoring for 150 patterns: <75ms total
- Graceful fallback to keyword-only scoring on error

Reference:
/Volumes/PRO-G40/Code/omniarchon/docs/api/PATTERN_LEARNING_API_FOR_OMNICLAUDE.md
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

from agents.lib.task_classifier import TaskContext
from config import settings

logger = logging.getLogger(__name__)


@dataclass
class ScoringResult:
    """Result from hybrid pattern scoring"""

    hybrid_score: float
    breakdown: Dict[str, float]
    confidence: float
    metadata: Dict[str, Any]
    error: Optional[str] = None


class ArchonHybridScorer:
    """
    Archon Intelligence hybrid pattern scorer.

    Uses Archon's multi-dimensional scoring API that combines:
    - Keyword matching (Jaccard similarity)
    - Semantic similarity (vector search)
    - Quality scores (ONEX compliance)
    - Success rates (historical pattern usage)

    Falls back to keyword-only scoring if API unavailable.
    """

    def __init__(
        self,
        archon_url: str = None,
        timeout: float = 5.0,
        max_retries: int = 2,
        enable_fallback: bool = True,
    ):
        """
        Initialize Archon hybrid scorer.

        Args:
            archon_url: Archon Intelligence Service URL (defaults to settings.archon_intelligence_url)
            timeout: Request timeout in seconds
            max_retries: Maximum retry attempts
            enable_fallback: Enable keyword-only fallback on error
        """
        self.archon_url = archon_url or str(settings.archon_intelligence_url)
        self.hybrid_score_endpoint = (
            f"{self.archon_url}/api/pattern-learning/hybrid/score"
        )
        self.timeout = timeout
        self.max_retries = max_retries
        self.enable_fallback = enable_fallback

        # Track API health
        self._api_available = True
        self._consecutive_failures = 0
        self._max_consecutive_failures = 5

    async def score_pattern_relevance(
        self,
        pattern: Dict[str, Any],
        user_prompt: str,
        task_context: TaskContext,
        include_tree_info: bool = False,
    ) -> float:
        """
        Score pattern relevance using Archon hybrid scoring.

        Args:
            pattern: Pattern dict with keywords and metadata
            user_prompt: User's task description
            task_context: Classified task context
            include_tree_info: Include OnexTree file paths

        Returns:
            Hybrid score (0.0-1.0)
        """
        result = await self.score_pattern_with_breakdown(
            pattern=pattern,
            user_prompt=user_prompt,
            task_context=task_context,
            include_tree_info=include_tree_info,
        )

        return result.hybrid_score

    async def score_pattern_with_breakdown(
        self,
        pattern: Dict[str, Any],
        user_prompt: str,
        task_context: TaskContext,
        include_tree_info: bool = False,
    ) -> ScoringResult:
        """
        Score pattern with detailed breakdown.

        Args:
            pattern: Pattern dict with keywords and metadata
            user_prompt: User's task description
            task_context: Classified task context
            include_tree_info: Include OnexTree file paths

        Returns:
            ScoringResult with score, breakdown, and metadata
        """
        # Skip API if consecutively failing
        if not self._api_available:
            logger.warning("Archon API marked as unavailable, using fallback")
            return await self._fallback_scoring(pattern, task_context)

        # Try API scoring with retries
        for attempt in range(self.max_retries):
            try:
                result = await self._score_via_api(
                    pattern=pattern,
                    task_context=task_context,
                    include_tree_info=include_tree_info,
                )

                # Success - reset failure counter
                self._consecutive_failures = 0
                self._api_available = True

                return result

            except httpx.TimeoutException:
                logger.warning(
                    f"Archon API timeout (attempt {attempt + 1}/{self.max_retries})"
                )
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(0.1 * (attempt + 1))  # Exponential backoff

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 400:
                    # Bad request - don't retry
                    logger.error(f"Invalid input to Archon API: {e.response.text}")
                    break
                elif e.response.status_code >= 500:
                    # Server error - retry
                    logger.warning(
                        f"Archon API server error (attempt {attempt + 1}/{self.max_retries}): {e}"
                    )
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(0.1 * (attempt + 1))
                else:
                    logger.error(f"Archon API error {e.response.status_code}: {e}")
                    break

            except Exception as e:
                logger.error(f"Unexpected error calling Archon API: {e}")
                break

        # All retries failed - mark API as unavailable and use fallback
        self._consecutive_failures += 1

        if self._consecutive_failures >= self._max_consecutive_failures:
            logger.error(
                f"Archon API failed {self._consecutive_failures} times consecutively, "
                f"marking as unavailable"
            )
            self._api_available = False

        if self.enable_fallback:
            logger.info("Using keyword-only fallback scoring")
            return await self._fallback_scoring(pattern, task_context)
        else:
            # Return zero score if fallback disabled
            return ScoringResult(
                hybrid_score=0.0,
                breakdown={},
                confidence=0.0,
                metadata={},
                error="Archon API unavailable and fallback disabled",
            )

    async def _score_via_api(
        self,
        pattern: Dict[str, Any],
        task_context: TaskContext,
        include_tree_info: bool = False,
    ) -> ScoringResult:
        """Call Archon Intelligence API for hybrid scoring"""
        # Extract pattern info
        pattern_keywords = self._extract_pattern_keywords(pattern)
        pattern_metadata = pattern.get("metadata", {})

        # Extract context keywords
        context_keywords = task_context.keywords

        # Build request
        request_data = {
            "pattern": {
                "name": pattern.get("name", pattern.get("pattern_name", "unknown")),
                "keywords": pattern_keywords,
                "metadata": {
                    "quality_score": pattern_metadata.get("quality_score", 0.5),
                    "success_rate": pattern_metadata.get("success_rate", 0.5),
                    "confidence_score": pattern_metadata.get("confidence_score", 0.5),
                    "semantic_score": pattern_metadata.get("semantic_score", 0.5),
                },
            },
            "context": {
                "keywords": context_keywords,
                "task_type": task_context.primary_intent.value,
                "complexity": "moderate",  # Could be made dynamic
            },
            "include_tree_info": include_tree_info,
        }

        # Call API
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(self.hybrid_score_endpoint, json=request_data)
            response.raise_for_status()

            result = response.json()
            data = result["data"]

            return ScoringResult(
                hybrid_score=data["hybrid_score"],
                breakdown=data["breakdown"],
                confidence=data["confidence"],
                metadata=data.get("metadata", {}),
                error=None,
            )

    async def _fallback_scoring(
        self, pattern: Dict[str, Any], task_context: TaskContext
    ) -> ScoringResult:
        """Fallback to keyword-only scoring using Jaccard similarity"""
        pattern_keywords = set(
            kw.lower() for kw in self._extract_pattern_keywords(pattern)
        )
        context_keywords = set(kw.lower() for kw in task_context.keywords)

        if not pattern_keywords or not context_keywords:
            return ScoringResult(
                hybrid_score=0.0,
                breakdown={"keyword_score": 0.0},
                confidence=0.0,
                metadata={"fallback": True, "reason": "empty keywords"},
                error="Empty keywords",
            )

        # Jaccard similarity
        intersection = len(pattern_keywords & context_keywords)
        union = len(pattern_keywords | context_keywords)
        keyword_score = intersection / union if union > 0 else 0.0

        return ScoringResult(
            hybrid_score=keyword_score,
            breakdown={"keyword_score": keyword_score},
            confidence=keyword_score,
            metadata={
                "fallback": True,
                "keyword_matches": intersection,
                "pattern_keywords_count": len(pattern_keywords),
                "context_keywords_count": len(context_keywords),
            },
            error=None,
        )

    def _extract_pattern_keywords(self, pattern: Dict[str, Any]) -> List[str]:
        """Extract keywords from pattern"""
        # Try multiple field names for keywords
        keywords = pattern.get("keywords") or pattern.get("pattern_keywords") or []

        if not keywords:
            # Fallback: extract from name and description
            name = pattern.get("name", pattern.get("pattern_name", ""))
            description = pattern.get(
                "description", pattern.get("pattern_description", "")
            )

            # Basic keyword extraction (split on non-alphanumeric)
            import re

            text = f"{name} {description}".lower()
            keywords = [
                word
                for word in re.findall(r"\w+", text)
                if len(word) > 2  # Minimum 3 chars
            ]

        return keywords

    async def score_patterns_batch(
        self,
        patterns: List[Dict[str, Any]],
        user_prompt: str,
        task_context: TaskContext,
        max_concurrent: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Score multiple patterns in parallel.

        Args:
            patterns: List of pattern dicts
            user_prompt: User's task description
            task_context: Classified task context
            max_concurrent: Maximum concurrent requests

        Returns:
            List of patterns with added 'hybrid_score' field, sorted by score descending
        """
        # Create semaphore to limit concurrency
        semaphore = asyncio.Semaphore(max_concurrent)

        async def score_one(pattern: Dict[str, Any]) -> Dict[str, Any]:
            async with semaphore:
                result = await self.score_pattern_with_breakdown(
                    pattern=pattern, user_prompt=user_prompt, task_context=task_context
                )

                # Add score fields to pattern
                pattern["hybrid_score"] = result.hybrid_score
                pattern["score_breakdown"] = result.breakdown
                pattern["score_confidence"] = result.confidence
                pattern["score_metadata"] = result.metadata

                return pattern

        # Score all patterns in parallel
        scored_patterns = await asyncio.gather(
            *[score_one(pattern) for pattern in patterns], return_exceptions=True
        )

        # Filter out errors and sort by score
        valid_patterns = [p for p in scored_patterns if not isinstance(p, Exception)]
        valid_patterns.sort(key=lambda p: p.get("hybrid_score", 0.0), reverse=True)

        return valid_patterns

    async def health_check(self) -> bool:
        """
        Check if Archon Intelligence API is healthy.

        Returns:
            True if API is responding, False otherwise
        """
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(
                    f"{self.archon_url}/api/pattern-learning/health"
                )
                response.raise_for_status()

                data = response.json()
                is_healthy = data.get("status") == "healthy"

                if is_healthy:
                    self._api_available = True
                    self._consecutive_failures = 0

                return is_healthy

        except Exception as e:
            logger.warning(f"Archon API health check failed: {e}")
            return False
