# Merge Sweep — Thin Trigger

You are the merge-sweep skill entry point. This prompt defines the complete execution logic.

**Execution mode: FULLY AUTONOMOUS.**
- Without `--dry-run`: publish command event and monitor immediately (no questions).
- `--dry-run` is the only preview mechanism; it sets `dry_run: true` in the command event.

---

## Announce

Output:
```
[merge-sweep] MODE: trigger | run: <run_id>
```

No tool calls, file reads, or bash commands may precede this output.

---

## Parse Arguments

Parse `$ARGUMENTS`:
- `--repos <list>` — default: all repos in omni_home (empty list = all)
- `--dry-run` — default: false
- `--merge-method <method>` — default: squash
- `--require-approval <bool>` — default: true
- `--require-up-to-date <policy>` — default: repo
- `--max-total-merges <n>` — default: 0 (unlimited)
- `--max-parallel-prs <n>` — default: 5
- `--max-parallel-repos <n>` — default: 3
- `--max-parallel-polish <n>` — default: 20
- `--skip-polish` — default: false
- `--polish-clean-runs <n>` — default: 2
- `--authors <list>` — default: all
- `--since <date>` — default: none (ISO 8601: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ)
- `--label <labels>` — default: all (comma-separated for any-match)
- `--run-id <id>` — default: generate `<YYYYMMDD-HHMMSS>-<random6>`
- `--resume` — default: false
- `--reset-state` — default: false
- `--inventory-only` — default: false
- `--fix-only` — default: false
- `--merge-only` — default: false
- `--enable-auto-rebase` — default: true
- `--use-dag-ordering` — default: true
- `--enable-trivial-comment-resolution` — default: true
- `--enable-admin-merge-fallback` — default: **true** (OMN-9065: flipped from opt-in to on-by-default; pass `--no-enable-admin-merge-fallback` to disable)
- `--admin-fallback-threshold-minutes <n>` — default: 15 (OMN-9065: lowered from 30 for faster auto-unstick)
- `--verify` — default: **true** (OMN-9066: flipped from opt-in to on-by-default; pass `--no-verify` to disable. Originally OMN-7742 pre-merge verification gate.)
- `--verify-timeout-seconds <n>` — default: 30 (per-PR verification timeout)

Generate `run_id` if `--run-id` not provided: `<YYYYMMDD-HHMMSS>-<random6>`.

---

## Map Args → Command Event

Build the command event payload:

```json
{
  "run_id": "<run_id>",
  "repos": ["<repos-list>"],
  "dry_run": <bool>,
  "merge_method": "<squash|merge|rebase>",
  "require_approval": <bool>,
  "require_up_to_date": "<always|never|repo>",
  "max_total_merges": <int>,
  "max_parallel_prs": <int>,
  "max_parallel_repos": <int>,
  "max_parallel_polish": <int>,
  "skip_polish": <bool>,
  "polish_clean_runs": <int>,
  "authors": ["<authors-list>"],
  "since": "<ISO-date-or-null>",
  "labels": ["<labels-list>"],
  "resume": <bool>,
  "reset_state": <bool>,
  "inventory_only": <bool>,
  "fix_only": <bool>,
  "merge_only": <bool>,
  "enable_auto_rebase": <bool>,
  "use_dag_ordering": <bool>,
  "enable_trivial_comment_resolution": <bool>,
  "enable_admin_merge_fallback": <bool>,
  "admin_fallback_threshold_minutes": <int>,
  "verify": <bool>,
  "verify_timeout_seconds": <int>,
  "emitted_at": "<UTC-ISO-timestamp>",
  "correlation_id": "<uuid4>"
}
```

If `--dry-run` is set: log the event payload and stop here (zero filesystem writes):
```
[merge-sweep] DRY RUN: would publish to onex.cmd.omnimarket.pr-lifecycle-orchestrator-start.v1
<payload JSON>
Dry run complete. No mutations performed.
```

---

## Publish Command Event

Publish the command event directly to the Kafka cmd topic via `kcat -P`. The emit daemon
is scoped to `onex.evt.*` observability events — cmd-topic command publishing uses a
direct broker produce, mirroring the pattern already proven in `skills/redeploy/prompt.md`
(DEPLOY phase).

Prior art (reference): `plugins/onex/skills/redeploy/prompt.md` — Phase 5: DEPLOY publishes
`onex.cmd.deploy.rebuild-requested.v1` via the same `echo ... | kcat -P` shell-out.

### Envelope wrapping (OMN-9215)

The consumer runtime (`omnibase_infra.runtime.auto_wiring.handler_wiring._make_event_bus_callback`)
validates every inbound message against `ModelEventEnvelope[object]` before dispatch. A
bare-payload JSON — the shape published before OMN-9215 — fails validation with
`payload: Field required` and the handler never runs (see
`docs/diagnosis-omn-9215-pr-lifecycle-orchestrator-envelope-mismatch.md`). The publish
step therefore wraps the command_event dict inside a `ModelEventEnvelope` and serializes
the envelope, not the raw payload.

```python
import json
import os
import shlex
import subprocess
from uuid import UUID

from omnibase_core.models.events.model_event_envelope import ModelEventEnvelope

COMMAND_TOPIC = "onex.cmd.omnimarket.pr-lifecycle-orchestrator-start.v1"

# Env-var probe (fail-fast — no silent defaults)
kafka_bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS")
if not kafka_bootstrap:
    print(
        "[merge-sweep] PUBLISH FAILED: KAFKA_BOOTSTRAP_SERVERS not set. "
        "Source ~/.omnibase/.env before invoking the skill."
    )
    # Write error ModelSkillResult and exit — see "Write ModelSkillResult and Report" below.
    result = {
        "status": "error",
        "message": "KAFKA_BOOTSTRAP_SERVERS not set",
        "run_id": run_id,
    }
    # EXIT 1

# Wrap the command event dict in ModelEventEnvelope so the runtime auto-wiring
# callback (which validates ModelEventEnvelope[object] before dispatch) accepts
# the message and routes it to HandlerPrLifecycleOrchestrator. Preserve the
# caller's correlation_id (command_event["correlation_id"] is a UUID string).
envelope = ModelEventEnvelope[dict](
    payload=command_event,
    correlation_id=UUID(command_event["correlation_id"]),
    event_type="omnimarket.pr-lifecycle-orchestrator-start",
    source_tool="merge-sweep-skill",
)
msg = envelope.model_dump_json()

# Produce command event to Kafka via kcat -P
proc = subprocess.run(
    f"echo {shlex.quote(msg)} | kcat -P -b {shlex.quote(kafka_bootstrap)} -t {COMMAND_TOPIC}",
    shell=True,
    capture_output=True,
    text=True,
)
if proc.returncode != 0:
    print(
        f"[merge-sweep] PUBLISH FAILED: kcat -P to {COMMAND_TOPIC} exited "
        f"{proc.returncode}. stderr: {proc.stderr.strip()}"
    )
    result = {
        "status": "error",
        "message": f"kafka produce failed: {proc.stderr.strip()}",
        "run_id": run_id,
    }
    # EXIT 1
```

Log:
```
[merge-sweep] Published command event to pr_lifecycle_orchestrator | run_id: <run_id>
```

### Why kcat, not the emit daemon

The emit daemon (observability event client in `plugins/onex/hooks/lib/`) fans out observability
events declared in `SUPPORTED_EVENT_TYPES` — a semantic event-type registry, not an
arbitrary topic passthrough. `onex.cmd.omnimarket.pr-lifecycle-orchestrator-start.v1`
is a command topic routed directly by the broker to the orchestrator's consumer group;
it is not in the emit daemon's registry and cannot be. This skill therefore uses the
same direct-produce pattern as `skills/redeploy` for its cmd-topic publish. Fixes
OMN-9214 (112 consecutive no-op refusals on 2026-04-19 from a missing daemon
symbol — see ticket for historical context).

### Why wrap in ModelEventEnvelope

The bare-payload publish that shipped with OMN-9214 produced every command on this
topic, but the runtime auto-wiring layer validates against `ModelEventEnvelope[object]`
before dispatching to the orchestrator handler. Bare payloads fail with
`payload: Field required` and the handler never runs — every merge_sweep tick timed
out at 15m. The envelope wrap makes the message round-trip through the auto-wiring
callback and reach `HandlerPrLifecycleOrchestrator.handle`, which in turn writes
`result.json` and unblocks the monitor loop. Fixes OMN-9215.

---

## Monitor Completion

Poll `$ONEX_STATE_DIR/merge-sweep/<run_id>/result.json` every 10 seconds.

Timeout: 3600 seconds (1 hour).

```python
import json, time
from pathlib import Path

result_path = Path(f"{ONEX_STATE_DIR}/merge-sweep/{run_id}/result.json")
timeout_seconds = 3600
poll_interval = 10
elapsed = 0

while elapsed < timeout_seconds:
    if result_path.exists():
        result = json.loads(result_path.read_text())
        break
    time.sleep(poll_interval)
    elapsed += poll_interval
else:
    result = {"status": "error", "message": "orchestrator timeout", "run_id": run_id}
```

Log poll progress every 60 seconds:
```
[merge-sweep] Waiting for orchestrator... <elapsed>s elapsed
```

---

## Write ModelSkillResult and Report

Write the orchestrator result directly to the skill result path:

```python
import json
from pathlib import Path

skill_result_path = Path(f"{ONEX_STATE_DIR}/skill-results/{run_id}/merge-sweep.json")
skill_result_path.parent.mkdir(parents=True, exist_ok=True)
skill_result_path.write_text(json.dumps(result, indent=2))
```

Log the final status:
```
[merge-sweep] complete | status: <status> | run_id: <run_id>
```

The result passes through unchanged from the orchestrator. Expected status values:
- `queued` — all candidates had auto-merge enabled and/or branches updated
- `nothing_to_merge` — no actionable PRs found (after all filters)
- `partial` — some queued/updated, some failed or blocked
- `error` — no PRs successfully queued or updated

---

## Failure Handling

| Failure | Behavior |
|---------|----------|
| `KAFKA_BOOTSTRAP_SERVERS` not set | Log error, exit with `status: error, message: KAFKA_BOOTSTRAP_SERVERS not set` |
| `kcat -P` exits non-zero | Log stderr, exit with `status: error, message: kafka produce failed: <stderr>` |
| Orchestrator timeout (>3600s) | Log warning, emit `status: error, message: orchestrator timeout` |
| `result.json` parse error | Log error, emit `status: error, message: malformed result` |
| `$ONEX_STATE_DIR` not set | Log error, exit immediately |

## Branch Protection Drift Diagnostic

When a PR has BLOCKED merge state but all CI checks are green, this signals
branch_protection drift: the repo's required status checks have diverged from
what's configured in `required-checks.yaml`.

If the orchestrator reports a BLOCKED + green PR in its result, surface this diagnostic:

```bash
python scripts/audit-branch-protection.py --repo <repo> --pr <N>
```

The `audit-branch-protection` script identifies which required checks are missing
from the PR's check suite vs. the branch protection configuration, enabling targeted
remediation without blocking the sweep.

---

## BLOCKED PR Cause Diagnosis (OMN-8811)

Before reporting any PR as BLOCKED or dispatching a fixer worker, run the following
against the PR to determine the exact root cause:

```bash
# Step 1: fetch CI, review decision, and review threads
gh pr view <N> --repo <org/repo> --json statusCheckRollup,reviewDecision,reviewThreads

# Step 2: fetch merge queue membership and position (gh pr view --json does not expose these)
gh api graphql -f query='
  query($owner:String!,$repo:String!,$number:Int!){
    repository(owner:$owner,name:$repo){
      pullRequest(number:$number){
        mergeQueueEntry{ position estimatedTimeToMerge enqueued }
      }
    }
  }
' -f owner=<org> -f repo=<repo> -F number=<N>
```

Categorize as exactly ONE of these mutually exclusive causes (evaluated in order):

| Priority | Category | Condition |
|---|---|---|
| 1 | `CI_FAILING` | `statusCheckRollup` contains any check with state FAILURE, ERROR, or PENDING |
| 2 | `CR_THREADS_OPEN` | `reviewThreads` contains any unresolved thread **and** CI is not failing |
| 3 | `QUEUE_STALE` | `mergeQueueEntry` is present but `position` has not changed across sweep ticks; no CI failures, no open threads |
| 4 | `APPROVED_PENDING_MERGE` | `mergeQueueEntry` present and advancing (position decreasing or `estimatedTimeToMerge` set); `reviewDecision == APPROVED`, all CI green |

**Rules:**
- Report the category name, not a qualitative description.
- Evaluate in priority order: `CI_FAILING` → `CR_THREADS_OPEN` → `QUEUE_STALE` → `APPROVED_PENDING_MERGE`. The first matching category wins.
- Never call a PR "stale queue" if it has open review threads — that is `CR_THREADS_OPEN`.
- A PR with no `mergeQueueEntry` and no other blockers is `APPROVED_PENDING_MERGE` only if `reviewDecision == APPROVED` and all CI green; otherwise classify by whichever blocker applies.
- False-positive guard: before dispatching any fixer, verify `gh pr view <N> --json state` returns `OPEN`. If `MERGED`, reclaim the dispatched.yaml slot and skip.

---

## What This Prompt Does NOT Do

- Scan GitHub repos
- Classify PRs (`needs_branch_update`, `is_merge_ready`, `needs_polish`)
- Call `gh pr merge --auto`
- Dispatch pr-polish agents
- Manage claim registry
- Track failure history
- Write sweep state checkpoints
