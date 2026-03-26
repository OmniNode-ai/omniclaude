# Agent Chat — Broadcast and Read

You are executing the `/chat` skill. This skill sends or reads broadcast messages
visible to all Claude Code sessions sharing the same `$ONEX_STATE_DIR`.

## Argument Parsing

```
/chat [message] [--channel CHANNEL] [--epic EPIC_ID] [--severity SEVERITY] [--n COUNT] [--type TYPE]
```

Parse the arguments:

```python
import shlex
raw_args = "$ARGUMENTS"

# Parse arguments
args = shlex.split(raw_args) if raw_args.strip() else []

channel = "BROADCAST"
epic_id = None
severity = "INFO"
n = 20
msg_type = None
message_parts = []

i = 0
while i < len(args):
    if args[i] == "--channel" and i + 1 < len(args):
        channel = args[i + 1].upper()
        i += 2
    elif args[i] == "--epic" and i + 1 < len(args):
        epic_id = args[i + 1]
        i += 2
    elif args[i] == "--severity" and i + 1 < len(args):
        severity = args[i + 1].upper()
        i += 2
    elif args[i] == "--n" and i + 1 < len(args):
        n = int(args[i + 1])
        i += 2
    elif args[i] == "--type" and i + 1 < len(args):
        msg_type = args[i + 1].upper()
        i += 2
    else:
        message_parts.append(args[i])
        i += 1

message_body = " ".join(message_parts).strip()
```

## Mode Detection

If `message_body` is non-empty, this is **send mode**. Otherwise, **read mode**.

## Send Mode

Publish a chat message using the dual-write publisher:

```python
from datetime import UTC, datetime
import os

from omniclaude.nodes.node_agent_chat import (
    EnumChatChannel,
    EnumChatMessageType,
    EnumChatSeverity,
    HandlerChatPublisher,
    ModelAgentChatMessage,
)

# Resolve identifiers
session_id = os.environ.get("CLAUDE_SESSION_ID", os.environ.get("SESSION_ID", "unknown"))
agent_id = os.environ.get("OMNICLAUDE_AGENT_ID", f"human-{session_id[:8]}")

# Default message type for human-sent messages
if msg_type is None:
    msg_type = "HUMAN"

msg = ModelAgentChatMessage(
    emitted_at=datetime.now(UTC),
    session_id=session_id,
    agent_id=agent_id,
    channel=EnumChatChannel(channel),
    message_type=EnumChatMessageType(msg_type),
    severity=EnumChatSeverity(severity),
    body=message_body,
    epic_id=epic_id,
)

publisher = HandlerChatPublisher()
publisher.publish(msg)
print(f"Sent: [{msg.severity.value}] {msg.body}")
```

## Read Mode

Display recent chat messages:

```python
from omniclaude.nodes.node_agent_chat import HandlerChatReader

reader = HandlerChatReader()
output = reader.read_formatted(n=n, channel=channel if channel != "BROADCAST" else None, epic_id=epic_id)

if output:
    print(output)
else:
    print("No chat messages found.")
```

## Examples

```bash
# Send a broadcast message
/chat "Starting work on OMN-6512"

# Send a CI alert
/chat "Build failed on omniclaude#887" --channel CI --severity ERROR --type CI_ALERT

# Send an epic-scoped message
/chat "Wave 2 complete" --channel EPIC --epic OMN-3972

# Read recent messages (default 20)
/chat

# Read CI channel only
/chat --channel CI

# Read last 5 messages for an epic
/chat --channel EPIC --epic OMN-3972 --n 5
```
