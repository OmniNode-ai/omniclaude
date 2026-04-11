#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Linear Done-state PR verification [OMN-8415].

Cross-checks Linear ticket Done-state transitions against the state of any
GitHub PRs referenced in the ticket description. If any referenced PR is still
open or blocked, the transition is rejected — catching the OMN-8375 class of
failure where a ticket was marked Done while its PR was still BLOCKED.

Parent: OMN-8407 (Overseer verification).

Usage (from shell wrapper, reads PreToolUse JSON on stdin):

    echo '<tool_json>' | python3 linear_done_verify.py

Exit codes:
    0 — allow the tool call
    2 — block the tool call (with JSON decision on stderr)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any

DONE_STATES = {"done", "complete", "completed", "closed", "canceled", "cancelled"}

# `#123` not preceded by a word char (skip things like `abc#1` inside code);
# also `https://github.com/<owner>/<repo>/pull/<num>`.
_PR_NUMBER_RE = re.compile(r"(?<![\w/])#(\d+)\b")
_PR_URL_RE = re.compile(
    r"https?://github\.com/([\w.-]+)/([\w.-]+)/pull/(\d+)",
    re.IGNORECASE,
)

BLOCKING_MERGE_STATES = {"BLOCKED", "DIRTY", "BEHIND"}

DEFAULT_OWNER = "OmniNode-ai"


@dataclass
class PRRef:
    number: int
    repo: str | None = None  # "owner/repo" when known; else None


@dataclass
class PRStatus:
    ref: PRRef
    state: str  # OPEN, CLOSED, MERGED
    merge_state: str  # CLEAN, BLOCKED, DIRTY, BEHIND, UNKNOWN, etc.
    error: str | None = None

    @property
    def is_blocking(self) -> bool:
        if self.error:
            return True
        if self.state == "MERGED":
            return False
        if self.state == "OPEN":
            return True
        # CLOSED-without-merge counts as blocking (unmerged)
        if self.state == "CLOSED":
            return True
        return True


@dataclass
class VerificationResult:
    allowed: bool
    reason: str = ""
    pr_statuses: list[PRStatus] = field(default_factory=list)


def parse_pr_refs(text: str, default_repo: str | None = None) -> list[PRRef]:
    """Extract PR references from a ticket description.

    Finds both `#123` shorthand and full `https://github.com/owner/repo/pull/N`
    URLs. Bare `#N` references use `default_repo` if provided.
    """
    refs: dict[tuple[str, int], PRRef] = {}

    for url_match in _PR_URL_RE.finditer(text):
        owner = url_match.group(1)
        repo_name = url_match.group(2)
        num = int(url_match.group(3))
        full_repo = f"{owner}/{repo_name}"
        refs[(full_repo, num)] = PRRef(number=num, repo=full_repo)

    repo_key = default_repo or ""
    for num_match in _PR_NUMBER_RE.finditer(text):
        num = int(num_match.group(1))
        key = (repo_key, num)
        if key in refs:
            continue
        refs[key] = PRRef(number=num, repo=default_repo)

    return list(refs.values())


def is_exempt(description: str, labels: list[str] | None) -> bool:
    """Return True if the ticket opts out of PR verification.

    Exemption signals:
        - Label `close-if-done` (or `close-if-done: true`)
        - Frontmatter/body line `close-if-done: true`
    """
    if labels:
        for label in labels:
            normalized = label.strip().lower()
            if normalized in {"close-if-done", "close-if-done: true"}:
                return True

    for line in description.splitlines():
        stripped = line.strip().lower().lstrip("-*# ").strip()
        if stripped in {"close-if-done: true", "close_if_done: true"}:
            return True

    return False


def is_done_state(state_value: str) -> bool:
    return state_value.strip().lower() in DONE_STATES


def fetch_pr_status(ref: PRRef, timeout: float = 15.0) -> PRStatus:
    """Query GitHub for PR state via `gh pr view`."""
    repo = ref.repo
    if not repo:
        return PRStatus(
            ref=ref,
            state="UNKNOWN",
            merge_state="UNKNOWN",
            error=(
                f"PR #{ref.number} has no associated repo; cannot verify. "
                "Include a full GitHub URL in the ticket DoD."
            ),
        )

    cmd = [
        "gh",
        "pr",
        "view",
        str(ref.number),
        "--repo",
        repo,
        "--json",
        "state,mergeStateStatus,url",
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return PRStatus(
            ref=ref,
            state="UNKNOWN",
            merge_state="UNKNOWN",
            error=f"Timeout querying {repo}#{ref.number}",
        )
    except FileNotFoundError:
        return PRStatus(
            ref=ref,
            state="UNKNOWN",
            merge_state="UNKNOWN",
            error="gh CLI not available in PATH",
        )

    if proc.returncode != 0:
        return PRStatus(
            ref=ref,
            state="UNKNOWN",
            merge_state="UNKNOWN",
            error=f"gh pr view failed for {repo}#{ref.number}: {proc.stderr.strip()}",
        )

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return PRStatus(
            ref=ref,
            state="UNKNOWN",
            merge_state="UNKNOWN",
            error=f"Could not parse gh output: {exc}",
        )

    return PRStatus(
        ref=ref,
        state=str(data.get("state", "UNKNOWN")).upper(),
        merge_state=str(data.get("mergeStateStatus", "UNKNOWN")).upper(),
    )


def classify_blocking(status: PRStatus) -> bool:
    """Return True if this PR should block a Done transition."""
    if status.error:
        return True
    if status.state == "MERGED":
        return False
    if status.state == "OPEN":
        return True
    if status.state == "CLOSED":
        return True  # closed-without-merge
    if status.merge_state in BLOCKING_MERGE_STATES:
        return True
    return False


def verify(
    description: str,
    labels: list[str] | None,
    default_repo: str | None = None,
    fetcher: Any = fetch_pr_status,
) -> VerificationResult:
    """Run the full verification against a ticket description.

    Returns allowed=True if the transition should proceed, allowed=False with a
    reason string describing the blocking PRs otherwise.
    """
    if is_exempt(description, labels):
        return VerificationResult(allowed=True, reason="exempt")

    refs = parse_pr_refs(description, default_repo=default_repo)
    if not refs:
        # No PR references — trust the human; nothing to verify.
        return VerificationResult(allowed=True, reason="no_pr_references")

    statuses = [fetcher(ref) for ref in refs]
    blocking = [s for s in statuses if classify_blocking(s)]

    if not blocking:
        return VerificationResult(
            allowed=True,
            reason="all_prs_merged",
            pr_statuses=statuses,
        )

    lines = ["Cannot mark Done — referenced PRs are not merged:"]
    for status in blocking:
        repo = status.ref.repo or "?"
        if status.error:
            lines.append(f"  - {repo}#{status.ref.number}: {status.error}")
        else:
            lines.append(
                f"  - {repo}#{status.ref.number}: state={status.state} "
                f"mergeState={status.merge_state}"
            )
    lines.append(
        "Add `close-if-done: true` label or frontmatter to exempt "
        "verified-already-merged tickets."
    )
    return VerificationResult(
        allowed=False,
        reason="\n".join(lines),
        pr_statuses=statuses,
    )


def _load_stdin_tool_call() -> dict[str, Any]:
    try:
        parsed = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return {}
    if isinstance(parsed, dict):
        return parsed
    return {}


def _fetch_linear_issue(ticket_id: str) -> dict[str, Any] | None:
    """Fetch a Linear issue via the gh-linear shim if available.

    Returns None if the shim isn't available. The shim is wired only in
    integration/dogfood environments; unit tests inject descriptions directly.
    """
    cmd = ["linear-cli", "get-issue", ticket_id]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=10.0, check=False
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    try:
        parsed = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


def main() -> int:
    call = _load_stdin_tool_call()
    tool_name = call.get("tool_name", "")
    if tool_name not in {
        "mcp__linear-server__save_issue",
        "mcp__linear-server__update_issue",
    }:
        return 0

    params: dict[str, Any] = call.get("tool_input") or {}
    state_value = str(params.get("state") or params.get("status") or "")
    if not is_done_state(state_value):
        return 0

    ticket_id = str(params.get("id") or params.get("issueId") or "")
    description = str(params.get("description") or "")
    labels: list[str] = list(params.get("labels") or [])

    # If the description wasn't passed on this update (common: status-only
    # updates), fetch the live ticket to read DoD references. Fail-closed: if
    # the fetch fails we cannot tell whether a PR is referenced, so reject
    # rather than let the Done transition through blind.
    if not description and ticket_id:
        issue = _fetch_linear_issue(ticket_id)
        if not issue:
            decision = {
                "decision": "block",
                "reason": (
                    f"[OMN-8415 done-state PR verify] Could not fetch Linear "
                    f"ticket {ticket_id} to read DoD; refusing to mark Done "
                    "without verifying referenced PRs. Retry once Linear is "
                    "reachable or pass the description in the save_issue call."
                ),
            }
            sys.stderr.write(json.dumps(decision) + "\n")
            return 2
        description = str(issue.get("description") or "")
        labels = labels or list(issue.get("labels") or [])

    default_repo = os.environ.get("LINEAR_DONE_VERIFY_DEFAULT_REPO") or None

    result = verify(description, labels, default_repo=default_repo)
    if result.allowed:
        return 0

    decision = {
        "decision": "block",
        "reason": f"[OMN-8415 done-state PR verify] {result.reason}",
    }
    sys.stderr.write(json.dumps(decision) + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
