#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Merge-queue unstick runner [OMN-9065].

Probes each configured repo's merge queue, classifies the head PR via
:mod:`queue_stall_classifier`, and performs the dequeue / re-enqueue +
friction-emit actions that match the verdict.

Invoked by ``scripts/cron-unstick-queue.sh`` (launchd tick) and the
``/onex:unstick_queue`` skill prompt. Emits one JSON line per repo plus a
final aggregate line so the cron wrapper can parse counts without scraping
log formatting.

CLI::

    uv run python scripts/lib/run-unstick-queue.py \
        --repos omnibase_infra,omniclaude \
        --dry-run

Exit codes:
    0 = completed (errors counted per-repo, not fatal)
    2 = unrecoverable preflight failure (gh missing, no repos resolved)
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import time
from datetime import UTC, datetime
from typing import Any

_LIB_DIR = (
    pathlib.Path(__file__).resolve().parent.parent.parent
    / "plugins"
    / "onex"
    / "hooks"
    / "lib"
)
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from queue_stall_classifier import (  # noqa: E402
    AWAITING_CHECKS_STALL_MINUTES,
    ORPHANED_CHECK_MINUTES,
    EnumQueueStallVerdict,
    classify_queue_entry,
    load_unstick_history,
    record_unstick,
)

ORG = "OmniNode-ai"

DEFAULT_REPOS = (
    "omniclaude",
    "omnibase_core",
    "omnibase_spi",
    "omnibase_infra",
    "omnibase_compat",
    "omniintelligence",
    "omnimemory",
    "omninode_infra",
    "onex_change_control",
)


def _gh(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run ``gh`` with stdout captured. Raises on non-zero when ``check`` is True."""
    return subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        check=check,
    )


def resolve_repos(cli_value: str | None) -> list[str]:
    """Resolve repo list from CLI → env → default."""
    raw = cli_value or os.environ.get("ONEX_QUEUE_REPOS") or ",".join(DEFAULT_REPOS)
    return [r.strip() for r in raw.split(",") if r.strip()]


def fetch_queue_head(repo: str) -> dict[str, Any] | None:
    """Fetch the position-1 entry from the repo's merge queue.

    Returns ``None`` when the queue is empty, the repo has no merge queue
    configured, or the query fails. Errors are surfaced via stderr so the
    cron wrapper can capture them, but do not abort the runner.
    """
    query = (
        "query($owner: String!, $name: String!) { "
        "repository(owner: $owner, name: $name) { "
        "mergeQueue { entries(first: 1) { nodes { "
        "enqueuedAt state "
        "pullRequest { number id } "
        "} } } } }"
    )
    try:
        proc = _gh(
            [
                "api",
                "graphql",
                "-f",
                f"query={query}",
                "-F",
                f"owner={ORG}",
                "-F",
                f"name={repo}",
                "--jq",
                ".data.repository.mergeQueue.entries.nodes[0]",
            ],
            check=False,
        )
    except FileNotFoundError:
        print(json.dumps({"repo": repo, "error": "gh CLI missing"}), file=sys.stderr)
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        # Empty queue or query error — either way, nothing to act on.
        if proc.stderr.strip():
            print(
                json.dumps({"repo": repo, "stderr": proc.stderr.strip()[:500]}),
                file=sys.stderr,
            )
        return None
    try:
        node = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(node, dict):
        return None
    # The classifier expects a "position" field; we queried first:1 so it's always 1.
    node["position"] = 1
    return node


def fetch_status_check_rollup(repo: str, pr_number: int) -> list[dict[str, Any]]:
    """Fetch statusCheckRollup for a PR — list of check-runs with status + startedAt."""
    query = (
        "query($owner: String!, $name: String!, $pr: Int!) { "
        "repository(owner: $owner, name: $name) { "
        "pullRequest(number: $pr) { commits(last: 1) { nodes { commit { "
        "statusCheckRollup { contexts(first: 100) { nodes { "
        "__typename ... on CheckRun { name status conclusion startedAt } "
        "... on StatusContext { context state createdAt } "
        "} } } } } } } } }"
    )
    proc = _gh(
        [
            "api",
            "graphql",
            "-f",
            f"query={query}",
            "-F",
            f"owner={ORG}",
            "-F",
            f"name={repo}",
            "-F",
            f"pr={pr_number}",
            "--jq",
            ".data.repository.pullRequest.commits.nodes[0].commit.statusCheckRollup.contexts.nodes",
        ],
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return []
    try:
        raw = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []
    normalised: list[dict[str, Any]] = []
    for node in raw:
        if not isinstance(node, dict):
            continue
        if node.get("__typename") == "StatusContext":
            # Normalise StatusContext shape to CheckRun shape for the classifier.
            normalised.append(
                {
                    "name": node.get("context"),
                    "status": None
                    if node.get("state") in ("PENDING", "EXPECTED")
                    else "COMPLETED",
                    "conclusion": None
                    if node.get("state") in ("PENDING", "EXPECTED")
                    else node.get("state"),
                    "startedAt": node.get("createdAt"),
                }
            )
        else:
            normalised.append(node)
    return normalised


def fetch_required_contexts(repo: str) -> set[str]:
    """Fetch branch-protection required status checks for ``main``.

    Returns an empty set when the query fails or protection is absent — the
    classifier tolerates an empty required-context set (it just cannot
    upgrade any failures to BROKEN). Safer than aborting.
    """
    proc = _gh(
        [
            "api",
            f"repos/{ORG}/{repo}/branches/main/protection/required_status_checks",
            "--jq",
            ".contexts[]?",
        ],
        check=False,
    )
    if proc.returncode != 0:
        return set()
    return {line.strip() for line in proc.stdout.splitlines() if line.strip()}


def dequeue_and_requeue(repo: str, pr_node_id: str, pause_seconds: float) -> bool:
    """Dequeue then re-enqueue a PR. Returns True iff both steps succeed.

    The re-enqueue call uses ``enqueuePullRequest`` (no merge-method arg), so
    the queue's configured method is used — eliminating the silent drop caused
    by method-mismatch, consistent with ``_queue_heal`` in cron-merge-sweep.
    """
    dequeue_query = (
        "mutation($pr: ID!) { dequeuePullRequest(input: {id: $pr}) "
        "{ clientMutationId } }"
    )
    enqueue_query = (
        "mutation($pr: ID!) { enqueuePullRequest(input: {pullRequestId: $pr}) "
        "{ mergeQueueEntry { position state } } }"
    )

    proc = _gh(
        [
            "api",
            "graphql",
            "-f",
            f"query={dequeue_query}",
            "-f",
            f"pr={pr_node_id}",
        ],
        check=False,
    )
    if proc.returncode != 0:
        print(
            json.dumps({"repo": repo, "phase": "dequeue", "stderr": proc.stderr[:500]}),
            file=sys.stderr,
        )
        # Attempt to re-enqueue anyway — the dequeue failure may just mean the
        # entry was removed between probe and mutation.
    time.sleep(pause_seconds)

    proc = _gh(
        [
            "api",
            "graphql",
            "-f",
            f"query={enqueue_query}",
            "-f",
            f"pr={pr_node_id}",
        ],
        check=False,
    )
    if proc.returncode != 0:
        print(
            json.dumps({"repo": repo, "phase": "enqueue", "stderr": proc.stderr[:500]}),
            file=sys.stderr,
        )
        return False
    return True


def process_repo(
    repo: str,
    *,
    dry_run: bool,
    awaiting_minutes: int,
    orphan_minutes: int,
    pause_seconds: float,
    now: datetime,
) -> dict[str, Any]:
    """Process a single repo; return a summary dict."""
    summary = {
        "repo": repo,
        "head_pr": None,
        "verdict": None,
        "action": "none",
        "error": None,
    }
    head = fetch_queue_head(repo)
    if head is None:
        summary["verdict"] = EnumQueueStallVerdict.HEALTHY.value
        return summary

    pr = head.get("pullRequest") or {}
    pr_number = pr.get("number")
    pr_node_id = pr.get("id")
    if pr_number is None or pr_node_id is None:
        summary["error"] = "malformed queue entry"
        return summary
    summary["head_pr"] = pr_number

    rollup = fetch_status_check_rollup(repo, pr_number)
    required = fetch_required_contexts(repo)

    prior = load_unstick_history(f"{ORG}/{repo}", pr_number)
    verdict = classify_queue_entry(
        entry=head,
        status_check_rollup=rollup,
        required_contexts=required,
        now=now,
        prior_unsticks=prior,
        awaiting_minutes_threshold=awaiting_minutes,
        orphan_minutes_threshold=orphan_minutes,
    )
    summary["verdict"] = verdict.value

    if verdict == EnumQueueStallVerdict.STALL:
        if dry_run:
            summary["action"] = "would-unstick"
        else:
            ok = dequeue_and_requeue(repo, pr_node_id, pause_seconds)
            if ok:
                try:
                    record_unstick(f"{ORG}/{repo}", pr_number, now)
                except KeyError:
                    summary["error"] = "ONEX_STATE_DIR unset — skipped record"
                summary["action"] = "unstuck"
            else:
                summary["action"] = "unstick-failed"
    elif verdict == EnumQueueStallVerdict.ESCALATE:
        summary["action"] = "escalate"
    elif verdict == EnumQueueStallVerdict.BROKEN:
        summary["action"] = "skip-broken"

    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge-queue unstick runner")
    parser.add_argument("--repos", help="Comma-separated repo short-names")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--awaiting-minutes",
        type=int,
        default=AWAITING_CHECKS_STALL_MINUTES,
        help="Queue-head AWAITING_CHECKS threshold (minutes)",
    )
    parser.add_argument(
        "--orphan-minutes",
        type=int,
        default=ORPHANED_CHECK_MINUTES,
        help="Check-run orphan threshold (minutes)",
    )
    parser.add_argument(
        "--pause-seconds",
        type=float,
        default=2.0,
        help="Pause between dequeue and re-enqueue",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repos = resolve_repos(args.repos)
    if not repos:
        print("ERROR: no repos resolved", file=sys.stderr)
        return 2

    if (
        subprocess.run(["gh", "--version"], capture_output=True, check=False).returncode
        != 0
    ):
        print("ERROR: gh CLI not available", file=sys.stderr)
        return 2

    now = datetime.now(UTC)

    totals = {
        "scanned": 0,
        "stall_unstuck": 0,
        "broken_skipped": 0,
        "escalated": 0,
        "errors": 0,
    }

    for repo in repos:
        totals["scanned"] += 1
        try:
            summary = process_repo(
                repo,
                dry_run=args.dry_run,
                awaiting_minutes=args.awaiting_minutes,
                orphan_minutes=args.orphan_minutes,
                pause_seconds=args.pause_seconds,
                now=now,
            )
        except Exception as exc:  # noqa: BLE001 — per-repo isolation
            summary = {"repo": repo, "error": str(exc)}
            totals["errors"] += 1

        print(json.dumps(summary, sort_keys=True))

        if summary.get("action") == "unstuck":
            totals["stall_unstuck"] += 1
        elif summary.get("action") == "skip-broken":
            totals["broken_skipped"] += 1
        elif summary.get("action") == "escalate":
            totals["escalated"] += 1
        elif summary.get("error") or summary.get("action") == "unstick-failed":
            totals["errors"] += 1

    print(json.dumps({"summary": totals}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
