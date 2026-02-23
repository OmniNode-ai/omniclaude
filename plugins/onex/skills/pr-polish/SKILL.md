---
name: pr-polish
description: Full PR readiness loop — resolve merge conflicts, address all review comments and CI failures, then iterate local-review until N consecutive clean passes
version: 1.0.0
category: workflow
tags:
  - pr
  - review
  - conflicts
  - code-quality
  - iteration
author: OmniClaude Team
args:
  - name: pr_number
    description: PR number or URL (auto-detects from current branch if omitted)
    required: false
  - name: --required-clean-runs
    description: "Consecutive clean local-review passes required before done (default 4)"
    required: false
  - name: --max-iterations
    description: "Maximum local-review cycles (default 10)"
    required: false
  - name: --skip-conflicts
    description: Skip merge conflict resolution phase
    required: false
  - name: --skip-pr-review
    description: Skip PR review comments and CI failures phase
    required: false
  - name: --skip-local-review
    description: Skip local-review clean-pass loop phase
    required: false
  - name: --no-ci
    description: Skip CI failure analysis (passed through to pr-review-dev)
    required: false
  - name: --no-push
    description: Make all fixes but do not push to remote
    required: false
---

# PR Polish

## Overview

Three-phase PR readiness workflow that takes a branch from "open PR" to "clean and ready to merge":

1. **Conflict Resolution** — detect and resolve merge conflicts against the base branch
2. **PR Review + CI Fix** — fetch all open review comments and CI failures, fix Critical/Major/Minor via `pr-review-dev`
3. **Local Review Loop** — run `local-review` until N consecutive passes with nothing but nits (default N=4)

**Announce at start:** "I'm using the pr-polish skill to bring PR #{pr_number} to merge-ready state."

> **Classification System**: Uses onex pr-review keyword-based classification throughout.
> ALL Critical/Major/Minor issues MUST be resolved. Only Nits are optional.
> See: `${CLAUDE_PLUGIN_ROOT}/skills/pr-review/SKILL.md` for full priority definitions.

## Quick Start

```
/pr-polish                              # Auto-detect PR from current branch, 4 clean passes
/pr-polish 226                          # Specific PR number
/pr-polish 226 --required-clean-runs 2  # Faster iteration (2 clean passes)
/pr-polish 226 --skip-conflicts         # Skip conflict phase (no conflicts expected)
/pr-polish 226 --skip-pr-review         # Only run local-review loop
/pr-polish 226 --skip-local-review      # Only resolve conflicts + pr-review-dev
/pr-polish 226 --no-ci                  # Skip CI failure fetch (PR review only)
/pr-polish 226 --no-push                # Fix everything locally, don't push
```

## Arguments

Parse arguments from `$ARGUMENTS`:

| Argument | Default | Description |
|----------|---------|-------------|
| `pr_number` | auto | PR number or URL (auto-detect from branch if omitted) |
| `--required-clean-runs <n>` | 4 | Consecutive clean local-review passes required |
| `--max-iterations <n>` | 10 | Max local-review cycles |
| `--skip-conflicts` | false | Skip Phase 0 conflict resolution |
| `--skip-pr-review` | false | Skip Phase 1 PR review + CI fix |
| `--skip-local-review` | false | Skip Phase 2 local-review loop |
| `--no-ci` | false | Skip CI failures in Phase 1 (PR review only) |
| `--no-push` | false | Apply all fixes without pushing to remote |

## Dispatch Contracts (Execution-Critical)

**You are an orchestrator.** You manage phase sequencing and state. You do NOT fix issues, resolve conflicts, or review code yourself — all three phases are delegated.

**Rule: The coordinator must NEVER call Edit(), Write(), or analyze code directly.**

> **CRITICAL — subagent_type must be `"onex:polymorphic-agent"`** (with the `onex:` prefix).

### Phase 0: Conflict Resolution — dispatch to polymorphic agent

Only runs if `git status` shows unmerged paths. Dispatch once per conflict batch:

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="Resolve merge conflicts on {branch}",
  prompt="**AGENT REQUIREMENT**: You MUST be a polymorphic-agent.

    Resolve all merge conflicts on this branch. Base branch: {base_branch}.

    Steps:
    1. Run: git status (identify conflicted files)
    2. For each conflicted file: read the file, understand both sides, apply the correct resolution
    3. git add <resolved files>
    4. git commit -m 'fix(merge): resolve conflicts against {base_branch}'
    5. If --no-push is NOT set: git push

    Conflict markers look like:
    <<<<<<< HEAD
    (current branch changes)
    =======
    (incoming changes)
    >>>>>>> {base_branch}

    Resolution rules:
    - Prefer the more recent/complete implementation
    - When in doubt, keep BOTH sides merged correctly (don't blindly discard either)
    - Never leave conflict markers in the file
    - Run linting after resolution to catch any issues introduced

    Report: list of resolved files and brief description of resolution strategy for each."
)
```

### Phase 1: PR Review + CI Fix — invoke pr-review-dev skill

```
Skill(skill="onex:pr-review-dev", args="{pr_number} {--no-ci if set}")
```

This handles fetching PR review comments, CI failures, running parallel-solve for all Critical/Major/Minor issues, and offering to fix nitpicks.

### Phase 2: Local Review Loop — invoke local-review skill

```
Skill(skill="onex:local-review", args="--required-clean-runs {required_clean_runs} --max-iterations {max_iterations}")
```

Runs until `required_clean_runs` consecutive clean passes (only nits). After clean passes, if `--no-push` is NOT set: `git push`.

---

## Phase Sequencing

```
Phase 0: Conflict Resolution
    ↓ (skip if --skip-conflicts or no conflicts found)
Phase 1: PR Review + CI Fix (pr-review-dev)
    ↓ (skip if --skip-pr-review)
Phase 2: Local Review Loop (local-review --required-clean-runs N)
    ↓ (skip if --skip-local-review)
Push (if not --no-push)
    ↓
Final Report
```

Each phase is independent. A phase failure is reported but does not block subsequent phases unless it leaves the working tree in a conflicted state.

## Status Indicators

- `Phase 0: No conflicts — skipped` — clean merge state
- `Phase 0: Resolved N files` — conflicts resolved and committed
- `Phase 1: N issues fixed (M CI failures + K review comments)` — pr-review-dev complete
- `Phase 1: No issues found` — already clean
- `Phase 2: Clean — Confirmed (N/N clean runs)` — local-review passed
- `Phase 2: Max iterations reached` — hit limit with blocking issues remaining
- `DONE: PR #{pr_number} is merge-ready` — all phases green

## Detailed Orchestration

Full orchestration logic (argument parsing, conflict detection heuristics, phase state tracking,
error handling per phase, push behavior, final report format) is documented in `prompt.md`.
The dispatch contracts above are sufficient to execute all three phases.

## See Also

- `local-review` skill (Phase 2 — iterative local review loop)
- `pr-review-dev` skill (Phase 1 — PR review comments + CI failures)
- `pr-review` skill (keyword-based priority classification reference)
- `ticket-pipeline` skill (chains pr-polish as its review + merge phase)
