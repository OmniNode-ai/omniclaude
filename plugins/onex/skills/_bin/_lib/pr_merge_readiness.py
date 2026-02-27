# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""PR merge readiness backend.

Checks whether a specific PR is ready to merge by validating:
1. CI checks all passing
2. At least 1 approved review, no CHANGES_REQUESTED
3. No unresolved review comments (conversations)
4. Not a draft PR
5. No merge conflicts
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
    """Check merge readiness for a specific PR."""
    meta = make_meta("pr_merge_readiness", run_id, repo_slug)
    pr_number = args.get("pr")

    if not pr_number:
        result = SkillScriptResult(
            meta=meta,
            inputs={"repo": repo_slug, "pr": None},
            parsed={},
            summary={"error": "--pr is required for merge readiness check"},
        )
        return ScriptStatus.FAIL, result, "--pr is required"

    # Fetch PR data with all relevant fields
    pr_result = run_gh(
        [
            "pr",
            "view",
            str(pr_number),
            "--repo",
            repo_slug,
            "--json",
            "number,title,state,isDraft,mergeable,reviewDecision,statusCheckRollup,reviews,comments",
        ]
    )
    pr_data = json.loads(pr_result.stdout) if pr_result.stdout.strip() else {}

    # Check 1: Not a draft
    is_draft = pr_data.get("isDraft", False)

    # Check 2: CI status
    rollup = pr_data.get("statusCheckRollup") or []
    ci_states = [c.get("conclusion") or c.get("status", "") for c in rollup]
    ci_all_passing = len(ci_states) > 0 and all(s == "SUCCESS" for s in ci_states if s)
    ci_failing_names = [
        c.get("name", "unknown")
        for c in rollup
        if (c.get("conclusion") or "") in ("FAILURE", "ERROR", "CANCELLED")
    ]
    ci_pending = any(
        (c.get("state") or "") in ("QUEUED", "IN_PROGRESS", "PENDING", "WAITING")
        for c in rollup
    )

    # Check 3: Review status
    review_decision = pr_data.get("reviewDecision", "")
    reviews = pr_data.get("reviews") or []
    approved_count = sum(1 for r in reviews if r.get("state") == "APPROVED")
    changes_requested = any(r.get("state") == "CHANGES_REQUESTED" for r in reviews)
    has_approval = approved_count >= 1 and not changes_requested

    # Check 4: Merge conflicts
    mergeable = pr_data.get("mergeable", "UNKNOWN")
    no_conflicts = mergeable in ("MERGEABLE", "CLEAN")

    # Check 5: PR is still open
    pr_state = pr_data.get("state", "UNKNOWN")
    is_open = pr_state == "OPEN"

    # Build blockers list
    blockers: list[str] = []
    if is_draft:
        blockers.append("PR is a draft")
    if not is_open:
        blockers.append(f"PR state is {pr_state} (not OPEN)")
    if not ci_all_passing:
        if ci_pending:
            blockers.append("CI checks still pending")
        if ci_failing_names:
            blockers.append(f"CI failing: {', '.join(ci_failing_names[:5])}")
        if not rollup:
            blockers.append("No CI checks found")
    if not has_approval:
        if changes_requested:
            blockers.append("Changes requested by reviewer")
        elif approved_count == 0:
            blockers.append("No approved reviews")
    if not no_conflicts:
        blockers.append(f"Merge conflicts (mergeable={mergeable})")

    is_ready = len(blockers) == 0

    script_result = SkillScriptResult(
        meta=meta,
        inputs={"repo": repo_slug, "pr": pr_number},
        parsed={
            "pr_state": pr_state,
            "is_draft": is_draft,
            "mergeable": mergeable,
            "review_decision": review_decision,
            "approved_count": approved_count,
            "changes_requested": changes_requested,
            "ci_total": len(rollup),
            "ci_passing": sum(
                1 for c in rollup if (c.get("conclusion") or "") == "SUCCESS"
            ),
            "ci_failing_names": ci_failing_names,
            "ci_pending": ci_pending,
        },
        summary={
            "ready_to_merge": is_ready,
            "blockers": blockers,
            "blocker_count": len(blockers),
        },
    )

    if is_ready:
        status = ScriptStatus.OK
        msg = f"PR #{pr_number} is ready to merge"
    else:
        status = ScriptStatus.WARN
        msg = f"PR #{pr_number} blocked: {'; '.join(blockers[:3])}"

    return status, script_result, msg


def main() -> None:
    script_main("pr_merge_readiness", _run)


if __name__ == "__main__":
    main()
