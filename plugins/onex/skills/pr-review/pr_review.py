#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""
PR Review - Unified Type-Safe PR Review System

This is the main entry point for the Pydantic-backed PR review system.
Ensures Claude bot comments are NEVER missed.

Usage:
    pr_review.py <pr_number> [options]
    pr_review.py --help
"""

import argparse
import sys
from pathlib import Path

# Add current directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from analyzer import PRAnalyzer, generate_markdown_report
from fetcher import PRFetcher
from models import BotType, CommentSeverity, ModelPRAnalysis


def main():
    parser = argparse.ArgumentParser(
        description="Type-safe PR review with guaranteed Claude bot comment detection",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  pr_review.py 38                    # Quick summary
  pr_review.py 38 --full             # Full analysis with all comments
  pr_review.py 38 --claude-only      # Only Claude bot comments
  pr_review.py 38 --blockers         # Only merge blockers
  pr_review.py 38 --json             # JSON output
  pr_review.py 38 --markdown         # Markdown report
  pr_review.py 38 --save             # Save to tmp/pr-review-38.md
        """,
    )

    parser.add_argument("pr_number", type=int, help="PR number to review")
    parser.add_argument(
        "--repo", help="Repository (owner/repo), auto-detected if not provided"
    )
    parser.add_argument(
        "--no-cache", action="store_true", help="Skip cache, fetch fresh data"
    )

    # Output format
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument("--json", action="store_true", help="JSON output")
    output_group.add_argument("--markdown", action="store_true", help="Markdown report")
    output_group.add_argument(
        "--summary", action="store_true", help="Summary only (default)"
    )

    # Filters
    filter_group = parser.add_argument_group("Filters")
    filter_group.add_argument(
        "--claude-only", action="store_true", help="Only show Claude bot comments"
    )
    filter_group.add_argument(
        "--blockers", action="store_true", help="Only show merge blockers"
    )
    filter_group.add_argument(
        "--critical", action="store_true", help="Only critical issues"
    )
    filter_group.add_argument(
        "--no-nitpicks", action="store_true", help="Exclude nitpicks"
    )

    # Detail level
    parser.add_argument("--full", action="store_true", help="Include all details")
    parser.add_argument("--save", action="store_true", help="Save report to tmp/")
    parser.add_argument("--quiet", "-q", action="store_true", help="Minimal output")

    args = parser.parse_args()

    # Get repo
    repo = args.repo
    if not repo:
        import subprocess

        result = subprocess.run(
            ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
            capture_output=True,
            text=True,
            check=False,
        )
        repo = result.stdout.strip()
        if not repo:
            print(
                "ERROR: Could not detect repository. Use --repo owner/repo",
                file=sys.stderr,
            )
            sys.exit(1)

    # Fetch and analyze
    if not args.quiet:
        print(f"Fetching PR #{args.pr_number} from {repo}...", file=sys.stderr)

    try:
        fetcher = PRFetcher(repo, args.pr_number)
        pr_data = fetcher.fetch(use_cache=not args.no_cache)
        analyzer = PRAnalyzer(pr_data)
        analysis = analyzer.analyze()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    # Apply filters
    if args.claude_only:
        output = format_claude_only(analysis)
    elif args.blockers:
        output = format_blockers(analysis)
    elif args.critical:
        output = format_critical(analysis)
    elif args.json:
        output = analysis.model_dump_json(indent=2)
    elif args.markdown:
        output = generate_markdown_report(analysis)
    else:
        output = format_summary(
            analysis, include_details=args.full, no_nitpicks=args.no_nitpicks
        )

    # Output
    print(output)

    # Save if requested
    if args.save:
        save_dir = Path.cwd() / "tmp"
        save_dir.mkdir(exist_ok=True)
        save_path = save_dir / f"pr-review-{args.pr_number}.md"

        # Always save as markdown
        md_output = generate_markdown_report(analysis)
        save_path.write_text(md_output)
        print(f"\nSaved to: {save_path}", file=sys.stderr)

    # Exit code based on merge readiness
    if analysis.merge_blockers:
        sys.exit(1)  # Not ready to merge
    sys.exit(0)  # Ready to merge


def format_summary(
    analysis: ModelPRAnalysis, include_details: bool = False, no_nitpicks: bool = False
) -> str:
    """Format analysis as summary text."""
    lines = [
        "======================================================================",
        f"  PR #{analysis.pr_data.pr_number} Review Summary",
        "======================================================================",
        "",
        f"Repository: {analysis.pr_data.repository}",
        f"Title: {analysis.pr_data.title}",
        f"Analyzed: {analysis.analyzed_at.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "--- Comment Statistics ---",
        f"Total comments: {analysis.total_comments}",
    ]

    # By severity - use string keys since that's how by_severity is structured
    severity_emoji = {
        "critical": "[CRIT]",
        "major": "[MAJR]",
        "minor": "[MINR]",
        "nitpick": "[NIT ]",
        "unclassified": "[UNCL]",
    }
    for severity in CommentSeverity:
        count = analysis.by_severity.get(severity.value, 0)
        if count > 0:
            emoji = severity_emoji.get(severity.value, "")
            lines.append(f"  {emoji} {severity.value.upper()}: {count}")

    # Claude bot comments (ALWAYS show)
    claude_count = analysis.by_author_type.get(BotType.CLAUDE_CODE.value, 0)
    lines.append("")
    lines.append("--- Claude Bot Comments ---")
    lines.append(f"[BOT] Claude comments: {claude_count}")

    if claude_count > 0 and include_details:
        for c in analysis.claude_issues:
            lines.append(f"  [{c.severity.value.upper()}] {c.body[:80]}...")

    # Merge readiness
    lines.append("")
    lines.append("--- Merge Readiness ---")
    if analysis.merge_blockers:
        lines.append("[X] NOT READY TO MERGE")
        lines.append(f"   {len(analysis.merge_blockers)} blocking issues:")
        for c in analysis.merge_blockers[:5]:  # Show first 5
            lines.append(
                f"   * [{c.severity.value.upper()}] {c.author}: {c.body[:60]}..."
            )
        if len(analysis.merge_blockers) > 5:
            lines.append(f"   ... and {len(analysis.merge_blockers) - 5} more")
    else:
        lines.append("[OK] Ready to merge (no blocking issues)")

    return "\n".join(lines)


def format_claude_only(analysis: ModelPRAnalysis) -> str:
    """Format only Claude bot comments."""
    lines = [
        "======================================================================",
        f"  Claude Bot Comments - PR #{analysis.pr_data.pr_number}",
        "======================================================================",
        "",
        f"Found: {len(analysis.claude_issues)} Claude bot comments",
        "",
    ]

    if not analysis.claude_issues:
        lines.append("No Claude bot comments found.")
        return "\n".join(lines)

    for i, c in enumerate(analysis.claude_issues, 1):
        lines.append(f"--- Comment {i} ---")
        lines.append(f"Severity: {c.severity.value}")
        lines.append(f"Status: {c.status.value}")
        lines.append(f"Source: {c.source.value}")
        if c.file_ref:
            lines.append(f"File: {c.file_ref.path}:{c.file_ref.line}")
        lines.append("")
        lines.append(c.body)
        lines.append("")

    return "\n".join(lines)


def format_blockers(analysis: ModelPRAnalysis) -> str:
    """Format only merge blockers."""
    lines = [
        "======================================================================",
        f"  Merge Blockers - PR #{analysis.pr_data.pr_number}",
        "======================================================================",
        "",
    ]

    if not analysis.merge_blockers:
        lines.append("[OK] No merge blockers!")
        return "\n".join(lines)

    lines.append(f"[X] {len(analysis.merge_blockers)} blocking issues:")
    lines.append("")

    for i, c in enumerate(analysis.merge_blockers, 1):
        lines.append(f"{i}. [{c.severity.value.upper()}] {c.author}")
        if c.file_ref:
            lines.append(f"   File: {c.file_ref.path}:{c.file_ref.line}")
        lines.append(f"   {c.body[:200]}...")
        lines.append("")

    return "\n".join(lines)


def format_critical(analysis: ModelPRAnalysis) -> str:
    """Format only critical issues."""
    lines = [
        "======================================================================",
        f"  Critical Issues - PR #{analysis.pr_data.pr_number}",
        "======================================================================",
        "",
    ]

    if not analysis.critical_issues:
        lines.append("[OK] No critical issues!")
        return "\n".join(lines)

    lines.append(f"[CRIT] {len(analysis.critical_issues)} critical issues:")
    lines.append("")

    for i, c in enumerate(analysis.critical_issues, 1):
        lines.append(f"{i}. {c.author}")
        if c.file_ref:
            lines.append(f"   File: {c.file_ref.path}:{c.file_ref.line}")
        lines.append(f"   {c.body[:300]}...")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    main()
