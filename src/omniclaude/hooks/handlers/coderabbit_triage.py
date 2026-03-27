# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""CodeRabbit review thread auto-triage handler.

Reads CodeRabbit review threads on a PR, classifies severity, and auto-replies
to Minor/Nitpick threads with an acknowledgment + resolves them. Major/Critical
threads are left for substantive fixes.

Design constraints:
    - Uses `gh` CLI for all GitHub API interactions (no PAT required).
    - Never blocks Claude Code — always exits 0.
    - All Pydantic models use frozen=True and extra="forbid".
    - No datetime.now() defaults — timestamps injected by callers.

Related:
    - OMN-6739: CodeRabbit thread auto-triage hook
    - plugins/onex/skills/_lib/pr_review/models.py: CommentSeverity, CODERABBIT_PATTERNS
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

# CodeRabbit severity markers found in review comments.
# CodeRabbit uses markdown headers like "🔴 Critical", "🟡 Minor", etc.
_SEVERITY_PATTERNS: dict[str, list[str]] = {
    "critical": [
        r"\bcritical\b",
        r"🔴",
        r"\[critical\]",
        r"severity:\s*critical",
    ],
    "major": [
        r"\bmajor\b",
        r"🟠",
        r"\[major\]",
        r"severity:\s*major",
        r"\bimportant\b",
    ],
    "minor": [
        r"\bminor\b",
        r"🟡",
        r"\[minor\]",
        r"severity:\s*minor",
        r"\bsuggestion\b",
    ],
    "nitpick": [
        r"\bnitpick\b",
        r"\bnit\b",
        r"🟢",
        r"\[nitpick\]",
        r"severity:\s*nitpick",
        r"\bstyle\b",
        r"\bnaming\b",
    ],
}

# Auto-reply template for Minor/Nitpick threads.
_ACK_REPLY = (
    "Acknowledged — tracking in tech-debt backlog. "
    "This is a minor/nitpick finding that does not block merge. "
    "Auto-triaged by CodeRabbit auto-triage hook [OMN-6739]."
)


# =============================================================================
# Enums
# =============================================================================


class EnumTriageSeverity(str, Enum):
    """Severity classification for CodeRabbit review threads."""

    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"
    NITPICK = "nitpick"
    UNKNOWN = "unknown"


class EnumTriageAction(str, Enum):
    """Action taken on a CodeRabbit review thread."""

    AUTO_REPLIED = "auto_replied"
    SKIPPED_REQUIRES_FIX = "skipped_requires_fix"
    SKIPPED_ALREADY_RESOLVED = "skipped_already_resolved"
    SKIPPED_NOT_CODERABBIT = "skipped_not_coderabbit"
    ERROR = "error"


# =============================================================================
# Models
# =============================================================================


class ModelTriagedThread(BaseModel):
    """Result of triaging a single CodeRabbit review thread."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    comment_id: int = Field(..., description="GitHub comment ID")
    thread_id: int | None = Field(
        None, description="Review thread ID (for inline comments)"
    )
    body_preview: str = Field(
        ..., max_length=200, description="First 200 chars of comment body"
    )
    severity: EnumTriageSeverity = Field(..., description="Classified severity")
    action: EnumTriageAction = Field(..., description="Action taken")
    reply_posted: bool = Field(False, description="Whether an auto-reply was posted")
    thread_resolved: bool = Field(False, description="Whether the thread was resolved")
    error: str | None = Field(None, description="Error message if action failed")


class ModelTriageReport(BaseModel):
    """Summary report of CodeRabbit auto-triage for a PR."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    repo: str = Field(..., description="GitHub repo (owner/name)")
    pr_number: int = Field(..., description="PR number")
    triaged_at: datetime = Field(..., description="When triage was performed")
    total_coderabbit_threads: int = Field(
        0, description="Total CodeRabbit threads found"
    )
    auto_replied: int = Field(0, description="Threads auto-replied and resolved")
    requires_fix: int = Field(0, description="Threads requiring substantive fixes")
    already_resolved: int = Field(0, description="Threads already resolved")
    errors: int = Field(0, description="Threads where triage failed")
    threads: list[ModelTriagedThread] = Field(
        default_factory=list, description="Per-thread triage results"
    )


# =============================================================================
# Severity classification
# =============================================================================


def classify_severity(body: str) -> EnumTriageSeverity:
    """Classify the severity of a CodeRabbit review comment.

    Scans the comment body for severity markers. If multiple severities
    match, returns the highest (most severe).

    Args:
        body: The full text of the CodeRabbit review comment.

    Returns:
        Classified severity level.
    """
    if not body:
        return EnumTriageSeverity.UNKNOWN

    body_lower = body.lower()

    # Check in priority order (highest severity first)
    for severity_name in ["critical", "major", "minor", "nitpick"]:
        patterns = _SEVERITY_PATTERNS[severity_name]
        for pattern in patterns:
            if re.search(pattern, body_lower):
                return EnumTriageSeverity(severity_name)

    return EnumTriageSeverity.UNKNOWN


def is_auto_triageable(severity: EnumTriageSeverity) -> bool:
    """Check if a severity level qualifies for auto-triage (auto-reply + resolve).

    Only Minor and Nitpick threads are auto-triaged. Critical and Major
    require substantive fixes.

    Args:
        severity: The classified severity.

    Returns:
        True if the thread can be auto-triaged.
    """
    return severity in (EnumTriageSeverity.MINOR, EnumTriageSeverity.NITPICK)


# =============================================================================
# GitHub API helpers (via gh CLI)
# =============================================================================


def _run_gh(args: list[str], *, timeout: int = 30) -> str:
    """Run a gh CLI command and return stdout.

    Args:
        args: Arguments to pass to `gh`.
        timeout: Command timeout in seconds.

    Returns:
        Command stdout as string.

    Raises:
        subprocess.CalledProcessError: If the command fails.
    """
    result = subprocess.run(  # noqa: S603 — gh CLI is trusted
        ["gh", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, ["gh", *args], result.stdout, result.stderr
        )
    return result.stdout


def fetch_coderabbit_comments(repo: str, pr_number: int) -> list[dict[str, object]]:
    """Fetch all CodeRabbit review comments on a PR.

    Fetches from both the reviews endpoint and the issue comments endpoint
    to catch all CodeRabbit threads.

    Args:
        repo: GitHub repo in "owner/name" format.
        pr_number: PR number.

    Returns:
        List of comment dicts with keys: id, body, author, path, isResolved.
    """
    comments: list[dict[str, object]] = []

    # Fetch inline review comments (code-level threads)
    try:
        raw = _run_gh(
            [
                "api",
                f"repos/{repo}/pulls/{pr_number}/comments",
                "--paginate",
                "--jq",
                '.[] | select(.user.login | test("coderabbit"; "i")) '
                "| {id: .id, body: .body, author: .user.login, "
                "path: .path, in_reply_to_id: .in_reply_to_id}",
            ]
        )
        for line in raw.strip().splitlines():
            if line.strip():
                comments.append(json.loads(line))
    except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        logger.warning("Failed to fetch inline comments: %s", exc)

    # Fetch issue comments (PR conversation thread)
    try:
        raw = _run_gh(
            [
                "api",
                f"repos/{repo}/issues/{pr_number}/comments",
                "--paginate",
                "--jq",
                '.[] | select(.user.login | test("coderabbit"; "i")) '
                "| {id: .id, body: .body, author: .user.login, "
                "path: null, in_reply_to_id: null}",
            ]
        )
        for line in raw.strip().splitlines():
            if line.strip():
                comments.append(json.loads(line))
    except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        logger.warning("Failed to fetch issue comments: %s", exc)

    # Fetch review threads to check resolution status
    try:
        raw = _run_gh(
            [
                "pr",
                "view",
                str(pr_number),
                "--repo",
                repo,
                "--json",
                "reviewThreads",
                "--jq",
                ".reviewThreads[] "
                '| select(.comments[0].author.login | test("coderabbit"; "i")) '
                "| {thread_id: .id, isResolved: .isResolved, "
                "comment_id: .comments[0].databaseId}",
            ]
        )
        thread_map: dict[int, dict[str, object]] = {}
        for line in raw.strip().splitlines():
            if line.strip():
                thread_data = json.loads(line)
                cid = thread_data.get("comment_id")
                if cid is not None:
                    thread_map[int(cid)] = thread_data

        # Enrich comments with thread resolution status
        for comment in comments:
            cid = comment.get("id")
            if cid is not None and int(str(cid)) in thread_map:
                td = thread_map[int(str(cid))]
                comment["isResolved"] = td.get("isResolved", False)
                comment["thread_id"] = td.get("thread_id")
            else:
                comment.setdefault("isResolved", False)
                comment.setdefault("thread_id", None)
    except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        logger.warning("Failed to fetch review threads: %s", exc)
        for comment in comments:
            comment.setdefault("isResolved", False)
            comment.setdefault("thread_id", None)

    return comments


def post_reply(
    repo: str,
    pr_number: int,
    comment_id: int,
    body: str,
    *,
    is_inline: bool = True,
) -> bool:
    """Post a reply to a review comment.

    Args:
        repo: GitHub repo in "owner/name" format.
        pr_number: The PR number.
        comment_id: The comment ID to reply to.
        body: Reply body text.
        is_inline: Whether this is an inline review comment (vs issue comment).

    Returns:
        True if the reply was posted successfully.
    """
    try:
        if is_inline:
            _run_gh(
                [
                    "api",
                    f"repos/{repo}/pulls/{pr_number}/comments/{comment_id}/replies",
                    "-f",
                    f"body={body}",
                ]
            )
        else:
            _run_gh(
                [
                    "api",
                    f"repos/{repo}/issues/{pr_number}/comments",
                    "-f",
                    f"body={body}",
                ]
            )
        return True
    except subprocess.CalledProcessError as exc:
        logger.warning("Failed to post reply to comment %d: %s", comment_id, exc)
        return False


def resolve_thread(repo: str, thread_id: str) -> bool:
    """Resolve a review thread via the GraphQL API.

    Args:
        repo: GitHub repo in "owner/name" format.
        thread_id: The GraphQL node ID of the review thread.

    Returns:
        True if the thread was resolved successfully.
    """
    try:
        _run_gh(
            [
                "api",
                "graphql",
                "-f",
                f'query=mutation {{ resolveReviewThread(input: {{threadId: "{thread_id}"}}) {{ thread {{ isResolved }} }} }}',
            ]
        )
        return True
    except subprocess.CalledProcessError as exc:
        logger.warning("Failed to resolve thread %s: %s", thread_id, exc)
        return False


# =============================================================================
# Main triage logic
# =============================================================================


def triage_pr(
    repo: str,
    pr_number: int,
    *,
    dry_run: bool = False,
    triaged_at: datetime | None = None,
) -> ModelTriageReport:
    """Auto-triage all CodeRabbit review threads on a PR.

    Fetches all CodeRabbit comments, classifies severity, and auto-replies
    to Minor/Nitpick threads. Major/Critical threads are left untouched.

    Args:
        repo: GitHub repo in "owner/name" format.
        pr_number: PR number.
        dry_run: If True, classify but don't post replies or resolve threads.
        triaged_at: Timestamp for the triage report. Defaults to now(UTC).

    Returns:
        ModelTriageReport with per-thread results.
    """
    if triaged_at is None:
        triaged_at = datetime.now(UTC)

    comments = fetch_coderabbit_comments(repo, pr_number)

    # Filter to root comments only (skip replies from CodeRabbit)
    root_comments = [c for c in comments if c.get("in_reply_to_id") is None]

    threads: list[ModelTriagedThread] = []
    auto_replied = 0
    requires_fix = 0
    already_resolved = 0
    errors = 0

    for comment in root_comments:
        comment_id = int(str(comment["id"]))
        body = str(comment.get("body", ""))
        is_resolved = bool(comment.get("isResolved", False))
        thread_id_raw = comment.get("thread_id")
        has_path = comment.get("path") is not None

        severity = classify_severity(body)

        _tid = int(str(thread_id_raw)) if thread_id_raw else None

        if is_resolved:
            threads.append(
                ModelTriagedThread(
                    comment_id=comment_id,
                    thread_id=_tid,
                    body_preview=body[:200],
                    severity=severity,
                    action=EnumTriageAction.SKIPPED_ALREADY_RESOLVED,
                    reply_posted=False,
                    thread_resolved=False,
                    error=None,
                )
            )
            already_resolved += 1
            continue

        if is_auto_triageable(severity):
            if dry_run:
                threads.append(
                    ModelTriagedThread(
                        comment_id=comment_id,
                        thread_id=_tid,
                        body_preview=body[:200],
                        severity=severity,
                        action=EnumTriageAction.AUTO_REPLIED,
                        reply_posted=False,
                        thread_resolved=False,
                        error=None,
                    )
                )
                auto_replied += 1
                continue

            # Post acknowledgment reply
            reply_ok = post_reply(
                repo, pr_number, comment_id, _ACK_REPLY, is_inline=has_path
            )

            # Resolve the thread if it has a thread ID
            resolved_ok = False
            if reply_ok and thread_id_raw:
                resolved_ok = resolve_thread(repo, str(thread_id_raw))

            if reply_ok:
                threads.append(
                    ModelTriagedThread(
                        comment_id=comment_id,
                        thread_id=_tid,
                        body_preview=body[:200],
                        severity=severity,
                        action=EnumTriageAction.AUTO_REPLIED,
                        reply_posted=True,
                        thread_resolved=resolved_ok,
                        error=None,
                    )
                )
                auto_replied += 1
            else:
                threads.append(
                    ModelTriagedThread(
                        comment_id=comment_id,
                        thread_id=_tid,
                        body_preview=body[:200],
                        severity=severity,
                        action=EnumTriageAction.ERROR,
                        reply_posted=False,
                        thread_resolved=False,
                        error="Failed to post reply",
                    )
                )
                errors += 1
        else:
            threads.append(
                ModelTriagedThread(
                    comment_id=comment_id,
                    thread_id=_tid,
                    body_preview=body[:200],
                    severity=severity,
                    action=EnumTriageAction.SKIPPED_REQUIRES_FIX,
                    reply_posted=False,
                    thread_resolved=False,
                    error=None,
                )
            )
            requires_fix += 1

    return ModelTriageReport(
        repo=repo,
        pr_number=pr_number,
        triaged_at=triaged_at,
        total_coderabbit_threads=len(root_comments),
        auto_replied=auto_replied,
        requires_fix=requires_fix,
        already_resolved=already_resolved,
        errors=errors,
        threads=threads,
    )


# =============================================================================
# CLI entry point
# =============================================================================


def main() -> None:
    """CLI entry point for CodeRabbit auto-triage.

    Usage:
        python -m omniclaude.hooks.handlers.coderabbit_triage <repo> <pr_number> [--dry-run]

    Outputs JSON triage report to stdout.
    """
    if len(sys.argv) < 3:
        sys.stderr.write(
            "Usage: python -m omniclaude.hooks.handlers.coderabbit_triage "
            "<repo> <pr_number> [--dry-run]\n"
        )
        sys.exit(1)

    repo = sys.argv[1]
    pr_number = int(sys.argv[2])
    dry_run = "--dry-run" in sys.argv

    report = triage_pr(repo, pr_number, dry_run=dry_run)
    sys.stdout.write(report.model_dump_json(indent=2) + "\n")


if __name__ == "__main__":
    main()
