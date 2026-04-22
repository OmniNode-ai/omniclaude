# /onex:unstick_queue — execution prompt

Run the unstick-queue recovery loop. Mechanical task; no user interaction required.

## Steps

1. Resolve repo list from `--repos`, else `ONEX_QUEUE_REPOS` env, else the canonical set:
   `omniclaude, omnibase_core, omnibase_spi, omnibase_infra, omnibase_compat, omniintelligence, omnimemory, omninode_infra, onex_change_control`.

2. Invoke the runner:

   ```bash
   uv run python "scripts/lib/run-unstick-queue.py" \
     --repos "<csv>" \
     ${DRY_RUN:+--dry-run} \
     --awaiting-minutes "${AWAITING:-30}" \
     --orphan-minutes "${ORPHAN:-20}"
   ```

3. The runner emits a one-line JSON summary per repo and a final aggregate line:
   `{"scanned": N, "stall_unstuck": N, "broken_skipped": N, "escalated": N, "errors": N}`.

4. For each ESCALATE verdict printed by the runner, call:
   `/onex:record_friction --skill unstick_queue --surface "queue_stall/<repo>#<pr>" --severity high --description "repeat-offender merge queue stall (>=3 unsticks in 1h)"`

5. Report the aggregate line back to the caller. Exit non-zero only if the runner itself crashed — individual repo errors are logged and counted but do not fail the tick.
