#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""CLI for pr_claim_registry diagnostics and lane ownership claims.

Inspect, record, and release claim files at ``$ONEX_STATE_DIR/pr-queue/claims/``.

The ``claim`` command is the escape hatch the OMN-16485 pre-mutation ownership
guard points at when it refuses a ``gh pr close``: recording the claim IS the
attribution record that the shared ``gh`` identity otherwise fails to produce.

Usage:
    python scripts/pr_claim_registry_cli.py list
    python scripts/pr_claim_registry_cli.py claim <pr_key> [--action close] [--lane <id>]
    python scripts/pr_claim_registry_cli.py release <pr_key> <run_id>

Examples:
    python scripts/pr_claim_registry_cli.py list
    python scripts/pr_claim_registry_cli.py claim omninode-ai/omniclaude#247 --action close
    python scripts/pr_claim_registry_cli.py release omninode-ai/omniclaude#247 20260223-143012-a3f
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime


def _resolve_session_id_fn() -> object:
    """Import the canonical session-id resolver (repo-root path may be needed)."""
    try:
        from plugins.onex.hooks.lib.session_id import resolve_session_id
    except ImportError:
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sys.path.insert(0, repo_root)
        from plugins.onex.hooks.lib.session_id import (  # type: ignore[no-redef]
            resolve_session_id,
        )
    return resolve_session_id


def _import_lib() -> tuple[object, object]:
    """Import the registry and ownership-guard modules, adding repo root if needed."""
    try:
        from plugins.onex.hooks.lib import pr_claim_registry, pr_ownership_guard
    except ImportError:
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sys.path.insert(0, repo_root)
        from plugins.onex.hooks.lib import (  # type: ignore[no-redef]
            pr_claim_registry,
            pr_ownership_guard,
        )
    return pr_claim_registry, pr_ownership_guard


def _cmd_list(registry: object) -> int:
    active = registry.list_active_claims()  # type: ignore[attr-defined]
    if not active:
        print("No active claims.")
        return 0
    print(f"{len(active)} active claim(s):")
    for claim in active:
        print(
            f"  {claim['pr_key']}"
            f" | lane: {claim.get('lane_id') or '<none — INDETERMINATE>'}"
            f" | run: {claim['claimed_by_run']}"
            f" | host: {claim['claimed_by_host']}"
            f" | action: {claim['action']}"
            f" | heartbeat: {claim['last_heartbeat_at']}"
        )
    return 0


def _cmd_claim(registry: object, guard: object, args: argparse.Namespace) -> int:
    lane_id = args.lane or guard.resolve_lane_id()  # type: ignore[attr-defined]
    if not lane_id:
        print(
            "Error: no lane identity could be resolved and --lane was not given.\n"
            "A claim without a lane cannot authorize a mutation — the ownership "
            "guard treats it as INDETERMINATE. Export ONEX_LANE_ID=<your-lane-handle> "
            "(the handle you registered in the rolling work ledger) or pass --lane.",
            file=sys.stderr,
        )
        return 1

    resolve_session_id = _resolve_session_id_fn()
    run_id = args.run_id or resolve_session_id(  # type: ignore[operator]
        default=datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    )

    acquired = registry.acquire(  # type: ignore[attr-defined]
        pr_key=args.pr_key,
        run_id=run_id,
        action=args.action,
        lane_id=lane_id,
    )
    if not acquired:
        existing = registry.get_claim(args.pr_key)  # type: ignore[attr-defined]
        owner = (existing or {}).get("lane_id") or "<unknown lane>"
        print(
            f"Refused: {args.pr_key} is already actively claimed by lane {owner}.\n"
            "Coordinate with that lane rather than taking the claim.",
            file=sys.stderr,
        )
        return 1

    print(
        f"Claimed {args.pr_key} for lane '{lane_id}' (run: {run_id}, action: {args.action})"
    )
    return 0


def _cmd_release(registry: object, args: argparse.Namespace) -> int:
    registry.release(args.pr_key, args.run_id)  # type: ignore[attr-defined]
    print(f"Released claim for {args.pr_key} (run: {args.run_id})")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the claim registry CLI."""
    parser = argparse.ArgumentParser(
        description="Inspect and manage PR lane-ownership claims (OMN-16485)."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List active claims")

    claim_parser = sub.add_parser("claim", help="Record lane ownership of a target")
    claim_parser.add_argument(
        "pr_key", help="Canonical key, e.g. omninode-ai/omniclaude#247"
    )
    claim_parser.add_argument(
        "--action", default="close", help="What the claim authorizes (default: close)"
    )
    claim_parser.add_argument(
        "--lane",
        default=None,
        help="Lane handle (default: resolved from the environment)",
    )
    claim_parser.add_argument(
        "--run-id", default=None, help="Run id (default: session id)"
    )

    release_parser = sub.add_parser("release", help="Release a claim held by a run")
    release_parser.add_argument("pr_key", help="Canonical PR key")
    release_parser.add_argument("run_id", help="Run id that holds the claim")

    args = parser.parse_args(argv)

    pr_claim_registry, pr_ownership_guard = _import_lib()
    registry = pr_claim_registry.ClaimRegistry()  # type: ignore[attr-defined]

    if args.command == "list":
        return _cmd_list(registry)
    if args.command == "claim":
        return _cmd_claim(registry, pr_ownership_guard, args)
    return _cmd_release(registry, args)


if __name__ == "__main__":
    sys.exit(main())
