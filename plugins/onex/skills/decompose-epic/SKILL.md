---
name: decompose-epic
description: Analyze a Linear epic and create per-repo child tickets — invoked by epic-team and ticket-pipeline when cross-repo work is detected
version: 1.0.0
category: workflow
tags: [linear, epic, tickets, cross-repo, decomposition]
author: OmniClaude Team
ticket: OMN-2522
args:
  - name: epic_id
    description: Linear epic ID (e.g., OMN-2522)
    required: true
  - name: --repos
    description: Comma-separated repo names — constrains decomposition to specific repos (Mode B); omit to infer from epic description (Mode A)
    required: false
  - name: --dry-run
    description: Analyze and print decomposition plan without creating tickets; no ModelSkillResult written; exits 0
    required: false
---

# Decompose Epic

## Overview

Analyze a Linear epic and create N per-repo sub-tickets as Linear children. Invoked as a composable sub-skill by `epic-team` (OMN-2530) and `ticket-pipeline` (OMN-2531) when cross-repo work is detected.

Two modes of operation:

- **Mode A** (no `--repos`): reads epic description, infers repo breakdown from `repo_manifest.yaml`, creates sub-tickets with one per identified work area matched to its owning repo
- **Mode B** (`--repos omniclaude,omnibase_core,...`): repos are pre-determined; creates one focused sub-ticket per repo, scoped to that repo's concerns

## Usage Examples

```
/decompose-epic OMN-2522
/decompose-epic OMN-2522 --dry-run
/decompose-epic OMN-2522 --repos omniclaude,omnibase_core
/decompose-epic OMN-2522 --repos omniclaude,omnibase_core --dry-run
```

## Dispatch Contracts

Uses Linear MCP tools directly (NOT gh CLI for Linear operations):

- `mcp__linear-server__get_issue(id=epic_id)` — read epic title, description, team
- `mcp__linear-server__create_issue(...)` — create each sub-ticket with `parentId=epic_id`
- `mcp__linear-server__list_issue_labels(...)` — find repo label IDs for assignment

## Repo Manifest

Reads `~/.claude/epic-team/repo_manifest.yaml` (home-dir path first). Falls back to `plugins/onex/skills/epic-team/repo_manifest.yaml` if the home-dir path does not exist. Each manifest entry maps a repo name to its team ID, label name, and description.

## Sub-Ticket Format

| Field | Value |
|-------|-------|
| `title` | `[{repo}] {scoped description from epic analysis}` |
| `description` | Parent epic reference, repo context, acceptance criteria scoped to that repo |
| `parentId` | `epic_id` |
| `team` | From `repo_manifest` entry for that repo |
| `labels` | Repo label if available (resolved via `mcp__linear-server__list_issue_labels`) |

## ModelSkillResult

Written to `~/.claude/skill-results/{epic_id}/decompose-epic.json` after live execution (not written on `--dry-run`):

```json
{
  "status": "completed",
  "created_tickets": [
    {"id": "OMN-YYYY", "title": "[omniclaude] ...", "repo": "omniclaude"},
    {"id": "OMN-ZZZZ", "title": "[omnibase_core] ...", "repo": "omnibase_core"}
  ],
  "repos_affected": ["omniclaude", "omnibase_core"],
  "epic_id": "OMN-XXXX",
  "count": 2,
  "dry_run": false
}
```

Where `{epic_id}` is the positional argument (e.g., `OMN-2522`). The `context_id` used for the result path equals `epic_id`.

## Error Handling

| Condition | Exit code | Message |
|-----------|-----------|---------|
| Epic not found in Linear | 1 | `decompose-epic: epic {epic_id} not found in Linear` |
| Epic description empty (Mode A) | 1 | `decompose-epic: epic {epic_id} has no description — add context before decomposing` |
| Zero tickets generated | 1 | `decompose-epic: analysis produced 0 sub-tickets — check epic description` |
| Partial create failure | 0 | warn, report partial success in ModelSkillResult |

Partial create failure: if some tickets are created and some fail, the skill exits 0 with `status: "partial"` in the ModelSkillResult. It reports which succeeded and which failed so callers can retry only the failing repos.

## See Also

- `prompt.md` — full execution logic, argument parsing, and step-by-step flow
- `epic-team` skill — orchestrator that calls decompose-epic in Phase 2
- `ticket-pipeline` skill — invokes decompose-epic for cross-repo split in Phase 1b
- `~/.claude/epic-team/repo_manifest.yaml` — repo-to-team mapping
- Linear MCP tools (`mcp__linear-server__*`)
