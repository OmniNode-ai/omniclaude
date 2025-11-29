#!/usr/bin/env python3
"""
PR Comment Analyzer - Type-safe analysis of PR comments

Ensures Claude bot comments are NEVER missed and provides
comprehensive severity classification.

This module processes fetched PR data and generates structured
analysis with priority categorization.
"""

import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional


# Add the script directory to path for relative imports
SCRIPT_DIR = Path(__file__).parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from fetcher import PRFetcher, get_repo_from_git
from models import (
    BotType,
    CommentSeverity,
    CommentStatus,
    PRAnalysis,
    PRComment,
    PRCommentSource,
    PRData,
    classify_severity,
)


class PRAnalyzer:
    """Analyzes PR data to identify issues and priorities.

    CRITICAL: This analyzer ensures Claude bot comments are NEVER missed
    by double-checking author detection and maintaining a separate
    tracking list for Claude comments.
    """

    def __init__(self, pr_data: PRData):
        self.pr_data = pr_data
        self._validate_claude_comments()

    def _validate_claude_comments(self) -> None:
        """
        CRITICAL: Verify we haven't missed any Claude bot comments.

        This is a safety check that logs warnings if Claude comments
        might have been missed and corrects the detection.
        """
        all_comments = self.pr_data.comments

        # Double-check: scan raw JSON and author names for "claude" mentions
        for comment in all_comments:
            author_lower = comment.author.lower()

            # If "claude" is in author but we didn't detect it as CLAUDE_CODE
            if "claude" in author_lower and comment.author_type != BotType.CLAUDE_CODE:
                print(
                    f"WARNING: Possible missed Claude comment from {comment.author}",
                    file=sys.stderr,
                )
                # Force correction
                comment.author_type = BotType.CLAUDE_CODE

            # Also check raw_json if available
            if comment.raw_json:
                raw_author = comment.raw_json.get("user", {}).get("login", "")
                if isinstance(raw_author, str) and "claude" in raw_author.lower():
                    if comment.author_type != BotType.CLAUDE_CODE:
                        print(
                            f"WARNING: Caught Claude comment via raw_json from {raw_author}",
                            file=sys.stderr,
                        )
                        comment.author_type = BotType.CLAUDE_CODE

        # Log Claude comment count for verification
        claude_count = len(
            [c for c in all_comments if c.author_type == BotType.CLAUDE_CODE]
        )
        print(f"[Analyzer] Found {claude_count} Claude bot comments", file=sys.stderr)

    def analyze(self) -> PRAnalysis:
        """Run full analysis on PR data.

        Returns:
            PRAnalysis with categorized issues and merge readiness info
        """
        all_comments = self.pr_data.comments

        # Classify by severity
        by_severity: dict[str, int] = defaultdict(int)
        by_status: dict[str, int] = defaultdict(int)
        by_author_type: dict[str, int] = defaultdict(int)

        critical_issues: list[PRComment] = []
        major_issues: list[PRComment] = []
        minor_issues: list[PRComment] = []
        nitpick_issues: list[PRComment] = []
        claude_issues: list[PRComment] = []
        merge_blockers: list[PRComment] = []

        for comment in all_comments:
            # Update counts
            by_severity[comment.severity.value] += 1
            by_status[comment.status.value] += 1
            by_author_type[comment.author_type.value] += 1

            # Categorize by severity
            if comment.severity == CommentSeverity.CRITICAL:
                critical_issues.append(comment)
                if comment.status == CommentStatus.UNADDRESSED:
                    merge_blockers.append(comment)
            elif comment.severity == CommentSeverity.MAJOR:
                major_issues.append(comment)
                if comment.status == CommentStatus.UNADDRESSED:
                    merge_blockers.append(comment)
            elif comment.severity == CommentSeverity.MINOR:
                minor_issues.append(comment)
                # Minor issues should also block merge according to requirements
                if comment.status == CommentStatus.UNADDRESSED:
                    merge_blockers.append(comment)
            elif comment.severity == CommentSeverity.NITPICK:
                nitpick_issues.append(comment)
                # Nitpicks do NOT block merge

            # ALWAYS track Claude comments separately - NEVER miss these!
            if comment.is_claude_bot():
                claude_issues.append(comment)

        # Generate summary
        summary = self._generate_summary(
            total=len(all_comments),
            critical=len(critical_issues),
            major=len(major_issues),
            minor=len(minor_issues),
            nitpicks=len(nitpick_issues),
            claude=len(claude_issues),
            blockers=len(merge_blockers),
        )

        return PRAnalysis(
            pr_data=self.pr_data,
            analyzed_at=datetime.now(),
            total_comments=len(all_comments),
            by_severity=dict(by_severity),
            by_status=dict(by_status),
            by_author_type=dict(by_author_type),
            critical_issues=critical_issues,
            major_issues=major_issues,
            minor_issues=minor_issues,
            nitpick_issues=nitpick_issues,
            claude_issues=claude_issues,
            merge_blockers=merge_blockers,
            summary=summary,
        )

    def _generate_summary(
        self,
        total: int,
        critical: int,
        major: int,
        minor: int,
        nitpicks: int,
        claude: int,
        blockers: int,
    ) -> str:
        """Generate human-readable summary."""
        lines = [
            f"PR #{self.pr_data.pr_number} Analysis Summary",
            "=" * 40,
            f"Repository: {self.pr_data.repository}",
            f"Total comments: {total}",
            "",
            "By Severity:",
            f"  Critical: {critical}",
            f"  Major: {major}",
            f"  Minor: {minor}",
            f"  Nitpicks: {nitpicks}",
            "",
            f"Claude bot comments: {claude}",
            f"Merge blockers: {blockers}",
            "",
        ]

        if blockers > 0:
            lines.append("STATUS: NOT READY TO MERGE")
            lines.append(f"  - {blockers} unaddressed critical/major/minor issues")
        else:
            lines.append("STATUS: No blocking issues found")

        return "\n".join(lines)

    def get_actionable_summary(self, include_nitpicks: bool = False) -> dict:
        """Get actionable issues in a structured format.

        Args:
            include_nitpicks: Whether to include nitpick issues

        Returns:
            Dictionary with categorized issues and merge readiness
        """
        analysis = self.analyze()

        result = {
            "pr_number": self.pr_data.pr_number,
            "repository": self.pr_data.repository,
            "merge_ready": len(analysis.merge_blockers) == 0,
            "blocker_count": len(analysis.merge_blockers),
            "total_comments": analysis.total_comments,
            "sections": {},
        }

        # Critical issues (always include)
        if analysis.critical_issues:
            result["sections"]["critical"] = [
                self._format_issue(c) for c in analysis.critical_issues
            ]

        # Major issues (always include)
        if analysis.major_issues:
            result["sections"]["major"] = [
                self._format_issue(c) for c in analysis.major_issues
            ]

        # Minor issues (always include)
        if analysis.minor_issues:
            result["sections"]["minor"] = [
                self._format_issue(c) for c in analysis.minor_issues
            ]

        # Nitpicks (optional)
        if include_nitpicks and analysis.nitpick_issues:
            result["sections"]["nitpicks"] = [
                self._format_issue(c) for c in analysis.nitpick_issues
            ]

        # Claude comments (ALWAYS include - never miss these!)
        if analysis.claude_issues:
            result["sections"]["claude_bot"] = [
                self._format_issue(c) for c in analysis.claude_issues
            ]

        return result

    def _format_issue(self, comment: PRComment) -> dict:
        """Format a comment for output."""
        return {
            "id": comment.id,
            "severity": comment.severity.value,
            "author": comment.author,
            "is_bot": comment.is_bot(),
            "is_claude": comment.is_claude_bot(),
            "status": comment.status.value,
            "source": comment.source.value,
            "file": comment.file_ref.path if comment.file_ref else None,
            "line": comment.file_ref.line if comment.file_ref else None,
            "summary": (
                comment.body[:200] + "..." if len(comment.body) > 200 else comment.body
            ),
            "full_body": comment.body,
            "structured_sections": [
                {"type": s.section_type, "content": s.content[:500]}
                for s in comment.structured_sections
            ],
        }


def analyze_pr(repo: str, pr_number: int, use_cache: bool = True) -> PRAnalysis:
    """Convenience function to fetch and analyze a PR.

    Args:
        repo: Repository in "owner/repo" format
        pr_number: PR number to analyze
        use_cache: Whether to use cached data

    Returns:
        PRAnalysis with complete categorization
    """
    fetcher = PRFetcher(repo, pr_number)
    pr_data = fetcher.fetch(use_cache=use_cache)
    analyzer = PRAnalyzer(pr_data)
    return analyzer.analyze()


def generate_markdown_report(analysis: PRAnalysis) -> str:
    """Generate a markdown report from analysis.

    Args:
        analysis: PRAnalysis to format

    Returns:
        Markdown-formatted report string
    """
    lines = [
        f"# PR #{analysis.pr_data.pr_number} Review Analysis",
        "",
        f"**Repository**: {analysis.pr_data.repository}",
        f"**Analyzed**: {analysis.analyzed_at.isoformat()}",
        f"**Total Comments**: {analysis.total_comments}",
        "",
    ]

    # Merge status
    if analysis.merge_blockers:
        lines.append("## NOT READY TO MERGE")
        lines.append("")
        lines.append(
            f"**{len(analysis.merge_blockers)} blocking issues** must be addressed:"
        )
        lines.append("")
    else:
        lines.append("## No Blocking Issues")
        lines.append("")
        lines.append("This PR has no critical, major, or minor issues blocking merge.")
        lines.append("")

    # Priority breakdown table
    lines.append("## Priority Breakdown")
    lines.append("")
    lines.append("| Priority | Count | Status |")
    lines.append("|----------|-------|--------|")
    lines.append(
        f"| CRITICAL | {len(analysis.critical_issues)} | {'Must resolve' if analysis.critical_issues else 'None'} |"
    )
    lines.append(
        f"| MAJOR | {len(analysis.major_issues)} | {'Should resolve' if analysis.major_issues else 'None'} |"
    )
    lines.append(
        f"| MINOR | {len(analysis.minor_issues)} | {'Should resolve' if analysis.minor_issues else 'None'} |"
    )
    lines.append(f"| NITPICK | {len(analysis.nitpick_issues)} | Optional |")
    lines.append("")

    # Critical issues
    if analysis.critical_issues:
        lines.append("## CRITICAL Issues")
        lines.append("")
        for i, c in enumerate(analysis.critical_issues, 1):
            lines.append(f"### CRITICAL-{i}: {c.author}")
            lines.append("")
            if c.file_ref:
                lines.append(
                    f"**File**: `{c.file_ref.path}`"
                    + (f":{c.file_ref.line}" if c.file_ref.line else "")
                )
            lines.append(f"**Source**: {c.source.value}")
            lines.append("")
            lines.append(c.body[:1000] + ("..." if len(c.body) > 1000 else ""))
            lines.append("")
            lines.append("---")
            lines.append("")

    # Major issues
    if analysis.major_issues:
        lines.append("## MAJOR Issues")
        lines.append("")
        for i, c in enumerate(analysis.major_issues, 1):
            lines.append(f"### MAJOR-{i}: {c.author}")
            lines.append("")
            if c.file_ref:
                lines.append(
                    f"**File**: `{c.file_ref.path}`"
                    + (f":{c.file_ref.line}" if c.file_ref.line else "")
                )
            lines.append(f"**Source**: {c.source.value}")
            lines.append("")
            lines.append(c.body[:1000] + ("..." if len(c.body) > 1000 else ""))
            lines.append("")
            lines.append("---")
            lines.append("")

    # Minor issues
    if analysis.minor_issues:
        lines.append("## MINOR Issues")
        lines.append("")
        for i, c in enumerate(analysis.minor_issues, 1):
            lines.append(f"### MINOR-{i}: {c.author}")
            lines.append("")
            if c.file_ref:
                lines.append(
                    f"**File**: `{c.file_ref.path}`"
                    + (f":{c.file_ref.line}" if c.file_ref.line else "")
                )
            lines.append(f"**Source**: {c.source.value}")
            lines.append("")
            lines.append(c.body[:500] + ("..." if len(c.body) > 500 else ""))
            lines.append("")
            lines.append("---")
            lines.append("")

    # Claude bot comments (ALWAYS show - very important!)
    if analysis.claude_issues:
        lines.append("## Claude Bot Comments")
        lines.append("")
        lines.append(f"**{len(analysis.claude_issues)} comments from Claude Code bot**")
        lines.append("")
        for i, c in enumerate(analysis.claude_issues, 1):
            lines.append(f"### [{c.severity.value.upper()}] Claude Comment {i}")
            lines.append("")
            lines.append(f"**Source**: {c.source.value}")
            lines.append(
                f"**Created**: {c.created_at.isoformat() if c.created_at else 'Unknown'}"
            )
            lines.append("")
            lines.append(c.body)
            lines.append("")
            lines.append("---")
            lines.append("")

    # Nitpicks (collapsed/summarized)
    if analysis.nitpick_issues:
        lines.append("## Nitpicks (Optional)")
        lines.append("")
        lines.append(f"{len(analysis.nitpick_issues)} nitpick comments (not blocking)")
        lines.append("")
        lines.append("<details>")
        lines.append("<summary>Click to expand nitpicks</summary>")
        lines.append("")
        for i, c in enumerate(analysis.nitpick_issues, 1):
            lines.append(f"**NIT-{i}** ({c.author}): {c.body[:200]}...")
            lines.append("")
        lines.append("</details>")
        lines.append("")

    return "\n".join(lines)


# CLI interface
def main():
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Analyze PR comments with type safety")
    parser.add_argument("pr_number", type=int, help="PR number")
    parser.add_argument("--repo", default=None, help="Repository (owner/repo)")
    parser.add_argument("--no-cache", action="store_true", help="Skip cache")
    parser.add_argument(
        "--output",
        choices=["json", "markdown", "summary"],
        default="summary",
        help="Output format",
    )
    parser.add_argument(
        "--claude-only", action="store_true", help="Show only Claude bot comments"
    )
    parser.add_argument(
        "--include-nitpicks", action="store_true", help="Include nitpicks in output"
    )
    args = parser.parse_args()

    # Get repo from git if not provided
    repo = args.repo
    if not repo:
        repo = get_repo_from_git()
        if not repo:
            print(
                "Error: Could not determine repository. Use --repo flag.",
                file=sys.stderr,
            )
            sys.exit(1)

    try:
        analysis = analyze_pr(repo, args.pr_number, use_cache=not args.no_cache)

        if args.claude_only:
            print(f"Claude Bot Comments ({len(analysis.claude_issues)}):")
            print("=" * 50)
            for c in analysis.claude_issues:
                print(f"\n[{c.severity.value.upper()}] {c.author}")
                print(f"Source: {c.source.value}")
                print(f"Status: {c.status.value}")
                print("-" * 30)
                print(c.body[:500] + "..." if len(c.body) > 500 else c.body)
                print()
            return

        if args.output == "json":
            # Output analysis as JSON
            print(analysis.model_dump_json(indent=2))
        elif args.output == "markdown":
            print(generate_markdown_report(analysis))
        else:
            # Summary output
            print(analysis.summary)
            print()

            # Show merge readiness prominently
            if analysis.is_merge_ready():
                print("MERGE READY: Yes")
            else:
                print(f"MERGE READY: No ({len(analysis.merge_blockers)} blockers)")

                # List blockers
                print("\nBlocking issues:")
                for c in analysis.merge_blockers[:10]:  # Show first 10
                    severity = c.severity.value.upper()
                    preview = c.body[:100].replace("\n", " ")
                    print(f"  [{severity}] {c.author}: {preview}...")

                if len(analysis.merge_blockers) > 10:
                    print(f"  ... and {len(analysis.merge_blockers) - 10} more")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
