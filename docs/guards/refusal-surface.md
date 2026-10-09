# Guard refusal surface (OMN-18983)

The four live worktree, git-stash, credential-rotation and ticket-creation guards
use the existing `hook_record_refusal` seam and the handlers of
`node_hook_refusal_record_effect` (`handler_hook_refusal_record.py` and
`handler_hook_refusal_lane.py`). The Bash guards run through their registered combined
entrypoint; the admission guard runs on its registered Linear matcher.

With `ONEX_STATE_DIR` unset, the declared log is
`$OMNI_HOME/.onex_state/hooks/logs/hooks.log`. `OMNI_HOME` must be absolute. Missing or
relative roots are configuration refusals, with a fix on stderr and no fallback
to the user's home directory. An explicit absolute `ONEX_STATE_DIR` selects the
same `hooks/logs/hooks.log` partition in an isolated state root.

Each refusal attempt gets a UTC ISO-8601 timestamp, the guard's script name,
the resolved lane, `lane_source`, and `refusal_count=1`. The recorder reuses the
existing sidecar, environment, registry and open-CLAIM resolution chain. An
unattributable refusal carries `lane=unresolved` and `lane_source=unresolved`.
Summing `refusal_count` for that source counts unresolved attempts. Counting
only ledger rows undercounts retries: the existing ledger writer deduplicates
per guard, reason and lane, while this log records each attempt before that
deduplication. Log rotation continues through the existing path resolver.

The same recorder still sends its aggregate rows through the locked ledger
writer the morning sweep reads. It records the local attempt before trying the
ledger, so a failed aggregate append does not erase the local evidence. Recording
remains asynchronous; consumers must allow the recorder to finish. An empty
log does not prove that hooks are healthy or that no refusal happened.

Historical log disposition: abandoned. The 198 lines reported in the owning
ticket at `$HOME/.onex_state/logs/hooks.log` are historical evidence, not the live
surface. Keep any surviving file read-only; do not replay, redate, or migrate its
lines into current refusals. New default-path writes go to the declared registry
surface under `hooks/`, which the sweep declares as an input. The previous
registry `logs/hooks.log` is likewise historical and receives no new default-path
refusals. This disposition does not assert that the historical count is a current
host measurement.

The dormant `skip_token_surface_guard.sh` runtime wrapper is explicitly retired.
It is retained as historical implementation on disk, is not registered, and is
not a runtime enforcement claim. Existing repository token gates remain the
enforcement surface. Installing a new runtime control is outside this fix.

`tests/hooks/test_refusal_surface_omn18983.py` drives real refusals through the
registered paths with a live CLAIM, a declared lane environment and unresolved
operands, and reads the log and aggregate row back. The `refusal-surface`
pre-commit hook and the independent `Refusal Surface (OMN-18983)` CI job execute
that file. The required CI Summary umbrella demands that job be present and
successful; missing, skipped and failed runs cannot count as acceptance.

This change finishes the existing recorder and guard wiring. It adds no node,
handler module, script, CLI, heartbeat, or sibling-ticket rollout.
