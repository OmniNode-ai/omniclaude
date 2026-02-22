---
name: gap-analysis
description: Cross-repo integration health audit — closes closed Linear Epics to find Kafka topic drift, model type mismatches, FK reference drift, API contract drift, and DB boundary violations across repo boundaries
version: 1.0.0
category: workflow
tags:
  - integration
  - audit
  - multi-repo
  - kafka
  - database
  - schema
  - linear
  - gap-analysis
author: OmniClaude Team
args:
  - name: --epic
    description: Linear Epic ID to audit (e.g., OMN-2500)
    required: false
  - name: --repo
    description: Limit audit to a specific repo name
    required: false
  - name: --since-days
    description: Look back N days for closed Epics (default 30)
    required: false
  - name: --severity-threshold
    description: "Minimum severity to report: WARNING | CRITICAL (default WARNING)"
    required: false
  - name: --max-findings
    description: Maximum total findings to emit (default 200)
    required: false
  - name: --max-best-effort
    description: Maximum BEST_EFFORT findings to emit (default 50)
    required: false
  - name: --dry-run
    description: Run all probes but do not create or comment on Linear tickets
    required: false
  - name: --output
    description: "Output format: json | md (default md)"
    required: false
---

# Gap Analysis

## Overview

Audit closed Linear Epics to find integration drift across repo boundaries. Checks
Kafka topic names, Pydantic model field compatibility, FK references, OpenAPI contract
hashes, and DB boundary violations.

**Announce at start:** "I'm using the gap-analysis skill to audit cross-repo integration
health for the specified Epic(s)."

## When to Use

**Use when:**
- An Epic has shipped but you suspect integration drift between repos
- You want to verify no silent breakage happened across service boundaries
- Pre-release health check across all repos touched by an Epic
- After a refactoring that spans multiple repositories

**Do NOT use when:**
- Debugging a single known failure (use `root-cause-tracing` instead)
- You need a single-repo code review (use `pr-review` or `local-review`)
- The Epic is still In Progress (wait for it to close first, or use `pipeline-audit`)

## CLI Args

```
/gap-analysis --epic OMN-2500
/gap-analysis --since-days 7
/gap-analysis --epic OMN-2500 --dry-run
/gap-analysis --epic OMN-2500 --output json
/gap-analysis --severity-threshold CRITICAL
/gap-analysis --max-best-effort 20
```

| Arg | Default | Description |
|-----|---------|-------------|
| `--epic` | none | Single Epic to audit |
| `--repo` | all | Limit probes to one repo |
| `--since-days` | 30 | Days to look back for closed Epics |
| `--severity-threshold` | WARNING | Minimum severity to surface |
| `--max-findings` | 200 | Cap on total findings |
| `--max-best-effort` | 50 | Cap on BEST_EFFORT findings |
| `--dry-run` | false | Skip ticket creation/commenting |
| `--output` | md | Output format: `json` or `md` |

## Gating Rules (Hard — Never Violate)

1. **BEST_EFFORT severity cap**: BEST_EFFORT confidence findings are capped at WARNING.
   A BEST_EFFORT finding may NEVER be CRITICAL.
2. **DB boundary is always DETERMINISTIC or SKIP**: Never BEST_EFFORT for DB boundary
   probes. AST-first; grep fallback is acceptable only for non-DB probes.
3. **SKIP probes emit no findings**: Log to `skipped_probes` only.
4. **Empty repos_in_scope**: If `repos_in_scope` is empty after canonicalization, emit
   `status=blocked, reason=NO_REPO_EVIDENCE`. Never silently skip.

## Confidence Levels

| Level | Meaning |
|-------|---------|
| `DETERMINISTIC` | Registry/AST/schema.json — unambiguous |
| `BEST_EFFORT` | Grep fallback — may have false positives |
| `SKIP` | Required input absent (no OpenAPI, no schema.json) |

## The Three Phases

Full orchestration logic is in `prompt.md`. Summary:

**Phase 1 — Intake**: Fetch Epic(s) from Linear, canonicalize repo names, build
`repos_in_scope`. Emit `status=blocked` if no repo evidence found.

**Phase 2 — Probe**: Run the 5 probe categories (Kafka topic drift, model type mismatch,
FK reference drift, API contract drift, DB boundary violation) against each repo in scope.
Apply scan-root filtering (skip tests/docs/generated code). Compute fingerprints and apply
suppressions.

**Phase 3 — Report**: Dedup against existing Linear tickets, create/comment tickets,
write report artifacts to `~/.claude/gap-analysis/{epic_id}/{run_id}.json` and `.md`.

## Fingerprint Spec

SHA-256 of pipe-delimited:
```
category | boundary_kind | rule_name | sorted(repos) | seam_id_suffix | mismatch_shape | repo_relative_path
```

- `seam_id_suffix`: suffix only (no env/namespace prefix)
- `repo_relative_path`: from repo root (not absolute)
- No timestamps, run IDs, or line numbers in the fingerprint

## Ticket Marker Block

Every created/commented ticket contains a stable machine-readable block:

```
<!-- gap-analysis-marker
fingerprint: <sha256>
gap_category: CONTRACT_DRIFT
boundary_kind: kafka_topic
rule_name: topic_name_mismatch
seam: pattern-learned.v1
repos: [omniclaude, omniintelligence]
confidence: DETERMINISTIC
evidence_method: registry
detected_at: <ISO timestamp>
-->
```

## Dedup Table

| Existing ticket state | Last closed | Fingerprint match | Action |
|-----------------------|-------------|-------------------|--------|
| In Progress / Backlog / Todo | — | — | Comment, skip creation |
| Done / Duplicate / Cancelled | ≤ 7 days | Same fingerprint | Comment, skip creation |
| Done / Duplicate / Cancelled | > 7 days OR diff fingerprint | — | Create new ticket |
| None | — | — | Create new ticket |

## Ticket Title Format

`[gap:<fingerprint[:8]>] <category>: <seam_id_suffix>`

Example: `[gap:a3f2c891] CONTRACT_DRIFT: pattern-learned.v1`

## Report Artifacts

```
~/.claude/gap-analysis/{epic_id}/{run_id}.json   # Full report (ModelGapAnalysisReport)
~/.claude/gap-analysis/{epic_id}/{run_id}.md     # Human-readable summary
```

## DB Boundary Rules

Repos that must not access upstream DBs (may have local read-model):
```yaml
no_upstream_db_repos:
  - omnidash
  - omnidash2
  - omniweb
```

Repos where DB writes are allowed:
```yaml
db_write_allowed_repos:
  - omnibase_infra
  - omniintelligence
  - omnimemory
```

## Scan Roots (Prevent False Positives)

| Repo type | Scan | Skip |
|-----------|------|------|
| Python (`src/` layout) | `src/**` | `tests/**`, `fixtures/**`, `docs/**` |
| TypeScript | `client/**`, `server/**`, `src/**` | `__tests__/**`, `*.test.ts`, `fixtures/**` |
| Generated code | — | Always skip |

## Suppressions

Format: `skills/gap-analysis/suppressions.yaml`

```yaml
suppressions:
  - fingerprint: "abc12345..."
    reason: "test harness only"
    expires: "2026-06-01"
  - path_glob: "tests/**"
    rule: "db_boundary"
    reason: "test fixtures allowed DB access"
```

Precedence: `fingerprint` > `path_glob`. Expired suppressions are NOT applied and
emit a WARNING in `expired_suppressions_warned`.

## See Also

- `pipeline-audit` skill (comprehensive end-to-end pipeline verification)
- `root-cause-tracing` skill (debugging a single known failure)
- `create-ticket` skill (ticket creation patterns)
- `skills/gap-analysis/suppressions.yaml` (suppression registry)
- `skills/gap-analysis/models/` (local Pydantic models)
- `~/.claude/gap-analysis/` (report output directory)
