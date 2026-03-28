# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""CI status backend.

Checks CI/CD status for a specific PR or the default branch.
Uses `gh pr checks` or `gh run list` for data.

When checking the default branch (no --pr), only required workflows are
considered.  Auxiliary workflows (release, nightly, pin cascade, etc.) are
excluded so that the integration sweep does not flag them as failures.
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

# ---------------------------------------------------------------------------
# Required workflow filter (OMN-6812)
# ---------------------------------------------------------------------------
# Only these workflow names are considered when checking CI on the default
# branch.  Auxiliary workflows (release, nightly, plugin-pin-cascade, etc.)
# are ignored because they may legitimately have never run on main and should
# not cause the integration sweep to flag a FAIL.
#
# Names are matched case-insensitively against the ``name`` field returned by
# ``gh run list --json name,...``.

REQUIRED_WORKFLOW_NAMES: list[str] = ["ci.yml", "CI"]

# Auxiliary workflow names explicitly skipped.  Listed for documentation and
# test assertions — the actual filter is an allowlist (REQUIRED_WORKFLOW_NAMES),
# not a denylist.
AUXILIARY_WORKFLOW_NAMES: list[str] = [
    "Release",
    "Plugin Pin Cascade",
    "Nightly Tests",
    "release.yml",
    "plugin-pin-cascade.yml",
    "nightly.yml",
]


def _is_required_workflow(name: str) -> bool:
    """Return True if *name* matches a required workflow (case-insensitive)."""
    name_lower = name.lower()
    return any(rw.lower() == name_lower for rw in REQUIRED_WORKFLOW_NAMES)


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
        all_runs = json.loads(result.stdout) if result.stdout.strip() else []

        # Filter to required workflows only (OMN-6812).  Auxiliary workflows
        # (release, nightly, etc.) are excluded so they don't cause false
        # FAIL signals in the integration sweep.
        runs = [r for r in all_runs if _is_required_workflow(r.get("name", ""))]

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
        skipped = len(all_runs) - len(runs)

        failing_names = [
            r.get("name", "unknown")
            for r in runs
            if r.get("conclusion") in ("failure", "cancelled")
        ]

        inputs_dict: dict[str, Any] = {
            "repo": repo_slug,
            "branch": "main",
            "limit": 10,
            "required_workflows": REQUIRED_WORKFLOW_NAMES,
            "auxiliary_skipped": skipped,
        }

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
