# Ticket Pipeline — Poly Worker Prompt

You are a polymorphic agent executing the ticket-pipeline skill. This prompt defines the complete orchestration logic for chaining existing skills into an autonomous per-ticket pipeline.

## Execution Context (provided by orchestrator)

- `TICKET_ID`: Linear ticket identifier (e.g., OMN-1234)
- `SKIP_TO`: Phase to skip to (or "none")
- `DRY_RUN`: Whether to skip side effects (true/false)
- `FORCE_RUN`: Whether to break stale locks (true/false)

## Argument Parsing

```python
ticket_id = TICKET_ID  # From execution context

import re
if not re.match(r'^[A-Z]+-\d+$', ticket_id):
    print(f"Error: Invalid ticket_id format '{ticket_id}'. Expected pattern like 'OMN-1234'.")
    exit(1)

dry_run = DRY_RUN == "true"
force_run = FORCE_RUN == "true"
skip_to = None if SKIP_TO == "none" else SKIP_TO

if skip_to:
    # Canonical phase order - referenced in multiple code blocks throughout this prompt
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

if lock_path.exists():
    try:
        lock_data = json.loads(lock_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        print(f"Warning: Corrupted lock file for {ticket_id}: {e}. Breaking lock.")
        lock_path.unlink(missing_ok=True)
        lock_data = None

    if lock_data is not None:
        lock_age = time.time() - lock_data.get("started_at_epoch", 0)

        if force_run:
            print(f"Force-run: breaking existing lock (run_id={lock_data.get('run_id')})")
            lock_path.unlink()
        elif lock_age > STALE_TTL_SECONDS:
            print(f"Stale lock detected ({lock_age:.0f}s old). Breaking automatically.")
            lock_path.unlink()
        elif state_path.exists():
            try:
                existing_state = yaml.safe_load(state_path.read_text())
            except (yaml.YAMLError, OSError) as e:
                print(f"Warning: Corrupted state file for {ticket_id}: {e}. Use --force-run to create fresh state.")
                notify_blocked(ticket_id=ticket_id, reason=f"Corrupted state file: {e}", block_kind="failed_exception")
                exit(1)

            if existing_state.get("run_id") == lock_data.get("run_id"):
                pass  # Same run resuming - OK
            else:
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

# Note: On resume, the lock file is written initially with a fresh run_id (line ~173)
# then overwritten with the correct run_id from saved state (line ~189).
# This is intentional: the initial write claims the lock, the second write corrects the ID.
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
    state = yaml.safe_load(state_path.read_text())

    state_version = state.get("pipeline_state_version", "0.0")
    if state_version != "1.0":
        print(f"Warning: State file version {state_version} differs from expected 1.0. "
              f"Pipeline may behave unexpectedly. Use --force-run to create fresh state.")

    run_id = state.get("run_id", run_id)
    lock_data["run_id"] = run_id
    lock_path.write_text(json.dumps(lock_data))
    print(f"Resuming pipeline for {ticket_id} (run_id: {run_id})")
else:
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
    return "done"
```

### notify_blocked

```python
def notify_blocked(ticket_id, reason, block_kind, run_id=None, phase=None):
    """Send Slack notification for blocked pipeline. Best-effort, non-blocking."""
    prefix = f"[{ticket_id}]"
    if phase:
        prefix += f"[pipeline:{phase}]"
    if run_id:
        prefix += f"[run:{run_id}]"

    try:
        # emit_client_wrapper is at ${CLAUDE_PLUGIN_ROOT}/hooks/lib/emit_client_wrapper.py
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
    except Exception as e:
        import sys
        print(f"Warning: Notification failed: {e}", file=sys.stderr)
```

### notify_completed

```python
def notify_completed(ticket_id, summary, run_id=None, phase=None, pr_url=None):
    """Send Slack notification for completed phase. Best-effort, non-blocking."""
    prefix = f"[{ticket_id}]"
    if phase:
        prefix += f"[pipeline:{phase}]"
    if run_id:
        prefix += f"[run:{run_id}]"

    try:
        # emit_client_wrapper is at ${CLAUDE_PLUGIN_ROOT}/hooks/lib/emit_client_wrapper.py
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
    except Exception as e:
        import sys
        print(f"Warning: Notification failed: {e}", file=sys.stderr)
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

    for phase_name, phase_data in state["phases"].items():
        if phase_data.get("artifacts"):
            for key, value in phase_data["artifacts"].items():
                if key != "skipped":
                    summary_yaml += f"\n  {phase_name}_{key}: \"{value}\""

    if not any(pd.get("artifacts") for pd in state["phases"].values()):
        summary_yaml += " {}"

    try:
        issue = mcp__linear-server__get_issue(id=ticket_id)
        description = issue["description"] or ""
    except Exception as e:
        print(f"Warning: Failed to fetch Linear issue {ticket_id}: {e}")
        return

    pipeline_start = "## Pipeline Status"
    pipeline_end = "<!-- /pipeline-status -->"
    pipeline_block = f"\n\n{pipeline_start}\n\n```yaml\n{summary_yaml}\n```\n\n{pipeline_end}\n"

    # Marker-based description patching: handles three cases:
    # 1. Both start+end markers present: replace between markers
    # 2. Only start marker: regex replace after start marker
    # 3. No markers: append to end (before ## Contract if present)
    if pipeline_start in description and pipeline_end in description:
        start_idx = description.index(pipeline_start)
        end_idx = description.index(pipeline_end) + len(pipeline_end)
        description = description[:start_idx] + pipeline_block.strip() + description[end_idx:]
    elif pipeline_start in description:
        import re
        pattern = r'## Pipeline Status\n+```(?:yaml)?\n.*?\n```'
        description = re.sub(pattern, pipeline_block.strip(), description, count=1, flags=re.DOTALL)
    else:
        contract_marker = "## Contract"
        if contract_marker in description:
            idx = description.find(contract_marker)
            description = description[:idx].rstrip() + "\n\n" + pipeline_block.strip() + "\n\n---\n\n" + description[idx:]
        else:
            description = description.rstrip() + "\n\n" + pipeline_block

    try:
        parsed = yaml.safe_load(summary_yaml)
        required_keys = {"run_id", "phase"}
        if not isinstance(parsed, dict) or not required_keys.issubset(parsed.keys()):
            raise ValueError(f"Missing required keys: {required_keys - set(parsed.keys() if isinstance(parsed, dict) else [])}")
        if not isinstance(parsed.get("run_id"), str):
            parsed["run_id"] = str(parsed["run_id"])  # Coerce to string
        valid_phases = PHASES + ["done"]
        if parsed.get("phase") not in valid_phases:
            raise ValueError(f"Invalid phase '{parsed.get('phase')}', expected one of: {valid_phases}")
    except (yaml.YAMLError, ValueError) as e:
        print(f"Warning: Pipeline summary YAML validation failed: {e}")
        notify_blocked(ticket_id, f"YAML validation failed for pipeline summary: {e}", "failed_exception",
                       run_id=state.get("run_id"))
        return

    try:
        mcp__linear-server__update_issue(id=ticket_id, description=description)
    except Exception as e:
        print(f"Warning: Failed to update Linear issue {ticket_id}: {e}")
```

### parse_phase_output

```python
def parse_phase_output(raw_output, phase_name):
    """Parse phase output into structured result.

    Expected schema:
        status: completed | blocked | failed
        blocking_issues: int
        nit_count: int
        artifacts: dict
        reason: str | None
        block_kind: str | None

    NOTE: This parses natural language output from skills, which is inherently fragile.
    Future improvement: skills should return structured JSON output instead.
    Current patterns are based on observed skill output formats.
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

    if "blocked by" in output_lower or "max iterations reached" in output_lower:
        result["status"] = "blocked"
        result["block_kind"] = "blocked_review_limit"
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

    import re
    nit_match = re.search(r'nits?\s*(?:deferred|remaining)?:?\s*(\d+)', output_lower)
    if nit_match:
        result["nit_count"] = int(nit_match.group(1))

    if "clean - ready to push" in output_lower or "clean - no issues found" in output_lower:
        result["status"] = "completed"
        result["blocking_issues"] = 0

    elif "clean with nits" in output_lower:
        result["status"] = "completed"
        result["blocking_issues"] = 0

    if result["status"] == "completed" and output_lower:
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

    if phase_data.get("completed_at"):
        print(f"Phase {phase_name}: already completed at {phase_data['completed_at']}. Skipping.")
        continue

    print(f"\n## Phase: {phase_name}\n")
    phase_data["started_at"] = datetime.now(timezone.utc).isoformat()
    save_state(state, state_path)

    # Lock release policy:
    # - Unexpected exceptions (bugs, crashes): RELEASE lock for clean retry
    # - Expected failures (blocked, failed phases): PRESERVE lock for resume with --force-run
    # This intentional asymmetry allows resume on expected failures while cleaning up after bugs.
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

    if result["status"] == "completed":
        phase_data["completed_at"] = datetime.now(timezone.utc).isoformat()
        phase_data["artifacts"].update(result.get("artifacts", {}))
        save_state(state, state_path)

        notify_completed(ticket_id, f"Phase {phase_name} completed", run_id=run_id, phase=phase_name,
                         pr_url=result.get("artifacts", {}).get("pr_url"))
        update_linear_pipeline_summary(ticket_id, state, dry_run)

        if not state["policy"]["auto_advance"]:
            print(f"Phase {phase_name} completed. auto_advance=false, stopping.")
            release_lock(lock_path)
            exit(0)

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
        # Lock intentionally NOT released on failure — preserved for resume (TTL: 2h). See release_lock docs.
        exit(1)

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
        pass
```

### execute_phase

```python
def execute_phase(phase_name, state):
    """Dispatch to the appropriate phase handler."""
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
   Skill(skill="ticket-work", args="{ticket_id}")
   ```
   This runs the full ticket-work workflow including human gates (questions, spec, approval).
   The pipeline waits for ticket-work to complete.

2. **Cross-repo check** (if `policy.stop_on_cross_repo == true`):
   After ticket-work completes, check that all changes are within the current repo:
   ```bash
   REPO_ROOT=$(git rev-parse --show-toplevel)
   CROSS_REPO_VIOLATION=""
   while IFS= read -r -d '' file; do
       REAL_PATH=$(realpath "$file" 2>/dev/null) || continue
       if [[ ! "$REAL_PATH" == "$REPO_ROOT"* ]]; then
           CROSS_REPO_VIOLATION="$file resolves outside $REPO_ROOT"
           break
       fi
   done < <(git diff -z --name-only origin/main...HEAD && git diff -z --name-only HEAD && git ls-files -z --others --exclude-standard)

   if [ -n "$CROSS_REPO_VIOLATION" ]; then
       echo "CROSS_REPO_VIOLATION: $CROSS_REPO_VIOLATION"
       exit 1
   fi
   ```

3. **Verify implementation is complete:**
   Check the ticket-work contract to confirm implementation phase is done:
   - Ticket contract phase should be `review` or `done`
   - At least one commit exists in the contract

4. **Dry-run behavior:** Phase 1 runs ticket-work normally (including human gates) because ticket-work does not support a dry-run flag. Dry-run is fully effective starting from Phase 2 onward.

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

2. **Parse result:** Use `parse_phase_output()` to determine status, blocking_issues, nit_count, artifacts.

3. **Policy checks:**
   - If `blocking_issues > 0`: status = blocked, block_kind = "blocked_review_limit"
   - If parse fails: status = failed, block_kind = "failed_exception"

4. **Dry-run behavior:** local-review runs normally but commits are skipped.

**Exit conditions:**
- **Completed:** 0 blocking issues (nits OK)
- **Blocked:** blocking issues remain after max iterations
- **Failed:** local-review errors out or output parse failure

---

### Phase 3: CREATE PR

**Invariants:**
- Phase 2 (local_review) is completed
- `policy.auto_push == true` AND `policy.auto_pr_create == true`

**Actions:**

1. **Policy check:** Block if `auto_push` or `auto_pr_create` is false.

2. **Pre-checks (idempotent):**
   a. Check for existing PR on current branch (`gh pr view --json url,number`)
   b. Clean working tree (`git status --porcelain`)
   c. Branch tracks remote
   d. Branch name pattern matches `{user}/omn-{number}-*`
   e. GitHub auth (`gh auth status`)
   f. Git remote origin exists
   g. Realm/topic naming invariant (if `policy.stop_on_invariant == true`):
      Check for hardcoded `dev.` prefix in topic/constant files

3. **Push and create PR:**
   ```bash
   git fetch origin
   BRANCH=$(git rev-parse --abbrev-ref HEAD)
   if git rev-parse --verify "origin/$BRANCH" >/dev/null 2>&1; then
       if ! git merge-base --is-ancestor "origin/$BRANCH" HEAD; then
           echo "Error: Remote branch has diverged."
           exit 1
       fi
   fi

   git push -u origin HEAD

   TICKET_ID="{ticket_id}"
   TICKET_TITLE="{ticket_title}"
   RUN_ID="{run_id}"
   BASE_REF=$(git merge-base origin/main HEAD)
   COMMIT_SUMMARY=$(git log --oneline "$BASE_REF"..HEAD)

   # Sanitize all interpolated values to prevent shell injection and heredoc breakage.
   # Remove characters that could break quoting or inject commands.
   sanitize() { printf '%s' "$1" | tr -d '\000-\037' | sed 's/[`$"\\]/\\&/g'; }
   SAFE_TICKET_ID=$(sanitize "$TICKET_ID")
   SAFE_TICKET_TITLE=$(sanitize "$TICKET_TITLE")
   SAFE_RUN_ID=$(sanitize "$RUN_ID")
   SAFE_COMMIT_SUMMARY=$(sanitize "$COMMIT_SUMMARY")

   # Write PR body to a temp file to avoid heredoc interpolation risks
   PR_BODY_FILE=$(mktemp)
   trap 'rm -f "$PR_BODY_FILE"' EXIT
   cat > "$PR_BODY_FILE" <<PRBODY
   ## Summary

   Automated PR created by ticket-pipeline.

   **Ticket**: ${SAFE_TICKET_ID}
   **Pipeline Run**: ${SAFE_RUN_ID}

   ## Changes

   ${SAFE_COMMIT_SUMMARY}

   ## Test Plan

   - [ ] CI passes
   - [ ] CodeRabbit review addressed
   PRBODY

   gh pr create \
     --title "feat(${SAFE_TICKET_ID}): ${SAFE_TICKET_TITLE}" \
     --body-file "$PR_BODY_FILE"
   ```

4. **Update Linear:**
   ```python
   mcp__linear-server__update_issue(id=ticket_id, state="In Review")
   ```

5. **Dry-run behavior:** All pre-checks execute. Push, PR creation, and Linear update are skipped.

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

1. **Pre-check:** Verify PR exists (`gh pr view --json url,number`). If not found, block.

2. **Invoke pr-release-ready:**
   ```
   Skill(skill="pr-release-ready")
   ```

3. **Parse result:** Use `parse_phase_output()` to determine status.

4. **Push fixes** (if any commits were made): `git push`

5. **Dry-run behavior:** pr-release-ready runs in report-only mode. No fixes committed or pushed.

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
   issue = mcp__linear-server__get_issue(id=ticket_id)
   existing_labels = [label["name"] for label in issue.get("labels", {}).get("nodes", [])]
   if "ready-for-merge" not in existing_labels:
       existing_labels.append("ready-for-merge")
   mcp__linear-server__update_issue(id=ticket_id, labels=existing_labels)
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

3. **Dry-run behavior:** Linear label update skipped. Slack notification sent with `[DRY RUN]` prefix.

4. **Pipeline stops here.** Manual merge is required.

---

## Linear Contract Safety

1. **Marker-based patching:** Find `## Pipeline Status` marker, patch only between markers.
2. **YAML validation before write:** Parse with `yaml.safe_load()` before updating.
3. **Preserve user text:** Everything outside `## Pipeline Status` is never touched.
4. **Missing markers:** Append new section, never rewrite.
5. **No full-description rewrites:** Updates are always additive patches.

---

## Block Kind Classification

| Block Kind | Meaning | Slack Copy |
|------------|---------|------------|
| `blocked_human_gate` | Waiting for human input | "Waiting for human input: {detail}" |
| `blocked_policy` | Policy switch prevents action | "Policy blocked: {switch}={value}" |
| `blocked_review_limit` | Max review iterations hit | "Review capped at {N} iterations, {M} issues remain" |
| `failed_exception` | Unexpected error | "Phase {name} failed: {error}" |

---

## Error Handling

| Error | Behavior | Lock Released? |
|-------|----------|----------------|
| Phase execution exception | Record error, notify, stop | No |
| Skill invocation failure | Record error, notify, stop | No |
| Linear MCP failure | Log warning, continue | N/A |
| State file write failure | Fatal: stop immediately | Yes |
| Lock acquisition failure | Do not start, notify, exit | N/A |
| YAML parse failure | Stop, notify, do not write | No |

**Never:**
- Silently swallow errors
- Continue past a failed phase
- Release lock on failure (preserves state for resume)
- Write invalid YAML to state file or Linear

---

## Resume Behavior

When invoked on an existing pipeline:

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

## Concurrency

- **One active run per ticket:** Lock file at `~/.claude/pipelines/{ticket_id}/lock`
- **Same run_id:** Resumes (lock check passes)
- **Different run_id:** Blocks with Slack notification
- **Stale lock TTL:** 2 hours (auto-breaks)
- **`--force-run`:** Breaks any existing lock
- **Lock released:** Only on clean pipeline completion
