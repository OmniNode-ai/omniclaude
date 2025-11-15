#!/usr/bin/env python3
"""
Check Database Health - PostgreSQL health and activity

Usage:
    python3 execute.py [--tables table1,table2] [--include-sizes]

Created: 2025-11-12
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "_shared"))

try:
    from db_helper import execute_query
    from status_formatter import format_json
except ImportError as e:
    print(json.dumps({"success": False, "error": f"Import failed: {e}"}))
    sys.exit(1)


def validate_table_name(name: str) -> bool:
    """
    Validate table name follows PostgreSQL naming rules.

    Valid table names:
    - Start with a letter (a-z, A-Z) or underscore (_)
    - Contain only letters, digits, and underscores
    - No SQL injection characters (quotes, semicolons, dashes, etc.)

    Args:
        name: Table name to validate

    Returns:
        True if valid, False otherwise
    """
    return bool(re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", name))


def main():
    parser = argparse.ArgumentParser(description="Check database health")
    parser.add_argument("--tables", help="Comma-separated list of tables")
    parser.add_argument(
        "--include-sizes", action="store_true", help="Include table sizes"
    )
    args = parser.parse_args()

    try:
        result = {}

        # Check connection and table count
        table_count_query = "SELECT COUNT(*) as count FROM information_schema.tables WHERE table_schema = 'public'"
        table_result = execute_query(table_count_query)

        if table_result["success"] and table_result["rows"]:
            result["connection"] = "healthy"
            result["total_tables"] = table_result["rows"][0]["count"]
        else:
            result["connection"] = "failed"
            print(format_json(result))
            return 1

        # Check connection pool
        conn_query = """
            SELECT
                count(*) FILTER (WHERE state = 'active') as active,
                count(*) FILTER (WHERE state = 'idle') as idle,
                count(*) as total
            FROM pg_stat_activity
        """
        conn_result = execute_query(conn_query)
        if conn_result["success"] and conn_result["rows"]:
            row = conn_result["rows"][0]
            result["connections"] = {
                "active": row["active"] or 0,
                "idle": row["idle"] or 0,
                "total": row["total"] or 0,
            }

        # Check activity for specific tables
        if args.tables:
            tables_list = [t.strip() for t in args.tables.split(",")]
        else:
            tables_list = [
                "agent_manifest_injections",
                "agent_routing_decisions",
                "agent_actions",
            ]

        recent_activity = {}
        for table in tables_list:
            # Validate table name to prevent SQL injection
            if not validate_table_name(table):
                recent_activity[table] = {
                    "error": "Invalid table name - rejected for security",
                    "valid": False,
                }
                continue

            activity_query = f"""
                SELECT
                    COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '5 minutes') as count_5m,
                    COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '1 hour') as count_1h,
                    COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '24 hours') as count_24h
                FROM {table}
            """
            activity_result = execute_query(activity_query)
            if activity_result["success"] and activity_result["rows"]:
                row = activity_result["rows"][0]
                recent_activity[table] = {
                    "5m": row["count_5m"] or 0,
                    "1h": row["count_1h"] or 0,
                    "24h": row["count_24h"] or 0,
                }

        result["recent_activity"] = recent_activity

        # Include table sizes if requested
        if args.include_sizes:
            sizes = {}
            for table in tables_list:
                # Validate table name to prevent SQL injection
                if not validate_table_name(table):
                    sizes[table] = {
                        "error": "Invalid table name - rejected for security",
                        "valid": False,
                    }
                    continue

                size_query = (
                    f"SELECT pg_size_pretty(pg_total_relation_size('{table}')) as size"
                )
                size_result = execute_query(size_query)
                if size_result["success"] and size_result["rows"]:
                    sizes[table] = size_result["rows"][0]["size"]
            result["table_sizes"] = sizes

        print(format_json(result))
        return 0

    except Exception as e:
        print(format_json({"success": False, "error": str(e)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
