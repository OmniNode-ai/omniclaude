# OmniClaude Investor Demo: Hook Emission Pipeline

## Overview

This demo shows Claude Code hooks emitting **typed ONEX events** to Kafka in real-time. Every session start, prompt, tool use, and session end becomes a structured, validated event flowing through the event bus.

The hook emission pipeline captures the full lifecycle of a Claude Code session:

```
Claude Code Session
  |
  +-- SessionStart hook   --> session.started event
  +-- UserPromptSubmit    --> prompt.submitted event (dual emission)
  +-- PostToolUse         --> tool.executed event
  +-- SessionEnd hook     --> session.ended + session.outcome events
```

Each event is a frozen Pydantic model with correlation IDs, causation chains, and automatic secret redaction. Events flow through a Unix socket to an in-process publisher daemon, then fan out to Kafka topics.

---

## Prerequisites

1. **Kafka/Redpanda** running at `192.168.86.200:29092` (or as configured in `.env`)
2. **`KAFKA_BOOTSTRAP_SERVERS`** set in the repository `.env` file
3. **Python environment** ready:
   ```bash
   cd /Volumes/PRO-G40/Code/omniclaude3
   uv sync --group dev
   ```
4. **`OMNICLAUDE_PROJECT_ROOT`** set to the repo root (for dev-mode Python venv resolution):
   ```bash
   export OMNICLAUDE_PROJECT_ROOT=/Volumes/PRO-G40/Code/omniclaude3
   ```

### Related Tickets (Full Cross-Repo Demo)

This demo covers the **omniclaude** slice. For the full investor demo spanning all repositories:

- **OMN-1525** -- Parent ticket: Investor demo orchestration
- **OMN-2081** -- omnibase_infra: Runtime contract routing verification
- **OMN-2082** -- omnidash: Real-time dashboard visualization

---

## Pre-flight Check

Run the verification script to confirm infrastructure is ready:

```bash
python scripts/demo_runner.py --check
```

Expected output:

```
=== OmniClaude Demo Pre-flight Check ===

[PASS] Emit daemon socket exists at /tmp/omniclaude-emit.sock
[PASS] Emit daemon responds to ping
[PASS] Kafka reachable at 192.168.86.200:29092
[PASS] ONEX topics found: onex.evt.omniclaude.session-started.v1, ...
[PASS] Intelligence topics found: onex.cmd.omniintelligence.claude-hook-event.v1, ...

All checks passed. Ready for demo.
```

If any check fails, see the Troubleshooting section below.

---

## Demo Walkthrough

### Step 1: Start Claude Code

Open a terminal and start Claude Code in this repository:

```bash
cd /Volumes/PRO-G40/Code/omniclaude3
claude
```

**What happens**: The `SessionStart` hook fires and emits a `session.started` event.

**Event emitted to**: `onex.evt.omniclaude.session-started.v1`

**Key payload fields**:
- `session_id` -- Unique session identifier (UUID)
- `working_directory` -- Repository path
- `git_branch` -- Current branch name
- `hook_source` -- `startup` (or `resume`, `clear`, `compact`)
- `emitted_at` -- UTC timestamp (explicitly injected, never defaulted)

**Performance budget**: <50ms synchronous path

---

### Step 2: Submit a Prompt

Type any prompt in Claude Code, for example:

```
What files are in the src/ directory?
```

**What happens**: The `UserPromptSubmit` hook fires and performs **dual emission**:

1. **Public topic** (`onex.evt.omniclaude.prompt-submitted.v1`):
   - `prompt_preview` -- First 100 characters, with secrets automatically redacted
   - `prompt_length` -- Full character count
   - `detected_intent` -- Classified intent (question, fix, workflow, etc.)

2. **Intelligence topic** (`onex.cmd.omniintelligence.claude-hook-event.v1`):
   - Full prompt content (restricted access, consumed only by OmniIntelligence)

**Privacy design**: The public topic never receives the full prompt. API keys, passwords, bearer tokens, and other secrets are pattern-matched and replaced with `***REDACTED***` before emission.

**Performance budget**: <500ms typical synchronous path

---

### Step 3: Use a Tool

Claude Code will use tools to answer your prompt. For example, it might use `Bash`, `Read`, `Glob`, or `Grep`.

**What happens**: The `PostToolUse` hook fires for each tool invocation and emits a `tool.executed` event.

**Event emitted to**: `onex.evt.omniclaude.tool-executed.v1`

**Key payload fields**:
- `tool_name` -- Name of the tool (`Read`, `Write`, `Edit`, `Bash`, `Glob`, `Grep`, etc.)
- `success` -- Whether the tool execution succeeded
- `duration_ms` -- Execution time in milliseconds
- `summary` -- Brief description of the result (max 500 chars)
- `tool_execution_id` -- Unique identifier for this invocation

**Matched tools** (from `hooks.json`):
`Read`, `Write`, `Edit`, `Bash`, `Glob`, `Grep`, `Task`, `Skill`, `WebFetch`, `WebSearch`, `NotebookEdit`, `NotebookRead`

**Performance budget**: <100ms synchronous path

---

### Step 4: End the Session

Exit Claude Code by typing `/clear` or pressing Ctrl+C.

**What happens**: The `SessionEnd` hook fires and emits two events:

1. **`onex.evt.omniclaude.session-ended.v1`**:
   - `reason` -- Why the session ended (`clear`, `logout`, `prompt_input_exit`, `other`)
   - `duration_seconds` -- Total session duration
   - `tools_used_count` -- Number of tool invocations during the session

2. **`onex.evt.omniclaude.session-outcome.v1`** (+ `onex.cmd.omniintelligence.session-outcome.v1`):
   - `outcome` -- Classification: `success`, `failed`, `abandoned`, or `unknown`
   - Feeds back into the intelligence system for routing improvement

**Performance budget**: <50ms synchronous path

---

### Step 5: Verify Events Arrived

After the demo session, verify that events were published to Kafka:

```bash
python scripts/demo_runner.py --verify
```

Expected output:

```
=== OmniClaude Demo Event Verification ===

Checking recent events (last 60 seconds)...

onex.evt.omniclaude.session-started.v1:
  [12:05:01] session_id=abc12345... hook_source=startup working_dir=/Volumes/PRO-G40/Code/omniclaude3

onex.evt.omniclaude.prompt-submitted.v1:
  [12:05:15] session_id=abc12345... preview="What files are in the..." length=42

onex.evt.omniclaude.tool-executed.v1:
  [12:05:16] session_id=abc12345... tool=Glob success=True duration=23ms
  [12:05:17] session_id=abc12345... tool=Read success=True duration=12ms

onex.evt.omniclaude.session-ended.v1:
  [12:06:00] session_id=abc12345... reason=clear duration=59.0s tools_used=2

onex.evt.omniclaude.session-outcome.v1:
  [12:06:00] session_id=abc12345... outcome=success

Summary: 5 events across 5 topics
```

To see all ONEX topics and message counts:

```bash
python scripts/demo_runner.py --topics
```

---

## Talking Points

Key architecture points for the investor audience:

### "Hooks, not plugins"
Claude Code fires hooks at every lifecycle point -- session start, prompt submission, tool use, session end. Our hooks capture events at zero additional latency because they run in the same process. No sidecar, no separate agent, no polling.

### "Typed events, not string parsing"
Every event is a frozen Pydantic model (`ModelHookSessionStartedPayload`, `ModelHookPromptSubmittedPayload`, etc.) with strict validation. Fields have type constraints, length limits, and semantic validators. The schema is the contract.

### "Privacy by design"
Dual emission separates public observability from sensitive intelligence data. Public topics (`onex.evt.*`) receive only 100-character sanitized previews with automatic secret redaction (API keys, passwords, bearer tokens, JWTs, PEM keys). Full prompts go only to restricted intelligence topics (`onex.cmd.omniintelligence.*`).

### "Fail-open architecture"
Hooks never block Claude Code. If Kafka is down, events are dropped and the hook exits 0. If the emit daemon crashes, the hook continues. Data loss is acceptable; UI freeze is not. Every failure mode has been explicitly designed.

### "Event-driven, not request-driven"
The same Kafka event stream feeds dashboards (omnidash), memory/learning (omniintelligence), analytics, and debugging. Adding a new consumer requires zero changes to the producer. The event bus is the integration point.

### "30+ event types"
The `TopicBase` enum defines 30+ topic types covering: session lifecycle, prompt submission, tool execution, context injection, agent routing decisions, routing feedback, manifest injection, latency breakdowns, agent matching, phase metrics, agent status, notification tracking, and transformation events.

### "Deterministic and replayable"
Every event carries explicit `emitted_at` timestamps (never `datetime.now()` defaults), `correlation_id` for distributed tracing, and `causation_id` for causal chains. Events can be replayed from Kafka for debugging, training data extraction, or system reconstruction.

---

## Troubleshooting

### Kafka not reachable

**Symptom**: `--check` reports Kafka connectivity failure.

**Fix**:
1. Verify the Kafka/Redpanda server is running on `192.168.86.200`:
   ```bash
   kcat -L -b 192.168.86.200:29092
   ```
2. Check `KAFKA_BOOTSTRAP_SERVERS` in `.env`:
   ```bash
   source .env && echo "$KAFKA_BOOTSTRAP_SERVERS"
   ```
3. For host scripts, use port `29092` (external). Port `9092` is for Docker-internal traffic only.

### Emit daemon not running

**Symptom**: `--check` reports daemon socket missing or not responding.

**Fix**:
1. Start a Claude Code session -- the `SessionStart` hook automatically starts the daemon.
2. Check daemon logs:
   ```bash
   ls -la ~/.claude/plugins/cache/*/hooks/logs/emit-daemon.log
   ```
3. Verify the socket exists:
   ```bash
   ls -la /tmp/omniclaude-emit.sock
   ```
4. Test manually:
   ```bash
   python plugins/onex/hooks/lib/emit_client_wrapper.py ping
   ```

### No Python venv found

**Symptom**: Hook scripts fail with "No valid Python interpreter found".

**Fix**:
1. Set `OMNICLAUDE_PROJECT_ROOT` to the repository root:
   ```bash
   export OMNICLAUDE_PROJECT_ROOT=/Volumes/PRO-G40/Code/omniclaude3
   ```
2. Ensure the venv exists:
   ```bash
   uv sync --group dev
   ```
3. Or set `PLUGIN_PYTHON_BIN` explicitly as an escape hatch:
   ```bash
   export PLUGIN_PYTHON_BIN=$(which python3)
   ```

### Stale socket file

**Symptom**: Daemon appears running but events are not being emitted.

**Fix**:
```bash
rm /tmp/omniclaude-emit.sock
```
Then start a new Claude Code session to restart the daemon.

### Events not appearing in Kafka

**Symptom**: `--verify` shows zero events.

**Fix**:
1. Confirm the daemon is running (see above).
2. Check hook logs for emission errors:
   ```bash
   ls -la ~/.claude/plugins/cache/*/hooks/logs/hook-*.log
   ```
3. Verify `KAFKA_ENVIRONMENT` is set (used as topic prefix):
   ```bash
   source .env && echo "$KAFKA_ENVIRONMENT"
   ```
4. Check Redpanda Console at `http://192.168.86.200:8080` for topic activity.

### Hook logs location

All hook logs are written to the plugin cache directory:

```
~/.claude/plugins/cache/*/hooks/logs/
  emit-daemon.log         -- Publisher daemon logs
  hook-session-start.log  -- SessionStart hook logs
  hook-session-end.log    -- SessionEnd hook logs
  hook-enhanced.log       -- UserPromptSubmit hook logs
  post-tool-use.log       -- PostToolUse hook logs
```

---

## Architecture Reference

### Event Flow

```
Hook Script (bash)
    |
    v
emit_client_wrapper.py  -->  emit_via_daemon()
    |
    v
Unix Domain Socket (/tmp/omniclaude-emit.sock)
    |
    v
Publisher Daemon (src/omniclaude/publisher/)
    |
    v
Kafka / Redpanda (192.168.86.200:29092)
    |
    +-- onex.evt.omniclaude.*          (public observability)
    +-- onex.cmd.omniintelligence.*    (restricted intelligence)
```

### Key Source Files

| File | Purpose |
|------|---------|
| `plugins/onex/hooks/hooks.json` | Hook configuration (matchers, scripts) |
| `plugins/onex/hooks/scripts/session-start.sh` | Session start hook script |
| `plugins/onex/hooks/scripts/session-end.sh` | Session end hook script |
| `plugins/onex/hooks/scripts/user-prompt-submit.sh` | Prompt submission hook script |
| `plugins/onex/hooks/scripts/post-tool-use-quality.sh` | Tool use hook script |
| `plugins/onex/hooks/lib/emit_client_wrapper.py` | Socket-based emit client |
| `src/omniclaude/publisher/` | Publisher daemon (Kafka producer) |
| `src/omniclaude/hooks/schemas.py` | Frozen Pydantic event schemas |
| `src/omniclaude/hooks/topics.py` | `TopicBase` enum (all topic names) |

### Performance Budgets (Synchronous Path)

| Hook | Budget | What Blocks | What Is Backgrounded |
|------|--------|-------------|----------------------|
| SessionStart | <50ms | Daemon check, stdin read | Kafka emit, Postgres log |
| UserPromptSubmit | <500ms typical | Routing, agent load, context injection | Kafka emit, intelligence requests |
| PostToolUse | <100ms | stdin read, quality check | Kafka emit, content capture |
| SessionEnd | <50ms | stdin read | Kafka emit, Postgres log |
