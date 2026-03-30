---
description: Measure test coverage across all Python repos under omni_home, flag modules below threshold, and auto-create Linear tickets for coverage gaps
version: 1.0.0
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
  - name: --team
    description: "Linear team name (default: Omninode)"
    required: false
  - name: --project
    description: "Linear project name (default: Active Sprint)"
    required: false
  - name: --force-rescan
    description: Ignore cache and re-run coverage scans
    required: false
inputs:
  - name: repos
    description: "list[str] -- repos to scan; empty = default list"
outputs:
  - name: skill_result
    description: "ModelCoverageSweepReport with scan results and ticket summary"
---

# Coverage Sweep

## Overview

Scans all OmniNode Python repos for test coverage gaps, identifies modules with
zero or below-target coverage, checks for existing tickets, and auto-creates
Linear tickets for uncovered modules.

**Announce at start:** "I'm using the coverage-sweep skill."

## Supported Repos (default scan target)

```
DEFAULT_REPOS = [
  "omniclaude", "omnibase_core", "omnibase_infra",
  "omnibase_spi", "omniintelligence", "omnimemory",
  "onex_change_control", "omnibase_compat"
]
```

## CLI

```
/coverage-sweep                                  # Full scan + ticket creation
/coverage-sweep --dry-run                        # Report only
/coverage-sweep --repos omniclaude,omnibase_core # Scan specific repos
/coverage-sweep --target 80                      # Override target percentage
/coverage-sweep --max-tickets 10                 # Limit tickets created
/coverage-sweep --force-rescan                   # Ignore 1-hour cache
```

## How It Works

### Phase 1: Scan

For each repo:
1. Check cache (1-hour TTL). If fresh, use cached result.
2. Otherwise run: `uv run pytest --cov=src/ --cov-report=json -q`
3. Parse the JSON coverage report
4. Identify modules below target (default 50%)
5. Cross-reference with `git log --since=14d` for recently-changed modules

### Phase 2: Prioritize

Gaps are prioritized:
1. **Zero coverage** -- complete blind spots (Linear priority: High)
2. **Recently changed, below target** -- changed without tests (priority: Medium)
3. **Below target** -- below repo target (priority: Low)

### Phase 3: Dedup

Before creating tickets:
1. Fetch existing Linear tickets with `test-coverage` or `coverage` labels
2. Search by title pattern: `test(coverage): add tests for <module> (<repo>)`
3. Skip any gaps that already have matching tickets

### Phase 4: Create Tickets

For each non-duplicate gap (up to `--max-tickets`):
1. Create Linear ticket with structured description
2. Include: module path, current coverage %, statement counts
3. Add `test-coverage` and `auto-generated` labels
4. Assign to specified team and project

## Cache

Scan results are cached at `~/.onex_state/coverage_cache/<repo>.json` with 1-hour TTL.
Use `--force-rescan` to bypass.

## Integration with Refill Sprint

This skill is designed to be called as a tier in the refill-sprint workflow:
```
Ready queue -> Future tech debt -> Coverage gaps (this skill)
```

When sprint is idle and Ready/Future are empty, coverage-sweep generates fresh
work items from actual test coverage data.

## Output

Reports include per-repo breakdown:
- Total modules, modules below target, zero-coverage modules
- Repo average coverage percentage
- List of gaps with priority classification
- Tickets created vs skipped (dedup)

## Execution Steps

1. Parse arguments (repos, target, dry-run, max-tickets)
2. Initialize `CoverageScanner` with omni_home path and target
3. Run `scanner.scan_repos(repos)` to get coverage data
4. If `--dry-run`: report gaps and exit
5. Fetch existing Linear tickets for dedup:
   ```
   mcp__linear-server__list_issues(
     team=team_id,
     labels=["test-coverage"]
   )
   ```
6. Initialize `CoverageTicketCreator` with existing titles
7. Build ticket requests: `creator.build_ticket_requests(scan_results, max_tickets=N)`
8. For each ticket request, create via:
   ```
   mcp__linear-server__create_issue(
     title=req.title,
     description=req.description,
     team=team_id,
     project=project_id,
     priority=req.priority,
     labels=req.labels
   )
   ```
9. Report summary: gaps found, tickets created, tickets skipped

## Error Handling

- If a repo scan fails (no pytest, no src/, timeout), log and continue
- If Linear API fails, report the error but don't block remaining tickets
- Cache errors are non-fatal (scan proceeds without cache)
