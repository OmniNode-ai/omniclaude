# Implementation Plan: OMN-1403 Context Injection for Session Enrichment

## Overview

Implement hook-based context injection to provide learned patterns and session insights to Claude Code sessions via the existing `hookSpecificOutput.additionalContext` mechanism.

## Architecture

```
SessionStart
    │
    └── (Future: Query historical context, cache for UserPromptSubmit)

UserPromptSubmit
    │
    ├── Agent Detection (existing)
    ├── Agent YAML Loading (existing)
    ├── Learned Pattern Injection (NEW) ─────► learned_pattern_injector.py
    │         │
    │         ├── Read pattern persistence file
    │         ├── Query session aggregator (if available)
    │         ├── Filter by domain/confidence
    │         └── Format markdown context
    │
    └── Context Assembly
            │
            ▼
        hookSpecificOutput.additionalContext

SessionEnd
    │
    └── (Future OMN-1402: Update pattern persistence file)
```

## Deliverables

### 1. Kafka Topic Definitions

**File**: `src/omniclaude/hooks/topics.py`

Add new topics to `TopicBase` enum (after line 40):

```python
# Context injection events (OMN-1403)
CONTEXT_RETRIEVAL_REQUESTED = "omniclaude.context.retrieval.requested.v1"
CONTEXT_RETRIEVAL_COMPLETED = "omniclaude.context.retrieval.completed.v1"
CONTEXT_INJECTED = "omniclaude.context.injected.v1"
```

**Rationale**: These topics enable observability of context injection and future integration with learning compute nodes (OMN-1402).

---

### 2. Event Schema Models

**File**: `src/omniclaude/hooks/schemas.py`

#### 2.1 Add HookEventType

```python
class HookEventType(StrEnum):
    # ... existing types ...
    CONTEXT_INJECTED = "hook.context.injected"
```

#### 2.2 New Payload Model

```python
class ModelHookContextInjectedPayload(BaseModel):
    """Event payload for context injection into Claude Code session."""

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    # ONEX Envelope Fields (all required)
    entity_id: UUID = Field(
        ...,
        description="Session identifier as UUID (partition key for ordering)",
    )
    session_id: str = Field(
        ...,
        min_length=1,
        description="Session identifier string",
    )
    correlation_id: UUID = Field(
        ...,
        description="Correlation ID for distributed tracing",
    )
    causation_id: UUID = Field(
        ...,
        description="ID of the event that triggered context retrieval",
    )
    emitted_at: TimezoneAwareDatetime = Field(
        ...,
        description="Timestamp when the hook emitted this event (UTC)",
    )

    # Context injection specific fields
    context_source: ContextSource = Field(
        ...,
        description="Where the injected context came from",
    )
    pattern_count: int = Field(
        ...,
        ge=0,
        le=100,
        description="Number of patterns injected",
    )
    context_size_bytes: int = Field(
        ...,
        ge=0,
        le=50000,  # Max 50KB context
        description="Size of injected context in bytes",
    )
    agent_domain: str | None = Field(
        default=None,
        description="Agent domain used for pattern filtering",
    )
    min_confidence_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum confidence threshold for included patterns",
    )
    retrieval_duration_ms: int = Field(
        ...,
        ge=0,
        le=10000,  # Max 10s retrieval time
        description="Time spent retrieving context in milliseconds",
    )
```

#### 2.3 New Enum

```python
class ContextSource(StrEnum):
    """Sources for injected context."""
    PERSISTENCE_FILE = "persistence_file"
    SESSION_AGGREGATOR = "session_aggregator"
    RAG_QUERY = "rag_query"
    FALLBACK_STATIC = "fallback_static"
    NONE = "none"
```

#### 2.4 Update Envelope Union

Add `ModelHookContextInjectedPayload` to the payload union type in `ModelHookEventEnvelope`.

---

### 3. Learned Pattern Injector Module

**File**: `plugins/onex/hooks/lib/learned_pattern_injector.py`

#### Interface

**Input** (JSON via stdin):
```json
{
  "agent_name": "code-reviewer",
  "domain": "code_review",
  "session_id": "abc-123",
  "project": "omniclaude",
  "correlation_id": "uuid-here",
  "max_patterns": 5,
  "min_confidence": 0.7
}
```

**Output** (JSON to stdout):
```json
{
  "success": true,
  "patterns_context": "## Learned Patterns\n\n### Pattern: ...",
  "pattern_count": 3,
  "source": "persistence_file",
  "retrieval_ms": 45
}
```

#### Implementation Structure

```python
#!/usr/bin/env python3
"""Learned pattern injector for Claude Code context enrichment.

Reads patterns from persistence file and formats for hook injection.
Always exits 0 - graceful degradation is mandatory for hook compatibility.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

# Default patterns file locations
DEFAULT_PATTERNS_FILE = Path.home() / ".claude" / "learned_patterns.json"
PROJECT_PATTERNS_FILE = ".claude/learned_patterns.json"

@dataclass
class PatternRecord:
    """A learned pattern with metadata."""
    pattern_id: str
    domain: str
    title: str
    description: str
    confidence: float
    usage_count: int
    success_rate: float
    example_reference: str | None = None

class InjectorInput(TypedDict):
    agent_name: str
    domain: str
    session_id: str
    project: str
    correlation_id: str
    max_patterns: int
    min_confidence: float

class InjectorOutput(TypedDict):
    success: bool
    patterns_context: str
    pattern_count: int
    source: str
    retrieval_ms: int

def load_patterns(project_root: Path | None, domain: str, min_confidence: float) -> list[PatternRecord]:
    """Load patterns from persistence files, filtered by domain and confidence."""
    # Implementation: Read JSON, filter, sort by confidence desc
    ...

def format_patterns_markdown(patterns: list[PatternRecord], max_patterns: int) -> str:
    """Format patterns as markdown for context injection."""
    if not patterns:
        return ""

    output = ["## Learned Patterns (Auto-Injected)", ""]
    for pattern in patterns[:max_patterns]:
        output.append(f"### {pattern.title}")
        output.append(f"- **Domain**: {pattern.domain}")
        output.append(f"- **Confidence**: {pattern.confidence:.0%}")
        output.append(f"- **Success Rate**: {pattern.success_rate:.0%}")
        output.append(f"- {pattern.description}")
        if pattern.example_reference:
            output.append(f"- **Reference**: {pattern.example_reference}")
        output.append("")

    return "\n".join(output)

def main() -> None:
    """Main entry point - reads JSON stdin, outputs JSON stdout."""
    start_time = time.monotonic()

    try:
        input_data: InjectorInput = json.load(sys.stdin)

        patterns = load_patterns(
            project_root=Path.cwd(),
            domain=input_data.get("domain", ""),
            min_confidence=input_data.get("min_confidence", 0.7),
        )

        context = format_patterns_markdown(
            patterns=patterns,
            max_patterns=input_data.get("max_patterns", 5),
        )

        output: InjectorOutput = {
            "success": True,
            "patterns_context": context,
            "pattern_count": min(len(patterns), input_data.get("max_patterns", 5)),
            "source": "persistence_file" if patterns else "none",
            "retrieval_ms": int((time.monotonic() - start_time) * 1000),
        }

    except Exception as e:
        output: InjectorOutput = {
            "success": False,
            "patterns_context": "",
            "pattern_count": 0,
            "source": "none",
            "retrieval_ms": int((time.monotonic() - start_time) * 1000),
        }

    json.dump(output, sys.stdout)
    sys.exit(0)  # Always exit 0 for hook compatibility

if __name__ == "__main__":
    main()
```

---

### 4. Hook Script Enhancement

**File**: `plugins/onex/hooks/scripts/user-prompt-submit.sh`

#### Insertion Point

After line 198 (after Agent YAML Loading, before "Handle no agent detected"):

```bash
# -----------------------------
# Learned Pattern Injection (OMN-1403)
# -----------------------------
LEARNED_PATTERNS=""
if [[ -n "$AGENT_NAME" ]] && [[ "$AGENT_NAME" != "NO_AGENT_DETECTED" ]]; then
    log "Loading learned patterns via learned_pattern_injector.py..."

    PATTERN_INPUT="$(jq -n \
        --arg agent "$AGENT_NAME" \
        --arg domain "${AGENT_DOMAIN:-}" \
        --arg session "$SESSION_ID" \
        --arg project "$PROJECT_NAME" \
        --arg correlation "$CORRELATION_ID" \
        '{
            agent_name: $agent,
            domain: $domain,
            session_id: $session,
            project: $project,
            correlation_id: $correlation,
            max_patterns: 5,
            min_confidence: 0.7
        }')"

    # 2s timeout - patterns should be fast (file-based)
    PATTERN_RESULT="$(echo "$PATTERN_INPUT" | run_with_timeout 2 $PYTHON_CMD "${HOOKS_LIB}/learned_pattern_injector.py" 2>>"$LOG_FILE" || echo '{}')"
    PATTERN_SUCCESS="$(echo "$PATTERN_RESULT" | jq -r '.success // false')"

    if [[ "$PATTERN_SUCCESS" == "true" ]]; then
        LEARNED_PATTERNS="$(echo "$PATTERN_RESULT" | jq -r '.patterns_context // ""')"
        PATTERN_COUNT="$(echo "$PATTERN_RESULT" | jq -r '.pattern_count // 0')"
        if [[ -n "$LEARNED_PATTERNS" ]] && [[ "$PATTERN_COUNT" != "0" ]]; then
            log "Learned patterns loaded: ${PATTERN_COUNT} patterns"
        fi
    else
        log "INFO: No learned patterns available"
    fi
fi
```

#### AGENT_CONTEXT Modification

Update the heredoc (lines 260-310) to include learned patterns:

```bash
AGENT_CONTEXT="$(cat <<EOF
${AGENT_YAML_INJECTION}

${LEARNED_PATTERNS}

========================================================================
MANDATORY AGENT DISPATCH DIRECTIVE
========================================================================
...
EOF
)"
```

---

### 5. Pattern Persistence File Format

**Location**: `{project}/.claude/learned_patterns.json` or `~/.claude/learned_patterns.json`

```json
{
  "version": "1.0.0",
  "last_updated": "2026-01-26T12:00:00Z",
  "patterns": [
    {
      "pattern_id": "onex-event-validation",
      "domain": "event_schemas",
      "title": "ONEX Event Schema Validation",
      "description": "Use pydantic.BaseModel with frozen=True for immutable events",
      "confidence": 0.92,
      "usage_count": 15,
      "success_rate": 0.87,
      "example_reference": "src/omniclaude/hooks/schemas.py:45"
    },
    {
      "pattern_id": "hook-graceful-exit",
      "domain": "hooks",
      "title": "Hook Graceful Exit Pattern",
      "description": "Always exit 0 from hook scripts, even on errors. Use JSON output with success flag.",
      "confidence": 0.95,
      "usage_count": 23,
      "success_rate": 1.0,
      "example_reference": "plugins/onex/hooks/lib/session_intelligence.py"
    }
  ]
}
```

---

### 6. Configuration Support

**File**: `src/omniclaude/hooks/context_config.py` (new)

```python
from pydantic import Field
from pydantic_settings import BaseSettings

class ContextInjectionConfig(BaseSettings):
    """Configuration for context injection."""

    model_config = {"env_prefix": "OMNICLAUDE_CONTEXT_"}

    enabled: bool = Field(default=True, description="Enable context injection")
    max_patterns: int = Field(default=5, ge=1, le=20)
    min_confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    timeout_ms: int = Field(default=2000, ge=500, le=10000)
    persistence_file: str = Field(default=".claude/learned_patterns.json")
```

**Environment Variables**:
- `OMNICLAUDE_CONTEXT_ENABLED=true|false`
- `OMNICLAUDE_CONTEXT_MAX_PATTERNS=5`
- `OMNICLAUDE_CONTEXT_MIN_CONFIDENCE=0.7`

---

## Test Plan

### Unit Tests

**File**: `tests/hooks/test_context_injection_schemas.py`

- Test `ModelHookContextInjectedPayload` creation (minimal, full)
- Test validation constraints (pattern_count bounds, context_size_bytes bounds)
- Test immutability (`frozen=True`)
- Test extra fields forbidden

**File**: `tests/hooks/test_learned_pattern_injector.py`

- Test pattern loading from file
- Test domain filtering
- Test confidence filtering
- Test markdown formatting
- Test graceful degradation on missing file
- Test JSON input/output contract

### Integration Tests

**File**: `tests/integration/test_context_injection_hook.py`

- Test hook script modification produces valid JSON output
- Test context is appended to `hookSpecificOutput.additionalContext`
- Test timeout handling (2s limit)

---

## Implementation Order

### Phase 1: Schema Foundation (Can start immediately)
1. Add topics to `TopicBase` enum
2. Add `ContextSource` enum to schemas
3. Add `ModelHookContextInjectedPayload` model
4. Update `ModelHookEventEnvelope` union
5. Add `HookEventType.CONTEXT_INJECTED`
6. Write unit tests for new schemas

### Phase 2: Injector Module
1. Create `learned_pattern_injector.py` with JSON stdin/stdout interface
2. Implement pattern loading from persistence file
3. Implement markdown formatting
4. Implement graceful degradation
5. Write unit tests

### Phase 3: Hook Integration
1. Modify `user-prompt-submit.sh` to call injector
2. Update `AGENT_CONTEXT` heredoc
3. Test end-to-end in Claude Code session

### Phase 4: Configuration
1. Add `ContextInjectionConfig` settings class
2. Wire configuration to injector module
3. Document environment variables

---

## Acceptance Criteria

- [ ] New sessions receive relevant context via hooks when patterns exist
- [ ] Context injection completes in <500ms (target <200ms for file-based)
- [ ] Can disable via `OMNICLAUDE_CONTEXT_ENABLED=false`
- [ ] Graceful degradation: missing patterns file = empty context, not error
- [ ] Patterns filtered by domain and confidence threshold
- [ ] All new code has unit tests with >90% coverage

---

## Out of Scope (Tracked Separately)

- **MCP tool integration**: OMN-1559
- **Pattern learning/writing**: OMN-1402 (Learning compute node)
- **RAG-based pattern retrieval**: Future enhancement
- **SessionStart preloading**: Future optimization

---

## Files to Create/Modify

| File | Action | Lines Changed |
|------|--------|---------------|
| `src/omniclaude/hooks/topics.py` | Modify | +3 lines |
| `src/omniclaude/hooks/schemas.py` | Modify | +50 lines |
| `src/omniclaude/hooks/context_config.py` | Create | ~30 lines |
| `plugins/onex/hooks/lib/learned_pattern_injector.py` | Create | ~150 lines |
| `plugins/onex/hooks/scripts/user-prompt-submit.sh` | Modify | +25 lines |
| `tests/hooks/test_context_injection_schemas.py` | Create | ~100 lines |
| `tests/hooks/test_learned_pattern_injector.py` | Create | ~150 lines |

**Total Estimated**: ~510 lines of new/modified code
