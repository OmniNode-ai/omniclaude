"""
Agent Performance Analytics System

Tracks and optimizes agent selection based on historical performance.
Provides insights into agent effectiveness, success rates, and optimization opportunities.
"""

import asyncio
import json
import uuid
from datetime import datetime, timedelta
from typing import Any

from .db import get_pg_pool


class AgentAnalytics:
    """Analytics system for tracking and optimizing agent performance."""

    def __init__(self):
        self._performance_cache: dict[str, dict[str, Any]] = {}
        self._cache_ttl = 300  # 5 minutes
        self._last_cache_update: datetime | None = None

    async def track_agent_performance(
        self,
        agent_id: str,
        task_type: str,
        success: bool,
        duration_ms: int,
        run_id: str,
        metadata: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> str:
        """
        Tracks agent performance for a specific task.

        Args:
            agent_id: Identifier for the agent
            task_type: Type of task performed
            success: Whether the task was successful
            duration_ms: Duration in milliseconds
            run_id: Workflow run identifier
            metadata: Additional performance metadata
            correlation_id: Correlation identifier

        Returns:
            Performance tracking ID
        """
        pool = await get_pg_pool()
        if pool is None:
            return "no-tracking-id"

        performance_id = str(uuid.uuid4())

        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO agent_performance (
                        id, agent_id, task_type, success, duration_ms, run_id,
                        correlation_id, metadata, created_at
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8::jsonb, NOW()
                    )
                    """,
                    performance_id,
                    agent_id,
                    task_type,
                    success,
                    duration_ms,
                    run_id,
                    correlation_id,
                    json.dumps(metadata or {}, default=str),
                )

            # Invalidate cache
            self._invalidate_cache()
            return performance_id
        except Exception as e:
            # Handle database errors gracefully (e.g., table doesn't exist in test env)
            print(f"Warning: Failed to track agent performance: {e}")
            return "no-tracking-id"

    async def get_agent_performance_summary(
        self,
        agent_id: str | None = None,
        task_type: str | None = None,
        days: int = 30,
    ) -> dict[str, Any]:
        """
        Gets performance summary for agents.

        Args:
            agent_id: Specific agent to analyze (None for all)
            task_type: Specific task type to analyze (None for all)
            days: Number of days to look back

        Returns:
            Performance summary data
        """
        # Check cache first
        cache_key = f"{agent_id or 'all'}_{task_type or 'all'}_{days}"
        if self._is_cache_valid() and cache_key in self._performance_cache:
            return self._performance_cache[cache_key]

        pool = await get_pg_pool()
        if pool is None:
            return {}

        try:
            since_date = datetime.now() - timedelta(days=days)

            async with pool.acquire() as conn:
                # Build query conditions
                where_conditions = ["created_at >= $1"]
                params: list[Any] = [since_date]
                param_count = 1

                if agent_id:
                    param_count += 1
                    where_conditions.append(f"agent_id = ${param_count}")
                    params.append(agent_id)

                if task_type:
                    param_count += 1
                    where_conditions.append(f"task_type = ${param_count}")
                    params.append(task_type)

                # Get overall performance metrics
                # where_conditions built from controlled parameterized clauses, values passed via *params
                overall_metrics = await conn.fetchrow(
                    f"""
                SELECT
                    COUNT(*) as total_tasks,
                    COUNT(CASE WHEN success = TRUE THEN 1 END) as successful_tasks,
                    AVG(duration_ms) as avg_duration_ms,
                    MIN(duration_ms) as min_duration_ms,
                    MAX(duration_ms) as max_duration_ms,
                    STDDEV(duration_ms) as duration_stddev
                FROM agent_performance
                WHERE {' AND '.join(where_conditions)}
                """,  # nosec B608
                    *params,
                )

            # Get performance by agent
            # where_conditions built from controlled parameterized clauses, values passed via *params
            agent_metrics = await conn.fetch(
                f"""
                SELECT
                    agent_id,
                    COUNT(*) as total_tasks,
                    COUNT(CASE WHEN success = TRUE THEN 1 END) as successful_tasks,
                    AVG(duration_ms) as avg_duration_ms,
                    (COUNT(CASE WHEN success = TRUE THEN 1 END)::numeric * 100) / NULLIF(COUNT(*), 0) as success_rate_percent
                FROM agent_performance
                WHERE {' AND '.join(where_conditions)}
                GROUP BY agent_id
                ORDER BY success_rate_percent DESC, avg_duration_ms ASC
                """,  # nosec B608
                *params,
            )

            # Get performance by task type
            # where_conditions built from controlled parameterized clauses, values passed via *params
            task_metrics = await conn.fetch(
                f"""
                SELECT
                    task_type,
                    COUNT(*) as total_tasks,
                    COUNT(CASE WHEN success = TRUE THEN 1 END) as successful_tasks,
                    AVG(duration_ms) as avg_duration_ms,
                    (COUNT(CASE WHEN success = TRUE THEN 1 END)::numeric * 100) / NULLIF(COUNT(*), 0) as success_rate_percent
                FROM agent_performance
                WHERE {' AND '.join(where_conditions)}
                GROUP BY task_type
                ORDER BY success_rate_percent DESC, avg_duration_ms ASC
                """,  # nosec B608
                *params,
            )

            # Get top performing agents for each task type
            # where_conditions built from controlled parameterized clauses, values passed via *params
            top_agents_by_task = await conn.fetch(
                f"""
                WITH task_agent_performance AS (
                    SELECT
                        task_type,
                        agent_id,
                        COUNT(*) as total_tasks,
                        COUNT(CASE WHEN success = TRUE THEN 1 END) as successful_tasks,
                        AVG(duration_ms) as avg_duration_ms,
                        (COUNT(CASE WHEN success = TRUE THEN 1 END)::numeric * 100) / NULLIF(COUNT(*), 0) as success_rate_percent
                    FROM agent_performance
                    WHERE {' AND '.join(where_conditions)}
                    GROUP BY task_type, agent_id
                    HAVING COUNT(*) >= 3  -- Minimum tasks for statistical significance
                ),
                ranked_agents AS (
                    SELECT
                        task_type,
                        agent_id,
                        total_tasks,
                        successful_tasks,
                        avg_duration_ms,
                        success_rate_percent,
                        ROW_NUMBER() OVER (PARTITION BY task_type ORDER BY success_rate_percent DESC, avg_duration_ms ASC) as rank
                    FROM task_agent_performance
                )
                SELECT
                    task_type,
                    agent_id,
                    total_tasks,
                    successful_tasks,
                    avg_duration_ms,
                    success_rate_percent
                FROM ranked_agents
                WHERE rank <= 3
                ORDER BY task_type, rank
                """,  # nosec B608
                *params,
            )

            result = {
                "period_days": days,
                "since_date": since_date.isoformat(),
                "overall_metrics": dict(overall_metrics) if overall_metrics else {},
                "agent_metrics": [dict(row) for row in agent_metrics],
                "task_metrics": [dict(row) for row in task_metrics],
                "top_agents_by_task": [dict(row) for row in top_agents_by_task],
            }

            # Cache the result
            self._performance_cache[cache_key] = result
            self._last_cache_update = datetime.now()

            return result
        except Exception as e:
            # Handle database errors gracefully
            print(f"Warning: Failed to get agent performance summary: {e}")
            return {
                "overall_metrics": {},
                "agent_metrics": [],
                "task_metrics": [],
            }

    async def get_agent_recommendations(
        self,
        task_type: str,
        context: dict[str, Any] | None = None,
        limit: int = 3,
        days: int = 30,
    ) -> list[dict[str, Any]]:
        """
        Gets agent recommendations for a specific task type.

        Args:
            task_type: Type of task to get recommendations for
            context: Optional context for more specific recommendations
            limit: Maximum number of recommendations
            days: Number of days to look back for performance data

        Returns:
            List of recommended agents with performance metrics
        """
        pool = await get_pg_pool()
        if pool is None:
            return []

        try:
            since_date = datetime.now() - timedelta(days=days)

            async with pool.acquire() as conn:
                # Get agent performance for this task type
                agent_performance = await conn.fetch(
                    """
                SELECT
                    agent_id,
                    COUNT(*) as total_tasks,
                    COUNT(CASE WHEN success = TRUE THEN 1 END) as successful_tasks,
                    AVG(duration_ms) as avg_duration_ms,
                    (COUNT(CASE WHEN success = TRUE THEN 1 END)::numeric * 100) / NULLIF(COUNT(*), 0) as success_rate_percent,
                    STDDEV(duration_ms) as duration_stddev
                FROM agent_performance
                WHERE task_type = $1 AND created_at >= $2
                GROUP BY agent_id
                HAVING COUNT(*) >= 2  -- Minimum tasks for reliability
                ORDER BY success_rate_percent DESC, avg_duration_ms ASC
                LIMIT $3
                """,
                    task_type,
                    since_date,
                    limit,
                )

                recommendations = []
                for row in agent_performance:
                    # Calculate confidence score based on success rate and consistency
                    # Use explicit None checks to preserve zero values
                    success_rate = (
                        row["success_rate_percent"]
                        if row["success_rate_percent"] is not None
                        else 0
                    )

                    # Handle duration consistency calculation safely
                    duration_stddev = (
                        row["duration_stddev"]
                        if row["duration_stddev"] is not None
                        else 0
                    )
                    avg_duration = (
                        row["avg_duration_ms"]
                        if row["avg_duration_ms"] is not None
                        else 1
                    )
                    # Avoid division by zero: use 1ms minimum for avg_duration
                    avg_duration = max(avg_duration, 1)
                    duration_consistency = 1.0 - duration_stddev / avg_duration
                    confidence_score = (
                        success_rate / 100.0
                    ) * 0.7 + duration_consistency * 0.3

                    recommendations.append(
                        {
                            "agent_id": row["agent_id"],
                            "task_type": task_type,
                            "total_tasks": row["total_tasks"],
                            "successful_tasks": row["successful_tasks"],
                            "success_rate_percent": success_rate,
                            "avg_duration_ms": row["avg_duration_ms"],
                            "duration_stddev": row["duration_stddev"],
                            "confidence_score": confidence_score,
                            "recommendation_reason": self._get_recommendation_reason(
                                success_rate, row["avg_duration_ms"]
                            ),
                        }
                    )

                return recommendations
        except Exception as e:
            # Handle database errors gracefully
            print(f"Warning: Failed to get agent recommendations: {e}")
            return []

    def _get_recommendation_reason(
        self, success_rate: float, avg_duration: float
    ) -> str:
        """Generates a human-readable reason for the recommendation."""
        if success_rate >= 90:
            if avg_duration < 1000:  # Less than 1 second
                return "High success rate with fast execution"
            else:
                return "High success rate with reliable execution"
        elif success_rate >= 75:
            return "Good success rate with acceptable performance"
        else:
            return "Moderate success rate, consider alternatives"

    async def get_performance_trends(
        self,
        agent_id: str | None = None,
        task_type: str | None = None,
        days: int = 30,
        interval_hours: int = 24,
    ) -> dict[str, Any]:
        """
        Gets performance trends over time.

        Args:
            agent_id: Specific agent to analyze (None for all)
            task_type: Specific task type to analyze (None for all)
            days: Number of days to look back
            interval_hours: Time interval for trend analysis

        Returns:
            Performance trends data
        """
        pool = await get_pg_pool()
        if pool is None:
            return {}

        try:
            since_date = datetime.now() - timedelta(days=days)

            async with pool.acquire() as conn:
                # Build query conditions
                where_conditions = ["created_at >= $1"]
                params: list[Any] = [since_date]
                param_count = 1

                if agent_id:
                    param_count += 1
                    where_conditions.append(f"agent_id = ${param_count}")
                    params.append(agent_id)

                if task_type:
                    param_count += 1
                    where_conditions.append(f"task_type = ${param_count}")
                    params.append(task_type)

                # Get performance trends by time interval
                # where_conditions built from controlled parameterized clauses, values passed via *params
                trends = await conn.fetch(
                    f"""
                    SELECT
                        DATE_TRUNC('hour', created_at) as time_bucket,
                        COUNT(*) as total_tasks,
                        COUNT(CASE WHEN success = TRUE THEN 1 END) as successful_tasks,
                        AVG(duration_ms) as avg_duration_ms,
                        (COUNT(CASE WHEN success = TRUE THEN 1 END)::numeric * 100) / NULLIF(COUNT(*), 0) as success_rate_percent
                    FROM agent_performance
                    WHERE {' AND '.join(where_conditions)}
                    GROUP BY DATE_TRUNC('hour', created_at)
                    ORDER BY time_bucket
                    """,  # nosec B608
                    *params,
                )

                # Calculate trend metrics
                if trends:
                    first_half = trends[: len(trends) // 2]
                    second_half = trends[len(trends) // 2 :]

                    # Use explicit None checks to preserve zero values
                    first_avg_success = (
                        sum(
                            (
                                row["success_rate_percent"]
                                if row["success_rate_percent"] is not None
                                else 0
                            )
                            for row in first_half
                        )
                        / len(first_half)
                        if first_half
                        else 0
                    )
                    second_avg_success = (
                        sum(
                            (
                                row["success_rate_percent"]
                                if row["success_rate_percent"] is not None
                                else 0
                            )
                            for row in second_half
                        )
                        / len(second_half)
                        if second_half
                        else 0
                    )

                    first_avg_duration = (
                        sum(
                            (
                                row["avg_duration_ms"]
                                if row["avg_duration_ms"] is not None
                                else 0
                            )
                            for row in first_half
                        )
                        / len(first_half)
                        if first_half
                        else 0
                    )
                    second_avg_duration = (
                        sum(
                            (
                                row["avg_duration_ms"]
                                if row["avg_duration_ms"] is not None
                                else 0
                            )
                            for row in second_half
                        )
                        / len(second_half)
                        if second_half
                        else 0
                    )

                    success_trend = (
                        "improving"
                        if second_avg_success > first_avg_success
                        else (
                            "declining"
                            if second_avg_success < first_avg_success
                            else "stable"
                        )
                    )
                    duration_trend = (
                        "improving"
                        if second_avg_duration < first_avg_duration
                        else (
                            "declining"
                            if second_avg_duration > first_avg_duration
                            else "stable"
                        )
                    )
                else:
                    success_trend = "stable"
                    duration_trend = "stable"

                return {
                    "period_days": days,
                    "interval_hours": interval_hours,
                    "since_date": since_date.isoformat(),
                    "trends": [dict(row) for row in trends],
                    "success_trend": success_trend,
                    "duration_trend": duration_trend,
                    "trend_summary": {
                        "success_rate_change": (
                            second_avg_success - first_avg_success if trends else 0
                        ),
                        "duration_change": (
                            second_avg_duration - first_avg_duration if trends else 0
                        ),
                    },
                }
        except Exception as e:
            # Handle database errors gracefully
            print(f"Warning: Failed to get performance trends: {e}")
            return {
                "period_days": days,
                "interval_hours": interval_hours,
                "trends": [],
                "success_trend": "unknown",
                "duration_trend": "unknown",
            }

    def _is_cache_valid(self) -> bool:
        """Checks if the performance cache is still valid."""
        if self._last_cache_update is None:
            return False
        return (
            datetime.now() - self._last_cache_update
        ).total_seconds() < self._cache_ttl

    def _invalidate_cache(self):
        """Invalidates the performance cache."""
        self._performance_cache.clear()
        self._last_cache_update = None


# Global instance
agent_analytics = AgentAnalytics()


async def track_agent_performance(
    agent_id: str,
    task_type: str,
    success: bool,
    duration_ms: int,
    run_id: str,
    metadata: dict[str, Any] | None = None,
    correlation_id: str | None = None,
) -> str:
    """
    Convenience function to track agent performance.
    """
    return await agent_analytics.track_agent_performance(
        agent_id=agent_id,
        task_type=task_type,
        success=success,
        duration_ms=duration_ms,
        run_id=run_id,
        metadata=metadata,
        correlation_id=correlation_id,
    )


async def get_agent_recommendations(
    task_type: str,
    context: dict[str, Any] | None = None,
    limit: int = 3,
    days: int = 30,
) -> list[dict[str, Any]]:
    """
    Convenience function to get agent recommendations.
    """
    return await agent_analytics.get_agent_recommendations(
        task_type=task_type,
        context=context,
        limit=limit,
        days=days,
    )


async def test_agent_analytics():
    """Test the agent analytics system."""
    print("Testing agent analytics system...")

    # Test tracking performance
    test_run_id = str(uuid.uuid4())
    test_correlation_id = str(uuid.uuid4())

    # Track some sample performance data
    await track_agent_performance(
        agent_id="test-agent-1",
        task_type="code_generation",
        success=True,
        duration_ms=1500,
        run_id=test_run_id,
        metadata={"complexity": "high", "language": "python"},
        correlation_id=test_correlation_id,
    )

    await track_agent_performance(
        agent_id="test-agent-2",
        task_type="code_generation",
        success=True,
        duration_ms=800,
        run_id=test_run_id,
        metadata={"complexity": "medium", "language": "python"},
        correlation_id=test_correlation_id,
    )

    await track_agent_performance(
        agent_id="test-agent-1",
        task_type="code_review",
        success=False,
        duration_ms=2000,
        run_id=test_run_id,
        metadata={"complexity": "high", "language": "python"},
        correlation_id=test_correlation_id,
    )

    # Test getting recommendations
    recommendations = await get_agent_recommendations(
        task_type="code_generation",
        context={"complexity": "high"},
        limit=2,
    )

    print(f"✓ Found {len(recommendations)} agent recommendations")
    for rec in recommendations:
        print(
            f"  - {rec['agent_id']}: {rec['success_rate_percent']:.1f}% success, {rec['avg_duration_ms']:.0f}ms avg"
        )

    # Test performance summary
    summary = await agent_analytics.get_agent_performance_summary(days=1)
    print(f"✓ Performance summary: {summary.get('overall_metrics', {})}")

    # Test trends
    trends = await agent_analytics.get_performance_trends(days=1)
    print(
        f"✓ Performance trends: {trends.get('success_trend', 'unknown')} success, {trends.get('duration_trend', 'unknown')} duration"
    )


if __name__ == "__main__":
    asyncio.run(test_agent_analytics())
