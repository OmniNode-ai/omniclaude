<!-- routing-enforced: dispatches to node_dod_sweep_orchestrator (stub). functionally-complete requires real node implementation. -->

# /onex:dod_sweep — dispatch-only shim

Dispatch to `node_dod_sweep_orchestrator` in omnimarket. Do not reimplement DoD checks inline.

No inline orchestration, no LLM reasoning, no direct Kafka publish — the node owns the full pipeline.

## Announce

Say: "I'm using the dod-sweep skill to dispatch node_dod_sweep_orchestrator."

## Parse `$ARGUMENTS`

| Flag | Default |
|------|---------|
| `target` (positional) | none |
| `--since-days <n>` | 7 |
| `--since-last-cycle` | unset |
| `--per-ticket-verify` | true |
| `--no-per-ticket-verify` | unset |
| `--contracts-dir <path>` | `$ONEX_CC_REPO_PATH/drift` |
| `--dry-run` | unset |

## Dispatch

```bash
onex run node_dod_sweep_orchestrator -- \
  ${TARGET:+--target "$TARGET"} \
  ${SINCE_DAYS:+--since-days "$SINCE_DAYS"} \
  ${SINCE_LAST_CYCLE:+--since-last-cycle} \
  ${NO_PER_TICKET_VERIFY:+--no-per-ticket-verify} \
  ${CONTRACTS_DIR:+--contracts-dir "$CONTRACTS_DIR"} \
  ${DRY_RUN:+--dry-run}
```

Surface the JSON output from stdout. The node produces a `ModelSkillResult` with `status`, `run_id`, and `message`.

On non-zero exit, a `SkillRoutingError` JSON envelope is returned — surface it directly, do not produce prose. If dispatch cannot execute, report the error and stop.

Never re-implement DoD sweep orchestration inline. If the node is unavailable, stop — do not fall back to inline contract parsing, evidence runner calls, or prose orchestration.
