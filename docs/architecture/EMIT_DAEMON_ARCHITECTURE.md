# Emit Daemon Architecture

**Last Updated**: 2026-02-19
**Tickets**: OMN-1631 (emit daemon integration), OMN-1632 (hook migration), OMN-1945 (EmitClient moved to omniclaude)

---

## Overview

The emit daemon decouples event emission from hook execution. Hooks call `emit_event()` and return immediately — they never block on Kafka. The daemon runs as a background process, receives events via a Unix domain socket, fans them out to multiple Kafka topics, and handles Kafka unavailability by buffering briefly before dropping. This architecture ensures that a Kafka outage never freezes the Claude Code UI.

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                   Claude Code Hook (Python)                      │
│                                                                  │
│   emit_client_wrapper.emit_event("prompt.submitted", payload)    │
│         │                                                        │
│         │  _SocketEmitClient._request()                         │
│         │  JSON newline-delimited protocol                       │
│         ▼                                                        │
│   Unix Domain Socket                                             │
│   Path: tempfile.gettempdir() / "omniclaude-emit.sock"          │
│   (macOS: /var/folders/.../omniclaude-emit.sock)                 │
│   (Linux: /tmp/omniclaude-emit.sock)                             │
└────────────────────────┬────────────────────────────────────────┘
                         │  Request:  {"event_type": "...", "payload": {...}}\n
                         │  Response: {"status": "queued", "event_id": "..."}\n
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                       Emit Daemon                                │
│   (started by SessionStart, persists across hook invocations)   │
│                                                                  │
│   EventRegistry.dispatch(event_type, payload)                   │
│         │                                                        │
│         ├── event_type = "prompt.submitted"                     │
│         │     ├─► onex.evt.omniclaude.prompt-submitted.v1       │
│         │     │       payload: {prompt_preview: "<100 chars>"}   │
│         │     │       (redacted, preview-safe)                  │
│         │     │                                                  │
│         │     └─► onex.cmd.omniintelligence.claude-hook-event.v1│
│         │               payload: {prompt: "<full text>"}         │
│         │               (full prompt, restricted topic)          │
│         │                                                        │
│         ├── event_type = "session.started"                      │
│         │     └─► onex.evt.omniclaude.session-started.v1        │
│         │                                                        │
│         ├── event_type = "routing.decision"                     │
│         │     └─► onex.evt.omniclaude.routing-decision.v1       │
│         │                                                        │
│         └── (other event types — see SUPPORTED_EVENT_TYPES)     │
│                                                                  │
│   KafkaProducer → KAFKA_BOOTSTRAP_SERVERS                       │
└─────────────────────────────────────────────────────────────────┘
                         │
                         ▼
              Kafka/Redpanda (192.168.86.200:29092)
```

---

## Socket Protocol

The daemon speaks a simple newline-delimited JSON protocol over a Unix SOCK_STREAM socket. Each request is a single JSON object followed by `\n`. The daemon responds with a single JSON object followed by `\n`.

**Emit request:**
```json
{"event_type": "prompt.submitted", "payload": {"session_id": "uuid", "prompt_preview": "..."}}
```

**Emit response (success):**
```json
{"status": "queued", "event_id": "abc-123"}
```

**Ping request:**
```json
{"command": "ping"}
```

**Ping response:**
```json
{"status": "ok", "queue_size": 0, "spool_size": 0}
```

The client (`_SocketEmitClient`) uses a connection-per-request pattern — a fresh socket connection is opened for each emit. This avoids persistent connection state but adds slight overhead per call. The overhead is acceptable because emits are backgrounded and not on the critical path.

---

## Daemon Startup

The daemon is started by the `SessionStart` hook shell script (`session-start.sh`). Startup is guarded so the daemon launches only once, even if SessionStart fires multiple times on reconnect (idempotency invariant).

```
SessionStart fires
    │
    ▼
session-start.sh
    │
    ├─ daemon_available() → ping socket
    │     │
    │     ├─ OK: daemon already running, skip launch
    │     │
    │     └─ FAIL: start daemon process in background
    │           nohup python emit_daemon.py &
    │
    └─ Emit session.started event
```

Once started, the daemon persists across all subsequent hook invocations for the session. It runs as a child process of the shell, not attached to Claude Code itself.

---

## Fan-Out: One Hook Event, Multiple Kafka Messages

A single `emit_event()` call in a hook can produce multiple Kafka messages. The daemon's `EventRegistry` maps each semantic `event_type` string to one or more Kafka topic writes. This fan-out is the key architectural abstraction — hooks specify what happened, the daemon decides which topics need to know.

The most significant fan-out is `prompt.submitted`, which writes to two topics with different payloads:

| event_type | Kafka Topic | Payload | Access |
|-----------|-------------|---------|--------|
| `prompt.submitted` | `onex.evt.omniclaude.prompt-submitted.v1` | 100-char redacted preview | Broad (any consumer) |
| `prompt.submitted` | `onex.cmd.omniintelligence.claude-hook-event.v1` | Full prompt text | Restricted (OmniIntelligence only) |

This dual-emission enforces the privacy boundary: observability consumers get only the preview, while the intelligence service gets the full prompt for analysis.

---

## Dual-Emission: Privacy Boundary

The omniclaude CLAUDE.md invariant "Only preview-safe data goes to `onex.evt.*` topics" is enforced in the daemon's fan-out logic, not in the hook itself. The hook calls `emit_event("prompt.submitted", {...})` once. The daemon is responsible for writing the sanitized payload to the `evt.*` topic and the full payload to the `cmd.omniintelligence.*` topic.

Secret redaction in `prompt_preview`:
- OpenAI keys (`sk-*`)
- AWS keys (`AKIA*`)
- GitHub tokens (`ghp_*`)
- Slack tokens (`xox*`)
- PEM keys
- Bearer tokens
- Passwords in URLs

The `secret_redactor.py` module performs this redaction. The routing wrapper also calls it independently before emitting `routing.decision` events that include a prompt preview.

---

## Supported Event Types

As of 2026-02-19, the client (`SUPPORTED_EVENT_TYPES` in `emit_client_wrapper.py`) recognizes these event type strings:

```
session.started          → onex.evt.omniclaude.session-started.v1
session.ended            → onex.evt.omniclaude.session-ended.v1
session.outcome          → onex.evt.omniclaude.session-outcome.v1 + cmd variant
prompt.submitted         → onex.evt.omniclaude.prompt-submitted.v1 (fan-out: 2 topics)
tool.executed            → onex.evt.omniclaude.tool-executed.v1
injection.recorded       → onex.evt.omniclaude.injection-recorded.v1
context.utilization      → onex.evt.omniclaude.context-utilization.v1
agent.match              → onex.evt.omniclaude.agent-match.v1
latency.breakdown        → onex.evt.omniclaude.latency-breakdown.v1
routing.decision         → onex.evt.omniclaude.routing-decision.v1
routing.feedback         → onex.evt.omniclaude.routing-feedback.v1
routing.skipped          → onex.evt.omniclaude.routing-feedback-skipped.v1
notification.blocked     → onex.evt.omniclaude.notification-blocked.v1
notification.completed   → onex.evt.omniclaude.notification-completed.v1
phase.metrics            → onex.evt.omniclaude.phase-metrics.v1
agent.status             → onex.evt.agent.status.v1
compliance.evaluate      → onex.cmd.omniintelligence.compliance-evaluate.v1
static.context.edit.detected → onex.evt.omniclaude.static-context-edit-detected.v1
llm.routing.decision     → onex.evt.omniclaude.llm-routing-decision.v1
llm.routing.fallback     → onex.evt.omniclaude.llm-routing-fallback.v1
context.enrichment       → onex.evt.omniclaude.context-enrichment.v1
```

The client validates the `event_type` against this frozenset before connecting to the daemon. Unknown event types are rejected with a WARNING log and `emit_event()` returns `False`.

---

## Client Initialization

The `_SocketEmitClient` is initialized lazily on the first call to `emit_event()`. It is cached as a module-level singleton (`_emit_client`). The socket path defaults to `tempfile.gettempdir() / "omniclaude-emit.sock"` (computed per-call to handle `$TMPDIR` changes), but can be overridden via `OMNICLAUDE_EMIT_SOCKET`. The connection timeout defaults to 5.0 seconds and can be overridden via `OMNICLAUDE_EMIT_TIMEOUT`.

`reset_client()` is provided for tests and for forcing re-reading of environment variables after the first call.

When called from an async context (detected via `asyncio.get_running_loop()`), the synchronous socket call is offloaded to a `ThreadPoolExecutor` to avoid blocking the event loop.

---

## Buffer and Drop Behavior

When Kafka is unavailable:
1. The daemon's internal queue holds events briefly (exact buffer size and TTL depend on the daemon's own configuration, separate from this repo).
2. If Kafka remains unavailable after the buffer window, events are dropped with a log entry.
3. The client receives `{"status": "queued", "event_id": "..."}` as long as the daemon accepted the event — the daemon does not wait for Kafka acknowledgment before responding.

This means `emit_event()` returning `True` indicates the daemon received the event, not that Kafka received it.

---

## Failure Modes

| Failure | Client Behavior | Exit Code | Data Loss |
|---------|----------------|-----------|-----------|
| Daemon socket not found (daemon not started) | `FileNotFoundError` → WARNING log → returns `False` | 0 | Yes (event dropped) |
| Daemon not accepting connections | `ConnectionRefusedError` → WARNING log → returns `False` | 0 | Yes (event dropped) |
| Socket timeout | `TimeoutError` → WARNING log → returns `False` | 0 | Yes (event dropped) |
| Broken pipe (daemon died mid-request) | `BrokenPipeError` → WARNING log → returns `False` | 0 | Yes (event dropped) |
| Kafka unavailable (daemon knows) | Daemon buffers, then drops. Client sees `queued`. | 0 | Yes (eventual drop) |
| Malformed payload (bad types) | `TypeError/ValueError` → ERROR log → returns `False` | 0 | Yes (event dropped) |
| Unknown event type | WARNING log → returns `False` before connecting | 0 | Yes (event dropped) |
| Daemon response exceeds 1MB | `ConnectionError` → WARNING log → returns `False` | 0 | Uncertain |

The design principle is: data loss is acceptable, UI freeze is not. Hooks call `emit_event()` in background threads (or fire-and-forget) and never wait for the return value to decide whether to proceed.

---

## Diagnostic Commands

```bash
# Check daemon status
python plugins/onex/hooks/lib/emit_client_wrapper.py status --json

# Ping daemon
python plugins/onex/hooks/lib/emit_client_wrapper.py ping

# Emit a test event
python plugins/onex/hooks/lib/emit_client_wrapper.py emit \
    --event-type session.started \
    --payload '{"session_id": "test-123"}'
```

---

## Key Files

| File | Role |
|------|------|
| `plugins/onex/hooks/lib/emit_client_wrapper.py` | Client-side API (`emit_event`, `daemon_available`, `get_status`) |
| `plugins/onex/hooks/scripts/session-start.sh` | Starts daemon if not running |
| `src/omniclaude/hooks/topics.py` | Kafka topic name definitions (`TopicBase` enum) |
| `src/omniclaude/hooks/schemas.py` | Pydantic event payload models |
