---
name: decompose-epic
description: Analyze a Linear epic description and automatically create sub-tickets as children, enabling epic-team to handle epics with zero initial child tickets
version: 1.0.0
category: workflow
tags:
  - epic
  - linear
  - decomposition
  - tickets
  - autonomous
author: OmniClaude Team
composable: true
args:
  - name: epic_id
    description: Linear epic identifier (e.g., OMN-2511)
    required: true
  - name: --dry-run
    description: Show decomposition plan without creating tickets
    required: false
inputs:
  - name: epic_id
    description: Linear identifier (e.g., OMN-2511)
  - name: dry_run
    description: bool — show decomposition without creating tickets
outputs:
  - name: skill_result
    description: ModelSkillResult with created ticket identifiers
---

# Decompose Epic

## Overview

Analyze a Linear epic's description and create sub-tickets automatically as children of the epic.
Enables `epic-team` to handle epics with zero child tickets without hard-stopping.

**Announce at start:** "I'm using the decompose-epic skill for epic {epic_id}."

## Quick Start

```
/decompose-epic OMN-2511             # Decompose and create sub-tickets
/decompose-epic OMN-2511 --dry-run   # Show plan without creating tickets
```

## Workflow

```
decompose-epic OMN-XXXX
  1. Fetch epic from Linear (description, title, team, project)
  2. Load repo manifest from ~/.claude/epic-team/repo_manifest.yaml
  3. Analyze epic description to identify logical work units:
     - Each work unit = one sub-ticket
     - Assign to repo using keyword matching from manifest
     - Estimate scope (small/medium/large)
  4. Present decomposition plan (always shown, even without --dry-run)
  5. Post Slack LOW_RISK gate:
     "Created N sub-tickets for {epic_id} — reply 'proceed' or 'reject' within 30 min"
     Silence = proceed (LOW_RISK)
  6. If rejected via Slack: abort, log reason
  7. Create sub-tickets in Linear as children of epic (if not --dry-run)
  8. Emit ModelSkillResult with created ticket identifiers
```

## Decomposition Algorithm

### Step 1: Fetch Epic

```python
epic = mcp__linear-server__get_issue(epic_id, includeRelations=True)
# Use: epic.title, epic.description, epic.team
```

### Step 2: Identify Work Units

Analyze the epic description by looking for:

- Numbered lists (1. item, 2. item → each is a work unit)
- Section headers (## Section → potential work unit boundary)
- "Changes" or "Tasks" sections (each bullet = work unit)
- Distinct file paths or modules mentioned
- Explicit "Phase N" or "Step N" markers

Group related items if they touch the same subsystem and can be done atomically.

### Step 3: Assign to Repos

For each work unit:
1. Load `~/.claude/epic-team/repo_manifest.yaml`
2. Score each repo by keyword matches in the work unit description
3. Assign to highest-scoring repo; if tie, assign to first matched
4. If no match: assign to `unmatched` (create ticket in same team, no repo label)

### Step 4: Create Sub-Tickets

```python
mcp__linear-server__create_issue(
    title=f"[{repo_name}] {work_unit.title}",
    team=epic.team,
    description=f"""
{work_unit.description}

## Source

Decomposed from [{epic_id}]({epic.url}) by decompose-epic skill.
    """,
    parentId=epic.id,
    labels=[repo_name, "auto-decomposed"],
    priority=epic.priority or 3
)
```

## Slack Gate (LOW_RISK)

After computing the decomposition plan (before creating tickets):

```
[LOW_RISK] decompose-epic: {epic_id}

Proposed decomposition for "{epic.title}":
  {N} sub-tickets across {M} repos:
  - omniclaude (K tickets): {titles...}
  - omnibase_core (J tickets): {titles...}

Reply 'proceed' to create tickets, 'reject' to abort.
Timeout: 30 min → auto-proceed (LOW_RISK)
```

Uses `slack-gate` skill with:
```yaml
gate_id: "decompose-epic:{epic_id}:{run_id}"
risk: LOW_RISK
timeout_seconds: 1800  # 30 minutes
```

## ModelSkillResult Output

Written to `~/.claude/skill-results/{context_id}/decompose-epic.json`:

```json
{
  "status": "completed | dry_run | rejected",
  "artifacts": {
    "epic_id": "OMN-2511",
    "created_tickets": ["OMN-2512", "OMN-2513", "OMN-2514"],
    "dry_run_plan": null
  }
}
```

For `--dry-run`:
```json
{
  "status": "dry_run",
  "artifacts": {
    "epic_id": "OMN-2511",
    "created_tickets": [],
    "dry_run_plan": [
      {"title": "...", "repo": "omniclaude", "scope": "small"},
      {"title": "...", "repo": "omnibase_core", "scope": "medium"}
    ]
  }
}
```

## Failure Handling

| Error | Behavior |
|-------|----------|
| Epic not found in Linear | Hard exit with error message |
| repo_manifest missing | Hard exit: "Create ~/.claude/epic-team/repo_manifest.yaml" |
| Epic description empty | Abort with `status: failed`, suggest manual ticket creation |
| Slack gate rejected | Abort with `status: rejected`, log reason |
| Linear ticket creation fails | Log partial success, continue with remaining, report failed in result |

## See Also

- `epic-team` skill — calls decompose-epic when epic has zero child tickets
- `slack-gate` skill — LOW_RISK approval gate used after decomposition
- `~/.claude/epic-team/repo_manifest.yaml` — repo routing configuration
- Linear MCP tools (`mcp__linear-server__*`) — issue creation and fetching
