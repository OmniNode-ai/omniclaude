# begin-day — Authoritative Behavior Specification

> **OMN-5349**: Automated morning investigation pipeline.
> **Authoritative**: When `SKILL.md` and `prompt.md` conflict, `prompt.md` wins.

---

## Invocation

```
/begin-day [--date YYYY-MM-DD] [--skip-plan] [--skip-sync] [--probes <list>] [--dry-run]
```

- `--date`: Override today's date (default: `date.today().isoformat()`)
- `--skip-plan`: Skip Phase 4 plan generation
- `--skip-sync`: Skip Phase 1 repo sync
- `--probes`: Comma-separated probe names to run (default: all 7)
- `--dry-run`: Print what would run, do not dispatch probes

---

## Phase 0 — Context Load (~30s, sequential)

### Determine dates and run_id

```python
import uuid, datetime
TODAY = args.get("--date") or datetime.date.today().isoformat()
YESTERDAY = (datetime.date.fromisoformat(TODAY) - datetime.timedelta(days=1)).isoformat()
RUN_ID = uuid.uuid4().hex[:12]
```

### Create artifact directory

```python
ARTIFACT_DIR = Path.home() / ".claude" / "begin-day" / RUN_ID
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
```

### Rerun check

If `$ONEX_STATE_DIR/begin-day/latest/day_open.yaml` exists and contains today's date:
- Print advisory: `"Prior run exists: {previous_run_id}. Proceeding with new run."`
- Continue — do NOT prompt. The user invoked `/begin-day` intentionally.
- New `RUN_ID`, new artifact directory. Prior artifacts are retained.

### Load yesterday's corrections

```python
ONEX_CC_REPO_PATH = os.environ.get("ONEX_CC_REPO_PATH", "")
corrections = []
if ONEX_CC_REPO_PATH:
    yesterday_yaml = Path(ONEX_CC_REPO_PATH) / "drift" / "day_close" / f"{YESTERDAY}.yaml"
    if yesterday_yaml.exists():
        data = yaml.safe_load(yesterday_yaml.read_text())
        corrections = data.get("corrections_for_tomorrow", [])
```

If `ONEX_CC_REPO_PATH` not set → empty corrections, continue.
If yesterday's file missing → empty corrections, continue.

---

## Phase 1 — Sync & Preconditions (~2min, sequential)

### Skip condition

If `--skip-sync` is set, skip pull-all.sh. Still run infra health check (read-only).

### Sync repos

```bash
bash /Volumes/PRO-G40/Code/omni_home/omnibase_infra/scripts/pull-all.sh 2>&1 | tail -20  # local-path-ok
```

Parse stdout to build `repo_sync_status`. On failure → HIGH finding, continue.

### Check infra health

```bash
docker ps --format '{{.Names}} {{.Status}}' | grep omnibase-infra
```

Port probes for liveness (not service readiness):
- PostgreSQL: `localhost:5436`
- Redpanda: `localhost:19092`
- Valkey: `localhost:16379`

If infra down → HIGH finding per service, **continue** (do NOT abort).

**Scope of health check**: Port liveness proves the service is listening, not that topics work, DB is ready, or auth passes. Sufficient for morning triage.

---

## Phase 2 — Parallel Investigation (~8min, parallel dispatch)

### Probe catalog

| Probe Name | Skill Invocation | Purpose |
|------------|-----------------|---------|
| `dashboard_sweep` | `/dashboard-sweep --triage-only` | Page health, no fixes |
| `aislop_sweep` | `/aislop-sweep --dry-run` | AI slop detection |
| `gap_detect` | `/gap detect --since-days 1` | Cross-repo integration drift |
| `env_parity` | `/env-parity check` | Local vs cloud env drift |
| `system_status` | `/system-status` | Platform service health |
| `omnidash_health` | `uv run check-omnidash-health --baseline-path ~/.omnibase/omnidash_baseline.json --json` | Dashboard row count regression (OMN-5653) |
| `boundary_parity` | `uv run check-boundary-parity --json` | Kafka boundary parity (OMN-5653) |

### Probe-specific handling (OMN-5653)

**omnidash_health** (severity weight: 16 -- CRITICAL):
- Source: `onex_change_control` package (`check-omnidash-health` entry point)
- If exit code 1 (regressions found): create `CRITICAL` findings for each regressed table
- If baseline file is stale (mtime older than latest migration): downgrade to advisory
- Known false-positive sources: transient DB access issues, baseline staleness after migrations
- Initial posture: RECOMMEND block, do not hard-block. Set `regression_detected` flag.

**boundary_parity** (severity weight: 8 -- HIGH):
- Source: `onex_change_control` package (`check-boundary-parity` entry point)
- If mismatches found: create `HIGH` findings with producer/consumer file paths
- Dedup by topic name (do not re-ticket already-tracked mismatches)
- If `check-boundary-parity` not installed (PR #82 not merged): status = "skipped"

**Baseline validity rule**: If the saved baseline predates material schema or boundary
changes, downgrade comparison from regression to advisory until a new close-day baseline
is captured. Detect staleness by comparing baseline file mtime against latest migration mtime.

### Dispatch rules

**ALL 7 probes MUST be dispatched in a SINGLE message as parallel polymorphic agents.**

If `--probes` is set, only dispatch the named probes. Others are skipped.

Each probe agent receives this prompt template:

```
You are a begin-day investigation probe. Your job:

1. Run the skill: {SKILL_INVOCATION}
2. Capture the output
3. Write a structured JSON artifact to: {ARTIFACT_DIR}/{PROBE_NAME}.json

The JSON artifact MUST follow this contract:
{
  "probe_name": "{PROBE_NAME}",
  "status": "completed" | "failed" | "skipped",
  "summary": "Brief summary of findings",
  "finding_count": <int>,
  "findings": [
    {
      "finding_id": "{PROBE_NAME}:{category}:{deterministic_key}",
      "severity": "critical" | "high" | "medium" | "low" | "info",
      "source_probe": "{PROBE_NAME}",
      "title": "Short description",
      "detail": "Detailed explanation",
      "repo": "affected_repo_or_null",
      "suggested_action": "What to do about it"
    }
  ],
  "error": null | "error message if failed",
  "duration_seconds": <float>
}

Finding ID rules:
- Format: {probe_name}:{category}:{deterministic_key}
- deterministic_key must identify the underlying resource (repo+PR, env var, topic name)
- NOT the wording of the finding
- Must be stable across reruns for the same issue

If the skill is not available, write: {"probe_name": "{PROBE_NAME}", "status": "skipped", "findings": [], "error": "Skill not available"}
```

Each agent MUST use:
- `subagent_type`: `onex:polymorphic-agent`

### Degraded dispatch fallback

If the bundled fan-out fails structurally (orchestration error, not individual probe failure):

1. Retry each failed probe individually as a solo polymorphic agent
2. If solo dispatch also fails → mark probe `FAILED` with error "dispatch failure"
3. **Never fail the entire morning pipeline on orchestration mechanics alone**

### Wait for completion

Wait for ALL dispatched probes to complete before proceeding to Phase 3.

---

## Phase 3 — Aggregate & Model (~1min, sequential)

### 1. Collect probe results

```python
# Glob ARTIFACT_DIR/*.json
# Adversarially validate each file per Malformed Probe Artifact Policy
probe_results = collect_probe_results(ARTIFACT_DIR)
```

### Malformed Probe Artifact Policy

| Artifact condition | Aggregator behavior |
|---|---|
| Valid JSON, all required fields | Normal aggregation |
| Valid JSON, missing required fields | Mark probe `FAILED`, synthesize HIGH finding naming missing fields |
| Malformed JSON | Mark probe `FAILED`, synthesize HIGH finding |
| Non-JSON file in artifact dir | Skip silently |
| Probe wrote nothing | Mark probe `FAILED`, synthesize MEDIUM finding |
| Duplicate finding_ids from one probe | Keep first occurrence, warn in summary |
| Unknown severity value | Map to MEDIUM, warn in summary |

### 2. Merge corrections as findings

```python
# Yesterday's corrections become HIGH findings with source_probe="close_day_carryforward"
# Finding ID: close_day_carryforward:correction:{sha256_hash_of_text[:12]}
```

### 3. Carry-Forward Collision Rule

When a fresh probe finding and a carry-forward correction describe the same resource:
- **Fresh finding wins** in aggregated_findings
- Carry-forward is **suppressed** from aggregated_findings
- Carry-forward text is **preserved** in `yesterday_corrections` (raw provenance)

### 4. Dedup and sort

```python
# Dedup by (source_probe, finding_id) — first occurrence wins within a probe
# Cross-probe same resource (by deterministic_key): higher severity wins
# Sort: CRITICAL > HIGH > MEDIUM > LOW > INFO
```

### 5. Compute focus areas

Weighted severity scoring:
- CRITICAL = 16 points
- HIGH = 8 points
- MEDIUM = 4 points
- LOW = 2 points
- INFO = 1 point

Group by affected repo (or "platform" for cross-repo issues). Top 3-5 by total score.

### 6. Build + validate ModelDayOpen

```python
raw = build_day_open(
    today=TODAY,
    run_id=RUN_ID,
    yesterday_corrections=corrections,
    repo_sync_status=repo_sync_status,
    infra_health=infra_health,
    probe_results=probe_results,
    aggregated_findings=aggregated_findings,
    recommended_focus_areas=focus_areas,
    total_duration_seconds=elapsed,
)

# Validate against schema — fail loudly on error
from onex_change_control import ModelDayOpen
ModelDayOpen.model_validate(raw)
```

### 7. Write artifact

```python
yaml_str = serialize_day_open(raw)
write_day_open(yaml_str, ARTIFACT_DIR)
# Updates $ONEX_STATE_DIR/begin-day/latest -> RUN_ID
```

### 8. Print executive summary

```
================================================================
BEGIN-DAY REPORT — {TODAY}
================================================================
Run ID:       {RUN_ID}
Duration:     {total_duration}s
Probes:       {completed}/{total} completed, {failed} failed, {skipped} skipped

FINDINGS:
  CRITICAL: {n}    HIGH: {n}    MEDIUM: {n}    LOW: {n}    INFO: {n}

CARRY-FORWARD FROM YESTERDAY: {n} corrections

RECOMMENDED FOCUS AREAS:
  1. {area}
  2. {area}
  3. {area}

Artifact: $ONEX_STATE_DIR/begin-day/{RUN_ID}/day_open.yaml
================================================================
```

---

## Phase 4 — Plan Generation (optional, unless --skip-plan)

Phase 4 is an **optional consumer** of the ModelDayOpen artifact. The morning artifact is complete and useful after Phase 3.

### Generate action plan

```
/design-to-plan --phase plan
```

Provide context:
- `day_open.yaml` path as input
- Topic: "Begin-day findings for {TODAY}"
- Skip brainstorm phase — investigation results are the input
- Output: plan with `## Task N:` headings (compatible with `plan-to-tickets`)

### If design-to-plan fails or is unavailable

The run is still successful. Print the artifact path and advise manual review:

```
Phase 4 skipped: /design-to-plan not available. Review findings manually:
  $ONEX_STATE_DIR/begin-day/{RUN_ID}/day_open.yaml
```

---

## Error Handling

| Condition | Behavior |
|-----------|----------|
| `ONEX_CC_REPO_PATH` not set | Skip close-day read, empty corrections |
| Yesterday's close-day missing | Empty corrections, continue |
| `pull-all.sh` fails | HIGH finding, continue |
| Docker not running | All infra flagged down (HIGH), continue probes |
| Any probe fails/times out | `status: failed/timed_out`, continue |
| Skill not merged yet | `status: skipped`, continue |
| `ModelDayOpen.model_validate()` fails | stderr error, exit 1 |
| `design-to-plan` unavailable | Print artifact path, advise manual review |
| Already ran today | Advisory notice, proceed with new run_id |

---

## Dry Run Behavior

When `--dry-run` is set:

- **Phase 0**: Runs (read-only — compute dates, load corrections)
- **Phase 1**: Skip pull-all, run infra check (read-only)
- **Phase 2**: Print probes that WOULD run, do NOT dispatch
- **Phase 3-4**: Skip

Output:
```
[begin-day --dry-run] Would dispatch 5 probes:
  - dashboard_sweep → /dashboard-sweep --triage-only
  - aislop_sweep → /aislop-sweep --dry-run
  - gap_detect → /gap detect --since-days 1
  - env_parity → /env-parity check
  - system_status → /system-status

Yesterday corrections: {n} items
Infra: postgres={ok/down}, redpanda={ok/down}, valkey={ok/down}
```
