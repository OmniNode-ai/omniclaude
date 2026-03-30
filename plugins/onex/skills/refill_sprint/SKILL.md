---
description: Auto-pull tech debt tickets from Future into Active Sprint when the sprint queue is empty or below capacity threshold
mode: full
version: 1.0.0
level: advanced
debug: false
category: workflow
tags:
  - autopilot
  - tech-debt
  - sprint-management
  - auto-pull
author: OmniClaude Team
composable: true
inputs:
  - name: dry-run
    type: bool
    description: Show what would be pulled without moving tickets
    required: false
  - name: threshold
    type: float
    description: Weighted capacity threshold below which to trigger pull (default 5.0)
    required: false
  - name: batch-size
    type: int
    description: Maximum tickets to pull per invocation (default 10)
    required: false
  - name: skip-scope-check
    type: bool
    description: Skip scope verification (faster but less safe)
    required: false
outputs:
  - name: pulled_count
    type: int
    description: Number of tickets moved to Active Sprint
  - name: skipped_count
    type: int
    description: Number of tickets skipped (stale, cross-repo, too large)
  - name: exhausted
    type: bool
    description: True if no eligible tech debt remains in Future
---

# refill-sprint Skill

> **OMN-6870** -- Auto-pull tech debt tickets from Future when Active Sprint empties.

## Overview

`/refill-sprint` detects when Active Sprint is below capacity and automatically pulls
the highest-value tech debt tickets from Future. Designed to run as the final step in
autopilot close-out, or standalone.

## Phases

### Phase 1: Capacity Check (~10s)

1. Query Linear for Active Sprint tickets in Backlog/Todo state with no active PR
2. Compute weighted capacity: sum of estimate values (no estimate = 1.0 Medium)
3. If weighted capacity >= threshold (default 5.0), exit early with "sprint has capacity"

### Phase 2: Candidate Selection (~20s)

Query Future project for tech debt candidates using priority tiers:

1. **Tier 1**: Tickets with labels `type-suppression`, `lint-suppression`, `any-type-narrowing`, `skipped-tests`
2. **Tier 2**: Tickets with `friction` label
3. **Tier 3**: Tickets matching tech-debt keywords in title/description (`tech debt`, `tech-debt`, `cleanup`, `refactor`, `dead code`, `deprecated`)
4. **Hard gates** (exclude):
   - Estimate > Medium (Large/XL tickets excluded)
   - Priority = Urgent (never auto-pull strategic work)
   - Has linked children/blockers in different repos (cross-repo exclusion)
   - Has 2+ failed implementation attempts (zombie exclusion)

### Phase 3: Scope Verification (~30s per ticket, parallelizable)

For each candidate (unless `--skip-scope-check`):

1. Read ticket description
2. Check referenced files/APIs still exist in current codebase
3. If ticket has DoD checklist, verify each item is still applicable
4. If >50% of DoD items are stale, flag for human review instead of pulling
5. Suggest labels for unlabeled tickets encountered
6. Update ticket description with verified scope

### Phase 4: Pull and Label (~5s per ticket)

For each verified candidate (up to batch-size):

1. Move ticket to Active Sprint project
2. Add `auto-pulled` label
3. Set priority below any human-created tickets in sprint
4. Add comment: "Auto-pulled by refill-sprint. Time-box: 30 min / 20 tool calls."

### Phase 5: Notification and Events (~5s)

1. Emit `sprint.auto-pull.completed` Kafka event with pull summary
2. If tickets pulled > 0 AND last notification was > 1 hour ago: send Discord notification
3. If no eligible tickets found: emit `tech-debt-queue-empty` event, send ONE Discord notification, go idle

## Time-Boxing (CRITICAL)

Each auto-pulled ticket gets enforced limits when later worked:
- **30 minutes wall clock** OR **20 LLM tool calls**, whichever first
- If exceeded: park ticket with comment "scope-expansion: exceeded time-box", move back to Future
- This prevents single tickets from consuming entire cycles

## Failure Recovery (CRITICAL)

- Track `failed_attempt_count` per ticket via Linear comments with tag `[auto-pull-attempt]`
- After 2 failed attempts: auto-return to Future with comment explaining why
- Exclude tickets with 2+ `[auto-pull-attempt]` comments from future pulls
- Prevents zombie ticket accumulation

## Priority Yielding

- Auto-pulled tickets always sort BELOW human-created tickets
- At cycle start, check for human-added tickets; if any exist, auto-pulled tickets that haven't started yield (deprioritize)
- The `auto-pulled` label makes these tickets visually distinct

## Exhaustion Behavior

When no eligible tech debt remains in Future:
- Emit `tech-debt-queue-empty` event
- Send ONE Discord notification (not repeated)
- Do NOT pull from Ready project (those need human judgment)
- Never create busy-work

## Integration Points

- **Autopilot close-out**: Add as final step after close-day
- **Autopilot build mode**: Check at start of build mode
- **Standalone**: `/refill-sprint` or `/refill-sprint --dry-run`

## Guardrails

- Never pull from Ready project
- Never pull Urgent/strategic tickets
- Never exceed batch-size per invocation
- Never auto-pull tickets the same day they were returned to Future
- Discord notifications rate-limited to 1/hour with aggregation
