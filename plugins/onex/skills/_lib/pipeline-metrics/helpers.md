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
If STANDALONE tier: write to `~/.claude/metrics/{ticket_id}/pipeline_metrics.jsonl` (append mode).

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
