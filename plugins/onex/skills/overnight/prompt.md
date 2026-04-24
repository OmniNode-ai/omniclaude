# overnight prompt

You are executing the **overnight** skill. This skill dispatches to the
`node_overnight` node in omnimarket for autonomous overnight session
orchestration (nightly_loop_controller, build_loop, merge_sweep, ci_watch,
platform_readiness).

No inline orchestration, no LLM reasoning, no multi-phase Python loop —
the node owns the full pipeline.

## Announce

Say: "I'm using the overnight skill to dispatch node_overnight."

## Parse arguments

Extract from `$ARGUMENTS`:

- `--max-cycles <N>` — Maximum build loop cycles (default: 0 = unlimited)
- `--dry-run` — Run all phases in dry-run mode (no workers dispatched)
- `--skip-build-loop` — Skip the build loop phase
- `--skip-merge-sweep` — Skip the merge sweep phase

## Execution: Dispatch to node_overnight

Build the `onex run-node` command from parsed arguments and dispatch to
the omnimarket node. The node handles every phase internally
(nightly_loop_controller → build_loop_orchestrator → merge_sweep →
ci_watch → platform_readiness) and emits the session-completed envelope.

```bash
cd /Volumes/PRO-G40/Code/omni_home/omnimarket  # local-path-ok: example command in documentation

ARGS=""
if [ -n "$MAX_CYCLES" ]; then
  ARGS="$ARGS --max-cycles $MAX_CYCLES"
fi
if [ "$DRY_RUN" = "true" ]; then
  ARGS="$ARGS --dry-run"
fi
if [ "$SKIP_BUILD_LOOP" = "true" ]; then
  ARGS="$ARGS --skip-build-loop"
fi
if [ "$SKIP_MERGE_SWEEP" = "true" ]; then
  ARGS="$ARGS --skip-merge-sweep"
fi

uv run onex run-node node_overnight -- $ARGS
```

Capture the JSON output from stdout. The node produces a
`ModelOvernightResult` with `session_status`, `phases_run`,
`phases_failed`, and `correlation_id`.

## Post-dispatch: Render results

Parse the node output and render the human-readable summary:

```
Overnight Session
=================
Session status: <completed | partial | failed>
Phases run:     <list>
Phases failed:  <list>
Correlation:    <correlation_id>
```

On non-zero exit from `onex run-node`, a `SkillRoutingError` JSON envelope
is returned — surface it directly, do not produce prose.

## Error handling

- If `onex run-node` fails to start (binary missing, contract not found):
  report the error and exit.
- If the node returns `session_status == "failed"`: surface
  `phases_failed` and exit with the node's exit code.
- Never re-implement the overnight pipeline inline. If the node is
  unavailable, stop — do not fall back to prose orchestration.
