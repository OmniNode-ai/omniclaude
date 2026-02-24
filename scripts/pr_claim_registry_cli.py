#!/usr/bin/env python3
"""CLI for pr_claim_registry diagnostics.

Provides list and release commands for inspecting and managing active claim files
at ~/.claude/pr-queue/claims/.

Usage:
    python scripts/pr_claim_registry_cli.py list
    python scripts/pr_claim_registry_cli.py release <pr_key> <run_id>

Examples:
    python scripts/pr_claim_registry_cli.py list
    python scripts/pr_claim_registry_cli.py release omninode-ai/omniclaude#247 20260223-143012-a3f
"""

from __future__ import annotations

import sys


def main() -> None:
    """Run the claim registry CLI."""
    # Import here so this script can be run from any directory
    try:
        from plugins.onex.hooks.lib.pr_claim_registry import ClaimRegistry
    except ImportError:
        # Try inserting repo root into path
        import os

        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sys.path.insert(0, repo_root)
        from plugins.onex.hooks.lib.pr_claim_registry import (
            ClaimRegistry,  # type: ignore[import-not-found]
        )

    registry = ClaimRegistry()

    if len(sys.argv) > 1 and sys.argv[1] == "list":
        active = registry.list_active_claims()
        if not active:
            print("No active claims.")
        else:
            print(f"{len(active)} active claim(s):")
            for claim in active:
                print(
                    f"  {claim['pr_key']}"
                    f" | run: {claim['claimed_by_run']}"
                    f" | host: {claim['claimed_by_host']}"
                    f" | action: {claim['action']}"
                    f" | heartbeat: {claim['last_heartbeat_at']}"
                )
    elif len(sys.argv) > 1 and sys.argv[1] == "release":
        if len(sys.argv) < 4:
            print(
                "Error: release requires <pr_key> and <run_id>. "
                "Use 'list' to find the run_id of the claim to release.",
                file=sys.stderr,
            )
            sys.exit(1)
        pr_key = sys.argv[2]
        run_id = sys.argv[3]
        registry.release(pr_key, run_id)
        print(f"Released claim for {pr_key} (run: {run_id})")
    else:
        print("Usage: pr_claim_registry_cli.py list")
        print("       pr_claim_registry_cli.py release <pr_key> <run_id>")
        sys.exit(1)


if __name__ == "__main__":
    main()
