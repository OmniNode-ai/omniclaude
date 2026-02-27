#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""CI Repair Effect Node -- Autonomous CI failure detection and repair.

EVENT_BUS+ tier ONEX effect node that receives CI failure events from Kafka,
orchestrates a multi-attempt repair loop with strategy rotation, and posts
inbox notifications on success or exhaustion.

Flow:
    CI fails -> relay -> Kafka -> watcher routes to node_ci_repair_effect
    -> fix loop (up to max_attempts with strategy rotation)
    -> push -> inbox notification on success

Related Tickets:
    - OMN-2829: Phase 7 -- Self-Healing CI
    - OMN-2826: Phase 2 -- Event Bus Relay (dependency)
    - OMN-2828: Phase 5 -- Inbox / Notification Pane (dependency)

.. versionadded:: 0.3.0
"""

from __future__ import annotations

import enum
import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# =============================================================================
# Configuration
# =============================================================================

_DEFAULT_MAX_ATTEMPTS = 3
_HARD_MAX_ATTEMPTS = 10  # Upper bound — prevents runaway repair loops
_DEFAULT_CI_STATUS_SCRIPT = "_bin/ci-status.sh"
_DEFAULT_INBOX_DIR = "~/.claude/inbox"
_DEFAULT_STATE_DIR = "~/.claude/state/ci-repair"
_CI_RERUN_WAIT_SECONDS = 30
_CI_RERUN_MAX_WAIT_SECONDS = 300


def _max_attempts() -> int:
    """Return the configured max repair attempts, clamped to a safe upper bound."""
    try:
        configured = int(
            os.environ.get("CI_REPAIR_MAX_ATTEMPTS", str(_DEFAULT_MAX_ATTEMPTS))
        )
        return min(configured, _HARD_MAX_ATTEMPTS)
    except ValueError:
        return _DEFAULT_MAX_ATTEMPTS


def _plugin_root() -> str:
    """Return the Claude plugin root directory."""
    return os.environ.get(
        "CLAUDE_PLUGIN_ROOT",
        str(Path.home() / ".claude" / "plugins" / "onex"),
    )


def _ci_status_script() -> str:
    """Return the path to the ci-status.sh script."""
    return os.path.join(_plugin_root(), _DEFAULT_CI_STATUS_SCRIPT)


def _inbox_dir() -> Path:
    """Return the inbox directory path."""
    return Path(
        os.path.expanduser(os.environ.get("CI_REPAIR_INBOX_DIR", _DEFAULT_INBOX_DIR))
    )


def _state_dir() -> Path:
    """Return the state directory for repair runs."""
    return Path(
        os.path.expanduser(os.environ.get("CI_REPAIR_STATE_DIR", _DEFAULT_STATE_DIR))
    )


def _now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(UTC).isoformat()


# =============================================================================
# Repair Strategy Enum
# =============================================================================


class RepairStrategy(enum.Enum):
    """Strategy rotation for CI repair attempts.

    Each attempt uses a different strategy to increase the likelihood of
    a successful fix. Strategies are ordered from most targeted to most
    aggressive.
    """

    TARGETED_FIX = "targeted_fix"
    """Attempt 1: Parse error logs, fix only the specific failing lines/files."""

    BROAD_LINT_FIX = "broad_lint_fix"
    """Attempt 2: Run ruff/mypy auto-fix on all files touched by the PR."""

    REGENERATE_AND_FIX = "regenerate_and_fix"
    """Attempt 3: Regenerate affected code sections, apply all auto-fixers."""

    @classmethod
    def for_attempt(cls, attempt: int) -> RepairStrategy:
        """Return the strategy for the given attempt number (1-indexed).

        Args:
            attempt: The attempt number (1, 2, 3).

        Returns:
            The strategy for this attempt.
        """
        strategies = [cls.TARGETED_FIX, cls.BROAD_LINT_FIX, cls.REGENERATE_AND_FIX]
        idx = min(attempt - 1, len(strategies) - 1)
        return strategies[max(0, idx)]


# =============================================================================
# Pydantic Contracts
# =============================================================================


class CIFailureEvent(BaseModel):
    """Incoming CI failure event from the event bus relay."""

    model_config = ConfigDict(extra="ignore")

    pr_number: int
    repo: str
    branch: str
    run_id: str | None = None
    ticket_id: str | None = None
    failed_jobs: list[dict[str, Any]] = Field(default_factory=list)
    failure_summary: str = ""
    timestamp: str = ""


class RepairAttempt(BaseModel):
    """Record of a single repair attempt."""

    model_config = ConfigDict(extra="ignore")

    attempt_number: int
    strategy: str
    started_at: str = ""
    completed_at: str = ""
    files_changed: list[str] = Field(default_factory=list)
    commit_sha: str | None = None
    ci_result: str | None = None  # "passing" | "failing" | "pending" | "error"
    error: str | None = None


class RepairRunState(BaseModel):
    """Full state of a CI repair run."""

    model_config = ConfigDict(extra="ignore")

    run_id: str
    pr_number: int
    repo: str
    branch: str
    ticket_id: str | None = None
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS
    attempts: list[RepairAttempt] = Field(default_factory=list)
    status: str = "in_progress"  # in_progress | repaired | exhausted | error
    started_at: str = ""
    completed_at: str = ""
    inbox_notification_sent: bool = False


# =============================================================================
# CI Status Fetcher
# =============================================================================


def fetch_ci_status(
    pr_number: int,
    repo: str,
    branch: str | None = None,
) -> dict[str, Any]:
    """Fetch CI status using _bin/ci-status.sh.

    Args:
        pr_number: The PR number to check.
        repo: The repo slug (org/repo).
        branch: Optional branch name override.

    Returns:
        Parsed JSON dict from ci-status.sh.
    """
    script = _ci_status_script()

    cmd = [script, "--pr", str(pr_number), "--repo", repo]
    if branch:
        cmd.extend(["--branch", branch])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if result.returncode in (0, 2):
            parsed: dict[str, Any] = json.loads(result.stdout)
            return parsed
        return {
            "status": "unknown",
            "error": result.stderr.strip() or f"Exit code {result.returncode}",
        }
    except subprocess.TimeoutExpired:
        return {"status": "unknown", "error": "ci-status.sh timed out"}
    except (json.JSONDecodeError, FileNotFoundError) as exc:
        return {"status": "unknown", "error": str(exc)}


# =============================================================================
# Inbox Notification
# =============================================================================


def send_inbox_notification(
    run_state: RepairRunState,
    message: str,
) -> bool:
    """Send an inbox notification about repair status.

    Writes a JSON notification file to the inbox directory.

    Args:
        run_state: Current repair run state.
        message: Notification message body.

    Returns:
        True if notification was sent, False on error.
    """
    inbox = _inbox_dir()
    try:
        inbox.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        filename = f"ci-repair-{run_state.pr_number}-{ts}.json"
        notification = {
            "type": "ci_repair",
            "run_id": run_state.run_id,
            "pr_number": run_state.pr_number,
            "repo": run_state.repo,
            "branch": run_state.branch,
            "ticket_id": run_state.ticket_id,
            "status": run_state.status,
            "attempts_used": len(run_state.attempts),
            "max_attempts": run_state.max_attempts,
            "message": message,
            "timestamp": _now_iso(),
        }
        notification_path = inbox / filename
        notification_path.write_text(json.dumps(notification, indent=2))
        return True
    except OSError:
        return False


# =============================================================================
# State Persistence
# =============================================================================


def save_repair_state(run_state: RepairRunState) -> Path:
    """Persist repair run state to disk.

    Args:
        run_state: The state to persist.

    Returns:
        Path to the saved state file.
    """
    state_dir = _state_dir()
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / f"{run_state.run_id}.json"
    path.write_text(run_state.model_dump_json(indent=2))
    return path


def load_repair_state(run_id: str) -> RepairRunState | None:
    """Load repair run state from disk.

    Args:
        run_id: The run identifier.

    Returns:
        RepairRunState if found, None otherwise.
    """
    path = _state_dir() / f"{run_id}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return RepairRunState(**data)
    except (json.JSONDecodeError, OSError):
        return None


# =============================================================================
# Wait for CI Re-run
# =============================================================================


def wait_for_ci_rerun(
    pr_number: int,
    repo: str,
    branch: str,
    previous_run_id: str | None,
    timeout_seconds: int = _CI_RERUN_MAX_WAIT_SECONDS,
) -> dict[str, Any]:
    """Wait for a new CI run to appear and complete after a push.

    Uses inbox-wait pattern: polls ci-status.sh until a new run_id appears
    and reaches a terminal state, rather than fixed sleep intervals.

    Args:
        pr_number: The PR number.
        repo: The repo slug.
        branch: The branch name.
        previous_run_id: The run_id from before the push (to detect new runs).
        timeout_seconds: Maximum time to wait.

    Returns:
        CI status dict from ci-status.sh once terminal, or error dict.
    """
    deadline = time.monotonic() + timeout_seconds
    poll_interval = _CI_RERUN_WAIT_SECONDS

    while time.monotonic() < deadline:
        time.sleep(poll_interval)
        status = fetch_ci_status(pr_number, repo, branch)

        new_run_id = status.get("run_id")
        ci_status = status.get("status", "unknown")

        # Wait for a different run_id (new run triggered by our push)
        if previous_run_id and new_run_id == previous_run_id:
            continue

        # Wait for terminal state
        if ci_status in ("passing", "failing"):
            return status

        # Still pending -- keep waiting
        if ci_status == "pending":
            continue

        # Unknown -- keep trying
        continue

    return {
        "status": "unknown",
        "error": f"Timed out waiting for CI re-run after {timeout_seconds}s",
    }


# =============================================================================
# Strategy Descriptions (for fix agent prompts)
# =============================================================================

STRATEGY_PROMPTS: dict[RepairStrategy, str] = {
    RepairStrategy.TARGETED_FIX: (
        "TARGETED FIX: Parse the CI failure logs carefully. "
        "Identify the exact files and line numbers causing failures. "
        "Apply minimal, surgical fixes to only the failing code. "
        "Do NOT change unrelated code. Do NOT refactor."
    ),
    RepairStrategy.BROAD_LINT_FIX: (
        "BROAD LINT FIX: The targeted fix did not resolve CI. "
        "Run `ruff check --fix` and `ruff format` on all files touched by this PR. "
        "Run `mypy` on affected files and fix any type errors. "
        "Fix any import ordering or formatting issues. "
        "This is a broader pass -- fix all lint and type issues in touched files."
    ),
    RepairStrategy.REGENERATE_AND_FIX: (
        "REGENERATE AND FIX: Previous repair attempts failed. "
        "This is the final attempt. Take a broader approach: "
        "1. Re-read the original ticket requirements. "
        "2. Identify if the implementation approach itself is flawed. "
        "3. If needed, rewrite failing sections from scratch. "
        "4. Run all available auto-fixers (ruff, mypy). "
        "5. Ensure all tests pass locally before committing."
    ),
}


# =============================================================================
# Core Effect: Execute Repair
# =============================================================================


def execute_effect(event: CIFailureEvent) -> RepairRunState:
    """Execute the CI repair effect.

    This is the main entry point for the ONEX effect node. It receives a CI
    failure event and orchestrates a multi-attempt repair loop with strategy
    rotation.

    Args:
        event: The incoming CI failure event.

    Returns:
        Final RepairRunState after all attempts or success.
    """
    run_id = f"ci-repair-{event.pr_number}-{int(time.time())}"
    max_attempts = _max_attempts()

    run_state = RepairRunState(
        run_id=run_id,
        pr_number=event.pr_number,
        repo=event.repo,
        branch=event.branch,
        ticket_id=event.ticket_id,
        max_attempts=max_attempts,
        status="in_progress",
        started_at=_now_iso(),
    )

    save_repair_state(run_state)

    previous_run_id = event.run_id

    for attempt_num in range(1, max_attempts + 1):
        strategy = RepairStrategy.for_attempt(attempt_num)

        attempt = RepairAttempt(
            attempt_number=attempt_num,
            strategy=strategy.value,
            started_at=_now_iso(),
        )

        # The actual fix is dispatched externally (via Task/skill invocation).
        # This node provides the orchestration framework. When used as a
        # library, the caller invokes the fix agent between setting up the
        # attempt and recording the result.

        # Record the attempt (will be updated by the caller after fix)
        run_state.attempts.append(attempt)
        save_repair_state(run_state)

    return run_state


def record_attempt_result(
    run_state: RepairRunState,
    attempt_number: int,
    files_changed: list[str] | None = None,
    commit_sha: str | None = None,
    ci_result: str | None = None,
    error: str | None = None,
) -> RepairRunState:
    """Record the result of a repair attempt.

    Args:
        run_state: Current run state.
        attempt_number: Which attempt to update (1-indexed).
        files_changed: Files modified in this attempt.
        commit_sha: Git commit SHA if committed.
        ci_result: CI status after fix ("passing", "failing", etc.).
        error: Error message if the attempt failed.

    Returns:
        Updated run state.
    """
    idx = attempt_number - 1
    if idx < 0 or idx >= len(run_state.attempts):
        return run_state

    attempt = run_state.attempts[idx]
    attempt.completed_at = _now_iso()
    attempt.files_changed = files_changed or []
    attempt.commit_sha = commit_sha
    attempt.ci_result = ci_result
    attempt.error = error

    # Check if repair succeeded
    if ci_result == "passing":
        run_state.status = "repaired"
        run_state.completed_at = _now_iso()

        # Send success notification; only mark sent if write succeeded
        msg = (
            f"CI repaired for PR #{run_state.pr_number} "
            f"on attempt {attempt_number}/{run_state.max_attempts} "
            f"using strategy: {attempt.strategy}. "
            f"Commit: {commit_sha or 'unknown'}"
        )
        if send_inbox_notification(run_state, msg):
            run_state.inbox_notification_sent = True

    # Check if all attempts exhausted
    elif attempt_number >= run_state.max_attempts:
        run_state.status = "exhausted"
        run_state.completed_at = _now_iso()

        msg = (
            f"CI repair exhausted for PR #{run_state.pr_number} "
            f"after {run_state.max_attempts} attempts. "
            f"Manual intervention required."
        )
        if send_inbox_notification(run_state, msg):
            run_state.inbox_notification_sent = True

    save_repair_state(run_state)
    return run_state


def finalize_with_error(
    run_state: RepairRunState,
    error: str,
) -> RepairRunState:
    """Finalize a repair run with an error status.

    Args:
        run_state: Current run state.
        error: Error description.

    Returns:
        Updated run state.
    """
    run_state.status = "error"
    run_state.completed_at = _now_iso()

    msg = f"CI repair error for PR #{run_state.pr_number}: {error}"
    send_inbox_notification(run_state, msg)
    run_state.inbox_notification_sent = True

    save_repair_state(run_state)
    return run_state


# =============================================================================
# Handler Registry (ONEX pattern)
# =============================================================================

HANDLERS: dict[str, Any] = {
    "execute_effect": execute_effect,
    "record_attempt_result": record_attempt_result,
    "finalize_with_error": finalize_with_error,
    "fetch_ci_status": fetch_ci_status,
    "wait_for_ci_rerun": wait_for_ci_rerun,
    "send_inbox_notification": send_inbox_notification,
    "save_repair_state": save_repair_state,
    "load_repair_state": load_repair_state,
}
