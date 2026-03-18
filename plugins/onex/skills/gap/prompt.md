<!-- persona: plugins/onex/skills/_lib/assistant-profile/persona.md -->
<!-- persona-scope: this-skill-only -- do not re-apply if polymorphic agent wraps this skill -->
Apply the persona profile above when generating outputs.

# Gap Skill Orchestration

You are executing the unified gap skill. This prompt defines the complete orchestration
logic for all three subcommands: detect, fix, and cycle.

---

## Subcommand Routing

Parse the first positional argument from `$ARGUMENTS` as the subcommand:

| Subcommand | Description |
|-----------|-------------|
| `detect` | Cross-repo integration health audit |
| `fix` | Auto-fix loop for gap-analysis findings |
| `cycle` | Full detect->fix->verify loop |

If no subcommand is provided, emit error: `[gap] ERROR: subcommand required. Use: detect, fix, or cycle`

Route to the corresponding section below.

---
---

# SUBCOMMAND: detect

Absorbed from: gap-analysis (v1.0.0)

## Step 0: Parse Arguments <!-- ai-slop-ok: skill-step-heading -->

Parse from `$ARGUMENTS` (after stripping the `detect` subcommand):

| Argument | Default | Description |
|----------|---------|-------------|
| `--epic <id>` | none | Single Linear Epic ID to audit |
| `--repo <name>` | all | Limit probes to one canonical repo |
| `--since-days <n>` | 30 | Days to look back for closed Epics |
| `--severity-threshold` | WARNING | `WARNING` or `CRITICAL` |
| `--max-findings <n>` | 200 | Cap on total findings (DETERMINISTIC) |
| `--max-best-effort <n>` | 50 | Cap on BEST_EFFORT findings |
| `--dry-run` | false | Skip ticket creation/commenting |
| `--output <fmt>` | md | `json` or `md` |

Generate a `run_id` = first 12 chars of a UUID4.

---

## Phase 1 -- Intake

### 1.1 Fetch Epic(s) from Linear

If `--epic` provided:
```
mcp__linear-server__get_issue(id=epic_id, includeRelations=true)
```

If `--epic` not provided:
```
mcp__linear-server__list_issues(
    state="Done",
    updatedAt="-P{since_days}D",
    parentId=null   # top-level only
)
```

Filter to issues where `identifier` starts with the org prefix and is a parent Epic
(has children). Accept only state = Done | Cancelled | Duplicate.

### 1.2 Evidence Sources (in order)

For each Epic, collect repo evidence from:

1. **Linear relations** (highest confidence): `includeRelations=true` -> look for PR/branch
   URLs in `relatedIssues`, `attachments`, `documents`
2. **PR/commit URLs**: Extract repo name from GitHub URL pattern
   `github.com/{org}/{repo}/pull/...` or `github.com/{org}/{repo}/commit/...`
3. **branchName** (weak): Parse `{user}/{repo}-...` patterns
4. **Description text**: Grep for repo names matching KNOWN_REPOS

Emit per Epic:
- `repos_in_scope`: list of canonicalized repo names
- `evidence_used`: which evidence source produced each repo
- `rejected_repos`: repos found but rejected by canonicalization

### 1.3 Mandatory Repo Canonicalization

```python
ALIAS_MAP = {
    "omnibase": "omnibase_core",
    "core": "omnibase_core",
    "infra": "omnibase_infra",
    "intelligence": "omniintelligence",
    "claude": "omniclaude",
}

KNOWN_REPOS = [
    "omnibase_compat", "omniclaude", "omniintelligence", "omnibase_core", "omnibase_infra",
    "omnimemory", "omnidash", "omnidash2", "omniweb",
]

def canonicalize(raw: str) -> str | None:
    s = raw.lower().strip()
    s = re.sub(r'\d+$', '', s)          # strip trailing digits
    s = ALIAS_MAP.get(s, s)             # apply alias map
    if s in KNOWN_REPOS:
        return s
    return None                          # rejected
```

### 1.4 Empty Scope Guard

If `repos_in_scope` is empty after canonicalization:
```
status = "blocked"
blocked_reason = "NO_REPO_EVIDENCE"
```

Log a clear message: "No repo evidence found for Epic {epic_id} -- skipping probes."
Do NOT silently fail. Add to report and move on to next Epic.

---

## Phase 2 -- Probe

Run all 12 probe categories for each repo in `repos_in_scope`.
Apply `--repo` filter if provided.

### Scan Root Rules (Apply Before Any Probe)

| Repo layout | Scan roots | Always skip |
|-------------|------------|-------------|
| Python `src/` layout | `src/**` | `tests/**`, `fixtures/**`, `docs/**`, `*.pyi` stubs |
| TypeScript | `client/**`, `server/**`, `src/**` | `__tests__/**`, `*.test.ts`, `*.spec.ts`, `fixtures/**` |
| Generated | -- | Entire directory (check for `# GENERATED` header or `codegen/` path) |

### 2.1 Probe: Kafka Topic Drift

**Category**: `CONTRACT_DRIFT` | **boundary_kind**: `kafka_topic`
**rule_name**: `topic_name_mismatch`

**Method (DETERMINISTIC first)**:
1. Find `TopicRegistry` or `TopicBase` enum in `src/**` (AST parse class bodies)
2. Extract all `str` enum values -> these are the canonical topic strings
3. Find all produce/emit calls referencing those constants
4. Find all consume/subscribe calls
5. Compare: producer topic string vs consumer topic string (byte-for-byte)

**Grep fallback (BEST_EFFORT)**:
- `grep -r "subscribe\|consume\|produce\|emit" src/` for topic string literals
- Confidence = `BEST_EFFORT`, severity capped at `WARNING`

**Kafka proof blob** must contain:
```json
{
  "expected_topic": "onex.evt.omniclaude.prompt-submitted.v1",
  "observed_topic": "onex.evt.omniclaude.prompt_submitted.v1",
  "producer_location": "src/omniclaude/publisher/emit.py:45",
  "consumer_location": "src/omniintelligence/consumers/claude.py:12"
}
```

Note: Fingerprint uses `seam_id_suffix` = topic string suffix only (after last `.v` version
marker stripped, then take the base name). Example: `prompt-submitted` from
`onex.evt.omniclaude.prompt-submitted.v1`.

### 2.2 Probe: Model Type Mismatch

**Category**: `CONTRACT_DRIFT` | **boundary_kind**: `model_field`
**rule_name**: `field_type_drift`

**Method**:
1. AST introspect Pydantic model classes (DETERMINISTIC if importable)
2. For fields shared between producer and consumer models, compare types
3. If model not importable (different repo, no common package): downgrade to BEST_EFFORT

**Confidence**: DETERMINISTIC if AST parse succeeds; BEST_EFFORT if grep-only.

### 2.3 Probe: FK Reference Drift

**Category**: `CONTRACT_DRIFT` | **boundary_kind**: `fk_reference`
**rule_name**: `fk_target_missing`

**Method**:
1. Read `schema.json` manifest from repo root (if present)
2. Parse FK references -> check target tables exist in all dependent repos
3. If `schema.json` absent: `confidence = SKIP`, add to `skipped_probes`, emit NO findings

**Confidence**: DETERMINISTIC if `schema.json` present; SKIP otherwise.

### 2.4 Probe: API Contract Drift

**Category**: `CONTRACT_DRIFT` | **boundary_kind**: `api_contract`
**rule_name**: `openapi_hash_mismatch`

**Method**:
1. Find `openapi.json` or `openapi.yaml` in repo root or `docs/`
2. Compute SHA-256 of the file content
3. Compare hash with any consumer repo that imports from this API
4. If no OpenAPI file: `confidence = SKIP`, add to `skipped_probes`, emit NO findings

**Confidence**: DETERMINISTIC if OpenAPI file present; SKIP otherwise.

### 2.5 Probe: DB Boundary Violation

**Category**: `ARCHITECTURE_VIOLATION` | **boundary_kind**: `db_boundary`
**rule_name**: `upstream_db_access`

**Method (ALWAYS DETERMINISTIC -- never BEST_EFFORT)**:
1. AST parse import statements in scan roots for DB driver imports:
   `psycopg2`, `asyncpg`, `sqlalchemy`, `tortoise`, `databases`, `aiopg`
2. Scan for DB URL env var patterns: `POSTGRES_*`, `PG*`, `DB_*`, `DATABASE_URL`,
   `DATABASE_DSN`, `OMNI*_DB_URL`, `DRIZZLE_*`, `.*_DATABASE_.*`
3. For repos in `no_upstream_db_repos`: any DB import/env var = CRITICAL finding
4. Grep fallback is acceptable for non-DB probes but NOT for this probe.
   If AST parse fails -> SKIP (never BEST_EFFORT for DB boundary)

**Severity**: CRITICAL for `no_upstream_db_repos` violation; WARNING otherwise.

### 2.6 Probe: Topic Registry Drift

**Category**: `CONTRACT_DRIFT` | **boundary_kind**: `topic_registry`
**rule_name**: `topic_registry_missing_member`

**Method**:
1. Load contract YAML files from each repo's `src/**/contracts/` directories
2. Extract all declared Kafka topic strings from contract `topics` fields
3. Find the local `TopicRegistry` or `TopicBase` enum (AST parse)
4. Compare: every contract-declared topic must have a corresponding enum member
5. Optionally query the broker (`rpk topic list`) to confirm topic exists on the bus

**Confidence**: DETERMINISTIC if both contract YAML and enum are found; SKIP if either is absent.

**Auto-fix**: LOCAL-ONLY. The skill can add the missing enum member to the local `TopicRegistry`.
It cannot create the topic on the broker or modify remote repos.

**Proof blob schema**:
```json
{
  "expected_topic": "onex.evt.omniclaude.gate-decision.v1",
  "source": "src/omniclaude/hooks/contracts/gate_decision.yaml",
  "broker_queried": true
}
```

**Fingerprint** `seam_id_suffix`: the topic string suffix (after last `.v` version marker stripped, then base name).

### 2.7 Probe: Env Activation Drift

**Category**: `ARCHITECTURE_VIOLATION` | **boundary_kind**: `env_activation`
**rule_name**: `env_var_not_activated`

**Method**:
1. Load contract YAML files and extract `config.required_env` fields
2. For each required env var, check if it is present in:
   a. `~/.omnibase/.env` (primary source of truth)
   b. Infisical (if `INFISICAL_ADDR` is set)
3. If a required env var is absent from all sources: emit finding

**Confidence**: DETERMINISTIC (contract declares the requirement; env is inspectable).

**Severity**: CRITICAL (missing env var causes runtime crash on node startup).

**Proof blob schema**:
```json
{
  "env_var": "KAFKA_BOOTSTRAP_SERVERS",
  "contract_path": "src/omnibase_infra/nodes/node_kafka_effect/contract.yaml",
  "node_name": "NodeKafkaEffect"
}
```

**Fingerprint** `seam_id_suffix`: the env var name.

### 2.8 Probe: Projection Lag

**Category**: `ARCHITECTURE_VIOLATION` | **boundary_kind**: `projection_lag`
**rule_name**: `consumer_group_lag_exceeded`

**Method**:
1. Query Redpanda/Kafka for consumer group lag via `rpk group describe <group>`
2. For each partition, compare current lag against `--lag-threshold` (default: 10000)
3. If lag exceeds threshold: emit finding

**Confidence**: DETERMINISTIC if broker is reachable; SKIP if broker unreachable.

**Severity**: WARNING by default. Upgrade to CRITICAL if lag exceeds 10x the threshold.

**Proof blob schema**:
```json
{
  "consumer_group": "omniintelligence-intent-classifier",
  "topic": "onex.cmd.omniintelligence.claude-hook-event.v1",
  "partition": 0,
  "lag": 15234,
  "threshold": 10000
}
```

**Fingerprint** `seam_id_suffix`: `{consumer_group}/{topic}`.

### 2.9 Probe: Auth Config Drift

**Category**: `CONTRACT_DRIFT` | **boundary_kind**: `auth_config`
**rule_name**: `auth_client_config_drift`

**Method**:
1. Load expected auth configuration from contract YAMLs (Infisical client IDs, service identity fields)
2. Query Infisical or local config for actual values
3. Compare: if any drift field differs between expected and actual, emit finding

**Confidence**: DETERMINISTIC if Infisical is reachable and contract declares auth fields; SKIP otherwise.

**Severity**: CRITICAL (auth drift can cause service authentication failures).

**Proof blob schema**:
```json
{
  "client_id": "omnibase-infra-runtime",
  "drift_fields": ["client_secret_hash", "project_id"],
  "expected": {"project_id": "proj-abc123"},
  "actual": {"project_id": "proj-def456"}
}
```

**Fingerprint** `seam_id_suffix`: the `client_id`.

### 2.10 Probe: Migration Parity

**Category**: `ARCHITECTURE_VIOLATION` | **boundary_kind**: `migration_parity`
**rule_name**: `migration_head_mismatch`

**Method**:
1. For each repo with Alembic migrations, run `alembic heads` (or check `alembic/versions/`)
2. Compare the migration head revision against the expected head declared in a release manifest or the last known-good state
3. If the head does not match: emit finding
4. If Alembic is not present or check command fails: SKIP

**Confidence**: DETERMINISTIC if Alembic is present and check command succeeds; SKIP otherwise.

**Severity**: WARNING.

**Proof blob schema**:
```json
{
  "repo": "omnibase_infra",
  "check_command": "alembic heads",
  "exit_code": 0,
  "stderr": ""
}
```

**Fingerprint** `seam_id_suffix`: the repo name.

### 2.11 Probe: Legacy Config Patterns

**Category**: `ARCHITECTURE_VIOLATION` | **boundary_kind**: `legacy_config`
**rule_name**: `legacy_denylist_match`

**Method**:
1. Load `skills/gap/legacy-denylist.yaml` -- contains patterns with reasons and replacement hints
2. For each pattern, grep across all repos in scope (respecting scan root rules)
3. For each match: emit finding with file path, line number, and the denylist reason

**Confidence**: DETERMINISTIC (literal string match).

**Auto-fix**: YES (search-replace). The skill can apply the replacement hint from the denylist
entry as a deterministic search-and-replace operation.

**Severity**: WARNING.

**Proof blob schema**:
```json
{
  "pattern": "OLLAMA_BASE_URL",
  "file_path": "src/omnibase_infra/config/settings.py",
  "line_number": 42,
  "reason": "Ollama endpoint decommissioned; use LLM_CODER_URL, LLM_EMBEDDING_URL, or LLM_DEEPSEEK_R1_URL"
}
```

**Fingerprint** `seam_id_suffix`: the pattern string.

### 2.12 Probe: Branch Protection Drift

**Category**: `INTEGRATION_HEALTH` | **boundary_kind**: `branch_protection`
**rule_name**: `required_check_name_stale`

**Method**:
1. For each repo in `repos_in_scope`, query GitHub branch protection required status checks:
   ```bash
   gh api repos/{ORG}/{repo}/branches/main/protection/required_status_checks --jq ".contexts"
   ```
2. Get actual check names from the most recent PR:
   ```bash
   gh pr list --repo {ORG}/{repo} --state all --limit 1 --json number
   gh pr checks {pr_number} --repo {ORG}/{repo}
   ```
3. Parse check names from the `gh pr checks` output (tab-delimited, first column is the check name)
4. Compare: any required check name that does not appear in the actual check names = drift
5. If branch protection API returns 404 (no protection configured): no finding (skip)
6. If no PRs exist to compare against: `confidence = SKIP`, add to `skipped_probes`

**Confidence**: DETERMINISTIC if both branch protection and recent PR checks are available; SKIP if either is absent.

**Severity**: CRITICAL (stale required checks silently block all merges).

**Auto-fix**: YES (gh api). Remove stale check names from the required checks list via:
```bash
gh api -X PATCH repos/{ORG}/{repo}/branches/main/protection/required_status_checks \
  --input - <<< '{"strict": true, "contexts": [<valid_checks>]}'
```
Only removes stale checks; keeps all valid checks intact. If no valid checks remain after
removing stale ones, do NOT apply the fix (requires manual intervention).

**Proof blob schema**:
```json
{
  "repo": "omniweb",
  "branch": "main",
  "required_checks": ["Quality Gate", "Tests Gate", "Security Gate"],
  "actual_checks": ["Quality Gate", "Security Gate"],
  "stale_checks": ["Tests Gate"],
  "valid_checks": ["Quality Gate", "Security Gate"]
}
```

**Fingerprint** `seam_id_suffix`: `{repo}/main` (the repo and protected branch).

**Reference implementation**: `omni_home/scripts/audit-branch-protection.py`

### 2.13 Apply Suppressions

After collecting all raw findings:

1. Load `skills/gap/suppressions.yaml`
2. For each finding, check suppressions in precedence order: `fingerprint` > `path_glob`
3. If matched AND not expired: suppress (remove from findings, do not log)
4. If matched AND expired: do NOT suppress, add fingerprint to `expired_suppressions_warned`
5. Emit warning: "Suppression for {fingerprint[:8]} expired on {expires}. Finding NOT suppressed."

### 2.14 Fingerprint Computation

```python
import hashlib, json

def compute_fingerprint(
    category: str,
    boundary_kind: str,
    rule_name: str,
    repos: list[str],
    seam_id_suffix: str,
    mismatch_shape: str,
    repo_relative_path: str,
) -> str:
    parts = "|".join([
        category,
        boundary_kind,
        rule_name,
        json.dumps(sorted(repos)),
        seam_id_suffix,
        mismatch_shape,
        repo_relative_path,
    ])
    return hashlib.sha256(parts.encode()).hexdigest()
```

No timestamps, run IDs, or line numbers. Stable across runs.

### 2.15 Severity and Best-Effort Caps

After suppressions:
1. Apply `--severity-threshold` filter (drop findings below threshold)
2. Cap BEST_EFFORT findings at `--max-best-effort` (default 50)
   - If exceeded: log "BEST_EFFORT findings capped at {max_best_effort}. {N} dropped."
3. Cap total findings at `--max-findings` (default 200)
   - If exceeded: log "Total findings capped at {max_findings}. {N} dropped."
4. **Hard rule**: Any finding with `confidence = BEST_EFFORT` must have `severity = WARNING`.
   If a finding would be CRITICAL with BEST_EFFORT confidence: downgrade to WARNING automatically.

---

## Phase 3 -- Report

### 3.1 Dedup Against Linear Tickets

For each finding, search Linear for existing tickets matching the fingerprint:

```
mcp__linear-server__list_issues(
    query="[gap:{fingerprint[:8]}]",
    team=team_id
)
```

Apply dedup table:

| Existing state | Last closed | Fingerprint match | Action |
|----------------|-------------|-------------------|--------|
| In Progress / Backlog / Todo | -- | -- | Comment only, skip creation |
| Done / Duplicate / Cancelled | <= 7 days | Same | Comment only, skip creation |
| Done / Duplicate / Cancelled | > 7 days OR diff fingerprint | -- | Create new ticket |
| None found | -- | -- | Create new ticket |

### 3.2 Ticket Title Format

`[gap:{fingerprint[:8]}] {category}: {seam_id_suffix}`

Example: `[gap:a3f2c891] CONTRACT_DRIFT: pattern-learned.v1`

### 3.3 Stable Marker Block

Every created or commented ticket description must include:

```
<!-- gap-analysis-marker
fingerprint: {fingerprint}
gap_category: {category}
boundary_kind: {boundary_kind}
rule_name: {rule_name}
seam: {seam_id}
repos: {json.dumps(sorted(repos))}
confidence: {confidence}
evidence_method: {evidence_method}
detected_at: {datetime.utcnow().isoformat()}Z
-->
```

Place the marker block at the end of the description (after human-readable content).

### 3.4 Ticket Description Template

```markdown
## Summary

{category} drift detected between {repos} at boundary `{seam_id}`.

**Confidence**: {confidence}
**Evidence method**: {evidence_method}
**Severity**: {severity}

## Evidence

{proof blob as formatted YAML or JSON}

## Proposed Fix

{rule-specific suggested fix}

## Definition of Done
- [ ] {category}-specific fix applied
- [ ] Integration test added or updated
- [ ] Gap-analysis re-run shows 0 findings for this fingerprint

{marker_block}
```

### 3.5 Ticket Creation / Commenting

If NOT `--dry-run`:

**Create new ticket**:
```
mcp__linear-server__create_issue(
    title="[gap:{fp[:8]}] {category}: {seam_id_suffix}",
    team=team_id,
    description=ticket_description,
    labels=["gap-analysis"],
    priority=2 if severity=="CRITICAL" else 3,
)
```

**Comment on existing ticket**:
```
mcp__linear-server__create_comment(
    issueId=existing_ticket_id,
    body="## Re-detected on {run_date}\n\n{marker_block}\n\nThis gap was re-detected in run `{run_id}`."
)
```

If `--dry-run`: log what would be created/commented, but make no API calls.

### 3.6 Report Persistence

Write two artifacts:

**JSON** (`~/.claude/gap-analysis/{epic_id}/{run_id}.json`):
```python
import json, pathlib
out_dir = pathlib.Path.home() / ".claude" / "gap-analysis" / (epic_id or "global")
out_dir.mkdir(parents=True, exist_ok=True)
(out_dir / f"{run_id}.json").write_text(report.model_dump_json(indent=2))
```

**Markdown** (`~/.claude/gap-analysis/{epic_id}/{run_id}.md`):
```markdown
# Gap Analysis Report -- {epic_id or "global"} -- {run_date}

Run ID: {run_id}
Repos in scope: {repos_in_scope}
Evidence sources: {evidence_used}
Rejected repos: {rejected_repos}

## Findings ({len(findings)} DETERMINISTIC + {len(best_effort_findings)} BEST_EFFORT)

{severity-ordered table of all findings}

## Skipped Probes

{skipped_probes list}

## Expired Suppressions Warned

{expired_suppressions_warned list}

## Tickets Created

{tickets_created list}

## Tickets Commented

{tickets_commented list}
```

---

## Dry-Run Behavior (detect)

When `--dry-run`:
1. Phases 1 and 2 run fully (probes execute, findings computed)
2. Phase 3 dedup runs (Linear searched for existing tickets)
3. No `create_issue` or `create_comment` calls
4. Report artifacts ARE written (so you can inspect findings)
5. Log prefix: `[DRY-RUN]` on all ticket operations

---

## Idempotency Test

Running `/gap detect --epic {id}` twice on the same Epic must produce 0 new tickets on
the second run (assuming no new code changes). Verify:

1. First run: N tickets created, N fingerprints logged
2. Second run: same fingerprints found -> all hit the "Comment only, skip creation" path
3. Result: 0 new tickets, N comments added to existing tickets

This is the primary idempotency invariant.

---

## Output Summary (detect)

After completing all phases, print a summary:

```
Gap Analysis Complete
---
Epics audited: {N}
Repos probed: {repos_in_scope}
Findings (DETERMINISTIC): {len(findings)}
Findings (BEST_EFFORT): {len(best_effort_findings)}
Skipped probes: {len(skipped_probes)}
Expired suppressions warned: {len(expired_suppressions_warned)}
Tickets created: {len(tickets_created)}
Tickets commented: {len(tickets_commented)}
Blocked epics: {N_blocked} (NO_REPO_EVIDENCE)

Report: ~/.claude/gap-analysis/{epic_id}/{run_id}.md
```

After writing the report files, emit this exact line to stdout as the FINAL LINE on ALL normal exit paths -- including early exits such as zero findings:

ARTIFACT: {full absolute path to the .json report, e.g. /Users/jonah/.claude/gap-analysis/{epic_id}/{run_id}.json} <!-- local-path-ok -->

If the skill exits early (zero findings, dry-run short-circuit, or any other normal completion), it must still emit this marker before exiting. Abnormal exits (exceptions) are excluded.

---
---

# SUBCOMMAND: fix

Absorbed from: gap-fix (v0.1.0)

## Step 0: Parse Arguments <!-- ai-slop-ok: skill-step-heading -->

Parse from `$ARGUMENTS` (after stripping the `fix` subcommand):

| Argument | Default | Description |
|----------|---------|-------------|
| `--report <run_path>` | none | Gap-analysis run path under `~/.claude/gap-analysis/` |
| `--ticket <id>` | none | Single finding via Linear ticket containing a marker block |
| `--latest` | false | Follow `~/.claude/gap-analysis/latest/` |
| `--dry-run` | false | Zero side effects |
| `--mode <mode>` | `ticket-pipeline` | `ticket-pipeline` \| `ticket-work` \| `implement-only` |
| `--choose <decisions>` | none | `GAP-id=A,GAP-id=B` to provide choices for gated findings |
| `--force-decide` | false | Re-open previously decided findings |

**Entry point resolution** (exactly one must resolve):
1. If `--ticket`: load finding from Linear ticket marker block -> synthetic one-finding report
2. If `--report <run_path>`: list `~/.claude/gap-analysis/<run_path>/` -> load the `.json` file
   (there must be exactly one; error if zero or multiple)
3. If `--latest`: resolve `~/.claude/gap-analysis/latest/` symlink -> load its `.json` report
4. If none provided: resolve `~/.claude/gap-analysis/latest/` (same as `--latest`)

Generate a `fix_run_id` = first 12 chars of a UUID4.

---

## Phase 0: Parse and Normalize Report

### 0.1 Load the Report

Load `ModelGapAnalysisReport` from the resolved JSON file.

Extract `findings: list[ModelGapFinding]`. Each finding has:
- `finding_id`: SHA-256 fingerprint (8-char prefix used as display ID)
- `boundary_kind`: `kafka_topic` | `db_url_drift` | `api_contract` | `model_type` | `fk_reference`
- `rule_name`: specific rule (e.g., `topic_name_mismatch`, `legacy_db_name_in_tests`)
- `confidence`: `DETERMINISTIC` | `BEST_EFFORT` | `SKIP`
- `severity`: `CRITICAL` | `WARNING`
- `repos`: list of affected repos
- `seam_id`: the integration seam identifier
- `evidence`: dict of probe evidence
- `linear_ticket_id`: existing Linear ticket if already created

### 0.2 Load decisions.json

Load `~/.claude/gap-analysis/<source_run_id>/decisions.json` if it exists. This contains
previously resolved gate decisions. These are used to skip re-prompting on resume.

`<source_run_id>` is the run ID of the original gap-analysis report -- extracted from the
resolved report path, NOT the newly-generated `fix_run_id`. This ensures decisions are
co-located with the source analysis run, not scattered under separate fix run directories.

```json
{
  "GAP-b7e2d5f8": { "choice": "A", "chosen_at": "...", "by": "jonah" }
}
```

If `--force-decide` is set: treat all prior decisions as absent (re-open them).

### 0.3 Apply --choose Decisions

Parse `--choose` argument: `GAP-b7e2d5f8=A,GAP-c3a1e2d4=B`

Merge into decisions map (new choices override prior decisions only if `--force-decide` is set;
otherwise skip silently if already decided).

---

## Phase 1: Classify Findings

For each finding, determine `dispatch_class`:

### Auto-Dispatch Table

| `boundary_kind` | `rule_name` | `dispatch_class` |
|-----------------|-------------|-----------------|
| `kafka_topic` | `topic_name_mismatch` | `AUTO` |
| `db_url_drift` | `legacy_db_name_in_tests` | `AUTO` |
| `db_url_drift` | `legacy_env_var` | `AUTO` |
| `legacy_config` | `legacy_denylist_match` | `AUTO` (search-replace from denylist) |
| `branch_protection` | `required_check_name_stale` | `AUTO` (removes stale checks via `gh api`; `GATE` if no valid checks remain) |
| `kafka_topic` | `producer_only_no_consumer` | `GATE` |
| `api_contract` | `missing_openapi` | `GATE` |
| Any `BEST_EFFORT` confidence with multiple resolutions | -- | `GATE` |
| All other cases not listed above | -- | `GATE` |

**Resolution count check**: A finding has "multiple resolutions" if its `evidence` dict contains
a `resolutions` list with `len > 1`. If `len == 1` and all other criteria are met for AUTO,
classify as AUTO.

**Already-decided gate findings**: If a finding is `GATE` but has an entry in `decisions.json`,
use the stored decision to convert it to `AUTO` with the chosen resolution.

Emit classification summary:
```
Phase 1 Classification:
  AUTO (5): GAP-a3f9c1d2 (kafka_topic/topic_name_mismatch), ...
  GATE (4): GAP-b7e2d5f8 (kafka_topic/producer_only_no_consumer), ...
  SKIP (3): already fixed / SKIP confidence
```

---

## Phase 2: Decision Gate

### 2.1 Emit Choices Block for GATE Findings

For each undecided `GATE` finding (not in decisions.json), emit a structured choices block:

```
DECISION REQUIRED -- GAP-b7e2d5f8
  boundary_kind: kafka_topic
  rule_name: producer_only_no_consumer
  repos: omniclaude, omniintelligence
  seam: agent.routing.requested.v1
  severity: WARNING
  evidence: producer found in omniclaude/hooks/lib/route_via_events_wrapper.py:1369
            no consumer found in any repo

  Options:
    A) Create consumer stub in omniintelligence (recommended)
    B) Add to suppressions.yaml (acknowledge as intentional)
    C) Skip this finding this run

  Provide choice via: /gap fix --choose GAP-b7e2d5f8=A [--report <same run_path>]
```

After emitting all choices blocks, **stop and return** with `status: gate_pending`.

If `--dry-run` is set: emit choices blocks as documentation only, do not write to decisions.json.

### 2.2 Auto Findings Continue

If there are AUTO findings AND undecided GATE findings exist simultaneously:
- Continue with AUTO findings only
- GATE findings are noted in the output as `gate_pending`
- Return `status: partial` (not `gate_pending`) since some work was done

---

## Phase 3: Execute Fix

### 3.1 Mode: ticket-pipeline (default)

For each AUTO finding:

1. **Check if Linear ticket already exists** (`finding.linear_ticket_id` non-null):
   - If yes, use existing ticket ID
   - If no, create a new ticket via `mcp__linear-server__create_issue`:
     ```
     title: "[gap-fix:<finding_id[:8]>] <boundary_kind>: <rule_name>"
     team: "Omninode"
     description: (see ticket template below)
     labels: ["gap-fix", "auto-dispatch"]
     priority: 2 (High) for CRITICAL, 3 (Normal) for WARNING
     ```

2. **Dispatch ticket-pipeline** per finding:
   ```
   Task(
     subagent_type="onex:polymorphic-agent",
     description="gap fix: Phase 3 fix for finding <finding_id> via ticket-pipeline",
     prompt="You are executing ticket-pipeline for <ticket_id>.
       Invoke: Skill(skill=\"onex:ticket-pipeline\", args=\"<ticket_id>\")
       Finding: <finding summary>
       Repo: <primary repo from finding.repos[0]>
       Report back with: pr_url, pr_number, status, any blockers."
   )
   ```

3. **Collect PR results** into `prs_created[]`:
   ```json
   { "repo": "OmniNode-ai/<repo>", "number": 123, "url": "...", "finding_id": "GAP-a3f9c1d2" }
   ```

4. **Write gap-fix-output.json** (append as PRs complete):
   ```json
   {
     "prs_created": [...],
     "tickets": ["OMN-XXXX", ...]
   }
   ```

### 3.2 Mode: ticket-work

Same as ticket-pipeline but dispatch `ticket-work` instead:
```
Task(
  subagent_type="onex:polymorphic-agent",
  description="gap fix: Phase 3 fix for finding <finding_id> via ticket-work",
  prompt="You are executing ticket-work for <ticket_id>.
    Invoke: Skill(skill=\"onex:ticket-work\", args=\"<ticket_id>\")
    Finding: <finding summary>
    Report back with: files_changed, tests_run, any blockers."
)
```
No PR creation step. Skip Phase 3.3.

### 3.3 Call merge-sweep (ticket-pipeline mode only)

After all ticket-pipeline dispatches complete, write `prs_created_path`:
```
~/.claude/gap-analysis/<source_run_id>/gap-fix-output.json
```

Invoke merge-sweep scoped to repos with created PRs:
```
Task(
  subagent_type="onex:polymorphic-agent",
  description="gap fix: Phase 3 merge-sweep for created PRs",
  prompt="Invoke: Skill(skill=\"onex:merge-sweep\",
    args=\"--repos <repos_with_created_prs>\")
    Report back with: status, auto_merge_set, polished, failed."
)
```

**Critical**: Always scope to repos that had PRs created, not all repos.

**Blocked-external guard**: If merge-sweep returns Track B `blocked` results, log a warning
and do NOT retry. These are infra failures (CI infrastructure down, deploy locks) -- do not loop.

### 3.4 Mode: implement-only

No ticket creation, no ticket-pipeline or ticket-work dispatch. Implement fixes directly:

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="gap fix: Phase 3 implement-only for finding <finding_id>",
  prompt="Implement the fix for gap-analysis finding <finding_id> directly.
    Finding: <full finding details>
    Repo: <repo> at <worktree path>
    boundary_kind: <kind>
    rule_name: <rule>
    Apply the fix, commit, and report back with: files_changed, commit_sha."
)
```

---

## Phase 4: Re-probe

Before marking any finding `fixed`, run a minimal re-probe to verify the fix.

### Probe Block Schema

Each re-probe execution produces a probe block that must be recorded. All five fields are
**required** before a finding may be marked `fixed`:

```json
{
  "command": "<shell command run to verify the fix>",
  "exit_code": 0,
  "stdout_sha256": "<sha256 of stdout output, for auditability>",
  "repo_head_sha": "<git HEAD SHA of the repo at probe time>",
  "ran_at": "<ISO-8601 timestamp>"
}
```

**`exit_code=0` is required** to mark a finding `fixed`. If `exit_code != 0` or if the probe
block is absent, the finding must be classified as `implemented_not_verified` (not `fixed`).

**`repo_head_sha` is required** to link the proof to a specific commit. This makes the proof
auditable -- if the commit is later reverted, the proof is invalidated.

### Marking Rules

| Probe result | Finding status |
|---|---|
| Probe block present, `exit_code=0`, `repo_head_sha` non-empty | `fixed` |
| Probe block absent OR `exit_code != 0` | `implemented_not_verified` |
| Re-probe command runs but finds legacy pattern still present | `still_open` |

### Re-probe by boundary_kind

| `boundary_kind` | Re-probe method |
|-----------------|-----------------|
| `kafka_topic` | grep for old topic name in affected repos -- must return zero matches |
| `db_url_drift` | grep for legacy DB name or env var in affected repos -- must return zero matches |
| `api_contract` | check that OpenAPI spec file now exists at expected path |
| `model_type` | grep for mismatched field type -- must return zero matches |
| `fk_reference` | grep for old FK target -- must return zero matches |

**Re-probe must pass before marking fixed.** If re-probe fails:
- Mark finding as `still_open` (not `fixed`)
- Log: `Re-probe failed for <finding_id>: <evidence>`
- Continue with remaining findings
- Include in `findings_still_open` in output

**Skip re-probe only for**:
- `--dry-run` mode
- `implement-only` mode (no PR yet to re-probe against)

---

## Phase 5: Report (fix)

### 5.1 Update decisions.json

For each `GATE` finding that was resolved via `--choose`, write to decisions.json:
```json
{
  "GAP-b7e2d5f8": {
    "choice": "A",
    "chosen_at": "<ISO timestamp>",
    "by": "gap-fix-skill"
  }
}
```

decisions.json is **write-once per finding**. Never overwrite an existing entry unless
`--force-decide` is set.

If `--dry-run`: do NOT write decisions.json.

### 5.2 Append Fix Section to Report .md

Append to the existing gap-analysis source report at `~/.claude/gap-analysis/<source_run_path>/<report>.md`
(the same `.md` produced by detect for this run -- not the fix_run_id):

```markdown
## Gap-Fix Run -- <fix_run_id>
Date: <ISO timestamp> | Mode: <mode> | Dry-run: <true|false>

### Fixed (<N> findings)
- GAP-a3f9c1d2 -- kafka_topic/topic_name_mismatch -- PR: OmniNode-ai/omniclaude#247
- GAP-c9f1e3b4 -- db_url_drift/legacy_db_name_in_tests -- PR: OmniNode-ai/omnibase_infra#403

### Gate Pending (<N> findings -- awaiting --choose)
- GAP-b7e2d5f8 -- kafka_topic/producer_only_no_consumer -- choices emitted above

### Still Open (<N> findings -- re-probe failed)
- GAP-d2a4f8c1 -- api_contract/missing_openapi -- re-probe failed: spec not found

### Skipped (<N> findings -- SKIP confidence or already fixed)
- GAP-e7b3d9a2 -- SKIP confidence: no OpenAPI spec present, cannot probe
```

### 5.3 Write ModelSkillResult

Write `~/.claude/gap-analysis/<source_run_id>/gap-fix-result.json`:

```json
{
  "skill": "gap",
  "version": "1.0.0",
  "status": "complete | partial | nothing_to_fix | gate_pending | error",
  "run_id": "<fix_run_id>",
  "source_run_id": "<gap_analysis_run_id>",
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

**Status resolution**:
- `complete` -- `findings_auto > 0`, all auto findings fixed, `gate_pending == []`
- `partial` -- some fixed, some failed or gated (gate_pending may or may not be empty)
- `nothing_to_fix` -- `findings_auto == 0` (all gated or skipped)
- `gate_pending` -- `findings_auto == 0` AND `findings_gated > 0` AND none were previously decided
- `error` -- unrecoverable error before any fixing occurred

---

## Linear Ticket Template (fix)

Used when creating new tickets for auto findings:

```markdown
## Summary

Auto-dispatch from gap-analysis finding <finding_id[:8]>.

**Finding**: `<boundary_kind>/<rule_name>`
**Seam**: `<seam_id>`
**Repos**: <comma-separated repos>
**Confidence**: <confidence>
**Severity**: <severity>

## Evidence

<finding.evidence rendered as YAML block>

## Fix

<auto-determined resolution -- one of:>
- kafka_topic/topic_name_mismatch: Update topic reference from `<old>` to `<new>` in <file>
- db_url_drift/legacy_db_name_in_tests: Replace `<legacy_name>` with `<canonical_name>` in tests
- db_url_drift/legacy_env_var: Replace `<legacy_var>` with `<canonical_var>` in <file>

## Definition of Done

- [ ] Fix applied and committed
- [ ] Re-probe passes: no legacy references found
- [ ] Tests pass
- [ ] PR merged

<!-- gap-analysis-marker
fingerprint: <finding_id>
boundary_kind: <boundary_kind>
rule_name: <rule_name>
seam: <seam_id>
repos: [<repos>]
confidence: <confidence>
gap_fix_run_id: <fix_run_id>
-->
```

---

## Error Handling (fix)

| Error | Behavior |
|-------|----------|
| Report file not found | Return `status: error`, log path tried |
| `findings` list empty | Return `status: nothing_to_fix` |
| All findings are GATE with no prior decisions | Return `status: gate_pending`, emit choices |
| ticket-pipeline dispatch fails for a finding | Mark finding `still_open`, continue with rest |
| merge-sweep returns Track B `blocked` results | Log warning, do NOT retry, mark as `partial` |
| Re-probe fails | Mark finding `still_open`, continue |
| decisions.json write fails | Log warning (non-blocking), continue |
| `--dry-run` | Never write decisions.json, never write gap-fix-output.json |

---

## --dry-run Invariant (fix)

When `--dry-run` is set, the following must produce ZERO side effects:
- No `decisions.json` writes
- No `gap-fix-output.json` writes
- No Linear ticket creation or mutation
- No PR creation, mutation, or merge
- No `ticket-pipeline` or `ticket-work` dispatch
- No `merge-sweep` invocation

The skill may still:
- Read report files
- Classify findings
- Emit choices blocks
- Print the plan

Log prefix for all output: `[DRY RUN]`

---

## Resuming from Gate Pending (fix)

After a human provides choices via `--choose`:

```
/gap fix --report <same run_path> --choose GAP-b7e2d5f8=A,GAP-c3a1e2d4=B
```

The skill:
1. Loads existing decisions.json
2. Merges new `--choose` decisions
3. Re-classifies findings (gate findings with decisions become AUTO)
4. Proceeds from Phase 3 for newly-decided findings only
5. Skips findings already marked `fixed` in prior run's result

**Idempotency**: Already-fixed findings (present in `prs_created[]`) are skipped on resume.

After writing gap-fix-output.json, emit this exact line to stdout as the FINAL LINE on ALL normal exit paths -- including early exits such as all findings gated or zero auto-dispatchable findings:

GAP_FIX_OUTPUT: {full absolute path to gap-fix-output.json, e.g. /Users/jonah/.claude/gap-analysis/{source_run_id}/gap-fix-output.json} <!-- local-path-ok -->

In `--dry-run` mode: still emit the path (no actual file written, but path is computed from source_run_id). If the skill exits early (all gated, zero eligible findings, dry-run, or any other normal completion), it must still emit this marker before exiting. Abnormal exits (exceptions) are excluded.

---
---

# SUBCOMMAND: cycle

Absorbed from: gap-cycle (v0.1.0)

## Phase 0 -- Intake

Parse flags from the invocation (after stripping the `cycle` subcommand):

1. **Mutual exclusion**: `--epic`, `--report`, `--resume` are XOR.
   If more than one is provided: emit error, stop.

2. **`--epic <id>`**: Set `epic_id`. Set `phases_executed.detect = true`.

3. **`--report <path>`**: Load the JSON file. Extract `epic_id` from
   `report.epic_id`. Hard error if field is absent or file unreadable.
   Set `phases_executed.detect = false`.
   Populate detect result immediately:
   ```json
   "phase_results": {
     "detect": {
       "status": "skipped",
       "artifact": "<report path>",
       "findings_count": <report.findings.length>
     }
   }
   ```
   Set `source_report_path = <report path>`.

4. **`--resume <path>`**: Load `summary.json`. Identify the first phase
   where `phase_results[phase] == null` AND `phases_executed[phase] == true`.
   Jump to that phase. Emit:
   `[gap cycle] Resuming from phase: {phase}`

5. **`--dry-run`**: Record flag. fix phase will receive `--dry-run`.
   golden-path-validate is suppressed entirely (`phases_executed.verify = false`).
   Local artifact files (report, gap-fix-output.json, summary.json) are still written.

6. Generate: `run_id = gap-cycle-{YYYY-MM-DDThh:mm:ss}Z` (UTC, Z suffix required).

7. Initialize `summary.json` structure in memory:
   ```json
   {
     "epic_id": null,
     "run_id": "gap-cycle-...Z",
     "source_report_path": null,
     "phases_executed": {"detect": true, "audit": false, "fix": true, "verify": false},
     "phase_results": {"detect": null, "audit": null, "fix": null, "verify": null},
     "prs_created": [],
     "gated_findings_count": 0,
     "nothing_to_fix": false,
     "composite_status": "error",
     "dry_run": false
   }
   ```
   Update `phases_executed` per flags:
   - `audit = true` if `--audit`
   - `fix = false` if `--no-fix`
   - `verify = true` if `--verify` AND NOT `--dry-run`
   - `dry_run = true` if `--dry-run`

---

## Phase 1 -- Detect (cycle)

**Skip if**: `--report` provided OR `--resume` past this phase.

1. Invoke detect subcommand internally:
   ```
   Execute: gap detect --epic {epic_id} [--dry-run if set]
   ```

2. **Require ARTIFACT marker**: scan the output for the last line
   matching `ARTIFACT: <path>`. If not found: emit hard error:
   `[gap cycle] ERROR: detect did not emit an ARTIFACT: marker. Cannot continue.`
   Stop.

3. Verify the path from the marker is a readable file. If not: emit:
   `[gap cycle] ERROR: ARTIFACT path is not readable: {path}. Cannot continue.`
   Stop.

4. Record:
   - `phase_results.detect.status = "complete"`
   - `phase_results.detect.artifact = {marker path}`
   - `phase_results.detect.findings_count = report.findings.length`
   - `source_report_path = {marker path}`

5. **Zero findings check**: if `findings_count == 0`:
   - Set `nothing_to_fix = true`
   - Set `composite_status = "complete"`
   - Write `summary.json` (see Rollup section)
   - Emit: `[gap cycle] Phase 1: zero findings. Status: complete.`
   - Exit.

6. Emit: `[gap cycle] Phase 1 complete: {N} findings across {K} repos`

---

## Phase 2 -- Audit Note (v0.1)

**Only if**: `--audit` flag set.

pipeline-audit chaining is deferred to v0.2. In v0.1:

- Record `phases_executed.audit = true`.
- Set `phase_results.audit = {"status": "deferred", "note": "pipeline-audit chaining not implemented in v0.1; run pipeline-audit separately then link artifacts manually"}`.
- Emit: `[gap cycle] Phase 2: pipeline-audit chaining deferred to v0.2. Run manually if needed.`
- Continue to Phase 3. Do NOT modify source_report_path.

---

## Phase 3 -- Fix (cycle)

**Skip if**: `--no-fix` flag set.

1. Invoke fix subcommand internally:
   ```
   Execute: gap fix --report {source_report_path} [--auto-only if set] [--dry-run if set]
   ```

2. **Require GAP_FIX_OUTPUT marker**: scan the output for the last line
   matching `GAP_FIX_OUTPUT: <path>`. If not found: emit hard error:
   `[gap cycle] ERROR: fix did not emit a GAP_FIX_OUTPUT: marker. Cannot continue.`
   Stop.

3. Verify the path from the marker is a readable file. If not: emit:
   `[gap cycle] ERROR: GAP_FIX_OUTPUT path is not readable: {path}. Cannot continue.`
   Stop.

4. Load `gap-fix-output.json`. Extract:
   - `prs_created`: list of `{repo, number, url}` objects
   - `gated_count`: count of findings still at GATE status

5. Record:
   - `phase_results.fix.status = "complete"`
   - `phase_results.fix.artifact = {gap-fix-output.json path}`
   - `phase_results.fix.prs_created_count = prs_created.length`
   - `phase_results.fix.gated_count = gated_count`
   - Update `prs_created` list in summary
   - Set `gated_findings_count = gated_count`

6. **--auto-only gate**: if `gated_count > 0` AND `prs_created.length == 0`:
   - Set `composite_status = "gate_pending"`
   - Set `phases_executed.verify = false`
   - Write `summary.json`
   - Emit: `[gap cycle] Phase 3: all findings gated. Status: gate_pending.`
   - Exit.

7. Emit: `[gap cycle] Phase 3 complete: {N} PRs created, {G} gated`

---

## Phase 3.5 -- Redeploy Gate

**Only if**: `phases_executed.verify == true` AND `prs_created.length > 0`.

Emit this exact prompt to the user and wait for response:

```
[gap cycle] Phase 4 requires the changes from created PRs to be deployed.
Have you redeployed the affected services? [y/N]
```

- If user responds `y` (case-insensitive): continue to Phase 4.
- Any other response (N, empty, or other input):
  - Set `phases_executed.verify = false`
  - Write `summary.json`
  - Emit: `[gap cycle] Phase 4 skipped -- redeploy not confirmed.`
  - Jump to Rollup.

---

## Phase 4 -- Verify

**Only if**: `phases_executed.verify == true` AND Phase 3.5 confirmed AND NOT `--dry-run`.

Run exactly ONE canonical verification -- the routing golden path:

```
Use skill: golden-path-validate
```

Consult `golden-path-validate`'s own documentation for the canonical routing fixture path.
Do not invent or derive a fixture path -- use what the skill documents as its default routing fixture.

Require nontrivial assertions: at minimum one field equality check on the output event.

Collect result:
- `status`: pass | fail | timeout
- `latency_ms`, `correlation_id`, `assertions`

Record:
- `phase_results.verify.status = "complete"` if pass; else `"failed"`
- `phase_results.verify.result = {status, latency_ms, correlation_id, assertions}`

Emit: `[gap cycle] Phase 4 complete: {status}`

---

## Rollup

After all enabled phases complete (or on early exit):

### 1. Compute composite_status

Apply this deterministic mapping (in order of precedence):

| Condition | composite_status |
|-----------|-----------------|
| Any phase threw an exception or returned error | `error` |
| `blocked` set in Phase 0 (prerequisite missing) | `blocked` |
| `gate_pending` set in Phase 3 | `gate_pending` |
| `nothing_to_fix == true` | `complete` |
| All enabled phases ran AND `gated_findings_count == 0` AND (verify not enabled OR verify passed) | `complete` |
| Otherwise (phases skipped by flags, verify disabled, `gated_findings_count > 0`) | `partial` |

**Rule:** `gated_findings_count > 0` always prevents `complete`, yielding `partial` at minimum.

### 2. Write summary.json

```
mkdir -p ~/.claude/gap-cycle/{epic_id}/{run_id}/
Write to: ~/.claude/gap-cycle/{epic_id}/{run_id}/summary.json
```

Create parent directories first. Write the complete summary object.

### 3. Print composite verdict

```
[gap cycle] -----------------------------------------------
  Epic:    {epic_id}
  Run:     {run_id}
  Status:  {composite_status}
  Phases:  detect={T/F} audit={T/F} fix={T/F} verify={T/F}
  PRs:     {prs_created.length} created
  Gated:   {gated_findings_count}
  Report:  {source_report_path}
  Summary: ~/.claude/gap-cycle/{epic_id}/{run_id}/summary.json
[gap cycle] -----------------------------------------------
```

---

## Error Handling (cycle)

- **Missing ARTIFACT marker**: hard error -- `[gap cycle] ERROR: detect did not emit an ARTIFACT: marker.` Do NOT attempt path reconstruction.
- **Missing GAP_FIX_OUTPUT marker**: hard error -- `[gap cycle] ERROR: fix did not emit a GAP_FIX_OUTPUT: marker.` Do NOT attempt path reconstruction.
- **File not readable**: set `composite_status = "blocked"`, emit clear message with the attempted path, write summary.json, exit cleanly (no exception crash).
- **Sub-skill exception**: catch, set `composite_status = "error"`, record error in `phase_results[current_phase].error`, write summary.json, re-raise to surface to user.
- **epic_id missing from --report file**: `[gap cycle] ERROR: --report file missing epic_id field at report.epic_id`. Hard stop.

---

## Dry-Run Behavior (cycle)

Policy: local artifact writes allowed; external writes (Linear, GitHub, Kafka mutations) forbidden; verify suppressed.

When `--dry-run`:
- Phase 1 (detect): runs normally (read-only, writes local report file)
- Phase 2 (audit note): emitted if --audit; no chaining in v0.1 regardless
- Phase 3 (fix): receives `--dry-run`; outputs plan only; no PRs; no Linear writes
- Phase 3.5: skipped (no PRs were created)
- Phase 4: suppressed entirely (`phases_executed.verify = false`)
- summary.json: written with `"dry_run": true`
