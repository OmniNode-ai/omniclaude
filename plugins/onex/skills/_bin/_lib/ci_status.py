# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""CI status backend.

Checks CI/CD status for a specific PR or the default branch.
Uses `gh pr checks` or `gh run list` for data.
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
    """Check CI status for a PR or default branch."""
    meta = make_meta("ci_status", run_id, repo_slug)
    pr_number = args.get("pr")

    if pr_number:
        # Check specific PR's CI status
        result = run_gh(
            [
                "pr",
                "checks",
                str(pr_number),
                "--repo",
                repo_slug,
                "--json",
                "name,state,conclusion,startedAt,completedAt,detailsUrl",
            ]
        )
        checks = json.loads(result.stdout) if result.stdout.strip() else []

        # Parse check results
        parsed_checks = [
            {
                "name": c.get("name", ""),
                "state": c.get("state", "UNKNOWN"),
                "conclusion": c.get("conclusion", ""),
                "started_at": c.get("startedAt", ""),
                "completed_at": c.get("completedAt", ""),
            }
            for c in checks
        ]

        total = len(checks)
        passing = sum(1 for c in checks if c.get("conclusion") == "SUCCESS")
        failing = sum(
            1
            for c in checks
            if c.get("conclusion") in ("FAILURE", "ERROR", "CANCELLED")
        )
        pending = sum(
            1
            for c in checks
            if c.get("state") in ("QUEUED", "IN_PROGRESS", "PENDING", "WAITING")
        )
        skipped = sum(1 for c in checks if c.get("conclusion") == "SKIPPED")

        # Identify failing check names
        failing_names = [
            c.get("name", "unknown")
            for c in checks
            if c.get("conclusion") in ("FAILURE", "ERROR", "CANCELLED")
        ]

        inputs_dict: dict[str, Any] = {"repo": repo_slug, "pr": pr_number}

    else:
        # Check recent workflow runs on default branch
        result = run_gh(
            [
                "run",
                "list",
                "--repo",
                repo_slug,
                "--branch",
                "main",
                "--limit",
                "10",
                "--json",
                "databaseId,name,status,conclusion,createdAt,updatedAt,headBranch",
            ]
        )
        runs = json.loads(result.stdout) if result.stdout.strip() else []

        parsed_checks = [
            {
                "name": r.get("name", ""),
                "state": r.get("status", "UNKNOWN"),
                "conclusion": r.get("conclusion", ""),
                "started_at": r.get("createdAt", ""),
                "completed_at": r.get("updatedAt", ""),
            }
            for r in runs
        ]

        total = len(runs)
        passing = sum(1 for r in runs if r.get("conclusion") == "success")
        failing = sum(
            1 for r in runs if r.get("conclusion") in ("failure", "cancelled")
        )
        pending = sum(1 for r in runs if r.get("status") in ("queued", "in_progress"))
        skipped = 0

        failing_names = [
            r.get("name", "unknown")
            for r in runs
            if r.get("conclusion") in ("failure", "cancelled")
        ]

        inputs_dict = {"repo": repo_slug, "branch": "main", "limit": 10}

    script_result = SkillScriptResult(
        meta=meta,
        inputs=inputs_dict,
        parsed={"checks": parsed_checks},
        summary={
            "total": total,
            "passing": passing,
            "failing": failing,
            "pending": pending,
            "skipped": skipped,
            "failing_names": failing_names,
            "all_green": failing == 0 and pending == 0 and total > 0,
        },
    )

    if failing > 0:
        status = ScriptStatus.WARN
        msg = f"{failing}/{total} checks failing: {', '.join(failing_names[:3])}"
    elif pending > 0:
        status = ScriptStatus.OK
        msg = f"{pending}/{total} checks pending, {passing} passing"
    elif total == 0:
        status = ScriptStatus.WARN
        msg = "No CI checks found"
    else:
        status = ScriptStatus.OK
        msg = f"All {total} checks passing"

    return status, script_result, msg


def main() -> None:
    script_main("ci_status", _run)


if __name__ == "__main__":
    main()
