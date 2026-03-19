---
description: Evaluate a PR's mergeability and label it appropriately. Outputs one of three statuses — mergeable, needs-split, or blocked — called by ticket-pipeline between local_review and create_pr phases.
mode: full
version: 1.0.0
level: advanced
debug: false
category: workflow
tags:
  - pr
  - mergeability
  - gate
  - ci
  - labels
author: OmniClaude Team
args:
  - name: pr_number
    description: PR number to evaluate
    required: true
  - name: repo
    description: Target GitHub repo (e.g., OmniNode-ai/omnibase_core)
    required: true
  - name: ticket_id
    description: Linear ticket ID for fetching expected test evidence
    required: false
mode: full
---

# mergeability-gate

## Dispatch Requirement

When invoked, dispatch to a polymorphic-agent:

```
Agent(
  subagent_type="onex:polymorphic-agent",
  description="Mergeability gate PR #<N>",
  prompt="Run the mergeability-gate skill for PR #<N> in <repo>. <full context>"
)
```

**CRITICAL**: `subagent_type` MUST be `"onex:polymorphic-agent"` (with the `onex:` prefix).

## Description
Evaluate a PR's mergeability and label it appropriately. Outputs one of three statuses:
`mergeable`, `needs-split`, or `blocked`. Called by ticket-pipeline between local_review
and create_pr phases.

## Inputs
- PR number (or URL) — required if PR exists
- Ticket ID — for fetching expected test evidence
- Repo — target GitHub repo (e.g., `OmniNode-ai/omnibase_core`)

## Evaluation Criteria

### Blocked (hard stops — must fix before merge)
- Missing required PR template section(s)
- CI is failing (not pending — actually failing)
- Merge conflicts present
- Invariant violations (from TCB constraints, if available)

### Needs Split (advisory — agent should restructure)
- Net diff > 500 lines (excluding test files and generated files)
- Mixed concerns: more than 2 unrelated modules changed with no shared ancestor
- More than 3 migrations in a single PR

### Mergeable (proceed)
- All blocked checks pass
- All needs-split checks pass (or explicitly waived with reason)
- Tests ran and passed (evidence in PR description)
- PR is rebased on current main/target branch

## Output
Write result to `~/.claude/skill-results/{context_id}/mergeability-gate.json`:
```json
{
  "status": "mergeable | needs-split | blocked",
  "pr_number": 1234,
  "repo": "OmniNode-ai/omnibase_core",
  "blocked_reasons": [],
  "split_reasons": [],
  "waived_reasons": [],
  "evaluated_at": "2026-02-28T00:00:00Z"
}
```

Apply GitHub label immediately:
- `mergeable` → add label `mergeable`, remove `blocked` and `needs-split`
- `needs-split` → add label `needs-split`, remove `mergeable` and `blocked`
- `blocked` → add label `blocked`, remove `mergeable` and `needs-split`
