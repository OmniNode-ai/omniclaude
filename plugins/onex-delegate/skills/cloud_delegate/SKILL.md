---
version: 1.0.0
description: "Delegate a task to the OmniNode platform with a dashboard API key. Runs `onex cloud delegate \"<prompt>\" --task-type <type>`, which submits over HTTPS, polls to a terminal state, fetches the signed receipt, and saves the output to local files. Handled inline — no subagent, no HTTP from the plugin."
skill_kind: dispatch
mode: full
level: advanced
debug: false
category: delegation
tags: [delegation, dispatch, single-command, cloud, gateway, api-key]
composable: false
args:
  - name: prompt
    description: "The task to delegate (e.g., 'summarize this changelog')"
    required: true
  - name: --task-type
    description: "Task classification the platform routes on: summarization, research, code_generation, code_review, refactor, reasoning, complex_reasoning, planning, review, document, test. Required."
    required: true
  - name: --max-tokens
    description: "Response budget. Omit to let the platform resolve it from its routing contract."
    required: false
  - name: --output-dir
    description: "Directory the run's files are written under, as <output-dir>/<workflow_id>/ (default: onex-delegations)"
    required: false
inputs:
  - name: prompt
    description: "User prompt to delegate to the OmniNode platform"
outputs:
  - name: result
    description: "The generated output, printed on stdout and saved to result.txt"
  - name: files
    description: "result.txt, receipt.json and run.json under <output-dir>/<workflow_id>/"
  - name: receipt
    description: "The signed receipt: model used, token count, latency, projection_row_hash, terminal_event_hash"
---

# /onex:cloud_delegate — delegate to the platform, keep the files

**Skill ID**: `onex:cloud_delegate` · **Command**: `onex cloud delegate` · **Backing surface**: `omnimarket.cli.cli_cloud` (gateway HTTPS)

A dispatch skill IS one CLI call. This skill runs that command and presents its
output. **It makes no HTTP calls of its own, and it must not**: the Claude Code
plugin never talks to the cloud (standing 2026-08-03 ruling). The `onex` CLI
is the sole gateway client; this skill is a shim over it.

See `prompt.md` for the one command and how to present the result.

## `cloud_delegate` vs `delegate` — pick the right one

| | `/onex:delegate` | `/onex:cloud_delegate` |
|---|---|---|
| Runs on | a local LLM, in-process or over the local bus | the OmniNode platform |
| Transport | event bus / in-process | HTTPS to the gateway |
| Credential | none | a dashboard-minted `onxk_` API key |
| Needs | a local workspace, a canonical `omnimarket` clone, broker access | nothing but the key and a base URL |
| Receipt | typed result on stdout | a signed receipt saved to disk |

The two are siblings, not modes of one command. `delegate` is the internal
dev-workstation path; `cloud_delegate` is the tenant path a customer uses.

## Prerequisite: install the CLI, then log in

The `cloud` command group is contributed by the **`omnimarket`** package through
the `onex.cli` entry-point group — installing that package is what makes
`onex cloud` exist. Nothing hand-wires it.

| Package | Provides |
|---|---|
| `omnibase-core` | the `onex` console script and the `onex.cli` entry-point loader |
| `omnimarket` | the `cloud` command group (`login`, `delegate`, `receipt`, `status`, `logout`) |

```bash
uv tool install --with omnimarket omnibase-core
```

Verify: `onex cloud --help` must exit 0 from any directory. If it exits 2 with
`No such command 'cloud'`, `omnimarket` is not installed in the same environment
as the `onex` script.

Then store the key created in the dashboard — read from stdin, never passed as a
flag value:

```bash
read -rs ONXK && printf '%s' "$ONXK" | \
  onex cloud login --base-url https://dev.api.omninode.ai --api-key-stdin
```

`onex cloud status` prints which key is configured without printing the key.

## Task Types

`summarization`, `research`, `document`, `test`, `code_generation`,
`code_review`, `refactor`, `reasoning`, `complex_reasoning`, `planning`,
`review`.

Unlike `/onex:delegate`, `--task-type` is **required** — the gateway contract
requires it, and guessing it would silently change which model answers.

## Usage

```
/onex:cloud_delegate --task-type summarization summarize this changelog
/onex:cloud_delegate --task-type code_generation write a Python retry helper
/onex:cloud_delegate --task-type research --max-tokens 2048 compare Kafka and NATS
```

## The files are the point

Every run writes `<output-dir>/<workflow_id>/`:

| File | What it holds |
|---|---|
| `result.txt` | the generated output, verbatim (omitted when the run produced no content) |
| `receipt.json` | the server's signed receipt, unmodified, hashes included |
| `run.json` | what was asked, where, and the terminal status — so the receipt can be tied back to its request later |

This is why the terminal path is preferred over a browser demo: a browser cannot
keep what it generates. Always report the saved paths.

## What This Skill Does NOT Do

- Make any HTTP request from the plugin — the CLI is the only gateway client
- Read, print, echo, or store the API key; the CLI resolves it from `~/.onex`
- Retry a failed run. A terminal `failed` with no content is a runtime failure
  class (a quota-dead model key, say) and is surfaced, not retried
- Spawn a general-purpose subagent (`skill_kind: dispatch`)
- Fall back to answering the prompt itself if the delegation fails

## Related

- **CLI entrypoint**: `omnimarket/src/omnimarket/cli/cli_cloud.py`, registered as `[project.entry-points."onex.cli"] cloud` in `omnimarket/pyproject.toml`
- **Registration ratchet**: `omnimarket/tests/unit/cli/test_cloud_cli_entry_point_registration_omn16967.py`
- **Gateway client**: `omnimarket/src/omnimarket/cloud/transport_cloud_delegation.py`
- **Console script**: `omnibase_core/pyproject.toml` `[project.scripts] onex`; the `onex.cli` group loader is `omnibase_core/src/omnibase_core/cli/cli_commands.py`
