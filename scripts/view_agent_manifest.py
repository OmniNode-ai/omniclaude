#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""
View the complete manifest that a specific agent would receive.

Usage:
    python3 scripts/view_agent_manifest.py [agent-name]

Examples:
    python3 scripts/view_agent_manifest.py database-adapter-builder
    python3 scripts/view_agent_manifest.py agent-researcher
    python3 scripts/view_agent_manifest.py

Options:
    agent-name: Optional agent name (defaults to 'manifest-viewer')

The script shows all manifest sections:
- AVAILABLE PATTERNS (from Qdrant)
- INFRASTRUCTURE TOPOLOGY (PostgreSQL, Kafka, Qdrant, etc.)
- AI MODELS & DATA MODELS (ONEX node types, AI providers)
- DATABASE SCHEMAS (table definitions)
- DEBUG INTELLIGENCE (similar successful/failed workflows)
"""

import argparse
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def main():
    parser = argparse.ArgumentParser(
        description="View the complete manifest that a specific agent would receive",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s database-adapter-builder
  %(prog)s agent-researcher
  %(prog)s  # Uses default 'manifest-viewer'
        """,
    )
    parser.add_argument(
        "agent_name",
        nargs="?",
        default="manifest-viewer",
        help="Agent name to simulate (default: manifest-viewer)",
    )
    parser.add_argument(
        "--sections",
        nargs="+",
        default=[
            "patterns",
            "infrastructure",
            "models",
            "database_schemas",
            "debug_intelligence",
        ],
        help="Sections to include (default: all sections)",
    )
    parser.add_argument(
        "--no-db-logging",
        action="store_true",
        help="Disable database logging (prevents constraint errors)",
    )

    args = parser.parse_args()

    print("=" * 80)
    print(f"GENERATING AGENT MANIFEST FOR: {args.agent_name}")
    print("=" * 80)
    print()

    # Optionally disable database logging to avoid constraint errors
    if args.no_db_logging:
        os.environ["DISABLE_MANIFEST_DB_LOGGING"] = "true"
        print("NOTE: Database logging disabled (avoiding constraint errors)")
        print()

    try:
        from agents.lib.manifest_injector import inject_manifest

        # Generate manifest with all sections
        # Note: Database constraint errors are non-blocking - manifest still generates
        manifest = inject_manifest(agent_name=args.agent_name, sections=args.sections)

        print(manifest)
        print()
        print("=" * 80)
        print("END OF MANIFEST")
        print("=" * 80)
        print()
        print(f"Agent simulated: {args.agent_name}")
        print(f"Sections included: {', '.join(args.sections)}")

    except ImportError as e:
        print(f"ERROR: Failed to import manifest_injector: {e}")
        print("Make sure you're running from the omniclaude directory")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
