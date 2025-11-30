#!/usr/bin/env python3
"""
PR Issue Collator - Python implementation with Pydantic models.

This module collates and categorizes PR review issues using type-safe
Pydantic models. It integrates with GitHub's GraphQL API to detect
resolved review threads and supports filtering by resolution status.

Features:
- Type-safe Pydantic models (PRIssue, CollatedIssues)
- Resolution detection via GitHub review threads
- Outdated detection (file changed after comment)
- --hide-resolved flag to filter resolved issues
- --show-status flag to display resolution indicators
- Compatible with existing bash collate-issues output format

Usage:
    # As CLI
    python collate_issues.py 33 --hide-resolved
    python collate_issues.py 33 --show-status --json

    # As module
    from collate_issues import collate_pr_issues
    issues = collate_pr_issues(33, hide_resolved=True)
    print(issues.get_summary())
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, TypedDict


SCRIPT_DIR = Path(__file__).parent

try:
    from models import (
        BotType,
        CollatedIssues,
        CommentSeverity,
        CommentStatus,
        PRComment,
        PRCommentSource,
        PRIssue,
        detect_bot_type,
    )
except ImportError:
    # Fallback for standalone execution
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    from models import (
        BotType,
        CollatedIssues,
        CommentSeverity,
        CommentStatus,
        PRComment,
        PRCommentSource,
        PRIssue,
        detect_bot_type,
    )


# =============================================================================
# Constants
# =============================================================================

# Maximum characters for issue description truncation
MAX_DESCRIPTION_LENGTH = 200


# =============================================================================
# Type Definitions
# =============================================================================


class ExtractedIssue(TypedDict):
    """Type-safe structure for issues extracted from comment bodies."""

    severity: CommentSeverity
    location: str
    summary: str


# =============================================================================
# Severity Detection Patterns
# =============================================================================

CRITICAL_PATTERNS = [
    r"## 🔴",
    r"### 🔴",
    r"### CRITICAL:",
    r"### Must Fix",
    r"## Must Fix",
    r"\*\*Must Fix\*\*",
    r"critical",
    r"security",
    r"vulnerability",
    r"data.?loss",
    r"crash",
    r"breaking.?change",
    r"blocker",
]

MAJOR_PATTERNS = [
    r"## ⚠️ Moderate",
    r"### ⚠️",
    r"### MAJOR:",
    r"### Should Fix",
    r"## Should Fix",
    r"\*\*Should Fix\*\*",
    r"## 🐛",
    r"## Issues & Concerns",
    r"## Areas for Improvement",
    r"major",
    r"bug",
    r"error",
    r"incorrect",
    r"performance",
    r"inconsistent",
    r"missing.*(test|validation|error.?handling)",
]

MINOR_PATTERNS = [
    r"## 💡 Suggestion",
    r"### 💡",
    r"### MINOR:",
    r"minor",
    r"suggestion",
    r"consider",
    r"could",
    r"might",
    r"nice.?to.?have",
    r"documentation",
    r"docstring",
]

NITPICK_PATTERNS = [
    r"nitpick",
    r"nit:",
    r"style",
    r"formatting",
    r"naming",
    r"cosmetic",
    r"optional",
]


def classify_severity(body: str) -> CommentSeverity:
    """
    Classify comment severity based on body content.

    Analyzes the comment body for severity indicator patterns (critical,
    major, minor, nitpick) and returns the appropriate severity level.

    Args:
        body: The comment body text to analyze for severity patterns.

    Returns:
        CommentSeverity enum value based on detected patterns.
        Returns UNCLASSIFIED if no patterns match.

    Example:
        >>> classify_severity("This is a critical security issue")
        CommentSeverity.CRITICAL
        >>> classify_severity("Consider renaming this variable")
        CommentSeverity.NITPICK
    """
    if not body:
        return CommentSeverity.UNCLASSIFIED

    # Check patterns in priority order (using re.IGNORECASE for case-insensitive matching)
    for pattern in CRITICAL_PATTERNS:
        if re.search(pattern, body, re.IGNORECASE):
            return CommentSeverity.CRITICAL

    for pattern in MAJOR_PATTERNS:
        if re.search(pattern, body, re.IGNORECASE):
            return CommentSeverity.MAJOR

    for pattern in MINOR_PATTERNS:
        if re.search(pattern, body, re.IGNORECASE):
            return CommentSeverity.MINOR

    for pattern in NITPICK_PATTERNS:
        if re.search(pattern, body, re.IGNORECASE):
            return CommentSeverity.NITPICK

    return CommentSeverity.UNCLASSIFIED


# =============================================================================
# Issue Extraction
# =============================================================================


def extract_issues_from_body(body: str, source: str = "") -> list[ExtractedIssue]:
    """
    Extract individual issues from a structured comment body.

    Looks for patterns like:
    - ### 1. **Title**
    - - [ ] Unchecked item
    - **N. Title (PRIORITY)**
    - ### CRITICAL: description

    Args:
        body: Comment body text.
        source: Location string like "[path:line]".

    Returns:
        List of ExtractedIssue dicts with {severity, location, summary}.
        Deduplicated by normalized summary text.
    """
    issues: list[ExtractedIssue] = []
    # Track seen summaries to prevent duplicate issues from multiple patterns
    seen_summaries: set[str] = set()

    def add_issue(severity: CommentSeverity, summary: str) -> None:
        """Add issue if not already seen (case-insensitive deduplication)."""
        normalized = summary.lower().strip()
        if normalized and normalized not in seen_summaries:
            seen_summaries.add(normalized)
            issues.append(
                ExtractedIssue(
                    severity=severity, location=source, summary=summary.strip()
                )
            )

    if not body:
        return issues

    # Pattern: ### N. **Title** (CodeRabbit/Claude structured format)
    numbered_bold = re.findall(r"### \d+\.\s*\*\*([^*]+)\*\*", body)
    for title in numbered_bold:
        severity = classify_severity(title)
        add_issue(severity, title)

    # Pattern: - [ ] Unchecked item (test plan items)
    unchecked = re.findall(r"- \[ \]\s*([^\n]+)", body)
    for item in unchecked:
        # Clean up status indicators
        item = re.sub(r"\s*[⚠️❌✅].*$", "", item)
        item = re.sub(r"\s*\(see issue[^)]*\)", "", item)
        item = item.strip()
        if item:
            add_issue(CommentSeverity.MAJOR, f"UNCHECKED: {item}")

    # Pattern: **N. Title (Priority)**
    priority_items = re.findall(r"\*\*\d+\.\s*([^(]+)\s*\(([^)]+)\)\*\*", body)
    for title, priority in priority_items:
        if "high" in priority.lower() or "critical" in priority.lower():
            severity = CommentSeverity.CRITICAL
        elif "medium" in priority.lower():
            severity = CommentSeverity.MAJOR
        elif "low" in priority.lower():
            severity = CommentSeverity.MINOR
        else:
            severity = CommentSeverity.MAJOR
        add_issue(severity, title)

    # Pattern: ### CRITICAL/MAJOR/MINOR: description
    for level, sev in [
        ("CRITICAL", CommentSeverity.CRITICAL),
        ("MAJOR", CommentSeverity.MAJOR),
        ("MINOR", CommentSeverity.MINOR),
    ]:
        matches = re.findall(rf"### {level}[:\s]+([^\n]+)", body, re.IGNORECASE)
        for desc in matches:
            add_issue(sev, desc)

    # Pattern: Risk items (High Risk: / Medium Risk: / Low Risk:)
    risk_patterns = [
        (r"High Risk[:\s]+([^\n]+)", CommentSeverity.MAJOR),
        (r"Medium Risk[:\s]+([^\n]+)", CommentSeverity.MINOR),
        (r"Low Risk[:\s]+([^\n]+)", CommentSeverity.NITPICK),
    ]
    for pattern, sev in risk_patterns:
        matches = re.findall(pattern, body)
        for desc in matches:
            add_issue(sev, desc)

    return issues


def is_claude_bot(author: str) -> bool:
    """Check if author is Claude Code bot.

    Uses detect_bot_type from models for consistent bot detection.

    Args:
        author: GitHub username to check.

    Returns:
        True if the author is identified as Claude Code bot.

    Example:
        >>> is_claude_bot("claude[bot]")
        True
        >>> is_claude_bot("octocat")
        False
    """
    return detect_bot_type(author) == BotType.CLAUDE_CODE


def is_coderabbit(author: str) -> bool:
    """Check if author is CodeRabbit bot.

    Uses detect_bot_type from models for consistent bot detection.

    Args:
        author: GitHub username to check.

    Returns:
        True if the author is identified as CodeRabbit bot.

    Example:
        >>> is_coderabbit("coderabbitai[bot]")
        True
        >>> is_coderabbit("github-actions[bot]")
        False
    """
    return detect_bot_type(author) == BotType.CODERABBIT


# =============================================================================
# Resolution Detection
# =============================================================================


def build_resolution_map(
    resolved_threads: list[dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    """
    Build a map of comment_id -> resolution info from resolved_threads.

    Args:
        resolved_threads: List of thread data from GraphQL API.

    Returns:
        Dict mapping comment database IDs to resolution info.
    """
    resolution_map: dict[int, dict[str, Any]] = {}

    for thread in resolved_threads:
        is_resolved = thread.get("is_resolved", False)
        is_outdated = thread.get("is_outdated", False)
        resolved_by = thread.get("resolved_by")

        # Map each comment in the thread
        comment_ids = thread.get("comment_ids", [])
        for cid in comment_ids:
            if cid:
                resolution_map[cid] = {
                    "is_resolved": is_resolved,
                    "is_outdated": is_outdated,
                    "resolved_by": resolved_by,
                    "path": thread.get("path"),
                    "line": thread.get("line"),
                }

    return resolution_map


def determine_comment_status(
    comment_id: Optional[int],
    resolution_map: dict[int, dict[str, Any]],
) -> tuple[CommentStatus, bool, Optional[str]]:
    """
    Determine comment resolution status from resolution map.

    Args:
        comment_id: GitHub comment database ID.
        resolution_map: Map from build_resolution_map().

    Returns:
        Tuple of (status, is_outdated, resolved_by).
    """
    if comment_id is None or comment_id not in resolution_map:
        return CommentStatus.UNADDRESSED, False, None

    info = resolution_map[comment_id]
    is_resolved = info.get("is_resolved", False)
    is_outdated = info.get("is_outdated", False)
    resolved_by = info.get("resolved_by")

    if is_outdated:
        return CommentStatus.OUTDATED, True, resolved_by
    if is_resolved:
        return CommentStatus.RESOLVED, False, resolved_by

    return CommentStatus.UNADDRESSED, False, None


# =============================================================================
# Main Collation Logic
# =============================================================================


def fetch_pr_data(pr_number: int) -> dict[str, Any]:
    """
    Fetch PR data using the fetch-pr-data script.

    Args:
        pr_number: PR number to fetch.

    Returns:
        Parsed JSON data from fetch-pr-data.

    Raises:
        RuntimeError: If fetch fails.
    """
    fetch_script = SCRIPT_DIR / "fetch-pr-data"

    try:
        result = subprocess.run(
            [str(fetch_script), str(pr_number)],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            raise RuntimeError(f"fetch-pr-data failed: {result.stderr}")

        if not result.stdout.strip():
            raise RuntimeError("fetch-pr-data returned empty output")

        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        raise RuntimeError("fetch-pr-data timed out")
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse fetch-pr-data output: {e}")


def get_repo_name() -> str:
    """Get repository name from git.

    Uses the GitHub CLI to retrieve the current repository's name with owner.

    Returns:
        Repository name in format "owner/repo", or empty string on failure.

    Example:
        >>> get_repo_name()  # In OmniNode-ai/omniclaude repo
        'OmniNode-ai/omniclaude'
    """
    try:
        result = subprocess.run(
            ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.SubprocessError, subprocess.TimeoutExpired, OSError, ValueError):
        pass
    return ""


def collate_pr_issues(
    pr_number: int,
    hide_resolved: bool = False,
    show_resolved_only: bool = False,
    include_nitpicks: bool = False,
) -> CollatedIssues:
    """
    Collate PR review issues with resolution detection.

    Args:
        pr_number: PR number to collate.
        hide_resolved: If True, exclude resolved issues.
        show_resolved_only: If True, only include resolved issues.
        include_nitpicks: If True, include nitpick issues (otherwise filtered).

    Returns:
        CollatedIssues instance with categorized issues.

    Raises:
        RuntimeError: If PR data fetch fails.
        ValueError: If both hide_resolved and show_resolved_only are True.
    """
    if hide_resolved and show_resolved_only:
        raise ValueError("Cannot use both hide_resolved and show_resolved_only")

    # Fetch PR data
    pr_data = fetch_pr_data(pr_number)

    # Build resolution map from resolved_threads
    resolved_threads = pr_data.get("resolved_threads", [])
    resolution_map = build_resolution_map(resolved_threads)

    # Collect all issues
    all_issues: list[PRIssue] = []

    # Process each comment source
    comment_sources = [
        ("reviews", "body"),
        ("inline_comments", "body"),
        ("pr_comments", "body"),
        ("issue_comments", "body"),
    ]

    for source_key, body_key in comment_sources:
        comments = pr_data.get(source_key, [])
        if not isinstance(comments, list):
            continue

        for comment in comments:
            if not isinstance(comment, dict):
                continue

            body = comment.get(body_key, "")
            if not body:
                continue

            # Skip addressed comments
            if body.strip().startswith("Addressed"):
                continue

            # Skip positive feedback
            positive_patterns = [
                r"^✅",
                r"^✔",
                r"excellent",
                r"great job",
                r"looks good",
                r"lgtm",
                r"approved",
            ]
            if any(re.search(p, body, re.IGNORECASE) for p in positive_patterns):
                continue

            author = comment.get("author", "")
            comment_id = comment.get("id")
            path = comment.get("path", "")
            line = comment.get("line")

            # Determine location string
            location = ""
            if path:
                if line:
                    location = f"[{path}:{line}]"
                else:
                    location = f"[{path}]"

            # Get resolution status
            status, is_outdated, resolved_by = determine_comment_status(
                comment_id, resolution_map
            )

            # Check if this is a structured bot comment
            if is_claude_bot(author) or is_coderabbit(author):
                # Extract structured issues from bot comments
                extracted = extract_issues_from_body(body, location)
                for item in extracted:
                    issue = PRIssue(
                        file_path=path,
                        line_number=line,
                        severity=item["severity"],
                        description=item["summary"],
                        status=status,
                        comment_id=comment_id,
                        is_outdated=is_outdated,
                        resolved_by=resolved_by,
                    )
                    all_issues.append(issue)
            else:
                # Single issue from human comment
                severity = classify_severity(body)

                # Extract first meaningful line as summary
                lines = body.strip().split("\n")
                summary = ""
                for line_text in lines:
                    line_text = line_text.strip()
                    if (
                        line_text
                        and not line_text.startswith("#")
                        and not line_text.startswith("<!--")
                    ):
                        summary = line_text[:MAX_DESCRIPTION_LENGTH]
                        break

                if not summary or len(summary) < 10:
                    continue

                # Skip HTML comments
                if summary.startswith("<!--") and summary.endswith("-->"):
                    continue

                issue = PRIssue(
                    file_path=path,
                    line_number=line if isinstance(line, int) else None,
                    severity=severity,
                    description=summary,
                    status=status,
                    comment_id=comment_id,
                    is_outdated=is_outdated,
                    resolved_by=resolved_by,
                )
                all_issues.append(issue)

    # Deduplicate by description (keep first occurrence)
    seen_descriptions: set[str] = set()
    unique_issues: list[PRIssue] = []
    for issue in all_issues:
        key = f"{issue.location}|{issue.description}"
        if key not in seen_descriptions:
            seen_descriptions.add(key)
            unique_issues.append(issue)

    # Categorize by severity
    critical: list[PRIssue] = []
    major: list[PRIssue] = []
    minor: list[PRIssue] = []
    nitpick: list[PRIssue] = []
    unclassified: list[PRIssue] = []

    for issue in unique_issues:
        if issue.severity == CommentSeverity.CRITICAL:
            critical.append(issue)
        elif issue.severity == CommentSeverity.MAJOR:
            major.append(issue)
        elif issue.severity == CommentSeverity.MINOR:
            minor.append(issue)
        elif issue.severity == CommentSeverity.NITPICK:
            nitpick.append(issue)
        else:
            unclassified.append(issue)

    # Build CollatedIssues
    result = CollatedIssues(
        pr_number=pr_number,
        repository=get_repo_name(),
        collated_at=datetime.now(),
        critical=critical,
        major=major,
        minor=minor,
        nitpick=nitpick if include_nitpicks else [],
        unclassified=unclassified,
    )

    # Apply resolution filter
    if hide_resolved or show_resolved_only:
        result = result.filter_by_status(
            hide_resolved=hide_resolved,
            show_resolved_only=show_resolved_only,
        )

    return result


# =============================================================================
# Output Formatting
# =============================================================================


def format_issues_human(
    issues: CollatedIssues,
    show_status: bool = True,
    include_nitpicks: bool = False,
) -> str:
    """Format issues for human-readable output.

    Generates a prioritized list of issues grouped by severity with optional
    resolution status indicators.

    Args:
        issues: CollatedIssues instance containing categorized issues.
        show_status: If True, include [RESOLVED]/[OUTDATED] indicators.
        include_nitpicks: If True, include nitpick-level issues.

    Returns:
        Formatted string suitable for terminal display.

    Example:
        >>> output = format_issues_human(issues, show_status=True)
        >>> print(output)
        PR #40 Issues - Prioritized

        :red_circle: CRITICAL (1):
        1. [RESOLVED] Missing test coverage
    """
    lines: list[str] = []

    lines.append(f"PR #{issues.pr_number} Issues - Prioritized")
    lines.append("")

    # Critical
    if issues.critical:
        lines.append(f"🔴 CRITICAL ({len(issues.critical)}):")
        for i, issue in enumerate(issues.critical, 1):
            status = (
                f" {issue.status_indicator}"
                if show_status and issue.status_indicator
                else ""
            )
            loc = f" {issue.location}" if issue.location else ""
            lines.append(f"{i}.{status}{loc} {issue.description}")
        lines.append("")

    # Major
    if issues.major:
        lines.append(f"🟠 MAJOR ({len(issues.major)}):")
        for i, issue in enumerate(issues.major, 1):
            status = (
                f" {issue.status_indicator}"
                if show_status and issue.status_indicator
                else ""
            )
            loc = f" {issue.location}" if issue.location else ""
            lines.append(f"{i}.{status}{loc} {issue.description}")
        lines.append("")

    # Minor
    if issues.minor:
        lines.append(f"🟡 MINOR ({len(issues.minor)}):")
        for i, issue in enumerate(issues.minor, 1):
            status = (
                f" {issue.status_indicator}"
                if show_status and issue.status_indicator
                else ""
            )
            loc = f" {issue.location}" if issue.location else ""
            lines.append(f"{i}.{status}{loc} {issue.description}")
        lines.append("")

    # Nitpicks (if included)
    if include_nitpicks and issues.nitpick:
        lines.append(f"⚪ NITPICK ({len(issues.nitpick)}):")
        for i, issue in enumerate(issues.nitpick, 1):
            status = (
                f" {issue.status_indicator}"
                if show_status and issue.status_indicator
                else ""
            )
            loc = f" {issue.location}" if issue.location else ""
            lines.append(f"{i}.{status}{loc} {issue.description}")
        lines.append("")

    # Unclassified
    if issues.unclassified:
        lines.append(f"❓ UNMATCHED ({len(issues.unclassified)}) - Review manually:")
        for i, issue in enumerate(issues.unclassified, 1):
            status = (
                f" {issue.status_indicator}"
                if show_status and issue.status_indicator
                else ""
            )
            loc = f" {issue.location}" if issue.location else ""
            lines.append(f"{i}.{status}{loc} {issue.description}")
        lines.append("")

    # Summary
    lines.append(issues.get_summary(include_nitpicks=include_nitpicks))

    # Resolution stats
    if issues.resolved_count > 0:
        lines.append(
            f"Resolution: {issues.resolved_count} resolved, {issues.open_count} open"
        )

    return "\n".join(lines)


def format_issues_json(issues: CollatedIssues) -> str:
    """Format issues as JSON output.

    Serializes the CollatedIssues model to JSON with indentation.

    Args:
        issues: CollatedIssues instance to serialize.

    Returns:
        JSON string representation of the issues.

    Example:
        >>> json_output = format_issues_json(issues)
        >>> data = json.loads(json_output)
        >>> data["pr_number"]
        40
    """
    return issues.model_dump_json(indent=2)


# =============================================================================
# CLI Entry Point
# =============================================================================


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Collate PR review issues with resolution detection",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python collate_issues.py 33                    # All issues
  python collate_issues.py 33 --hide-resolved    # Only open issues
  python collate_issues.py 33 --show-resolved-only  # Only resolved
  python collate_issues.py 33 --show-status      # Show [RESOLVED] indicators
  python collate_issues.py 33 --json             # JSON output
        """,
    )

    parser.add_argument("pr_number", type=int, help="PR number")
    parser.add_argument(
        "--hide-resolved",
        action="store_true",
        help="Hide issues that have been resolved on GitHub",
    )
    parser.add_argument(
        "--show-resolved-only",
        action="store_true",
        help="Only show resolved issues",
    )
    parser.add_argument(
        "--no-status",
        dest="show_status",
        action="store_false",
        default=True,
        help="Hide resolution status indicators",
    )
    parser.add_argument(
        "--include-nitpicks",
        action="store_true",
        help="Include nitpick issues in output",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )

    args = parser.parse_args()

    # Validate conflicting options
    if args.hide_resolved and args.show_resolved_only:
        print(
            "ERROR: Cannot use both --hide-resolved and --show-resolved-only",
            file=sys.stderr,
        )
        return 1

    try:
        issues = collate_pr_issues(
            args.pr_number,
            hide_resolved=args.hide_resolved,
            show_resolved_only=args.show_resolved_only,
            include_nitpicks=args.include_nitpicks,
        )

        if args.json:
            print(format_issues_json(issues))
        else:
            show_status = args.show_status
            print(
                format_issues_human(
                    issues,
                    show_status=show_status,
                    include_nitpicks=args.include_nitpicks,
                )
            )

        return 0

    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
