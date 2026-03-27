---
description: Worktree lifecycle manager -- wraps prune-worktrees.sh as a skill with cron scheduling for automatic GC of merged worktrees
mode: full
version: 1.0.0
level: intermediate
debug: false
category: maintenance
tags:
  - worktrees
  - cleanup
  - lifecycle
  - cron
  - automation
author: OmniClaude Team
composable: true
args:
  - name: --execute
    description: "Actually remove stale worktrees (default: dry-run report only)"
    required: false
  - name: --schedule
    description: "Schedule recurring GC via CronCreate (e.g., '2h', '30m'). Runs --execute on each tick."
    required: false
  - name: --verbose
    description: "Show active and skipped worktrees in addition to stale ones"
    required: false
  - name: --worktrees-root
    description: "Override worktrees root path (default: $OMNI_WORKTREES)" # local-path-ok
    required: false
---

# Worktree Lifecycle Manager

## Dispatch Requirement <!-- ai-slop-ok: skill-step-heading -->

When invoked, dispatch to a polymorphic-agent:

```
Agent(
  subagent_type="onex:polymorphic-agent",
  description="Run worktree-lifecycle GC",
  prompt="Run the worktree-lifecycle skill. <full context and args>"
)
```

**CRITICAL**: `subagent_type` MUST be `"onex:polymorphic-agent"` (with the `onex:` prefix).

**Skill ID**: `onex:worktree_lifecycle`
**Version**: 1.0.0
**Owner**: omniclaude
**Ticket**: OMN-6741

---

## Purpose

Manages the lifecycle of git worktrees under the omni_worktrees directory. Wraps
the existing `scripts/prune-worktrees.sh` with skill orchestration, adds cron
scheduling for automatic garbage collection, and reports results.

A worktree is stale when:
- Its branch's PR has been merged (state=MERGED via `gh pr list`)
- Its remote branch no longer exists

---

## Usage

```
/worktree-lifecycle                          # dry-run: report stale worktrees
/worktree-lifecycle --execute                # remove stale worktrees
/worktree-lifecycle --schedule 2h            # schedule GC every 2 hours
/worktree-lifecycle --verbose                # include active worktrees in report
```

---

## Behavior

### Step 1: Parse arguments <!-- ai-slop-ok: skill-step-heading -->

| Argument | Default | Description |
|----------|---------|-------------|
| `--execute` | false | Remove stale worktrees (vs dry-run) |
| `--schedule` | none | Cron interval for recurring GC |
| `--verbose` | false | Show active/skipped worktrees |
| `--worktrees-root` | (system default) | Override worktrees root | <!-- local-path-ok -->

### Step 2: Run prune-worktrees.sh <!-- ai-slop-ok: skill-step-heading -->

Invoke the existing prune script:

```bash
bash scripts/prune-worktrees.sh ${execute_flag} ${verbose_flag} ${root_flag}
```

The script:
1. Scans for `.git` worktree pointers under the worktrees root
2. Extracts branch and remote info for each worktree
3. Queries GitHub PR state via `gh pr list --state merged`
4. Classifies each worktree as stale or active
5. In `--execute` mode, runs `git worktree remove` for stale entries

### Step 3: Report results <!-- ai-slop-ok: skill-step-heading -->

Output summary:

```
Worktree Lifecycle Report
=========================

Stale (removed):
  /omni_worktrees/OMN-1234/omniclaude — PR #42 merged 2d ago
  /omni_worktrees/OMN-1235/omnibase_core — remote branch deleted

Active (kept):
  /omni_worktrees/OMN-1300/omniclaude — PR #55 open

Removed: 2 | Active: 1 | Total: 3
```

### Step 4: Schedule recurring GC (if --schedule) <!-- ai-slop-ok: skill-step-heading -->

If `--schedule` is provided, use CronCreate to schedule recurring execution:

```
CronCreate(
  cron="<parsed from interval>",
  prompt="/worktree-lifecycle --execute",
  recurring=true
)
```

Report the cron job ID for later cancellation via CronDelete.

---

## Integration Points

- **autopilot close-out**: Can be added as a maintenance step
- **prune-worktrees.sh**: This skill wraps the existing script (no reimplementation)
- **begin-day**: Natural companion -- clean up stale worktrees at start of day
