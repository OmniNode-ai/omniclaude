# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Decision query backend.

Queries the local decision store for recent decisions related to a repo.
The decision store is at ~/.claude/decisions/ (JSON files written by
the decision-store skill).

Falls back to checking recent PR comments and review decisions
when no local decision store entries are found.
"""

from __future__ import annotations

import json
from pathlib import Path
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
    """Query decisions for a repository."""
    meta = make_meta("decision_query", run_id, repo_slug)

    # Check local decision store
    decision_dir = Path.home() / ".claude" / "decisions"
    local_decisions: list[dict[str, Any]] = []

    if decision_dir.is_dir():
        repo_short = repo_slug.split("/")[-1] if "/" in repo_slug else repo_slug
        for path in sorted(decision_dir.glob("*.json"), reverse=True)[:50]:
            try:
                data = json.loads(path.read_text())
                # Match decisions related to this repo
                decision_repo = data.get("repo", "")
                if repo_short in decision_repo or repo_slug in decision_repo:
                    local_decisions.append(
                        {
                            "id": data.get("id", path.stem),
                            "type": data.get("type", "unknown"),
                            "summary": data.get("summary", ""),
                            "status": data.get("status", "unknown"),
                            "created_at": data.get("created_at", ""),
                            "ticket": data.get("ticket_id", ""),
                        }
                    )
            except (json.JSONDecodeError, OSError):
                continue

    # Also fetch recent merged PRs as implicit decisions
    try:
        pr_result = run_gh(
            [
                "pr",
                "list",
                "--repo",
                repo_slug,
                "--state",
                "merged",
                "--limit",
                "10",
                "--json",
                "number,title,mergedAt,author,headRefName",
            ]
        )
        merged_prs = json.loads(pr_result.stdout) if pr_result.stdout.strip() else []
    except Exception:
        merged_prs = []

    parsed_merged = [
        {
            "number": pr.get("number"),
            "title": pr.get("title", ""),
            "merged_at": pr.get("mergedAt", ""),
            "author": (pr.get("author") or {}).get("login", "unknown"),
            "branch": pr.get("headRefName", ""),
        }
        for pr in merged_prs
    ]

    total_decisions = len(local_decisions)
    total_merged = len(parsed_merged)

    script_result = SkillScriptResult(
        meta=meta,
        inputs={"repo": repo_slug},
        parsed={
            "local_decisions": local_decisions[:20],
            "recent_merges": parsed_merged,
        },
        summary={
            "local_decision_count": total_decisions,
            "recent_merge_count": total_merged,
            "has_decisions": total_decisions > 0 or total_merged > 0,
        },
    )

    if total_decisions > 0:
        msg = f"{total_decisions} local decisions, {total_merged} recent merges"
    elif total_merged > 0:
        msg = f"No local decisions; {total_merged} recent merges found"
    else:
        msg = "No decisions or recent merges found"

    return ScriptStatus.OK, script_result, msg


def main() -> None:
    script_main("decision_query", _run)


if __name__ == "__main__":
    main()
