#!/usr/bin/env python3
"""
Linear PR Integration - Create Linear tickets from PR review data

Uses the Pydantic-backed PR review system to ensure Claude bot
comments are NEVER missed when creating tickets.

This module bridges the PR review analysis system with Linear ticket
creation, providing type-safe data transformation.

Usage:
    # CLI
    ./pr_integration.py 123                    # Analyze PR #123
    ./pr_integration.py 123 --claude-only      # Only Claude comments
    ./pr_integration.py 123 --critical-only    # Critical + Claude

    # Python
    from pr_integration import get_pr_issues_for_linear
    issues = get_pr_issues_for_linear(123)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Add pr-review to path for imports
PR_REVIEW_PATH = Path(__file__).parent.parent / "pr-review"
if str(PR_REVIEW_PATH) not in sys.path:
    sys.path.insert(0, str(PR_REVIEW_PATH))

from analyzer import PRAnalyzer
from fetcher import PRFetcher, get_repo_from_git
from models import CommentSeverity, PRComment


def get_pr_issues_for_linear(
    pr_number: int,
    repo: str | None = None,
    include_claude: bool = True,
    include_critical: bool = True,
    include_major: bool = True,
    include_minor: bool = False,
    min_severity: CommentSeverity = CommentSeverity.MAJOR,
    use_cache: bool = True,
) -> list[dict]:
    """
    Get PR issues formatted for Linear ticket creation.

    CRITICAL: Claude bot comments are ALWAYS included and prioritized
    to ensure they are NEVER missed in the ticket creation process.

    Args:
        pr_number: The PR number to analyze
        repo: Repository in "owner/repo" format (auto-detected if not provided)
        include_claude: Always include Claude bot comments (default: True)
        include_critical: Include critical severity issues (default: True)
        include_major: Include major severity issues (default: True)
        include_minor: Include minor severity issues (default: False)
        min_severity: Minimum severity to include (default: MAJOR)
        use_cache: Whether to use cached PR data (default: True)

    Returns:
        List of dicts ready for Linear API with the following structure:
        {
            "title": str,
            "description": str,
            "priority": int (1=Urgent, 2=High, 3=Medium, 4=Low),
            "labels": list[str],
            "source_comment_id": str,
            "source_pr": int,
            "source_author": str,
            "is_claude_comment": bool,
        }

    Example:
        >>> issues = get_pr_issues_for_linear(123)
        >>> for issue in issues:
        ...     print(f"{issue['priority']}: {issue['title']}")
    """
    # Auto-detect repo if not provided
    if not repo:
        repo = get_repo_from_git()
        if not repo:
            raise ValueError(
                "Could not determine repository. "
                "Provide --repo flag or run from a git repository."
            )

    # Fetch and analyze PR data
    fetcher = PRFetcher(repo, pr_number)
    pr_data = fetcher.fetch(use_cache=use_cache)
    analyzer = PRAnalyzer(pr_data)
    analysis = analyzer.analyze()

    issues: list[dict] = []
    seen_ids: set[str] = set()  # Avoid duplicates

    # CRITICAL: Always include Claude bot comments first - they should NEVER be missed
    if include_claude:
        for comment in analysis.claude_issues:
            if comment.id not in seen_ids:
                issues.append(format_for_linear(comment, pr_number, repo, "Claude Bot"))
                seen_ids.add(comment.id)

    # Add critical issues (excluding already-added Claude comments)
    if include_critical:
        for comment in analysis.critical_issues:
            if comment.id not in seen_ids:
                issues.append(format_for_linear(comment, pr_number, repo, "Critical"))
                seen_ids.add(comment.id)

    # Add major issues (excluding already-added comments)
    if include_major:
        for comment in analysis.major_issues:
            if comment.id not in seen_ids:
                issues.append(format_for_linear(comment, pr_number, repo, "Major"))
                seen_ids.add(comment.id)

    # Add minor issues (excluding already-added comments)
    if include_minor:
        for comment in analysis.minor_issues:
            if comment.id not in seen_ids:
                issues.append(format_for_linear(comment, pr_number, repo, "Minor"))
                seen_ids.add(comment.id)

    return issues


def format_for_linear(
    comment: PRComment, pr_number: int, repo: str, source: str
) -> dict:
    """
    Format a PR comment for Linear ticket creation.

    Args:
        comment: The PRComment to format
        pr_number: PR number for reference
        repo: Repository name
        source: Source label (e.g., "Claude Bot", "Critical")

    Returns:
        Dictionary formatted for Linear API
    """
    # Create a meaningful title from the comment
    # Truncate and clean up for title
    body_preview = comment.body.replace("\n", " ").strip()
    if len(body_preview) > 60:
        # Find a good breakpoint
        title_text = body_preview[:57]
        # Try to break at word boundary
        last_space = title_text.rfind(" ")
        if last_space > 40:
            title_text = title_text[:last_space]
        title_text += "..."
    else:
        title_text = body_preview

    title = f"[PR #{pr_number}] {title_text}"

    # Build comprehensive description
    description_parts = [
        "## Source",
        f"- **PR**: #{pr_number} in {repo}",
        f"- **Author**: {comment.author}",
        f"- **Type**: {source}",
        f"- **Severity**: {comment.severity.value.upper()}",
        f"- **Comment Source**: {comment.source.value}",
    ]

    # Add file reference if present
    if comment.file_ref:
        description_parts.append("")
        description_parts.append("## Location")
        file_loc = f"- **File**: `{comment.file_ref.path}`"
        if comment.file_ref.line:
            file_loc += f":{comment.file_ref.line}"
        description_parts.append(file_loc)

    # Add the full comment body
    description_parts.append("")
    description_parts.append("## Comment")
    description_parts.append(comment.body)

    # Add structured sections if available
    if comment.structured_sections:
        description_parts.append("")
        description_parts.append("## Structured Sections")
        for section in comment.structured_sections:
            description_parts.append(
                f"### {section.section_type.replace('_', ' ').title()}"
            )
            if section.extracted_issues:
                for issue in section.extracted_issues:
                    description_parts.append(f"- {issue}")
            else:
                description_parts.append(section.content[:500])

    # Footer
    description_parts.append("")
    description_parts.append("---")
    description_parts.append(
        "*Auto-generated from PR review via Linear PR Integration*"
    )

    description = "\n".join(description_parts)

    # Map severity to Linear priority
    # Linear: 0 = No priority, 1 = Urgent, 2 = High, 3 = Normal, 4 = Low
    priority_map = {
        CommentSeverity.CRITICAL: 1,  # Urgent
        CommentSeverity.MAJOR: 2,  # High
        CommentSeverity.MINOR: 3,  # Normal
        CommentSeverity.NITPICK: 4,  # Low
        CommentSeverity.UNCLASSIFIED: 3,  # Normal (default)
    }

    # Build labels
    labels = [comment.severity.value.lower()]
    if comment.is_claude_bot():
        labels.append("claude-review")
    if comment.file_ref:
        labels.append("code-change")

    return {
        "title": title,
        "description": description,
        "priority": priority_map.get(comment.severity, 3),
        "labels": labels,
        "source_comment_id": comment.id,
        "source_pr": pr_number,
        "source_author": comment.author,
        "is_claude_comment": comment.is_claude_bot(),
        "severity": comment.severity.value,
        "file_path": comment.file_ref.path if comment.file_ref else None,
        "file_line": comment.file_ref.line if comment.file_ref else None,
    }


def get_merge_status_for_linear(
    pr_number: int,
    repo: str | None = None,
    use_cache: bool = True,
) -> dict:
    """
    Get merge status summary for Linear ticket tracking.

    Args:
        pr_number: The PR number to check
        repo: Repository in "owner/repo" format
        use_cache: Whether to use cached PR data

    Returns:
        Dictionary with merge status information
    """
    if not repo:
        repo = get_repo_from_git()
        if not repo:
            raise ValueError("Could not determine repository.")

    fetcher = PRFetcher(repo, pr_number)
    pr_data = fetcher.fetch(use_cache=use_cache)
    analyzer = PRAnalyzer(pr_data)
    analysis = analyzer.analyze()

    return {
        "pr_number": pr_number,
        "repository": repo,
        "can_merge": analysis.can_merge(),
        "merge_status": analysis.get_merge_status(),
        "blocker_count": len(analysis.merge_blockers),
        "critical_count": len(analysis.critical_issues),
        "major_count": len(analysis.major_issues),
        "minor_count": len(analysis.minor_issues),
        "claude_comment_count": len(analysis.claude_issues),
        "total_comments": analysis.total_comments,
    }


def main():
    """CLI interface for Linear PR integration."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Get PR issues formatted for Linear ticket creation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Get all critical and major issues from PR #123
  %(prog)s 123

  # Get only Claude bot comments
  %(prog)s 123 --claude-only

  # Get critical issues and Claude comments only
  %(prog)s 123 --critical-only

  # Include minor issues
  %(prog)s 123 --include-minor

  # Get merge status summary
  %(prog)s 123 --status-only

  # Force fresh data (skip cache)
  %(prog)s 123 --no-cache
""",
    )

    parser.add_argument("pr_number", type=int, help="PR number to analyze")
    parser.add_argument(
        "--repo", help="Repository in owner/repo format (auto-detected if not provided)"
    )
    parser.add_argument(
        "--claude-only", action="store_true", help="Only include Claude bot comments"
    )
    parser.add_argument(
        "--critical-only",
        action="store_true",
        help="Only include critical issues and Claude comments",
    )
    parser.add_argument(
        "--include-minor", action="store_true", help="Include minor severity issues"
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Skip cache, fetch fresh data from GitHub",
    )
    parser.add_argument(
        "--status-only", action="store_true", help="Only output merge status summary"
    )
    parser.add_argument(
        "--format",
        choices=["json", "summary"],
        default="json",
        help="Output format (default: json)",
    )

    args = parser.parse_args()

    try:
        # Handle status-only mode
        if args.status_only:
            status = get_merge_status_for_linear(
                args.pr_number,
                repo=args.repo,
                use_cache=not args.no_cache,
            )
            if args.format == "json":
                print(json.dumps(status, indent=2))
            else:
                print(f"PR #{status['pr_number']} - {status['repository']}")
                print(f"Can Merge: {'Yes' if status['can_merge'] else 'No'}")
                print(f"Status: {status['merge_status']}")
                print(f"Blockers: {status['blocker_count']}")
                print(f"Critical: {status['critical_count']}")
                print(f"Major: {status['major_count']}")
                print(f"Minor: {status['minor_count']}")
                print(f"Claude Comments: {status['claude_comment_count']}")
            return

        # Get issues for Linear
        issues = get_pr_issues_for_linear(
            args.pr_number,
            repo=args.repo,
            include_claude=True,  # ALWAYS include Claude comments
            include_critical=not args.claude_only,
            include_major=not (args.claude_only or args.critical_only),
            include_minor=args.include_minor
            and not (args.claude_only or args.critical_only),
            use_cache=not args.no_cache,
        )

        if args.format == "json":
            print(json.dumps(issues, indent=2))
        else:
            print(f"Found {len(issues)} issues for Linear tickets:\n")
            for i, issue in enumerate(issues, 1):
                claude_marker = " [CLAUDE]" if issue["is_claude_comment"] else ""
                print(f"{i}. [{issue['severity'].upper()}]{claude_marker}")
                print(f"   Title: {issue['title']}")
                print(f"   Priority: {issue['priority']}")
                print(f"   Labels: {', '.join(issue['labels'])}")
                if issue.get("file_path"):
                    print(
                        f"   File: {issue['file_path']}:{issue.get('file_line', '?')}"
                    )
                print()

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
