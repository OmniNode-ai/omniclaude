# Ticket Pipeline Orchestration

You are executing the ticket-pipeline skill. This prompt defines the complete orchestration logic for chaining existing skills into an autonomous per-ticket pipeline.

## Argument Parsing

Parse arguments from the skill invocation:

```
/ticket-pipeline {ticket_id} [--skip-to PHASE] [--dry-run] [--force-run]
```

```python
args = "$ARGUMENTS".split()
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
    if idx + 1 < len(args):
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
    lock_data = json.loads(lock_path.read_text())
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
        existing_state = yaml.safe_load(state_path.read_text())
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

    run_id = state.get("run_id", run_id)
    # Update lock to match preserved run_id
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

### notify_blocked

```python
def notify_blocked(ticket_id, reason, block_kind, run_id=None, phase=None):
    """Send Slack notification for blocked pipeline. Best-effort, non-blocking.

    NOTE: No rate limiting. If pipeline hits rapid failures, Slack may be spammed.
    Mitigation: pipeline exits on first block/fail (no retry loops).
    Future: add per-ticket rate limiting if retry patterns are added.
    """
    prefix = f"[{ticket_id}]"
    if phase:
        prefix += f"[pipeline:{phase}]"
    if run_id:
        prefix += f"[run:{run_id}]"

    try:
        from plugins.onex.hooks.lib.emit_client_wrapper import emit_event
        emit_event(
            event_type='notification.blocked',
            payload={
                'ticket_id': ticket_id,
                'reason': f"{prefix} {reason}",
                'details': [f"block_kind: {block_kind}"],
                'repo': get_current_repo(),
                'session_id': os.environ.get('CLAUDE_SESSION_ID', 'unknown')
            }
        )
    except Exception:
        pass  # Best-effort, non-blocking
```

### notify_completed

```python
def notify_completed(ticket_id, summary, run_id=None, phase=None, pr_url=None):
    """Send Slack notification for completed phase. Best-effort, non-blocking.

    NOTE: No rate limiting. If pipeline hits rapid failures, Slack may be spammed.
    Mitigation: pipeline exits on first block/fail (no retry loops).
    Future: add per-ticket rate limiting if retry patterns are added.
    """
    prefix = f"[{ticket_id}]"
    if phase:
        prefix += f"[pipeline:{phase}]"
    if run_id:
        prefix += f"[run:{run_id}]"

    try:
        from plugins.onex.hooks.lib.emit_client_wrapper import emit_event
        emit_event(
            event_type='notification.completed',
            payload={
                'ticket_id': ticket_id,
                'summary': f"{prefix} {summary}",
                'repo': get_current_repo(),
                'pr_url': pr_url or '',
                'session_id': os.environ.get('CLAUDE_SESSION_ID', 'unknown')
            }
        )
    except Exception:
        pass  # Best-effort, non-blocking
```

### get_current_repo

```python
def get_current_repo():
    """Extract repo name from current working directory."""
    import os
    return os.path.basename(os.getcwd())
```

### update_linear_pipeline_summary

Updates the Linear ticket with a compact pipeline summary. Uses marker-based patching to preserve existing description content.

```python
def update_linear_pipeline_summary(ticket_id, state, dry_run=False):
    """Mirror compact pipeline state to Linear ticket description.

    Safety:
    - Uses marker-based patching (## Pipeline Status section)
    - Validates YAML before write
    - Preserves all existing description content outside markers
    - If markers missing, appends new section (never rewrites full description)
    - If dry_run=True, skips the actual Linear update
    """
    import yaml

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
                    summary_yaml += f"\n  {phase_name}_{key}: \"{value}\""

    if not any(pd.get("artifacts") for pd in state["phases"].values()):
        summary_yaml += " {}"

    # Fetch current description
    try:
        issue = mcp__linear-server__get_issue(id=ticket_id)
        description = issue["description"] or ""
    except Exception as e:
        print(f"Warning: Failed to fetch Linear issue {ticket_id}: {e}")
        return  # Non-blocking: Linear is not critical path

    # Marker-based patching with explicit end marker for safety
    pipeline_start = "## Pipeline Status"
    pipeline_end = "<!-- /pipeline-status -->"
    pipeline_block = f"\n\n{pipeline_start}\n\n```yaml\n{summary_yaml}\n```\n\n{pipeline_end}\n"

    if pipeline_start in description and pipeline_end in description:
        # Safe: replace between known markers
        start_idx = description.index(pipeline_start)
        end_idx = description.index(pipeline_end) + len(pipeline_end)
        description = description[:start_idx] + pipeline_block.strip() + description[end_idx:]
    elif pipeline_start in description:
        # Legacy: has start but no end marker — use heading-based regex
        import re
        pattern = r'## Pipeline Status\n+```(?:yaml)?\n.*?\n```'
        description = re.sub(pattern, pipeline_block.strip(), description, count=1, flags=re.DOTALL)
    else:
        # Find the ## Contract marker and insert before it
        contract_marker = "## Contract"
        if contract_marker in description:
            idx = description.rfind(contract_marker)
            description = description[:idx].rstrip() + "\n\n" + pipeline_block.strip() + "\n\n---\n\n" + description[idx:]
        else:
            # No contract section - append at end
            description = description.rstrip() + "\n\n" + pipeline_block

    # Validate YAML in pipeline block before writing
    try:
        parsed = yaml.safe_load(summary_yaml)
        # Basic schema validation: required keys must be present
        required_keys = {"run_id", "phase"}
        if not isinstance(parsed, dict) or not required_keys.issubset(parsed.keys()):
            raise ValueError(f"Missing required keys: {required_keys - set(parsed.keys() if isinstance(parsed, dict) else [])}")
    except (yaml.YAMLError, ValueError) as e:
        print(f"Warning: Pipeline summary YAML validation failed: {e}")
        notify_blocked(ticket_id, f"YAML validation failed for pipeline summary: {e}", "failed_exception",
                       run_id=state.get("run_id"))
        return  # Do not write invalid YAML

    try:
        mcp__linear-server__update_issue(id=ticket_id, description=description)
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

        notify_blocked(ticket_id, f"Phase {phase_name} failed: {e}", "failed_exception",
                       run_id=run_id, phase=phase_name)
        update_linear_pipeline_summary(ticket_id, state, dry_run)
        print(f"\nPipeline stopped at {phase_name}: {e}")
        release_lock(lock_path)
        exit(1)

    # Handle phase result
    if result["status"] == "completed":
        phase_data["completed_at"] = datetime.now(timezone.utc).isoformat()
        phase_data["artifacts"].update(result.get("artifacts", {}))
        save_state(state, state_path)

        notify_completed(ticket_id, f"Phase {phase_name} completed", run_id=run_id, phase=phase_name,
                         pr_url=result.get("artifacts", {}).get("pr_url"))
        update_linear_pipeline_summary(ticket_id, state, dry_run)

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

        notify_blocked(ticket_id, result.get("reason", "Unknown"), result.get("block_kind", "failed_exception"),
                       run_id=run_id, phase=phase_name)
        update_linear_pipeline_summary(ticket_id, state, dry_run)

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

---

## Phase Handlers

### Phase 1: IMPLEMENT

**Invariants:**
- Pipeline is initialized with valid ticket_id
- Lock is acquired

**Actions:**

1. **Invoke ticket-work:**
   ```
   Skill(skill="ticket-work", args="{ticket_id}")
   ```
   This runs the full ticket-work workflow including human gates (questions, spec, approval).
   The pipeline waits for ticket-work to complete.

2. **Cross-repo check** (if `policy.stop_on_cross_repo == true`):
   After ticket-work completes, check that all changes are within the current repo:
   ```bash
   # Get the repo root
   REPO_ROOT=$(git rev-parse --show-toplevel)

   # Check all changed and untracked files using null-delimited output
   # NOTE: Use process substitution (not pipe) so exit 1 affects main shell
   CROSS_REPO_VIOLATION=""
   while IFS= read -r -d '' file; do
       REAL_PATH=$(realpath "$file" 2>/dev/null) || continue
       if [[ ! "$REAL_PATH" == "$REPO_ROOT"* ]]; then
           CROSS_REPO_VIOLATION="$file resolves outside $REPO_ROOT"
           break
       fi
   done < <(git diff -z --name-only HEAD && git ls-files -z --others --exclude-standard)

   if [ -n "$CROSS_REPO_VIOLATION" ]; then
       echo "CROSS_REPO_VIOLATION: $CROSS_REPO_VIOLATION"
       exit 1
   fi
   ```

   If cross-repo violation detected:
   ```python
   result = {
       "status": "blocked",
       "block_kind": "blocked_policy",
       "reason": f"Cross-repo change detected: {violating_file} resolves outside {repo_root}",
       "blocking_issues": 1,
       "nit_count": 0,
       "artifacts": {}
   }
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
   Skill(skill="local-review", args="--max-iterations {policy.max_review_iterations}")
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
       for f in $TOPIC_FILES; do
           if grep -q 'dev\.' "$f" 2>/dev/null && ! grep -q '"dev\.' "$f" 2>/dev/null; then
               echo "INVARIANT_VIOLATION: Found 'dev.' prefix in $f"
               exit 1
           fi
       done
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

   # Create PR with heredoc-safe title/body
   gh pr create --title "$(cat <<'EOF'
   feat({ticket_id}): {ticket_title}
   EOF
   )" --body "$(cat <<'EOF'
   ## Summary

   Automated PR created by ticket-pipeline.

   **Ticket**: {ticket_id}
   **Pipeline Run**: {run_id}

   ## Changes

   {commit_summary}

   ## Test Plan

   - [ ] CI passes
   - [ ] CodeRabbit review addressed
   EOF
   )"
   ```

4. **Update Linear:**
   ```python
   try:
       mcp__linear-server__update_issue(id="{ticket_id}", state="In Review")
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
   Skill(skill="pr-release-ready")
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
       mcp__linear-server__update_issue(id="{ticket_id}", labels=["ready-for-merge"])
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

## Slack Notification Format (R10)

All Slack messages include correlation context:

```
[OMN-XXXX][pipeline:{phase}][run:{run_id}]
{message}
```

- Blocked notifications: `notification.blocked` event type
- Completed notifications: `notification.completed` event type
- Dry-run: prefix message with `[DRY RUN]`
- All notifications are best-effort and non-blocking
- `slack_thread_ts` is a placeholder in pipeline_state (threading deferred to future ticket)

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
