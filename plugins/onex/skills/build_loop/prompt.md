# build_loop prompt

You are executing the **build-loop** skill. This skill dispatches to the
`node_build_loop_orchestrator` node in omnimarket for autonomous build loop
execution (CLOSING_OUT → VERIFYING → FILLING → CLASSIFYING → BUILDING → COMPLETE).

No inline orchestration, no LLM reasoning, no multi-phase Python loop —
the node owns the full FSM pipeline.

## Announce

Say: "I'm using the build-loop skill to start the autonomous build loop."

## Parse arguments

Extract from `$ARGUMENTS`:

- `--max-cycles <N>` — Maximum build loop cycles (default: 1)
- `--skip-closeout` — Skip the CLOSING_OUT phase
- `--dry-run` — Simulate all phases without side effects (no PRs, tickets, or merges)
- `--max-tickets <N>` — Max tickets to dispatch per fill cycle (default: 5)
- `--mode <build|close_out|full|observe>` — Execution mode (default: build)

## Execution: Dispatch to node_build_loop_orchestrator

Build the `onex run` command from parsed arguments and dispatch to the omnimarket
node. The node handles every FSM phase internally and emits the
build-loop-orchestrator-completed envelope.

```bash
cd "$ONEX_REGISTRY_ROOT/omnimarket"  # local-path-ok: canonical omnimarket worktree

ARGS=""
if [ -n "$MAX_CYCLES" ]; then
  ARGS="$ARGS --max-cycles $MAX_CYCLES"
fi
if [ "$SKIP_CLOSEOUT" = "true" ]; then
  ARGS="$ARGS --skip-closeout"
fi
if [ "$DRY_RUN" = "true" ]; then
  ARGS="$ARGS --dry-run"
fi
if [ -n "$MAX_TICKETS" ]; then
  ARGS="$ARGS --max-tickets $MAX_TICKETS"
fi
if [ -n "$MODE" ]; then
  ARGS="$ARGS --mode $MODE"
fi

uv run onex run node_build_loop_orchestrator -- $ARGS
```

Capture the JSON output from stdout. The node produces a
`ModelOrchestratorResult` with `cycles_completed`, `cycles_failed`,
`total_tickets_dispatched`, and `cycle_summaries`.

## Post-dispatch: Render results

Parse the node output and render the human-readable summary:

```
Build Loop Session
==================
Cycles completed: <N>
Cycles failed:    <N>
Tickets dispatched: <N>
Circuit breaker:  <tripped | ok>
```

For each cycle in `cycle_summaries`, render per-cycle phase outcomes.

On non-zero exit from `onex run`, a `SkillRoutingError` JSON envelope
is returned — surface it directly, do not produce prose.

## Error handling

- If `onex run` fails to start (binary missing, contract not found):
  report the error and exit.
- If the node returns `cycles_failed > 0`: surface `cycle_summaries`
  with per-cycle phase errors and exit with the node's exit code.
- If the circuit breaker tripped (3 consecutive phase failures): surface
  the circuit breaker status and halt.
- Never re-implement the build loop pipeline inline. If the node is
  unavailable, stop — do not fall back to prose orchestration.
