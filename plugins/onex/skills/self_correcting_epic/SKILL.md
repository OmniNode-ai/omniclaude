---
description: Wrap epic-team with per-agent validation gates to push fully_achieved from ~60% to 90%+
mode: full
version: 1.0.0
level: advanced
debug: false
category: workflow
tags: [epic, validation, self-correcting, gates]
args:
  - name: epic_id
    description: Linear epic ID (e.g., OMN-2000)
    required: true
  - name: --dry-run
    description: Print gate plan without executing
    required: false
  - name: --skip-gates
    description: Comma-separated gate names to skip (preflight,postaction,parentverify,audit,escalation)
    required: false
---

# Self-Correcting Epic Agent

## Dispatch Surface

**Target**: Agent Teams

## Overview

Wraps `epic_team` with 5 built-in validation gates per agent to increase the fully_achieved
rate from ~60% to 90%+. Each ticket dispatch is bracketed by pre-flight and post-action
checks. The coordinator audits scope before merge, verifies parent epic integrity after
each wave, and escalates via the Two-Strike Diagnosis Protocol on repeated failures.

**Announce at start:** "I'm using the self-correcting-epic skill to run epic {epic_id} with validation gates."

## Gate Types

| Gate | When | What | Blocks on Failure |
|------|------|------|-------------------|
| **preflight** | Before each ticket dispatch | Verify ticket maps to exactly one repo, changeset within declared scope | Yes -- skip ticket |
| **postaction** | After each ticket-pipeline completes | Run `pytest -x --timeout=120` and `pre-commit run --all-files` on worktree | Yes -- retry ticket |
| **parentverify** | After each wave completes | Query Linear to confirm all completed tickets are still children of parent epic | No -- log warning |
| **audit** | Before auto-merge | Compare `gh pr diff --stat` file list against ticket's declared scope | Yes -- block merge |
| **escalation** | After 2 failed retries of any ticket | Write `docs/diagnosis-{ticket-id}.md` per Two-Strike Diagnosis Protocol | N/A -- skip ticket |

## Orchestration Flow

```
self-correcting-epic OMN-XXXX
  -> Fetch child tickets from Linear
  -> For each ticket in wave:
      -> [GATE 1] Pre-flight scope check (Skill: scope_check)
      -> Dispatch ticket-pipeline
      -> [GATE 2] Post-action validation (pytest + pre-commit)
      -> Record pass/fail to state.yaml
  -> [GATE 3] Parent epic verification (Linear query)
  -> For each PR ready to merge:
      -> [GATE 4] Coordinator audit (diff vs ticket scope)
      -> auto-merge
  -> [GATE 5] On 2nd failure: write diagnosis doc, skip ticket
  -> Write final report to ~/.claude/skill-results/{context_id}/self-correcting-epic.json
```

## Gate Scripts

| Script | Purpose |
|--------|---------|
| `epic_preflight_gate.sh` | Pre-flight scope check (env: TICKET_ID, TICKET_REPO, EPIC_ID) |
| `epic_postaction_gate.sh` | Post-action pytest + pre-commit (env: WORKTREE_PATH, TICKET_ID) |

## Skill Result Output

**Output contract:** `ModelSkillResult` from `omnibase_core.models.skill`

Write to: `~/.claude/skill-results/{context_id}/self-correcting-epic.json`

| Field | Value |
|-------|-------|
| `skill_name` | `"self-correcting-epic"` |
| `status` | `"success"` / `"partial"` / `"error"` |
| `extra_status` | `"all_passed"` / `"some_escalated"` / `"failed"` |
| `extra` | `{"tickets_total": int, "tickets_passed": int, "tickets_escalated": int, "gates_triggered": int}` |

## See Also

- `prompt.md` -- authoritative behavioral specification
- `epic_team` skill -- base orchestration (wrapped by this skill)
- `scope_check` skill -- pre-flight scope validation (PR #883)
- `epic_preflight_gate.sh` -- pre-flight gate script
- `epic_postaction_gate.sh` -- post-action gate script
