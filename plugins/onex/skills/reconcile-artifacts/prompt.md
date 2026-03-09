# reconcile-artifacts execution prompt

## Pre-flight

1. Source `~/.omnibase/.env` to ensure the correct broker address is available:
   ```bash
   source ~/.omnibase/.env
   ```
2. Verify `omni-infra` is available:
   ```bash
   which omni-infra || uv run omni-infra --help
   ```
   If neither succeeds, tell the user to run `uv run omni-infra --help` from an `omnibase_infra` worktree and stop.
3. Extract `--repo` arg (required). If not provided, ask the user which repo to reconcile before proceeding.
4. Extract `--reason` arg (optional). Default value if not provided: `"Manual reconciliation via omniclaude skill"`.

## Execution

Dispatch via `onex:polymorphic-agent`:

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="Run artifact reconciliation for {repo}",
  prompt="""
Run the artifact reconcile command:

    source ~/.omnibase/.env
    omni-infra artifact-reconcile --repo {repo} --reason "{reason}"

Capture stdout and stderr. Return:
- exit code
- stdout
- stderr (if any)

Do not interpret the result — return the raw output to the caller.
"""
)
```

## Output Handling

After the polymorphic agent returns:

| Exit code | Stdout contains | Action |
|-----------|----------------|--------|
| 0 | "Published to" | Display stdout as-is — publish succeeded |
| Non-zero | Any | Surface stderr; advise user to check broker reachability (`KAFKA_BOOTSTRAP_SERVERS=localhost:19092` by default) and run `omni-infra artifact-reconcile --help` |

Note: The CLI uses Rich formatting for stdout output. When captured, it may contain ANSI escape codes — strip them if displaying in plain-text contexts.

## Error Cases

| Condition | Response |
|-----------|----------|
| `omni-infra` not found on PATH and `uv run omni-infra` fails | Tell user to run `uv run omni-infra --help` from the omnibase_infra worktree to confirm the CLI is installed |
| Missing `--repo` arg | Ask user which repo to reconcile before dispatching |
| Kafka not reachable | CLI exits non-zero; surface stderr and advise the user to verify broker reachability |
| Non-zero exit | Surface stderr content and link user to `omni-infra artifact-reconcile --help` |
| `~/.omnibase/.env` missing | Warn user that env file is absent; `KAFKA_BOOTSTRAP_SERVERS` will not be set and the CLI will default to `localhost:19092`; proceed if that broker is acceptable |
