# Ticket Pipeline Orchestration

You are executing the ticket-pipeline skill. This prompt defines the complete orchestration logic for chaining existing skills into an autonomous per-ticket pipeline.

## Argument Parsing

Parse arguments from the skill invocation:

```
/ticket-pipeline {ticket_id} [--skip-to PHASE] [--dry-run] [--force-run]
```

```python
args = "$ARGUMENTS".split()
if len(args) == 0:
    print("Error: ticket_id is required. Usage: /ticket-pipeline OMN-1234")
    exit(1)
ticket_id = args[0]  # Required: e.g., "OMN-1234"

# Validate ticket_id format
import re
if not re.match(r'^[A-Z]+-\d+$', ticket_id):
    print(f"Error: Invalid ticket_id format '{ticket_id}'. Expected pattern like 'OMN-1234'.")
    exit(1)

dry_run = "--dry-run" in args
force_run = "--force-run" in args

skip_to = None
if "--skip-to" in args:
    idx = args.index("--skip-to")
    if idx + 1 >= len(args) or args[idx + 1].startswith("--"):
        print("Error: --skip-to requires a phase argument (pre_flight|implement|local_review|create_pr|ci_watch|pr_review_loop|auto_merge)")
        exit(1)
    skip_to = args[idx + 1]
    if skip_to not in PHASE_ORDER:
        print(f"Error: Invalid phase '{skip_to}'. Valid: {PHASE_ORDER}")
        exit(1)
```

---

## Pipeline State Schema

State is stored at `~/.claude/pipelines/{ticket_id}/state.yaml`:

```yaml
pipeline_state_version: "2.0"
run_id: "uuid-v4"               # Stable correlation ID for this pipeline run
ticket_id: "OMN-XXXX"
started_by: "user"              # "user" or "agent" (for future team-pipeline)
dry_run: false                  # true if --dry-run mode
policy_version: "2.0"
slack_thread_ts: null           # Placeholder for P0 (threading deferred)

policy:
  auto_advance: true
  auto_commit: true
  auto_push: true
  auto_pr_create: true
  max_review_iterations: 3
  stop_on_major: true
  stop_on_repeat: true
  stop_on_cross_repo: false
  stop_on_invariant: true
  auto_fix_ci: true
  ci_watch_timeout_minutes: 60
  max_ci_fix_cycles: 3
  cap_escalation: "slack_notify_and_continue"

phases:
  pre_flight:
    started_at: null
    completed_at: null
    artifacts: {}
    blocked_reason: null
    block_kind: null             # blocked_human_gate | blocked_policy | blocked_review_limit | failed_exception
    last_error: null
    last_error_at: null
  implement:
    started_at: null
    completed_at: null
    artifacts: {}
    blocked_reason: null
    block_kind: null
    last_error: null
    last_error_at: null
  local_review:
    started_at: null
    completed_at: null
    artifacts: {}
    blocked_reason: null
    block_kind: null
    last_error: null
    last_error_at: null
  create_pr:
    started_at: null
    completed_at: null
    artifacts: {}
    blocked_reason: null
    block_kind: null
    last_error: null
    last_error_at: null
  ci_watch:
    started_at: null
    completed_at: null
    artifacts: {}
    blocked_reason: null
    block_kind: null
    last_error: null
    last_error_at: null
  pr_review_loop:
    started_at: null
    completed_at: null
    artifacts: {}
    blocked_reason: null
    block_kind: null
    last_error: null
    last_error_at: null
  auto_merge:
    started_at: null
    completed_at: null
    artifacts: {}
    blocked_reason: null
    block_kind: null
    last_error: null
    last_error_at: null
```

---

## Initialization

When `/ticket-pipeline {ticket_id}` is invoked:

### 1. Acquire Lock

```python
import os, json, time, uuid, yaml
from pathlib import Path
from datetime import datetime, timezone

PHASE_ORDER = ["pre_flight", "implement", "local_review", "create_pr", "ci_watch", "pr_review_loop", "auto_merge"]

# NOTE: Helper functions (notify_blocked, etc.) are defined in the
# "Helper Functions" section below. They are referenced before their
# definition for readability but must be available before execution.

pipeline_dir = Path.home() / ".claude" / "pipelines" / ticket_id
pipeline_dir.mkdir(parents=True, exist_ok=True)
lock_path = pipeline_dir / "lock"
state_path = pipeline_dir / "state.yaml"

STALE_TTL_SECONDS = 7200  # 2 hours

# NOTE: Lock acquisition is not fully atomic (TOCTOU). Practical mitigation:
# - Only one Claude session should run pipeline for a given ticket
# - Stale TTL (2h) auto-recovers from crashed sessions
# - --force-run allows manual override
# For production use, consider fcntl.flock() or atomic O_EXCL file creation

if lock_path.exists():
    try:
        lock_data = json.loads(lock_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        # Corrupted lock file (e.g., mid-write crash) — break it
        print(f"Warning: Corrupted lock file for {ticket_id}: {e}. Breaking lock.")
        lock_path.unlink(missing_ok=True)
        lock_data = None

    if lock_data is not None:
        lock_age = time.time() - lock_data.get("started_at_epoch", 0)

        if force_run:
            # --force-run: break stale lock
            print(f"Force-run: breaking existing lock (run_id={lock_data.get('run_id')})")
            lock_path.unlink()
        elif lock_age > STALE_TTL_SECONDS:
            # Stale lock: auto-break
            print(f"Stale lock detected ({lock_age:.0f}s old). Breaking automatically.")
            lock_path.unlink()
        elif state_path.exists():
            # Check if same run_id (resume case)
            try:
                existing_state = yaml.safe_load(state_path.read_text())
            except (yaml.YAMLError, OSError) as e:
                print(f"Warning: Corrupted state file for {ticket_id}: {e}. Use --force-run to create fresh state.")
                notify_blocked(ticket_id=ticket_id, reason=f"Corrupted state file: {e}", block_kind="failed_exception")
                exit(1)

            if existing_state.get("run_id") == lock_data.get("run_id"):
                # Same run resuming - OK
                pass
            else:
                # Different run - block
                notify_blocked(
                    ticket_id=ticket_id,
                    reason=f"Pipeline already running (run_id={lock_data.get('run_id')}, pid={lock_data.get('pid')})",
                    block_kind="blocked_policy"
                )
                print(f"Error: Pipeline already running for {ticket_id}. Use --force-run to override.")
                exit(1)
        else:
            notify_blocked(
                ticket_id=ticket_id,
                reason=f"Lock exists but no state file. Use --force-run to override.",
                block_kind="blocked_policy"
            )
            print(f"Error: Lock exists for {ticket_id} but no state file. Use --force-run to override.")
            exit(1)

# Write lock file
run_id = str(uuid.uuid4())[:8]
lock_data = {
    "run_id": run_id,
    "pid": os.getpid(),
    "started_at": datetime.now(timezone.utc).isoformat(),
    "started_at_epoch": time.time(),
    "ticket_id": ticket_id
}
lock_path.write_text(json.dumps(lock_data))
```

### 2. Load or Create State

```python
if state_path.exists() and not force_run:
    # Resume existing pipeline — preserve stable correlation ID
    state = yaml.safe_load(state_path.read_text())

    # Version migration check
    state_version = state.get("pipeline_state_version", "0.0")
    if state_version != "2.0":
        print(f"Warning: State file version {state_version} differs from expected 2.0. "
              f"Pipeline may behave unexpectedly. Use --force-run to create fresh state.")

    # Preserve the stable correlation ID from the existing state.
    # Falls back to the freshly generated run_id only if state lacks one.
    run_id = state.get("run_id", run_id)
    # Update lock to match the (possibly restored) run_id so lock and state stay in sync
    lock_data["run_id"] = run_id
    lock_path.write_text(json.dumps(lock_data))
    print(f"Resuming pipeline for {ticket_id} (run_id: {run_id})")
else:
    # Create new state
    state = {
        "pipeline_state_version": "2.0",
        "run_id": run_id,
        "ticket_id": ticket_id,
        "started_by": "user",
        "dry_run": dry_run,
        "policy_version": "2.0",
        "slack_thread_ts": None,
        "policy": {
            "auto_advance": True,
            "auto_commit": True,
            "auto_push": True,
            "auto_pr_create": True,
            "max_review_iterations": 3,
            "stop_on_major": True,
            "stop_on_repeat": True,
            "stop_on_cross_repo": False,
            "stop_on_invariant": True,
            "auto_fix_ci": True,
            "ci_watch_timeout_minutes": 60,
            "max_ci_fix_cycles": 3,
            "cap_escalation": "slack_notify_and_continue",
        },
        "phases": {
            phase_name: {
                "started_at": None,
                "completed_at": None,
                "artifacts": {},
                "blocked_reason": None,
                "block_kind": None,
                "last_error": None,
                "last_error_at": None,
            }
            for phase_name in PHASE_ORDER
        }
    }
```

### 3. Handle --skip-to (Checkpoint-Validated Resume, OMN-2144)

When `--skip-to` is used, the pipeline validates checkpoints for all prior phases.
This replaces the naive "mark as skipped" approach with structural verification
that prior work actually completed.

```python
if skip_to:
    skip_idx = PHASE_ORDER.index(skip_to)

    for phase_name in PHASE_ORDER[:skip_idx]:
        phase_data = state["phases"][phase_name]

        # If phase is already completed in state, trust it (resume case)
        if phase_data.get("completed_at"):
            print(f"Phase '{phase_name}': already completed at {phase_data['completed_at']}. OK.")
            continue

        # Read checkpoint for this phase
        checkpoint = read_checkpoint(ticket_id, run_id, phase_name)
        if not checkpoint.get("success"):
            print(f"Error: No checkpoint found for phase '{phase_name}'. "
                  f"Cannot skip to '{skip_to}' without completed checkpoints for all prior phases.")
            print(f"Hint: Run the pipeline from the beginning, or use --force-run to start fresh.")
            thread_ts = notify_sync(slack_notifier, "notify_blocked",
                phase=phase_name,
                reason=f"Missing checkpoint for {phase_name} — cannot skip to {skip_to}",
                block_kind="blocked_policy",
                thread_ts=state.get("slack_thread_ts"),
            )
            state["slack_thread_ts"] = thread_ts
            save_state(state, state_path)
            release_lock(lock_path)
            exit(1)

        # Validate the checkpoint structurally
        validation = validate_checkpoint(ticket_id, run_id, phase_name)
        if not validation.get("is_valid"):
            errors = validation.get("errors", ["Unknown validation error"])
            print(f"Error: Checkpoint for '{phase_name}' failed validation: {errors}")
            print(f"Hint: Re-run the pipeline from phase '{phase_name}' to produce a valid checkpoint.")
            thread_ts = notify_sync(slack_notifier, "notify_blocked",
                phase=phase_name,
                reason=f"Checkpoint validation failed for {phase_name}: {errors}",
                block_kind="blocked_policy",
                thread_ts=state.get("slack_thread_ts"),
            )
            state["slack_thread_ts"] = thread_ts
            save_state(state, state_path)
            release_lock(lock_path)
            exit(1)

        # Populate pipeline state from the validated checkpoint
        cp = checkpoint["checkpoint"]
        timestamp_utc = cp.get("timestamp_utc")
        if not timestamp_utc:
            # Fallback: use current time when checkpoint has no timestamp (avoid non-ISO sentinel strings)
            print(f"Warning: Checkpoint for '{phase_name}' is missing 'timestamp_utc'. Using current time as fallback.")
            timestamp_utc = datetime.now(timezone.utc).isoformat()
        phase_data["completed_at"] = timestamp_utc
        phase_data["artifacts"] = extract_artifacts_from_checkpoint(cp)
        save_state(state, state_path)
        print(f"Restored phase '{phase_name}' from checkpoint (attempt {cp.get('attempt_number', '?')})")
```

### 4. Save State and Announce

```python
save_state(state, state_path)

# Determine current phase
current_phase = get_current_phase(state)

dry_label = " [DRY RUN]" if dry_run else ""
print(f"""
## Pipeline Started{dry_label}

**Ticket**: {ticket_id}
**Run ID**: {run_id}
**Current Phase**: {current_phase}
**Policy**: auto_advance={state['policy']['auto_advance']}, max_review_iterations={state['policy']['max_review_iterations']}
""")
```

---

## Helper Functions

### save_state

```python
def save_state(state, state_path):
    """Atomic write of pipeline state."""
    import yaml
    from pathlib import Path

    tmp_path = state_path.with_suffix('.yaml.tmp')
    tmp_path.write_text(yaml.dump(state, default_flow_style=False, sort_keys=False))
    tmp_path.rename(state_path)
```

### get_current_phase

```python
def get_current_phase(state):
    """Return the first phase without completed_at."""
    for phase_name in PHASE_ORDER:
        if not state["phases"][phase_name].get("completed_at"):
            return phase_name
    return "done"  # All phases completed
```

### Pipeline Slack Notifier (OMN-1970)

Replaces the inline `notify_blocked`/`notify_completed` helpers with `PipelineSlackNotifier`
from `plugins/onex/hooks/lib/pipeline_slack_notifier.py`. Provides:
- Correlation-formatted messages: `[OMN-1804][pipeline:local_review][run:abcd-1234]`
- Per-ticket Slack threading via `thread_ts` (requires OMN-2157 for full support)
- Dual-emission: direct Slack delivery + Kafka event for observability
- Dry-run prefixing: `[DRY RUN]` on all messages when `--dry-run`
- Graceful degradation when Slack is not configured

```python
# Initialize at pipeline start (after state is loaded/created)
from pipeline_slack_notifier import PipelineSlackNotifier, notify_sync

slack_notifier = PipelineSlackNotifier(
    ticket_id=ticket_id,
    run_id=run_id,
    dry_run=dry_run,
)

# Send pipeline started notification (seeds the Slack thread)
thread_ts = notify_sync(slack_notifier, "notify_pipeline_started",
                        thread_ts=state.get("slack_thread_ts"))
state["slack_thread_ts"] = thread_ts
save_state(state, state_path)
```

**Notify phase completed:**
```python
thread_ts = notify_sync(slack_notifier, "notify_phase_completed",
    phase=phase_name,
    summary=f"0 blocking, {nit_count} nits",
    thread_ts=state.get("slack_thread_ts"),
    pr_url=result.get("artifacts", {}).get("pr_url"),
)
state["slack_thread_ts"] = thread_ts
save_state(state, state_path)
```

**Notify blocked:**
```python
thread_ts = notify_sync(slack_notifier, "notify_blocked",
    phase=phase_name,
    reason=result.get("reason", "Unknown"),
    block_kind=result.get("block_kind", "failed_exception"),
    thread_ts=state.get("slack_thread_ts"),
)
state["slack_thread_ts"] = thread_ts
save_state(state, state_path)
```

### Cross-Repo Detector (OMN-1970)

Replaces the inline bash cross-repo check with `cross_repo_detector.py`
from `plugins/onex/hooks/lib/cross_repo_detector.py`. Used in Phase 1 (implement).

```python
from cross_repo_detector import detect_cross_repo_changes

if state["policy"]["stop_on_cross_repo"]:
    cross_repo_result = detect_cross_repo_changes()
    if cross_repo_result.violation:
        result = {
            "status": "blocked",
            "block_kind": "blocked_policy",
            "reason": f"Cross-repo change detected: {cross_repo_result.violating_file} resolves outside {cross_repo_result.repo_root}",
            "blocking_issues": 1,
            "nit_count": 0,
            "artifacts": {},
        }
```

### Linear Contract Patcher (OMN-1970)

Replaces inline marker-based patching with `linear_contract_patcher.py`
from `plugins/onex/hooks/lib/linear_contract_patcher.py`. Provides:
- Safe extraction and validation of `## Contract` YAML blocks
- Patch-only updates that preserve human-authored content
- YAML validation before every write
- Separate handler for `## Pipeline Status` blocks

```python
from linear_contract_patcher import (
    extract_contract_yaml,
    patch_contract_yaml,
    patch_pipeline_status,
    validate_contract_yaml,
)

# Read current contract from Linear
issue = mcp__linear-server__get_issue(id=ticket_id)
description = issue["description"] or ""

# Extract and validate
extract_result = extract_contract_yaml(description)
if not extract_result.success:
    # Contract marker missing or malformed — stop pipeline
    notify_sync(slack_notifier, "notify_blocked",
        phase=phase_name,
        reason=f"Linear contract error: {extract_result.error}",
        block_kind="failed_exception",
        thread_ts=state.get("slack_thread_ts"),
    )

# Patch contract safely
patch_result = patch_contract_yaml(description, new_yaml_str)
if patch_result.success:
    mcp__linear-server__update_issue(id=ticket_id, description=patch_result.patched_description)
else:
    # YAML validation failed — do NOT write
    notify_sync(slack_notifier, "notify_blocked",
        phase=phase_name,
        reason=f"Contract YAML validation failed: {patch_result.validation_error}",
        block_kind="failed_exception",
        thread_ts=state.get("slack_thread_ts"),
    )

# Update pipeline status (separate from contract)
status_result = patch_pipeline_status(description, status_yaml_str)
if status_result.success:
    mcp__linear-server__update_issue(id=ticket_id, description=status_result.patched_description)
```

### Checkpoint Helpers (OMN-2144)

Checkpoint operations delegate to `checkpoint_manager.py` via Bash.  All checkpoint
writes are **non-blocking**: failures log a warning but never stop the pipeline.

```python
import subprocess, sys

_plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
if _plugin_root:
    _CHECKPOINT_MANAGER = Path(_plugin_root) / "hooks" / "lib" / "checkpoint_manager.py"
else:
    # Hardcoded known location relative to home when CLAUDE_PLUGIN_ROOT is not set
    _CHECKPOINT_MANAGER = Path.home() / ".claude" / "plugins" / "onex" / "hooks" / "lib" / "checkpoint_manager.py"


def write_checkpoint(ticket_id, run_id, phase_name, attempt_number, repo_commit_map, artifact_paths, phase_payload):
    """Write a checkpoint after a phase completes.  Non-blocking on failure.

    Args:
        artifact_paths: list[str] of relative file-system paths for generated outputs
            (e.g., ["reports/review.md", "coverage/lcov.info"]).  Each entry is a path
            on disk -- NOT a dictionary, not commit hashes, and not code-state references.
        repo_commit_map: dict[str, str] mapping repository names to commit SHAs
            (e.g., {"omniclaude": "abc1234"}).  Tracks the code state at checkpoint time.
            This is the correct place for commit hashes -- distinct from artifact_paths.
        phase_payload: dict of structured metadata about the phase execution (e.g.,
            pr_url, branch_name, iteration_count).  Schema varies per phase -- see
            build_phase_payload().
    """
    try:
        cmd = [
            sys.executable, str(_CHECKPOINT_MANAGER), "write",
            "--ticket-id", ticket_id,
            "--run-id", run_id,
            "--phase", phase_name,
            "--attempt", str(attempt_number),
            "--repo-commit-map", json.dumps(repo_commit_map),
            "--artifact-paths", json.dumps(artifact_paths),
            "--payload", json.dumps(phase_payload),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        # checkpoint_manager.py always returns exit code 0; success/failure is
        # encoded in JSON stdout.  Parse stdout to determine the outcome.
        _cp_result = json.loads(proc.stdout) if proc.stdout.strip() else {}
        if _cp_result.get("success", False):
            print(f"Checkpoint written for phase '{phase_name}' (attempt {attempt_number}): {_cp_result.get('checkpoint_path', 'ok')}")
            return _cp_result
        else:
            print(f"Warning: Checkpoint write failed for phase '{phase_name}': {_cp_result.get('error', proc.stderr or 'unknown')}")
            return {"success": False, "error": _cp_result.get("error", proc.stderr or "unknown")}
    except Exception as e:
        print(f"Warning: Checkpoint write failed for phase '{phase_name}': {e}")
        return {"success": False, "error": str(e)}


def read_checkpoint(ticket_id, run_id, phase_name):
    """Read the latest checkpoint for a phase.  Returns parsed JSON result."""
    try:
        cmd = [
            sys.executable, str(_CHECKPOINT_MANAGER), "read",
            "--ticket-id", ticket_id,
            "--run-id", run_id,
            "--phase", phase_name,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if proc.returncode != 0:
            return {"success": False, "error": f"checkpoint read failed: {proc.stdout or proc.stderr}"}
        return json.loads(proc.stdout)
    except Exception as e:
        return {"success": False, "error": str(e)}


def validate_checkpoint(ticket_id, run_id, phase_name):
    """Validate a checkpoint structurally.  Returns parsed JSON result."""
    try:
        cmd = [
            sys.executable, str(_CHECKPOINT_MANAGER), "validate",
            "--ticket-id", ticket_id,
            "--run-id", run_id,
            "--phase", phase_name,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if proc.returncode != 0:
            return {"is_valid": False, "errors": [f"validation failed: {proc.stdout or proc.stderr}"]}
        return json.loads(proc.stdout)
    except Exception as e:
        return {"success": False, "is_valid": False, "errors": [str(e)]}


def get_head_sha():
    """Return the short HEAD SHA, or '0000000' on failure."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short=7", "HEAD"], text=True
        ).strip()
    except Exception:
        return "0000000"


def get_current_branch():
    """Return current git branch name, or 'unknown' on failure."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            text=True, timeout=5
        ).strip()
    except (subprocess.SubprocessError, OSError):
        return "unknown"


def build_phase_payload(phase_name, state, result):
    """Build the phase-specific payload dict from pipeline state and phase result.

    Each phase has a different payload schema.  This helper constructs the correct
    dict based on the phase name and available data.
    """
    artifacts = result.get("artifacts", {})
    head_sha = get_head_sha()

    if phase_name == "implement":
        branch = get_current_branch()
        return {
            "branch_name": artifacts.get("branch_name", branch),
            "commit_sha": head_sha,
            "files_changed": list(artifacts.get("files_changed", [])),
        }

    elif phase_name == "local_review":
        return {
            "iteration_count": artifacts.get("iterations", 1),
            "issue_fingerprints": list(artifacts.get("issue_fingerprints", [])),
            "last_clean_sha": head_sha,
        }

    elif phase_name == "create_pr":
        return {
            "pr_url": artifacts.get("pr_url", ""),
            "pr_number": artifacts.get("pr_number", 0),
            "head_sha": head_sha,
        }

    elif phase_name == "ci_watch":
        return {
            "status": artifacts.get("status", ""),
            "ci_fix_cycles_used": artifacts.get("ci_fix_cycles_used", 0),
            "watch_duration_minutes": artifacts.get("watch_duration_minutes", 0),
        }

    elif phase_name in ("pr_review_loop", "auto_merge", "pre_flight"):
        # Placeholder phases — return minimal payload
        return {
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }

    print(f"Warning: build_phase_payload called with unrecognized phase '{phase_name}'. Returning empty payload.")
    return {}


def get_checkpoint_attempt_number(ticket_id, run_id, phase_name):
    """Count existing checkpoints for a phase and return next attempt number."""
    try:
        list_result_raw = subprocess.run(
            [sys.executable, str(_CHECKPOINT_MANAGER), "list",
             "--ticket-id", ticket_id, "--run-id", run_id],
            capture_output=True, text=True, timeout=30,
        )
        if list_result_raw.returncode != 0:
            print(f"Warning: checkpoint list failed for phase '{phase_name}': {list_result_raw.stdout or list_result_raw.stderr}")
            return 1
        list_result = json.loads(list_result_raw.stdout)
        if list_result.get("success"):
            count = sum(
                1 for cp in list_result.get("checkpoints", [])
                if cp.get("phase") == phase_name
            )
            return count + 1
    except Exception as e:
        print(f"Warning: checkpoint attempt number lookup failed for phase '{phase_name}': {e}")
    return 1


def extract_artifacts_from_checkpoint(checkpoint_data):
    """Extract pipeline-compatible artifacts dict from a checkpoint's phase_payload."""
    payload = checkpoint_data.get("phase_payload", {})
    phase = checkpoint_data.get("phase", "")
    artifacts = {}

    if phase == "implement":
        artifacts["branch_name"] = payload.get("branch_name", "")
        artifacts["commit_sha"] = payload.get("commit_sha", "")
        artifacts["files_changed"] = payload.get("files_changed", [])
    elif phase == "local_review":
        artifacts["iterations"] = payload.get("iteration_count", 1)
        artifacts["last_clean_sha"] = payload.get("last_clean_sha", "")
    elif phase == "create_pr":
        artifacts["pr_url"] = payload.get("pr_url", "")
        artifacts["pr_number"] = payload.get("pr_number", 0)
    elif phase == "ci_watch":
        artifacts["status"] = payload.get("status", "")
        artifacts["ci_fix_cycles_used"] = payload.get("ci_fix_cycles_used", 0)
        artifacts["watch_duration_minutes"] = payload.get("watch_duration_minutes", 0)

    return artifacts
```

### get_current_repo

```python
def get_current_repo():
    """Extract repo name from current working directory."""
    import os
    return os.path.basename(os.getcwd())
```

### update_linear_pipeline_summary

Updates the Linear ticket with a compact pipeline summary. Now delegates to
`linear_contract_patcher.patch_pipeline_status()` for safe marker-based patching (OMN-1970).

```python
def update_linear_pipeline_summary(ticket_id, state, dry_run=False, slack_notifier=None):
    """Mirror compact pipeline state to Linear ticket description.

    Safety (delegated to linear_contract_patcher):
    - Uses marker-based patching (## Pipeline Status section)
    - Validates YAML before write
    - Preserves all existing description content outside markers
    - If markers missing, appends new section (never rewrites full description)
    - If dry_run=True, skips the actual Linear update
    """
    import yaml
    from linear_contract_patcher import patch_pipeline_status
    from pipeline_slack_notifier import notify_sync

    if dry_run:
        print("[DRY RUN] Skipping Linear pipeline summary update")
        return

    current_phase = get_current_phase(state)
    blocked = None
    for phase_name, phase_data in state["phases"].items():
        if phase_data.get("blocked_reason"):
            blocked = f"{phase_name}: {phase_data['blocked_reason']}"
            break

    summary_yaml = f"""run_id: "{state['run_id']}"
phase: "{current_phase}"
blocked_reason: {f'"{blocked}"' if blocked else 'null'}
artifacts:"""

    # Collect artifacts from all completed phases
    for phase_name, phase_data in state["phases"].items():
        if phase_data.get("artifacts"):
            for key, value in phase_data["artifacts"].items():
                if key != "skipped":
                    summary_yaml += f'\n  {phase_name}_{key}: "{value}"'

    if not any(pd.get("artifacts") for pd in state["phases"].values()):
        summary_yaml += " {}"

    # Fetch current description
    try:
        issue = mcp__linear-server__get_issue(id=ticket_id)
        description = issue["description"] or ""
    except Exception as e:
        print(f"Warning: Failed to fetch Linear issue {ticket_id}: {e}")
        return  # Non-blocking: Linear is not critical path

    # Use linear_contract_patcher for safe patching
    result = patch_pipeline_status(description, summary_yaml)
    if not result.success:
        print(f"Warning: Pipeline status patch failed: {result.error}")
        if slack_notifier:
            notify_sync(slack_notifier, "notify_blocked",
                phase=current_phase,
                reason=f"Pipeline status YAML validation failed: {result.validation_error or result.error}",
                block_kind="failed_exception",
                thread_ts=state.get("slack_thread_ts"),
            )
        return  # Do not write invalid YAML

    try:
        mcp__linear-server__update_issue(id=ticket_id, description=result.patched_description)
    except Exception as e:
        print(f"Warning: Failed to update Linear issue {ticket_id}: {e}")
        # Non-blocking: Linear update failure is logged but does not stop pipeline
```

### parse_phase_output

Parses the output of upstream skills into a structured phase result.

```python
def parse_phase_output(raw_output, phase_name):
    """Parse phase output into structured result.

    Expected schema:
        status: completed | blocked | failed
        blocking_issues: int
        nit_count: int
        artifacts: dict
        reason: str | None
        block_kind: str | None  (blocked_human_gate | blocked_policy | blocked_review_limit | failed_exception)

    Since upstream skills (ticket-work, local-review) don't return
    structured output yet, this adapter infers status from observable signals.

    KNOWN LIMITATION: This is fragile string parsing. Expected output format contract:
    - Local-review outputs status lines like "Clean - Confirmed (N/N clean runs)" or
      "Clean with nits - Confirmed (N/N clean runs)" (deterministic 2-clean-run gate, OMN-2327)
    - Blocked states should mention "blocked by", "max iterations", or "waiting for"
    - Error states should include "error", "failed", or "parse failed"
    If no recognized pattern is found, defaults to "failed" status.
    """
    import re

    result = {
        "status": "completed",
        "blocking_issues": 0,
        "nit_count": 0,
        "artifacts": {},
        "reason": None,
        "block_kind": None,
    }

    if raw_output is None:
        result["status"] = "failed"
        result["reason"] = "No output received from phase"
        result["block_kind"] = "failed_exception"
        return result

    output_lower = raw_output.lower() if isinstance(raw_output, str) else ""

    # Detect blocked states
    if "blocked by" in output_lower or "max iterations reached" in output_lower:
        result["status"] = "blocked"
        result["block_kind"] = "blocked_review_limit"
        # Try to extract issue count
        count_match = re.search(r'(\d+)\s+blocking\s+issues?\s+remain', output_lower)
        if count_match:
            result["blocking_issues"] = int(count_match.group(1))
        result["reason"] = "Review iteration limit reached with blocking issues remaining"

    elif "waiting for" in output_lower or ("human" in output_lower and "gate" in output_lower):
        result["status"] = "blocked"
        result["block_kind"] = "blocked_human_gate"
        result["reason"] = "Waiting for human input"

    elif "error" in output_lower or "failed" in output_lower or "parse failed" in output_lower:
        result["status"] = "failed"
        result["block_kind"] = "failed_exception"
        result["reason"] = "Phase execution failed"

    # Extract nit count
    nit_match = re.search(r'nits?\s*(?:deferred|remaining)?:?\s*(\d+)', output_lower)
    if nit_match:
        result["nit_count"] = int(nit_match.group(1))

    # Extract status indicators from local-review output
    # OMN-2327: local-review now outputs "Clean - Confirmed (N/N clean runs)" and
    # "Clean with nits - Confirmed (N/N clean runs)" from the deterministic 2-clean-run gate.
    if "confirmed (" in output_lower:
        # Covers both "Clean - Confirmed (...)" and "Clean with nits - Confirmed (...)"
        # The trailing open-paren avoids false positives from casual uses of "confirmed"
        # (e.g., "user confirmed the spec") by matching only the gate format
        # "Confirmed (N/N clean runs)".
        result["status"] = "completed"
        result["blocking_issues"] = 0
        result["block_kind"] = None
        result["reason"] = None
        # Extract quality_gate info from confirmed status for Phase 4 validation
        gate_match = re.search(r'confirmed\s*\((\d+)/(\d+)\s*clean\s*runs?\)', output_lower)
        if gate_match:
            actual_runs = int(gate_match.group(1))
            required_runs = int(gate_match.group(2))
            result["artifacts"]["quality_gate"] = {
                "status": "passed",
                "consecutive_clean_runs": actual_runs,
                "required_clean_runs": required_runs,
            }

    # Backwards-compatibility branch for pre-OMN-2327 output that doesn't include
    # "Confirmed (N/N clean runs)".  New-format output like
    # "Clean with nits - Confirmed (2/2 clean runs)" matches "confirmed (" above,
    # so this branch only triggers for old-format "clean with nits" without a
    # confirmation suffix.  Intentionally does not populate quality_gate — the
    # Phase 4 fallback handles that case.
    elif "clean with nits" in output_lower:
        result["status"] = "completed"
        result["blocking_issues"] = 0

    # If no known status indicator was found and status is still "completed" (default),
    # check if the output contains enough signal to confirm success
    if result["status"] == "completed" and output_lower:
        # Only return "completed" if we found positive confirmation
        if not any(indicator in output_lower for indicator in [
            "confirmed (", "clean with nits",
            "report only", "changes staged", "completed", "success", "ready"
        ]):
            result["status"] = "failed"
            result["block_kind"] = "failed_exception"
            result["reason"] = "Could not determine phase status from output (no recognized status indicator)"

    return result
```

---

## Phase Execution Loop

After initialization, execute phases in order:

```python
for phase_name in PHASE_ORDER:
    phase_data = state["phases"][phase_name]

    # Skip completed phases (resume semantics)
    if phase_data.get("completed_at"):
        print(f"Phase {phase_name}: already completed at {phase_data['completed_at']}. Skipping.")
        continue

    # Execute phase
    print(f"\n## Phase: {phase_name}\n")
    phase_data["started_at"] = datetime.now(timezone.utc).isoformat()
    save_state(state, state_path)

    # NOTE: Phase execution has no explicit timeout. The stale lock TTL (2h)
    # serves as an implicit upper bound. For future: add policy.phase_timeout_seconds
    # and enforce with signal.alarm() or threading.Timer.
    try:
        result = execute_phase(phase_name, state)
    except Exception as e:
        phase_data["last_error"] = str(e)
        phase_data["last_error_at"] = datetime.now(timezone.utc).isoformat()
        phase_data["block_kind"] = "failed_exception"
        phase_data["blocked_reason"] = str(e)
        save_state(state, state_path)

        # OMN-1970: Use PipelineSlackNotifier for threaded notifications
        thread_ts = notify_sync(slack_notifier, "notify_blocked",
            phase=phase_name,
            reason=f"Phase {phase_name} failed: {e}",
            block_kind="failed_exception",
            thread_ts=state.get("slack_thread_ts"),
        )
        state["slack_thread_ts"] = thread_ts
        save_state(state, state_path)
        update_linear_pipeline_summary(ticket_id, state, dry_run, slack_notifier=slack_notifier)
        print(f"\nPipeline stopped at {phase_name}: {e}")
        release_lock(lock_path)
        exit(1)

    # Handle phase result
    if result["status"] == "completed":
        phase_data["completed_at"] = datetime.now(timezone.utc).isoformat()
        phase_data["artifacts"].update(result.get("artifacts", {}))
        save_state(state, state_path)

        # OMN-2144: Write checkpoint after phase completion (non-blocking)
        try:
            attempt_num = get_checkpoint_attempt_number(ticket_id, run_id, phase_name)
            repo_name = get_current_repo()
            head_sha = get_head_sha()
            phase_payload = build_phase_payload(phase_name, state, result)
            write_checkpoint(
                ticket_id=ticket_id,
                run_id=run_id,
                phase_name=phase_name,
                attempt_number=attempt_num,
                repo_commit_map={repo_name: head_sha},
                artifact_paths=[],  # artifact_paths is for file-level outputs (e.g., generated reports); pipeline metadata lives in phase_payload
                phase_payload=phase_payload,
            )
        except Exception as cp_err:
            print(f"Warning: Checkpoint write failed for phase '{phase_name}': {cp_err}")
            # Non-blocking: checkpoint failure does not stop the pipeline

        # OMN-1970: Use PipelineSlackNotifier for threaded notifications
        thread_ts = notify_sync(slack_notifier, "notify_phase_completed",
            phase=phase_name,
            summary=f"Phase {phase_name} completed",
            thread_ts=state.get("slack_thread_ts"),
            pr_url=result.get("artifacts", {}).get("pr_url"),
            nit_count=result.get("nit_count", 0),
            blocking_count=result.get("blocking_issues", 0),
        )
        state["slack_thread_ts"] = thread_ts
        save_state(state, state_path)
        update_linear_pipeline_summary(ticket_id, state, dry_run, slack_notifier=slack_notifier)

        # Check auto_advance policy
        if not state["policy"]["auto_advance"]:
            print(f"Phase {phase_name} completed. auto_advance=false, stopping.")
            release_lock(lock_path)
            exit(0)

        # Continue to next phase
        continue

    elif result["status"] in ("blocked", "failed"):
        phase_data["blocked_reason"] = result.get("reason", "Unknown")
        phase_data["block_kind"] = result.get("block_kind", "failed_exception")
        phase_data["last_error"] = result.get("reason")
        phase_data["last_error_at"] = datetime.now(timezone.utc).isoformat()
        save_state(state, state_path)

        # OMN-1970: Use PipelineSlackNotifier for threaded notifications
        thread_ts = notify_sync(slack_notifier, "notify_blocked",
            phase=phase_name,
            reason=result.get("reason", "Unknown"),
            block_kind=result.get("block_kind", "failed_exception"),
            thread_ts=state.get("slack_thread_ts"),
        )
        state["slack_thread_ts"] = thread_ts
        save_state(state, state_path)
        update_linear_pipeline_summary(ticket_id, state, dry_run, slack_notifier=slack_notifier)

        print(f"\nPipeline stopped at {phase_name}: {result.get('reason')}")
        # Do NOT release lock on block/fail - preserves state for resume
        exit(1)

# All phases completed
print(f"\nPipeline completed for {ticket_id}!")
release_lock(lock_path)
```

### release_lock

```python
def release_lock(lock_path):
    """Release pipeline lock. Only called on clean stop."""
    try:
        lock_path.unlink(missing_ok=True)
    except OSError:
        pass  # Best-effort
```

### execute_phase

```python
def execute_phase(phase_name, state):
    """Dispatch to the appropriate phase handler.

    Each phase handler returns a result dict with:
        status: completed | blocked | failed
        blocking_issues: int
        nit_count: int
        artifacts: dict
        reason: str | None
        block_kind: str | None
    """
    handlers = {
        "pre_flight": execute_pre_flight,
        "implement": execute_implement,
        "local_review": execute_local_review,
        "create_pr": execute_create_pr,
        "ci_watch": execute_ci_watch,
        "pr_review_loop": execute_pr_review_loop,
        "auto_merge": execute_auto_merge,
    }

    handler = handlers.get(phase_name)
    if handler is None:
        return {
            "status": "failed",
            "blocking_issues": 0,
            "nit_count": 0,
            "artifacts": {},
            "reason": f"Unknown phase: {phase_name}",
            "block_kind": "failed_exception",
        }

    return handler(state)
```

---

## Phase Handlers

### Phase 1: IMPLEMENT

**Invariants:**
- Pipeline is initialized with valid ticket_id
- Lock is acquired

**Actions:**

1. **Dispatch ticket-work to a separate agent:**
   ```
   Task(
     subagent_type="onex:polymorphic-agent",
     description="Implement {ticket_id}: {title}",
     prompt="You are executing ticket-work for {ticket_id}.
       Invoke: Skill(skill=\"onex:ticket-work\", args=\"{ticket_id} --autonomous\")

       Ticket: {ticket_id} - {title}
       Description: {description}
       Branch: {branch_name}
       Repo: {repo_path}

       Execute the full ticket-work workflow (intake -> research -> questions -> spec -> implementation).
       Do NOT commit changes -- the orchestrator handles git operations.
       Report back with: files changed, tests run, any blockers encountered."
   )
   ```
   This spawns a polymorphic agent with its own context window to run the full ticket-work
   workflow including human gates (questions, spec, approval). The pipeline waits for the
   agent to complete and reads its result.

2. **Cross-repo check** (if `policy.stop_on_cross_repo == true`):
   After ticket-work completes, use the `cross_repo_detector` module (OMN-1970):
   ```python
   from cross_repo_detector import detect_cross_repo_changes

   if state["policy"]["stop_on_cross_repo"]:
       cross_repo_result = detect_cross_repo_changes()
       if cross_repo_result.error:
           print(f"Warning: Cross-repo detection failed: {cross_repo_result.error}")
           # Non-blocking error: log but don't stop pipeline
       elif cross_repo_result.violation:
           result = {
               "status": "blocked",
               "block_kind": "blocked_policy",
               "reason": f"Cross-repo change detected: {cross_repo_result.violating_file} resolves outside {cross_repo_result.repo_root}",
               "blocking_issues": 1,
               "nit_count": 0,
               "artifacts": {}
           }
           return result
   ```

3. **Verify implementation is complete:**
   Check the ticket-work contract to confirm implementation phase is done:
   - Ticket contract phase should be `review` or `done`
   - At least one commit exists in the contract

4. **On success:**
   ```python
   result = {
       "status": "completed",
       "blocking_issues": 0,
       "nit_count": 0,
       "artifacts": {"commits": "N commits from ticket-work"},
       "reason": None,
       "block_kind": None
   }
   ```

5. **Dry-run behavior:** In dry-run mode, Phase 1 runs ticket-work normally (including human gates) because ticket-work does not support a dry-run flag. The pipeline tracks state as `dry_run: true` but cannot prevent ticket-work from making commits. Dry-run is fully effective starting from Phase 2 onward. To safely dry-run Phase 1, run `/ticket-work` separately first, then use `--skip-to local_review --dry-run`.

**Mutations:**
- `phases.implement.started_at`
- `phases.implement.completed_at`
- `phases.implement.artifacts`

**Exit conditions:**
- **Completed:** ticket-work finishes, cross-repo check passes
- **Blocked (human gate):** ticket-work waiting for human input
- **Blocked (policy):** cross-repo violation detected
- **Failed:** ticket-work errors out

---

### Phase 2: LOCAL REVIEW

**Invariants:**
- Phase 1 (implement) is completed
- Working directory has changes to review

**Actions:**

1. **Dispatch local-review to a separate agent:**
   ```
   Task(
     subagent_type="onex:polymorphic-agent",
     description="Local review for {ticket_id}",
     prompt="You are executing local-review for {ticket_id}.
       Invoke: Skill(skill=\"onex:local-review\", args=\"--max-iterations {max_review_iterations} --required-clean-runs 1\")

       Branch: {branch_name}
       Repo: {repo_path}
       Previous phase: implementation complete

       Execute the local review loop.
       Do NOT commit changes -- the orchestrator handles git operations.
       Report back with:
       - Number of iterations completed
       - Blocking issues found (count and descriptions)
       - Whether review passed (0 blocking issues)"
   )
   ```

2. **Parse result:**
   Use `parse_phase_output()` on the local-review output to determine:
   - `status`: completed (clean) or blocked (issues remain)
   - `blocking_issues`: count of remaining critical/major/minor
   - `nit_count`: count of remaining nits
   - `artifacts`: commits made, iterations run

3. **Policy checks:**
   - If `blocking_issues > 0`: status = blocked, block_kind = "blocked_review_limit"
   - If parse fails: status = failed, block_kind = "failed_exception", reason = "Could not parse local-review output"

4. **Dry-run behavior:** local-review runs normally (reviews code), but any commits are skipped (`--no-commit` implied). The review output is still parsed for status determination.

**Mutations:**
- `phases.local_review.started_at`
- `phases.local_review.completed_at`
- `phases.local_review.artifacts` (iterations, commits, blocking_remaining, nit_count)

**Exit conditions:**
- **Completed:** 0 blocking issues (nits OK)
- **Blocked:** blocking issues remain after max iterations
- **Failed:** local-review errors out or output parse failure

---

### Phase 3: CREATE PR

**Invariants:**
- Phase 2 (local_review) is completed
- `policy.auto_push == true` AND `policy.auto_pr_create == true` (checked before acting)

**Actions:**

1. **Policy check:**
   ```python
   if not state["policy"]["auto_push"]:
       result = {"status": "blocked", "block_kind": "blocked_policy",
                 "reason": "auto_push=false, manual push required"}
       return result

   if not state["policy"]["auto_pr_create"]:
       result = {"status": "blocked", "block_kind": "blocked_policy",
                 "reason": "auto_pr_create=false, manual PR creation required"}
       return result
   ```

2. **Pre-checks (idempotent):**

   a. **Check for existing PR on current branch:**
   ```bash
   gh pr view --json url,number 2>/dev/null
   ```
   If PR exists: skip creation, record artifacts, advance.
   ```python
   # If PR exists: skip creation, record artifacts, advance
   if pr_exists:
       pr_info = json.loads(pr_check_output)
       result["artifacts"]["pr_url"] = pr_info["url"]
       result["artifacts"]["pr_number"] = pr_info["number"]
       result["artifacts"]["branch_name"] = branch_name
       result["status"] = "completed"
       print(f"PR already exists: {pr_info['url']}. Skipping creation.")
       return result
   ```

   b. **Clean working tree:**
   ```bash
   git status --porcelain
   ```
   If dirty: block with reason "Working tree is not clean. Commit or stash changes first."

   c. **Branch tracks remote:**
   ```bash
   git rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null
   ```
   If no upstream: will be set by `git push -u`.

   d. **Branch name pattern:**
   ```bash
   BRANCH=$(git rev-parse --abbrev-ref HEAD)
   ```
   Validate: matches `{user}/omn-{number}-*` pattern (case-insensitive).
   If mismatch: block with reason "Branch name does not match expected pattern."

   e. **GitHub auth:**
   ```bash
   gh auth status
   ```
   If not authenticated: block with reason "GitHub CLI not authenticated."

   f. **Git remote:**
   ```bash
   git remote get-url origin
   ```
   If no origin: block with reason "No git remote 'origin' configured."

   g. **Realm/topic naming invariant** (if `policy.stop_on_invariant == true`):
   ```bash
   # Check if any changed files are topic/constant files
   CHANGED=$(git diff --name-only origin/main...HEAD)
   TOPIC_FILES=$(echo "$CHANGED" | grep -E '(topics?|constants?)\.py$' || true)

   if [ -n "$TOPIC_FILES" ]; then
       # Check for hardcoded 'dev.' prefix in topic constants
       # Use while-read to handle filenames with spaces safely
       # NOTE: Requires bash (uses PIPESTATUS). Script should use #!/usr/bin/env bash.
       # Detect hardcoded 'dev.' environment prefix in topic/constant files.
       # Topic constants should use KAFKA_ENVIRONMENT variable, not literal 'dev.' prefix.
       # Flag ANY non-comment line containing 'dev.' — both quoted and unquoted forms.
       INVARIANT_FAILED=0
       echo "$TOPIC_FILES" | while IFS= read -r f; do
           [ -z "$f" ] && continue
           # Intentionally matches both quoted and unquoted 'dev.' — topic constants
           # should use KAFKA_ENVIRONMENT variable, never a hardcoded env prefix.
           # Match 'dev.' on non-comment lines (skip lines starting with #)
           if grep -Eq '^[^#]*dev\.' "$f" 2>/dev/null; then
               echo "INVARIANT_VIOLATION: Hardcoded 'dev.' prefix in $f"
               exit 1
           fi
       done
       # Propagate subshell exit code from pipe (bash-specific PIPESTATUS)
       if [ "${PIPESTATUS[1]:-0}" -ne 0 ]; then
           exit 1
       fi
   fi
   ```
   If violation: block with reason "Topic naming invariant violation: hardcoded 'dev.' prefix detected."

3. **Push and create PR:**
   ```bash
   # Fetch latest remote state
   git fetch origin

   # Check if branch exists on remote and has diverged
   BRANCH=$(git rev-parse --abbrev-ref HEAD)
   if git rev-parse --verify "origin/$BRANCH" >/dev/null 2>&1; then
       # Remote branch exists — check if we're ahead
       if ! git merge-base --is-ancestor "origin/$BRANCH" HEAD; then
           echo "Error: Remote branch has diverged. Pull or rebase before pushing."
           exit 1
       fi
   fi

   # Push branch (safe — we verified no divergence above)
   git push -u origin HEAD

   # NOTE: The following is a bash command sequence for the agent to execute
   # via the Bash tool. Variables like $TICKET_ID are set from pipeline state above.
   # Create PR — use shell variables (not heredoc with 'EOF' which prevents expansion)
   TICKET_ID="{ticket_id}"   # Set from pipeline state
   TICKET_TITLE="{ticket_title}"  # Fetched from Linear
   RUN_ID="{run_id}"         # From pipeline state
   BASE_REF=$(git merge-base origin/main HEAD)
   COMMIT_SUMMARY=$(git log --oneline "$BASE_REF"..HEAD)

   gh pr create \
     --title "feat($TICKET_ID): $TICKET_TITLE" \
     --body "$(cat <<EOF
## Summary

Automated PR created by ticket-pipeline.

**Ticket**: $TICKET_ID
**Pipeline Run**: $RUN_ID

## Changes

$COMMIT_SUMMARY

## Test Plan

- [ ] CI passes
- [ ] CodeRabbit review addressed
EOF
)"
   ```

4. **Update Linear:**
   ```python
   try:
       mcp__linear-server__update_issue(id=ticket_id, state="In Review")
   except Exception as e:
       print(f"Warning: Failed to update Linear issue {ticket_id}: {e}")
       # Non-blocking: Linear update failure is logged but does not stop pipeline
   ```

5. **Record artifacts:**
   ```python
   pr_info = json.loads(subprocess.check_output(["gh", "pr", "view", "--json", "url,number"]))
   result["artifacts"] = {
       "pr_url": pr_info["url"],
       "pr_number": pr_info["number"],
       "branch_name": branch_name
   }
   ```

6. **Dry-run behavior:** All pre-checks execute normally. Push, PR creation, and Linear update are skipped. State records what _would_ have happened.

**Mutations:**
- `phases.create_pr.started_at`
- `phases.create_pr.completed_at`
- `phases.create_pr.artifacts` (pr_url, pr_number, branch_name)

**Exit conditions:**
- **Completed:** PR created (or already exists) and Linear updated
- **Blocked (policy):** auto_push or auto_pr_create is false
- **Blocked (pre-check):** any pre-check fails
- **Failed:** push or PR creation errors

---

### Phase 0: PRE_FLIGHT

**Invariants:**
- Pipeline lock is acquired
- Working directory is clean checkout

**Actions:**

Runs pre-commit hooks and mypy on clean checkout. Classifies pre-existing issues as AUTO-FIX or DEFER.
- AUTO-FIX: <=10 files, same subsystem, low-risk → fix, commit as `chore(pre-existing):`
- DEFER: creates Linear sub-ticket, notes in PR description

For Phase 0, the executor currently runs inline (no sub-agent dispatch needed for pre-flight checks).

**Exit conditions:**
- **Completed:** pre-flight checks passed or pre-existing issues classified and handled

---

### Phase 4: CI WATCH

**Invariants:**
- Phase 3 (create_pr) is completed
- PR number is available in `state["phases"]["create_pr"]["artifacts"]["pr_number"]`

**Actions:**

1. **Dispatch ci-watch to a polymorphic agent:**
   ```
   Task(
     subagent_type="onex:polymorphic-agent",
     description="ticket-pipeline: Phase 4 ci_watch for {ticket_id} on PR #{pr_number}",
     prompt="You are executing ci-watch for {ticket_id}.
       Invoke: Skill(skill=\"onex:ci-watch\",
         args=\"--pr {pr_number} --ticket-id {ticket_id} --timeout-minutes {ci_watch_timeout_minutes} --max-fix-cycles {max_ci_fix_cycles}\")

       Read the ModelSkillResult from ~/.claude/skill-results/{context_id}/ci-watch.json
       Report back with: status (completed|capped|timeout|failed), ci_fix_cycles_used, watch_duration_minutes."
   )
   ```

2. **Handle ci_watch result** (read from ModelSkillResult, not text parsing):
   ```python
   ci_status = result.get("status")  # completed | capped | timeout | failed

   if ci_status == "completed":
       # CI green — advance to Phase 5
       return {
           "status": "completed",
           "blocking_issues": 0,
           "nit_count": 0,
           "artifacts": {
               "status": ci_status,
               "ci_fix_cycles_used": result.get("ci_fix_cycles_used", 0),
               "watch_duration_minutes": result.get("watch_duration_minutes", 0),
           },
           "reason": None,
           "block_kind": None,
       }

   elif ci_status in ("capped", "timeout"):
       # Log warning but continue to Phase 5 with degraded confidence note
       warning_msg = (
           "CI fix cap reached — continuing to Phase 5 with degraded confidence"
           if ci_status == "capped"
           else "CI watch timed out — continuing to Phase 5"
       )
       print(f"Warning: {warning_msg}")
       thread_ts = notify_sync(slack_notifier, "notify_blocked",
           phase="ci_watch",
           reason=warning_msg,
           block_kind="blocked_policy",
           thread_ts=state.get("slack_thread_ts"),
       )
       state["slack_thread_ts"] = thread_ts
       save_state(state, state_path)
       # Return completed so pipeline continues to Phase 5
       return {
           "status": "completed",
           "blocking_issues": 0,
           "nit_count": 0,
           "artifacts": {
               "status": ci_status,
               "ci_fix_cycles_used": result.get("ci_fix_cycles_used", 0),
               "watch_duration_minutes": result.get("watch_duration_minutes", 0),
               "degraded_confidence": True,
           },
           "reason": warning_msg,
           "block_kind": None,
       }

   else:  # ci_status == "failed"
       # Post Slack MEDIUM_RISK gate and stop pipeline
       pr_number = state["phases"]["create_pr"]["artifacts"].get("pr_number", "?")
       slack_message = f"""[MEDIUM_RISK] ticket-pipeline: CI watch failed for {ticket_id}

PR #{pr_number} CI failed and could not be fixed automatically.
Reply 'skip' to continue to PR review anyway, 'stop' to halt pipeline.
Silence (15 min) = stop."""
       thread_ts = notify_sync(slack_notifier, "notify_blocked",
           phase="ci_watch",
           reason=slack_message,
           block_kind="failed_exception",
           thread_ts=state.get("slack_thread_ts"),
       )
       state["slack_thread_ts"] = thread_ts
       save_state(state, state_path)
       return {
           "status": "failed",
           "blocking_issues": 1,
           "nit_count": 0,
           "artifacts": {
               "status": ci_status,
               "ci_fix_cycles_used": result.get("ci_fix_cycles_used", 0),
               "watch_duration_minutes": result.get("watch_duration_minutes", 0),
           },
           "reason": f"CI watch failed for {ticket_id} — pipeline stopped",
           "block_kind": "failed_exception",
       }
   ```

3. **Dry-run behavior:** ci-watch dispatch is skipped. Returns completed with `status: completed` and zero cycles used.

**Mutations:**
- `phases.ci_watch.started_at`
- `phases.ci_watch.completed_at`
- `phases.ci_watch.artifacts` (status, ci_fix_cycles_used, watch_duration_minutes)

**Exit conditions:**
- **Completed:** CI green, or capped/timeout (pipeline continues with warning)
- **Failed:** CI failed and could not be fixed — Slack MEDIUM_RISK gate posted

---

### Phase 5: PR REVIEW LOOP (Placeholder — OMN-2528)

**Invariants:**
- Phase 4 (ci_watch) is completed

**Actions:**

Placeholder. Implemented in OMN-2528 via `pr-watch` sub-skill.

```python
# execute_pr_review_loop — placeholder implementation
# Returns completed immediately so pipeline can advance to auto_merge.
# Full implementation in OMN-2528.
return {
    "status": "completed",
    "blocking_issues": 0,
    "nit_count": 0,
    "artifacts": {"placeholder": True},
    "reason": None,
    "block_kind": None,
}
```

**Exit conditions:**
- **Completed (placeholder):** advances to Phase 6

---

### Phase 6: AUTO MERGE (Placeholder — OMN-2529)

**Invariants:**
- Phase 5 (pr_review_loop) is completed

**Actions:**

Placeholder. Implemented in OMN-2529 via `auto-merge` sub-skill.

```python
# execute_auto_merge — placeholder implementation
# Returns completed immediately. Full implementation in OMN-2529.
return {
    "status": "completed",
    "blocking_issues": 0,
    "nit_count": 0,
    "artifacts": {"placeholder": True},
    "reason": None,
    "block_kind": None,
}
```

**Exit conditions:**
- **Completed (placeholder):** pipeline done

---

## Linear Contract Safety (R15)

All Linear description updates follow these safety rules:

1. **Marker-based patching:** Find `## Pipeline Status` marker, patch only between markers. Never rewrite the full description.
2. **YAML validation before write:** Parse the YAML string with `yaml.safe_load()` before updating. If validation fails, stop and notify.
3. **Preserve user text:** Everything outside the `## Pipeline Status` section is never touched.
4. **Missing markers:** If the expected marker section doesn't exist, append it (never rewrite). If `## Contract` marker is missing when expected, stop and send `notification.blocked`.
5. **No full-description rewrites:** Updates are always additive patches, never full replacements.

---

## Block Kind Classification (R14)

Pipeline distinguishes these block reasons for accurate Slack messaging:

| Block Kind | Meaning | Slack Copy |
|------------|---------|------------|
| `blocked_human_gate` | Waiting for human input (ticket-work questions/spec) | "Waiting for human input: {detail}" |
| `blocked_policy` | Policy switch prevents action | "Policy blocked: {switch}={value}" |
| `blocked_review_limit` | Max review iterations hit with issues remaining | "Review capped at {N} iterations, {M} issues remain" |
| `failed_exception` | Unexpected error | "Phase {name} failed: {error}" |

---

## Slack Notification Format (R10, OMN-1970)

All Slack messages include correlation context and use per-ticket threading:

```
[OMN-XXXX][pipeline:{phase}][run:{run_id}]
{message}
```

- **Threading**: First notification creates Slack thread; all subsequent reply to `thread_ts`
- `thread_ts` stored in `pipeline_state.slack_thread_ts` for resume
- >3 parallel pipelines produce threaded (not flat) Slack messages
- Blocked notifications: WARNING severity (or ERROR for `failed_exception`)
- Completed notifications: INFO severity
- Dry-run: prefix message with `[DRY RUN]`
- All notifications are best-effort and non-blocking
- Dual-emission: direct Slack via `PipelineSlackNotifier` + Kafka event via `emit_client_wrapper`
- **Dependency**: Full threading requires OMN-2157 (Web API support in omnibase_infra).
  Without it, notifications still send but without thread grouping.

### Module: `pipeline_slack_notifier.py`

Located at `plugins/onex/hooks/lib/pipeline_slack_notifier.py`. Key interface:

| Method | Purpose | Returns |
|--------|---------|---------|
| `notify_pipeline_started()` | Seed Slack thread on pipeline start | `thread_ts` |
| `notify_phase_completed()` | Phase completion with summary | `thread_ts` |
| `notify_blocked()` | Pipeline block with reason and block_kind | `thread_ts` |

Use `notify_sync()` wrapper for synchronous calling context.

---

## Error Handling

| Error | Behavior | Lock Released? |
|-------|----------|----------------|
| Phase execution exception | Record error in state, notify blocked, stop pipeline | No (preserves for resume) |
| Skill invocation failure | Record error, notify, stop | No |
| Linear MCP failure | Log warning, continue (Linear is not blocking) | N/A |
| State file write failure | Fatal: stop pipeline immediately | Yes |
| Lock acquisition failure | Do not start, notify, exit | N/A |
| YAML parse failure | Stop, notify, do not write invalid state | No |

**Never:**
- Silently swallow errors
- Continue past a failed phase
- Release lock on failure (preserves state for resume)
- Write invalid YAML to state file or Linear

---

## Resume Behavior

When `/ticket-pipeline {ticket_id}` is invoked on an existing pipeline:

1. Load existing `state.yaml`
2. Acquire lock (same run_id OK; different run_id blocks)
3. Determine current phase (first phase without `completed_at`)
4. Skip completed phases
5. Resume from current phase
6. Report status:
   ```
   Resuming pipeline for {ticket_id}

   Phase Status:
   - pre_flight: completed (2026-02-06T12:30:00Z)
   - implement: completed (2026-02-06T12:45:00Z)
   - local_review: completed (2026-02-06T13:10:00Z)
   - create_pr: blocked (auto_push=false)
   - ci_watch: pending
   - pr_review_loop: pending
   - auto_merge: pending

   Resuming from: create_pr
   ```

---

## Concurrency (R12)

- **One active run per ticket:** Lock file at `~/.claude/pipelines/{ticket_id}/lock`
- **Lock contents:** `{run_id, pid, started_at, started_at_epoch, ticket_id}`
- **Same run_id:** Resumes (lock check passes)
- **Different run_id:** Blocks with Slack notification
- **Stale lock TTL:** 2 hours (auto-breaks)
- **`--force-run`:** Breaks any existing lock
- **Lock released:** Only on clean pipeline completion (not on block/fail)
