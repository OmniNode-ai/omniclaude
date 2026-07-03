# Hook Measurement Harness

Read-only analytics that compare the omniclaude hook surface in two windows —
**hooks-off** (the baseline established when hooks were first disabled) and **hooks-on** — across tokens/turn,
latency/tool-call, and outcome impact. It reads existing telemetry surfaces
only; it never deploys, mutates, or adds a REST endpoint.

## Surfaces read

| Surface | Path | Provides |
|---------|------|----------|
| Cost-accounting DB | `$ONEX_STATE_DIR/hooks/cost_accounting.db` | per tool-call tokens, USD cost, `session_id`, `is_delegated` |
| PRM trajectory store | `$ONEX_STATE_DIR/hooks/logs/post-tool-use-trajectory.jsonl` | per tool-call ordering → inter-call latency |

The canonical `onex.evt.omniclaude.tool-executed.v1` event stream remains the
authoritative bus-side surface for downstream rollups.

## Run

```bash
# ONEX_STATE_DIR must be set; --boundary is the off→on toggle instant.
python -m omniclaude.hook_measurement.cli --boundary 2026-06-20T17:00:00Z
python -m omniclaude.hook_measurement.cli --boundary 2026-06-20T17:00:00Z --json
```

Records before `--boundary` are scored hooks-off; records at/after it hooks-on.

## API

```python
from omniclaude.hook_measurement import (
    load_cost_records, aggregate_window, compare_windows, EnumHookWindow,
)
```

See `docs/proposals/2026-06-18-hook-measurement-and-tiered-reintroduction.md` for the
tiered reintroduction plan, measurement gates, and the kill-switch/rollback story.
