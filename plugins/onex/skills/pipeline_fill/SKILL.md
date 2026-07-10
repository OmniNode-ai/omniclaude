---
description: RSD-driven continuous pipeline fill — queries Linear for unstarted tickets, scores by acceleration, and dispatches to the appropriate execution path
mode: full
version: 2.0.0
level: advanced
debug: false
category: workflow
tags:
  - pipeline
  - rsd
  - automation
  - linear
  - delegation
  - continuous
author: OmniClaude Team
args:
  - name: --dry-run
    description: Score and rank tickets, print the dispatch plan, but do not execute
    required: false
  - name: --wave-cap
    description: "Maximum concurrent dispatches (default: 5)"
    required: false
  - name: --once
    description: Run a single fill cycle then exit (do not loop)
    required: false
  - name: --min-score
    description: "Minimum RSD acceleration score to dispatch (default: 0.1)"
    required: false
  - name: --top-n
    description: "Maximum tickets to dispatch per cycle (default: 5)"
    required: false
boundary_exempt: true
---

# Pipeline Fill

## Tools Required

This skill spawns sub-workers via `Agent()`. Workers run in fresh sessions where the `Agent`
tool is **deferred** (schema not pre-loaded). Any worker that itself needs to dispatch
sub-agents must fetch the schema at session start:

```
ToolSearch(query="select:Agent,SendMessage,TaskCreate,TaskUpdate,TaskGet", max_results=5)
```

Add this call as the first action in every dispatch prompt that includes downstream `Agent()`
calls. Without it, the worker will see "Agent tool unavailable" when it tries to spawn.

## Backing Node

**This skill is a thin wrapper over `node_pipeline_fill` in omnimarket.**

The business logic (Linear query, RSD scoring, dispatch, state management) lives in:
- Node: `omnimarket.nodes.node_pipeline_fill`
- Handler: `HandlerPipelineFill`
- Command topic: `onex.cmd.omnimarket.pipeline-fill-start.v1`
- Completion event: `onex.evt.omnimarket.pipeline-fill-completed.v1`

Invoke the node directly (headless/cron/full-runtime) or use this skill for
interactive sessions.

## Dispatch Surface

**Target**: Interactive, Agent Teams, Headless, or CronCreate loop

```bash
# Interactive
/pipeline-fill

# One-shot
/pipeline-fill --once

# Dry run (score + rank, no dispatch)
/pipeline-fill --dry-run

# Scheduled via /loop
/loop 15m /pipeline-fill

# Scheduled via CronCreate
CronCreate("*/15 * * * *", "/pipeline-fill", recurring=true)

# Headless (publishes to node event bus)
claude -p "/pipeline-fill" \
  --allowedTools "Bash,Read,Write,Edit,Glob,Grep,Agent,tracker.*"
```

**Announce at start:** "I'm using the pipeline-fill skill to select and dispatch the highest-acceleration ticket."

## Interactive Execution

When invoked interactively (not headless), execute the full orchestration inline
using the same logic as `HandlerPipelineFill`:

### Phase 1: Query Linear

Query for unstarted tickets in the Active Sprint using `tracker.list_issues`.

**Filters:**
- State: `Backlog` or `Todo` (not `In Progress`, `In Review`, `Done`, `Canceled`)
- Cycle: Active Sprint (current cycle)
- Exclude: tickets with `blocked` label or unresolved blocking issues

### Phase 2: Filter Candidates

Remove tickets that should not be dispatched:

1. **Already dispatched**: Check `.onex_state/pipeline-fill/dispatched.yaml` for in-flight ticket IDs
2. **Blocked**: Tickets with `blocked` label or unresolved `blocked_by` relations
3. **Wave cap**: If current in-flight count >= wave cap, skip this cycle entirely

### Phase 3: Score via RSD

For each candidate, compute acceleration score using the weights from `HandlerPipelineFill._compute_rsd_score`:

```
score = 0.30 * blocking_score
      + 0.25 * priority_score
      + 0.20 * staleness_score
      + 0.15 * repo_readiness_score  (default 0.5 if no GitHub API)
      + 0.10 * size_score
```

### Phase 4: Dispatch Top-N

For each ticket above `--min-score` (default 0.1), up to `--top-n` (default 5):
1. Publish `onex.cmd.omnimarket.ticket-pipeline-start.v1` with `ticket_id`
2. Record in `.onex_state/pipeline-fill/dispatched.yaml` under `in_flight`

### Phase 5: Write State

Write `.onex_state/pipeline-fill/last-run.yaml` with cycle summary.

## Dry Run Mode

When `--dry-run` is passed, execute Phases 1-3 but skip Phase 4. Output:

```
Pipeline Fill — Dry Run
========================

Active Sprint Candidates: 12
After Filtering: 8
Wave Status: 3/5 in-flight (2 slots available)

Ranked Tickets:
  #1  TICKET-A  score=0.668  blocking=3  priority=High    → ticket-pipeline
  #2  TICKET-B  score=0.542  blocking=1  priority=High    → ticket-pipeline
  ...

Would dispatch: TICKET-A, TICKET-B
```

## State Files

All state written to `$ONEX_STATE_DIR/pipeline-fill/` (not a cwd-relative
`.onex_state/pipeline-fill/` — verified live 2026-07-02: the node resolves
`state_dir` through `$ONEX_STATE_DIR`, not the request model's literal default):

| File | Purpose |
|------|---------|
| `dispatched.yaml` | In-flight, completed, and failed ticket tracking |
| `last-run.yaml` | Timestamp and result of last cycle |

## Error Handling

| Failure | Behavior |
|---------|----------|
| Linear unreachable | Retry 3x with 60s backoff, log friction event, skip cycle |
| No candidates found | Log reason, skip cycle |
| Wave cap reached | Log "Wave cap reached (N/cap)", skip cycle |
| Dispatch failure | Move ticket to `failed` in dispatched.yaml, continue |

## Integration with /loop

```bash
/loop 15m /pipeline-fill          # Every 15 minutes
/loop 5m /pipeline-fill --wave-cap 8   # Aggressive fill
/loop 30m /pipeline-fill --wave-cap 3  # Conservative fill
```

## Routing Contract

- **Classification**: Deterministic
- **Backing node**: `node_pipeline_fill`
- **Dispatch (Kafka required)**: `onex run-node node_pipeline_fill --input '<envelope-json>'`
- **Local fallback (no Kafka — use whenever the broker is unreachable, the
  common case on a dev Mac)**: `onex node node_pipeline_fill --input <envelope-file>.json --output receipt`

Both forms run from `$OMNI_HOME/omnimarket` (canonical registry clone — never a bare `$ONEX_WORKTREES_ROOT/omnimarket`, which does not exist; worktrees are always ticket-scoped). # local-path-ok: OMNI_HOME is the correct canonical registry clone path for a source checkout per CLAUDE.md — ONEX_STATE_DIR/ONEX_WORKTREES_ROOT do not apply to a source checkout.

They accept the same `ModelPipelineFillCommand` fields (`correlation_id`, `top_n`,
`wave_cap`, `min_score`, `dry_run`, `state_dir`) — `run-node`'s `--input` takes
the JSON payload inline as text, `node`/`run`'s `--input` takes a path to a
JSON file. `pipeline_fill` is registered for the newer single-command `onex
skill <name>` dispatch (<TICKET>, mirroring `onex:session`'s migration) in
`omnibase_infra`'s `skill_mapping.yaml`, but that registration has not yet
reached the omnibase-infra release pinned by omnimarket — `onex skill
pipeline_fill` currently fails with `Unknown skill 'pipeline_fill'` (verified
live 2026-07-02). Until that release lands, the node-level commands above are
the only working dispatch path.

On non-zero exit, a `SkillRoutingError` JSON envelope is returned — surface it directly, do not produce prose.

---

## Verification

After each cycle (including no-op cycles), the backing node writes three observable
artifacts to `$ONEX_STATE_DIR/pipeline-fill/`:

| File | Written when | Contents |
|------|-------------|----------|
| `dispatched.yaml` | Tickets dispatched (not dry-run) | `in_flight`, `completed`, `failed` lists with ticket IDs, timestamps, RSD scores |
| `scores.yaml` | After RSD scoring (any cycle with candidates) | Ranked ticket IDs with `rsd_score`, `priority`, timestamp |
| `last-run.yaml` | Every cycle including no-ops | `timestamp`, `correlation_id`, `candidates_found`, `candidates_after_filter`, `dispatched`, `wave_status`, optional `skip_reason` |

**To confirm a cycle ran:**

```bash
# Check last-run timestamp
cat $ONEX_STATE_DIR/pipeline-fill/last-run.yaml

# Confirm in-flight tracking is populated
cat $ONEX_STATE_DIR/pipeline-fill/dispatched.yaml

# Inspect score ranking from last cycle
cat $ONEX_STATE_DIR/pipeline-fill/scores.yaml
```

If `last-run.yaml` is absent or stale, the node has not executed. A cycle that
skips dispatch (wave cap, no candidates, all below min-score) still writes
`last-run.yaml` with a `skip_reason` field.
