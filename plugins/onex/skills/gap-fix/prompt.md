# Gap Fix Orchestration

You are executing the gap-fix skill. This prompt defines the complete orchestration logic.

---

## Step 0: Parse Arguments

Parse from `$ARGUMENTS`:

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
1. If `--ticket`: load finding from Linear ticket marker block → synthetic one-finding report
2. If `--report <run_path>`: load `~/.claude/gap-analysis/<run_path>/<run_id>.json`
3. If `--latest`: resolve `~/.claude/gap-analysis/latest/` symlink → load its `.json` report
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

Load `~/.claude/gap-analysis/<run_id>/decisions.json` if it exists. This contains previously
resolved gate decisions. These are used to skip re-prompting on resume.

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
| `kafka_topic` | `producer_only_no_consumer` | `GATE` |
| `api_contract` | `missing_openapi` | `GATE` |
| Any `BEST_EFFORT` confidence with multiple resolutions | — | `GATE` |
| All other cases not listed above | — | `GATE` |

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
DECISION REQUIRED — GAP-b7e2d5f8
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

  Provide choice via: /gap-fix --choose GAP-b7e2d5f8=A [--report <same run_path>]
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
     description="gap-fix: Phase 3 fix for finding <finding_id> via ticket-pipeline",
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
  description="gap-fix: Phase 3 fix for finding <finding_id> via ticket-work",
  prompt="You are executing ticket-work for <ticket_id>.
    Invoke: Skill(skill=\"onex:ticket-work\", args=\"<ticket_id>\")
    Finding: <finding summary>
    Report back with: files_changed, tests_run, any blockers."
)
```
No PR creation step. Skip Phase 3.3.

### 3.3 Call pr-queue-pipeline (ticket-pipeline mode only)

After all ticket-pipeline dispatches complete, write `prs_created_path`:
```
~/.claude/gap-analysis/<run_id>/gap-fix-output.json
```

Invoke pr-queue-pipeline scoped to the created PRs only:
```
Task(
  subagent_type="onex:polymorphic-agent",
  description="gap-fix: Phase 3 pr-queue-pipeline for created PRs",
  prompt="Invoke: Skill(skill=\"onex:pr-queue-pipeline\",
    args=\"--prs ~/.claude/gap-analysis/<run_id>/gap-fix-output.json\")
    Report back with: status, total_prs_merged, total_prs_still_blocked."
)
```

**Critical**: Always call with `--prs <path>` (scoped to new PRs), NEVER with `--repos`.

**Blocked-external guard**: If pr-queue-pipeline returns `blocked_external > 0`, log a warning
and do NOT retry. These are infra failures (CI infrastructure down, deploy locks) — do not loop.

### 3.4 Mode: implement-only

No ticket creation, no ticket-pipeline or ticket-work dispatch. Implement fixes directly:

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="gap-fix: Phase 3 implement-only for finding <finding_id>",
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

### Re-probe by boundary_kind

| `boundary_kind` | Re-probe method |
|-----------------|-----------------|
| `kafka_topic` | grep for old topic name in affected repos — must return zero matches |
| `db_url_drift` | grep for legacy DB name or env var in affected repos — must return zero matches |
| `api_contract` | check that OpenAPI spec file now exists at expected path |
| `model_type` | grep for mismatched field type — must return zero matches |
| `fk_reference` | grep for old FK target — must return zero matches |

**Re-probe must pass before marking fixed.** If re-probe fails:
- Mark finding as `still_open` (not `fixed`)
- Log: `Re-probe failed for <finding_id>: <evidence>`
- Continue with remaining findings
- Include in `findings_still_open` in output

**Skip re-probe only for**:
- `--dry-run` mode
- `implement-only` mode (no PR yet to re-probe against)

---

## Phase 5: Report

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

Append to the existing `~/.claude/gap-analysis/<run_id>.md` artifact:

```markdown
## Gap-Fix Run — <fix_run_id>
Date: <ISO timestamp> | Mode: <mode> | Dry-run: <true|false>

### Fixed (<N> findings)
- GAP-a3f9c1d2 — kafka_topic/topic_name_mismatch — PR: OmniNode-ai/omniclaude#247
- GAP-c9f1e3b4 — db_url_drift/legacy_db_name_in_tests — PR: OmniNode-ai/omnibase_infra#403

### Gate Pending (<N> findings — awaiting --choose)
- GAP-b7e2d5f8 — kafka_topic/producer_only_no_consumer — choices emitted above

### Still Open (<N> findings — re-probe failed)
- GAP-d2a4f8c1 — api_contract/missing_openapi — re-probe failed: spec not found

### Skipped (<N> findings — SKIP confidence or already fixed)
- GAP-e7b3d9a2 — SKIP confidence: no OpenAPI spec present, cannot probe
```

### 5.3 Write ModelSkillResult

Write `~/.claude/gap-analysis/<run_id>/gap-fix-result.json`:

```json
{
  "skill": "gap-fix",
  "version": "0.1.0",
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
  "output_path": "~/.claude/gap-analysis/<run_id>/gap-fix-output.json"
}
```

**Status resolution**:
- `complete` — `findings_auto > 0`, all auto findings fixed, `gate_pending == []`
- `partial` — some fixed, some failed or gated (gate_pending may or may not be empty)
- `nothing_to_fix` — `findings_auto == 0` (all gated or skipped)
- `gate_pending` — `findings_auto == 0` AND `findings_gated > 0` AND none were previously decided
- `error` — unrecoverable error before any fixing occurred

---

## Linear Ticket Template

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

<auto-determined resolution — one of:>
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

## Error Handling

| Error | Behavior |
|-------|----------|
| Report file not found | Return `status: error`, log path tried |
| `findings` list empty | Return `status: nothing_to_fix` |
| All findings are GATE with no prior decisions | Return `status: gate_pending`, emit choices |
| ticket-pipeline dispatch fails for a finding | Mark finding `still_open`, continue with rest |
| pr-queue-pipeline returns `blocked_external > 0` | Log warning, do NOT retry, mark as `partial` |
| Re-probe fails | Mark finding `still_open`, continue |
| decisions.json write fails | Log warning (non-blocking), continue |
| `--dry-run` | Never write decisions.json, never write gap-fix-output.json |

---

## --dry-run Invariant

When `--dry-run` is set, the following must produce ZERO side effects:
- No `decisions.json` writes
- No `gap-fix-output.json` writes
- No Linear ticket creation or mutation
- No PR creation, mutation, or merge
- No `ticket-pipeline` or `ticket-work` dispatch
- No `pr-queue-pipeline` invocation

The skill may still:
- Read report files
- Classify findings
- Emit choices blocks
- Print the plan

Log prefix for all output: `[DRY RUN]`

---

## Resuming from Gate Pending

After a human provides choices via `--choose`:

```
/gap-fix --report <same run_path> --choose GAP-b7e2d5f8=A,GAP-c3a1e2d4=B
```

The skill:
1. Loads existing decisions.json
2. Merges new `--choose` decisions
3. Re-classifies findings (gate findings with decisions become AUTO)
4. Proceeds from Phase 3 for newly-decided findings only
5. Skips findings already marked `fixed` in prior run's result

**Idempotency**: Already-fixed findings (present in `prs_created[]`) are skipped on resume.
