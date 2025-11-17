#!/usr/bin/env python3
"""
My Skill Name - Brief description

This skill does X, Y, and Z to help with A, B, and C.

Usage:
    python3 execute.py --param1 VALUE1 --param2 VALUE2 [--param3 VALUE3]

Examples:
    # Basic usage
    python3 execute.py --param1 "value1" --param2 "value2"

    # With optional parameter
    python3 execute.py --param1 "value1" --param2 "value2" --param3 "value3"

Author: <your-name>
Created: <YYYY-MM-DD>
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

# Add _shared to path for helper imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "_shared"))

# Import shared helpers (uncomment as needed)
# from db_helper import execute_query, get_correlation_id, handle_db_error
# from docker_helper import list_containers, get_container_status
# from kafka_helper import check_kafka_connection, list_topics
# from qdrant_helper import check_qdrant_connection, list_collections
from status_formatter import (  # Use shared formatter for consistent JSON output
    format_json,
)


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="My Skill Name - Brief description",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --param1 "value1" --param2 "value2"
  %(prog)s --param1 "value1" --param2 "value2" --param3 "value3"
        """,
    )

    # Required arguments
    parser.add_argument(
        "--param1", required=True, help="Description of param1 (required)"
    )
    parser.add_argument(
        "--param2", required=True, help="Description of param2 (required)"
    )

    # Optional arguments
    parser.add_argument(
        "--param3", required=False, help="Description of param3 (optional)"
    )

    # Output format
    parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="json",
        help="Output format (default: json)",
    )

    return parser.parse_args()


def validate_arguments(args: argparse.Namespace) -> None:
    """
    Validate parsed arguments.

    Raises:
        ValueError: If validation fails
    """
    # Add custom validation logic here
    # Example:
    # if args.param1 and len(args.param1) < 3:
    #     raise ValueError("param1 must be at least 3 characters")
    pass


def execute_skill_logic(args: argparse.Namespace) -> Dict[str, Any]:
    """
    Main skill execution logic.

    Args:
        args: Parsed command-line arguments

    Returns:
        Dict containing execution results

    Raises:
        Exception: If skill execution fails
    """
    # Implement your skill logic here
    # Example:
    # result = some_operation(args.param1, args.param2)

    return {
        "success": True,
        "message": "Skill executed successfully",
        "data": {"param1": args.param1, "param2": args.param2, "param3": args.param3},
    }


def format_output(result: Dict[str, Any], format_type: str) -> str:
    """
    Format output based on requested format.

    Args:
        result: Execution result dictionary
        format_type: Output format ("json" or "text")

    Returns:
        Formatted output string
    """
    if format_type == "json":
        # Use shared formatter for consistent JSON output with proper Decimal/datetime handling
        return format_json(result)
    elif format_type == "text":
        # Text format implementation
        if result.get("success"):
            return f"✅ Success: {result.get('message', 'Operation completed')}"
        else:
            return f"❌ Error: {result.get('error', 'Operation failed')}"
    else:
        # Default to JSON format using shared formatter
        return format_json(result)


def main() -> int:
    """
    Main entry point for the skill.

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    try:
        # Parse arguments
        args = parse_arguments()

        # Validate arguments
        validate_arguments(args)

        # Execute skill logic
        result = execute_skill_logic(args)

        # Format and print output
        output = format_output(result, args.format)
        print(output)

        return 0

    except ValueError as e:
        # Validation errors
        error_result = {
            "success": False,
            "error": "Validation Error",
            "details": str(e),
        }
        print(format_json(error_result), file=sys.stderr)
        return 1

    except Exception as e:
        # Unexpected errors
        error_result = {
            "success": False,
            "error": "Execution Error",
            "details": str(e),
            "type": type(e).__name__,
        }
        print(format_json(error_result), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
