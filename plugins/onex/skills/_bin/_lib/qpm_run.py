# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""QPM orchestrator -- fetch, classify, score, decide, audit.

Path dependency: imports merge_planner from plugins/onex/skills/_lib/merge_planner/
via sys.path insertion. This is consistent with how _bin/_lib/ scripts access shared
skill libraries.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .base import (
    ScriptStatus,
    SkillScriptResult,
    make_meta,
    run_gh,
    script_main,
)

# Add skills/_lib/ to path for merge_planner imports
_SKILLS_LIB = str(Path(__file__).resolve().parent.parent.parent / "_lib")
if _SKILLS_LIB not in sys.path:
    sys.path.insert(0, _SKILLS_LIB)

from merge_planner.audit import write_audit  # noqa: E402
from merge_planner.classifier import (  # noqa: E402
    PRContext,  # noqa: TC002 -- runtime access to attrs
    classify_pr,
)
from merge_planner.models import (  # noqa: E402
    EnumPromotionDecision,
    ModelPromotionRecord,
    ModelQPMAuditEntry,
)
from merge_planner.promoter import PromotionMode, decide_promotion  # noqa: E402
from merge_planner.scorer import PROMOTION_THRESHOLD, score_pr  # noqa: E402

DEFAULT_REPOS = [
    "OmniNode-ai/omnibase_core",
    "OmniNode-ai/omnibase_infra",
    "OmniNode-ai/omniclaude",
    "OmniNode-ai/omniintelligence",
    "OmniNode-ai/omnimemory",
    "OmniNode-ai/omnidash",
]


class FetchResult:
    """Result of a gh CLI fetch. Tracks degraded state explicitly."""

    def __init__(self, data: Any = None, error: str | None = None) -> None:
        self.data = data
        self.error = error
        self.degraded = error is not None


def _fetch_open_prs(repo: str) -> FetchResult:
    """Fetch open PRs via gh CLI.

    Returns FetchResult with degraded=True on failure, NOT an empty list.
    An empty list means the repo genuinely has no open PRs.
    A degraded result means we don't know.
    """
    result = run_gh(
        [
            "pr",
            "list",
            "--repo",
            repo,
            "--state",
            "open",
            "--limit",
            "100",
            "--json",
            "number,title,isDraft,files,labels,reviewDecision,statusCheckRollup",
        ]
    )
    if result.returncode != 0:
        return FetchResult(data=[], error=f"gh pr list failed: {result.stderr.strip()}")
    try:
        prs = json.loads(result.stdout) if result.stdout.strip() else []
        return FetchResult(data=prs)
    except json.JSONDecodeError as e:
        return FetchResult(data=[], error=f"Malformed JSON from gh pr list: {e}")


def _fetch_queue_depth(repo: str) -> FetchResult:
    """Fetch current merge queue depth.

    Returns FetchResult with degraded=True on failure. A degraded depth of 0
    means we don't know the real depth, NOT that the queue is empty.
    """
    try:
        result = run_gh(
            [
                "api",
                f"repos/{repo}/merge-queue",
                "--jq",
                ".entries | length",
            ]
        )
        if result.returncode != 0:
            return FetchResult(
                data=0,
                error=f"merge-queue API failed: {result.stderr.strip()}",
            )
        depth = int(result.stdout.strip()) if result.stdout.strip() else 0
        return FetchResult(data=depth)
    except (ValueError, Exception) as e:  # noqa: BLE001
        return FetchResult(data=0, error=f"merge-queue depth parse error: {e}")


def _parse_pr_context(repo: str, pr_data: dict[str, Any]) -> PRContext:
    """Convert gh CLI JSON to PRContext."""
    checks = pr_data.get("statusCheckRollup") or []
    has_failure = any(c.get("conclusion") == "FAILURE" for c in checks)
    has_success = any(c.get("conclusion") == "SUCCESS" for c in checks)
    ci_status = "failure" if has_failure else ("success" if has_success else "pending")

    return PRContext(
        number=pr_data["number"],
        repo=repo,
        title=pr_data.get("title", ""),
        is_draft=pr_data.get("isDraft", False),
        ci_status=ci_status,
        review_state=(pr_data.get("reviewDecision") or "none").lower(),
        changed_files=[f["path"] for f in (pr_data.get("files") or [])],
        labels=[label["name"] for label in (pr_data.get("labels") or [])],
    )


def _execute_promotion(repo: str, pr_number: int, dry_run: bool) -> tuple[bool, str]:
    """Call qpm-enqueue.sh via subprocess."""
    bin_dir = Path(__file__).resolve().parent.parent
    script = bin_dir / "qpm-enqueue.sh"
    args = [str(script), repo, str(pr_number), "--jump"]
    if dry_run:
        args.append("--dry-run")
    result = subprocess.run(  # noqa: S603
        args, capture_output=True, text=True, timeout=30, check=False
    )
    if result.returncode in (0, 2):  # 0=success, 2=dry-run
        return True, result.stdout
    return False, result.stderr


def run_qpm(
    repos: list[str],
    mode: PromotionMode,
    max_promotions: int = 3,
    dry_run: bool = False,
) -> ModelQPMAuditEntry:
    """Execute a full QPM run."""
    run_id = f"qpm-{uuid4().hex[:12]}"
    started_at = datetime.now(UTC)
    records: list[ModelPromotionRecord] = []
    errors: list[str] = []
    repo_fetch_errors: dict[str, str] = {}
    promote_count = 0

    for repo in repos:
        pr_result = _fetch_open_prs(repo)
        depth_result = _fetch_queue_depth(repo)

        # Track degraded fetch state per repo
        repo_errors: list[str] = []
        if pr_result.degraded:
            repo_errors.append(pr_result.error or "unknown error")
        if depth_result.degraded:
            repo_errors.append(depth_result.error or "unknown error")
        if repo_errors:
            repo_fetch_errors[repo] = "; ".join(repo_errors)

        prs: list[dict[str, Any]] = pr_result.data
        queue_depth: int = depth_result.data

        for pr_data in prs:
            ctx = _parse_pr_context(repo, pr_data)
            queue_class = classify_pr(ctx)
            score = score_pr(ctx, queue_class, queue_depth)
            record = decide_promotion(ctx, queue_class, score, mode)

            # Check promotion cap BEFORE executing
            if (
                record.decision == EnumPromotionDecision.PROMOTE
                and promote_count >= max_promotions
            ):
                record = decide_promotion(
                    ctx,
                    queue_class,
                    score,
                    mode,
                    override_decision=EnumPromotionDecision.HOLD,
                    override_reason=f"Max promotions ({max_promotions}) reached for this run",
                )
            elif record.decision == EnumPromotionDecision.PROMOTE:
                success, output = _execute_promotion(repo, ctx.number, dry_run)
                if success:
                    promote_count += 1
                else:
                    errors.append(f"{repo}#{ctx.number}: {output}")

            records.append(record)

    held_count = sum(
        1
        for r in records
        if r.decision == EnumPromotionDecision.HOLD and r.would_promote
    )

    audit = ModelQPMAuditEntry(
        run_id=run_id,
        timestamp=started_at,
        mode=mode.value,
        repos_queried=repos,
        repo_fetch_errors=repo_fetch_errors,
        promotion_threshold=PROMOTION_THRESHOLD,
        max_promotions=max_promotions,
        records=records,
        promotions_executed=promote_count,
        promotions_held=held_count,
    )
    write_audit(audit)
    return audit


def _run(
    repo_slug: str, run_id: str, args: dict[str, Any]
) -> tuple[ScriptStatus, SkillScriptResult, str]:
    """Entry point following _bin/_lib/ backend convention."""
    meta = make_meta("qpm_run", run_id, repo_slug)

    mode_str = args.get("mode", "shadow")
    repos_str = args.get("repos")
    dry_run = args.get("dry_run", False)
    max_promotions = int(args.get("max_promotions", 3))

    repos = repos_str.split(",") if repos_str else DEFAULT_REPOS
    mode = PromotionMode(mode_str)

    audit = run_qpm(repos, mode, max_promotions, dry_run)

    result = SkillScriptResult(
        meta=meta,
        inputs={
            "mode": mode_str,
            "repos": repos,
            "dry_run": dry_run,
            "max_promotions": max_promotions,
        },
        parsed={
            "records": [r.model_dump() for r in audit.records],
        },
        summary={
            "prs_classified": len(audit.records),
            "prs_promoted": audit.promotions_executed,
            "prs_held": audit.promotions_held,
            "errors": errors if (errors := []) else [],
        },
    )
    status = ScriptStatus.OK if not audit.repo_fetch_errors else ScriptStatus.WARN
    return status, result, audit.model_dump_json(indent=2)


if __name__ == "__main__":
    script_main("qpm_run", _run)
