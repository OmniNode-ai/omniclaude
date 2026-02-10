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
        print("Error: --skip-to requires a phase argument (implement|local_review|create_pr|pr_release_ready|ready_for_merge)")
        exit(1)
    skip_to = args[idx + 1]
    valid_phases = ["implement", "local_review", "create_pr", "pr_release_ready", "ready_for_merge"]
    if skip_to not in valid_phases:
        print(f"Error: Invalid phase '{skip_to}'. Valid: {valid_phases}")
        exit(1)
```

---

## Pipeline State Schema

State is stored at `~/.claude/pipelines/{ticket_id}/state.yaml`:

```yaml
pipeline_state_version: "1.0"
run_id: "uuid-v4"               # Stable correlation ID for this pipeline run
ticket_id: "OMN-XXXX"
started_by: "user"              # "user" or "agent" (for future team-pipeline)
dry_run: false                  # true if --dry-run mode
policy_version: "1.0"
slack_thread_ts: null           # Placeholder for P0 (threading deferred)

policy:
  auto_advance: true
  auto_commit: true
  auto_push: true
  auto_pr_create: true
  max_review_iterations: 3
  stop_on_major: true
  stop_on_repeat: true
  stop_on_cross_repo: true
  stop_on_invariant: true

phases:
  implement:
    started_at: null
    completed_at: null
    artifacts: {}
    blocked_reason: null
    block_kind: null             # blocked_human_gate | blocked_policy | blocked_review_limit | failed_exception
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
  pr_release_ready:
    started_at: null
    completed_at: null
    artifacts: {}
    blocked_reason: null
    block_kind: null
    last_error: null
    last_error_at: null
  ready_for_merge:
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
    if state_version != "1.0":
        print(f"Warning: State file version {state_version} differs from expected 1.0. "
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
        "pipeline_state_version": "1.0",
        "run_id": run_id,
        "ticket_id": ticket_id,
        "started_by": "user",
        "dry_run": dry_run,
        "policy_version": "1.0",
        "slack_thread_ts": None,
        "policy": {
            "auto_advance": True,
            "auto_commit": True,
            "auto_push": True,
            "auto_pr_create": True,
            "max_review_iterations": 3,
            "stop_on_major": True,
            "stop_on_repeat": True,
            "stop_on_cross_repo": True,
            "stop_on_invariant": True,
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
            for phase_name in ["implement", "local_review", "create_pr", "pr_release_ready", "ready_for_merge"]
        }
    }
```

### 3. Handle --skip-to

```python
if skip_to:
    phase_order = ["implement", "local_review", "create_pr", "pr_release_ready", "ready_for_merge"]
    skip_idx = phase_order.index(skip_to)

    # Mark all phases before skip_to as completed (if not already)
    for phase_name in phase_order[:skip_idx]:
        phase_data = state["phases"][phase_name]
        if not phase_data.get("completed_at"):
            phase_data["completed_at"] = datetime.now(timezone.utc).isoformat()
            phase_data["artifacts"]["skipped"] = True
            print(f"Skipping phase: {phase_name}")
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
    phase_order = ["implement", "local_review", "create_pr", "pr_release_ready", "ready_for_merge"]
    for phase_name in phase_order:
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

    Since upstream skills (ticket-work, local-review, pr-release-ready) don't return
    structured output yet, this adapter infers status from observable signals.

    KNOWN LIMITATION: This is fragile string parsing. Expected output format contract:
    - Local-review should output status lines like "clean - ready to push" or "clean with nits"
    - Blocked states should mention "blocked by", "max iterations", or "waiting for"
    - Error states should include "error", "failed", or "parse failed"
    If no recognized pattern is found, defaults to "failed" status.
    """
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
        import re
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
    import re
    nit_match = re.search(r'nits?\s*(?:deferred|remaining)?:?\s*(\d+)', output_lower)
    if nit_match:
        result["nit_count"] = int(nit_match.group(1))

    # Extract status indicators from local-review output
    if "clean - ready to push" in output_lower or "clean - no issues found" in output_lower:
        result["status"] = "completed"
        result["blocking_issues"] = 0

    elif "clean with nits" in output_lower:
        result["status"] = "completed"
        result["blocking_issues"] = 0

    # If no known status indicator was found and status is still "completed" (default),
    # check if the output contains enough signal to confirm success
    if result["status"] == "completed" and output_lower:
        # Only return "completed" if we found positive confirmation
        if not any(indicator in output_lower for indicator in [
            "clean - ready to push", "clean - no issues found", "clean with nits",
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
phase_order = ["implement", "local_review", "create_pr", "pr_release_ready", "ready_for_merge"]

for phase_name in phase_order:
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
        "implement": execute_implement,
        "local_review": execute_local_review,
        "create_pr": execute_create_pr,
        "pr_release_ready": execute_pr_release_ready,
        "ready_for_merge": execute_ready_for_merge,
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

1. **Invoke ticket-work:**
   ```
   Skill(skill="onex:ticket-work", args="{ticket_id}")
   ```
   This runs the full ticket-work workflow including human gates (questions, spec, approval).
   The pipeline waits for ticket-work to complete.

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

1. **Invoke local-review:**
   ```
   Skill(skill="onex:local-review", args="--max-iterations {policy.max_review_iterations}")
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

### Phase 4: PR RELEASE READY

**Invariants:**
- Phase 3 (create_pr) is completed
- PR exists on GitHub

**Actions:**

1. **Pre-check: Verify PR exists:**
   ```python
   # Pre-check: verify PR exists (required if Phase 3 was skipped via --skip-to)
   try:
       pr_check = subprocess.check_output(["gh", "pr", "view", "--json", "url,number"], stderr=subprocess.DEVNULL)
       pr_info = json.loads(pr_check)
       # Record PR artifacts if not already captured (e.g., Phase 3 was skipped)
       if not state["phases"]["create_pr"]["artifacts"].get("pr_url"):
           state["phases"]["create_pr"]["artifacts"]["pr_url"] = pr_info["url"]
           state["phases"]["create_pr"]["artifacts"]["pr_number"] = pr_info["number"]
           save_state(state, state_path)
   except (subprocess.CalledProcessError, json.JSONDecodeError):
       result = {"status": "blocked", "block_kind": "blocked_policy",
                 "reason": "No PR found on current branch. Cannot run pr-release-ready without a PR. Create one first or use --skip-to create_pr."}
       return result
   ```

2. **Invoke pr-release-ready:**
   ```
   Skill(skill="onex:pr-release-ready")
   ```
   This fetches CodeRabbit review issues and invokes `/parallel-solve` to fix them.

3. **Parse result:**
   Use `parse_phase_output()` to determine status:
   - `status`: completed (all issues fixed) or blocked (issues remain)
   - `blocking_issues`: remaining critical/major/minor
   - `nit_count`: remaining nits

4. **Push fixes** (if any commits were made):
   ```bash
   git push
   ```

5. **Dry-run behavior:** pr-release-ready runs in report-only mode. No fixes are committed or pushed.

**Mutations:**
- `phases.pr_release_ready.started_at`
- `phases.pr_release_ready.completed_at`
- `phases.pr_release_ready.artifacts` (iterations, blocking_remaining, nit_count)

**Exit conditions:**
- **Completed:** 0 blocking issues
- **Blocked:** blocking issues remain after review iterations
- **Failed:** pr-release-ready errors out

---

### Phase 5: READY FOR MERGE

**Invariants:**
- Phase 4 (pr_release_ready) is completed
- 0 blocking issues

**Actions:**

1. **Add ready-for-merge label to Linear:**
   ```python
   try:
       # Fetch existing labels to avoid overwriting them
       issue = mcp__linear-server__get_issue(id=ticket_id)
       existing_labels = [label["name"] for label in issue.get("labels", {}).get("nodes", [])]
       if "ready-for-merge" not in existing_labels:
           existing_labels.append("ready-for-merge")
       mcp__linear-server__update_issue(id=ticket_id, labels=existing_labels)
   except Exception as e:
       print(f"Warning: Failed to update Linear issue {ticket_id}: {e}")
       # Non-blocking: Linear label update failure is logged but does not stop pipeline
   ```

2. **Send Slack notification:**
   ```python
   notify_completed(
       ticket_id=ticket_id,
       summary=f"{ticket_id} ready for merge -- 0 blocking, {nit_count} nits",
       run_id=run_id,
       phase="ready_for_merge",
       pr_url=state["phases"]["create_pr"]["artifacts"].get("pr_url")
   )
   ```

3. **Dry-run behavior:** Linear label update is skipped. Slack notification is sent with `[DRY RUN]` prefix.

4. **Pipeline stops here.** Manual merge is required. This is the only manual pause besides ticket-work human gates.

**Mutations:**
- `phases.ready_for_merge.started_at`
- `phases.ready_for_merge.completed_at`
- `phases.ready_for_merge.artifacts` (nit_count, pr_url)

**Exit conditions:**
- **Completed:** label added, notification sent, pipeline done

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
   - implement: completed (2026-02-06T12:45:00Z)
   - local_review: completed (2026-02-06T13:10:00Z)
   - create_pr: blocked (auto_push=false)
   - pr_release_ready: pending
   - ready_for_merge: pending

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
