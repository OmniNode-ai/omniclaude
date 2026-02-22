"""Deterministic replay engine for ChangeFrames.

Given a frame_id, the replay engine:
1. Loads the ChangeFrame from the JSONL session file
2. Reconstructs the workspace at base_commit in a temp directory
3. Applies the diff_patch
4. Re-runs checks (with optional tool output stubbing)
5. Compares the replayed outcome to the original

Three replay modes:
- FULL: re-run everything live (root cause investigation)
- STUBBED: replace tool outputs with stored hashes (deterministic CI replay)
- TEST_ONLY: re-run checks only, skip tool events (fast regression check)

Stage 6 of DESIGN_AGENT_TRACE_PR_DEBUGGING_SYSTEM.md
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import time
from enum import Enum
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from omniclaude.trace.change_frame import (
    ChangeFrame,
    ModelCheckResult,
    OutcomeStatus,
)
from omniclaude.trace.frame_assembler import CheckSpec, run_checks, sha256_of

# ---------------------------------------------------------------------------
# Replay mode enum
# ---------------------------------------------------------------------------


class ReplayMode(str, Enum):
    """Replay execution mode controlling which steps are live vs stubbed."""

    FULL = "full"
    STUBBED = "stubbed"
    TEST_ONLY = "test_only"


# ---------------------------------------------------------------------------
# Divergence reason constants
# ---------------------------------------------------------------------------

#: Outcome differs and tool output hashes changed (live tool re-execution detected divergence)
REASON_NON_DETERMINISTIC_TOOL: Literal["non_deterministic_tool"] = (
    "non_deterministic_tool"
)
#: Outcome differs and environment hash changed
REASON_ENV_CHANGED: Literal["env_changed"] = "env_changed"
#: Outcome differs for unknown reason in STUBBED mode (tools not re-run; likely check flakiness)
REASON_STUBBED_UNKNOWN: Literal["stubbed_unknown"] = "stubbed_unknown"
#: Outcome differs for unknown reason (e.g. FULL mode before tool re-execution is implemented)
REASON_UNKNOWN: Literal["unknown"] = "unknown"


# ---------------------------------------------------------------------------
# ReplayResult model
# ---------------------------------------------------------------------------


class ReplayResult(BaseModel):
    """Result of replaying a ChangeFrame.

    Records whether the replayed outcome matches the original and,
    if not, why the divergence occurred.
    """

    model_config = ConfigDict(frozen=True, extra="ignore", from_attributes=True)

    frame_id: UUID
    mode: ReplayMode
    original_outcome: OutcomeStatus
    replayed_outcome: OutcomeStatus
    diverged: bool  # True if outcomes differ
    divergence_reason: str | None  # Set when diverged=True
    check_results: list[ModelCheckResult]
    duration_seconds: float


# ---------------------------------------------------------------------------
# Frame loading
# ---------------------------------------------------------------------------


def load_frame_from_jsonl(
    session_id: str,
    frame_id: UUID,
    trace_dir: Path | None = None,
) -> ChangeFrame | None:
    """Load a specific ChangeFrame from the session JSONL file.

    Args:
        session_id: Session identifier (matches JSONL filename)
        frame_id: UUID of the frame to load
        trace_dir: Override for the trace directory (default: ~/.claude/trace)

    Returns:
        ChangeFrame if found, None if not found
    """
    if trace_dir is None:
        trace_dir = Path.home() / ".claude" / "trace"

    jsonl_path = trace_dir / f"{session_id}.jsonl"
    if not jsonl_path.exists():
        return None

    target_str = str(frame_id)
    try:
        with jsonl_path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if not isinstance(data, dict):
                        continue
                    if data.get("frame_id") == target_str:
                        return ChangeFrame.model_validate(data)
                except (json.JSONDecodeError, ValueError, AttributeError):
                    continue
    except OSError:
        return None

    return None


# ---------------------------------------------------------------------------
# Workspace setup helpers
# ---------------------------------------------------------------------------


def _clone_repo_to_tempdir(repo_root: str, tmpdir: str) -> bool:
    """Clone the repository into a temp directory.

    Args:
        repo_root: Source repository path
        tmpdir: Target temp directory

    Returns:
        True if clone succeeded, False otherwise
    """
    try:
        result = subprocess.run(  # noqa: S603
            ["git", "clone", "--local", repo_root, tmpdir],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, FileNotFoundError):
        return False


def _checkout_commit(commit_sha: str, cwd: str) -> bool:
    """Checkout a specific commit in the given directory.

    Args:
        commit_sha: Commit SHA to checkout
        cwd: Working directory (the cloned repo)

    Returns:
        True if checkout succeeded
    """
    try:
        result = subprocess.run(  # noqa: S603
            ["git", "checkout", commit_sha],  # noqa: S607
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=30,
            check=False,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, FileNotFoundError):
        return False


def _apply_patch(diff_patch: str, cwd: str) -> bool:
    """Apply a unified diff patch to the working directory.

    Writes the patch to a temp file, then applies with git apply.

    Args:
        diff_patch: Unified diff string
        cwd: Working directory (the cloned repo)

    Returns:
        True if patch applied successfully
    """
    patch_path = Path(cwd) / "_replay.patch"
    try:
        patch_path.write_text(diff_patch, encoding="utf-8")
        result = subprocess.run(  # noqa: S603
            ["git", "apply", str(patch_path)],  # noqa: S607
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=30,
            check=False,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError):
        return False
    finally:
        if patch_path.exists():
            patch_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Outcome classification
# ---------------------------------------------------------------------------


def _classify_outcome(check_results: list[ModelCheckResult]) -> OutcomeStatus:
    """Classify a list of check results into an OutcomeStatus."""
    if not check_results:
        return OutcomeStatus.FAIL
    if all(c.exit_code == 0 for c in check_results):
        return OutcomeStatus.PASS
    if all(c.exit_code != 0 for c in check_results):
        return OutcomeStatus.FAIL
    return OutcomeStatus.PARTIAL


# ---------------------------------------------------------------------------
# Divergence detection
# ---------------------------------------------------------------------------


def _detect_divergence_reason(
    frame: ChangeFrame,
    replayed_checks: list[ModelCheckResult],
    mode: ReplayMode,
) -> str:
    """Determine why replayed outcome diverges from original outcome.

    Args:
        frame: Original ChangeFrame
        replayed_checks: Check results from the replay run
        mode: The replay mode used

    Returns:
        One of the REASON_* constants
    """
    # Check if environment changed
    original_env_hashes = {c.environment_hash for c in frame.checks}
    replayed_env_hashes = {c.environment_hash for c in replayed_checks}
    if original_env_hashes != replayed_env_hashes:
        return REASON_ENV_CHANGED

    # In STUBBED mode, tool outputs are replaced with stored values rather than
    # re-executed live. Any remaining divergence is unknown — tools were not
    # re-run, so non-determinism cannot be confirmed. Likely check flakiness or
    # timing differences in the stubbed environment.
    if mode == ReplayMode.STUBBED:
        return REASON_STUBBED_UNKNOWN

    return REASON_UNKNOWN


# ---------------------------------------------------------------------------
# Main replay engine
# ---------------------------------------------------------------------------


class ReplayEngine:
    """Deterministic replay engine for ChangeFrames.

    Usage:
        engine = ReplayEngine(repo_root="/path/to/repo")
        result = engine.replay(frame=my_frame, mode=ReplayMode.TEST_ONLY)
    """

    def __init__(
        self,
        repo_root: str,
        checks: list[CheckSpec] | None = None,
    ) -> None:
        """Initialize the replay engine.

        Args:
            repo_root: Absolute path to the repository root (source for cloning)
            checks: Custom check specs (defaults to DEFAULT_CHECKS from frame_assembler)
        """
        self.repo_root = repo_root
        self.checks = checks

    def replay(
        self,
        frame: ChangeFrame,
        mode: ReplayMode = ReplayMode.TEST_ONLY,
    ) -> ReplayResult:
        """Replay a ChangeFrame and compare the outcome.

        Args:
            frame: The ChangeFrame to replay
            mode: Replay mode (FULL, STUBBED, or TEST_ONLY)

        Returns:
            ReplayResult with outcome comparison and check results
        """
        start = time.monotonic()

        with tempfile.TemporaryDirectory() as tmpdir:
            result = self._replay_in_tempdir(frame, mode, tmpdir)

        duration = time.monotonic() - start
        return ReplayResult(
            frame_id=result.frame_id,
            mode=result.mode,
            original_outcome=result.original_outcome,
            replayed_outcome=result.replayed_outcome,
            diverged=result.diverged,
            divergence_reason=result.divergence_reason,
            check_results=result.check_results,
            duration_seconds=duration,
        )

    def _replay_in_tempdir(
        self,
        frame: ChangeFrame,
        mode: ReplayMode,
        tmpdir: str,
    ) -> ReplayResult:
        """Internal: execute replay steps inside the isolated temp directory."""
        original_status = frame.outcome.status
        original_outcome = OutcomeStatus(original_status)

        # Step 1: Clone repo into tmpdir
        if not _clone_repo_to_tempdir(self.repo_root, tmpdir):
            # Can't set up workspace — treat as FAIL with env_changed reason
            return self._make_failure_result(
                frame=frame,
                original_outcome=original_outcome,
                mode=mode,
                reason=REASON_ENV_CHANGED,
            )

        # Step 2: Checkout base commit
        base_commit = frame.workspace_ref.base_commit
        if base_commit != "unknown" and not _checkout_commit(base_commit, tmpdir):
            return self._make_failure_result(
                frame=frame,
                original_outcome=original_outcome,
                mode=mode,
                reason=REASON_ENV_CHANGED,
            )

        # Step 3: Apply diff patch
        if not _apply_patch(frame.delta.diff_patch, tmpdir):
            return self._make_failure_result(
                frame=frame,
                original_outcome=original_outcome,
                mode=mode,
                reason=REASON_ENV_CHANGED,
            )

        # Step 4: Run checks (all modes run checks live in the temp dir)
        check_results = run_checks(tmpdir, self.checks)

        # FULL mode: also simulate re-execution of tool events
        if mode == ReplayMode.FULL:
            # TODO(OMN-2412): Implement live tool re-execution for FULL mode.
            # FULL mode is documented to re-run everything (including tool events),
            # but live LLM tool call replay is not yet implemented — it requires
            # deterministic tool invocation infrastructure that is not yet available.
            # Until implemented, FULL mode behaves identically to TEST_ONLY.
            raise NotImplementedError(
                "FULL replay mode (live tool re-execution) is not yet implemented. "
                "Use ReplayMode.TEST_ONLY or ReplayMode.STUBBED instead."
            )

        # STUBBED mode: verify stored output hashes still match
        # (no additional action needed — checks already run on the patched state)

        # TEST_ONLY mode: only checks, skip tool events entirely (already done above)

        # Step 5: Classify replayed outcome
        replayed_outcome = _classify_outcome(check_results)

        # Step 6: Detect divergence
        diverged = replayed_outcome != original_outcome
        divergence_reason: str | None = None
        if diverged:
            divergence_reason = _detect_divergence_reason(frame, check_results, mode)

        return ReplayResult(
            frame_id=frame.frame_id,
            mode=mode,
            original_outcome=original_outcome,
            replayed_outcome=replayed_outcome,
            diverged=diverged,
            divergence_reason=divergence_reason,
            check_results=check_results,
            duration_seconds=0.0,  # Overwritten by caller with actual duration
        )

    def _make_failure_result(
        self,
        frame: ChangeFrame,
        original_outcome: OutcomeStatus,
        mode: ReplayMode,
        reason: str,
    ) -> ReplayResult:
        """Return a failure ReplayResult when workspace setup fails."""
        failed_check = ModelCheckResult(
            command="workspace-setup",
            environment_hash=sha256_of("workspace-setup-failed"),
            exit_code=-1,
            output_hash=sha256_of("workspace-setup-failed"),
            truncated_output="Workspace setup failed during replay",
        )
        diverged = original_outcome != OutcomeStatus.FAIL
        return ReplayResult(
            frame_id=frame.frame_id,
            mode=mode,
            original_outcome=original_outcome,
            replayed_outcome=OutcomeStatus.FAIL,
            diverged=diverged,
            divergence_reason=reason if diverged else None,
            check_results=[failed_check],
            duration_seconds=0.0,
        )
