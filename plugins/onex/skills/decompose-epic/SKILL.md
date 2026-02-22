---
name: decompose-epic
description: Analyze a Linear epic description and create sub-tickets as Linear children
version: 1.0.0
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
    description: "Written to ~/.claude/skill-results/{context_id}/decompose-epic.json"
    fields:
      - status: created | dry_run | error
      - epic_id: str
      - created_tickets: list[{id, title, repo_hint}]
      - count: int
args:
  - name: epic_id
    description: Linear epic ID (e.g., OMN-2000)
    required: true
  - name: --dry-run
    description: Print decomposition plan without creating tickets
    required: false
---

# Decompose Epic

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
2. Read `~/.claude/epic-team/repo_manifest.yaml` for keyword-to-repo mapping
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

Loaded from `~/.claude/epic-team/repo_manifest.yaml`:

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

Write `ModelSkillResult` to `~/.claude/skill-results/{context_id}/decompose-epic.json` on exit.

```json
{
  "skill": "decompose-epic",
  "status": "created",
  "epic_id": "OMN-2000",
  "created_tickets": [
    {"id": "OMN-2001", "title": "Implement X", "repo_hint": "omniclaude"},
    {"id": "OMN-2002", "title": "Add node Y", "repo_hint": "omnibase_core"}
  ],
  "count": 2,
  "context_id": "{context_id}"
}
```

**Status values**: `created` | `dry_run` | `error`

## See Also

- `epic-team` skill (invokes decompose-epic when epic has 0 child tickets)
- `ticket-pipeline` skill (invokes decompose-epic on cross-repo auto-split)
- `~/.claude/epic-team/repo_manifest.yaml` — repo keyword mapping
- OMN-2522 — implementation ticket
