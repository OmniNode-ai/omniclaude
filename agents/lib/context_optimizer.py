"""
Context Learning and Optimization

Learns from successful context selections and optimizes context gathering
based on task types and historical performance data.
"""

import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from .db import get_pg_pool


@dataclass
class ContextLearningRecord:
    """Record of context learning data."""

    task_type: str
    context_keys: List[str]
    success_rate: float
    sample_count: int
    avg_duration_ms: float
    last_updated: datetime = field(default_factory=datetime.now)


@dataclass
class ContextOptimization:
    """Context optimization recommendation."""

    task_type: str
    recommended_contexts: List[str]
    confidence: float
    expected_improvement: float
    reasoning: str


class ContextOptimizer:
    """
    Learns from successful context selections and optimizes context gathering.

    Features:
    - Learning from execution outcomes
    - Context effectiveness analysis
    - Predictive context recommendations
    - Performance-based optimization
    - Task-type specific learning
    """

    def __init__(self):
        self.learning_cache: Dict[str, ContextLearningRecord] = {}
        self.task_patterns: Dict[str, List[str]] = defaultdict(list)
        self.context_effectiveness: Dict[str, float] = {}
        self._cache_ttl = 3600  # 1 hour
        self._last_cache_update: float = 0.0

    async def learn_from_success(
        self,
        prompt: str,
        context_types: List[str],
        success_rate: float,
        avg_duration: float,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        Learn from a successful context execution.

        Args:
            prompt: User prompt that was successful
            context_types: Context types that were used
            success_rate: Success rate achieved
            avg_duration: Average duration in milliseconds
            metadata: Additional metadata
        """
        # Delegate to learn_from_execution with success=True
        await self.learn_from_execution(
            task_type="prompt_execution",
            context_keys=context_types,
            success=success_rate >= 0.8,  # Consider 80%+ as success
            duration_ms=avg_duration,
            metadata=metadata,
        )

    async def learn_from_execution(
        self,
        task_type: str,
        context_keys: List[str],
        success: bool,
        duration_ms: float,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        Learn from a context execution outcome.

        Args:
            task_type: Type of task executed
            context_keys: Context keys that were used
            success: Whether execution was successful
            duration_ms: Execution duration in milliseconds
            metadata: Additional execution metadata
        """
        try:
            # Update learning cache
            cache_key = f"{task_type}:{':'.join(sorted(context_keys))}"

            if cache_key not in self.learning_cache:
                self.learning_cache[cache_key] = ContextLearningRecord(
                    task_type=task_type,
                    context_keys=context_keys,
                    success_rate=0.0,
                    sample_count=0,
                    avg_duration_ms=0.0,
                )

            record = self.learning_cache[cache_key]

            # Update statistics
            record.sample_count += 1
            if success:
                record.success_rate = (
                    (record.success_rate * (record.sample_count - 1)) + 1.0
                ) / record.sample_count
            else:
                record.success_rate = (
                    record.success_rate * (record.sample_count - 1)
                ) / record.sample_count

            # Update average duration
            record.avg_duration_ms = (
                (record.avg_duration_ms * (record.sample_count - 1)) + duration_ms
            ) / record.sample_count
            record.last_updated = datetime.now()

            # Update task patterns
            self.task_patterns[task_type].extend(context_keys)

            # Persist to database
            await self._persist_learning_record(record)

        except Exception as e:
            print(f"Warning: Context learning failed: {e}")

    async def optimize_context_for_task(
        self, task_type: str, available_contexts: List[str], max_contexts: int = 5
    ) -> List[str]:
        """
        Return optimized context selection for a task type.

        Args:
            task_type: Type of task to optimize for
            available_contexts: Available context keys
            max_contexts: Maximum number of contexts to return

        Returns:
            List of optimized context keys
        """
        try:
            # Load learning data if cache is stale
            if time.time() - self._last_cache_update > self._cache_ttl:
                await self._load_learning_data()

            # Get task-specific learning records
            task_records = [
                record
                for record in self.learning_cache.values()
                if record.task_type == task_type and record.sample_count >= 3
            ]

            if not task_records:
                # No learning data available, return first few available contexts
                return available_contexts[:max_contexts]

            # Sort by effectiveness (success rate * speed factor)
            def effectiveness_score(record: ContextLearningRecord) -> float:
                speed_factor = 1.0 / (
                    1.0 + record.avg_duration_ms / 1000.0
                )  # Prefer faster contexts
                return record.success_rate * speed_factor

            task_records.sort(key=effectiveness_score, reverse=True)

            # Select best contexts that are available
            optimized_contexts = []
            for record in task_records:
                for context_key in record.context_keys:
                    if (
                        context_key in available_contexts
                        and context_key not in optimized_contexts
                    ):
                        optimized_contexts.append(context_key)
                        if len(optimized_contexts) >= max_contexts:
                            break
                if len(optimized_contexts) >= max_contexts:
                    break

            # Fill remaining slots with available contexts
            for context_key in available_contexts:
                if (
                    context_key not in optimized_contexts
                    and len(optimized_contexts) < max_contexts
                ):
                    optimized_contexts.append(context_key)

            return optimized_contexts

        except Exception as e:
            print(f"Warning: Context optimization failed: {e}")
            return available_contexts[:max_contexts]

    async def predict_context_needs(self, user_prompt: str) -> List[str]:
        """
        Predict required context types based on prompt analysis.

        Args:
            user_prompt: User's original request

        Returns:
            List of predicted context types
        """
        try:
            # Analyze prompt for keywords and patterns
            prompt_lower = user_prompt.lower()

            # Architecture-related keywords
            architecture_keywords = [
                "onex",
                "architecture",
                "pattern",
                "node",
                "effect",
                "compute",
                "reducer",
                "validator",
                "orchestrator",
                "protocol",
                "spi",
                "omninode",
                "omnibase",
                "omniagent",
                "omnimcp",
            ]

            # API-related keywords
            api_keywords = [
                "api",
                "endpoint",
                "rest",
                "graphql",
                "service",
                "microservice",
                "controller",
                "handler",
                "route",
                "method",
            ]

            # Database-related keywords
            database_keywords = [
                "database",
                "db",
                "sql",
                "postgres",
                "mysql",
                "mongodb",
                "query",
                "table",
                "schema",
                "migration",
            ]

            # Security-related keywords
            security_keywords = [
                "auth",
                "authentication",
                "authorization",
                "security",
                "jwt",
                "oauth",
                "token",
                "permission",
                "role",
                "access",
            ]

            # Predict context needs based on keywords
            predicted_contexts = []

            if any(keyword in prompt_lower for keyword in architecture_keywords):
                predicted_contexts.extend(
                    ["rag:domain-patterns", "pattern:onex-architecture"]
                )

            if any(keyword in prompt_lower for keyword in api_keywords):
                predicted_contexts.extend(["rag:api-patterns", "pattern:api-design"])

            if any(keyword in prompt_lower for keyword in database_keywords):
                predicted_contexts.extend(
                    ["rag:database-patterns", "pattern:data-modeling"]
                )

            if any(keyword in prompt_lower for keyword in security_keywords):
                predicted_contexts.extend(
                    ["rag:security-patterns", "pattern:auth-design"]
                )

            # Always include general patterns if no specific patterns found
            if not predicted_contexts:
                predicted_contexts = ["rag:domain-patterns", "pattern:general"]

            return predicted_contexts

        except Exception as e:
            print(f"Warning: Context prediction failed: {e}")
            return ["rag:domain-patterns", "pattern:general"]

    async def get_context_effectiveness_analysis(
        self, days: int = 30
    ) -> Dict[str, Any]:
        """
        Get analysis of context effectiveness over time.

        Args:
            days: Number of days to analyze

        Returns:
            Dictionary with effectiveness analysis
        """
        try:
            pool = await get_pg_pool()
            if pool is None:
                return {}

            since_date = datetime.now() - timedelta(days=days)

            async with pool.acquire() as conn:
                # Get context usage statistics
                context_stats = await conn.fetch(
                    """
                    SELECT
                        context_keys,
                        AVG(success_rate) as avg_success_rate,
                        AVG(avg_duration_ms) as avg_duration_ms,
                        SUM(sample_count) as total_samples
                    FROM context_learning
                    WHERE last_updated >= $1
                    GROUP BY context_keys
                    ORDER BY avg_success_rate DESC
                    """,
                    since_date,
                )

                # Get task type effectiveness
                task_effectiveness = await conn.fetch(
                    """
                    SELECT
                        task_type,
                        AVG(success_rate) as avg_success_rate,
                        AVG(avg_duration_ms) as avg_duration_ms,
                        SUM(sample_count) as total_samples
                    FROM context_learning
                    WHERE last_updated >= $1
                    GROUP BY task_type
                    ORDER BY avg_success_rate DESC
                    """,
                    since_date,
                )

                return {
                    "analysis_period_days": days,
                    "since_date": since_date.isoformat(),
                    "context_effectiveness": [dict(row) for row in context_stats],
                    "task_effectiveness": [dict(row) for row in task_effectiveness],
                    "total_context_combinations": len(context_stats),
                    "total_task_types": len(task_effectiveness),
                }

        except Exception as e:
            print(f"Warning: Context effectiveness analysis failed: {e}")
            return {}

    async def _persist_learning_record(self, record: ContextLearningRecord):
        """Persist learning record to database."""
        try:
            pool = await get_pg_pool()
            if pool is None:
                return

            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO context_learning (
                        id, task_type, context_keys, success_rate, sample_count,
                        avg_duration_ms, last_updated
                    ) VALUES (
                        gen_random_uuid(), $1, $2, $3, $4, $5, $6
                    )
                    ON CONFLICT (task_type, context_keys) DO UPDATE SET
                        success_rate = EXCLUDED.success_rate,
                        sample_count = EXCLUDED.sample_count,
                        avg_duration_ms = EXCLUDED.avg_duration_ms,
                        last_updated = EXCLUDED.last_updated
                    """,
                    record.task_type,
                    record.context_keys,
                    record.success_rate,
                    record.sample_count,
                    record.avg_duration_ms,
                    record.last_updated,
                )
        except Exception as e:
            print(f"Warning: Failed to persist learning record: {e}")

    async def _load_learning_data(self):
        """Load learning data from database."""
        try:
            pool = await get_pg_pool()
            if pool is None:
                return

            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT task_type, context_keys, success_rate, sample_count,
                           avg_duration_ms, last_updated
                    FROM context_learning
                    ORDER BY last_updated DESC
                    """
                )

                self.learning_cache.clear()
                for row in rows:
                    cache_key = f"{row['task_type']}:{':'.join(row['context_keys'])}"
                    self.learning_cache[cache_key] = ContextLearningRecord(
                        task_type=row["task_type"],
                        context_keys=row["context_keys"],
                        success_rate=row["success_rate"],
                        sample_count=row["sample_count"],
                        avg_duration_ms=row["avg_duration_ms"],
                        last_updated=row["last_updated"],
                    )

                self._last_cache_update = time.time()

        except Exception as e:
            print(f"Warning: Failed to load learning data: {e}")

    def get_learning_stats(self) -> Dict[str, Any]:
        """Get current learning statistics."""
        return {
            "cached_records": len(self.learning_cache),
            "task_types": len(
                set(record.task_type for record in self.learning_cache.values())
            ),
            "total_samples": sum(
                record.sample_count for record in self.learning_cache.values()
            ),
            "avg_success_rate": sum(
                record.success_rate for record in self.learning_cache.values()
            )
            / max(len(self.learning_cache), 1),
            "cache_ttl": self._cache_ttl,
            "last_cache_update": self._last_cache_update,
        }


# Global context optimizer instance
context_optimizer = ContextOptimizer()


# Convenience functions
async def learn_from_execution(
    task_type: str,
    context_keys: List[str],
    success: bool,
    duration_ms: float,
    metadata: Optional[Dict[str, Any]] = None,
):
    """Learn from a context execution outcome."""
    await context_optimizer.learn_from_execution(
        task_type, context_keys, success, duration_ms, metadata
    )


async def optimize_context_for_task(
    task_type: str, available_contexts: List[str], max_contexts: int = 5
) -> List[str]:
    """Return optimized context selection for a task type."""
    return await context_optimizer.optimize_context_for_task(
        task_type, available_contexts, max_contexts
    )


async def predict_context_needs(user_prompt: str) -> List[str]:
    """Predict required context types based on prompt analysis."""
    return await context_optimizer.predict_context_needs(user_prompt)


async def get_context_effectiveness_analysis(days: int = 30) -> Dict[str, Any]:
    """Get analysis of context effectiveness over time."""
    return await context_optimizer.get_context_effectiveness_analysis(days)


def get_learning_stats() -> Dict[str, Any]:
    """Get current learning statistics."""
    return context_optimizer.get_learning_stats()
