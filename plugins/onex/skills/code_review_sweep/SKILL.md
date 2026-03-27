---
description: Automated code review sweep — dead code detection, missing error handling, stubs shipped as done, missing Kafka wiring, schema mismatches, hardcoded values, and missing tests. Scan files by git hash, dedup findings, optionally create Linear tickets.
version: 1.0.0
mode: full
level: advanced
debug: false
category: quality
tags:
  - code-review
  - dead-code
  - quality
  - org-wide
  - autonomous
author: OmniClaude Team
composable: true
args:
  - name: --repos
    description: "Comma-separated repo names to scan (default: all Python repos in omni_home)"
    required: false
  - name: --categories
    description: "Comma-separated finding categories: dead-code,missing-error-handling,stubs-shipped,missing-kafka-wiring,schema-mismatches,hardcoded-values,missing-tests (default: all)"
    required: false
  - name: --dry-run
    description: Scan and report only — no tickets created. First run defaults to --dry-run.
    required: false
  - name: --ticket
    description: Create Linear tickets for findings (hard cap 10 per run)
    required: false
  - name: --max-tickets
    description: "Hard cap on tickets created per run (default: 10)"
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

# Code Review Sweep

## Overview

Automated code review sweep that detects structural quality issues across all repos.
Tracks reviewed files by git hash to avoid re-scanning unchanged files. Deduplicates
findings across runs via file+line hash in a persistent state file.

**Announce at start:** "I'm using the code-review-sweep skill."

> **First-run safety**: The first invocation defaults to `--dry-run` unless explicitly
> overridden. Subsequent runs respect the flags as given.

> **Autonomous execution**: No Human Confirmation Gate. `--dry-run` is the only
> preview mechanism. Without it, proceed directly to ticket creation.

## Supported Repos (default scan target)

```
CODE_REVIEW_REPOS = [
  "omniclaude", "omnibase_core", "omnibase_infra",
  "omnibase_spi", "omniintelligence", "omnimemory",
  "onex_change_control", "omnibase_compat"
]
```

Excluded by default: `omnidash` (Node.js), `omniweb` (PHP), `omninode_infra` (k8s YAML).
Use `--repos` to override.

## CLI

```
/code-review-sweep                                    # Full scan all repos (first run = dry-run)
/code-review-sweep --dry-run                          # Report only
/code-review-sweep --ticket                           # Create Linear tickets for findings
/code-review-sweep --categories dead-code,stubs-shipped
/code-review-sweep --repos omniclaude,omnibase_core
/code-review-sweep --max-tickets 5                    # Lower ticket cap
```

## Finding Categories

### 1. Dead Code (module-level + vulture)

**Module-level detection** (LLM analysis — single file scope only):
- Unexported functions/classes within a single file that have no internal callers
- Private functions (`_name`) with zero references in the same module
- CONSTRAINT: Do NOT use LLM analysis for cross-file dead code detection

**Cross-file detection** (vulture subprocess):
```bash
uv run vulture src/ --min-confidence 80 --exclude .venv,__pycache__,docs
```
Parse vulture output for unused code with confidence >= 80%.

### 2. Missing Error Handling

Detect patterns where errors are silently swallowed:
- Bare `except:` or `except Exception:` with only `pass`
- `try/except` blocks that catch broad exceptions and do nothing
- Async functions calling external services without timeout/retry

### 3. Stubs Shipped as Done

Detect TODO/FIXME/NotImplementedError in non-test source code:
```bash
grep -rn "TODO\|FIXME\|NotImplementedError\|raise NotImplementedError" \
  --include="*.py" src/ \
  --exclude-dir=.git --exclude-dir=.venv --exclude-dir=__pycache__ \
  --exclude-dir=tests --exclude-dir=docs
```
Exclude abstract base classes and protocol definitions.

### 4. Missing Kafka Wiring

Detect event contracts that declare topics but have no corresponding producer/consumer:
- Parse `contract.yaml` files for `subscribe` and `publish` topic declarations
- Grep for actual `produce()` / `consume()` calls referencing those topics
- Flag contracts with declared but unwired topics

### 5. Schema Mismatches

Detect Pydantic model field mismatches between:
- Contract YAML `config_keys` and actual model fields
- Event schema field names vs. what producers actually emit
- Import references to models that have been renamed/removed

### 6. Hardcoded Values

Detect hardcoded configuration that should come from env/Infisical:
- IP addresses (excluding localhost/127.0.0.1 in tests)
- Port numbers in source code (not in config/contract files)
- Database URLs, API keys, connection strings

### 7. Missing Tests

Detect source modules with no corresponding test file:
- For each `src/<pkg>/module.py`, check for `tests/**/test_module.py`
- Flag modules with zero test coverage markers

## State Tracking

**State file**: `.onex_state/code-review-state.json`

```json
{
  "last_run_id": "20260326-140000-a3f",
  "last_run_at": "2026-03-26T14:00:00Z",
  "file_hashes": {
    "omniclaude:src/omniclaude/hooks/schemas.py": "abc123def",
    "omnibase_core:src/omnibase_core/models/base.py": "def456ghi"
  },
  "finding_fingerprints": {
    "omniclaude:src/omniclaude/hooks/schemas.py:42:dead-code": "20260326-140000-a3f",
    "omnibase_core:src/omnibase_core/models/base.py:15:stubs-shipped": "20260326-140000-a3f"
  }
}
```

**File hash tracking**: Before scanning a file, compute `git hash-object <file>`.
If the hash matches state, skip the file. After scanning, update the hash.

**Finding dedup**: Fingerprint = `f"{repo}:{path}:{line}:{category}"`.
If fingerprint exists in state, skip ticket creation for that finding.

## Ticket Cap

**Hard cap: 10 tickets per run** (configurable via `--max-tickets`).
When cap is reached, remaining findings are reported but no more tickets created.
Prioritize tickets by severity: dead-code and stubs-shipped before missing-tests.

## ModelCodeReviewFinding Schema

```python
{
  "repo":        str,      # e.g. "omniclaude"
  "path":        str,      # repo-relative path
  "line":        int,      # 0 if whole-file
  "category":    str,      # e.g. "dead-code"
  "message":     str,      # human-readable description
  "severity":    str,      # CRITICAL | ERROR | WARNING | INFO
  "confidence":  str,      # HIGH | MEDIUM | LOW
  "fingerprint": str,      # dedup key
  "is_new":      bool,     # not seen in prior run
  "ticketed":    bool,     # ticket was created
}
```

## Execution Algorithm

```
1. PARSE arguments; resolve repo list and category set
   IF first run (no state file exists) AND --dry-run not explicitly set:
     force --dry-run = true, log "First run — defaulting to --dry-run"

2. LOAD state from .onex_state/code-review-state.json (or initialize empty)

3. SCAN (parallel, up to --max-parallel-repos):
   For each repo:
     For each .py file in src/:
       Compute git hash; skip if unchanged
       Run enabled category checks
     For dead-code (vulture):
       Run vulture subprocess, parse output
   Aggregate into findings[]

4. TRIAGE:
   Compute fingerprints for all findings
   Mark is_new = fingerprint not in state.finding_fingerprints

5. IF no findings → emit ModelSkillResult(status=clean), exit

6. IF --dry-run → print findings table grouped by category, exit

7. IF --ticket:
   tickets_created = 0
   For each finding where is_new=true, ordered by severity:
     IF tickets_created >= max_tickets: break
     Create Linear ticket
     tickets_created += 1
     Mark finding.ticketed = true

8. UPDATE state file with new file hashes and finding fingerprints

9. SUMMARY: print results table

10. EMIT ModelSkillResult
```

## ModelSkillResult

```json
{
  "skill": "code-review-sweep",
  "status": "clean | findings | partial | error",
  "run_id": "20260326-140000-a3f",
  "repos_scanned": 8,
  "files_scanned": 142,
  "files_skipped_unchanged": 87,
  "total_findings": 23,
  "new_findings": 8,
  "by_category": {
    "dead-code": 5,
    "missing-error-handling": 3,
    "stubs-shipped": 4,
    "missing-kafka-wiring": 2,
    "schema-mismatches": 1,
    "hardcoded-values": 3,
    "missing-tests": 5
  },
  "tickets_created": 8,
  "ticket_cap_hit": false
}
```

Status values:
- `clean` — zero findings
- `findings` — findings reported (tickets created if requested)
- `partial` — some repos failed to scan
- `error` — scan failures prevented completion
