---
description: Detect AI-generated quality anti-patterns across all repos — phantom callables in skill markdown, backwards compat shims, prohibited env var patterns, hardcoded topic strings, agent-left TODO/FIXME markers, and empty implementations. Scan → triage → optional Linear tickets → optional fix.
version: 1.0.0
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
    description: "Comma-separated repo names to scan (default: aislop supported repos — see supported repo list)"
    required: false
  - name: --checks
    description: "Comma-separated pattern categories: phantom-callables,compat-shims,prohibited-patterns,hardcoded-topics,todo-fixme,empty-impls (default: all)"
    required: false
  - name: --dry-run
    description: Scan and report only — no tickets, no fixes
    required: false
  - name: --ticket
    description: Create Linear tickets for findings above severity threshold
    required: false
  - name: --auto-fix
    description: Attempt auto-fix for trivially fixable patterns (remove shims, dead vars)
    required: false
  - name: --severity-threshold
    description: "Minimum severity to act on: WARNING | ERROR (default: WARNING)"
    required: false
  - name: --max-parallel-repos
    description: Repos scanned in parallel (default: 4)
    required: false
inputs:
  - name: repos
    description: "list[str] — repos to scan; empty = all"
outputs:
  - name: skill_result
    description: "ModelSkillResult with status: clean | findings | partial | error"
---

# AI Slop Sweep

## Overview

Detects AI-generated quality anti-patterns that violate ONEX platform invariants.
These are patterns that slip through normal code review because they look syntactically
valid but violate architectural contracts or CLAUDE.md invariants.

**Announce at start:** "I'm using the aislop-sweep skill."

## Supported Repo List (default scan target)

Aislop scan is intentionally narrower than "all repos" to avoid signal noise from
config-only, vendored, or non-Python repos:

```
AISLOP_REPOS = [
  "omniclaude", "omnibase_core", "omnibase_infra",
  "omnibase_spi", "omniintelligence", "omnimemory",
  "onex_change_control", "omnibase_compat"
]
```

Excluded by default: `omnidash` (Node.js), `omniweb` (PHP), `omninode_infra` (k8s YAML, no Python src/).
Use `--repos` to override.

> **Autonomous execution**: No Human Confirmation Gate. `--dry-run` is the only
> preview mechanism. Without it, proceed directly to ticket creation and/or fix dispatch.

## CLI

```
/aislop-sweep                                   # Full scan all repos
/aislop-sweep --dry-run                        # Report only
/aislop-sweep --ticket                         # Create Linear tickets for findings
/aislop-sweep --checks phantom-callables,todo-fixme
/aislop-sweep --repos omniclaude,omnibase_core
/aislop-sweep --auto-fix                       # Fix trivial patterns
```

## Path Exclusions

Applied to every scan and grep:

```
.git/          .venv/         node_modules/
__pycache__/   *.pyc          dist/          build/
docs/          examples/      fixtures/      _golden_path_validate/
migrations/    *.generated.*  vendored/
```

## Check Categories + Conservative Triage Policy

**Default action by severity tier:**

| Severity | Default action |
|----------|----------------|
| CRITICAL | Always ticket (even in dry-run, emit as finding) |
| ERROR (HIGH confidence) | Ticket if `--ticket` set |
| WARNING | Report only — no ticket unless `--ticket` + `--severity-threshold WARNING` |
| INFO | Report only |

**Conservative first**: Only `prohibited-patterns`, `hardcoded-topics`, and high-confidence `phantom-callables` create tickets by default. Context-sensitive checks (`compat-shims`, `empty-impls`, `todo-fixme`) are WARNING/INFO and require explicit `--ticket --severity-threshold WARNING` to create tickets.

| Check | Pattern | Severity | Confidence rule |
|-------|---------|----------|-----------------|
| `prohibited-patterns` | `ONEX_EVENT_BUS_TYPE=inmemory`, `OLLAMA_BASE_URL` in .py/.sh | CRITICAL | HIGH always |
| `hardcoded-topics` | `"onex\.` string literal in .py outside `contract.yaml` / enum | ERROR | HIGH if in src/, MEDIUM if in tests/ |
| `phantom-callables` | Executable-looking `identifier()` or `call identifier` in **imperative** skill .md context (not prose description, not examples); identifier absent from `_lib/`, `_bin/`, any `.py` under `plugins/` | ERROR | HIGH if confirmed missing (searched 3 locations); MEDIUM if only 1 location checked |
| `compat-shims` | `# removed`, `# backwards.compat`, `_unused_` in non-test src | WARNING | MEDIUM |
| `empty-impls` | `^\s*pass$` in src/ outside Abstract/Protocol/stub files | WARNING | MEDIUM |
| `todo-fixme` | `TODO`, `FIXME`, `HACK` in src/ (not tests/, not docs/) | INFO | LOW |

## ModelSweepFinding Schema

Every finding is a structured object:

```python
{
  "repo":        str,      # e.g. "omniclaude"
  "path":        str,      # repo-relative path
  "line":        int,      # 0 if whole-file
  "check":       str,      # e.g. "prohibited-patterns"
  "message":     str,      # human-readable description
  "severity":    str,      # CRITICAL | ERROR | WARNING | INFO
  "confidence":  str,      # HIGH | MEDIUM | LOW
  "autofixable": bool,
  "ticketable":  bool,     # confidence=HIGH AND severity>=WARNING
}
```

**Fingerprint**: `f"{repo}:{path}:{check}:{symbol_or_line_bucket}"`

## Execution Algorithm

```
1. PARSE arguments; resolve repo list and check set

2. SCAN (parallel, up to --max-parallel-repos):
   For each repo + each enabled check:
     Run grep pattern or static analysis
     Collect (file, line, pattern, severity) tuples
   Aggregate into findings[]

3. TRIAGE:
   Apply per-finding confidence + file-context rules:
   - prohibited-patterns in .py/.sh → CRITICAL, HIGH confidence always
   - hardcoded-topics in src/ → ERROR, HIGH; in tests/ → WARNING, MEDIUM
   - phantom-callables: verify identifier absent from _lib/, _bin/, any .py under plugins/
     → HIGH if confirmed missing; MEDIUM if path match is ambiguous
   - compat-shims: flag only in src/ (skip tests/, docs/, skill markdown)
   - empty-impls: skip *Abstract*, *Protocol*, *stub*, *__init__* files
   - todo-fixme: flag only in src/ (not tests/, not docs/, not skill markdown)
   Set ticketable=true when confidence=HIGH AND severity>=WARNING

4. IF no findings → emit ModelSkillResult(status=clean), exit

4a. FINGERPRINT + DEDUP:
   Compute fingerprints; load ~/.claude/aislop-sweep/latest/findings.json
   Mark finding.new = fingerprint not in prior_fingerprints
   Save to ~/.claude/aislop-sweep/<run_id>/findings.json

4b. GROUP findings:
   Group key = (repo, check_family, path)
   At most one ticket per group key unless severity=CRITICAL

5. IF --dry-run → print findings table by category and confidence tier, exit

6. IF --ticket:
   For each group: ticketable=true AND new=true AND severity>=threshold:
     Create Linear ticket: "aislop: <check_family> in <repo>:<path>"
     Parent: active sprint, label: aislop-sweep

7. IF --auto-fix:
   Auto-fix allowlist (extremely narrow):
   - Missing SPDX headers → stamp via `onex spdx fix`
   - `# removed` comment on blank line → safe to remove
   NOT auto-fixed: compat-shims with content, `_unused_` vars, empty `pass`
   Commit + PR per repo after confirming change via post-fix re-grep.

8. SUMMARY: Slack notification (best-effort)

9. EMIT ModelSkillResult
```

## ModelSkillResult

```json
{
  "skill": "aislop-sweep",
  "status": "clean | findings | partial | error",
  "run_id": "20260317-130000-b2c",
  "repos_scanned": 8,
  "total_findings": 23,
  "by_severity": {"CRITICAL": 1, "ERROR": 5, "WARNING": 12, "INFO": 5},
  "by_check": {
    "phantom-callables": 3,
    "compat-shims": 8,
    "prohibited-patterns": 1,
    "hardcoded-topics": 2,
    "todo-fixme": 7,
    "empty-impls": 2
  },
  "tickets_created": 6,
  "auto_fixed": 3
}
```

Status values:
- `clean` — zero findings
- `findings` — findings reported (tickets/fixes applied if requested)
- `partial` — some repos failed to scan
- `error` — scan failures prevented completion
