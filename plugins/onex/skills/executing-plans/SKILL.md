---
name: executing-plans
description: Use when partner provides a complete implementation plan to execute — reviews the plan critically, creates Linear tickets via plan-to-tickets, then routes to epic-team (≥3 tickets) or ticket-pipeline (1-2 tickets)
version: 2.0.0
category: workflow
tags:
  - planning
  - execution
  - linear
  - routing
author: OmniClaude Team
---

# Executing Plans

## Overview

Load a plan file, review it critically, create Linear tickets from it, then route to the
appropriate execution skill based on ticket count.

**Core principle:** Linear-native routing. Plans become tickets; tickets drive execution.

**Announce at start:** "I'm using the executing-plans skill to implement this plan."

---

## The 4-Step Flow

### Step 1: Review Plan

Load the plan file and review it critically before taking any action.

1. Read the plan file in full
2. Identify any concerns:
   - Missing acceptance criteria or definition of done
   - Ambiguous or contradictory requirements
   - Unclear dependencies between phases
   - Missing repo label (required for architecture validation)
   - Steps that reference external systems or secrets not yet available
3. If concerns exist: raise them with your human partner and wait for resolution before proceeding
4. If no concerns: proceed to Step 2

**Do not proceed to ticket creation if the plan has unresolved questions.**

---

### Step 2: Dry-Run Preview

Call `/plan-to-tickets` with `--dry-run` to preview what tickets would be created.

```bash
/plan-to-tickets <plan-file> --dry-run [--repo <repo-label>] [--project <project>]
```

Review the dry-run output:
- Confirm the detected structure (phase_sections, milestone_table, or priority_labels)
- Confirm the epic title that would be used
- Confirm the list of tickets that would be created
- Check that dependencies are correctly detected

If the preview looks wrong, stop and discuss with your partner before creating tickets.

---

### Step 3: Create Tickets

Call `/plan-to-tickets` (without `--dry-run`) to create the Linear tickets under the epic.

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

### Step 4: Route to Execution

Route based on ticket count:

#### 3 or more tickets → `/epic-team`

```bash
/epic-team <epic-id>
```

`epic-team` orchestrates a team of parallel worker agents, one per repo. It handles
ticket assignment, worktree creation, and lifecycle notifications automatically.

#### 1 or 2 tickets → `/ticket-pipeline` (per ticket)

```bash
/ticket-pipeline <ticket-id>
```

Run `/ticket-pipeline` for each ticket sequentially. Each pipeline handles the full
implement → review → PR → CI → merge workflow autonomously.

---

## Routing Decision

| Ticket Count | Skill | Why |
|---|---|---|
| ≥ 3 | `/epic-team <epic-id>` | Parallel execution across repos; team lead + worker topology |
| 1–2 | `/ticket-pipeline <ticket-id>` (per ticket) | Lightweight; no team overhead needed |

---

## Verification Commands

After routing, verify progress:

```bash
# Check epic status in Linear
# (use Linear MCP or Linear UI to view the epic and child tickets)

# If routed to epic-team — resume after session disconnect:
/epic-team <epic-id> --resume

# If routed to ticket-pipeline — check pipeline state:
cat ~/.claude/pipelines/<ticket-id>/state.yaml
```

---

## When to Stop and Ask for Help

**STOP executing immediately when:**
- Plan has critical gaps or missing context (before Step 2)
- Dry-run output reveals structural problems (before Step 3)
- `plan-to-tickets` fails with an architecture violation (before routing)
- A ticket-pipeline run fails and cannot self-recover

**Ask for clarification rather than guessing.**

---

## Remember

- Review plan critically before creating any tickets
- Always dry-run first to preview ticket structure
- Routing threshold is 3 tickets: `epic-team` for ≥3, `ticket-pipeline` for 1–2
- Stop and ask if any step surfaces unexpected errors
