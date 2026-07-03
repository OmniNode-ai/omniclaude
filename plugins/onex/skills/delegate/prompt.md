# /onex:delegate — one command, one typed result

Run ONE command. It prints exactly one typed `ModelSkillResult[ModelDelegateSkillResponse]`
JSON to stdout — the full LLM response and metrics, never truncated. RuntimeLocal
logs and intermediate context go to a capture file + the artifact store, never to you.

```bash
uv run onex delegate "<prompt>" [--task-type <type>] [--max-tokens <n>]
```

- `<prompt>` — the task to delegate (required).
- `--task-type` — `test | document | research | code_generation | refactor | reasoning | review`. Omit to auto-classify from the prompt.
- `--max-tokens` — response budget (default 2048).

The command builds the payload, dispatches the node, and extracts the result
internally. Do NOT construct a payload file, `cd` anywhere, or read any
intermediate result file — there is no procedure to learn.

## Present the result

Parse the single JSON object on stdout and present `result` (a `ModelDelegateSkillResponse`):

- **Response**: `result.response` — the LLM output. Show it.
- **Status**: `result.status`
- **Model / provider**: `result.model_name` / `result.provider`
- **Cost savings**: `result.metrics.cost_savings_usd`
- **Latency**: `result.metrics.latency_ms`

If `status` is `failed` or `timeout`, show `result.error_message`. On non-zero
exit the receipt's `result` carries the full error inline — surface it; do not
fall back to an inline LLM call.
