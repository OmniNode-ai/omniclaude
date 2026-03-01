<!-- persona: plugins/onex/skills/_lib/assistant-profile/persona.md -->
<!-- persona-scope: this-skill-only — do not re-apply if polymorphic agent wraps this skill -->
Apply the persona profile above when generating outputs.

# Gap Analysis Orchestration

You are executing the gap-analysis skill. This prompt defines the complete orchestration logic.

---

## Parse Arguments

Parse from `$ARGUMENTS`:

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

## Phase 1 — Intake

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

1. **Linear relations** (highest confidence): `includeRelations=true` → look for PR/branch
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
    "archon": "omniarchon",
}

KNOWN_REPOS = [
    "omniclaude", "omniintelligence", "omnibase_core", "omnibase_infra",
    "omniarchon", "omnimemory", "omnidash", "omnidash2", "omniweb",
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

Log a clear message: "No repo evidence found for Epic {epic_id} — skipping probes."
Do NOT silently fail. Add to report and move on to next Epic.

---

## Phase 2 — Probe

Run all 5 probe categories for each repo in `repos_in_scope`.
Apply `--repo` filter if provided.

### Scan Root Rules (Apply Before Any Probe)

| Repo layout | Scan roots | Always skip |
|-------------|------------|-------------|
| Python `src/` layout | `src/**` | `tests/**`, `fixtures/**`, `docs/**`, `*.pyi` stubs |
| TypeScript | `client/**`, `server/**`, `src/**` | `__tests__/**`, `*.test.ts`, `*.spec.ts`, `fixtures/**` |
| Generated | — | Entire directory (check for `# GENERATED` header or `codegen/` path) |

### 2.1 Probe: Kafka Topic Drift

**Category**: `CONTRACT_DRIFT` | **boundary_kind**: `kafka_topic`
**rule_name**: `topic_name_mismatch`

**Method (DETERMINISTIC first)**:
1. Find `TopicRegistry` or `TopicBase` enum in `src/**` (AST parse class bodies)
2. Extract all `str` enum values → these are the canonical topic strings
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
2. Parse FK references → check target tables exist in all dependent repos
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

**Method (ALWAYS DETERMINISTIC — never BEST_EFFORT)**:
1. AST parse import statements in scan roots for DB driver imports:
   `psycopg2`, `asyncpg`, `sqlalchemy`, `tortoise`, `databases`, `aiopg`
2. Scan for DB URL env var patterns: `POSTGRES_*`, `PG*`, `DB_*`, `DATABASE_URL`,
   `DATABASE_DSN`, `OMNI*_DB_URL`, `DRIZZLE_*`, `.*_DATABASE_.*`
3. For repos in `no_upstream_db_repos`: any DB import/env var = CRITICAL finding
4. Grep fallback is acceptable for non-DB probes but NOT for this probe.
   If AST parse fails → SKIP (never BEST_EFFORT for DB boundary)

**Severity**: CRITICAL for `no_upstream_db_repos` violation; WARNING otherwise.

### 2.6 Apply Suppressions

After collecting all raw findings:

1. Load `skills/gap-analysis/suppressions.yaml`
2. For each finding, check suppressions in precedence order: `fingerprint` > `path_glob`
3. If matched AND not expired: suppress (remove from findings, do not log)
4. If matched AND expired: do NOT suppress, add fingerprint to `expired_suppressions_warned`
5. Emit warning: "Suppression for {fingerprint[:8]} expired on {expires}. Finding NOT suppressed."

### 2.7 Fingerprint Computation

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

### 2.8 Severity and Best-Effort Caps

After suppressions:
1. Apply `--severity-threshold` filter (drop findings below threshold)
2. Cap BEST_EFFORT findings at `--max-best-effort` (default 50)
   - If exceeded: log "BEST_EFFORT findings capped at {max_best_effort}. {N} dropped."
3. Cap total findings at `--max-findings` (default 200)
   - If exceeded: log "Total findings capped at {max_findings}. {N} dropped."
4. **Hard rule**: Any finding with `confidence = BEST_EFFORT` must have `severity = WARNING`.
   If a finding would be CRITICAL with BEST_EFFORT confidence: downgrade to WARNING automatically.

---

## Phase 3 — Report

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
| In Progress / Backlog / Todo | — | — | Comment only, skip creation |
| Done / Duplicate / Cancelled | ≤ 7 days | Same | Comment only, skip creation |
| Done / Duplicate / Cancelled | > 7 days OR diff fingerprint | — | Create new ticket |
| None found | — | — | Create new ticket |

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
# Gap Analysis Report — {epic_id or "global"} — {run_date}

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

## Dry-Run Behavior

When `--dry-run`:
1. Phases 1 and 2 run fully (probes execute, findings computed)
2. Phase 3 dedup runs (Linear searched for existing tickets)
3. No `create_issue` or `create_comment` calls
4. Report artifacts ARE written (so you can inspect findings)
5. Log prefix: `[DRY-RUN]` on all ticket operations

---

## Idempotency Test

Running `/gap-analysis --epic {id}` twice on the same Epic must produce 0 new tickets on
the second run (assuming no new code changes). Verify:

1. First run: N tickets created, N fingerprints logged
2. Second run: same fingerprints found → all hit the "Comment only, skip creation" path
3. Result: 0 new tickets, N comments added to existing tickets

This is the primary idempotency invariant.

---

## Edge Cases

### Epic With No PR/Branch Evidence

If Linear epic has no PR URLs, branch names, or repo references:
```
repos_in_scope = []
status = "blocked"
blocked_reason = "NO_REPO_EVIDENCE"
```

Log: "Epic {id} has no repo evidence. Set status=blocked."
Skip all probes. Write partial report. Continue to next Epic.

### DB Boundary CRITICAL Finding

When a repo in `no_upstream_db_repos` is found to import DB drivers:
```
severity = CRITICAL
confidence = DETERMINISTIC
category = ARCHITECTURE_VIOLATION
boundary_kind = db_boundary
rule_name = upstream_db_access
```

This finding is NEVER suppressed by path_glob suppressions (only fingerprint suppression applies).

### BEST_EFFORT Cap Exceeded

When `best_effort_count > max_best_effort`:
1. Sort BEST_EFFORT findings by (seam_id alphabetical)
2. Keep the first `max_best_effort`
3. Log: "BEST_EFFORT capped: kept {max_best_effort} of {total_best_effort}"
4. Add note to report markdown

---

## Output Summary

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

After writing the report files, emit this exact line to stdout as the FINAL LINE on ALL normal exit paths — including early exits such as zero findings:

ARTIFACT: {full absolute path to the .json report, e.g. /Users/jonah/.claude/gap-analysis/{epic_id}/{run_id}.json} <!-- local-path-ok -->

If the skill exits early (zero findings, dry-run short-circuit, or any other normal completion), it must still emit this marker before exiting. Abnormal exits (exceptions) are excluded.
