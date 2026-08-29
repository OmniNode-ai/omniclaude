# /onex:cloud_delegate — one command, one saved run

Run ONE command. It submits the delegation to the OmniNode platform, polls it to
a terminal state, fetches the signed receipt, prints the generated output on
stdout, and writes the run to disk.

```bash
onex cloud delegate "<prompt>" --task-type <type> [--max-tokens <n>] [--output-dir <dir>]
```

Call the bare `onex` on PATH — never `uv run onex`, which resolves the venv of
the current directory's project. If `onex cloud --help` does not exit 0, install
per SKILL.md's prerequisite section.

- `<prompt>` — the task to delegate (required).
- `--task-type` — **required**: `summarization | research | document | test | code_generation | code_review | refactor | reasoning | complex_reasoning | planning | review`.
- `--max-tokens` — response budget. Omit to let the platform decide.
- `--output-dir` — defaults to `onex-delegations`.

Do NOT construct a payload, call the gateway yourself, or read the credential.
The command owns submit, poll, receipt and file-writing. There is no procedure
to learn, and **no HTTP request is ever made from this plugin.**

## Present the result

The generated output goes to **stdout**; progress, saved paths and the model
line go to **stderr**. Present:

- **Response**: the stdout content. Show it in full.
- **Saved files**: the `result:` / `receipt:` / `run:` paths from stderr. Always
  report these — keeping the files locally is the reason this path exists.
- **Model line**: the `model:` line — model used, token count, latency.

## When it fails, say what failed

The command exits non-zero and names the failure class. Relay it; do not
paper over it, do not retry, and **never answer the prompt yourself instead.**

| Exit shape | What it means | What to tell the user |
|---|---|---|
| `rejected the API key (401/403)` | key revoked, wrong environment, or truncated on paste | re-run `onex cloud login`; the key may belong to a different gateway |
| `has it FENCED` | the workflow type is declared but deliberately not servable | an operator state, not a fault in the request |
| `refused this delegation with 429` | rate limit or plan quota | a refusal, not a transient error — it was not retried |
| `terminal status 'failed' — the runtime returned no content` | submit accepted, the runtime could not answer (e.g. a quota-dead model key) | report it as a platform-side failure; the receipt was still saved and says why |
| `could not reach the OmniNode gateway` | wrong base URL or no network | not a credential problem |
| `no 'cloud:' block` / `no ONEX config` | no key stored on this machine | run `onex cloud login` with a key created in the dashboard |

Never print, echo, or reconstruct the API key in any output.
