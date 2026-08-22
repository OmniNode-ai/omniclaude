# Headless Mode (`claude -p`)

> Moved out of the root `CLAUDE.md` in OMN-15200. This is the operational reference for
> running the plugin without an interactive Claude Code session — the primary trigger
> surface for CLI automation, Slack bots, and webhooks.

## Basic invocation

```bash
claude -p "Run ticket-pipeline for <TICKET-ID>" \
  --allowedTools "Bash,Read,Write,Edit,Glob,Grep,mcp__linear-server__*,mcp__slack__*"
```

## Required environment variables

| Variable | Purpose | Notes |
|----------|---------|-------|
| `ONEX_RUN_ID` | Unique run identifier for correlation | **Mandatory** — the pipeline will not start without it |
| `ONEX_UNSAFE_ALLOW_EDITS` | Permit file edits in headless mode | Set to `1` to allow Write/Edit tools |
| `GITHUB_TOKEN` | GitHub CLI auth | Required for PR creation and CI polling |
| `SLACK_BOT_TOKEN` | Slack API token | Required for gate notifications |
| `LINEAR_API_KEY` | Linear API key | Required for ticket updates |

> **`ANTHROPIC_API_KEY` is NOT required.** Claude Code sessions (including `claude -p`)
> authenticate via OAuth, not API keys. Do not add it as a required env var or preflight
> check (see `plugins/onex/skills/preflight/SKILL.md`).

```bash
export ONEX_RUN_ID="pipeline-$(date +%s)-<TICKET-ID>"
export ONEX_UNSAFE_ALLOW_EDITS=1
export GITHUB_TOKEN="..."
export SLACK_BOT_TOKEN="..."
export LINEAR_API_KEY="..."

claude -p "Run ticket-pipeline for <TICKET-ID>" \
  --allowedTools "Bash,Read,Write,Edit,Glob,Grep,mcp__linear-server__*,mcp__slack__*"
```

## How auth and correlation work

`ONEX_RUN_ID` is the correlation key written to:

- `~/.claude/pipelines/ledger.json` (run tracking / duplicate prevention)
- `~/.claude/pipelines/{ticket_id}/state.yaml` (phase state machine)
- `~/.claude/rrh-artifacts/{ticket_id}/` (RRH audit artifacts, if RRH is enabled)

Without `ONEX_RUN_ID` the pipeline cannot distinguish runs and refuses to start.

MCP server credentials are sourced from the environment at startup: Linear via
`LINEAR_API_KEY` (or `~/.claude/claude_desktop_config.json`), Slack via `SLACK_BOT_TOKEN`,
GitHub via `GITHUB_TOKEN` (used by the `gh` CLI).

Hook scripts (`plugins/onex/hooks/scripts/`) run in the same subprocess environment. If
`KAFKA_BOOTSTRAP_SERVERS` is set, the emit daemon will attempt to connect; if not set,
events are silently dropped (hooks still exit 0).

## Resume after rate limits

Checkpoints are written to `~/.claude/pipelines/{ticket_id}/state.yaml` after every phase
transition. If the `claude -p` process is interrupted (rate limit, network drop, process
kill), resume from the last completed phase:

```bash
claude -p "Run ticket-pipeline for <TICKET-ID> --skip-to ci_watch" \
  --allowedTools "Bash,Read,Write,Edit,Glob,Grep,mcp__linear-server__*,mcp__slack__*"
```

Auto-detection picks up the correct phase automatically when no `--skip-to` flag is
provided and a state file already exists.

## Trigger surfaces

| Surface | How |
|---------|-----|
| **CLI (direct)** | `claude -p "Run ticket-pipeline for <TICKET-ID>" --allowedTools "..."` |
| **Slack bot** | Webhook handler constructs the `claude -p` call and spawns it as a subprocess |
| **Webhook** | HTTP handler receives ticket ID, sets env vars, invokes `claude -p` |
| **Cron / CI** | Shell script iterates tickets and calls `claude -p` per ticket |
