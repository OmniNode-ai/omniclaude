#!/usr/bin/env python3
"""
Observability Framework Report Generator

Generates comprehensive reports on agent execution traces, routing decisions,
and framework observability metrics from the PostgreSQL database.
"""

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import psycopg2
from psycopg2.extras import RealDictCursor


class ObservabilityReporter:
    """Generate observability reports from the database."""

    def __init__(self, connection_string: Optional[str] = None):
        """Initialize reporter with database connection."""
        if connection_string is None:
            # Note: Set password via environment variable
            password = os.getenv(
                "POSTGRES_PASSWORD", "YOUR_PASSWORD"
            )  # Replace YOUR_PASSWORD
            connection_string = (
                f"host=localhost port=5436 "
                f"dbname=omninode_bridge "
                f"user=postgres "
                f"password={password}"
            )
        self.conn = psycopg2.connect(connection_string)

    def get_table_schema(self, table_name: str) -> List[Dict[str, str]]:
        """Get schema information for a table."""
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT column_name, data_type, character_maximum_length
                FROM information_schema.columns
                WHERE table_name = %s
                ORDER BY ordinal_position
            """,
                (table_name,),
            )
            return cur.fetchall()

    def get_all_tables(self) -> List[str]:
        """Get list of all tables in the database."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_type = 'BASE TABLE'
                ORDER BY table_name
            """
            )
            return [row[0] for row in cur.fetchall()]

    def get_table_row_counts(self) -> Dict[str, int]:
        """Get row counts for all tables."""
        tables = self.get_all_tables()
        counts = {}
        with self.conn.cursor() as cur:
            for table in tables:
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                counts[table] = cur.fetchone()[0]
        return counts

    def get_routing_decisions(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent routing decisions."""
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT *
                FROM agent_routing_decisions
                ORDER BY created_at DESC
                LIMIT %s
            """,
                (limit,),
            )
            return cur.fetchall()

    def get_routing_statistics(self) -> Dict[str, Any]:
        """Get routing decision statistics."""
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*) as total_decisions,
                    AVG(confidence_score) as avg_confidence,
                    MIN(confidence_score) as min_confidence,
                    MAX(confidence_score) as max_confidence,
                    AVG(routing_time_ms) as avg_routing_time_ms,
                    MAX(routing_time_ms) as max_routing_time_ms,
                    MIN(created_at) as earliest_decision,
                    MAX(created_at) as latest_decision
                FROM agent_routing_decisions
            """
            )
            return cur.fetchone()

    def get_agent_usage_stats(self) -> List[Dict[str, Any]]:
        """Get agent usage statistics."""
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    selected_agent,
                    COUNT(*) as usage_count,
                    AVG(confidence_score) as avg_confidence,
                    AVG(routing_time_ms) as avg_routing_time_ms
                FROM agent_routing_decisions
                GROUP BY selected_agent
                ORDER BY usage_count DESC
            """
            )
            return cur.fetchall()

    def get_transformation_events(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent transformation events."""
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            # First get the schema to find the timestamp column
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'agent_transformation_events'
                AND data_type LIKE '%timestamp%'
                ORDER BY ordinal_position
                LIMIT 1
            """
            )
            timestamp_col = cur.fetchone()

            if timestamp_col:
                time_col = timestamp_col["column_name"]
                cur.execute(
                    f"""
                    SELECT *
                    FROM agent_transformation_events
                    ORDER BY {time_col} DESC
                    LIMIT %s
                """,
                    (limit,),
                )
                return cur.fetchall()
            return []

    def get_hook_events(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent hook events."""
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT *
                FROM hook_events
                ORDER BY created_at DESC
                LIMIT %s
            """,
                (limit,),
            )
            return cur.fetchall()

    def get_workflows(self) -> List[Dict[str, Any]]:
        """Get workflow information."""
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT *
                FROM workflows
                ORDER BY created_at DESC
            """
            )
            return cur.fetchall()

    def get_workflow_tasks(self) -> List[Dict[str, Any]]:
        """Get workflow task information."""
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT *
                FROM workflow_tasks
                ORDER BY created_at DESC
            """
            )
            return cur.fetchall()

    def generate_report(self) -> str:
        """Generate comprehensive observability report."""
        report_lines = []

        # Header
        report_lines.append("=" * 80)
        report_lines.append("AGENT OBSERVABILITY FRAMEWORK REPORT")
        report_lines.append(f"Generated: {datetime.now(timezone.utc).isoformat()}")
        report_lines.append("=" * 80)
        report_lines.append("")

        # Database Tables Overview
        report_lines.append("📊 DATABASE TABLES & ROW COUNTS")
        report_lines.append("-" * 80)
        table_counts = self.get_table_row_counts()
        for table, count in sorted(table_counts.items()):
            indicator = "✓" if count > 0 else "○"
            report_lines.append(f"  {indicator} {table}: {count:,} rows")
        report_lines.append("")

        # Routing Decisions Statistics
        report_lines.append("🎯 ROUTING DECISIONS STATISTICS")
        report_lines.append("-" * 80)
        stats = self.get_routing_statistics()
        if stats and stats["total_decisions"] > 0:
            report_lines.append(f"  Total Decisions: {stats['total_decisions']}")
            report_lines.append(f"  Avg Confidence: {stats['avg_confidence']:.4f}")
            report_lines.append(
                f"  Confidence Range: {stats['min_confidence']:.4f} - {stats['max_confidence']:.4f}"
            )
            report_lines.append(
                f"  Avg Routing Time: {stats['avg_routing_time_ms']:.2f}ms"
            )
            report_lines.append(
                f"  Max Routing Time: {stats['max_routing_time_ms']:.2f}ms"
            )
            report_lines.append(
                f"  Time Range: {stats['earliest_decision']} to {stats['latest_decision']}"
            )
        else:
            report_lines.append("  ⚠️  No routing decisions found")
        report_lines.append("")

        # Agent Usage Statistics
        report_lines.append("🤖 AGENT USAGE STATISTICS")
        report_lines.append("-" * 80)
        agent_stats = self.get_agent_usage_stats()
        if agent_stats:
            for stat in agent_stats:
                report_lines.append(f"  {stat['selected_agent']}")
                report_lines.append(f"    Usage Count: {stat['usage_count']}")
                report_lines.append(f"    Avg Confidence: {stat['avg_confidence']:.4f}")
                report_lines.append(
                    f"    Avg Routing Time: {stat['avg_routing_time_ms']:.2f}ms"
                )
                report_lines.append("")
        else:
            report_lines.append("  ⚠️  No agent usage data found")
        report_lines.append("")

        # Recent Routing Decisions
        report_lines.append("📋 RECENT ROUTING DECISIONS (Last 5)")
        report_lines.append("-" * 80)
        decisions = self.get_routing_decisions(limit=5)
        if decisions:
            for i, decision in enumerate(decisions, 1):
                report_lines.append(f"  Decision #{i}")
                report_lines.append(f"    Request: {decision['user_request']}")
                report_lines.append(f"    Selected Agent: {decision['selected_agent']}")
                report_lines.append(
                    f"    Confidence: {decision['confidence_score']:.4f}"
                )
                report_lines.append(
                    f"    Routing Time: {decision['routing_time_ms']}ms"
                )
                report_lines.append(f"    Strategy: {decision['routing_strategy']}")
                report_lines.append(f"    Created: {decision['created_at']}")

                # Parse alternatives
                if decision.get("alternatives"):
                    try:
                        alts = (
                            json.loads(decision["alternatives"])
                            if isinstance(decision["alternatives"], str)
                            else decision["alternatives"]
                        )
                        if alts:
                            report_lines.append("    Alternatives:")
                            for alt in alts[:3]:
                                report_lines.append(
                                    f"      - {alt['agent']}: {alt['confidence']:.4f}"
                                )
                    except:
                        pass
                report_lines.append("")
        else:
            report_lines.append("  ⚠️  No routing decisions found")
        report_lines.append("")

        # Transformation Events
        report_lines.append("🔄 TRANSFORMATION EVENTS")
        report_lines.append("-" * 80)
        transforms = self.get_transformation_events(limit=5)
        if transforms:
            report_lines.append(f"  Total Events: {len(transforms)}")
            for i, transform in enumerate(transforms[:3], 1):
                report_lines.append(f"  Event #{i}: {dict(transform)}")
        else:
            report_lines.append("  ℹ️  No transformation events found")
        report_lines.append("")

        # Hook Events
        report_lines.append("🎣 HOOK EVENTS")
        report_lines.append("-" * 80)
        hooks = self.get_hook_events(limit=5)
        if hooks:
            report_lines.append(f"  Total Events: {len(hooks)}")
            for i, hook in enumerate(hooks[:3], 1):
                report_lines.append(f"  Event #{i}: {dict(hook)}")
        else:
            report_lines.append("  ℹ️  No hook events found")
        report_lines.append("")

        # Workflows
        report_lines.append("⚙️  WORKFLOWS")
        report_lines.append("-" * 80)
        workflows = self.get_workflows()
        tasks = self.get_workflow_tasks()
        report_lines.append(f"  Total Workflows: {len(workflows)}")
        report_lines.append(f"  Total Tasks: {len(tasks)}")
        if workflows:
            for i, wf in enumerate(workflows[:3], 1):
                report_lines.append(f"  Workflow #{i}: {dict(wf)}")
        else:
            report_lines.append("  ℹ️  No workflows found")
        report_lines.append("")

        # Footer
        report_lines.append("=" * 80)
        report_lines.append("END OF REPORT")
        report_lines.append("=" * 80)

        return "\n".join(report_lines)

    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()


def main():
    """Main entry point."""
    try:
        reporter = ObservabilityReporter()
        report = reporter.generate_report()
        print(report)

        # Optionally save to file
        output_file = "observability_report.txt"
        with open(output_file, "w") as f:
            f.write(report)
        print(f"\n✅ Report saved to {output_file}")

        reporter.close()
        return 0
    except Exception as e:
        print(f"❌ Error generating report: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
