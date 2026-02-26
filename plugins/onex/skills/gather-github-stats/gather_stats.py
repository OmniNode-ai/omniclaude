#!/usr/bin/env python3
"""gather_stats.py — GitHub statistics gatherer for the gather-github-stats omniclaude skill.

Phase 1 stub: argparse wired to all 8 args + main() entry point.
Subsequent phases will implement the actual GitHub API queries and local archive scan.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gather_stats.py",
        description=(
            "Gather GitHub repository statistics — PR counts, commit velocity, "
            "contributor activity, LOC metrics — from the GitHub API and/or a "
            "local archive scan."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python gather_stats.py                              # Full report (GitHub + local)
  python gather_stats.py --github-only               # GitHub API only
  python gather_stats.py --local-only --local-path . # Local archive only
  python gather_stats.py --cached                    # Re-use cached results
  python gather_stats.py --output /tmp/report.md     # Custom output path
  python gather_stats.py --include-local-loc         # Enable LOC scan (slow)
  python gather_stats.py --include-private           # Include private repos
""",
    )

    # Scope flags
    scope = parser.add_argument_group("scope flags")
    scope_exclusive = scope.add_mutually_exclusive_group()
    scope_exclusive.add_argument(
        "--github-only",
        action="store_true",
        default=False,
        help="Skip local archive scan; query GitHub API only.",
    )
    scope_exclusive.add_argument(
        "--local-only",
        action="store_true",
        default=False,
        help="Skip GitHub API calls; scan local archive only.",
    )

    # Cache control
    parser.add_argument(
        "--cached",
        action="store_true",
        default=False,
        help="Use cached results (bypass TTL); skip live API/FS queries.",
    )

    # Output
    parser.add_argument(
        "--output",
        metavar="PATH",
        default="./stats_output.md",
        help="Output file path for the generated stats report (default: ./stats_output.md).",
    )

    # Local scan options
    local = parser.add_argument_group("local scan options")
    local.add_argument(
        "--local-path",
        metavar="PATH",
        default=".",
        help="Root path for local archive scan (default: current working directory).",
    )
    local.add_argument(
        "--max-depth",
        metavar="N",
        type=int,
        default=3,
        help="Maximum recursion depth for local archive scan (default: 3).",
    )
    local.add_argument(
        "--include-local-loc",
        action="store_true",
        default=False,
        help="Enable lines-of-code scan on local repos (can be slow for large trees).",
    )

    # GitHub options
    github = parser.add_argument_group("github options")
    github.add_argument(
        "--include-private",
        action="store_true",
        default=False,
        help="Include private GitHub repositories in API results.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Resolve output path
    output_path = Path(args.output)

    print("gather-github-stats v1.0.0 (Phase 1 stub)")
    print(f"  --github-only:       {args.github_only}")
    print(f"  --local-only:        {args.local_only}")
    print(f"  --cached:            {args.cached}")
    print(f"  --output:            {output_path}")
    print(f"  --local-path:        {args.local_path}")
    print(f"  --max-depth:         {args.max_depth}")
    print(f"  --include-local-loc: {args.include_local_loc}")
    print(f"  --include-private:   {args.include_private}")
    print()
    print("Phase 1 stub only — implementation coming in Phase 2+.")
    print(f"Would write report to: {output_path.resolve()}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
