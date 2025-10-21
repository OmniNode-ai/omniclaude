#!/usr/bin/env python3
"""
Validation Script for Migration 002: Separate Task Metrics

Validates data quality before and after migration:
1. Pre-migration: Identifies mislabeled metrics
2. Post-migration: Verifies data separation and integrity
3. Reports metrics distribution and quality

Correlation ID: fe9bbe61-39d7-4124-b6ec-d61de1e0ee41-P2
"""

import os
import sys
from datetime import datetime
from typing import Any, Dict

import psycopg2
from psycopg2.extras import RealDictCursor


class MigrationValidator:
    """Validate migration 002 data quality"""

    def __init__(self, db_password: str = None):
        password = db_password or os.getenv(
            "OMNINODE_BRIDGE_PASSWORD", "omninode-bridge-postgres-dev-2024"
        )
        self.conn_string = (
            f"host=localhost port=5436 dbname=omninode_bridge "
            f"user=postgres password={password}"
        )

    def get_connection(self):
        """Get database connection"""
        return psycopg2.connect(self.conn_string, cursor_factory=RealDictCursor)

    def check_pre_migration_state(self) -> Dict[str, Any]:
        """Check state before migration"""
        print("\n" + "=" * 80)
        print("PRE-MIGRATION VALIDATION")
        print("=" * 80)

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                # Check if task_completion_metrics exists
                cur.execute(
                    """
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_name = 'task_completion_metrics'
                    ) as table_exists
                """
                )
                result = cur.fetchone()
                task_table_exists = result["table_exists"] if result else False

                if task_table_exists:
                    print("⚠️  WARNING: task_completion_metrics already exists")
                    print("   Migration may have already been run")
                    return {"already_migrated": True}

                # Analyze router_performance_metrics
                cur.execute(
                    """
                    SELECT
                        COUNT(*) as total_records,
                        COUNT(*) FILTER (WHERE routing_duration_ms > 500) as high_duration_count,
                        COUNT(*) FILTER (WHERE routing_duration_ms > 1000) as very_high_duration_count,
                        MIN(routing_duration_ms) as min_duration,
                        MAX(routing_duration_ms) as max_duration,
                        AVG(routing_duration_ms) as avg_duration,
                        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY routing_duration_ms) as median_duration,
                        PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY routing_duration_ms) as p95_duration
                    FROM router_performance_metrics
                """
                )
                stats = dict(cur.fetchone())

                print("\nRouter Performance Metrics Analysis:")
                print(f"  Total records: {stats['total_records']}")
                print(
                    f"  Records >500ms: {stats['high_duration_count']} "
                    f"({100.0 * stats['high_duration_count'] / max(stats['total_records'], 1):.1f}%)"
                )
                print(
                    f"  Records >1000ms: {stats['very_high_duration_count']} "
                    f"({100.0 * stats['very_high_duration_count'] / max(stats['total_records'], 1):.1f}%)"
                )
                print("\nDuration Statistics:")
                print(f"  Min: {stats['min_duration']}ms")
                print(f"  Avg: {stats['avg_duration']:.0f}ms")
                print(f"  Median: {stats['median_duration']:.0f}ms")
                print(f"  P95: {stats['p95_duration']:.0f}ms")
                print(f"  Max: {stats['max_duration']}ms")

                # Show records that will be moved
                if stats["high_duration_count"] > 0:
                    print("\nRecords to be migrated (>500ms):")
                    cur.execute(
                        """
                        SELECT
                            id,
                            created_at,
                            LEFT(query_text, 60) as query_preview,
                            routing_duration_ms,
                            trigger_match_strategy
                        FROM router_performance_metrics
                        WHERE routing_duration_ms > 500
                        ORDER BY routing_duration_ms DESC
                    """
                    )
                    for row in cur.fetchall():
                        print(
                            f"  - {row['routing_duration_ms']:>5}ms | "
                            f"{row['trigger_match_strategy']:<30} | "
                            f"{row['query_preview']}"
                        )

                return stats

    def check_post_migration_state(self) -> Dict[str, Any]:
        """Check state after migration"""
        print("\n" + "=" * 80)
        print("POST-MIGRATION VALIDATION")
        print("=" * 80)

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                # Check task_completion_metrics exists
                cur.execute(
                    """
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_name = 'task_completion_metrics'
                    ) as table_exists
                """
                )
                result = cur.fetchone()
                task_table_exists = result["table_exists"] if result else False

                if not task_table_exists:
                    print("❌ ERROR: task_completion_metrics does not exist")
                    print("   Migration has not been run")
                    return {"migration_incomplete": True}

                print("✅ task_completion_metrics table exists")

                # Check router_performance_metrics
                cur.execute(
                    """
                    SELECT
                        COUNT(*) as total_records,
                        COUNT(*) FILTER (WHERE routing_duration_ms > 500) as high_duration_count,
                        COUNT(*) FILTER (WHERE routing_duration_ms > 1000) as very_high_duration_count,
                        MAX(routing_duration_ms) as max_duration
                    FROM router_performance_metrics
                """
                )
                routing_stats = dict(cur.fetchone())

                print("\nRouter Performance Metrics (Post-Migration):")
                print(f"  Total records: {routing_stats['total_records']}")
                print(f"  Records >500ms: {routing_stats['high_duration_count']}")
                print(f"  Records >1000ms: {routing_stats['very_high_duration_count']}")
                print(f"  Max duration: {routing_stats['max_duration']}ms")

                if routing_stats["high_duration_count"] > 0:
                    print("  ⚠️  WARNING: Found records >500ms (should be migrated)")

                if routing_stats["very_high_duration_count"] > 0:
                    print("  ❌ ERROR: Found records >1000ms (constraint violation)")

                # Check task_completion_metrics
                cur.execute(
                    """
                    SELECT
                        COUNT(*) as total_records,
                        COUNT(*) FILTER (WHERE success = true) as successful_tasks,
                        MIN(completion_time_ms) as min_completion,
                        MAX(completion_time_ms) as max_completion,
                        AVG(completion_time_ms) as avg_completion,
                        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY completion_time_ms) as median_completion
                    FROM task_completion_metrics
                """
                )
                task_stats = dict(cur.fetchone())

                print("\nTask Completion Metrics (Post-Migration):")
                print(f"  Total records: {task_stats['total_records']}")
                print(
                    f"  Successful: {task_stats['successful_tasks']} "
                    f"({100.0 * task_stats['successful_tasks'] / max(task_stats['total_records'], 1):.1f}%)"
                )
                print("\nCompletion Time Statistics:")
                print(f"  Min: {task_stats['min_completion']}ms")
                print(f"  Avg: {task_stats['avg_completion']:.0f}ms")
                print(f"  Median: {task_stats['median_completion']:.0f}ms")
                print(f"  Max: {task_stats['max_completion']}ms")

                # Check constraint exists
                cur.execute(
                    """
                    SELECT EXISTS (
                        SELECT FROM information_schema.table_constraints
                        WHERE table_name = 'router_performance_metrics'
                          AND constraint_name = 'valid_routing_duration'
                    ) as constraint_exists
                """
                )
                result = cur.fetchone()
                constraint_exists = result["constraint_exists"] if result else False

                if constraint_exists:
                    print("\n✅ Constraint 'valid_routing_duration' exists")
                else:
                    print(
                        "\n⚠️  WARNING: Constraint 'valid_routing_duration' does not exist"
                    )

                # Check view exists
                cur.execute(
                    """
                    SELECT EXISTS (
                        SELECT FROM information_schema.views
                        WHERE table_name = 'v_all_performance_metrics'
                    ) as view_exists
                """
                )
                result = cur.fetchone()
                view_exists = result["view_exists"] if result else False

                if view_exists:
                    print("✅ View 'v_all_performance_metrics' exists")
                else:
                    print("⚠️  WARNING: View 'v_all_performance_metrics' does not exist")

                # Check migration record
                try:
                    cur.execute(
                        """
                        SELECT EXISTS (
                            SELECT FROM schema_migrations
                            WHERE name = '002_separate_task_metrics'
                        ) as migration_recorded
                    """
                    )
                    result = cur.fetchone()
                    migration_recorded = (
                        result["migration_recorded"] if result else False
                    )

                    if migration_recorded:
                        print("✅ Migration recorded in schema_migrations")
                    else:
                        print("⚠️  WARNING: Migration not recorded in schema_migrations")
                except Exception:
                    print(
                        "⚠️  INFO: schema_migrations table does not exist (expected in some environments)"
                    )
                    migration_recorded = None

                return {
                    "routing_stats": routing_stats,
                    "task_stats": task_stats,
                    "constraint_exists": constraint_exists,
                    "view_exists": view_exists,
                    "migration_recorded": migration_recorded,
                }

    def validate_data_integrity(self) -> bool:
        """Validate data integrity post-migration"""
        print("\n" + "=" * 80)
        print("DATA INTEGRITY VALIDATION")
        print("=" * 80)

        issues = []

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                # Check for orphaned metadata
                cur.execute(
                    """
                    SELECT COUNT(*) as count
                    FROM task_completion_metrics
                    WHERE metadata->>'original_table' IS NOT NULL
                """
                )
                migrated_count = cur.fetchone()["count"]
                print(f"\nMigrated records: {migrated_count}")

                # Check for data loss
                cur.execute(
                    """
                    SELECT COUNT(*) as routing_count
                    FROM router_performance_metrics
                """
                )
                routing_count = cur.fetchone()["routing_count"]

                cur.execute(
                    """
                    SELECT COUNT(*) as task_count
                    FROM task_completion_metrics
                """
                )
                task_count = cur.fetchone()["task_count"]

                total_count = routing_count + task_count
                print(f"Total records after migration: {total_count}")
                print(f"  Routing metrics: {routing_count}")
                print(f"  Task metrics: {task_count}")

                # Verify no high-duration records in routing table
                cur.execute(
                    """
                    SELECT COUNT(*) as count
                    FROM router_performance_metrics
                    WHERE routing_duration_ms >= 1000
                """
                )
                violation_count = cur.fetchone()["count"]

                if violation_count > 0:
                    issues.append(
                        f"Found {violation_count} records with duration >=1000ms in routing table"
                    )

        print("\n" + "=" * 80)
        if issues:
            print("❌ VALIDATION FAILED")
            print("=" * 80)
            for issue in issues:
                print(f"  - {issue}")
            return False
        else:
            print("✅ VALIDATION PASSED")
            print("=" * 80)
            print("All data integrity checks passed successfully")
            return True

    def generate_migration_report(self) -> str:
        """Generate comprehensive migration report"""
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

        report = []
        report.append("=" * 80)
        report.append("MIGRATION 002 VALIDATION REPORT")
        report.append(f"Generated: {timestamp}")
        report.append("Correlation ID: fe9bbe61-39d7-4124-b6ec-d61de1e0ee41-P2")
        report.append("=" * 80)

        pre_state = self.check_pre_migration_state()

        if not pre_state.get("already_migrated"):
            report.append("\n⚠️  Migration has not been run yet")
            report.append(
                "Run: psql -h localhost -p 5436 -U postgres -d omninode_bridge -f agents/migrations/002_separate_task_metrics.sql"
            )
        else:
            self.check_post_migration_state()
            integrity_valid = self.validate_data_integrity()

            report.append(
                "\nMigration Status: "
                + ("✅ COMPLETE" if integrity_valid else "❌ FAILED")
            )

        return "\n".join(report)


def main():
    """Main validation entry point"""
    validator = MigrationValidator()

    if len(sys.argv) > 1 and sys.argv[1] == "pre":
        # Pre-migration validation
        validator.check_pre_migration_state()
    elif len(sys.argv) > 1 and sys.argv[1] == "post":
        # Post-migration validation
        validator.check_post_migration_state()
        validator.validate_data_integrity()
    else:
        # Full report
        print(validator.generate_migration_report())


if __name__ == "__main__":
    main()
