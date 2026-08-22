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

The plugin files live in `plugins/onex/`. Claude Code finds the hook scripts and agent
definitions at whatever path the plugin's **marketplace source** resolves to — which is
not necessarily a copy in the plugin cache.

`CLAUDE_PLUGIN_ROOT` (injected by Claude Code) does **not** reliably point into
`~/.claude/plugins/cache/`. Published Claude Code docs describe marketplace plugins as
being copied to that cache; observed behavior for a `directory`-source marketplace on
a live workstation contradicts it — the resolved root is the marketplace's own
`installLocation`, i.e. the source checkout, and the cache is never read
(OMN-15274/OMN-15244). Treat the copy semantics as unverified and read the load path
back instead of assuming either answer:

```bash
python3 plugins/onex/hooks/lib/plugin_deploy_readback.py
```

Deploy via the Claude Code plugin marketplace, from a terminal:

```bash
claude plugin marketplace update omninode-tools
claude plugin uninstall onex@omninode-tools && claude plugin install onex@omninode-tools
# restart the Claude Code session to pick up hooks/skills
```

## 4. Verify Hook Configuration

The hook configuration lives in `plugins/onex/hooks/hooks.json`. Validate it
with:

```bash
jq . plugins/onex/hooks/hooks.json
```

Expected hook event types registered (from the current `hooks.json`):

| Hook | Matcher | Notes |
|------|---------|-------|
| `SessionStart` | (all) | Session lifecycle logging, daemon startup, venv pin check |
| `SessionEnd` | (all) | Session cleanup and finalization |
| `UserPromptSubmit` | (all) | Agent routing, context injection, delegation enforcement |
| `PreToolUse` | (various) | Authorization, branch protection, dispatch guards, model routing |
| `PostToolUse` | `^(Read\|Write\|Edit\|Bash\|Glob\|Grep\|Task\|Skill\|...)$` | Quality enforcement, pattern tracking |
| `Stop` | (all) | Graceful shutdown, quality gate, skip-token surface guard |
| `SubagentStart` | (all) | Subagent session marker creation |
| `SubagentStop` | (all) | Subagent claim verification, skip-token surface guard |
| `PermissionDenied` | (all) | Permission denial logging |
| `StopFailure` | (all) | Stop failure logging |
| `PreCompact` | (all) | Pre-compaction hook |

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
routing falls back to the `general-purpose` (exit 0, no blocking).

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
| `PLUGIN_PYTHON_BIN` | — | Override Python interpreter path (escape hatch) |
| `KAFKA_ENVIRONMENT` | — | Environment label for observability (not used for topic prefixing) |

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Hook fails with exit 1 | Python interpreter not found | Set `PLUGIN_PYTHON_BIN` or run `scripts/repair-plugin-venv.sh` |
| `daemon_running: false` | SessionStart hook did not run | Open/restart Claude Code session in project directory |
| Events not arriving in Kafka | Daemon started but Kafka unreachable | Check `KAFKA_BOOTSTRAP_SERVERS`; verify port 29092 is accessible |
| Routing always returns `general-purpose` | Routing service timeout (5 s) | Check network to Kafka; set `USE_EVENT_ROUTING=false` to disable |
| Context injection empty | PostgreSQL unreachable | Check `POSTGRES_HOST`/`POSTGRES_PORT` in `.env` |

See [CLAUDE.md](../../CLAUDE.md) for the complete failure mode table.
