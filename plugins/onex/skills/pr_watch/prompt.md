<!-- routing-enforced: dispatches to node_pr_watch_orchestrator (stub). functionally-complete requires real node implementation. -->

# /onex:pr_watch — dispatch-only shim

Dispatch to `node_pr_watch_orchestrator` in omnimarket. Do not reimplement PR watch logic inline.

No inline orchestration, no LLM reasoning, no direct Kafka publish — the node owns the full pipeline.

## Announce

Say: "I'm using the pr-watch skill to dispatch node_pr_watch_orchestrator."

## Parse `$ARGUMENTS`

| Flag | Default |
|------|---------|
| `--pr <pr_number>` | required |
| `--ticket-id <ticket_id>` | required |
| `--timeout-hours <n>` | 24 |
| `--max-review-cycles <n>` | 3 |
| `--fix-nits` | unset |
| `--no-auto-fix` | unset |

## Dispatch

```bash
onex run node_pr_watch_orchestrator -- \
  --pr "$PR_NUMBER" \
  --ticket-id "$TICKET_ID" \
  ${TIMEOUT_HOURS:+--timeout-hours "$TIMEOUT_HOURS"} \
  ${MAX_REVIEW_CYCLES:+--max-review-cycles "$MAX_REVIEW_CYCLES"} \
  ${FIX_NITS:+--fix-nits} \
  ${NO_AUTO_FIX:+--no-auto-fix}
```

Surface the JSON output from stdout. The node produces a `ModelSkillResult` with `status`, `run_id`, and `message`.

On non-zero exit, a `SkillRoutingError` JSON envelope is returned — surface it directly, do not produce prose. If dispatch cannot execute, report the error and stop.

Never re-implement PR watch orchestration inline. If the node is unavailable, stop — do not fall back to inline polling, direct GitHub API calls, or prose orchestration.
