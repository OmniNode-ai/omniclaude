---
description: Contract-driven ticket execution with Linear integration - orchestrates intake, research, questions, spec, implementation, review, and done phases with explicit human gates
mode: full
version: 3.0.0
level: basic
debug: false
category: workflow
tags:
  - linear
  - tickets
  - automation
  - workflow
  - contract-driven
author: OmniClaude Team
runtime: mcp
composable: true
inputs:
  - name: ticket_id
    type: str
    description: Linear ticket ID (e.g., OMN-1807)
    required: true
  - name: autonomous
    type: bool
    description: Skip human gates; proceed through all phases unattended
    required: false
outputs:
  - name: skill_result
    type: ModelSkillResult
    description: "Written to $ONEX_STATE_DIR/skill-results/{context_id}/ticket-work.json"
    fields:
      - status: '"success" | "blocked" | "pending" | "error"'
      - extra_status: '"done" | "questions_pending" | null'
      - ticket_id: str
      - extra: "{pr_url, phase_reached, commits}"
args:
  - name: ticket_id
    description: Linear ticket ID (e.g., OMN-1807)
    required: true
  - name: --autonomous
    description: Skip human gates; proceed through all phases unattended
    required: false
  - name: --skip-to
    description: Resume from specified phase
    required: false
---

# Contract-Driven Ticket Execution

**Announce at start:** "I'm using the ticket-work skill."

## Usage

```
/ticket-work OMN-1807
/ticket-work OMN-1807 --autonomous
/ticket-work OMN-1807 --skip-to implement
```

## Execution

### Step 1 — Parse arguments

- `ticket_id` → Linear ticket ID (required)
- `--autonomous` → skip human gates (for pipeline/overnight use)
- `--skip-to` → resume from named phase

### Step 2 — Initialize node (contract verification)

```bash
onex run-node node_ticket_work \
  --input '{"ticket_id": "<ticket_id>", "autonomous": false, "skip_to": null}' \
  --timeout 300
```

On non-zero exit, a `SkillRoutingError` JSON envelope is returned — surface it directly, do not produce prose. Note: handler is a structural placeholder; full migration tracked in OMN-8004.

### Step 3 — Execute ticket phases via tracker DI

This skill uses `ProtocolProjectTracker` DI (resolved via `resolve_project_tracker()`) for all
Linear operations. The tracker adapter handles routing automatically.

1. **INTAKE**: Fetch ticket via `tracker.get_issue()`; parse contract YAML block
2. **RESEARCH**: Read relevant code, check existing implementations
3. **QUESTIONS**: Surface blockers → human gate (skipped in `--autonomous` mode)
4. **SPEC**: Write implementation spec to ticket description
5. **IMPLEMENT**: Write code in git worktree; run tests; pre-commit clean
6. **REVIEW**: Run local-review skill; address findings
7. **DONE**: Create PR; update Linear ticket status to In Review

### Step 4 — Report

Write `ModelSkillResult` to `$ONEX_STATE_DIR/skill-results/{context_id}/ticket-work.json`.
Display: phase reached, PR URL, any blocking questions.

## Architecture

```
SKILL.md   -> thin shell (this file)
node       -> omnimarket/src/omnimarket/nodes/node_ticket_work/ (structural placeholder)
contract   -> node_ticket_work/contract.yaml
migration  -> OMN-8004 (full handler implementation)
```
