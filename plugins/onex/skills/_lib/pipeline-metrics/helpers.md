# Pipeline Metrics Helpers

## Kafka Topic
`onex.evt.omniclaude.phase-metrics.v1`

## Event Schema

```json
{
  "schema_version": "1.0",
  "event_type": "pipeline_phase_transition",
  "ticket_id": "OMN-XXXX",
  "epic_id": "OMN-EPIC-YYYY",
  "phase": "local_review",
  "outcome": "passed | failed | blocked | skipped",
  "iteration_count": 2,
  "phase_elapsed_ms": 45000,
  "total_elapsed_ms": 120000,
  "hostile_block_count": 0,
  "emitted_at": "2026-02-28T00:00:00Z"
}
```

## `emit_phase_metric(ticket_id, epic_id, phase, outcome, iteration_count, phase_elapsed_ms, total_elapsed_ms, hostile_block_count=0, model_id="unknown", producer_kind="unknown")` — Procedure

Emit to Kafka if FULL_ONEX tier (use `@_lib/tier-routing/helpers.md` for tier check).
If STANDALONE tier: write to `$ONEX_STATE_DIR/metrics/{ticket_id}/pipeline_metrics.jsonl` (append mode).

Always write to local file regardless of tier (local file is the fallback + debug log).

### Attribution kwargs

- `model_id` (str): LLM model identifier, read from `state["attribution"]["model_id"]`. Defaults to `"unknown"` for backwards compatibility with legacy runs that lack an attribution block.
- `producer_kind` (str): Producer classification (`"agent"`, `"human"`, or `"unknown"`), read from `state["attribution"]["producer_kind"]`. Defaults to `"unknown"`.

These are threaded into `ContractMeasurementContext.extensions` and appear in the emitted phase metrics event on the `onex.evt.omniclaude.phase-metrics.v1` topic.

## TCB Effectiveness Tracking

After auto_merge completes successfully:
Emit additional event:

```json
{
  "schema_version": "1.0",
  "event_type": "tcb.outcome",
  "ticket_id": "OMN-XXXX",
  "tcb_id": "{ticket_id}-tcb",
  "entrypoints_used": ["src/foo.py"],
  "entrypoints_suggested": ["src/foo.py", "src/bar.py"],
  "tests_run": ["test_foo"],
  "tests_suggested": ["test_foo"],
  "patterns_cited": ["PAT-001"],
  "outcome": "merged | regression",
  "emitted_at": "..."
}
```

This feeds the pattern scoring feedback loop via `node_pattern_feedback_effect`.

Note: `ticket_id` and `outcome` are required fields in the TCB outcome event (see `TCB_OUTCOME_REGISTRATION` in `omnibase_infra/src/omnibase_infra/runtime/emit_daemon/topics.py`).

## PR Validation Rollup

### Kafka Topic
`onex.evt.omniclaude.pr-validation-rollup.v1`

### `emit_pr_validation_rollup(state, checkpoints)` -- Procedure

Emitted at pipeline terminal states:
- **Final rollup** (`rollup_status="final"`): After auto_merge success (merged_via_auto or merged).
- **Partial rollup** (`rollup_status="partial"`): On pipeline blocked/failed terminal state.

```python
from plugins.onex.hooks.lib.rollup_aggregator import build_pr_validation_rollup
from plugins.onex.hooks.lib.emit_client_wrapper import emit_event

rollup = build_pr_validation_rollup(state, all_phase_checkpoints)
emit_event("pr.validation.rollup", rollup)
```

### Rollup Schema

```json
{
  "metric_version": "v1",
  "run_id": "abc12345",
  "ticket_id": "OMN-XXXX",
  "model_id": "claude-sonnet-4-20250514",
  "producer_kind": "agent",
  "pr_url": "https://github.com/OmniNode-ai/repo/pull/42",
  "pr_number": 42,
  "repo_full_name": "OmniNode-ai/repo",
  "rollup_status": "final | partial",
  "tax": {
    "blocking_failures": 0,
    "warn_findings": 2,
    "reruns": 1,
    "validator_runtime_ms": 45000,
    "human_escalations": 0,
    "autofix_successes": 1,
    "time_to_green_ms": 120000,
    "files_changed": 5,
    "lines_changed": 200
  },
  "vts": 12.5,
  "vts_per_kloc": 62.5,
  "extensions": {
    "missing_fields": [],
    "vts_weights": {"blocking_failures": 10.0, "warn_findings": 1.0, "...": "..."}
  }
}
```

### VTS Formula

VTS = sum(weight_i * field_i) for each tax field, floored at 0.0.

Weights (from `DEFAULT_VTS_WEIGHTS`):
- `blocking_failures`: 10.0
- `warn_findings`: 1.0
- `reruns`: 5.0
- `validator_runtime_s`: 0.5 (note: runtime converted from ms to seconds)
- `human_escalations`: 20.0
- `autofix_successes`: -3.0 (negative = reduces cost)

VTS per kLoC = `vts / max(1, lines_changed / 1000)`

Fields unavailable from state are set to 0 and listed in `extensions.missing_fields`.
