# Quick Start: Zero to Instrumented Session in 10 Minutes

This walkthrough takes you from a fresh clone to a fully instrumented Claude Code
session with events flowing to Kafka and agent routing active.

---

## Step 1: Clone and Install (2 min)

```bash
git clone <repo-url> omniclaude
cd omniclaude
uv sync
uv sync --group dev
```

Verify Python version:

```bash
uv run python --version
# Python 3.12.x
```

---

## Step 2: Configure Environment (2 min)

```bash
cp .env.example .env
```

Open `.env` and set at minimum:

```bash
KAFKA_BOOTSTRAP_SERVERS=<kafka-bootstrap-servers>:9092
```

For full observability, also set the Postgres variables:

```bash
POSTGRES_HOST=<postgres-host>
POSTGRES_PORT=5436
POSTGRES_DATABASE=omninode_bridge
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<your_password>
ENABLE_POSTGRES=true
```

To enable Kafka-based agent routing:

```bash
USE_EVENT_ROUTING=true
```

> **Infrastructure note**: Kafka (Redpanda) and PostgreSQL run on `<your-infrastructure-host>`.
> Port 29092 is the externally published Kafka port for host scripts. See
> `~/.claude/CLAUDE.md` for the full infrastructure topology.

---

## Step 3: Deploy the Plugin (1 min)

The plugin hooks are only active when deployed to Claude Code's plugin cache.
From within a Claude Code session in this project:

```
/deploy-local-plugin
```

After deployment, `plugins/onex/` is copied to `~/.claude/plugins/cache/` and
Claude Code will load it on the next session start.

Verify the hook config is valid:

```bash
jq . plugins/onex/hooks/hooks.json
# Should print the JSON without errors
```

---

## Step 4: Start a Claude Code Session

Open Claude Code in the `omniclaude` directory. The `SessionStart` hook runs
automatically. It:

1. Reads the session context from stdin
2. Starts the emit daemon (if not already running)
3. Emits a `session.started` event to Kafka

The daemon persists across hook invocations for the lifetime of the session.

---

## Step 5: Verify Events are Flowing

### Check the daemon

In a terminal (outside Claude Code):

```bash
uv run python plugins/onex/hooks/lib/emit_client_wrapper.py status --json
```

Expected:

```json
{
  "client_available": true,
  "socket_path": "/var/folders/.../omniclaude-emit.sock",
  "daemon_running": true
}
```

### Watch the hook log

The PostToolUse hook writes to a rolling log. Watch it in a terminal:

```bash
tail -f plugins/onex/hooks/logs/post-tool-use.log
```

When Claude uses any matched tool (Read, Write, Edit, Bash, etc.), you will see
lines like:

```
[2026-02-19T...] PostToolUse hook triggered for Read (plugin mode)
[2026-02-19T...] Tool Read not applicable for auto-fix
[2026-02-19T...] Tool event emission started
```

### Watch the pipeline trace log

For a higher-level view of Skill and Task dispatching:

```bash
tail -f ~/.claude/logs/pipeline-trace.log
```

Lines look like:

```
[2026-02-19T...] [PostToolUse] SKILL_LOADED skill=commit args=[REDACTED]
[2026-02-19T...] [PostToolUse] FILE_MODIFIED tool=Write file=example.py path=/path/to/example.py
```

### Verify events in Redpanda Console

Open `http://<redpanda-console-host>:8080` in a browser and navigate to the Topics view.
Look for messages on:

- `onex.evt.omniclaude.session-started.v1` — session start events
- `onex.evt.omniclaude.prompt-submitted.v1` — 100-character prompt previews
- `onex.evt.omniclaude.tool-executed.v1` — per-tool events

---

## Step 6: Try Agent Routing

Type a prompt in Claude Code that matches a specific agent. For example:

```
Design a REST API for user authentication
```

With `USE_EVENT_ROUTING=true`, the `UserPromptSubmit` hook sends this to the
routing service. The routing service scores candidate agents and returns a ranked
list. Claude Code receives the candidates in `hookSpecificOutput.additionalContext`
and selects the best match.

To see the routing decision in the hook log:

```bash
# UserPromptSubmit hook does not have its own log file; check the hooks.log
# if LOG_FILE is set, or watch stderr output from the shell script
tail -f ~/.claude/hooks.log 2>/dev/null || echo "LOG_FILE not set — routing decisions go to routing service"
```

If routing times out (5 s), the hook falls back to `polymorphic-agent` and exits
0. The session is never blocked.

---

## Step 7: What to Do Next

| Goal | Where to go |
|------|------------|
| Full installation reference | [INSTALLATION.md](./INSTALLATION.md) |
| Add a custom PostToolUse handler | [FIRST_HOOK.md](./FIRST_HOOK.md) |
| Architecture and data flow | [CLAUDE.md](../../CLAUDE.md) |
| Hook event schemas | `src/omniclaude/hooks/schemas.py` |
| Agent YAML format | `plugins/onex/agents/configs/` |
| Kafka topic reference | `src/omniclaude/hooks/topics.py` |
| Architecture decision records | `docs/adr/` |

---

## Performance Expectations

| Hook | Typical latency |
|------|----------------|
| SessionStart | < 50 ms (sync path) |
| SessionEnd | < 50 ms |
| UserPromptSubmit | < 500 ms (up to 15 s worst-case with delegation) |
| PostToolUse | < 100 ms |

All hooks exit 0 on infrastructure failure. If Kafka is unreachable, events are
dropped silently and Claude Code continues normally.
