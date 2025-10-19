"""
Analytics Dashboard Queries

Provides comprehensive analytics and monitoring queries for the debug pipeline.
Enables visualization of workflow performance, error patterns, cost analysis,
and transformation function effectiveness.
"""

from datetime import datetime, timedelta
from typing import Any, Dict

from .db import get_pg_pool


class DebugAnalytics:
    """Analytics engine for debug pipeline data."""

    def __init__(self):
        self.pool = None

    async def _get_pool(self):
        """Get database pool."""
        if self.pool is None:
            self.pool = await get_pg_pool()
        return self.pool

    async def get_workflow_performance_summary(self, days: int = 7) -> Dict[str, Any]:
        """
        Get workflow performance summary for the last N days.

        Args:
            days: Number of days to analyze

        Returns:
            Performance summary with metrics
        """
        pool = await self._get_pool()
        if pool is None:
            return {}

        since_date = datetime.now() - timedelta(days=days)

        async with pool.acquire() as conn:
            # Get workflow steps summary
            steps_summary = await conn.fetchrow(
                """
                SELECT
                    COUNT(*) as total_steps,
                    COUNT(CASE WHEN success = true THEN 1 END) as successful_steps,
                    COUNT(CASE WHEN success = false THEN 1 END) as failed_steps,
                    AVG(duration_ms) as avg_duration_ms,
                    MAX(duration_ms) as max_duration_ms,
                    MIN(duration_ms) as min_duration_ms
                FROM workflow_steps
                WHERE started_at >= $1
                """,
                since_date,
            )

            # Get phase breakdown
            phase_breakdown = await conn.fetch(
                """
                SELECT
                    phase,
                    COUNT(*) as step_count,
                    COUNT(CASE WHEN success = true THEN 1 END) as success_count,
                    AVG(duration_ms) as avg_duration_ms
                FROM workflow_steps
                WHERE started_at >= $1
                GROUP BY phase
                ORDER BY step_count DESC
                """,
                since_date,
            )

            # Get error events summary
            error_summary = await conn.fetchrow(
                """
                SELECT
                    COUNT(*) as total_errors,
                    COUNT(DISTINCT run_id) as runs_with_errors,
                    COUNT(CASE WHEN error_type = 'EXECUTION_ERROR' THEN 1 END) as execution_errors,
                    COUNT(CASE WHEN error_type = 'VALIDATION_ERROR' THEN 1 END) as validation_errors,
                    COUNT(CASE WHEN error_type = 'TIMEOUT_ERROR' THEN 1 END) as timeout_errors,
                    COUNT(CASE WHEN error_type = 'QUORUM_ERROR' THEN 1 END) as quorum_errors
                FROM error_events
                WHERE created_at >= $1
                """,
                since_date,
            )

            # Get success events summary
            success_summary = await conn.fetchrow(
                """
                SELECT
                    COUNT(*) as total_successes,
                    COUNT(CASE WHEN is_golden = true THEN 1 END) as golden_states,
                    COUNT(DISTINCT run_id) as successful_runs
                FROM success_events
                WHERE created_at >= $1
                """,
                since_date,
            )

            return {
                "period_days": days,
                "since_date": since_date.isoformat(),
                "workflow_steps": dict(steps_summary) if steps_summary else {},
                "phase_breakdown": [dict(row) for row in phase_breakdown],
                "error_summary": dict(error_summary) if error_summary else {},
                "success_summary": dict(success_summary) if success_summary else {},
            }

    async def get_cost_analysis(self, days: int = 7) -> Dict[str, Any]:
        """
        Get cost analysis for LLM calls.

        Args:
            days: Number of days to analyze

        Returns:
            Cost analysis with breakdowns
        """
        pool = await self._get_pool()
        if pool is None:
            return {}

        since_date = datetime.now() - timedelta(days=days)

        async with pool.acquire() as conn:
            # Get total cost summary
            cost_summary = await conn.fetchrow(
                """
                SELECT
                    COUNT(*) as total_calls,
                    SUM(computed_cost_usd) as total_cost_usd,
                    AVG(computed_cost_usd) as avg_cost_per_call,
                    SUM(input_tokens) as total_input_tokens,
                    SUM(output_tokens) as total_output_tokens
                FROM llm_calls
                WHERE created_at >= $1
                """,
                since_date,
            )

            # Get cost by model
            cost_by_model = await conn.fetch(
                """
                SELECT
                    model,
                    provider,
                    COUNT(*) as call_count,
                    SUM(computed_cost_usd) as total_cost_usd,
                    AVG(computed_cost_usd) as avg_cost_per_call,
                    SUM(input_tokens) as total_input_tokens,
                    SUM(output_tokens) as total_output_tokens
                FROM llm_calls
                WHERE created_at >= $1
                GROUP BY model, provider
                ORDER BY total_cost_usd DESC
                """,
                since_date,
            )

            # Get cost by run
            cost_by_run = await conn.fetch(
                """
                SELECT
                    run_id,
                    COUNT(*) as call_count,
                    SUM(computed_cost_usd) as total_cost_usd,
                    AVG(computed_cost_usd) as avg_cost_per_call
                FROM llm_calls
                WHERE created_at >= $1
                GROUP BY run_id
                ORDER BY total_cost_usd DESC
                LIMIT 10
                """,
                since_date,
            )

            return {
                "period_days": days,
                "since_date": since_date.isoformat(),
                "cost_summary": dict(cost_summary) if cost_summary else {},
                "cost_by_model": [dict(row) for row in cost_by_model],
                "cost_by_run": [dict(row) for row in cost_by_run],
            }

    async def get_error_pattern_analysis(self, days: int = 7) -> Dict[str, Any]:
        """
        Analyze error patterns and correlations.

        Args:
            days: Number of days to analyze

        Returns:
            Error pattern analysis
        """
        pool = await self._get_pool()
        if pool is None:
            return {}

        since_date = datetime.now() - timedelta(days=days)

        async with pool.acquire() as conn:
            # Get error frequency by type
            error_frequency = await conn.fetch(
                """
                SELECT
                    error_type,
                    COUNT(*) as error_count,
                    COUNT(DISTINCT run_id) as affected_runs
                FROM error_events
                WHERE created_at >= $1
                GROUP BY error_type
                ORDER BY error_count DESC
                """,
                since_date,
            )

            # Get error-success correlations
            error_success_correlations = await conn.fetch(
                """
                SELECT
                    e.error_type,
                    COUNT(*) as correlation_count,
                    AVG(esm.n_success::numeric / NULLIF(esm.n_trials, 0)) as avg_success_rate,
                    COUNT(CASE WHEN esm.n_success > 0 THEN 1 END) as successful_correlations
                FROM error_events e
                JOIN error_success_maps esm ON e.id = esm.error_id
                WHERE e.created_at >= $1
                GROUP BY e.error_type
                ORDER BY correlation_count DESC
                """,
                since_date,
            )

            # Get most problematic runs
            problematic_runs = await conn.fetch(
                """
                SELECT
                    run_id,
                    COUNT(*) as error_count,
                    COUNT(DISTINCT error_type) as error_type_count,
                    MIN(created_at) as first_error,
                    MAX(created_at) as last_error
                FROM error_events
                WHERE created_at >= $1
                GROUP BY run_id
                HAVING COUNT(*) > 1
                ORDER BY error_count DESC
                LIMIT 10
                """,
                since_date,
            )

            return {
                "period_days": days,
                "since_date": since_date.isoformat(),
                "error_frequency": [dict(row) for row in error_frequency],
                "error_success_correlations": [
                    dict(row) for row in error_success_correlations
                ],
                "problematic_runs": [dict(row) for row in problematic_runs],
            }

    async def get_stf_effectiveness_analysis(self, days: int = 7) -> Dict[str, Any]:
        """
        Analyze STF effectiveness and usage patterns.

        Args:
            days: Number of days to analyze

        Returns:
            STF effectiveness analysis
        """
        pool = await self._get_pool()
        if pool is None:
            return {}

        since_date = datetime.now() - timedelta(days=days)

        async with pool.acquire() as conn:
            # Get STF usage summary
            stf_usage = await conn.fetch(
                """
                SELECT
                    dtf.name,
                    dtf.version,
                    COUNT(ws.id) as execution_count,
                    COUNT(CASE WHEN ws.success = true THEN 1 END) as successful_executions,
                    AVG(ws.duration_ms) as avg_duration_ms
                FROM debug_transform_functions dtf
                LEFT JOIN workflow_steps ws ON dtf.id = ws.applied_tf_id
                WHERE ws.started_at >= $1 OR ws.started_at IS NULL
                GROUP BY dtf.id, dtf.name, dtf.version
                ORDER BY execution_count DESC
                """,
                since_date,
            )

            # Get STF success rates
            stf_success_rates = await conn.fetch(
                """
                SELECT
                    dtf.name,
                    dtf.version,
                    COUNT(*) as total_executions,
                    COUNT(CASE WHEN ws.success = true THEN 1 END) as successful_executions,
                    ROUND(
                        COUNT(CASE WHEN ws.success = true THEN 1 END)::numeric / COUNT(*)::numeric * 100, 2
                    ) as success_rate_percent
                FROM debug_transform_functions dtf
                JOIN workflow_steps ws ON dtf.id = ws.applied_tf_id
                WHERE ws.started_at >= $1
                GROUP BY dtf.id, dtf.name, dtf.version
                HAVING COUNT(*) > 0
                ORDER BY success_rate_percent DESC
                """,
                since_date,
            )

            # Get reward events summary
            reward_summary = await conn.fetchrow(
                """
                SELECT
                    COUNT(*) as total_rewards,
                    SUM(reward_usd) as total_reward_usd,
                    AVG(reward_usd) as avg_reward_usd,
                    COUNT(DISTINCT tf_id) as unique_stfs_rewarded
                FROM reward_events
                WHERE created_at >= $1
                """,
                since_date,
            )

            return {
                "period_days": days,
                "since_date": since_date.isoformat(),
                "stf_usage": [dict(row) for row in stf_usage],
                "stf_success_rates": [dict(row) for row in stf_success_rates],
                "reward_summary": dict(reward_summary) if reward_summary else {},
            }

    async def get_lineage_analysis(self, days: int = 7) -> Dict[str, Any]:
        """
        Analyze lineage relationships and dependencies.

        Args:
            days: Number of days to analyze

        Returns:
            Lineage analysis
        """
        pool = await self._get_pool()
        if pool is None:
            return {}

        since_date = datetime.now() - timedelta(days=days)

        async with pool.acquire() as conn:
            # Get lineage edge summary
            lineage_summary = await conn.fetchrow(
                """
                SELECT
                    COUNT(*) as total_edges,
                    COUNT(DISTINCT src_type) as source_types,
                    COUNT(DISTINCT dst_type) as target_types,
                    COUNT(DISTINCT edge_type) as edge_types
                FROM lineage_edges
                WHERE created_at >= $1
                """,
                since_date,
            )

            # Get edge type breakdown
            edge_type_breakdown = await conn.fetch(
                """
                SELECT
                    edge_type,
                    COUNT(*) as edge_count,
                    COUNT(DISTINCT src_type) as source_type_count,
                    COUNT(DISTINCT dst_type) as target_type_count
                FROM lineage_edges
                WHERE created_at >= $1
                GROUP BY edge_type
                ORDER BY edge_count DESC
                """,
                since_date,
            )

            # Get most connected entities
            connected_entities = await conn.fetch(
                """
                SELECT
                    src_type,
                    src_id,
                    COUNT(*) as connection_count
                FROM lineage_edges
                WHERE created_at >= $1
                GROUP BY src_type, src_id
                ORDER BY connection_count DESC
                LIMIT 10
                """,
                since_date,
            )

            return {
                "period_days": days,
                "since_date": since_date.isoformat(),
                "lineage_summary": dict(lineage_summary) if lineage_summary else {},
                "edge_type_breakdown": [dict(row) for row in edge_type_breakdown],
                "connected_entities": [dict(row) for row in connected_entities],
            }


# Global analytics instance
analytics = DebugAnalytics()


async def get_dashboard_data(days: int = 7) -> Dict[str, Any]:
    """
    Get comprehensive dashboard data for the debug pipeline.

    Args:
        days: Number of days to analyze

    Returns:
        Complete dashboard data
    """
    return {
        "performance": await analytics.get_workflow_performance_summary(days),
        "costs": await analytics.get_cost_analysis(days),
        "errors": await analytics.get_error_pattern_analysis(days),
        "stf_effectiveness": await analytics.get_stf_effectiveness_analysis(days),
        "lineage": await analytics.get_lineage_analysis(days),
        "generated_at": datetime.now().isoformat(),
    }
