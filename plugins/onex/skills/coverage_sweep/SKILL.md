---
description: Measure test coverage across all Python repos under omni_home, flag modules below threshold, and auto-create Linear tickets for coverage gaps
version: 3.0.0
mode: full
level: intermediate
debug: false
category: quality
tags:
  - coverage
  - testing
  - automation
  - linear
  - org-wide
author: OmniClaude Team
composable: true
args:
  - name: --repos
    description: "Comma-separated repo names to scan (default: all Python repos)"
    required: false
  - name: --target
    description: "Coverage target percentage (default: 50)"
    required: false
  - name: --dry-run
    description: Scan and report only -- no ticket creation
    required: false
  - name: --max-tickets
    description: "Maximum tickets to create per run (default: 20)"
    required: false
  - name: --force-rescan
    description: Ignore cache and re-run coverage scans
    required: false
inputs:
  - name: repos
    description: "list[str] -- repos to scan; empty = default list"
outputs:
  - name: skill_result
    description: "CoverageSweepResult JSON with gaps, per-repo breakdown, and ticket summary"
---

# Coverage Sweep

**Announce at start:** "I'm using the coverage-sweep skill."

## Usage

```
/coverage-sweep                                  # Full scan + ticket creation
/coverage-sweep --dry-run                        # Report only
/coverage-sweep --repos omniclaude,omnibase_core # Scan specific repos
/coverage-sweep --target 80                      # Override target percentage
/coverage-sweep --max-tickets 10
/coverage-sweep --force-rescan                   # Ignore 1-hour cache
```

## Execution

### Step 1 — Parse arguments

- `--repos` → comma-separated repo names (default: all 8 supported repos)
- `--target` → coverage target percentage (default: 50)
- `--dry-run` → pass through to node; skips ticket creation
- `--max-tickets` → cap on Linear tickets created per run (default: 20)
- `--force-rescan` → bypass 1-hour coverage cache

### Step 2 — Dispatch to node

```bash
onex run-node node_coverage_sweep \
  --input '{"repos": "<comma-list>", "target_pct": 50, "dry_run": false}' \
  --timeout 300
```

On non-zero exit, a `SkillRoutingError` JSON envelope is returned — surface it directly, do not produce prose. Exit 0 = clean, exit 1 = gaps found.

### Step 3 — Render report

Display per-repo breakdown: total modules, modules below target, zero-coverage modules,
repo average coverage %. List gaps grouped by priority (ZERO → RECENTLY_CHANGED → BELOW_TARGET).

### Step 4 — Ticket creation (only if not `--dry-run`)

Fetch existing Linear tickets with `test-coverage` label to dedup. For each gap not already
tracked (up to `--max-tickets`), create via `mcp__linear-server__save_issue`:

```
Title: test(coverage): add tests for <module> (<repo>)
Labels: test-coverage, auto-generated
Priority: High (zero coverage) | Medium (recently changed) | Low (below target)
```

## Supported Repos (default scan)

```
omniclaude, omnibase_core, omnibase_infra,
omnibase_spi, omniintelligence, omnimemory,
onex_change_control, omnibase_compat
```

## Architecture

```
SKILL.md   -> thin shell: parse args -> node dispatch -> render results
node       -> omnimarket/src/omnimarket/nodes/node_coverage_sweep/
contract   -> node_coverage_sweep/contract.yaml
```

All scanning logic lives in the node handler. This skill does no scanning.
