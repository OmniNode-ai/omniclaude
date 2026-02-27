# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Inbox check backend.

Checks notifications and review requests for the authenticated user
across a specific repository. Uses `gh` API to query notifications
and review requests.
"""

from __future__ import annotations

import json
from typing import Any

from .base import (
    ScriptStatus,
    SkillScriptResult,
    make_meta,
    run_gh,
    script_main,
)


def _run(
    repo_slug: str, run_id: str, args: dict[str, Any]
) -> tuple[
    ScriptStatus,
    SkillScriptResult,
    str,
]:
    """Check inbox notifications and review requests."""
    meta = make_meta("inbox_check", run_id, repo_slug)

    # Fetch review requests assigned to the authenticated user
    review_result = run_gh(
        [
            "pr",
            "list",
            "--repo",
            repo_slug,
            "--search",
            "review-requested:@me",
            "--state",
            "open",
            "--json",
            "number,title,headRefName,author,createdAt,updatedAt",
            "--limit",
            "20",
        ]
    )
    review_prs = (
        json.loads(review_result.stdout) if review_result.stdout.strip() else []
    )

    # Fetch PRs authored by the authenticated user (for tracking)
    my_result = run_gh(
        [
            "pr",
            "list",
            "--repo",
            repo_slug,
            "--author",
            "@me",
            "--state",
            "open",
            "--json",
            "number,title,headRefName,reviewDecision,statusCheckRollup,createdAt",
            "--limit",
            "20",
        ]
    )
    my_prs = json.loads(my_result.stdout) if my_result.stdout.strip() else []

    # Parse review requests
    parsed_reviews = [
        {
            "number": pr.get("number"),
            "title": pr.get("title", ""),
            "branch": pr.get("headRefName", ""),
            "author": (pr.get("author") or {}).get("login", "unknown"),
            "created_at": pr.get("createdAt", ""),
        }
        for pr in review_prs
    ]

    # Parse my PRs with status
    parsed_my_prs = [
        {
            "number": pr.get("number"),
            "title": pr.get("title", ""),
            "branch": pr.get("headRefName", ""),
            "review_decision": pr.get("reviewDecision", "PENDING"),
            "ci_status": _summarize_ci(pr.get("statusCheckRollup") or []),
        }
        for pr in my_prs
    ]

    # Count PRs needing attention
    needs_attention = len(review_prs)
    my_approved = sum(1 for pr in my_prs if pr.get("reviewDecision") == "APPROVED")
    my_changes_requested = sum(
        1 for pr in my_prs if pr.get("reviewDecision") == "CHANGES_REQUESTED"
    )

    script_result = SkillScriptResult(
        meta=meta,
        inputs={"repo": repo_slug},
        parsed={
            "review_requests": parsed_reviews,
            "my_prs": parsed_my_prs,
        },
        summary={
            "review_requests_count": needs_attention,
            "my_open_prs": len(my_prs),
            "my_approved": my_approved,
            "my_changes_requested": my_changes_requested,
            "action_needed": needs_attention > 0 or my_changes_requested > 0,
        },
    )

    parts = []
    if needs_attention > 0:
        parts.append(f"{needs_attention} review requests")
    if my_changes_requested > 0:
        parts.append(f"{my_changes_requested} PRs need fixes")
    if my_approved > 0:
        parts.append(f"{my_approved} PRs ready to merge")

    if not parts:
        msg = "Inbox clear -- no action needed"
        status = ScriptStatus.OK
    else:
        msg = "; ".join(parts)
        status = ScriptStatus.WARN if my_changes_requested > 0 else ScriptStatus.OK

    return status, script_result, msg


def _summarize_ci(rollup: list[dict[str, Any]]) -> str:
    """Summarize CI status from statusCheckRollup."""
    if not rollup:
        return "none"
    conclusions = [c.get("conclusion") or c.get("status", "") for c in rollup]
    if all(s == "SUCCESS" for s in conclusions if s):
        return "passing"
    if any(s in ("FAILURE", "ERROR", "CANCELLED") for s in conclusions):
        return "failing"
    return "pending"


def main() -> None:
    script_main("inbox_check", _run)


if __name__ == "__main__":
    main()
