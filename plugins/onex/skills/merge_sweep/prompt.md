# merge_sweep prompt

You are executing the **merge_sweep** skill. This skill dispatches to the
`node_merge_sweep` node in omnimarket for autonomous org-wide PR sweep
orchestration (inventory, triage, auto-merge, pr-polish dispatch, queue
stall detection, pre-merge verification).

No inline orchestration, no LLM reasoning, no direct Kafka publish, no
`gh` subprocess fallback — the node owns the full pipeline.

## Announce

Say: "I'm using the merge-sweep skill to dispatch node_merge_sweep."

## Parse arguments

Extract from `$ARGUMENTS`:

- `--repos <list>` — default: all OmniNode repos
- `--dry-run` — default: false
- `--merge-method <method>` — default: squash
- `--require-approval <bool>` — default: true
- `--require-up-to-date <policy>` — default: repo
- `--max-total-merges <n>` — default: 0 (unlimited)
- `--max-parallel-prs <n>` — default: 5
- `--max-parallel-repos <n>` — default: 3
- `--max-parallel-polish <n>` — default: 20
- `--skip-polish` — default: false
- `--polish-clean-runs <n>` — default: 2
- `--authors <list>` — default: all
- `--since <date>` — default: none
- `--label <labels>` — default: all
- `--run-id <id>` — default: node-generated
- `--resume` — default: false
- `--reset-state` — default: false
- `--inventory-only` — default: false
- `--fix-only` — default: false
- `--merge-only` — default: false
- `--enable-auto-rebase` — default: true
- `--use-dag-ordering` — default: true
- `--enable-trivial-comment-resolution` — default: true
- `--enable-admin-merge-fallback` — default: true
- `--admin-fallback-threshold-minutes <n>` — default: 15
- `--verify` — default: true
- `--verify-timeout-seconds <n>` — default: 30

## Execution: Dispatch to node_merge_sweep

Forward every parsed argument through to the omnimarket node. The node
handles inventory, triage, merge, fix, state reduction, and result
emission internally.

```bash
uv run onex run-node node_merge_sweep -- $PARSED_ARGS
```

Capture the JSON output from stdout. The node produces a
`ModelSkillResult` with `status`, `run_id`, and `message`.

## Post-dispatch: Render results

Parse the node output and render the human-readable summary:

```
Merge Sweep
===========
Status:  <queued | nothing_to_merge | partial | error>
Run ID:  <run_id>
Summary: <message>
```

On non-zero exit from `onex run-node`, a `SkillRoutingError` JSON
envelope is returned — surface it directly, do not produce prose.

## Error handling

- If `onex run-node` fails to start (binary missing, contract not found):
  report the error and exit.
- If the node returns `status == "error"`: surface the `message` field
  and exit with the node's exit code.
- Never re-implement merge sweep orchestration inline. If the node is
  unavailable, stop — do not fall back to `gh pr merge`, direct Kafka
  publish, or prose orchestration.
