---
description: Delegate tasks to the ONEX node-based delegation pipeline via Kafka command event. Classifies prompt, wraps in envelope, publishes to delegation-request topic.
mode: full
level: advanced
debug: true
index: true
args:
  - name: prompt
    description: "The task to delegate (e.g., 'write unit tests for verify_registration.py')"
    required: true
  - name: --source-file
    description: "Source file path for context (optional)"
    required: false
  - name: --max-tokens
    description: "Maximum tokens for the LLM response (default: 2048)"
    required: false
---

# Delegate

Thin skill that classifies a user prompt and publishes a delegation request to the ONEX runtime
event bus. The runtime pipeline handles routing, LLM inference, quality gating, and baseline
comparison — this skill only classifies and publishes.

## How It Works

1. Parse the user's prompt
2. Classify the task type using the existing `TaskClassifier` (heuristic keyword matching)
3. Construct a delegation request envelope (plain dict, no infrastructure model imports)
4. Publish to `onex.cmd.omniclaude.delegation-request.v1` via the emit daemon
5. Return immediately with the correlation ID

## Task Types

Classification maps to three delegatable intents from `TaskClassifier`:

| Task Type | Trigger Keywords | Example |
|-----------|-----------------|---------|
| `test` | test, testing, unit test, pytest, assert | "write unit tests for verify_registration.py" |
| `document` | document, docstring, README, explain | "add docstrings to the handler module" |
| `research` | what, how, explain, investigate, analyze | "what does the routing reducer do?" |

Non-delegatable intents (debug, refactor, database, unknown) are rejected with a message
explaining that only test/document/research tasks can be delegated.

## Wire Schema

The published payload is a plain dict (no Pydantic model import from omnibase_infra).
Runtime-side validation occurs on the consuming `node_delegation_orchestrator`.

```json
{
  "prompt": "write unit tests for verify_registration.py",
  "task_type": "test",
  "source_session_id": "session-abc123",
  "source_file_path": "/path/to/verify_registration.py",
  "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
  "max_tokens": 2048,
  "emitted_at": "2026-03-30T14:30:00Z"
}
```

## Kafka Topic

- **Command topic**: `onex.cmd.omniclaude.delegation-request.v1`
- **Producer**: this skill (via omniclaude emit daemon)
- **Consumer**: `node_delegation_orchestrator` (omnibase_infra runtime)

## Usage

```
/delegate write unit tests for verify_registration.py
/delegate --source-file src/omniclaude/hooks/handler_event_emitter.py add docstrings
/delegate --max-tokens 4096 analyze the routing architecture
```

## What This Skill Does NOT Do

- Wait for the delegation result (fire-and-forget)
- Call any LLM directly
- Run quality gates
- Import omnibase_infra models (wire schema is a plain dict)
- Contain business logic beyond classification + publish

## Emit Mechanism

The skill publishes via the omniclaude emit daemon (`EmitClient`), the same mechanism
used by all hook event emitters. The emit daemon handles Kafka producer lifecycle,
serialization, and circuit breaking.

To publish from a skill script:

```python
#!/usr/bin/env python3
import json
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

# Add src/ to path for omniclaude imports
_SRC_PATH = Path(__file__).parent.parent.parent.parent.parent / "src"
if _SRC_PATH.exists() and str(_SRC_PATH) not in sys.path:
    sys.path.insert(0, str(_SRC_PATH))

from omniclaude.hooks.topics import TopicBase, build_topic
from omniclaude.lib.task_classifier import TaskClassifier, TaskIntent

TOPIC = build_topic(TopicBase.DELEGATION_REQUEST)
DELEGATABLE = frozenset({TaskIntent.TEST, TaskIntent.DOCUMENT, TaskIntent.RESEARCH})


def classify_and_publish(prompt: str, source_file: str | None = None, max_tokens: int = 2048) -> dict:
    """Classify prompt and return the delegation request envelope."""
    classifier = TaskClassifier()
    result = classifier.classify(prompt)

    if result.intent not in DELEGATABLE:
        return {
            "success": False,
            "error": f"Task type '{result.intent.value}' is not delegatable. Only test/document/research tasks can be delegated.",
        }

    correlation_id = str(uuid.uuid4())
    envelope = {
        "prompt": prompt,
        "task_type": result.intent.value,
        "source_session_id": os.environ.get("CLAUDE_SESSION_ID"),
        "source_file_path": source_file,
        "correlation_id": correlation_id,
        "max_tokens": max_tokens,
        "emitted_at": datetime.now(UTC).isoformat(),
    }

    # Publish via emit daemon (fire-and-forget)
    # The emit daemon is started by the hook system; if unavailable,
    # the skill reports the envelope for manual submission.
    try:
        from omniclaude.hooks._helpers import get_emit_client
        client = get_emit_client()
        if client is not None:
            client.emit(TOPIC, envelope)
    except ImportError:
        pass  # Emit client unavailable — envelope returned for manual submission

    return {
        "success": True,
        "correlation_id": correlation_id,
        "task_type": result.intent.value,
        "topic": TOPIC,
        "envelope": envelope,
    }
```

## Pipeline Architecture

```
/delegate "write tests for X"
  |
  v
TaskClassifier.classify() --> task_type = "test"
  |
  v
Construct plain dict envelope
  |
  v
Publish to onex.cmd.omniclaude.delegation-request.v1
  |
  v
[RUNTIME SIDE - not in this skill]
node_delegation_orchestrator --> node_delegation_routing_reducer
  --> node_llm_inference_effect --> node_delegation_quality_gate_reducer
  --> node_baseline_comparison_compute
  |
  v
onex.evt.omnibase-infra.delegation-completed.v1 --> omnidash
```

## Related

- **Existing delegation hook**: `plugins/onex/hooks/lib/delegation_orchestrator.py` (being replaced by this pipeline)
- **TaskClassifier**: `src/omniclaude/lib/task_classifier.py`
- **Topics**: `src/omniclaude/hooks/topics.py` (`TopicBase.DELEGATION_REQUEST`)
- **Plan**: `docs/plans/2026-03-30-delegation-pipeline.md`
