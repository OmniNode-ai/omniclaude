---
description: Autonomous per-ticket pipeline that chains ticket-work, local-review, PR creation, test-iterate loop, CI watching, PR review loop, integration verification gate, and auto-merge into a single unattended workflow with Slack notifications and policy guardrails
mode: full
version: 6.0.0
level: intermediate
debug: false
category: workflow
tags:
  - pipeline
  - automation
  - linear
  - tickets
  - review
  - pr
  - slack
  - ci
  - merge
  - cross-repo
author: OmniClaude Team
args:
  - name: ticket_id
    description: Linear ticket ID (e.g., OMN-1804)
    required: true
  - name: --skip-to
    description: Resume from specified phase (pre_flight|implement|local_review|create_pr|test_iterate|ci_watch|pr_review|auto_merge)
    required: false
  - name: --dry-run
    description: Execute phase logic and log decisions without side effects
    required: false
  - name: --skip-test-iterate
    description: Skip the test-iterate phase entirely
    required: false
  - name: --auto-merge
    description: Force auto_merge=true
    required: false
  - name: --require-gate
    description: Require explicit HIGH_RISK gate before merging
    required: false
  - name: --docs-only
    description: Assert all changes are documentation-only; skips integration verification
    required: false
---

# Ticket Pipeline

**Announce at start:** "I'm using the ticket-pipeline skill."

## Usage

```
/ticket-pipeline OMN-1234
/ticket-pipeline OMN-1234 --dry-run
/ticket-pipeline OMN-1234 --skip-to ci_watch
/ticket-pipeline OMN-1234 --skip-test-iterate
/ticket-pipeline OMN-1234 --require-gate
/ticket-pipeline OMN-1234 --docs-only
```

## Execution

### Step 1 — Parse arguments

- `ticket_id` → Linear ticket ID (required)
- `--skip-to` → resume from phase (auto-detected from state file if omitted)
- `--dry-run` → no commits, pushes, or PRs
- `--skip-test-iterate` → skip test-fix loop (for infra-dependent tests)
- `--auto-merge` / `--require-gate` → merge policy override

### Step 2 — Initialize FSM

```bash
cd /Volumes/PRO-G40/Code/omni_home/omnimarket  # local-path-ok
uv run python -m omnimarket.nodes.node_ticket_pipeline \
  <ticket_id> \
  [--skip-to <phase>] \
  [--skip-test-iterate] \
  [--dry-run]
```

Outputs `ModelPipelineState` JSON with initial phase. Use this to confirm FSM wiring.

### Step 3 — Execute phases

Run each phase in sequence, advancing the FSM via `handler.advance()`. For each phase:

1. **PRE_FLIGHT**: Load ticket contract from Linear, validate repo target, check environment
2. **IMPLEMENT**: Execute ticket work (delegates to ticket-work skill)
3. **LOCAL_REVIEW**: Run local-review loop until N consecutive clean passes
4. **CREATE_PR**: Create PR via `gh pr create`, enable auto-merge
5. **TEST_ITERATE**: Fix failing tests up to `--max-test-iterations` cycles
6. **CI_WATCH**: Poll CI until green or timeout; auto-fix failures
7. **PR_REVIEW**: Address CodeRabbit + human review comments
8. **AUTO_MERGE**: Wait for merge queue; verify merged

Circuit breaker halts after 3 consecutive phase failures → FAILED state.

### Step 4 — Report

Display final pipeline state: phase reached, PR URL, any errors, cycle counts.

## Phases

| Phase | FSM State | Description |
|-------|-----------|-------------|
| PRE_FLIGHT | → IMPLEMENT | Load contract, validate env |
| IMPLEMENT | → LOCAL_REVIEW | Execute ticket work |
| LOCAL_REVIEW | → CREATE_PR | Clean review passes |
| CREATE_PR | → TEST_ITERATE | Open PR |
| TEST_ITERATE | → CI_WATCH | Fix test failures |
| CI_WATCH | → PR_REVIEW | Wait for green CI |
| PR_REVIEW | → AUTO_MERGE | Address comments |
| AUTO_MERGE | → DONE | Merge queue |

## Architecture

```
SKILL.md   -> thin shell (this file)
node       -> omnimarket/src/omnimarket/nodes/node_ticket_pipeline/ (FSM logic)
contract   -> node_ticket_pipeline/contract.yaml
```
