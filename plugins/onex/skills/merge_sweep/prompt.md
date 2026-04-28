# merge_sweep prompt

ADR: The contract-canonical merge-sweep backing node is
`node_pr_lifecycle_orchestrator`, because its contract terminal event is
`onex.evt.omnimarket.pr-lifecycle-orchestrator-completed.v1`, which this skill
uses as its completion signal.

You are executing the **merge_sweep** skill. This skill builds a
`ModelEventEnvelope[ModelPrLifecycleStartCommand]` and dispatches it through the
manifest-canonical runtime path:

```bash
plugins/onex/skills/merge_sweep/run.sh $PARSED_ARGS
```

## Announce

Say: "I'm using the merge-sweep skill."

## Parse arguments

Extract from `$ARGUMENTS`:

- `--repos <list>` — default: all OmniNode repos
- `--dry-run` — default: false
- `--inventory-only` — default: false
- `--fix-only` — default: false
- `--merge-only` — default: false
- `--max-parallel-polish <n>` — default: 20
- `--enable-auto-rebase <bool>` — default: true
- `--use-dag-ordering <bool>` — default: true
- `--enable-trivial-comment-resolution <bool>` — default: true
- `--enable-admin-merge-fallback <bool>` — default: true
- `--admin-fallback-threshold-minutes <n>` — default: 15
- `--verify <bool>` — default: false
- `--verify-timeout-seconds <n>` — default: 30
- `--run-id <id>` — default: generated

## Wire Schema

The launcher sends `event_type:
omnimarket.pr-lifecycle-orchestrator-start` with payload
`ModelPrLifecycleStartCommand` to
`uv run onex run-node node_pr_lifecycle_orchestrator --input`.

## Error handling

- Surface the backing command stdout/stderr directly.
- If the backing command exits non-zero, stop.
- Never re-implement merge sweep orchestration inline.
- Never fall back to direct GitHub merge commands or direct Kafka publish.
