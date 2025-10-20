#!/usr/bin/env python3
"""
System Dashboard - Markdown Banner Generator
Auto-generates markdown dashboard from database metrics
"""

import os
from datetime import datetime
from typing import Any, Dict, List

import psycopg2
from psycopg2.extras import RealDictCursor


class SystemDashboard:
    """Generate markdown dashboard from system metrics"""

    def __init__(
        self,
        db_password: str = None,
        output_file: str = "SYSTEM_DASHBOARD.md",
    ):
        password = db_password or os.getenv(
            "OMNINODE_BRIDGE_PASSWORD", "omninode-bridge-postgres-dev-2024"
        )
        self.conn_string = (
            f"host=localhost port=5436 dbname=omninode_bridge "
            f"user=postgres password={password}"
        )
        self.output_file = output_file

    def get_connection(self):
        """Get database connection with dictionary cursor"""
        return psycopg2.connect(self.conn_string, cursor_factory=RealDictCursor)

    def get_system_health(self) -> Dict[str, Any]:
        """Get overall system health metrics"""
        query = """
        WITH routing_stats AS (
            SELECT
                COUNT(*) as total_decisions,
                AVG(confidence_score) as avg_confidence,
                AVG(routing_time_ms) as avg_routing_ms,
                MIN(created_at) as first_decision,
                MAX(created_at) as last_decision
            FROM agent_routing_decisions
            WHERE created_at > NOW() - INTERVAL '24 hours'
        ),
        exec_stats AS (
            SELECT
                COUNT(*) as total_executions,
                0 as successful_executions
            FROM agent_execution_logs
            WHERE started_at > NOW() - INTERVAL '24 hours'
        ),
        hook_stats AS (
            SELECT
                COUNT(*) as total_events,
                COUNT(*) FILTER (WHERE processed = true) as processed_events,
                COUNT(*) FILTER (WHERE processed = false) as pending_events
            FROM hook_events
            WHERE created_at > NOW() - INTERVAL '24 hours'
        ),
        cache_stats AS (
            SELECT
                COUNT(*) as total_queries,
                COUNT(*) FILTER (WHERE cache_hit = true) as cache_hits,
                ROUND(100.0 * COUNT(*) FILTER (WHERE cache_hit = true) / NULLIF(COUNT(*), 0), 2) as hit_rate
            FROM router_performance_metrics
            WHERE created_at > NOW() - INTERVAL '24 hours'
        )
        SELECT
            r.*,
            e.*,
            h.*,
            c.*
        FROM routing_stats r, exec_stats e, hook_stats h, cache_stats c
        """

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                return dict(cur.fetchone()) if cur.rowcount > 0 else {}

    def get_top_agents(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Get top selected agents"""
        query = """
        SELECT
            selected_agent,
            COUNT(*) as selections,
            ROUND(AVG(confidence_score) * 100, 2) as avg_confidence,
            ROUND(AVG(routing_time_ms), 0) as avg_routing_ms
        FROM agent_routing_decisions
        WHERE created_at > NOW() - INTERVAL '24 hours'
        GROUP BY selected_agent
        ORDER BY selections DESC
        LIMIT %s
        """

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (limit,))
                return [dict(row) for row in cur.fetchall()]

    def get_recent_errors(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Get recent failed detections or errors"""
        query = """
        SELECT
            created_at,
            source,
            action,
            payload->>'error' as error_msg,
            metadata->>'correlation_id' as correlation_id
        FROM hook_events
        WHERE payload->>'error' IS NOT NULL
          AND created_at > NOW() - INTERVAL '24 hours'
        ORDER BY created_at DESC
        LIMIT %s
        """

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (limit,))
                return [dict(row) for row in cur.fetchall()]

    def get_recent_routing_decisions(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent routing decisions with timestamps"""
        query = """
        SELECT
            created_at,
            selected_agent,
            confidence_score,
            routing_time_ms,
            routing_strategy,
            LEFT(user_request, 80) as request_preview
        FROM agent_routing_decisions
        ORDER BY created_at DESC
        LIMIT %s
        """

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (limit,))
                return [dict(row) for row in cur.fetchall()]

    def get_recent_hook_events(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent hook events"""
        query = """
        SELECT
            created_at,
            source,
            action,
            resource_id,
            processed
        FROM hook_events
        ORDER BY created_at DESC
        LIMIT %s
        """

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (limit,))
                return [dict(row) for row in cur.fetchall()]

    def get_agent_statistics(self) -> List[Dict[str, Any]]:
        """Get detailed agent statistics"""
        query = """
        SELECT
            selected_agent,
            COUNT(*) as total_selections,
            COUNT(*) FILTER (WHERE confidence_score >= 0.95) as excellent_count,
            COUNT(*) FILTER (WHERE confidence_score >= 0.85 AND confidence_score < 0.95) as good_count,
            COUNT(*) FILTER (WHERE confidence_score < 0.85) as poor_count,
            ROUND(AVG(confidence_score) * 100, 2) as avg_confidence,
            ROUND(MIN(confidence_score) * 100, 2) as min_confidence,
            ROUND(MAX(confidence_score) * 100, 2) as max_confidence,
            ROUND(AVG(routing_time_ms), 0) as avg_routing_ms,
            MIN(routing_time_ms) as min_routing_ms,
            MAX(routing_time_ms) as max_routing_ms
        FROM agent_routing_decisions
        WHERE created_at > NOW() - INTERVAL '24 hours'
        GROUP BY selected_agent
        ORDER BY total_selections DESC
        """

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                return [dict(row) for row in cur.fetchall()]

    def get_system_issues(self) -> List[Dict[str, Any]]:
        """Get list of system issues and problems"""
        issues = []

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                # Check for unprocessed hook events
                cur.execute(
                    """
                    SELECT COUNT(*) as count, MIN(created_at) as oldest
                    FROM hook_events
                    WHERE processed = false
                """
                )
                row = cur.fetchone()
                if row and row["count"] > 0:
                    age_hours = (
                        datetime.utcnow() - row["oldest"].replace(tzinfo=None)
                    ).total_seconds() / 3600
                    issues.append(
                        {
                            "severity": "critical" if row["count"] > 100 else "warning",
                            "category": "Hook Processing",
                            "issue": f"{row['count']} unprocessed hook events",
                            "details": f"Oldest event: {age_hours:.1f}h ago",
                            "impact": "Event-driven workflows not executing",
                        }
                    )

                # Check for low confidence detections
                cur.execute(
                    """
                    SELECT COUNT(*) as count
                    FROM agent_routing_decisions
                    WHERE confidence_score < 0.85
                      AND created_at > NOW() - INTERVAL '24 hours'
                """
                )
                row = cur.fetchone()
                if row and row["count"] > 0:
                    issues.append(
                        {
                            "severity": "warning",
                            "category": "Agent Detection",
                            "issue": f"{row['count']} low-confidence routing decisions",
                            "details": "Confidence <85%",
                            "impact": "May be routing to wrong agents",
                        }
                    )

                # Check for slow routing (using corrected threshold)
                # Note: After P2 migration, routing times >500ms moved to task_completion_metrics
                cur.execute(
                    """
                    SELECT COUNT(*) as count, MAX(routing_time_ms) as max_ms
                    FROM agent_routing_decisions
                    WHERE routing_time_ms > 200  -- Updated threshold for actual routing performance
                      AND created_at > NOW() - INTERVAL '24 hours'
                """
                )
                row = cur.fetchone()
                if row and row["count"] > 0:
                    issues.append(
                        {
                            "severity": "warning",
                            "category": "Performance",
                            "issue": f"{row['count']} slow routing decisions",
                            "details": f"Max: {row['max_ms']}ms (threshold: 200ms, target: <100ms)",
                            "impact": "Slower than target routing performance",
                        }
                    )

                # Check cache hit rate
                cur.execute(
                    """
                    SELECT
                        COUNT(*) as total,
                        COUNT(*) FILTER (WHERE cache_hit = true) as hits
                    FROM router_performance_metrics
                    WHERE created_at > NOW() - INTERVAL '24 hours'
                """
                )
                row = cur.fetchone()
                if row and row["total"] > 0:
                    hit_rate = 100.0 * row["hits"] / row["total"]
                    if hit_rate < 30:
                        issues.append(
                            {
                                "severity": "critical" if hit_rate == 0 else "warning",
                                "category": "Cache System",
                                "issue": f"Cache hit rate: {hit_rate:.1f}%",
                                "details": f"{row['hits']}/{row['total']} queries cached",
                                "impact": "Wasted computation, slower routing",
                            }
                        )

                # Check for detection failures (if table exists)
                try:
                    cur.execute(
                        """
                        SELECT COUNT(*) as count
                        FROM agent_detection_failures
                        WHERE reviewed = false
                          AND created_at > NOW() - INTERVAL '24 hours'
                    """
                    )
                    row = cur.fetchone()
                    if row and row["count"] > 0:
                        issues.append(
                            {
                                "severity": "info",
                                "category": "Detection Quality",
                                "issue": f"{row['count']} unreviewed detection failures",
                                "details": "Require manual review",
                                "impact": "Missed opportunities for improvement",
                            }
                        )
                except Exception:
                    pass  # Table may not exist yet

                # Check for agent execution failures
                cur.execute(
                    """
                    SELECT COUNT(*) as count
                    FROM agent_execution_logs
                    WHERE status = 'error'
                      AND started_at > NOW() - INTERVAL '24 hours'
                """
                )
                row = cur.fetchone()
                if row and row["count"] > 0:
                    issues.append(
                        {
                            "severity": "critical",
                            "category": "Agent Execution",
                            "issue": f"{row['count']} failed agent executions",
                            "details": "Check error_message column",
                            "impact": "Tasks not completing",
                        }
                    )

        return issues

    def get_detection_quality(self) -> Dict[str, Any]:
        """Get agent detection quality metrics"""
        query = """
        WITH detection_stats AS (
            SELECT
                COUNT(*) FILTER (WHERE confidence_score >= 0.95) as excellent_detections,
                COUNT(*) FILTER (WHERE confidence_score >= 0.85 AND confidence_score < 0.95) as good_detections,
                COUNT(*) FILTER (WHERE confidence_score >= 0.70 AND confidence_score < 0.85) as fair_detections,
                COUNT(*) FILTER (WHERE confidence_score < 0.70) as poor_detections,
                COUNT(*) as total_detections
            FROM agent_routing_decisions
            WHERE created_at > NOW() - INTERVAL '24 hours'
        )
        SELECT
            excellent_detections,
            good_detections,
            fair_detections,
            poor_detections,
            total_detections,
            ROUND(100.0 * excellent_detections / NULLIF(total_detections, 0), 1) as excellent_pct,
            ROUND(100.0 * (excellent_detections + good_detections) / NULLIF(total_detections, 0), 1) as acceptable_pct
        FROM detection_stats
        """

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                return dict(cur.fetchone()) if cur.rowcount > 0 else {}

    def get_task_completion_stats(self) -> Dict[str, Any]:
        """Get task completion metrics (P2: separated from routing metrics)"""
        # Check if table exists first
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_name = 'task_completion_metrics'
                    ) as table_exists
                """
                )
                result = cur.fetchone()
                table_exists = result["table_exists"] if result else False

                if not table_exists:
                    return {}

                query = """
                WITH task_stats AS (
                    SELECT
                        COUNT(*) as total_tasks,
                        COUNT(*) FILTER (WHERE success = true) as successful_tasks,
                        AVG(completion_time_ms) as avg_completion_ms,
                        MIN(completion_time_ms) as min_completion_ms,
                        MAX(completion_time_ms) as max_completion_ms,
                        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY completion_time_ms) as median_completion_ms,
                        PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY completion_time_ms) as p95_completion_ms
                    FROM task_completion_metrics
                    WHERE created_at > NOW() - INTERVAL '24 hours'
                )
                SELECT
                    total_tasks,
                    successful_tasks,
                    ROUND(avg_completion_ms::numeric, 0) as avg_completion_ms,
                    min_completion_ms,
                    max_completion_ms,
                    ROUND(median_completion_ms::numeric, 0) as median_completion_ms,
                    ROUND(p95_completion_ms::numeric, 0) as p95_completion_ms,
                    ROUND(100.0 * successful_tasks / NULLIF(total_tasks, 0), 1) as success_rate
                FROM task_stats
                """
                cur.execute(query)
                return dict(cur.fetchone()) if cur.rowcount > 0 else {}

    def get_recent_task_completions(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent task completions (P2: new table)"""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                # Check if table exists
                cur.execute(
                    """
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_name = 'task_completion_metrics'
                    ) as table_exists
                """
                )
                result = cur.fetchone()
                table_exists = result["table_exists"] if result else False

                if not table_exists:
                    return []

                query = """
                SELECT
                    created_at,
                    task_type,
                    LEFT(task_description, 80) as task_preview,
                    completion_time_ms,
                    success,
                    agent_name
                FROM task_completion_metrics
                ORDER BY created_at DESC
                LIMIT %s
                """
                cur.execute(query, (limit,))
                return [dict(row) for row in cur.fetchall()]

    def generate_health_banner(self, health: Dict[str, Any]) -> str:
        """Generate health status banner"""
        if not health:
            return "⚠️ **SYSTEM OFFLINE** - No recent activity"

        # Calculate health score (convert Decimal to float for math operations)
        avg_conf = float(health.get("avg_confidence", 0) or 0)
        routing_health = min(100, avg_conf * 100)

        total_events = int(health.get("total_events", 0) or 0)
        processed_events = int(health.get("processed_events", 0) or 0)
        hook_health = (
            100 if total_events == 0 else (100 * processed_events / total_events)
        )
        cache_health = float(health.get("hit_rate", 0) or 0)

        overall_score = routing_health * 0.5 + hook_health * 0.3 + cache_health * 0.2

        if overall_score >= 90:
            status = "✅ EXCELLENT"
            emoji = "🟢"
        elif overall_score >= 75:
            status = "✅ GOOD"
            emoji = "🟡"
        elif overall_score >= 60:
            status = "⚠️ FAIR"
            emoji = "🟠"
        else:
            status = "❌ POOR"
            emoji = "🔴"

        return f"{emoji} **{status}** (Health Score: {overall_score:.1f}/100)"

    def generate_markdown(self) -> str:
        """Generate complete markdown dashboard"""
        health = self.get_system_health()
        top_agents = self.get_top_agents()
        recent_errors = self.get_recent_errors()
        quality = self.get_detection_quality()
        task_stats = self.get_task_completion_stats()
        recent_tasks = self.get_recent_task_completions(5)

        now = datetime.utcnow()
        md = []

        # Header
        md.append("# 🎯 OmniClaude System Dashboard")
        md.append("")
        md.append(f"**Generated**: {now.strftime('%Y-%m-%d %H:%M:%S')} UTC")
        md.append("**Period**: Last 24 hours")
        md.append("")
        md.append("---")
        md.append("")

        # Health Banner
        md.append("## System Health")
        md.append("")
        md.append(self.generate_health_banner(health))
        md.append("")

        # Quick Metrics Table
        md.append("### Quick Metrics")
        md.append("")
        md.append("| Metric | Value | Status |")
        md.append("|--------|-------|--------|")

        if health:
            # Routing metrics
            routing_decisions = health.get("total_decisions", 0)
            avg_confidence = health.get("avg_confidence", 0) * 100
            avg_routing_ms = health.get("avg_routing_ms", 0)

            md.append(
                f"| Routing Decisions | **{routing_decisions}** | "
                f"{'✅' if routing_decisions > 0 else '⚠️'} |"
            )
            md.append(
                f"| Avg Confidence | **{avg_confidence:.1f}%** | "
                f"{'✅' if avg_confidence >= 85 else '⚠️' if avg_confidence >= 70 else '❌'} |"
            )
            md.append(
                f"| Avg Routing Time | **{avg_routing_ms:.0f}ms** | "
                f"{'✅' if avg_routing_ms < 100 else '⚠️' if avg_routing_ms < 500 else '❌'} |"
            )

            # Execution metrics
            total_executions = health.get("total_executions", 0)

            if total_executions > 0:
                md.append(f"| Agent Executions | **{total_executions}** | ✅ |")

            # Hook metrics
            total_events = health.get("total_events", 0)
            processed_events = health.get("processed_events", 0)
            pending_events = health.get("pending_events", 0)

            md.append(
                f"| Hook Events | **{total_events}** "
                f"({processed_events} processed, {pending_events} pending) | "
                f"{'✅' if pending_events == 0 else '⚠️' if pending_events < 100 else '❌'} |"
            )

            # Cache metrics
            cache_hit_rate = health.get("hit_rate", 0)
            md.append(
                f"| Cache Hit Rate | **{cache_hit_rate:.1f}%** | "
                f"{'✅' if cache_hit_rate >= 60 else '⚠️' if cache_hit_rate >= 30 else '❌'} |"
            )

        md.append("")

        # Detection Quality
        if quality and quality.get("total_detections", 0) > 0:
            md.append("### Detection Quality (24h)")
            md.append("")
            md.append("| Quality Level | Count | Percentage |")
            md.append("|---------------|-------|------------|")
            md.append(
                f"| Excellent (≥95%) | {quality['excellent_detections']} | "
                f"{quality['excellent_pct']:.1f}% |"
            )
            md.append(
                f"| Good (85-94%) | {quality['good_detections']} | "
                f"{100.0 * quality['good_detections'] / quality['total_detections']:.1f}% |"
            )
            md.append(
                f"| Fair (70-84%) | {quality['fair_detections']} | "
                f"{100.0 * quality['fair_detections'] / quality['total_detections']:.1f}% |"
            )
            md.append(
                f"| Poor (<70%) | {quality['poor_detections']} | "
                f"{100.0 * quality['poor_detections'] / quality['total_detections']:.1f}% |"
            )
            md.append("")
            md.append(
                f"**Acceptable Rate**: {quality['acceptable_pct']:.1f}% (≥85% confidence)"
            )
            md.append("")

        # Top Agents
        if top_agents:
            md.append("### Top Agents (24h)")
            md.append("")
            md.append("| Agent | Selections | Avg Confidence | Avg Routing |")
            md.append("|-------|------------|----------------|-------------|")

            for agent in top_agents:
                md.append(
                    f"| {agent['selected_agent']} | "
                    f"{agent['selections']} | "
                    f"{agent['avg_confidence']:.1f}% | "
                    f"{agent['avg_routing_ms']:.0f}ms |"
                )

            md.append("")

        # Task Completion Metrics (P2: New Section)
        if task_stats and task_stats.get("total_tasks", 0) > 0:
            md.append("### Task Completion Metrics (24h)")
            md.append("")
            md.append("| Metric | Value | Status |")
            md.append("|--------|-------|--------|")

            total_tasks = task_stats.get("total_tasks", 0)
            success_rate = task_stats.get("success_rate", 0)
            avg_completion = task_stats.get("avg_completion_ms", 0)
            median_completion = task_stats.get("median_completion_ms", 0)
            p95_completion = task_stats.get("p95_completion_ms", 0)

            md.append(f"| Total Tasks | **{total_tasks}** | ✅ |")
            md.append(
                f"| Success Rate | **{success_rate:.1f}%** | "
                f"{'✅' if success_rate >= 90 else '⚠️' if success_rate >= 75 else '❌'} |"
            )
            md.append(
                f"| Avg Completion | **{avg_completion:.0f}ms** | "
                f"{'✅' if avg_completion < 1000 else '⚠️' if avg_completion < 5000 else '❌'} |"
            )
            md.append(
                f"| Median Completion | **{median_completion:.0f}ms** | "
                f"{'✅' if median_completion < 1000 else '⚠️'} |"
            )
            md.append(
                f"| P95 Completion | **{p95_completion:.0f}ms** | "
                f"{'✅' if p95_completion < 5000 else '⚠️'} |"
            )

            md.append("")

            # Recent task completions
            if recent_tasks:
                md.append("### Recent Task Completions")
                md.append("")
                md.append("| Time | Type | Duration | Status | Task |")
                md.append("|------|------|----------|--------|------|")

                for task in recent_tasks:
                    timestamp = task["created_at"].strftime("%H:%M:%S")
                    task_type = task["task_type"] or "unknown"
                    duration = task["completion_time_ms"]
                    success = "✅" if task["success"] else "❌"
                    task_preview = task["task_preview"] or ""

                    md.append(
                        f"| {timestamp} | {task_type} | {duration}ms | {success} | {task_preview} |"
                    )

                md.append("")

        # Recent Errors
        if recent_errors:
            md.append("### ⚠️ Recent Errors")
            md.append("")
            for error in recent_errors:
                timestamp = error["created_at"].strftime("%H:%M:%S")
                md.append(
                    f"- **{timestamp}** [{error['source']}] {error.get('error_msg', 'Unknown error')}"
                )
            md.append("")

        # Alerts
        alerts = []

        if health:
            if health.get("pending_events", 0) > 100:
                alerts.append(
                    "🔴 **CRITICAL**: Hook event backlog >100 - processor may be down"
                )

            if health.get("hit_rate", 0) == 0:
                alerts.append(
                    "🔴 **CRITICAL**: Cache system not functioning (0% hit rate)"
                )

            if (health.get("avg_confidence", 1) * 100) < 70:
                alerts.append(
                    "🟠 **WARNING**: Low average confidence <70% - review agent definitions"
                )

            if health.get("total_decisions", 0) == 0:
                alerts.append("🟡 **INFO**: No routing activity in last 24 hours")

        if quality and quality.get("poor_detections", 0) > 0:
            poor_pct = (
                100.0 * quality["poor_detections"] / quality.get("total_detections", 1)
            )
            if poor_pct > 10:
                alerts.append(
                    f"🟠 **WARNING**: {poor_pct:.1f}% of detections have <70% confidence"
                )

        if alerts:
            md.append("### 🚨 Alerts")
            md.append("")
            for alert in alerts:
                md.append(f"- {alert}")
            md.append("")

        # Footer
        md.append("---")
        md.append("")
        md.append(
            "_Dashboard auto-generated from database metrics. "
            "Run `./claude_hooks/tools/system_dashboard_md.py` to refresh._"
        )
        md.append("")

        return "\n".join(md)

    def write_dashboard(self) -> str:
        """Generate and write dashboard to file"""
        markdown = self.generate_markdown()

        with open(self.output_file, "w") as f:
            f.write(markdown)

        return self.output_file

    def print_dashboard(self):
        """Print dashboard to console"""
        markdown = self.generate_markdown()
        print(markdown)


if __name__ == "__main__":
    import sys

    dashboard = SystemDashboard()

    if len(sys.argv) > 1 and sys.argv[1] == "--file":
        output_file = dashboard.write_dashboard()
        print(f"✅ Dashboard written to: {output_file}")
    else:
        dashboard.print_dashboard()
