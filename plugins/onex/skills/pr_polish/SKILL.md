---
description: Full PR readiness loop — resolve merge conflicts, address all review comments and CI failures, then iterate local-review until N consecutive clean passes
mode: full
version: 2.0.0
level: intermediate
debug: false
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
    description: "Consecutive clean local-review passes required before done (default: 4)"
    required: false
  - name: --max-iterations
    description: "Maximum local-review cycles (default: 10)"
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
    description: Skip CI failure fetch in PR review phase (review comments only)
    required: false
  - name: --no-push
    description: Apply all fixes locally without pushing to remote
    required: false
  - name: --dry-run
    description: Log phase decisions without making changes
    required: false
  - name: --no-automerge
    description: Skip enabling GitHub automerge after all phases complete
    required: false
---

# PR Polish

**Announce at start:** "I'm using the pr-polish skill."

## Usage

```
/pr-polish                              # Auto-detect PR from current branch
/pr-polish 42                           # Specific PR number
/pr-polish --skip-conflicts             # Skip conflict resolution
/pr-polish --required-clean-runs 2      # Fewer clean runs (headless/pipeline)
/pr-polish --dry-run
/pr-polish --no-automerge
```

## Execution

### Step 1 — Parse arguments

- `pr_number` → PR number (auto-detected from current branch if omitted)
- `--skip-conflicts` / `--skip-pr-review` / `--skip-local-review` → phase toggles
- `--required-clean-runs` → consecutive clean passes needed (default: 4, pipeline: 2)
- `--dry-run` → log decisions without making changes
- `--no-automerge` → skip enabling GitHub auto-merge at end

### Step 2 — Initialize FSM

```bash
cd /Volumes/PRO-G40/Code/omni_home/omnimarket  # local-path-ok
uv run python -m omnimarket.nodes.node_pr_polish \
  [--pr-number <n>] \
  [--skip-conflicts] \
  [--dry-run]
```

Outputs `ModelPrPolishState` JSON with initial phase.

### Step 3 — Execute phases

| Phase | What It Does |
|-------|-------------|
| RESOLVE_CONFLICTS | Rebase onto target branch; fix conflicts |
| FIX_CI | Read CI failures; fix code; push fix commits |
| ADDRESS_COMMENTS | Read CodeRabbit + human review threads; address each |
| LOCAL_REVIEW | Run local-review loop until N consecutive clean passes |
| DONE | Enable GitHub auto-merge (unless `--no-automerge`) |

Circuit breaker: 3 consecutive phase failures → FAILED.

### Step 4 — Report

Display final state: phase reached, conflicts resolved, CI fixes, comments addressed,
review iterations run. If FAILED, emit friction event.

## Headless Mode

Safe for overnight pipeline use via `claude -p`. No interactive gates. Minimum tool set:

```bash
ALLOWED_TOOLS="Bash,Read,Write,Edit,Glob,Grep,Task,TaskCreate,TaskUpdate,TaskGet,TaskList,SendMessage"
claude -p --allowedTools "${ALLOWED_TOOLS}" "Run pr-polish for PR #42 --required-clean-runs 2"
```

## Architecture

```
SKILL.md   -> thin shell (this file)
node       -> omnimarket/src/omnimarket/nodes/node_pr_polish/ (FSM logic)
contract   -> node_pr_polish/contract.yaml
```
