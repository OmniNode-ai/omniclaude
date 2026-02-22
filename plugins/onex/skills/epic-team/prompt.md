# Epic Team Orchestration

You are executing the epic-team skill as the **team-lead agent**. This document is the authoritative operational guide. Follow it exactly. Every phase transition, every state write, every guard check is mandatory.

## Argument Parsing

```
/epic-team {epic_id} [--resume] [--force] [--force-kill] [--force-unmatched] [--dry-run]
```

```python
args = "$ARGUMENTS".split()
if len(args) == 0:
    print("Error: epic_id is required. Usage: /epic-team OMN-1234")
    exit(1)
epic_id = args[0]

import re
if not re.match(r'^[A-Z]+-\d+$', epic_id):
    print(f"Error: Invalid epic_id format '{epic_id}'. Expected pattern like 'OMN-1234'.")
    exit(1)

resume       = "--resume"           in args
force        = "--force"            in args
force_kill   = "--force-kill"       in args
force_unmatched = "--force-unmatched" in args
dry_run      = "--dry-run"          in args

STATE_DIR  = f"~/.claude/epics/{epic_id}"
STATE_FILE = f"{STATE_DIR}/state.yaml"
REVOKED_FILE = f"{STATE_DIR}/revoked_runs.yaml"
```

---

## Core Invariants

These rules are enforced at every step without exception.

### Phase Transition Rule

**Assert current phase → PERSIST new phase to state.yaml → Execute side effects.**

State.yaml is the ONLY write gate. Never execute side effects before persisting the new phase. If a side effect fails after the phase is persisted, the `--resume` path handles recovery.

### TaskList Filter (Triple Filter)

All TaskList calls use this base filter. Additional filters (owner, status) are ADDED to this base — never replacing it:

```python
BASE_FILTER = {
    "team_name": team_name,              # scoped to this team
    "description__contains": [
        f"[epic:{epic_id}]",             # scoped to this epic
        f"[run:{run_id}]",               # scoped to this run
    ]
}
# Example with additional filters:
WORKER_FILTER = {**BASE_FILTER, "owner": f"worker-{repo}", "status": "todo"}
```

### Termination Authority

**TaskList is the sole source of truth for task terminal status.** Worker SendMessage notifications are optional telemetry. A task is only terminal when TaskList confirms it. Notifications that arrive before TaskList confirms are logged and ignored for status decisions.

### TaskCreate Description Format (Canonical)

This exact format is used for all TaskCreate calls. It enables the triple filter and lease validation:

```
[epic:{epic_id}][run:{run_id}][repo:{repo}][lease:{run_id[:8]}:{repo}]{triage_tag}{part_tag} {title} — {url}
```

Where:
- `{triage_tag}` = `[triage:true]` for unmatched tickets, empty string otherwise
- `{part_tag}` = `[origin:{orig}][part:1-of-2]` for part 1 of a cross-repo split, `[part:2-of-2]` for part 2, empty string for non-split tickets
- `{title}` = ticket title from Linear
- `{url}` = Linear ticket URL

---

## `--resume` Path

Evaluated BEFORE any phase logic. If `--resume` is passed:

```python
# 1. Load state.yaml
state = load_yaml(STATE_FILE)
if state is None:
    print(f"ERROR: state.yaml not found at {STATE_FILE}. Cannot resume.")
    print("Run without --resume to start a new run.")
    exit(1)

# 2. If phase == "done": idempotent exit
if state["phase"] == "done":
    print_done_summary(state)
    print("Run is already complete. Use TeamDelete if you want to clean up resources.")
    exit(0)

# 3. Require both team_name and run_id
if not state.get("team_name") or not state.get("run_id"):
    print("ERROR: state.yaml is missing team_name or run_id.")
    print("State is unrecoverable. Use --force to start fresh.")
    exit(1)

team_name = state["team_name"]
run_id = state["run_id"]

# 4. Rebuild ticket_status_map from TaskList (authoritative)
tasks = TaskList(**BASE_FILTER)
ticket_status_map = {task.subject: task.status for task in tasks}

# 5. If all terminal: proceed directly to Phase 5
terminal = {"completed", "failed"}
if all(v in terminal for v in ticket_status_map.values()):
    goto Phase5()

# 6. Otherwise: print status table, enter monitoring loop
print_status_table(ticket_status_map)
goto Phase4_MonitoringLoop()
```

---

## Phase 1 — Intake

### Duplicate Guard

```python
def revoke_run(run_id):
    """Write run_id to revoked_runs.yaml. Workers check this on startup."""
    revoked = load_yaml(REVOKED_FILE) or {"revoked": []}
    if run_id not in revoked["revoked"]:
        revoked["revoked"].append(run_id)
    write_yaml(REVOKED_FILE, revoked)

def archive_state(path):
    import time
    ts = int(time.time())
    rename(path, f"{path}.bak.{ts}")
```

```python
state = load_yaml(STATE_FILE)  # None if not found

if state is not None:
    if state["phase"] != "done":
        # Active run exists
        if not force:
            print(f"ERROR: Active run {state['run_id']} exists (phase={state['phase']}).")
            print("Use --force to override, or --resume to continue.")
            exit(1)
        else:
            # --force: check for active workers
            tasks = TaskList(**BASE_FILTER, status="in_progress")
            active_tasks = [t for t in tasks]
            if active_tasks and not force_kill:
                print(f"ERROR: {len(active_tasks)} workers still active.")
                print("Use --force-kill to terminate active workers, or --resume to continue.")
                exit(1)
            # Revoke and archive
            revoke_run(state["run_id"])         # write revoked_runs.yaml
            TeamDelete(state["team_name"])       # best-effort, non-fatal
            archive_state(STATE_FILE)            # rename to state.yaml.bak.{timestamp}
    else:
        # phase == "done"
        if not force:
            print_done_summary(state)
            print("Run is already complete (idempotent). Use --force to re-run.")
            exit(0)
        # --force on done run: continue to start fresh (archive and proceed)
        archive_state(STATE_FILE)
```

### Working Directory Guard

```python
import os
cwd = os.getcwd()
has_omniclaude = os.path.isdir(os.path.join(cwd, "plugins/onex"))
has_omnibase  = os.path.isdir(os.path.join(cwd, "../omnibase_core"))

if not has_omniclaude or not has_omnibase:
    missing = []
    if not has_omniclaude: missing.append("plugins/onex (omniclaude marker)")
    if not has_omnibase:   missing.append("../omnibase_core")
    print(f"ERROR: Working directory guard failed. Missing: {', '.join(missing)}")
    print(f"Current directory: {cwd}")
    print("Run this skill from the omniclaude repository root.")
    exit(1)
```

### Actions

```python
# 1. Fetch epic from Linear
epic = mcp_linear_get_issue(id=epic_id)
print(f"Epic: {epic.title} ({epic_id})")

# 2. Generate run_id (needed before empty-ticket check for auto-decompose dispatch)
import uuid
run_id = str(uuid.uuid4())

# 3. Fetch all child tickets
tickets = mcp_linear_list_issues(parentId=epic_id, limit=250)
print(f"Found {len(tickets)} child tickets")
if len(tickets) == 0:
    # Auto-decompose: invoke decompose-epic sub-skill, post LOW_RISK Slack gate
    if dry_run:
        # Dry-run: invoke decompose-epic with --dry-run flag (plan only, no tickets created)
        Task(
            subagent_type="onex:polymorphic-agent",
            description=f"epic-team: dry-run decompose empty epic {epic_id}",
            prompt=f"""The epic {epic_id} has no child tickets. Invoke decompose-epic in dry-run mode.
    Run ID: {run_id}
    Invoke: Skill(skill="onex:decompose-epic", args="{epic_id} --dry-run")

    Print the decomposition plan returned by decompose-epic.
    Do NOT create any tickets. Do NOT post Slack gate.
    Report back with: the decomposition plan."""
        )
        print("\n--- DRY RUN: Empty epic decomposition plan above. No tickets created. ---")
        exit(0)

    # Normal run: auto-decompose and post Slack gate
    decompose_result = Task(
        subagent_type="onex:polymorphic-agent",
        description=f"epic-team: auto-decompose empty epic {epic_id}",
        prompt=f"""The epic {epic_id} has no child tickets. Invoke decompose-epic to create them.
    Run ID: {run_id}
    Invoke: Skill(skill="onex:decompose-epic", args="{epic_id}")

    Read the ModelSkillResult from ~/.claude/skill-results/{run_id}/decompose-epic.json
    Report back with: created_tickets (list of ticket IDs and titles), count."""
    )
    created_tickets = decompose_result.get("created_tickets", [])
    ticket_count = len(created_tickets)

    # Post LOW_RISK Slack gate
    tickets_list = "\n".join(f"  - {t['id']}: {t['title']}" for t in created_tickets)
    slack_gate_message = (
        f"[LOW_RISK] epic-team: Auto-decomposed {epic_id}\n\n"
        f"Epic had no child tickets. Created {ticket_count} sub-tickets:\n"
        f"{tickets_list}\n\n"
        f"Reply reject within 30 minutes to cancel. Silence = proceed with orchestration."
    )
    gate_status = "approved"  # default: proceed on gate failure (fail-open)
    try:
        gate_result = Task(
            subagent_type="onex:polymorphic-agent",
            description=f"epic-team: post Slack LOW_RISK gate for {epic_id}",
            prompt=f"""Post this Slack gate message and wait up to 30 minutes for a reject reply.
    Invoke: Skill(skill="onex:slack-gate", args="--message {slack_gate_message} --timeout 30m --keyword reject")

    If reject received: report status=rejected
    If timeout (silence): report status=approved
    Report back with: status (approved or rejected)."""
        )
        gate_status = gate_result.get("status", "approved")
    except Exception as e:
        print(f"Warning: Slack gate failed (non-fatal): {e}")
        # On Slack gate failure, proceed (fail-open)

    if gate_status == "rejected":
        print("Decomposition rejected by human via Slack. Stopping.")
        try:
            notify_pipeline_rejected(epic_id=epic_id, run_id=run_id)
        except Exception as e:
            print(f"Warning: Slack rejection notification failed (non-fatal): {e}")
        exit(0)

    # Re-fetch newly created tickets after gate approval
    tickets = mcp_linear_list_issues(parentId=epic_id, limit=250)
    print(f"Auto-decompose complete. Re-fetched {len(tickets)} child tickets.")
    if len(tickets) == 0:
        print("ERROR: decompose-epic created no tickets. Cannot proceed.")
        exit(1)

# 4. PERSIST state.yaml
import datetime
state = {
    "epic_id": epic_id,
    "run_id": run_id,
    "team_name": None,          # populated in Phase 3
    "phase": "intake",
    "slack_thread_ts": None,
    "slack_ts_candidates": [],
    "slack_last_error": None,
    "start_time": datetime.datetime.utcnow().isoformat() + "Z",
    "end_time": None,
    "assignments": {},
    "cross_repo_splits": [],
    "tickets": [t.__dict__ for t in tickets],  # persisted for Phase 2 use on resume
    "ticket_scores": {},
    "ticket_status_map": {},
    "pr_urls": {},
}
os.makedirs(STATE_DIR, exist_ok=True)
write_yaml(STATE_FILE, state)
print(f"State initialized. run_id={run_id}")
```

---

## Phase 2 — Decomposition

### Actions

```python
# Assert phase == "intake"
state = load_yaml(STATE_FILE)
assert state["phase"] == "intake", f"Expected phase=intake, got {state['phase']}"

# 1. Load repo manifest
MANIFEST_PATH = "plugins/onex/skills/epic-team/repo_manifest.yaml"
manifest = load_yaml(MANIFEST_PATH)
if manifest is None:
    print(f"ERROR: repo_manifest.yaml not found at {MANIFEST_PATH}")
    exit(1)

# 2. Decompose epic
from plugins.onex.skills.epic_team.epic_decomposer import decompose_epic, validate_decomposition
result = decompose_epic(tickets=state["tickets"], manifest_path=MANIFEST_PATH)

# 3. Validate
errors = validate_decomposition(result)
if errors:
    print("HARD FAIL: Decomposition validation errors:")
    for e in errors:
        print(f"  - {e}")
    exit(1)

# 4. Print decomposition table
print_decomposition_table(result)

# 5. Unmatched gate
unmatched = [t for t in result["ticket_scores"] if result["ticket_scores"][t]["matched_repo"] is None]
if unmatched:
    print(f"\n{len(unmatched)} unmatched ticket(s):")
    for tid in unmatched:
        score = result["ticket_scores"][tid]
        print(f"  {tid}: {score.get('reason', 'no reason given')}")

    if not force_unmatched:
        print("\nERROR: Unmatched tickets block decomposition.")
        print("Use --force-unmatched to assign them to omniplan for triage, or resolve them manually.")
        exit(1)
    else:
        # Assign unmatched to omniplan with triage marking
        for tid in unmatched:
            result["assignments"].setdefault("omniplan", []).append(tid)
            result["ticket_scores"][tid]["triage"] = True
        print("--force-unmatched: unmatched tickets assigned to omniplan for triage.")

# 6. Dry-run stop
if dry_run:
    print("\n--- DRY RUN: Full plan below. No resources created. ---")
    print_full_plan(result)
    print("\nCross-repo split rationale:")
    for split in result.get("cross_repo", []):
        print(f"  {split['ticket_id']}: {split['rationale']}")
    print("\n--- DRY RUN COMPLETE ---")
    exit(0)

# PERSIST
state["phase"] = "decomposed"
state["assignments"] = result["assignments"]
state["cross_repo_splits"] = result.get("cross_repo", [])
state["ticket_scores"] = result["ticket_scores"]
write_yaml(STATE_FILE, state)
print("Phase 2 complete: decomposition persisted.")
```

---

## Phase 3 — Team Setup + Spawn

### Actions

```python
# Assert phase == "decomposed"
state = load_yaml(STATE_FILE)
assert state["phase"] == "decomposed", f"Expected phase=decomposed, got {state['phase']}"

epic_id  = state["epic_id"]
run_id   = state["run_id"]

# 1. Create team
team_name = f"epic-{epic_id}-{run_id[:8]}"
TeamCreate(team_name=team_name)

# 2. PERSIST team_name and phase BEFORE any TaskCreate
state["phase"] = "spawned"
state["team_name"] = team_name
write_yaml(STATE_FILE, state)
print(f"Team created and persisted: {team_name}")

# 3. Create tasks — two-pass strategy to enforce cross-repo part ordering.
#
# Pass 1: Create all non-split tasks AND all Part 1 split tasks.
#         After Pass 1, persist cross_repo_splits (with part1_task_id populated)
#         to state.yaml before touching Part 2 tasks.
# Pass 2: Create all Part 2 split tasks, using part1_task_id from state.yaml
#         as the addBlockedBy dependency.
#
# This ordering is mandatory. If Part 2 tasks were created before their
# corresponding Part 1 task, split["part1_task_id"] would be missing (KeyError).

assignments = state["assignments"]
cross_repo_splits = state["cross_repo_splits"]
# Build a lookup keyed by (ticket_id, part) to avoid ambiguity
cross_repo_by_ticket_part = {(s["ticket_id"], s["part"]): s for s in cross_repo_splits}

def make_task_kwargs(repo, ticket_id, split, part):
    ticket = get_ticket(ticket_id)  # from tickets persisted to state.yaml in Phase 1
    score = state["ticket_scores"].get(ticket_id, {})
    is_triage = score.get("triage", False)
    triage_tag = "[triage:true]" if is_triage else ""

    if part == 1:
        part_tag = f"[origin:{split['origin_repo']}][part:1-of-2]"
    elif part == 2:
        part_tag = f"[part:2-of-2]"
    else:
        part_tag = ""

    description = (
        f"[epic:{epic_id}][run:{run_id}][repo:{repo}]"
        f"[lease:{run_id[:8]}:{repo}]"
        f"{triage_tag}{part_tag} {ticket.title} — {ticket.url}"
    )
    subject = f"TRIAGE-{ticket_id} [{repo}]" if is_triage else f"{ticket_id} [{repo}]"
    return {"subject": subject, "description": description, "owner": f"worker-{repo}"}

# --- Pass 1: non-split tasks + Part 1 split tasks ---
for repo, ticket_ids in assignments.items():
    for ticket_id in ticket_ids:
        split_part2 = cross_repo_by_ticket_part.get((ticket_id, 2))
        split_part1 = cross_repo_by_ticket_part.get((ticket_id, 1))

        if split_part2:
            # This assignment entry is a Part 2 split — skip in Pass 1
            continue

        split = split_part1  # None for non-split tickets
        part = 1 if split_part1 else None
        kwargs = make_task_kwargs(repo, ticket_id, split, part)
        task = TaskCreate(**kwargs)

        # Store part1_task_id in the split descriptor for Pass 2 use
        if split_part1:
            split_part1["part1_task_id"] = task.id
            print(f"  [pass-1] Part 1 task created: {task.id} for {ticket_id} [{repo}]")
        else:
            print(f"  [pass-1] Task created: {task.id} for {ticket_id} [{repo}]")

# Persist cross_repo_splits with part1_task_id populated BEFORE Pass 2
state["cross_repo_splits"] = list(cross_repo_by_ticket_part.values())
write_yaml(STATE_FILE, state)
print("  [pass-1] cross_repo_splits (with part1_task_id) persisted to state.yaml.")

# --- Pass 2: Part 2 split tasks (part1_task_id now available from state.yaml) ---
for repo, ticket_ids in assignments.items():
    for ticket_id in ticket_ids:
        split_part2 = cross_repo_by_ticket_part.get((ticket_id, 2))
        if not split_part2:
            continue

        # Resolve part1_task_id from the persisted Part 1 split descriptor
        split_part1 = cross_repo_by_ticket_part.get((ticket_id, 1))
        part1_task_id = split_part1["part1_task_id"] if split_part1 else split_part2.get("part1_task_id")
        if not part1_task_id:
            raise RuntimeError(
                f"Cannot create Part 2 task for {ticket_id}: part1_task_id not found. "
                "This is a bug — Part 1 must be created and persisted before Part 2."
            )

        kwargs = make_task_kwargs(repo, ticket_id, split_part2, 2)
        kwargs["addBlockedBy"] = [part1_task_id]
        task = TaskCreate(**kwargs)
        print(f"  [pass-2] Part 2 task created: {task.id} for {ticket_id} [{repo}] (blocked by {part1_task_id})")

print(f"All tasks created for team {team_name}.")

# 4. Notify Slack (non-fatal)
try:
    slack_thread_ts = notify_pipeline_started(
        epic_id=epic_id,
        run_id=run_id,
        team_name=team_name,
        ticket_count=sum(len(v) for v in assignments.values()),
    )
except Exception as e:
    slack_thread_ts = None
    state["slack_last_error"] = str(e)
    print(f"Warning: Slack notification failed (non-fatal): {e}")

# PERSIST slack_thread_ts only if non-None; never overwrite existing non-None with None
if slack_thread_ts is not None:
    state["slack_thread_ts"] = slack_thread_ts
# Never: state["slack_thread_ts"] = slack_thread_ts  (if it could be None and existing is set)
# Only initialize slack_ts_candidates if not already present (preserve on re-entry/resume)
if "slack_ts_candidates" not in state:
    state["slack_ts_candidates"] = []
write_yaml(STATE_FILE, state)

# 5. Spawn workers
for repo in assignments.keys():
    worker_prompt = WORKER_TEMPLATE.format(
        repo=repo,
        epic_id=epic_id,
        run_id=run_id,
        team_name=team_name,
        run_id_short=run_id[:8],
    )
    Task(
        subagent_type="onex:polymorphic-agent",
        team_name=team_name,
        name=f"worker-{repo}",
        prompt=worker_prompt,
    )
    print(f"Spawned worker-{repo}")

print("Phase 3 complete: all workers spawned.")
```

---

## Phase 4 — Monitoring

```python
# PERSIST phase="monitoring" first
state = load_yaml(STATE_FILE)
assert state["phase"] in ("spawned", "monitoring"), f"Unexpected phase {state['phase']}"
state["phase"] = "monitoring"
write_yaml(STATE_FILE, state)

import hashlib, json

def state_hash(s):
    return hashlib.md5(json.dumps(s, sort_keys=True).encode()).hexdigest()

terminal_statuses = {"completed", "failed"}
notified_terminal = set()  # track which tasks we've already notified for

while True:
    # --- Rebuild ticket_status_map from TaskList (authoritative) ---
    tasks = TaskList(**BASE_FILTER)
    new_map = {task.subject: task.status for task in tasks}

    # Persist only if changed
    old_hash = state_hash(state.get("ticket_status_map", {}))
    new_hash = state_hash(new_map)
    if old_hash != new_hash:
        state["ticket_status_map"] = new_map
        write_yaml(STATE_FILE, state)

    # --- Console: print status table at every team-lead turn ---
    print_status_table(new_map, team_name=state["team_name"])

    # --- Fire Slack for newly-terminal tasks ---
    # ONLY fire Slack on notify_ticket_completed/failed (no Slack during polling)
    for subject, status in new_map.items():
        if status in terminal_statuses and subject not in notified_terminal:
            notified_terminal.add(subject)
            try:
                if status == "completed":
                    ts = notify_ticket_completed(
                        subject=subject,
                        slack_thread_ts=state.get("slack_thread_ts"),
                    )
                else:
                    ts = notify_ticket_failed(
                        subject=subject,
                        slack_thread_ts=state.get("slack_thread_ts"),
                    )
                # If slack_thread_ts was None, capture the returned ts
                if state["slack_thread_ts"] is None and ts is not None:
                    state["slack_thread_ts"] = ts
                    write_yaml(STATE_FILE, state)
            except Exception as e:
                state["slack_last_error"] = str(e)
                write_yaml(STATE_FILE, state)
                print(f"Warning: Slack notification failed for {subject}: {e}")

    # --- Handle worker SendMessage (telemetry only) ---
    # If a worker sends a message (e.g., PR URL update):
    #   - Log it
    #   - Update pr_urls in state.yaml if message contains pr_url
    #   - Do NOT update ticket_status_map from messages alone
    # (This block executes when a message arrives between polling turns)

    # --- Check for finalization ---
    if new_map and all(v in terminal_statuses for v in new_map.values()):
        print("All tasks terminal. Proceeding to Phase 5.")
        goto Phase5()

    # Wait for next team-lead turn (event-driven; no busy loop)
    wait_for_event_or_timeout()
```

### Worker SendMessage Handling

When a worker sends a message, process it as follows:

```python
def handle_worker_message(message):
    """Process incoming worker SendMessage. Telemetry only."""
    print(f"[telemetry] Worker message received: {message.sender}")

    # Extract and store pr_url if present
    if "pr_url" in message.content:
        pr_url = message.content["pr_url"]
        ticket_id = message.content.get("ticket_id")
        if ticket_id:
            state = load_yaml(STATE_FILE)
            state["pr_urls"][ticket_id] = pr_url
            write_yaml(STATE_FILE, state)
            print(f"[telemetry] PR URL stored: {ticket_id} -> {pr_url}")

    # DO NOT update ticket_status_map here.
    # Status is only updated via TaskList polling.
    print(f"[telemetry] Message logged. TaskList remains authoritative for status.")
```

---

## Phase 5 — Done

```python
# PERSIST phase="done" and end_time FIRST — before any side effects
state = load_yaml(STATE_FILE)
import datetime
state["phase"] = "done"
state["end_time"] = datetime.datetime.utcnow().isoformat() + "Z"
write_yaml(STATE_FILE, state)
print("Phase 5: persisted done state.")

# 1. Notify Slack (non-fatal)
ticket_status_map = state.get("ticket_status_map", {})
completed = [s for s, v in ticket_status_map.items() if v == "completed"]
failed    = [s for s, v in ticket_status_map.items() if v == "failed"]
prs       = state.get("pr_urls", {})

try:
    notify_epic_done(
        completed=completed,
        failed=failed,
        prs=prs,
        slack_thread_ts=state.get("slack_thread_ts"),
    )
except Exception as e:
    print(f"Warning: Slack epic-done notification failed (non-fatal): {e}")

# 2. Print summary table
print("\n=== Epic Run Summary ===")
print(f"Epic:    {state['epic_id']}")
print(f"Run ID:  {state['run_id']}")
print(f"Team:    {state['team_name']}")
print(f"Start:   {state.get('start_time', 'unknown')}")
print(f"End:     {state['end_time']}")
print()
print(f"{'Repo':<20} {'Done':>6} {'Failed':>8} {'PRs'}")
print("-" * 60)
assignments = state.get("assignments", {})
for repo in assignments:
    repo_tickets = assignments[repo]
    done_count   = sum(1 for t in repo_tickets if ticket_status_map.get(f"{t} [{repo}]") == "completed"
                       or ticket_status_map.get(f"TRIAGE-{t} [{repo}]") == "completed")
    fail_count   = sum(1 for t in repo_tickets if ticket_status_map.get(f"{t} [{repo}]") == "failed"
                       or ticket_status_map.get(f"TRIAGE-{t} [{repo}]") == "failed")
    repo_prs     = [url for tid, url in prs.items() if tid in repo_tickets]
    pr_str       = ", ".join(repo_prs) if repo_prs else "—"
    print(f"{repo:<20} {done_count:>6} {fail_count:>8}  {pr_str}")
print()
if failed:
    print(f"FAILED tasks ({len(failed)}):")
    for f in failed:
        print(f"  - {f}")
    print()

# 3. Print worktree locations and cleanup commands
print("=== Worktree Locations ===")
print("Each worker created a git worktree. Locations (workers do NOT auto-delete them):")
for repo in assignments:
    for ticket_id in assignments[repo]:
        wt_path = f"../{repo}/.claude/worktrees/{epic_id}/{run_id[:8]}/{ticket_id}"
        branch  = f"epic/{epic_id}/{ticket_id}/{run_id[:8]}"
        print(f"\n  {ticket_id} [{repo}]")
        print(f"    Path:   {wt_path}")
        print(f"    Branch: {branch}")
        print(f"    Remove: git -C ../{repo} worktree remove --force {wt_path}")

print()
print("=== Cleanup ===")
print(f"To remove the task team (if still present):")
print(f"  TeamDelete({state['team_name']})")

# 4. TeamDelete — best-effort, non-fatal
try:
    TeamDelete(state["team_name"])
    print(f"Team {state['team_name']} deleted.")
except Exception as e:
    print(f"Warning: TeamDelete failed (non-fatal): {e}")
    print(f"You may need to delete team {state['team_name']} manually.")
```

---

## Worker Prompt Template

The following constant `WORKER_TEMPLATE` is embedded in the team-lead orchestration. It is filled with `repo`, `epic_id`, `run_id`, `team_name`, `run_id_short` before spawning each worker.

```python
WORKER_TEMPLATE = """
You are a worker agent for epic {epic_id}, assigned to repository {repo}.
Team: {team_name} | Run: {run_id}

## Startup Validation

Before claiming any task, perform these checks:

### 1. Path Check

Verify you are in a valid environment:

```python
import os
cwd = os.getcwd()
expected_markers = ["plugins/onex"]  # omniclaude repo root markers
if not any(os.path.isdir(os.path.join(cwd, m)) for m in expected_markers):
    print(f"ERROR: Worker path check failed. CWD={cwd}")
    print("Expected to be in omniclaude repo root.")
    exit(1)
```

### 2. Revocation Check

Check whether this run has been revoked:

```python
REVOKED_FILE = f"~/.claude/epics/{epic_id}/revoked_runs.yaml"
revoked_data = load_yaml(REVOKED_FILE) or {{"revoked": []}}
if "{run_id}" in revoked_data["revoked"]:
    print(f"Run {run_id} has been revoked. Exiting.")
    exit(0)
```

## Task Discovery

Use the triple filter to find tasks assigned to this worker:

```python
BASE_FILTER = {{
    "team_name": "{team_name}",
    "description__contains": [
        "[epic:{epic_id}]",
        "[run:{run_id}]",
    ]
}}
WORKER_FILTER = {{**BASE_FILTER, "owner": "worker-{repo}", "status": "todo"}}

tasks = TaskList(**WORKER_FILTER)
if not tasks:
    print("No tasks found for worker-{repo} in run {run_id}. Nothing to do.")
    SendMessage(
        to="team-lead",
        content={{
            "status": "idle",
            "repo": "{repo}",
            "message": "No tasks found. Worker exiting."
        }}
    )
    exit(0)
```

## Lease Token Verification

Before claiming a task, verify the lease token in the description:

```python
def verify_lease(task):
    expected_lease = f"[lease:{run_id_short}:{repo}]"
    if expected_lease not in task.description:
        print(f"WARNING: Task {{task.id}} lease mismatch. Expected {{expected_lease}}.")
        print(f"Description: {{task.description[:200]}}")
        return False
    return True
```

Where `run_id_short = "{run_id_short}"` (first 8 chars of run_id).

## Task Claim

For each task in `tasks`:

```python
for task in tasks:
    # Verify lease token
    if not verify_lease(task):
        print(f"Skipping task {{task.id}}: lease mismatch.")
        continue

    # Check for blocked tasks (cross-repo part 2)
    if task.status == "blocked":
        print(f"Task {{task.id}} is blocked. Skipping for now.")
        continue

    # Claim: update status to in_progress
    TaskUpdate(task_id=task.id, status="in_progress")

    # Re-fetch to confirm claim (verify status is in_progress and owner is us)
    claimed = TaskGet(task_id=task.id)
    if claimed.status != "in_progress" or claimed.owner != "worker-{repo}":
        print(f"Task {{task.id}} claim failed (race condition). Skipping.")
        continue

    # Notify team-lead of claim (telemetry)
    SendMessage(
        to="team-lead",
        content={{
            "event": "task_claimed",
            "task_id": task.id,
            "ticket_id": extract_ticket_id(task.description),
            "repo": "{repo}",
        }}
    )

    # Execute ticket work
    execute_ticket(task)
```

## Worktree Setup

For each ticket, create a git worktree at the canonical path:

```python
def setup_worktree(ticket_id):
    repo_path = f"../{repo}"
    worktree_root = f"{{repo_path}}/.claude/worktrees/{epic_id}/{run_id_short}/{{ticket_id}}"
    branch = f"epic/{epic_id}/{{ticket_id}}/{run_id_short}"

    # Create worktree
    import subprocess
    result = subprocess.run(
        ["git", "-C", repo_path, "worktree", "add", "-b", branch,
         worktree_root, "origin/main"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"Worktree creation failed: {{result.stderr}}")

    return worktree_root, branch
```

Canonical root path: `../{repo}/.claude/worktrees/{epic_id}/{run_id_short}/{{ticket_id}}`
Branch format: `epic/{epic_id}/{{ticket_id}}/{run_id_short}`

## Ticket Work Execution

```python
def execute_ticket(task):
    ticket_id = extract_ticket_id(task.description)
    is_triage = "[triage:true]" in task.description

    try:
        worktree_path, branch = setup_worktree(ticket_id)

        if is_triage:
            # Triage tickets: analyze and create sub-tickets, no implementation
            result = Skill("onex:triage-ticket", args=ticket_id, cwd=worktree_path)
        else:
            # Normal ticket: invoke ticket-work skill
            result = Skill("onex:ticket-work", args=ticket_id, cwd=worktree_path)

        # Extract PR URL if present in result
        pr_url = extract_pr_url(result)

        # SUCCESS: update task status BEFORE sending message
        TaskUpdate(task_id=task.id, status="completed")

        # Send success message (after status update)
        SendMessage(
            to="team-lead",
            content={{
                "event": "task_completed",
                "task_id": task.id,
                "ticket_id": ticket_id,
                "repo": "{repo}",
                "pr_url": pr_url,
                "worktree": worktree_path,
                "branch": branch,
            }}
        )

    except Exception as e:
        # FAILURE: update task status BEFORE sending message
        TaskUpdate(task_id=task.id, status="failed")

        # Send failure message (after status update)
        SendMessage(
            to="team-lead",
            content={{
                "event": "task_failed",
                "task_id": task.id,
                "ticket_id": ticket_id,
                "repo": "{repo}",
                "error": str(e),
            }}
        )
```

**Ordering rule**: TaskUpdate (status=completed/failed) MUST happen BEFORE SendMessage. This ensures the team-lead's TaskList polling sees terminal status before processing any notification.

## Final Summary

After processing all tasks, send a final summary:

```python
completed_tasks = [t for t in all_processed if t.final_status == "completed"]
failed_tasks    = [t for t in all_processed if t.final_status == "failed"]

SendMessage(
    to="team-lead",
    content={{
        "event": "worker_done",
        "repo": "{repo}",
        "run_id": "{run_id}",
        "team_name": "{team_name}",
        "summary": {{
            "total":     len(all_processed),
            "completed": len(completed_tasks),
            "failed":    len(failed_tasks),
            "pr_urls":   {{t.ticket_id: t.pr_url for t in completed_tasks if t.pr_url}},
        }},
    }}
)
```

"""
```

---

## State File Schema

### `~/.claude/epics/{epic_id}/state.yaml`

```yaml
# --- Identity ---
epic_id: "OMN-XXXX"               # Epic ticket ID from Linear
run_id: "uuid-v4-string"          # Unique run identifier (uuid4)
team_name: "epic-OMN-XXXX-abc12345"  # Claude team name (null until Phase 3)

# --- Phase ---
phase: "intake"                    # intake | decomposed | spawned | monitoring | done

# --- Slack ---
slack_thread_ts: null              # Slack thread timestamp (null until first message sent)
slack_ts_candidates: []            # Candidate thread timestamps (for deduplication)
slack_last_error: null             # Last Slack error string (for debugging)

# --- Timing ---
start_time: "2026-01-01T00:00:00Z"  # ISO 8601 UTC
end_time: null                       # ISO 8601 UTC (null until phase=done)

# --- Intake ---
tickets:                           # Raw ticket data from Phase 1 (persisted for Phase 2 on resume)
  - id: "OMN-1001"
    title: "Ticket title"
    url: "https://linear.app/..."

# --- Decomposition ---
assignments:                       # Map of repo -> [ticket_id, ...]
  omniclaude: ["OMN-1001", "OMN-1002"]
  omnibase_core: ["OMN-1003"]
  omniplan: ["OMN-1004"]           # Unmatched tickets (when --force-unmatched)

cross_repo_splits:                 # List of cross-repo split descriptors
  - ticket_id: "OMN-1005"
    origin_repo: "omniclaude"
    part: 1
    part1_task_id: "task-abc"      # Populated after TaskCreate
    rationale: "Touches both omniclaude hooks and omnibase_core contracts"
  - ticket_id: "OMN-1005"
    origin_repo: "omniclaude"
    part: 2
    rationale: "omnibase_core side of OMN-1005 split"

ticket_scores:                     # Per-ticket decomposition metadata
  OMN-1001:
    matched_repo: "omniclaude"
    score: 0.92
    reason: "Touches plugins/onex hooks"
    triage: false
  OMN-1004:
    matched_repo: null
    score: 0.0
    reason: "No repo match found"
    triage: true

# --- Runtime ---
ticket_status_map:                 # Subject -> status (rebuilt from TaskList each turn)
  "OMN-1001 [omniclaude]": "completed"
  "OMN-1002 [omniclaude]": "in_progress"
  "OMN-1003 [omnibase_core]": "todo"

pr_urls:                           # ticket_id -> PR URL (populated by worker messages)
  OMN-1001: "https://github.com/org/omniclaude/pull/42"
```

### `~/.claude/epics/{epic_id}/revoked_runs.yaml`

Workers check this file during startup validation. If their `run_id` appears here, they self-terminate immediately.

```yaml
revoked:
  - "uuid-of-run-1"    # Previously force-killed runs
  - "uuid-of-run-2"
```

**Write procedure**: Always read-merge-write (never overwrite). Append the new run_id to the existing list.

---

## Error Reference

| Condition | Message | Exit |
|-----------|---------|------|
| No epic_id argument | `Error: epic_id is required. Usage: /epic-team OMN-1234` | 1 |
| Invalid epic_id format | `Error: Invalid epic_id format '...'` | 1 |
| Active run without --force | `ERROR: Active run {run_id} exists (phase={phase}). Use --force...` | 1 |
| Active workers without --force-kill | `ERROR: {n} workers still active. Use --force-kill...` | 1 |
| Working dir missing plugins/onex | `ERROR: Working directory guard failed. Missing: plugins/onex` | 1 |
| Working dir missing ../omnibase_core | `ERROR: Working directory guard failed. Missing: ../omnibase_core` | 1 |
| No child tickets (decompose-epic returned 0) | `ERROR: decompose-epic created no tickets. Cannot proceed.` | 1 |
| Slack gate rejected by human | `Decomposition rejected by human via Slack. Stopping.` | 0 |
| repo_manifest.yaml not found | `ERROR: repo_manifest.yaml not found at plugins/onex/skills/epic-team/repo_manifest.yaml` | 1 |
| Decomposition validation errors | `HARD FAIL: Decomposition validation errors: [...]` | 1 |
| Unmatched tickets without --force-unmatched | `ERROR: Unmatched tickets block decomposition. Use --force-unmatched...` | 1 |
| --resume with no state.yaml | `ERROR: state.yaml not found. Cannot resume.` | 1 |
| --resume missing team_name/run_id | `ERROR: state.yaml is missing team_name or run_id. Use --force.` | 1 |
| Phase == "done" without --force | (print summary) `Run is already complete (idempotent).` | 0 |

---

## Execution Checklist

Before marking any phase complete, verify:

- [ ] Phase asserted before executing logic
- [ ] New phase persisted to state.yaml BEFORE side effects
- [ ] All TaskList calls use the triple filter (team_name + epic_id + run_id)
- [ ] No status decisions made from worker messages alone
- [ ] slack_thread_ts never overwritten with None if currently non-None
- [ ] TaskUpdate (completed/failed) fires BEFORE SendMessage in workers
- [ ] TeamDelete called best-effort (non-fatal) in Phase 5
- [ ] Slack notifications non-fatal everywhere
- [ ] Worktree locations printed for manual cleanup (never auto-deleted)
