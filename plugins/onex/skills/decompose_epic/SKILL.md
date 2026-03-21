---
description: Analyze a Linear epic description and create sub-tickets as Linear children
mode: full
version: 1.0.0
level: advanced
debug: false
category: workflow
tags: [epic, linear, decomposition, planning]
author: OmniClaude Team
composable: true
inputs:
  - name: epic_id
    type: str
    description: Linear epic ID (e.g., OMN-2000)
    required: true
  - name: dry_run
    type: bool
    description: Print decomposition plan without creating tickets
    required: false
outputs:
  - name: skill_result
    type: ModelSkillResult
    description: "Written to $ONEX_STATE_DIR/skill-results/{context_id}/decompose_epic.json"
    fields:
      - status: "success" | "dry_run" | "error"  # EnumSkillResultStatus canonical values
      - extra_status: "created" | null  # domain-specific granularity
      - extra: "{epic_id, created_tickets, count}"
args:
  - name: epic_id
    description: Linear epic ID (e.g., OMN-2000)
    required: true
  - name: --dry-run
    description: Print decomposition plan without creating tickets
    required: false
mode: full
---

# Decompose Epic

## Dispatch Requirement

When invoked, dispatch to a polymorphic-agent:

```
Agent(
  subagent_type="onex:polymorphic-agent",
  description="Decompose epic <epic_id>",
  prompt="Run the decompose-epic skill for <epic_id>. <full context>"
)
```

**CRITICAL**: `subagent_type` MUST be `"onex:polymorphic-agent"` (with the `onex:` prefix).

## Overview

Analyze a Linear epic's description, goals, and context to generate a set of actionable
sub-tickets. Creates each sub-ticket as a Linear child of the epic, assigns repo hints
from the repo manifest, and returns `ModelSkillResult` with created ticket details.

**Announce at start:** "I'm using the decompose-epic skill to create sub-tickets for {epic_id}."

**Implements**: OMN-2522

- **Mode A** (no `--repos`): reads epic description, infers repo breakdown from `repo_manifest.yaml`, creates sub-tickets with one per identified work area matched to its owning repo
- **Mode B** (`--repos omniclaude,omnibase_core,...`): repos are pre-determined; creates one focused sub-ticket per repo, scoped to that repo's concerns

## Usage Examples

```
/decompose-epic OMN-2000
/decompose-epic OMN-2000 --dry-run
```

## Decomposition Flow

1. Fetch epic from Linear: `mcp__linear-server__get_issue({epic_id}, includeRelations=true)`
2. Read `plugins/onex/skills/epic-team/repo_manifest.yaml` for keyword-to-repo mapping
3. Analyze epic description + goals:
   - Identify distinct workstreams (one ticket per independent deliverable)
   - Keep tickets atomic: each ticket = one thing, one repo, one PR
   - Assign repo hint based on keywords in the work description
   - Generate title, description, requirements, and DoD for each ticket
4. If `--dry-run`: print plan, exit with `status: dry_run`
5. Create each ticket via `mcp__linear-server__create_issue`:
   - `parentId`: epic's Linear ID
   - `team`: same team as epic
   - `labels`: ["omniclaude"] (or appropriate repo label)
6. Write result and exit

## Ticket Creation Contract

```python
mcp__linear-server__create_issue(
    title="{ticket_title}",
    team="{epic_team}",
    parentId="{epic_linear_id}",
    description="""
## Summary
{what_this_ticket_implements}

## Requirements
{functional_requirements}

## Definition of Done
- [ ] Implementation complete
- [ ] Tests passing
- [ ] PR merged

## Repo Hint
{repo_name}: {rationale}
    """,
    labels=["{repo_label}"]
)
```

## Repo Manifest

Loaded from `plugins/onex/skills/epic-team/repo_manifest.yaml`:

```yaml
repos:
  - name: omniclaude
    path: ~/Code/omniclaude
    keywords: [hooks, skills, agents, claude, plugin]
  - name: omnibase_core
    path: ~/Code/omnibase_core
    keywords: [nodes, contracts, runtime, onex]
```

## Skill Result Output

**Output contract:** `ModelSkillResult` from `omnibase_core.models.skill`

> **Note: This contract reference is behavioral guidance for the LLM executing this skill. Runtime validation not yet implemented.**

Write to: `$ONEX_STATE_DIR/skill-results/{context_id}/decompose_epic.json`

| Field | Value |
|-------|-------|
| `skill_name` | `"decompose-epic"` |
| `status` | One of the canonical string values: `"success"`, `"dry_run"`, `"error"` (see mapping below) |
| `extra_status` | Domain-specific status string (see mapping below) |
| `run_id` | Correlation ID |
| `extra` | `{"epic_id": str, "created_tickets": list[{"id": str, "title": str, "repo_hint": str}], "count": int}` |

> **Note on `context_id`:** Prior schema versions included `context_id` as a top-level field. This field is not part of `ModelSkillResult` — it belongs to the file path convention (`$ONEX_STATE_DIR/skill-results/{context_id}/decompose_epic.json`). Consumers should derive context from the file path, not from `context_id` in the result body.

**Status mapping:**

| Current status | Canonical `status` (string value) | `extra_status` |
|----------------|-----------------------------------|----------------|
| `created` | `"success"` (`EnumSkillResultStatus.SUCCESS`) | `"created"` |
| `dry_run` | `"dry_run"` (`EnumSkillResultStatus.DRY_RUN`) | `null` |
| `error` | `"error"` (`EnumSkillResultStatus.ERROR`) | `null` |

**Behaviorally significant `extra_status` values:**
- `"created"` → ticket-pipeline (cross-repo split path) proceeds to invoke epic-team with parent epic ID; the `extra["created_tickets"]` list contains the sub-ticket IDs passed to epic-team
- `null` (dry_run) → ticket-pipeline does not advance; decomposition plan is logged for human review only

**Promotion rule for `extra` fields:** If a field appears in 3+ producer skills, open a ticket to evaluate promotion to a first-class field. If any orchestrator consumer (epic-team, ticket-pipeline) branches on `extra["x"]`, that field MUST be promoted. Note: ticket-pipeline already branches on `extra["created_tickets"]` — evaluate promotion.

Example result:

```json
{
  "skill_name": "decompose_epic",
  "status": "success",
  "extra_status": "created",
  "run_id": "pipeline-1709856000-OMN-2000",
  "extra": {
    "epic_id": "OMN-2000",
    "created_tickets": [
      {"id": "OMN-2001", "title": "Implement X", "repo_hint": "omniclaude"},
      {"id": "OMN-2002", "title": "Add node Y", "repo_hint": "omnibase_core"}
    ],
    "count": 2
  }
}
```

**Status values**: `success` (`extra_status: "created"`) | `dry_run` | `error`

## See Also

- `epic-team` skill (invokes decompose-epic when epic has 0 child tickets)
- `ticket-pipeline` skill (planned: invokes decompose-epic on cross-repo auto-split)
- `plugins/onex/skills/epic-team/repo_manifest.yaml` — repo keyword mapping
- OMN-2522 — implementation ticket
