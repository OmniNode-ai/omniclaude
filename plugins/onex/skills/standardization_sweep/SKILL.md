---
name: standardization-sweep
description: Org-wide Python standards enforcement — scans all repos for ruff violations, mypy errors, missing SPDX headers, PEP 604 type union violations, and direct pip/python usage. Parallel scan → triage → optional fix agents per repo → PRs.
version: 1.0.0
level: advanced
debug: false
category: quality
tags:
  - standards
  - python
  - ruff
  - mypy
  - spdx
  - org-wide
  - parallel
author: OmniClaude Team
composable: true
args:
  - name: --repos
    description: Comma-separated repo names to scan (default: all Python repos in omni_home)
    required: false
  - name: --checks
    description: "Comma-separated check types to run: ruff,mypy,spdx,type-unions,pip-usage (default: all)"
    required: false
  - name: --dry-run
    description: Scan and report only — no fix agents, no PRs
    required: false
  - name: --auto-fix
    description: Attempt auto-fix for trivially fixable issues (ruff --fix, spdx stamp)
    required: false
  - name: --severity-threshold
    description: "Minimum severity to report: WARNING | ERROR (default: WARNING)"
    required: false
  - name: --max-parallel-repos
    description: Repos scanned in parallel (default: 3)
    required: false
  - name: --max-parallel-fix
    description: Concurrent fix agents (default: 2)
    required: false
inputs:
  - name: repos
    description: "list[str] — repo names to scan; empty = all Python repos"
outputs:
  - name: skill_result
    description: "ModelSkillResult with status: clean | violations_found | partial | error"
---

# Standardization Sweep

## Overview

Org-wide Python standards enforcement across all OmniNode repos. Runs a parallel
scan of every Python repo, then (without --dry-run) dispatches fix agents per repo
to resolve violations and create PRs.

**Announce at start:** "I'm using the standardization-sweep skill."

> **Autonomous execution**: No Human Confirmation Gate. After scan+triage, proceed
> directly to fix dispatch. `--dry-run` is the only preview mechanism.

## CLI

```
/standardization-sweep                          # Full scan + fix all repos
/standardization-sweep --dry-run               # Scan and report only
/standardization-sweep --repos omniclaude,omnibase_core
/standardization-sweep --checks ruff,spdx      # Run specific checks only
/standardization-sweep --auto-fix              # Attempt trivial auto-fixes inline
/standardization-sweep --severity-threshold ERROR  # Only report errors
```

## Check Categories

| Check | Command | What it finds |
|-------|---------|---------------|
| `ruff` | `uv run ruff check src/` | Style, import, and lint violations |
| `mypy` | `uv run mypy src/ --strict` | Type annotation errors |
| `spdx` | `onex spdx fix --check src tests scripts examples` | Missing SPDX file headers |
| `type-unions` | `grep -r "Optional\[\|Union\["` | PEP 604 violations (use `X \| Y`) |
| `pip-usage` | `grep -r "^pip install\|^python " scripts/` | Direct pip/python calls (use `uv run`) |

## Python Repos (default scan list)

omniclaude, omnibase_core, omnibase_infra, omnibase_spi, omniintelligence,
omnimemory, omninode_infra, onex_change_control, omnibase_compat

## Path Exclusions

Applied to every scan and grep:

```
.git/          .venv/         node_modules/
__pycache__/   *.pyc          dist/          build/
docs/          examples/      fixtures/      _golden_path_validate/
migrations/    *.generated.*  vendored/
```

Additional exclusions for specific checks:
- `type-unions`: also exclude `scripts/` (scripts often have legacy Optional for readability)
- `pip-usage`: also exclude `tests/` (test helpers may call python directly for subprocess tests)

## Execution Algorithm

```
1. PARSE arguments; resolve repo list and check set

2. SCAN (parallel, up to --max-parallel-repos):
   For each repo:
     Run each enabled check; collect (file, line, message, severity) tuples
     On success: repo_results[repo] = findings[]
     On failure: repo_results[repo] = None (scan error)

3. TRIAGE:
   Group findings by repo and check type
   Classify: TRIVIAL_AUTO_FIX | REQUIRES_FIX_AGENT | INFORMATIONAL
   TRIVIAL: ruff --fix-able violations, missing SPDX (stampable)
   REQUIRES_FIX_AGENT: mypy errors, type-union violations (require human judgment)
   INFORMATIONAL: pip-usage in legacy scripts that can't be changed

4. IF no findings → emit ModelSkillResult(status=clean), exit

4a. FINGERPRINT + DEDUP:
   For each finding, compute fingerprint = f"{repo}:{path}:{check}:{symbol_or_line_bucket}"
   Load prior findings from ~/.claude/standardization-sweep/latest/findings.json (if exists)
   Mark finding.new = fingerprint not in prior_fingerprints
   Save all findings (with fingerprints) to ~/.claude/standardization-sweep/<run_id>/findings.json

4b. GROUP findings for dispatch:
   Group key = (repo, check_family, path)
   One fix-agent per repo (not per finding); CRITICAL findings get dedicated agents.

5. IF --dry-run → print per-repo summary table grouped by check_family, exit

6. IF --auto-fix:
   For each TRIVIAL finding:
     run `uv run ruff check --fix src/` in repo
     run `onex spdx fix src tests scripts examples` in repo
   Re-scan; promote fixed findings to RESOLVED

7. DISPATCH fix agents (parallel, up to --max-parallel-fix):
   For each repo with REQUIRES_FIX_AGENT findings:
     Create worktree at ${OMNI_WORKTREES}/std-sweep-<run_id>/<repo>/
     Dispatch polymorphic-agent: resolve all findings for that repo, commit, create PR, auto-merge
     Remove worktree

8. SUMMARY: Post findings + PR links to Slack (best-effort)

9. EMIT ModelSkillResult
```

## ModelSkillResult

```json
{
  "skill": "standardization-sweep",
  "status": "clean | violations_found | partial | error",
  "run_id": "20260317-120000-a1b",
  "repos_scanned": 9,
  "repos_failed": 0,
  "total_violations": 42,
  "trivial_auto_fixed": 10,
  "fix_agents_dispatched": 3,
  "prs_created": 3,
  "by_repo": {
    "omniclaude": {"ruff": 5, "mypy": 0, "spdx": 2, "type-unions": 3, "pip-usage": 0},
    "omnibase_core": {"ruff": 0, "mypy": 1, "spdx": 0, "type-unions": 0, "pip-usage": 0}
  }
}
```

Status values:
- `clean` — zero violations found across all repos and checks
- `violations_found` — violations found and all fix agents succeeded
- `partial` — some fixes succeeded, some failed or blocked
- `error` — scan failures prevented completion
