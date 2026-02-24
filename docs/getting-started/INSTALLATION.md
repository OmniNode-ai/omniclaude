# Installation Guide

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) installed
- Claude Code CLI installed

## 1. Install Dependencies

```bash
cd /path/to/omniclaude
uv sync
uv sync --group dev  # For development tools (ruff, mypy, bandit, pytest)
```

## 2. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your values. Minimum required for event emission:

```bash
# Kafka — use host port for scripts running outside Docker
KAFKA_BOOTSTRAP_SERVERS=<kafka-bootstrap-servers>:9092

# PostgreSQL (optional — enables database logging)
POSTGRES_HOST=<postgres-host>
POSTGRES_PORT=5436
POSTGRES_DATABASE=omninode_bridge
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<your_password>

# Feature flags (all optional — hooks degrade gracefully without them)
USE_EVENT_ROUTING=true          # Kafka-based agent routing
ENABLE_POSTGRES=true            # Database logging
ENFORCEMENT_MODE=warn           # warn | block | silent
```

See [CLAUDE.md](../../CLAUDE.md) for the complete environment variable reference.

## 3. Deploy the Plugin

The plugin files live in `plugins/onex/` and must be deployed to Claude Code's
plugin cache so that Claude Code can find the hook scripts and agent definitions
at runtime.

The canonical deploy path is `~/.claude/plugins/cache/`. After deployment, the
`CLAUDE_PLUGIN_ROOT` environment variable (injected by Claude Code) points into
that cache directory.

Use the deploy skill from within an active Claude Code session:

```
/deploy-local-plugin
```

Or check whether a deploy script exists in the repo root:

```bash
ls scripts/deploy*.sh 2>/dev/null || echo "No deploy script found — use /deploy-local-plugin"
```

## 4. Verify Hook Configuration

The hook configuration lives in `plugins/onex/hooks/hooks.json`. Validate it
with:

```bash
jq . plugins/onex/hooks/hooks.json
```

Expected hooks registered (from the current `hooks.json`):

| Hook | Matcher | Script |
|------|---------|--------|
| `SessionStart` | (all) | `session-start.sh` |
| `SessionEnd` | (all) | `session-end.sh` |
| `UserPromptSubmit` | (all) | `user-prompt-submit.sh` |
| `PreToolUse` | `^(Edit\|Write)$` | `pre_tool_use_authorization_shim.sh` |
| `PostToolUse` | `^(Read\|Write\|Edit\|Bash\|Glob\|Grep\|Task\|Skill\|WebFetch\|WebSearch\|NotebookEdit\|NotebookRead)$` | `post-tool-use-quality.sh` |

Verify hook scripts are executable:

```bash
ls -la plugins/onex/hooks/scripts/*.sh
```

All `.sh` files must have execute permission (`-rwxr-xr-x`). If they do not:

```bash
chmod +x plugins/onex/hooks/scripts/*.sh
```

## 5. Verify the Emit Daemon

After starting a Claude Code session, the `SessionStart` hook automatically
starts the emit daemon. The daemon listens on a Unix socket and forwards events
to Kafka.

Check its status from the project root:

```bash
uv run python plugins/onex/hooks/lib/emit_client_wrapper.py status --json
```

Expected output when daemon is running:

```json
{
  "client_available": true,
  "socket_path": "/var/folders/.../omniclaude-emit.sock",
  "daemon_running": true
}
```

If `daemon_running` is `false`, the SessionStart hook has not run yet. Open a
new Claude Code session in this project directory to trigger it.

Ping the daemon directly:

```bash
uv run python plugins/onex/hooks/lib/emit_client_wrapper.py ping
```

## 6. Verify Agent Routing

Test that the routing wrapper is importable and wired:

```bash
uv run python -c "
import sys
sys.path.insert(0, 'plugins/onex/hooks/lib')
from route_via_events_wrapper import RouteViaEventsWrapper
print('Routing wrapper OK')
"
```

If `USE_EVENT_ROUTING=true` is set and `KAFKA_BOOTSTRAP_SERVERS` is reachable,
routing requests will be sent to Kafka during `UserPromptSubmit`. Without those,
routing falls back to the `polymorphic-agent` (exit 0, no blocking).

## Environment Variables

### Required (for event emission)

| Variable | Purpose |
|----------|---------|
| `KAFKA_BOOTSTRAP_SERVERS` | Kafka connection string (e.g. `<kafka-bootstrap-servers>:9092` for host scripts) |

### Optional

| Variable | Default | Purpose |
|----------|---------|---------|
| `USE_EVENT_ROUTING` | `false` | Enable Kafka-based agent routing |
| `ENABLE_POSTGRES` | `false` | Enable database logging to omninode_bridge |
| `ENFORCEMENT_MODE` | `warn` | Quality enforcement: `warn`, `block`, `silent` |
| `LLM_CODER_URL` | — | Local LLM endpoint for delegation (port 8000) |
| `LLM_CODER_FAST_URL` | — | Fast LLM for delegation (port 8001) |
| `OMNICLAUDE_PROJECT_ROOT` | — | Explicit project root for dev-mode venv resolution |
| `PLUGIN_PYTHON_BIN` | — | Override Python interpreter path (escape hatch) |
| `KAFKA_ENVIRONMENT` | — | Environment label for observability (not used for topic prefixing) |

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Hook fails with exit 1 | Python interpreter not found | Set `OMNICLAUDE_PROJECT_ROOT` or `PLUGIN_PYTHON_BIN` |
| `daemon_running: false` | SessionStart hook did not run | Open/restart Claude Code session in project directory |
| Events not arriving in Kafka | Daemon started but Kafka unreachable | Check `KAFKA_BOOTSTRAP_SERVERS`; verify port 29092 is accessible |
| Routing always returns `polymorphic-agent` | Routing service timeout (5 s) | Check network to Kafka; set `USE_EVENT_ROUTING=false` to disable |
| Context injection empty | PostgreSQL unreachable | Check `POSTGRES_HOST`/`POSTGRES_PORT` in `.env` |

See [CLAUDE.md](../../CLAUDE.md) for the complete failure mode table.
