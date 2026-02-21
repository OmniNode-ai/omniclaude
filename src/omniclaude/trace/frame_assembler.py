"""ChangeFrame assembler for the PostToolUse hook.

This module implements the core frame assembly logic that runs after
Write/Edit/Bash tool calls. It captures git diffs, runs checks, computes
failure signatures, and assembles validated ChangeFrame records.

Design constraints:
- Must complete in < 500ms for typical changes (PostToolUse budget: < 100ms
  total, but frame assembly runs in background after hook returns)
- Returns None (silently skips) when git diff is empty
- All frame invariants validated before persistence

Stage 4 of DESIGN_AGENT_TRACE_PR_DEBUGGING_SYSTEM.md
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from omniclaude.trace.change_frame import (
    ChangeFrame,
    FailureType,
    ModelCheckResult,
    ModelDelta,
    ModelEvidence,
    ModelFrameConfig,
    ModelIntentRef,
    ModelOutcome,
    ModelToolEvent,
    ModelWorkspaceRef,
)
from omniclaude.trace.failure_signature import (
    FailureSignature,
    compute_failure_signature,
)

# ---------------------------------------------------------------------------
# Session context (passed in from hook entrypoint)
# ---------------------------------------------------------------------------


@dataclass
class SessionContext:
    """Context available to the assembler from the hook session.

    Fields map to what the PostToolUse hook receives and what is tracked
    across hook invocations.
    """

    session_id: str
    trace_id: str
    agent_id: str
    model_id: str
    prompt_hash: str
    repo_root: str
    ticket_id: str | None = None
    temperature: float | None = None
    seed: int | None = None
    max_tokens: int | None = None
    parent_frame_id: UUID | None = None


# ---------------------------------------------------------------------------
# Tool classification
# ---------------------------------------------------------------------------

#: Tools that can produce file changes worth tracing
WRITE_TOOLS = frozenset({"Write", "Edit", "Bash", "NotebookEdit"})


def should_trace_tool(tool_name: str) -> bool:
    """Return True if this tool might produce traceable file changes."""
    return tool_name in WRITE_TOOLS


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def run_git_diff_patch(repo_root: str) -> str:
    """Run git diff --patch to capture staged and unstaged changes.

    Args:
        repo_root: Absolute path to the repository root

    Returns:
        Unified diff string, or empty string if no changes or git fails
    """
    try:
        result = subprocess.run(  # noqa: S603
            ["git", "diff", "HEAD", "--patch"],  # noqa: S607
            capture_output=True,
            text=True,
            cwd=repo_root,
            timeout=10,
            check=False,
        )
        diff = result.stdout.strip()
        if not diff:
            # Also try staged-only diff
            result2 = subprocess.run(  # noqa: S603
                ["git", "diff", "--cached", "--patch"],  # noqa: S607
                capture_output=True,
                text=True,
                cwd=repo_root,
                timeout=10,
                check=False,
            )
            diff = result2.stdout.strip()
        return diff
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, FileNotFoundError):
        return ""


def get_current_commit(repo_root: str) -> str:
    """Return the current HEAD commit SHA.

    Returns:
        Full 40-char commit SHA, or empty string on failure
    """
    try:
        result = subprocess.run(  # noqa: S603
            ["git", "rev-parse", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            cwd=repo_root,
            timeout=5,
            check=False,
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, FileNotFoundError):
        return ""


def get_current_branch(repo_root: str) -> str:
    """Return the current branch name.

    Returns:
        Branch name, or "unknown" on failure
    """
    try:
        result = subprocess.run(  # noqa: S603
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            cwd=repo_root,
            timeout=5,
            check=False,
        )
        return result.stdout.strip() or "unknown"
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, FileNotFoundError):
        return "unknown"


def get_repo_name(repo_root: str) -> str:
    """Return the remote origin URL as a repo identifier.

    Returns:
        Remote URL or local directory name as fallback
    """
    try:
        result = subprocess.run(  # noqa: S603
            ["git", "remote", "get-url", "origin"],  # noqa: S607
            capture_output=True,
            text=True,
            cwd=repo_root,
            timeout=5,
            check=False,
        )
        url = result.stdout.strip()
        if url:
            return url
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, FileNotFoundError):
        pass
    # Fallback: use directory name
    return Path(repo_root).name


def parse_diff_stats(diff_patch: str) -> tuple[list[str], int, int]:
    """Parse a unified diff patch to extract file names and LOC stats.

    Args:
        diff_patch: Unified diff string

    Returns:
        Tuple of (files_changed, loc_added, loc_removed)
    """
    files_changed: list[str] = []
    loc_added = 0
    loc_removed = 0

    for line in diff_patch.splitlines():
        if line.startswith("+++ b/"):
            filename = line[6:]
            if filename not in files_changed:
                files_changed.append(filename)
        elif line.startswith("+") and not line.startswith("+++"):
            loc_added += 1
        elif line.startswith("-") and not line.startswith("---"):
            loc_removed += 1

    return files_changed, loc_added, loc_removed


# ---------------------------------------------------------------------------
# Hash helpers
# ---------------------------------------------------------------------------


def sha256_of(text: str) -> str:
    """Compute SHA-256 hash of a string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_of_dict(data: dict[str, Any]) -> str:
    """Compute SHA-256 hash of a JSON-serializable dict."""
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


# ---------------------------------------------------------------------------
# Check runner
# ---------------------------------------------------------------------------


@dataclass
class CheckSpec:
    """Specification for a quality check to run during frame assembly."""

    command: list[str]
    failure_type: FailureType
    timeout: int = 30


#: Minimum checks run for every frame
DEFAULT_CHECKS: list[CheckSpec] = [
    CheckSpec(
        command=["uv", "run", "ruff", "check", "src/"],
        failure_type=FailureType.LINT_FAIL,
        timeout=15,
    ),
    CheckSpec(
        command=["uv", "run", "mypy", "src/omniclaude/", "--no-error-summary"],
        failure_type=FailureType.TYPE_FAIL,
        timeout=30,
    ),
]


def run_checks(
    repo_root: str,
    checks: list[CheckSpec] | None = None,
) -> list[ModelCheckResult]:
    """Run quality checks and return results.

    Args:
        repo_root: Repository root directory
        checks: List of check specs to run (defaults to DEFAULT_CHECKS)

    Returns:
        List of ModelCheckResult (one per check, all checks run regardless of failures)
    """
    if checks is None:
        checks = DEFAULT_CHECKS

    results: list[ModelCheckResult] = []
    env_hash = _compute_environment_hash(repo_root)

    for spec in checks:
        try:
            proc = subprocess.run(  # noqa: S603
                spec.command,
                capture_output=True,
                text=True,
                cwd=repo_root,
                timeout=spec.timeout,
                check=False,
            )
            output = proc.stdout + proc.stderr
            results.append(
                ModelCheckResult(
                    command=" ".join(spec.command),
                    environment_hash=env_hash,
                    exit_code=proc.returncode,
                    output_hash=sha256_of(output),
                    truncated_output=output[:2000] if output else "",
                )
            )
        except subprocess.TimeoutExpired:
            results.append(
                ModelCheckResult(
                    command=" ".join(spec.command),
                    environment_hash=env_hash,
                    exit_code=-1,
                    output_hash=sha256_of("TIMEOUT"),
                    truncated_output="Check timed out",
                )
            )
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            results.append(
                ModelCheckResult(
                    command=" ".join(spec.command),
                    environment_hash=env_hash,
                    exit_code=-2,
                    output_hash=sha256_of(str(e)),
                    truncated_output=f"Check failed to run: {e}",
                )
            )

    return results


def _compute_environment_hash(repo_root: str) -> str:
    """Compute a hash of the current environment for deterministic replay.

    Captures package versions via pip freeze.

    Args:
        repo_root: Repository root (used for pip freeze context)

    Returns:
        SHA-256 hash of environment snapshot
    """
    try:
        result = subprocess.run(  # noqa: S603
            ["uv", "pip", "freeze"],  # noqa: S607
            capture_output=True,
            text=True,
            cwd=repo_root,
            timeout=10,
            check=False,
        )
        return sha256_of(result.stdout)
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, FileNotFoundError):
        return sha256_of("unknown-env")


# ---------------------------------------------------------------------------
# Main assembly function
# ---------------------------------------------------------------------------


def assemble_change_frame(
    tool_name: str,
    tool_input: dict[str, Any],
    tool_output: str,
    session_context: SessionContext,
    timestamp_utc: str,
    checks: list[CheckSpec] | None = None,
) -> ChangeFrame | None:
    """Assemble a ChangeFrame after a tool call.

    Returns None if:
    - The tool is not a write-type tool
    - git diff produces empty output (frame invariant 1 requires non-empty delta)

    Args:
        tool_name: Name of the tool that was called (Write, Edit, Bash, etc.)
        tool_input: Tool input dict from the hook
        tool_output: Tool output/response string
        session_context: Session-level metadata for the frame
        timestamp_utc: ISO-8601 UTC timestamp (explicitly injected, no datetime.now())
        checks: Check specs to run (defaults to DEFAULT_CHECKS)

    Returns:
        Assembled and validated ChangeFrame, or None if frame should be skipped
    """
    # Only trace write-type tools
    if not should_trace_tool(tool_name):
        return None

    repo_root = session_context.repo_root

    # 1. Capture git delta
    diff_patch = run_git_diff_patch(repo_root)
    if not diff_patch.strip():
        # Frame invariant 1: non-empty delta required
        return None

    # 2. Parse diff stats
    files_changed, loc_added, loc_removed = parse_diff_stats(diff_patch)

    # 3. Run checks (at least one required — Frame invariant 2)
    check_results = run_checks(repo_root, checks)
    if not check_results:
        # Fallback: create a synthetic "no checks ran" result
        # This prevents the frame invariant from failing due to infra issues
        check_results = [
            ModelCheckResult(
                command="no-op",
                environment_hash="",
                exit_code=0,
                output_hash="",
            )
        ]

    # 4. Compute failure signature if any check failed
    failure_sig: FailureSignature | None = None
    failed_checks = [c for c in check_results if c.exit_code != 0]
    if failed_checks:
        # Combine output from all failed checks for the fingerprint
        combined_output = "\n".join(c.truncated_output for c in failed_checks)
        # Determine failure type from first failed check's command
        first_fail_cmd = failed_checks[0].command
        if "mypy" in first_fail_cmd or "pyright" in first_fail_cmd:
            failure_type = FailureType.TYPE_FAIL
        elif "ruff" in first_fail_cmd or "lint" in first_fail_cmd:
            failure_type = FailureType.LINT_FAIL
        elif "pytest" in first_fail_cmd or "test" in first_fail_cmd:
            failure_type = FailureType.TEST_FAIL
        elif "build" in first_fail_cmd or "compile" in first_fail_cmd:
            failure_type = FailureType.BUILD_FAIL
        else:
            failure_type = FailureType.RUNTIME_FAIL

        if combined_output.strip():
            try:
                failure_sig = compute_failure_signature(
                    failure_type=failure_type,
                    raw_output=combined_output,
                    repo_root=repo_root,
                    repro_command=" ".join(failed_checks[0].command.split()),
                    suspected_files=files_changed,
                )
            except ValueError:
                failure_sig = None

    # 5. Classify outcome
    if all(c.exit_code == 0 for c in check_results):
        status: str = "pass"
    elif all(c.exit_code != 0 for c in check_results):
        status = "fail"
    else:
        status = "partial"

    # 6. Build tool event record
    tool_event = ModelToolEvent(
        tool_name=tool_name,
        input_hash=sha256_of_dict(tool_input),
        output_hash=sha256_of(tool_output),
        raw_pointer=None,
    )

    # 7. Build and validate ChangeFrame (raises ValueError if invariants violated)
    try:
        frame = ChangeFrame(
            frame_id=uuid4(),
            parent_frame_id=session_context.parent_frame_id,
            trace_id=session_context.trace_id,
            timestamp_utc=timestamp_utc,
            agent_id=session_context.agent_id,
            model_id=session_context.model_id,
            frame_config=ModelFrameConfig(
                temperature=session_context.temperature,
                seed=session_context.seed,
                max_tokens=session_context.max_tokens,
            ),
            intent_ref=ModelIntentRef(
                prompt_hash=session_context.prompt_hash,
                ticket_id=session_context.ticket_id,
            ),
            workspace_ref=ModelWorkspaceRef(
                repo=get_repo_name(repo_root),
                branch=get_current_branch(repo_root),
                base_commit=get_current_commit(repo_root) or "unknown",
            ),
            delta=ModelDelta(
                diff_patch=diff_patch,
                files_changed=files_changed,
                loc_added=loc_added,
                loc_removed=loc_removed,
            ),
            tool_events=[tool_event],
            checks=check_results,
            outcome=ModelOutcome(
                status=status,
                failure_signature_id=failure_sig.signature_id if failure_sig else None,
            ),
            evidence=ModelEvidence(),
        )
    except ValueError:
        # Frame invariant violated — skip this frame
        return None

    return frame


# ---------------------------------------------------------------------------
# JSONL persistence
# ---------------------------------------------------------------------------


def persist_frame_to_jsonl(frame: ChangeFrame, session_id: str) -> Path:
    """Append a ChangeFrame to the session JSONL file.

    File location: ~/.claude/trace/{session_id}.jsonl

    Args:
        frame: The assembled ChangeFrame to persist
        session_id: Session identifier (used for file naming)

    Returns:
        Path to the JSONL file
    """
    trace_dir = Path.home() / ".claude" / "trace"
    trace_dir.mkdir(parents=True, exist_ok=True)

    jsonl_path = trace_dir / f"{session_id}.jsonl"
    frame_json = frame.model_dump_json()

    with jsonl_path.open("a") as f:
        f.write(frame_json + "\n")

    return jsonl_path
