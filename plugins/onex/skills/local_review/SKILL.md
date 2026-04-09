---
description: Local code review loop that iterates through review, fix, commit cycles without pushing
mode: full
version: 3.0.0
level: basic
debug: false
category: workflow
tags:
  - review
  - code-quality
  - local
  - iteration
author: OmniClaude Team
composable: true
inputs:
  - name: since
    type: str
    description: Base ref for diff (branch/commit); auto-detected if omitted
    required: false
  - name: max_iterations
    type: int
    description: Maximum review-fix cycles (default 10)
    required: false
  - name: required_clean_runs
    type: int
    description: Consecutive clean runs required before passing (default 2)
    required: false
outputs:
  - name: skill_result
    type: ModelSkillResult
    description: "Written to $ONEX_STATE_DIR/skill-results/{context_id}/local-review.json"
    fields:
      - status: '"success" | "partial" | "error"'
      - extra_status: '"clean" | "clean_with_nits" | "max_iterations_reached" | null'
      - extra: "{iterations_run, issues_remaining}"
args:
  - name: --uncommitted
    description: Only review uncommitted changes (ignore committed)
    required: false
  - name: --since
    description: Base ref for diff (branch/commit)
    required: false
  - name: --max-iterations
    description: Maximum review-fix cycles (default 10)
    required: false
  - name: --required-clean-runs
    description: Consecutive clean runs required (default 2)
    required: false
  - name: --no-fix
    description: Report only, don't attempt fixes
    required: false
  - name: --no-commit
    description: Fix but don't commit (stage only)
    required: false
  - name: --dry-run
    description: Log review decisions without making changes
    required: false
---

# Local Review

**Announce at start:** "I'm using the local-review skill."

## Usage

```
/local-review
/local-review --uncommitted
/local-review --since HEAD~3
/local-review --max-iterations 5 --required-clean-runs 2
/local-review --no-fix
/local-review --dry-run
```

## Execution

### Step 1 — Parse arguments

- `--uncommitted` → review only unstaged/staged changes
- `--since` → base ref for diff (default: auto-detected from branch)
- `--max-iterations` → cap on review-fix cycles (default: 10)
- `--required-clean-runs` → consecutive clean passes needed (default: 2)
- `--no-fix` → report issues only, no code changes
- `--no-commit` → fix but don't commit (leave staged)

### Step 2 — Initialize FSM

```bash
cd /Volumes/PRO-G40/Code/omni_home/omnimarket  # local-path-ok
uv run python -m omnimarket.nodes.node_local_review \
  [--max-iterations <n>] \
  [--required-clean-runs <n>] \
  [--dry-run]
```

Outputs `ModelLocalReviewState` JSON with initial phase.

### Step 3 — Execute review loop

Repeat until N consecutive clean passes or max iterations reached:

1. **REVIEW**: Inspect changed files (ruff, mypy, tests, CLAUDE.md conventions, aislop patterns)
2. **FIX**: Apply fixes for each finding (unless `--no-fix`)
3. **COMMIT**: Stage and commit fixes with `fix(review): <description>` (unless `--no-commit`)
4. **CHECK_CLEAN**: Re-run review on committed changes; count consecutive clean passes

→ DONE when `consecutive_clean >= required_clean_runs`
→ FAILED if circuit breaker (3 consecutive phase failures) trips

### Step 4 — Report

Write `ModelSkillResult` to `$ONEX_STATE_DIR/skill-results/{context_id}/local-review.json`.
Display: iterations run, issues found/fixed, final clean status, any remaining nits.

## Architecture

```
SKILL.md   -> thin shell (this file)
node       -> omnimarket/src/omnimarket/nodes/node_local_review/ (FSM logic)
contract   -> node_local_review/contract.yaml
```
