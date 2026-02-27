# _lib/agent-inbox/helpers.md

**Shared inter-agent messaging helpers for epic coordination.**

Used by `/epic-team`, `/ticket-pipeline`, and other skills that need
inter-agent communication via the inbox pattern.

## Import

```
@_lib/agent-inbox/helpers.md
```

---

## Constants

```python
import os
from pathlib import Path

# Inbox root directory (STANDALONE tier)
INBOX_ROOT = Path(os.path.expanduser("~/.claude/agent-inboxes"))

# Broadcast subdirectory
BROADCAST_DIR = "_broadcast"

# Topic templates (EVENT_BUS+ tier)
TOPIC_DIRECTED = "onex.evt.omniclaude.agent-inbox.{agent_id}.v1"
TOPIC_BROADCAST = "onex.evt.omniclaude.epic.{epic_id}.status.v1"

# Message types
MSG_TASK_COMPLETED = "agent.task.completed"
MSG_UNBLOCK = "agent.unblock"

# Default GC settings
DEFAULT_GC_TTL_HOURS = 24
DEFAULT_MAX_INBOX_SIZE_MB = 10
```

---

## make_message_envelope(type, source_agent_id, target_agent_id, target_epic_id, payload, correlation_id, run_id)

Create a versioned message envelope for inter-agent communication.

```python
import json
import uuid
from datetime import datetime, timezone


def make_message_envelope(
    type: str,
    source_agent_id: str,
    payload: dict,
    correlation_id: str | None = None,
    run_id: str | None = None,
    target_agent_id: str | None = None,
    target_epic_id: str | None = None,
) -> dict:
    """Create a versioned message envelope.

    Exactly one of target_agent_id or target_epic_id must be provided.

    Args:
        type: Message type (e.g., "agent.task.completed", "agent.unblock").
        source_agent_id: ID of the sending agent.
        payload: Type-specific payload data.
        correlation_id: Workflow correlation ID (auto-generated if None).
        run_id: Pipeline or epic run ID.
        target_agent_id: Directed delivery target (for agent-to-agent).
        target_epic_id: Broadcast delivery target (for epic-wide).

    Returns:
        Dictionary conforming to the inbox message envelope schema.

    Raises:
        ValueError: If neither or both targets are provided.

    Examples:
        >>> # Directed message (task completion)
        >>> env = make_message_envelope(
        ...     type="agent.task.completed",
        ...     source_agent_id="worker-omnibase-core",
        ...     target_agent_id="worker-omniclaude",
        ...     payload={"pr_url": "https://github.com/org/repo/pull/1"},
        ...     correlation_id="abc-123",
        ...     run_id="run-001",
        ... )

        >>> # Broadcast message (epic status)
        >>> env = make_message_envelope(
        ...     type="agent.task.completed",
        ...     source_agent_id="worker-omniclaude",
        ...     target_epic_id="OMN-2821",
        ...     payload={"ticket_id": "OMN-2827", "status": "completed"},
        ...     run_id="run-001",
        ... )
    """
    if target_agent_id is None and target_epic_id is None:
        raise ValueError("Exactly one of target_agent_id or target_epic_id must be set")
    if target_agent_id is not None and target_epic_id is not None:
        raise ValueError("Cannot set both target_agent_id and target_epic_id")

    return {
        "schema_version": "1",
        "message_id": str(uuid.uuid4()),
        "emitted_at": datetime.now(timezone.utc).isoformat(),
        "trace": {
            "correlation_id": correlation_id or str(uuid.uuid4()),
            "run_id": run_id or "unknown",
        },
        "type": type,
        "source_agent_id": source_agent_id,
        "target_agent_id": target_agent_id,
        "target_epic_id": target_epic_id,
        "payload": payload,
    }
```

---

## send_to_inbox(agent_id, message_envelope)

Write a message to an agent's file-based inbox using atomic writes.

```python
import tempfile


def send_to_inbox(agent_id: str, message_envelope: dict) -> str:
    """Write a message to an agent's file-based inbox atomically.

    Uses write-to-temp + os.replace() to prevent partial reads.

    Args:
        agent_id: Target agent identifier.
        message_envelope: The message envelope dictionary.

    Returns:
        Absolute path to the written file.

    Examples:
        >>> env = make_message_envelope(
        ...     type="agent.unblock",
        ...     source_agent_id="worker-omnibase-core",
        ...     target_agent_id="worker-omniclaude",
        ...     payload={"merged_pr": 42},
        ... )
        >>> path = send_to_inbox("worker-omniclaude", env)
        >>> print(f"Message written to {path}")
    """
    inbox_dir = INBOX_ROOT / agent_id
    inbox_dir.mkdir(parents=True, exist_ok=True)

    emitted_at = message_envelope.get("emitted_at", "")
    message_id = message_envelope.get("message_id", str(uuid.uuid4()))
    # Use a filename-safe timestamp
    ts_safe = emitted_at.replace(":", "").replace("-", "").replace("+", "p")[:20]
    filename = f"{ts_safe}_{message_id}.json"
    final_path = inbox_dir / filename

    # Atomic write
    fd, tmp_path = tempfile.mkstemp(suffix=".tmp", dir=str(inbox_dir))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(message_envelope, f, indent=2, default=str)
        os.replace(tmp_path, str(final_path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return str(final_path)
```

---

## broadcast_to_epic(epic_id, message_envelope)

Write a broadcast message to the epic status inbox.

```python
def broadcast_to_epic(epic_id: str, message_envelope: dict) -> str:
    """Write a broadcast message to the epic-wide status inbox.

    Args:
        epic_id: Epic identifier (e.g., "OMN-2821").
        message_envelope: The message envelope dictionary.

    Returns:
        Absolute path to the written file.

    Examples:
        >>> env = make_message_envelope(
        ...     type="agent.task.completed",
        ...     source_agent_id="worker-omniclaude",
        ...     target_epic_id="OMN-2821",
        ...     payload={"ticket_id": "OMN-2827"},
        ... )
        >>> path = broadcast_to_epic("OMN-2821", env)
    """
    broadcast_dir = INBOX_ROOT / BROADCAST_DIR / epic_id
    broadcast_dir.mkdir(parents=True, exist_ok=True)

    emitted_at = message_envelope.get("emitted_at", "")
    message_id = message_envelope.get("message_id", str(uuid.uuid4()))
    ts_safe = emitted_at.replace(":", "").replace("-", "").replace("+", "p")[:20]
    filename = f"{ts_safe}_{message_id}.json"
    final_path = broadcast_dir / filename

    # Atomic write
    fd, tmp_path = tempfile.mkstemp(suffix=".tmp", dir=str(broadcast_dir))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(message_envelope, f, indent=2, default=str)
        os.replace(tmp_path, str(final_path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return str(final_path)
```

---

## read_inbox(agent_id, since)

Read pending messages from an agent's inbox.

```python
def read_inbox(
    agent_id: str,
    since: str | None = None,
) -> list[dict]:
    """Read pending messages from an agent's file-based inbox.

    Returns messages in timestamp order (oldest first).

    Args:
        agent_id: The agent whose inbox to read.
        since: ISO 8601 timestamp; only return messages after this time.

    Returns:
        List of message envelope dictionaries in timestamp order.

    Examples:
        >>> messages = read_inbox("worker-omniclaude")
        >>> for msg in messages:
        ...     print(f"{msg['type']}: {msg['payload']}")
    """
    inbox_dir = INBOX_ROOT / agent_id
    if not inbox_dir.is_dir():
        return []

    messages = []
    since_dt = datetime.fromisoformat(since) if since else None

    for json_file in sorted(inbox_dir.glob("*.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            if since_dt:
                msg_time = datetime.fromisoformat(data.get("emitted_at", ""))
                if msg_time <= since_dt:
                    continue
            messages.append(data)
        except (json.JSONDecodeError, ValueError, OSError):
            continue

    return messages
```

---

## read_epic_broadcast(epic_id, since)

Read broadcast messages for an epic.

```python
def read_epic_broadcast(
    epic_id: str,
    since: str | None = None,
) -> list[dict]:
    """Read broadcast messages for an epic.

    Args:
        epic_id: Epic identifier (e.g., "OMN-2821").
        since: ISO 8601 timestamp; only return messages after this time.

    Returns:
        List of broadcast message envelopes in timestamp order.
    """
    broadcast_dir = INBOX_ROOT / BROADCAST_DIR / epic_id
    if not broadcast_dir.is_dir():
        return []

    messages = []
    since_dt = datetime.fromisoformat(since) if since else None

    for json_file in sorted(broadcast_dir.glob("*.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            if since_dt:
                msg_time = datetime.fromisoformat(data.get("emitted_at", ""))
                if msg_time <= since_dt:
                    continue
            messages.append(data)
        except (json.JSONDecodeError, ValueError, OSError):
            continue

    return messages
```

---

## gc_inboxes(ttl_hours)

Garbage collect expired messages from all agent inboxes.

```python
import time


def gc_inboxes(ttl_hours: int = DEFAULT_GC_TTL_HOURS) -> int:
    """Remove expired messages from all agent inboxes.

    Walks ~/.claude/agent-inboxes/ and removes .json files older
    than ttl_hours.

    Args:
        ttl_hours: Messages older than this many hours are removed.

    Returns:
        Number of files removed.

    Examples:
        >>> removed = gc_inboxes(ttl_hours=24)
        >>> print(f"Removed {removed} expired inbox messages")
    """
    if not INBOX_ROOT.is_dir():
        return 0

    cutoff = time.time() - (ttl_hours * 3600)
    removed = 0

    for entry in INBOX_ROOT.iterdir():
        if not entry.is_dir():
            continue

        # Handle both agent directories and broadcast subdirectories
        dirs_to_scan = [entry]
        if entry.name == BROADCAST_DIR:
            dirs_to_scan = [d for d in entry.iterdir() if d.is_dir()]

        for scan_dir in dirs_to_scan:
            for json_file in scan_dir.glob("*.json"):
                try:
                    if json_file.stat().st_mtime < cutoff:
                        json_file.unlink()
                        removed += 1
                except OSError:
                    continue

    return removed
```

---

## wait_for_message(agent_id, message_type, timeout_seconds, poll_interval_seconds)

Block-wait for a specific message type in an agent's inbox.

```python
def wait_for_message(
    agent_id: str,
    message_type: str,
    timeout_seconds: int = 300,
    poll_interval_seconds: int = 5,
    since: str | None = None,
) -> dict | None:
    """Wait for a specific message type to appear in an agent's inbox.

    Polls the file-based inbox at regular intervals until a matching
    message is found or the timeout expires.

    Args:
        agent_id: The agent whose inbox to monitor.
        message_type: The message type to wait for (e.g., "agent.unblock").
        timeout_seconds: Maximum seconds to wait.
        poll_interval_seconds: Seconds between polls.
        since: ISO 8601 timestamp; only consider messages after this time.

    Returns:
        The matching message envelope, or None if timeout expired.

    Examples:
        >>> # Wait for an unblock signal from another agent
        >>> msg = wait_for_message(
        ...     agent_id="worker-omniclaude",
        ...     message_type="agent.unblock",
        ...     timeout_seconds=600,
        ... )
        >>> if msg:
        ...     print(f"Unblocked by {msg['source_agent_id']}")
        ... else:
        ...     print("Timeout waiting for unblock signal")
    """
    deadline = time.time() + timeout_seconds

    while time.time() < deadline:
        messages = read_inbox(agent_id, since=since)
        for msg in messages:
            if msg.get("type") == message_type:
                return msg

        time.sleep(poll_interval_seconds)

    return None
```

---

## notify_task_completed(source_agent_id, target_agent_id, epic_id, payload, correlation_id, run_id)

Convenience wrapper: send task-completed to a specific agent AND broadcast to epic.

```python
def notify_task_completed(
    source_agent_id: str,
    payload: dict,
    correlation_id: str | None = None,
    run_id: str | None = None,
    target_agent_id: str | None = None,
    epic_id: str | None = None,
) -> list[str]:
    """Send task-completed notification via directed and/or broadcast delivery.

    Convenience wrapper that creates the envelope and delivers it.
    If both target_agent_id and epic_id are provided, sends both a
    directed message and a broadcast message (two separate envelopes).

    Args:
        source_agent_id: The completing agent.
        payload: Task completion data (pr_url, commit_sha, branch, etc.).
        correlation_id: Workflow correlation ID.
        run_id: Pipeline or epic run ID.
        target_agent_id: Specific agent to notify (directed).
        epic_id: Epic to broadcast to (broadcast).

    Returns:
        List of file paths written.

    Examples:
        >>> paths = notify_task_completed(
        ...     source_agent_id="worker-omnibase-core",
        ...     target_agent_id="worker-omniclaude",
        ...     epic_id="OMN-2821",
        ...     payload={"pr_url": "https://github.com/org/repo/pull/42"},
        ...     run_id="run-001",
        ... )
    """
    paths = []

    if target_agent_id:
        env = make_message_envelope(
            type=MSG_TASK_COMPLETED,
            source_agent_id=source_agent_id,
            target_agent_id=target_agent_id,
            payload=payload,
            correlation_id=correlation_id,
            run_id=run_id,
        )
        paths.append(send_to_inbox(target_agent_id, env))

    if epic_id:
        env = make_message_envelope(
            type=MSG_TASK_COMPLETED,
            source_agent_id=source_agent_id,
            target_epic_id=epic_id,
            payload=payload,
            correlation_id=correlation_id,
            run_id=run_id,
        )
        paths.append(broadcast_to_epic(epic_id, env))

    return paths
```

---

## send_unblock(source_agent_id, target_agent_id, payload, correlation_id, run_id)

Send an unblock signal to a specific agent.

```python
def send_unblock(
    source_agent_id: str,
    target_agent_id: str,
    payload: dict,
    correlation_id: str | None = None,
    run_id: str | None = None,
) -> str:
    """Send an unblock signal to a specific agent.

    Used when a dependency is resolved (e.g., PR merged in another repo)
    and a blocked agent can proceed.

    Args:
        source_agent_id: The agent sending the unblock.
        target_agent_id: The agent to unblock.
        payload: Unblock context (merged_pr, merged_repo, etc.).
        correlation_id: Workflow correlation ID.
        run_id: Pipeline or epic run ID.

    Returns:
        File path of the written message.

    Examples:
        >>> path = send_unblock(
        ...     source_agent_id="worker-omnibase-core",
        ...     target_agent_id="worker-omniclaude",
        ...     payload={"merged_pr": 42, "merged_repo": "omnibase_core"},
        ...     run_id="run-001",
        ... )
    """
    env = make_message_envelope(
        type=MSG_UNBLOCK,
        source_agent_id=source_agent_id,
        target_agent_id=target_agent_id,
        payload=payload,
        correlation_id=correlation_id,
        run_id=run_id,
    )
    return send_to_inbox(target_agent_id, env)
```

---

## Usage Pattern

```python
# In epic-team worker prompt:

# 1. After completing a task, notify the team and broadcast to epic
notify_task_completed(
    source_agent_id=f"worker-{repo}",
    target_agent_id="team-lead",
    epic_id=epic_id,
    payload={
        "ticket_id": ticket_id,
        "pr_url": pr_url,
        "commit_sha": commit_sha,
        "branch": branch,
    },
    correlation_id=correlation_id,
    run_id=run_id,
)

# 2. When a dependency is resolved, unblock the waiting agent
send_unblock(
    source_agent_id=f"worker-{repo}",
    target_agent_id=f"worker-{dependent_repo}",
    payload={
        "merged_pr": pr_number,
        "merged_repo": repo,
    },
    run_id=run_id,
)

# 3. In a blocked worker, wait for unblock signal
msg = wait_for_message(
    agent_id=f"worker-{repo}",
    message_type="agent.unblock",
    timeout_seconds=600,
)
if msg:
    merged_pr = msg["payload"]["merged_pr"]
    print(f"Dependency resolved: PR #{merged_pr} merged")
else:
    print("Timeout waiting for dependency. Proceeding with best-effort.")

# 4. Team lead reads all epic broadcasts to track progress
broadcasts = read_epic_broadcast(epic_id)
for b in broadcasts:
    print(f"[{b['source_agent_id']}] {b['type']}: {b['payload']}")

# 5. Periodic GC (run from orchestrator)
removed = gc_inboxes(ttl_hours=24)
print(f"GC: removed {removed} expired inbox messages")
```
