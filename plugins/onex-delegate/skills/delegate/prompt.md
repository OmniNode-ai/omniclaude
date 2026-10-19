# /onex:delegate — one command, the answer, then the run

Run ONE command. It prints one typed result object as JSON on stdout. Diagnostics go to
a log file on disk. Show the user the answer from that object, then one line naming the
run. Nothing else.

```bash
onex delegate "<prompt>" --json [--task-type <type>] [--max-tokens <n>]
```

Run it exactly like that: a plain `onex delegate` invocation with no redirect, pipe, `&&`
or `2>&1`. The permission rule `Bash(onex delegate:*)` covers only a plain invocation.

Call the bare `onex` on PATH — never `uv run onex`, which resolves the venv of
the current directory's project and fails outside a repo that co-installs
`omnibase-infra`. Install per SKILL.md's prerequisite section if
`onex delegate --help` does not exit 0 or does not list `--json`.

- `<prompt>` — the task to delegate (required).
- `--json` — required. The one stdout line is the typed result, and its `correlation_id` is the run id the closing line carries; `--result-only` is not used because it prints the answer alone, with no run id.
- `--task-type` — `test | document | research | code_generation | refactor | reasoning | review`. Omit to auto-classify from the prompt.
- `--max-tokens` — response budget (default 2048).

The command builds the payload, dispatches the node, and extracts the result
internally. Do NOT construct a payload file, `cd` anywhere, or read any
intermediate result file — there is no procedure to learn.

## Present the result

Read the single JSON object on stdout. Reply with exactly two parts, in this order:

1. **The answer**: `result.response`, as it is. Add no summary of your own, no status, no model name, no cost, no metrics.
2. **The run**: after a blank line, one line, `Run: <correlation_id>`, where `<correlation_id>` is the object's top-level `correlation_id`, copied exactly.

Do not show the rest of the object: no receipt fields, no metrics, no attempts.

If the command exits non-zero, or `result.status` is not `completed`, show the one error
line (stderr's `Error: ...` line, else `result.error_message`) and the same
`Run: <correlation_id>` line when the object has one, then stop. Do not fall back to an
inline LLM call.

## Read the receipt only when needed

The run's `receipt.json` (its path is on the `delegate artifacts` line the command
prints, under the run's directory in the state root) holds the model, provider, cost,
latency and attempts. Read it only when the user asks for the cost, the model or the
attempts, or when the error line alone cannot diagnose the failure. Suppressed
diagnostics are in the same run directory's `diagnostics.log`. Otherwise leave both
unread: every byte you read comes back into your context.
