---
description: Cross-repo integration health audit with detect, fix, and cycle modes
mode: full
version: 1.0.0
level: advanced
debug: false
category: quality
tags: [gap, analysis, fix, cycle, integration, health]
author: OmniClaude Team
composable: true
inputs:
  - name: subcommand
    type: str
    description: "Mode: detect, fix, or cycle"
    required: true
args:
  - name: subcommand
    description: "Mode: detect (audit), fix (auto-fix loop), cycle (detect->fix->verify), or reconcile (trigger artifact reconciliation)"
    required: true
  - name: --epic
    description: "Linear epic ID to audit (detect mode)"
    required: false
  - name: --report
    description: "Path to gap-analysis report (fix mode)"
    required: false
  - name: --max-iterations
    description: "Maximum fix iterations (cycle mode, default: 3)"
    required: false
  - name: --dry-run
    description: "Preview without making changes"
    required: false
  - name: --repo
    description: "Limit audit to a specific repo name (detect mode)"
    required: false
  - name: --since-days
    description: "Look back N days for closed Epics (detect mode, default 30)"
    required: false
  - name: --severity-threshold
    description: "Minimum severity to report: WARNING | CRITICAL (detect mode, default WARNING)"
    required: false
  - name: --max-findings
    description: "Maximum total findings to emit (detect mode, default 200)"
    required: false
  - name: --max-best-effort
    description: "Maximum BEST_EFFORT findings to emit (detect mode, default 50)"
    required: false
  - name: --output
    description: "Output format: json | md (detect mode, default md)"
    required: false
  - name: --ticket
    description: "Single finding via Linear ticket ID containing a gap-analysis marker block (fix mode)"
    required: false
  - name: --latest
    description: "Follow ~/.claude/gap-analysis/latest/ symlink (fix mode, default if no other entry point)"
    required: false
  - name: --mode
    description: "Execution mode: ticket-pipeline | ticket-work | implement-only (fix mode, default ticket-pipeline)"
    required: false
  - name: --choose
    description: "Provide decisions for gated findings e.g. GAP-b7e2d5f8=A,GAP-c3a1e2d4=B (fix mode)"
    required: false
  - name: --force-decide
    description: "Re-open previously decided findings in decisions.json (fix mode)"
    required: false
  - name: --resume
    description: "Path to a prior gap-cycle summary.json to resume from (cycle mode)"
    required: false
  - name: --audit
    description: "Record that pipeline-audit was requested (cycle mode, v0.1 deferred)"
    required: false
  - name: --no-fix
    description: "Skip gap-fix phase (cycle mode)"
    required: false
  - name: --verify
    description: "Run golden-path-validate after fix (cycle mode)"
    required: false
  - name: --auto-only
    description: "Skip GATE findings in fix phase (cycle mode)"
    required: false
  - name: --skip-infra-probes
    description: "Skip infrastructure probes (projection_lag, env_activation, migration_parity) that require live services"
    required: false
  - name: --include-auth-probes
    description: "Include auth_config probes (disabled by default as they require Infisical access)"
    required: false
  - name: --lag-threshold
    description: "Consumer group lag threshold for projection_lag probe (default: 10000)"
    required: false
---

# Gap

Cross-repo integration health audit. Consolidated from gap-analysis, gap-fix, and gap-cycle.

## Execution Rules

Execute end-to-end without stopping between tasks. If blocked on one task, record a skip note
and continue to the next. Only pause for: (a) credentials not available in the session,
(b) a destructive action not explicitly covered by the plan, or (c) an explicit user gate in
the plan. Do not exit plan mode or stop to "await direction" in any other circumstance.

---

## Overview

Unified cross-repo integration health audit. Three subcommands:
- **detect**: Audit closed epics for Kafka topic drift, model mismatches, FK drift, API contract drift, DB boundary violations, and branch protection drift
- **fix**: Auto-fix loop for gap-analysis findings with decision gates
- **cycle**: Full detect->fix->verify loop with artifact chaining

**Announce at start:** "I'm using the gap skill to perform cross-repo integration health analysis."

## Subcommand Routing

Parse the first positional argument as the subcommand:

```
/gap detect --epic OMN-2500
/gap fix --report multi-epic-2026-02-23/run-001
/gap cycle --epic OMN-XXXX
```

Route to the corresponding section in `prompt.md` based on the subcommand value.

---

## Subcommand: detect

Absorbed from: gap-analysis (v1.0.0)

### When to Use

**Use when:**
- An Epic has shipped but you suspect integration drift between repos
- You want to verify no silent breakage happened across service boundaries
- Pre-release health check across all repos touched by an Epic
- After a refactoring that spans multiple repositories

**Do NOT use when:**
- Debugging a single known failure (use `systematic-debugging` instead)
- You need a single-repo code review (use `pr-review` or `local-review`)
- The Epic is still In Progress (wait for it to close first, or use `pipeline-audit`)

### CLI Examples

```
/gap detect --epic OMN-2500
/gap detect --since-days 7
/gap detect --epic OMN-2500 --dry-run
/gap detect --epic OMN-2500 --output json
/gap detect --severity-threshold CRITICAL
/gap detect --max-best-effort 20
/gap detect --epic OMN-2500 --skip-infra-probes
/gap detect --epic OMN-2500 --include-auth-probes --lag-threshold 5000
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
| `--skip-infra-probes` | false | Skip probes 2.7-2.8, 2.10 (env_activation, projection_lag, migration_parity) that require live infrastructure |
| `--include-auth-probes` | false | Include probe 2.9 (auth_config); disabled by default as it requires Infisical access |
| `--lag-threshold` | 10000 | Consumer group lag threshold for projection_lag probe (probe 2.8) |

### Gating Rules (Hard -- Never Violate)

1. **BEST_EFFORT severity cap**: BEST_EFFORT confidence findings are capped at WARNING.
   A BEST_EFFORT finding may NEVER be CRITICAL.
2. **DB boundary is always DETERMINISTIC or SKIP**: Never BEST_EFFORT for DB boundary
   probes. AST-first; grep fallback is acceptable only for non-DB probes.
3. **SKIP probes emit no findings**: Log to `skipped_probes` only.
4. **Empty repos_in_scope**: If `repos_in_scope` is empty after canonicalization, emit
   `status=blocked, reason=NO_REPO_EVIDENCE`. Never silently skip.

### Confidence Levels

| Level | Meaning |
|-------|---------|
| `DETERMINISTIC` | Registry/AST/schema.json -- unambiguous |
| `BEST_EFFORT` | Grep fallback -- may have false positives |
| `SKIP` | Required input absent (no OpenAPI, no schema.json) |

### The Three Phases

Full orchestration logic is in `prompt.md`. Summary:

**Phase 1 -- Intake**: Fetch Epic(s) from Linear, canonicalize repo names, build
`repos_in_scope`. Emit `status=blocked` if no repo evidence found.

**Phase 2 -- Probe**: Run the 12 probe categories against each repo in scope:
1. Kafka topic drift, 2. Model type mismatch, 3. FK reference drift, 4. API contract drift,
5. DB boundary violation, 6. Topic registry drift, 7. Env activation drift,
8. Projection lag, 9. Auth config drift, 10. Migration parity, 11. Legacy config patterns,
12. Branch protection drift.
Apply scan-root filtering (skip tests/docs/generated code). Compute fingerprints and apply
suppressions. Topic registry auto-fix is LOCAL-ONLY (enum member addition only).
Legacy config auto-fix uses deterministic search-replace from the denylist.
Branch protection auto-fix removes stale required check names via the GitHub API.

**Phase 3 -- Report**: Dedup against existing Linear tickets, create/comment tickets,
write report artifacts to `~/.claude/gap-analysis/{epic_id}/{run_id}.json` and `.md`.

### Fingerprint Spec

SHA-256 of pipe-delimited:
```
category | boundary_kind | rule_name | sorted(repos) | seam_id_suffix | mismatch_shape | repo_relative_path
```

- `seam_id_suffix`: suffix only (no env/namespace prefix)
- `repo_relative_path`: from repo root (not absolute)
- No timestamps, run IDs, or line numbers in the fingerprint

### Ticket Marker Block

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

### Dedup Table

| Existing ticket state | Last closed | Fingerprint match | Action |
|-----------------------|-------------|-------------------|--------|
| In Progress / Backlog / Todo | -- | -- | Comment, skip creation |
| Done / Duplicate / Cancelled | <= 7 days | Same fingerprint | Comment, skip creation |
| Done / Duplicate / Cancelled | > 7 days OR diff fingerprint | -- | Create new ticket |
| None | -- | -- | Create new ticket |

### Ticket Title Format

`[gap:<fingerprint[:8]>] <category>: <seam_id_suffix>`

Example: `[gap:a3f2c891] CONTRACT_DRIFT: pattern-learned.v1`

### Report Artifacts

```
~/.claude/gap-analysis/{epic_id}/{run_id}.json   # Full report (ModelGapAnalysisReport)
~/.claude/gap-analysis/{epic_id}/{run_id}.md     # Human-readable summary
```

### DB Boundary Rules

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

### Scan Roots (Prevent False Positives)

| Repo type | Scan | Skip |
|-----------|------|------|
| Python (`src/` layout) | `src/**` | `tests/**`, `fixtures/**`, `docs/**` |
| TypeScript | `client/**`, `server/**`, `src/**` | `__tests__/**`, `*.test.ts`, `fixtures/**` |
| Generated code | -- | Always skip |

### Suppressions

Format: `skills/gap/suppressions.yaml`

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

---

## Subcommand: fix

Absorbed from: gap-fix (v0.1.0)

### Overview

Automates the "detected to fixed" loop that detect opens but leaves manual. Reads a
gap-analysis report, classifies findings by auto-dispatch eligibility, dispatches
`ticket-pipeline` for safe-only findings, then calls `merge-sweep --prs` on the created PRs.

**Scope (v0 -- narrow)**: Only auto-dispatch findings with a single deterministic resolution.
Anything multi-option emits a decision gate and waits for human input.

### Entry Points

```
/gap fix --report <run_path>   # e.g., multi-epic-2026-02-23/run-001
/gap fix --ticket OMN-XXXX     # single finding via marker block
/gap fix --latest              # follows ~/.claude/gap-analysis/latest/
/gap fix --dry-run             # classify and print plan, no side effects
```

| Arg | Default | Description |
|-----|---------|-------------|
| `--report <run_path>` | none | Gap-analysis run path under `~/.claude/gap-analysis/` |
| `--ticket <id>` | none | Single finding via Linear ticket containing a marker block |
| `--latest` | false | Follow `~/.claude/gap-analysis/latest/` symlink |
| `--dry-run` | false | Zero side effects: no ledger, no Linear writes, no PR mutations |
| `--mode <mode>` | `ticket-pipeline` | `ticket-pipeline` \| `ticket-work` \| `implement-only` |
| `--choose <decisions>` | none | `GAP-id=A,GAP-id=B` -- provide choices for gated findings |
| `--force-decide` | false | Re-open previously decided findings in decisions.json |

### Phases

```
Phase 0: Parse + normalize report -> ModelGapFinding[]
Phase 1: Classify findings by auto-dispatch eligibility
Phase 2: Decision gate -- emit choices block for non-auto findings; skip undecided; continue with auto
Phase 3: Execute fix -- dispatch ticket-pipeline per auto finding
          -> emit gap-fix-output.json with prs_created[]
          -> call: merge-sweep --prs <path>  (NOT --repos -- scoped to new PRs only)
Phase 4: Re-probe -- minimal grep/AST per boundary_kind before marking fixed
Phase 5: Report -- append fix section to .md artifact; update decisions ledger
```

### Auto-Dispatch vs Gate Table

| `boundary_kind` | `rule_name` | Auto-dispatch? |
|-----------------|-------------|----------------|
| `kafka_topic` | `topic_name_mismatch` | YES |
| `db_url_drift` | `legacy_db_name_in_tests` | YES |
| `db_url_drift` | `legacy_env_var` | YES |
| `topic_registry` | `topic_registry_missing_member` | YES (LOCAL-ONLY: adds enum member to local TopicRegistry only) |
| `legacy_config` | `legacy_denylist_match` | YES (search-replace from denylist) |
| `branch_protection` | `required_check_name_stale` | YES (removes stale checks via `gh api`; gate if no valid checks remain) |
| `kafka_topic` | `producer_only_no_consumer` | NO -- gate |
| `api_contract` | `missing_openapi` | NO -- gate |
| `env_activation` | `env_var_not_activated` | NO -- gate |
| `projection_lag` | `consumer_group_lag_exceeded` | NO -- gate |
| `auth_config` | `auth_client_config_drift` | NO -- gate |
| `migration_parity` | `migration_head_mismatch` | NO -- gate |
| `db_boundary` | `upstream_db_access` | NO -- gate |
| Any `BEST_EFFORT` with multiple resolutions | -- | NO -- gate |

### Key Invariants

- Re-probe **must pass** before marking a finding `fixed`
- `merge-sweep` always called with `--prs` (not `--repos`) -- only touches created PRs
- `--dry-run` produces zero side effects: no ledger writes, no Linear writes, no PR mutations
- `decisions.json` is write-once per finding; `--force-decide` to re-open
- `blocked_external` guard: if `merge-sweep` returns `blocked_external > 0`, log a warning
  and do NOT retry -- these are external infra failures (deploy locks, CI secrets), not skill bugs

### Modes

| Mode | Description |
|------|-------------|
| `ticket-pipeline` | Default -- dispatches `ticket-pipeline` per auto finding; calls `merge-sweep --prs` on created PRs |
| `ticket-work` | Dispatches `ticket-work` only (no PR creation or merge) |
| `implement-only` | No ticket-pipeline or ticket-work; implements fixes directly in worktree |

### Artifacts

`~/.claude/gap-analysis/<source_run_id>/gap-fix-output.json`:

```json
{
  "prs_created": [
    { "repo": "org/repo", "number": 123, "url": "...", "finding_id": "GAP-a3f9c1d2" }
  ],
  "tickets": ["OMN-XXXX"]
}
```

`~/.claude/gap-analysis/<source_run_id>/decisions.json` -- persisted decisions so `--choose`
selections are not re-prompted on every run. `<source_run_id>` is the gap-analysis run
identifier (the original analysis run), NOT the fix run ID:

```json
{
  "GAP-b7e2d5f8": { "choice": "A", "chosen_at": "...", "by": "jonah" }
}
```

### ModelSkillResult

Written to `~/.claude/gap-analysis/<source_run_id>/gap-fix-result.json`:

```json
{
  "skill": "gap",
  "version": "1.0.0",
  "status": "complete | partial | nothing_to_fix | gate_pending | error",
  "run_id": "<run_id>",
  "findings_total": 12,
  "findings_auto": 5,
  "findings_gated": 4,
  "findings_skipped": 3,
  "prs_created": 5,
  "prs_merged": 4,
  "findings_fixed": 4,
  "findings_still_open": 1,
  "gate_pending": ["GAP-b7e2d5f8", "GAP-c3a1e2d4"],
  "output_path": "~/.claude/gap-analysis/<source_run_id>/gap-fix-output.json"
}
```

Status values:
- `complete` -- all auto findings fixed, no gate_pending
- `partial` -- some findings fixed, some failed or gated
- `nothing_to_fix` -- no auto-dispatchable findings found
- `gate_pending` -- gated findings emitted; awaiting human `--choose`
- `error` -- unrecoverable error

### Sub-skills Used

- `ticket-pipeline` (existing) -- creates PR from finding (default mode)
- `merge-sweep` -- merges the created PRs (called with `--prs`, not `--repos`)

---

## Subcommand: cycle

Absorbed from: gap-cycle (v0.1.0)

### Overview

Orchestrates the full gap investigation loop: detect -> fix -> verify.
Single entry point replacing manual sub-skill chaining.

### CLI Examples

```
# Minimal: detect + fix (default)
/gap cycle --epic OMN-XXXX

# Detect only (no fix)
/gap cycle --epic OMN-XXXX --no-fix

# Detect + fix + single routing verify
/gap cycle --epic OMN-XXXX --verify

# Skip detect (use existing report)
/gap cycle --report ~/.claude/gap-analysis/OMN-XXXX/<run_id>.json

# Resume interrupted run
/gap cycle --resume ~/.claude/gap-cycle/OMN-XXXX/<run_id>/summary.json

# Dry run (no external writes, local files written)
/gap cycle --epic OMN-XXXX --dry-run
```

### Artifact Chaining

The cycle subcommand requires stdout markers from sub-phases. If a marker is absent,
it emits a hard error -- it does NOT reconstruct paths from naming conventions or check
fallback pointer files.

- **detect phase** must emit: `ARTIFACT: <absolute path>`
- **fix phase** must emit: `GAP_FIX_OUTPUT: <absolute path>`

### Output

Written to `~/.claude/gap-cycle/{epic_id}/{run_id}/summary.json`:

```json
{
  "epic_id": "OMN-XXXX",
  "run_id": "gap-cycle-2026-03-04T12:00:00Z",
  "source_report_path": "...",
  "phases_executed": {"detect": true, "audit": false, "fix": true, "verify": false},
  "phase_results": {"detect": null, "audit": null, "fix": null, "verify": null},
  "prs_created": [],
  "gated_findings_count": 0,
  "nothing_to_fix": false,
  "composite_status": "complete",
  "dry_run": false
}
```

### Status Values

- `complete`: All enabled phases ran AND gated_findings_count == 0 AND (verify not enabled OR verify passed). OR nothing_to_fix=true.
- `partial`: Some phases skipped by flags; OR verify not enabled; OR gated_findings_count > 0.
- `gate_pending`: --auto-only: all findings were gated, zero PRs created. Phase 4 skipped.
- `blocked`: Required prerequisite missing -- report not found, epic_id absent from report metadata.
- `error`: Exception or tool failure in any phase.

### v0.2 Roadmap

- pipeline-audit chaining (Phase 2 automation)
- sidecar audit annotation files (no schema mutation)
- per-repo-to-pipeline verification mapping

---

## Integration Test

Test suite: `tests/integration/skills/gap_fix/test_gap_fix_integration.py`

All tests use `@pytest.mark.unit` -- static analysis of skill files, no external services required.

| Test Case | Class | What it verifies |
|---|---|---|
| 1 | `TestDryRunContract` | `--dry-run` produces zero side effects |
| 2 | `TestFixedRequiresProof` | `fixed` status requires probe block with all 5 fields |
| 3 | `TestInfraBoundaryGate` | DB import in UI repo classified as `GATE` |
| 4 | `TestPositiveRouting` | merge-sweep called with `--prs` |
| 5 | `TestDecisionsJsonAppendOnly` | `decisions.json` is write-once per fingerprint |
| 6 | `TestForcedDecideVersioning` | `--force-decide` re-opens prior decisions |
| 7 | `TestPrQueuePipelineInvocation` | `merge-sweep` always invoked with `--prs` |

```bash
uv run pytest tests/integration/skills/gap_fix/test_gap_fix_integration.py -v
```

---

## Subcommand: reconcile

Absorbed from the former `reconcile-artifacts` skill.

Triggers artifact reconciliation for a target repository by dispatching a
`ModelManualReconcileCommand` to the `onex.cmd.artifact.reconcile.v1` Kafka topic via the
`omni-infra` CLI.

### CLI Examples

```
/gap reconcile --repo omnibase_infra
/gap reconcile --repo omnibase_core --reason "Post-deploy artifact drift detected"
```

| Arg | Default | Description |
|-----|---------|-------------|
| `--repo` | required | Target repo name (e.g., omnibase_infra) |
| `--reason` | `"Manual reconciliation via omniclaude skill"` | Human-readable reason |

### Behavior

1. Sources `~/.omnibase/.env` to load `KAFKA_BOOTSTRAP_SERVERS`
2. Verifies `omni-infra` CLI is available (falls back to `uv run omni-infra`)
3. Runs `omni-infra artifact-reconcile --repo <repo> --reason "<reason>"`
4. Returns exit code, stdout, and stderr

Uses `KAFKA_BOOTSTRAP_SERVERS` if set, otherwise defaults to `localhost:19092`.
If broker is unreachable, exits non-zero with error message.

---

## See Also

- `pipeline-audit` skill (comprehensive end-to-end pipeline verification)
- `systematic-debugging` skill (debugging a single known failure; see Phase 1 Backward Tracing)
- `create-ticket` skill (ticket creation patterns)
- `skills/gap/suppressions.yaml` (suppression registry)
- `skills/gap/legacy-denylist.yaml` (legacy config patterns for probe 2.11)
- `skills/gap/models/` (local Pydantic models)
- `skills/gap/docs/FAILURE_TAXONOMY.md` (11 failure class reference)
- `skills/gap/docs/POST_MERGE_STABILIZATION.md` (6-step post-merge workflow)
- `~/.claude/gap-analysis/` (report output directory)
- `~/.claude/gap-cycle/` (cycle summary output directory)
