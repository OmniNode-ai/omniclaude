<!-- routing-enforced: dispatches to node_integration_sweep_orchestrator (stub). functionally-complete requires real node implementation. -->

# /onex:integration_sweep — dispatch-only shim

Dispatch to `node_integration_sweep_orchestrator` in omnimarket. Do not reimplement scans inline.

No inline orchestration, no LLM reasoning, no direct Kafka publish, no
`gh` subprocess fallback — the node owns the full pipeline.

## Announce

Say: "I'm using the integration-sweep skill to dispatch node_integration_sweep_orchestrator."

## Parse `$ARGUMENTS`

| Flag | Default |
|------|---------|
| `--date <iso-date>` | today |
| `--tickets <ids>` | (empty) |
| `--mode <scope>` | `omniclaude-only` |
| `--dry-run` | unset |
| `--output <path>` | auto |

## Dispatch

```bash
onex run node_integration_sweep_orchestrator -- \
  ${DATE:+--date "$DATE"} \
  ${TICKETS:+--tickets "$TICKETS"} \
  ${MODE:+--mode "$MODE"} \
  ${DRY_RUN:+--dry-run} \
  ${OUTPUT:+--output "$OUTPUT"}
```

Surface the JSON output from stdout. The node produces a `ModelSkillResult` with `status`, `run_id`, and `message`.

On non-zero exit, a `SkillRoutingError` JSON envelope is returned — surface it directly, do not produce prose. If dispatch cannot execute, report the error and stop.

Never re-implement integration sweep orchestration inline. If the node is unavailable, stop — do not fall back to inline probing, direct Kafka publish, or prose orchestration.
