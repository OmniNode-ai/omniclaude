# /onex:delegate — one command, one answer

Run ONE command. On success its stdout is the final answer and nothing else; on failure
stdout is empty and stderr is one error line. Diagnostics go to a log file on disk, never
to you.

```bash
onex delegate "<prompt>" --result-only [--task-type <type>] [--max-tokens <n>]
```

Run it exactly like that: a plain `onex delegate` invocation with no redirect, pipe, `&&`
or `2>&1`. The permission rule `Bash(onex delegate:*)` covers only a plain invocation, and
the flag already keeps the output down to the answer.

Call the bare `onex` on PATH — never `uv run onex`, which resolves the venv of
the current directory's project and fails outside a repo that co-installs
`omnibase-infra`. Install per SKILL.md's prerequisite section if
`onex delegate --help` does not exit 0 or does not list `--result-only`.

- `<prompt>` — the task to delegate (required).
- `--result-only` — required. Exit 0: stdout is the final answer, stderr is empty. Non-zero exit: stdout is empty and stderr is exactly one line. It cannot be combined with `--json` or `--human`.
- `--task-type` — `test | document | research | code_generation | refactor | reasoning | review`. Omit to auto-classify from the prompt.
- `--max-tokens` — response budget (default 2048).

The command builds the payload, dispatches the node, and extracts the result
internally. Do NOT construct a payload file, `cd` anywhere, or read any
intermediate result file — there is no procedure to learn.

## Present the result

- **Exit 0**: show stdout as the answer, as it is. Add no summary of your own, no status, no model name, no cost, no metrics.
- **Non-zero exit**: show the one stderr line and stop. It has the form `Error: <terminal cause>: <error_message> (receipt: <path>)`, and it covers a refusal before dispatch as well. Do not fall back to an inline LLM call.

## Read the receipt only when needed

The run's `receipt.json` (the absolute path is in the error line; on success it is under
the run's directory in the state root) holds the model, provider, cost, latency and
attempts. Read it only when the user asks for the cost, the model or the attempts, or when
the error line alone cannot diagnose the failure. Suppressed diagnostics are in the same
run directory's `diagnostics.log`. Otherwise leave both unread: every byte you read comes
back into your context.
