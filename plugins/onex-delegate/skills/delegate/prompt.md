# /onex:delegate — one command, the answer, then the run

Run ONE command. It prints one typed result object as JSON on stdout. Diagnostics go to
a log file on disk. Show the user the answer from that object, then one line naming the
run. Nothing else.

```bash
onex delegate "<prompt>" --json --session-model <session-model-id> [--task-type <type>] [--max-tokens <n>]
```

If that command exits 2 with `Error: No such option '--session-model'` and `REFUSED -- argument_parsing, nothing dispatched`, the installed `onex` predates the flag and
no delegation ran. That refusal is not the answer and not a failure to report: run the same command once more without `--session-model`, then answer from that run.

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
- `--session-model` — the exact model ID this Claude Code session runs, as the session's own system prompt names it (for example `claude-opus-5-5`). The run's savings are stated against your own model, and the receipt names `baseline_source: session_model`. Never guess an ID: if the session does not name one, leave the flag out and the fixed default baseline is used. If the command fails with `No such option: --session-model`, the installed `onex` predates the flag: run the same command once more without `--session-model`.

The command builds the payload, dispatches the node, and extracts the result
internally. Do NOT construct a payload file, `cd` anywhere, or read any
intermediate result file — there is no procedure to learn.

## Choosing the model: `/onex:delegate models`

When the arguments are `models`, or start with `models first`, the user is choosing
which model delegation tries first, not delegating a task. Run the matching command
below and show its output as it is. These change what delegation tries first; they
re-run no onboarding, ask for no key and send no prompt anywhere.

```bash
onex models list
onex models first <provider> <model>
onex models first --clear
```

- `/onex:delegate models`: run `onex models list`. It shows each provider, whether it
  is set up, and its models in the order they are tried. The provider whose model is
  tried first is listed first, marked `tried first: <model>`.
- `/onex:delegate models first <provider> <model>`: run
  `onex models first <provider> <model>`, then `onex models list`. `<provider>` is one
  of `gemini`, `openrouter`, `openai`, `anthropic`, `glm` or `local`, and `<model>` is
  one of that provider's models from the list. Leaving out `<model>` keeps the
  provider's own first model. The next delegation tries that model first, before any
  other model or key. If it fails, the run moves on in its usual order.
- `/onex:delegate models first --clear`: run `onex models first --clear`. Delegation
  goes back to its usual order: local models first, then your keys.

If the command refuses (a provider that is not set up, or a model not in its list),
show its one `Error: ...` line and stop. Adding a provider is
`onex models add <provider>`, which asks for the key at a hidden prompt, so tell the
user to run it in their own terminal.

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
