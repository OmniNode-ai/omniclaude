---
name: decompose-epic
description: Analyze a Linear epic description and automatically create sub-tickets as children, enabling epic-team to handle epics with zero initial child tickets
version: 1.0.0
category: workflow
tags: [epic, linear, decomposition, tickets, autonomous]
author: OmniClaude Team
composable: true
args:
  - name: epic_id
    description: Linear epic identifier (e.g., OMN-2511)
    required: true
  - name: --dry-run
    description: Show decomposition plan without creating tickets
    required: false
---

# Decompose Epic

## Overview

Analyze a Linear epic's description and create sub-tickets automatically as children of the epic.
Run this skill BEFORE `epic-team` when an epic has zero child tickets — `epic-team` hard-exits
when no child tickets exist, so decompose-epic is used to pre-populate the epic first.

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
  2. Load repo manifest from plugins/onex/skills/epic-team/repo_manifest.yaml
  3. Analyze epic description to identify logical work units:
     - Each work unit = one sub-ticket
     - Assign to repo using keyword matching from manifest
     - Estimate scope (small/medium/large)
  4. Present decomposition plan (always shown, even without --dry-run)
  5. If --dry-run: write result.json with status: dry_run and exit — skip steps 6-9
  6. Post Slack LOW_RISK gate:
     "Proposed N sub-tickets for {epic_id} — reply 'proceed' to create or 'reject' to abort within 30 min"
     Silence = proceed (LOW_RISK)
  7. If rejected via Slack: abort, log reason
  8. Create sub-tickets in Linear as children of epic
  9. Write result to ~/.claude/skill-results/decompose-epic-{epic_id}/result.json
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
1. Load `plugins/onex/skills/epic-team/repo_manifest.yaml`
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

After computing the decomposition plan (before creating tickets), post a Slack message and wait
for approval. Generate a `timestamp` at skill start using `import time; timestamp = int(time.time())`.

Message to post:

```
[LOW_RISK] decompose-epic: {epic_id}

Proposed decomposition for "{epic.title}":
  {N} sub-tickets across {M} repos:
  - omniclaude (K tickets): {titles...}
  - omnibase_core (J tickets): {titles...}

Reply 'proceed' to create tickets, 'reject' to abort.
Gate ID: decompose-epic:{epic_id}:{timestamp}
Timeout: 30 min → auto-proceed (LOW_RISK)
```

Wait up to 30 minutes (1800 seconds) for a reply:
- Reply contains 'proceed' (case-insensitive): continue to ticket creation
- Reply contains 'reject' (case-insensitive): abort with `status: rejected`
- No reply after 30 min: auto-proceed (LOW_RISK = silence means proceed)

Slack notification is **non-fatal**: if posting fails, log the error and auto-proceed.

## ModelSkillResult Output

Written to `~/.claude/skill-results/decompose-epic-{epic_id}/result.json`:

```json
{
  "status": "completed | dry_run | rejected | failed | partial",
  "artifacts": {
    "epic_id": "OMN-2511",
    "created_tickets": ["OMN-2512", "OMN-2513", "OMN-2514"],
    "failed_tickets": [],
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
| repo_manifest missing | Hard exit: "repo_manifest.yaml not found at plugins/onex/skills/epic-team/repo_manifest.yaml" |
| Epic description empty | Abort with `status: failed`, suggest manual ticket creation |
| Slack gate rejected | Abort with `status: rejected`, log reason |
| Linear ticket creation fails | Log partial success, continue with remaining, write `status: partial` with failed ticket IDs in result |

## See Also

- `epic-team` skill — orchestrates agent teams across repos for epics that already have child tickets; hard-exits if no child tickets exist — run decompose-epic first to pre-populate
- `plugins/onex/skills/epic-team/repo_manifest.yaml` — repo routing configuration (keyword-based repo assignment)
- Linear MCP tools (`mcp__linear-server__*`) — issue creation and fetching
