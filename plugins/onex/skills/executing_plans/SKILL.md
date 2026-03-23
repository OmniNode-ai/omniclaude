---
description: Use when partner provides a complete implementation plan to execute — reviews the plan critically, verifies live PR state against plan assumptions, creates Linear tickets via plan-to-tickets, then routes to epic-team (≥3 tickets) or ticket-pipeline (1-2 tickets)
mode: both
version: 2.0.0
level: intermediate
debug: false
category: workflow
tags:
  - planning
  - execution
  - linear
  - routing
author: OmniClaude Team
---

# Executing Plans

## Dispatch Requirement

When invoked, dispatch to a polymorphic-agent:

```
Agent(
  subagent_type="onex:polymorphic-agent",
  description="Execute plan <plan-name>",
  prompt="Run the executing-plans skill. <full context>"
)
```

**CRITICAL**: `subagent_type` MUST be `"onex:polymorphic-agent"` (with the `onex:` prefix).

## Overview

Load a plan file, review it critically, create Linear tickets from it, then route to the
appropriate execution skill based on ticket count.

**Core principle:** Linear-native routing. Plans become tickets; tickets drive execution.

**Announce at start:** "I'm using the executing-plans skill to implement this plan."

---

## The 5-Step Flow

### Step 1: Review Plan <!-- ai-slop-ok: pre-existing step structure -->

Load the plan file and review it critically before taking any action.

**Plan file**: If a plan path was passed as a positional argument (e.g., from design-to-plan Phase 3),
use it directly. Do not re-discover or re-summarize the plan.

1. Read the plan file in full
2. Identify any concerns:
   - Missing acceptance criteria or definition of done
   - Ambiguous or contradictory requirements
   - Unclear dependencies between phases
   - Missing repo label (required for architecture validation)
   - Steps that reference external systems or secrets not yet available
3. If concerns exist: raise them with your human partner and wait for resolution before proceeding
4. If no concerns: proceed to Step 1.5

**Do not proceed to ticket creation if the plan has unresolved questions.**

---

### Step 1.5: Verify Live PR State <!-- ai-slop-ok: new verification step -->

If the plan references existing PRs or branches, verify their live state before proceeding.
Plans often assume a PR is open and mergeable, but reality may have changed since the plan
was written.

**Run for each PR referenced in the plan:**

```bash
gh pr view <PR-number> --json state,mergeable,mergeStateStatus,statusCheckRollup,headRefName
```

**Classification and action:**

| CI/Mergeability State | Classification | Action |
|---|---|---|
| `PENDING` / checks still running | PENDING | Poll up to 3 times (30s interval). If still pending after 90s, report status and proceed -- do not block indefinitely. |
| `BEHIND` (mergeable but needs rebase) | ACTIONABLE | Note in plan review; proceed. Rebase will happen during execution. |
| `CLEAN` / `UNSTABLE` (mergeable, checks pass/flaky) | READY | Proceed normally. |
| `CONFLICTING` (merge conflicts) | STOP | Stop and report: "PR #N has merge conflicts. Plan assumes it is mergeable. Please resolve conflicts or update the plan." |
| Checks `FAILURE` (required checks failing) | STOP | Stop and report: "PR #N has failing required checks. Plan assumes CI is green. Please fix CI or update the plan." |
| `MERGED` | STOP | Stop and report: "PR #N is already merged. Plan assumes it is open. Please update the plan to reflect current state." |
| `CLOSED` (not merged) | STOP | Stop and report: "PR #N is closed without merge. Plan assumes it is open. Please update the plan." |

**Rules:**
- Only poll for PENDING state; all other states are immediately actionable or blocking.
- Never wait more than 90 seconds total for pending checks.
- If the plan does not reference any PRs or branches, skip this step entirely.
- After verification, proceed to Step 2.

---

### Step 2: Dry-Run Preview <!-- ai-slop-ok: pre-existing step structure -->

Call `onex:plan-to-tickets` with `--dry-run` to preview what tickets would be created.

```bash
/plan-to-tickets <plan-file> --dry-run [--repo <repo-label>] [--project <project>]
```

Review the dry-run output:
- Confirm the detected structure — expect `task_sections` for plans produced by design-to-plan (`## Task N:` headers); other valid types: `phase_sections` (legacy `## Phase N:`), `numbered_h2`, `step_sections`, `milestone_table`, `priority_labels`. If dry-run reports `task_sections`, that is correct — do NOT ask the user to reformat.
- Confirm the epic title that would be used
- Confirm the list of tickets that would be created
- Check that dependencies are correctly detected

If the preview looks wrong, stop and discuss with your partner before creating tickets.

---

### Step 3: Create Tickets <!-- ai-slop-ok: pre-existing step structure -->

Call `onex:plan-to-tickets` (without `--dry-run`) to create the Linear tickets under the epic.

```bash
/plan-to-tickets <plan-file> [--repo <repo-label>] [--project <project>] [--skip-existing]
```

After creation, record:
- The epic identifier (e.g., OMN-XXXX)
- The list of created ticket identifiers
- The total ticket count

**Common flags:**
- `--repo <label>` — enables architecture dependency validation (recommended)
- `--project <name>` — assigns tickets to a Linear project
- `--skip-existing` — skip tickets that already exist instead of prompting
- `--no-create-epic` — fail if the epic does not already exist

---

### Step 4: Route to Execution <!-- ai-slop-ok: pre-existing step structure -->

Compute routing from the plan file content, not just ticket count:

| Condition | Route | Why |
|-----------|-------|-----|
| Multiple repos touched | `onex:epic-team` | Cross-repo needs orchestration |
| Migrations or deploy steps present | `onex:epic-team` | Infrastructure changes need coordination |
| 3+ distinct subsystems affected | `onex:epic-team` | Broad blast radius |
| 3+ tickets (fallback) | `onex:epic-team` | Parallel execution needed |
| 1-2 tickets, single repo, no migrations | `onex:ticket-pipeline` | Lightweight |

Log the routing decision: "Routing to {skill} because: {reason}"

#### epic-team route

```bash
/epic-team <epic-id>
```

`epic-team` orchestrates a team of parallel worker agents, one per repo. It handles
ticket assignment, worktree creation, and lifecycle notifications automatically.

#### ticket-pipeline route

```bash
/ticket-pipeline <ticket-id>
```

Run `onex:ticket-pipeline` for each ticket sequentially. Each pipeline handles the full
implement → review → PR → CI → merge workflow autonomously.

---

## Verification Commands

After routing, verify progress:

```bash
# Check epic status in Linear
# (use Linear MCP or Linear UI to view the epic and child tickets)

# If routed to epic-team — resume after session disconnect:
/epic-team <epic-id> --resume

# If routed to ticket-pipeline — check pipeline state:
cat $ONEX_STATE_DIR/pipelines/<ticket-id>/state.yaml
```

---

## Execution Rules

Execute end-to-end without stopping between tasks. If blocked on one task, record a skip note
and continue to the next. Only pause for: (a) credentials not available in the session,
(b) a destructive action not explicitly covered by the plan, or (c) an explicit user gate in
the plan. Do not exit plan mode or stop to "await direction" in any other circumstance.

---

## When to Stop and Ask for Help

**STOP executing immediately when:**
- Plan has critical gaps or missing context (before Step 1.5)
- A referenced PR is CONFLICTING, FAILING, MERGED, or CLOSED (Step 1.5)
- Dry-run output reveals structural problems (before Step 3)
- `plan-to-tickets` fails with an architecture violation (before routing)
- A ticket-pipeline run fails and cannot self-recover

**Ask for clarification rather than guessing.**

---

## Post-Completion

When all tickets/tasks close:

1. **Discover open PRs**: `gh pr list --head <branch> --json number,title,state`
2. **If PRs have review comments**: offer `pr-polish`
3. **Offer**: "All work complete. Run onex:finishing-a-development-branch? [Y/n]"
4. If Y: invoke finishing-a-development-branch

This is an offer only — user must approve before dispatch.

---

## Remember

- Review plan critically before creating any tickets
- Verify live PR state before dry-run if the plan references existing PRs
- Always dry-run first to preview ticket structure
- Routing threshold is 3 tickets: `epic-team` for ≥3, `ticket-pipeline` for 1–2
- Stop and ask if any step surfaces unexpected errors
