# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""PR scanning backend.

Lists open PRs for a repository with status summary.
Uses `gh pr list` to fetch PR data.
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
    """Scan open PRs for a repository."""
    meta = make_meta("pr_scan", run_id, repo_slug)

    # Fetch open PRs with key fields
    result = run_gh(
        [
            "pr",
            "list",
            "--repo",
            repo_slug,
            "--state",
            "open",
            "--json",
            "number,title,headRefName,author,createdAt,updatedAt,isDraft,reviewDecision,mergeable,statusCheckRollup",
            "--limit",
            "50",
        ]
    )

    prs = json.loads(result.stdout) if result.stdout.strip() else []

    # Parse into summary
    total = len(prs)
    drafts = sum(1 for pr in prs if pr.get("isDraft", False))
    approved = sum(1 for pr in prs if pr.get("reviewDecision") == "APPROVED")
    changes_requested = sum(
        1 for pr in prs if pr.get("reviewDecision") == "CHANGES_REQUESTED"
    )
    pending_review = total - approved - changes_requested - drafts

    # Check CI status per PR
    ci_passing = 0
    ci_failing = 0
    ci_pending = 0
    for pr in prs:
        rollup = pr.get("statusCheckRollup") or []
        if not rollup:
            ci_pending += 1
            continue
        states = [c.get("conclusion") or c.get("status", "") for c in rollup]
        if all(s == "SUCCESS" for s in states if s):
            ci_passing += 1
        elif any(s in ("FAILURE", "ERROR", "CANCELLED") for s in states):
            ci_failing += 1
        else:
            ci_pending += 1

    # Build parsed list (safe for logging -- no tokens)
    parsed_prs = [
        {
            "number": pr.get("number"),
            "title": pr.get("title", ""),
            "branch": pr.get("headRefName", ""),
            "author": (pr.get("author") or {}).get("login", "unknown"),
            "is_draft": pr.get("isDraft", False),
            "review_decision": pr.get("reviewDecision", "PENDING"),
            "mergeable": pr.get("mergeable", "UNKNOWN"),
        }
        for pr in prs
    ]

    script_result = SkillScriptResult(
        meta=meta,
        inputs={"repo": repo_slug, "state": "open", "limit": 50},
        parsed={"prs": parsed_prs},
        summary={
            "total_open": total,
            "drafts": drafts,
            "approved": approved,
            "changes_requested": changes_requested,
            "pending_review": pending_review,
            "ci_passing": ci_passing,
            "ci_failing": ci_failing,
            "ci_pending": ci_pending,
        },
    )

    status = ScriptStatus.OK if ci_failing == 0 else ScriptStatus.WARN
    msg = (
        f"{total} open PRs: {approved} approved, "
        f"{ci_failing} CI failing, {drafts} draft"
    )

    return status, script_result, msg


def main() -> None:
    script_main("pr_scan", _run)


if __name__ == "__main__":
    main()
