<!-- routing-enforced: dispatches to node_gap_compute (stub). functionally-complete requires real node implementation. -->

# /onex:gap — dispatch-only shim

Dispatch to `node_gap_compute` in omnimarket. Do not reimplement gap analysis inline.

No inline orchestration, no LLM reasoning, no direct Kafka publish, no
`gh` subprocess fallback — the node owns the full pipeline.

## Announce

Say: "I'm using the gap skill to dispatch node_gap_compute."

## Parse `$ARGUMENTS`

First positional argument is the subcommand: `detect`, `fix`, `cycle`, or `reconcile`.

All remaining flags are passed through to the node.

## Dispatch

```bash
onex run node_gap_compute -- $PARSED_ARGS
```

Surface the JSON output from stdout. The node produces a `ModelSkillResult` with `status`, `run_id`, and `message`.

On non-zero exit, a `SkillRoutingError` JSON envelope is returned — surface it directly, do not produce prose. If dispatch cannot execute, report the error and stop.

Never re-implement gap analysis orchestration inline. If the node is unavailable, stop — do not fall back to inline probing, direct Kafka publish, or prose orchestration.
