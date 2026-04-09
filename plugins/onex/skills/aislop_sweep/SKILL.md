---
description: Detect AI-generated quality anti-patterns across all repos — phantom callables in skill markdown, backwards compat shims, prohibited env var patterns, hardcoded topic strings, agent-left TODO/FIXME markers, and empty implementations.
version: 2.0.0
mode: full
level: advanced
debug: false
category: quality
tags:
  - ai-quality
  - code-review
  - anti-patterns
  - org-wide
  - autonomous
author: OmniClaude Team
composable: true
args:
  - name: --repos
    description: "Comma-separated repo names (default: all supported repos)"
    required: false
  - name: --checks
    description: "Comma-separated check categories: phantom-callables,compat-shims,prohibited-patterns,hardcoded-topics,todo-fixme,todo-stale,empty-impls (default: all)"
    required: false
  - name: --dry-run
    description: Scan and report only — no tickets, no fixes
    required: false
  - name: --ticket
    description: Create Linear tickets for findings above severity threshold
    required: false
  - name: --severity-threshold
    description: "Minimum severity to act on: WARNING | ERROR (default: WARNING)"
    required: false
inputs:
  - name: repos
    description: "list[str] — repos to scan; empty = all"
outputs:
  - name: skill_result
    description: "ModelSkillResult JSON; aislop-specific findings (by severity and check) are delivered in the model's output field"
---

# AI Slop Sweep

**Announce at start:** "I'm using the aislop-sweep skill."

## Usage

```
/aislop-sweep                                   # Full scan, all repos
/aislop-sweep --dry-run                         # Report only, no tickets
/aislop-sweep --repos omniclaude,omnibase_core  # Limit repos
/aislop-sweep --checks prohibited-patterns,hardcoded-topics
/aislop-sweep --ticket                          # Create Linear tickets
/aislop-sweep --severity-threshold ERROR        # Only ERROR+ findings
```

## Execution

### Step 1 — Parse arguments

- `--repos` → comma-separated list (default: all supported repos)
- `--checks` → comma-separated check names (default: all)
- `--dry-run` → pass through to node
- `--ticket` → create Linear tickets for findings above severity threshold
- `--severity-threshold` → pass through to node (default: WARNING)

### Step 2 — Run node

Path exclusions: `.git/`, `.venv/`, `docs/`, `fixtures/` are always excluded from scanning.

```bash
cd /Volumes/PRO-G40/Code/omni_home/omnimarket  # local-path-ok
uv run python -m omnimarket.nodes.node_aislop_sweep \
  [--repos <comma-list>] \
  [--checks <comma-list>] \
  [--severity-threshold WARNING] \
  [--dry-run]
```

Capture stdout (JSON: `ModelSkillResult`, with aislop findings in the `output` field). Exit 0 = clean, exit 1 = findings found.

### Step 3 — Render report

From the JSON output display:
- Summary: repos scanned, total findings, by-severity counts, by-check counts
- Findings table grouped by severity (CRITICAL → ERROR → WARNING → INFO)
- Each finding: repo, path:line, check, message, severity, confidence, ticketable, autofixable

### Step 4 — Ticket creation (only if `--ticket`)

For each finding where `ticketable=true` (confidence=HIGH, severity≥threshold),
create a Linear ticket via `mcp__linear-server__save_issue`. Deduplicate by
searching for existing open tickets with the same title before creating.

```
Title: aislop: <check> in <repo>:<path>
Project: Active Sprint
Label: aislop-sweep
```

### Step 5 — Write skill result

Write to `$ONEX_STATE_DIR/skill-results/<run_id>/aislop-sweep.json`:

```json
{
  "skill": "aislop-sweep",
  "status": "clean | findings | partial | error",
  "repos_scanned": 0,
  "total_findings": 0,
  "by_severity": {},
  "by_check": {}
}
```

## Architecture

```
SKILL.md  → thin shell: parse args → node dispatch → render results
node      → omnimarket/src/omnimarket/nodes/node_aislop_sweep/
contract  → node_aislop_sweep/contract.yaml
```

All scanning logic lives in the node handler. This skill does no scanning.
