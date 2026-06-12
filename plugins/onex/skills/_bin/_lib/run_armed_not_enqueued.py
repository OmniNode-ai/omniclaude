# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""CLI entry point for the armed-not-enqueued detector (OMN-13031).

Usage:
    python -m _lib.run_armed_not_enqueued [--repos REPOS] [--threshold-minutes N]
                                          [--format summary|json] [--out PATH]

    --repos              Comma-separated list of owner/repo slugs or short aliases.
                         Defaults to all configured QUEUE_REPOS.
    --threshold-minutes  Integer minutes before a PR is flagged (default: 30).
    --format             Output format: summary (default) or json.
    --out                Optional path for JSON log output.

Exit codes:
    0  No flagged PRs (or scan completed with errors but no flags)
    1  One or more PRs are flagged as armed-not-enqueued

[OMN-13031]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .armed_not_enqueued import (
    ARMED_NOT_ENQUEUED_THRESHOLD_MINUTES,
    QUEUE_REPOS,
    render_summary,
    scan_all_queue_repos,
)
from .base import ScriptStatus, atomic_write_json, default_log_dir, default_run_id
from .repo_aliases import AliasResolutionError, resolve


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="run_armed_not_enqueued",
        description="Armed-not-enqueued detector for ONEX queue repos (OMN-13031)",
    )
    parser.add_argument(
        "--repos",
        default=None,
        help=(
            "Comma-separated list of owner/repo slugs or short aliases. "
            "Defaults to all queue repos."
        ),
    )
    parser.add_argument(
        "--threshold-minutes",
        type=int,
        default=ARMED_NOT_ENQUEUED_THRESHOLD_MINUTES,
        dest="threshold_minutes",
        help=f"Minutes before flagging (default: {ARMED_NOT_ENQUEUED_THRESHOLD_MINUTES})",
    )
    parser.add_argument(
        "--format",
        choices=["summary", "json"],
        default="summary",
        dest="output_format",
        help="Output format (default: summary)",
    )
    parser.add_argument(
        "--out",
        default=None,
        dest="out",
        help="Optional path for JSON log output",
    )
    parser.add_argument(
        "--run-id",
        default=default_run_id(),
        dest="run_id",
        help="Unique run identifier (default: generated timestamp)",
    )
    return parser.parse_args()


def _resolve_repos(repos_arg: str | None) -> tuple[str, ...]:
    """Resolve --repos argument to a tuple of owner/repo slugs."""
    if repos_arg is None:
        return QUEUE_REPOS
    resolved: list[str] = []
    for raw in repos_arg.split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            resolved.append(resolve(raw))
        except AliasResolutionError:
            # Accept full slugs that aren't in the alias registry
            if "/" in raw:
                resolved.append(raw)
            else:
                print(
                    f"WARNING: unknown repo alias {raw!r} — skipping",
                    file=sys.stderr,
                )
    return tuple(resolved)


def main() -> None:
    args = _parse_args()
    repos = _resolve_repos(args.repos)

    if not repos:
        print("ERROR: no repos to scan", file=sys.stderr)
        sys.exit(1)

    result = scan_all_queue_repos(repos=repos, threshold_minutes=args.threshold_minutes)

    # Determine log path
    if args.out:
        log_path = Path(args.out)
    else:
        log_dir = default_log_dir()
        log_path = log_dir / f"armed-not-enqueued-{args.run_id}.json"

    # Write JSON log atomically
    atomic_write_json(log_path, result.model_dump())

    # Determine status
    status = ScriptStatus.WARN if result.flagged_count > 0 else ScriptStatus.OK

    if args.output_format == "json":
        print(json.dumps(result.model_dump(), indent=2, default=str))
    else:
        print(render_summary(result))
        print(
            f"\nSTATUS={status.value} LOG={log_path} "
            f'MSG="flagged={result.flagged_count} repos={len(repos)}"'
        )

    sys.exit(1 if status == ScriptStatus.WARN else 0)


if __name__ == "__main__":
    main()
