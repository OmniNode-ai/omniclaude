---
description: Measure test coverage across all Python repos under omni_home, flag modules below threshold, and auto-create Linear tickets for coverage gaps
mode: full
version: 1.0.0
level: intermediate
debug: false
category: quality
tags:
  - coverage
  - testing
  - quality
  - automation
  - sweep
author: OmniClaude Team
composable: true
args:
  - name: --threshold
    description: "Minimum coverage percentage to pass (default: 60)"
    required: false
  - name: --repos
    description: "Comma-separated list of repos to scan (default: all Python repos under omni_home)"
    required: false
  - name: --auto-ticket
    description: "Auto-create Linear tickets for modules below threshold (default: true)"
    required: false
  - name: --dry-run
    description: "Report coverage gaps without creating tickets"
    required: false
  - name: --skip-install
    description: "Skip uv sync step (use when deps are already installed)"
    required: false
---

# Coverage Sweep

## Dispatch Requirement

When invoked, dispatch to a polymorphic-agent:

```
Agent(
  subagent_type="onex:polymorphic-agent",
  description="Run coverage-sweep across repos",
  prompt="Run the coverage-sweep skill. <full context and args>"
)
```

**CRITICAL**: `subagent_type` MUST be `"onex:polymorphic-agent"` (with the `onex:` prefix).

**Skill ID**: `onex:coverage_sweep`
**Version**: 1.0.0
**Owner**: omniclaude
**Ticket**: OMN-6736

---

## Purpose

Measure test coverage across all Python repos in the omni_home registry, identify modules
that fall below a configurable threshold, and optionally auto-create Linear tickets for
coverage gaps. Designed to run as a recurring quality gate or on-demand audit.

---

## Usage

```
/coverage-sweep
/coverage-sweep --threshold 80
/coverage-sweep --repos omnibase_core,omniclaude --dry-run
/coverage-sweep --threshold 70 --auto-ticket
```

---

## Behavior

### Step 1: Discover repos <!-- ai-slop-ok: skill-step-heading -->

Scan `$OMNI_HOME/` for directories containing `pyproject.toml`. <!-- local-path-ok -->
If `--repos` is provided, filter to only those repos.

Skip repos that do not have a `tests/` directory.

### Step 2: Run coverage per repo <!-- ai-slop-ok: skill-step-heading -->

For each repo, run:

```bash
cd $OMNI_HOME/{repo} # local-path-ok
uv run pytest tests/ -m unit --cov=src/ --cov-report=json --cov-report=term -q 2>/dev/null || true
```

If `--skip-install` is not set, run `uv sync --group dev` first.

Parse the generated `coverage.json` to extract per-module coverage percentages.

### Step 3: Evaluate against threshold <!-- ai-slop-ok: skill-step-heading -->

Default threshold: 60%. Override with `--threshold`.

For each module, classify:
- **PASS**: coverage >= threshold
- **GAP**: coverage < threshold
- **MISSING**: no tests found at all (0% coverage)

### Step 4: Generate report <!-- ai-slop-ok: skill-step-heading -->

Output a summary table:

```
Coverage Sweep Report
=====================

Threshold: 60%

| Repo | Module | Coverage | Status |
|------|--------|----------|--------|
| omnibase_core | src/omnibase_core/models/ | 85% | PASS |
| omnibase_core | src/omnibase_core/validators/ | 42% | GAP |
| omniclaude | src/omniclaude/hooks/ | 71% | PASS |
| omniclaude | src/omniclaude/cli/ | 0% | MISSING |

Summary: 2 PASS, 1 GAP, 1 MISSING across 2 repos
```

Write the full report to `$ONEX_STATE_DIR/coverage-sweep/latest-report.json`.

### Step 5: Auto-ticket gaps (unless --dry-run) <!-- ai-slop-ok: skill-step-heading -->

For each GAP or MISSING module (if `--auto-ticket` is true, which is the default):

1. Check if an open Linear ticket already exists for this coverage gap
   (search for `coverage-gap:{repo}:{module_path}` in ticket descriptions)
2. If no existing ticket, create one:
   - Title: `chore: add test coverage for {repo}/{module_path}`
   - Description includes: current coverage %, threshold, which files lack tests
   - Labels: `tech-debt`, `testing`
   - Project: Active Sprint
3. Report created/skipped tickets in the output

### Step 6: Emit summary <!-- ai-slop-ok: skill-step-heading -->

Write skill result to `$ONEX_STATE_DIR/skill-results/{context_id}/coverage_sweep.json`:

```json
{
  "status": "success",
  "extra_status": "gaps_found",
  "extra": {
    "repos_scanned": 5,
    "modules_total": 42,
    "modules_passing": 35,
    "modules_gap": 5,
    "modules_missing": 2,
    "threshold": 60,
    "tickets_created": 3,
    "tickets_skipped": 4
  }
}
```

---

## Error Handling

- If `uv run pytest` fails for a repo: log the error, mark all modules as UNKNOWN, continue
- If Linear API is unavailable: report gaps but skip ticket creation, exit cleanly
- If a repo has no `src/` directory: skip it with a warning

---

## Integration Points

- **autopilot**: Can be added as a step in close-out mode for periodic coverage audits
- **ticket-pipeline**: OMN-6730 uses coverage data from this skill as a hard gate
- **insights-to-plan**: Coverage trends feed into sprint planning insights
