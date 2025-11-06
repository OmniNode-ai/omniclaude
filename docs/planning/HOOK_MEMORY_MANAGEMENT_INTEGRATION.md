# Hook-Based Memory Management with Anthropic's Context API

**Status**: Proposal - Phase 0 (Architecture Design)
**Created**: 2025-11-06
**Last Updated**: 2025-11-06
**Priority**: Critical - High ROI Feature
**Correlation ID**: TBD

---

## Executive Summary

This document proposes integrating **Anthropic's Context Management API Beta** (released Sept 29, 2025) with OmniClaude's existing hook system to create a **real-time memory management architecture**.

Instead of hooks only validating/routing, **every hook becomes a memory update point**, giving Claude:
- ✅ **Real-time workspace awareness** (file changes, project state)
- ✅ **Persistent memory across sessions** (no 1-hour TTL limits)
- ✅ **Dynamic context updates** (manifest injections, routing history, patterns)
- ✅ **39% performance improvement** (from Anthropic's benchmarks)
- ✅ **Reduced token budget pressure** (context editing auto-cleans stale data)

**Key Innovation**: Transform hooks from passive validators → **active memory managers**

---

## Table of Contents

1. [Background: Anthropic's Context Management API](#background)
2. [Current OmniClaude Context Architecture](#current-architecture)
3. [Proposed Hook-Memory Integration](#proposed-integration)
4. [Intent-Driven Memory Retrieval](#intent-driven-retrieval)
5. [Memory Schema Design](#memory-schema)
6. [Implementation Plan](#implementation-plan)
7. [API Integration Details](#api-integration)
8. [Performance Benefits](#performance-benefits)
9. [Migration Strategy](#migration-strategy)
10. [Risk Assessment](#risk-assessment)

---

## Background: Anthropic's Context Management API

### Release Details
- **Announced**: September 29, 2025 (with Claude Sonnet 4.5)
- **Status**: Beta (requires opt-in header)
- **Beta Header**: `anthropic-beta: context-management-2025-06-27`

### Two Key Features

#### 1. Context Editing (`clear_tool_uses_20250919`)
**Purpose**: Automatically removes stale tool calls/results when approaching token limits

**Benefits**:
- 29% performance improvement (standalone)
- Extends agent runtime without manual intervention
- Preserves conversation flow while clearing stale data

**How It Works**:
```json
{
  "context_management": {
    "edit_types": ["clear_tool_uses_20250919"]
  }
}
```

Claude automatically identifies and removes tool results that are no longer relevant, keeping context fresh.

#### 2. Memory Tool (`memory_20250818`)
**Purpose**: File-based storage system for persisting information **outside** the 200K context window

**Benefits**:
- Combined with context editing: **39% performance improvement**
- Cross-session persistence (no context loss on restart)
- Developer-managed storage backend (client-side tool calls)

**How It Works**:
```json
{
  "context_management": {
    "edit_types": ["clear_tool_uses_20250919", "memory_20250818"]
  }
}
```

Claude can make tool calls to:
- **Store memory**: `store_memory(key, value, category)`
- **Retrieve memory**: `get_memory(key, category)`
- **Update memory**: `update_memory(key, delta, category)`
- **Delete memory**: `delete_memory(key, category)`

**Storage Backend**: Developer implements storage (filesystem, database, S3, etc.)

---

## Current OmniClaude Context Architecture

### Existing Components

#### 1. Correlation Manager (`claude_hooks/lib/correlation_manager.py`)
- **Purpose**: Session state persistence
- **Storage**: JSON files in `~/.claude/hooks/.state/`
- **TTL**: 1 hour (auto-cleanup after inactivity)
- **Limitations**:
  - ❌ Lost on Claude Code restart
  - ❌ Manual TTL management
  - ❌ No native Claude integration

#### 2. Context Manager (`agents/parallel_execution/context_manager.py`)
- **Purpose**: Multi-agent context distribution
- **Features**:
  - Global context gathering (Phase 0)
  - Selective filtering (Phase 2)
  - Token budget management
- **Limitations**:
  - ❌ Regenerates context on every request
  - ❌ No persistent storage
  - ❌ High latency for large contexts

#### 3. Context Optimizer (`agents/lib/context_optimizer.py`)
- **Purpose**: ML-based context prediction
- **Features**:
  - Historical learning (PostgreSQL-backed)
  - Task-type optimization
  - Success rate tracking
- **Limitations**:
  - ❌ Doesn't persist optimized contexts
  - ❌ Recalculates every time

#### 4. Hook Intelligence (Phase 1 Complete)
- **Purpose**: RAG-based intelligence injection
- **Features**:
  - <500ms latency
  - In-memory caching (5-minute TTL)
  - Fallback rules
- **Limitations**:
  - ❌ Cache expires frequently
  - ❌ No cross-session persistence

### Current Hook System

**Existing Hooks**:
1. **pre-prompt-submit**: Manifest injection, quality enforcement
2. **pre-tool-use**: Tool validation, routing
3. **post-tool-use**: Metrics collection, pattern capture
4. **workspace-change** (planned): File change tracking

**Current Hook Behavior**: Mostly **read-only** (query intelligence, inject context, validate)

---

## Proposed Hook-Memory Integration

### Core Concept: Hooks as Memory Update Points

**Every hook execution becomes a memory write opportunity**:

```
┌─────────────────────────────────────────────────────────────┐
│                    CLAUDE CODE EXECUTION                     │
└─────────────────────────────────────────────────────────────┘
                            ↓
        ┌───────────────────────────────────────┐
        │  PRE-PROMPT-SUBMIT HOOK               │
        │  ✓ Read workspace state               │
        │  ✓ Read recent patterns               │
        │  → UPDATE MEMORY: workspace_state     │ ← NEW!
        │  → UPDATE MEMORY: available_patterns  │ ← NEW!
        │  → UPDATE MEMORY: routing_history     │ ← NEW!
        └───────────────────────────────────────┘
                            ↓
        ┌───────────────────────────────────────┐
        │  CLAUDE EXECUTION (with fresh memory) │
        │  Context includes:                    │
        │  • Current workspace state            │
        │  • Recent successful patterns         │
        │  • Agent routing decisions            │
        │  • File change history                │
        └───────────────────────────────────────┘
                            ↓
        ┌───────────────────────────────────────┐
        │  PRE-TOOL-USE HOOK                    │
        │  ✓ Validate tool usage                │
        │  → UPDATE MEMORY: tool_intent         │ ← NEW!
        │  → UPDATE MEMORY: validation_results  │ ← NEW!
        └───────────────────────────────────────┘
                            ↓
        ┌───────────────────────────────────────┐
        │  TOOL EXECUTION                       │
        └───────────────────────────────────────┘
                            ↓
        ┌───────────────────────────────────────┐
        │  POST-TOOL-USE HOOK                   │
        │  ✓ Collect metrics                    │
        │  ✓ Capture patterns                   │
        │  → UPDATE MEMORY: execution_results   │ ← NEW!
        │  → UPDATE MEMORY: success_patterns    │ ← NEW!
        │  → UPDATE MEMORY: failure_patterns    │ ← NEW!
        └───────────────────────────────────────┘
                            ↓
        ┌───────────────────────────────────────┐
        │  WORKSPACE-CHANGE HOOK (background)   │
        │  ✓ Detect file changes                │
        │  → UPDATE MEMORY: file_changes        │ ← NEW!
        │  → UPDATE MEMORY: project_context     │ ← NEW!
        └───────────────────────────────────────┘
```

### Memory Update Examples

#### Pre-Prompt-Submit Hook
```python
# Before: Just inject manifest
manifest = await get_manifest_from_intelligence()
inject_into_prompt(manifest)

# After: Update memory + inject manifest
manifest = await get_manifest_from_intelligence()

# Update Claude's memory with current workspace state
await memory_client.store_memory(
    key="workspace_state",
    value={
        "current_branch": git_branch,
        "modified_files": git_status(),
        "last_patterns_used": recent_patterns,
        "active_agents": active_agent_list
    },
    category="workspace"
)

# Update available patterns
await memory_client.store_memory(
    key="available_patterns",
    value=manifest["patterns"],
    category="intelligence"
)

# Claude now has fresh memory of workspace + patterns!
```

#### Post-Tool-Use Hook
```python
# Before: Just log metrics
log_metrics(tool_name, execution_time, success)

# After: Update memory with execution patterns
await memory_client.store_memory(
    key=f"tool_execution_{tool_name}_{timestamp}",
    value={
        "tool": tool_name,
        "success": success,
        "duration_ms": execution_time,
        "error_pattern": error if not success else None
    },
    category="execution_history"
)

# Update success/failure patterns
if success:
    await memory_client.update_memory(
        key="success_patterns",
        delta={"tool": tool_name, "context": current_context},
        category="patterns"
    )
else:
    await memory_client.update_memory(
        key="failure_patterns",
        delta={"tool": tool_name, "error": error},
        category="patterns"
    )

# Claude learns from every tool execution!
```

#### Workspace-Change Hook (Background)
```python
# New hook: Runs on file changes (non-blocking)
async def on_workspace_change(changed_files: List[str]):
    """Update memory when files change"""

    # Store file change event
    await memory_client.store_memory(
        key=f"file_change_{timestamp}",
        value={
            "files": changed_files,
            "timestamp": timestamp,
            "branch": git_branch
        },
        category="workspace_events"
    )

    # Update project context
    for file in changed_files:
        context = await analyze_file_context(file)
        await memory_client.update_memory(
            key="project_context",
            delta={file: context},
            category="workspace"
        )

    # Claude always has latest file context!
```

---

## Intent-Driven Memory Retrieval

### The Smart Memory Problem

With the Memory Tool, we can store unlimited context. But loading **all** memory into Claude's context every time would:
- ❌ Waste tokens (200K context limit)
- ❌ Slow down responses (processing overhead)
- ❌ Include irrelevant information (noise)

**Solution**: Use **intent extraction** to selectively retrieve only relevant memories.

### Architecture: Intent → Memory Query → Context

```
User Prompt
    ↓
┌────────────────────────────────────────┐
│ 1. EXTRACT INTENT (LangExtract/NLP)   │
│    - Task type: "authentication"      │
│    - Entities: "JWT", "security"      │
│    - Files: "auth.py", "config.py"    │
└────────────────────────────────────────┘
    ↓
┌────────────────────────────────────────┐
│ 2. QUERY MEMORY (Intent-Based)        │
│    → Get success_patterns.auth*       │
│    → Get workspace.files.auth.py      │
│    → Get execution_history.JWT*       │
│    → Get intelligence.security*       │
└────────────────────────────────────────┘
    ↓
┌────────────────────────────────────────┐
│ 3. RETRIEVE RELEVANT MEMORIES          │
│    Only 5-10 most relevant items       │
│    (instead of all 1000+ memories)     │
└────────────────────────────────────────┘
    ↓
┌────────────────────────────────────────┐
│ 4. INJECT INTO CONTEXT                 │
│    Claude sees only relevant context   │
│    Token budget: ~2-5K (not 20K+)      │
└────────────────────────────────────────┘
```

### Intent Extraction with LangExtract

**LangExtract** is a Python library for extracting structured information from text using LLMs.

#### Installation
```bash
pip install langextract
```

#### Example: Extract Intent from User Prompt
```python
from langextract import extract

# User prompt
user_prompt = "Help me implement JWT authentication with token refresh in auth.py"

# Extract structured intent
intent = await extract(
    user_prompt,
    schema={
        "task_type": "string",  # authentication, database, api, etc.
        "entities": ["string"],  # JWT, Redis, PostgreSQL, etc.
        "files": ["string"],     # auth.py, config.py, etc.
        "operations": ["string"] # implement, fix, refactor, etc.
    }
)

# Result:
# {
#     "task_type": "authentication",
#     "entities": ["JWT", "token refresh"],
#     "files": ["auth.py"],
#     "operations": ["implement"]
# }
```

### Pre-Prompt-Submit Hook with Intent-Driven Retrieval

```python
from langextract import extract
from claude_hooks.lib.memory_client import get_memory_client

async def pre_prompt_submit_with_intent(user_prompt: str) -> str:
    """Pre-prompt-submit with intent-driven memory retrieval"""

    memory_client = get_memory_client()

    # 1. Extract intent from user prompt
    intent = await extract(
        user_prompt,
        schema={
            "task_type": "string",
            "entities": ["string"],
            "files": ["string"],
            "operations": ["string"]
        }
    )

    # 2. Query memory based on intent
    relevant_memories = {}

    # Get success patterns for this task type
    if intent["task_type"]:
        success_patterns = await memory_client.get_memory(
            key=f"success_patterns_{intent['task_type']}",
            category="patterns"
        )
        if success_patterns:
            relevant_memories["success_patterns"] = success_patterns

    # Get execution history for mentioned entities
    for entity in intent["entities"]:
        entity_history = await memory_client.get_memory(
            key=f"execution_history_{entity.lower()}",
            category="execution_history"
        )
        if entity_history:
            relevant_memories[f"history_{entity}"] = entity_history

    # Get file context for mentioned files
    for file in intent["files"]:
        file_context = await memory_client.get_memory(
            key=f"project_context.{file}",
            category="workspace"
        )
        if file_context:
            relevant_memories[f"file_{file}"] = file_context

    # Get intelligence patterns for entities
    for entity in intent["entities"]:
        patterns = await memory_client.get_memory(
            key=f"patterns_{entity.lower()}",
            category="intelligence"
        )
        if patterns:
            relevant_memories[f"patterns_{entity}"] = patterns

    # 3. Rank memories by relevance (optional)
    ranked_memories = rank_memories_by_relevance(
        memories=relevant_memories,
        intent=intent,
        max_tokens=5000  # Budget for memory
    )

    # 4. Inject only relevant memories
    return inject_relevant_context(user_prompt, ranked_memories)
```

### Memory Ranking Algorithm

```python
def rank_memories_by_relevance(
    memories: Dict[str, Any],
    intent: Dict[str, Any],
    max_tokens: int = 5000
) -> Dict[str, Any]:
    """Rank memories by relevance to intent"""

    scored_memories = []

    for key, memory in memories.items():
        score = calculate_relevance_score(memory, intent)
        token_estimate = estimate_tokens(json.dumps(memory))

        scored_memories.append({
            "key": key,
            "memory": memory,
            "score": score,
            "tokens": token_estimate
        })

    # Sort by score (descending)
    scored_memories.sort(key=lambda x: x["score"], reverse=True)

    # Select top memories within token budget
    selected = {}
    total_tokens = 0

    for item in scored_memories:
        if total_tokens + item["tokens"] > max_tokens:
            break

        selected[item["key"]] = item["memory"]
        total_tokens += item["tokens"]

    return selected


def calculate_relevance_score(memory: Any, intent: Dict[str, Any]) -> float:
    """Calculate relevance score (0.0-1.0)"""

    score = 0.0

    # Task type match (+0.3)
    if "task_type" in intent:
        if intent["task_type"].lower() in json.dumps(memory).lower():
            score += 0.3

    # Entity match (+0.2 per entity)
    for entity in intent.get("entities", []):
        if entity.lower() in json.dumps(memory).lower():
            score += 0.2

    # File match (+0.3)
    for file in intent.get("files", []):
        if file.lower() in json.dumps(memory).lower():
            score += 0.3

    # Recency bonus (+0.2 if within last hour)
    if "timestamp" in memory:
        age_hours = (datetime.utcnow() - parse_timestamp(memory["timestamp"])).total_seconds() / 3600
        if age_hours < 1:
            score += 0.2

    # Success rate bonus (+0.2 if high success rate)
    if "success_rate" in memory and memory["success_rate"] > 0.8:
        score += 0.2

    return min(score, 1.0)  # Cap at 1.0
```

### Integration with Context Optimizer

OmniClaude already has a **Context Optimizer** (`agents/lib/context_optimizer.py`) with ML-based prediction. We can enhance it with intent extraction:

```python
# Current: Predict context needs from prompt (ML-based)
predicted_contexts = await predict_context_needs(user_prompt)

# Enhanced: Extract intent + predict + query memory
intent = await extract_intent(user_prompt)
predicted_contexts = await predict_context_needs_with_intent(user_prompt, intent)
relevant_memories = await query_memory_by_intent(intent, predicted_contexts)

# Result: More accurate, targeted memory retrieval
```

### Advanced: Semantic Search with Embeddings

For even better memory retrieval, combine intent extraction with **semantic search**:

```python
from openai import AsyncOpenAI

async def semantic_memory_search(
    user_prompt: str,
    intent: Dict[str, Any],
    top_k: int = 10
) -> List[Dict]:
    """Search memory using semantic similarity"""

    # 1. Generate embedding for user prompt
    openai_client = AsyncOpenAI()
    response = await openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=user_prompt
    )
    query_embedding = response.data[0].embedding

    # 2. Search memory embeddings (stored in Qdrant or PostgreSQL)
    # This leverages your existing Qdrant integration!
    similar_memories = await qdrant_client.search(
        collection_name="memory_embeddings",
        query_vector=query_embedding,
        limit=top_k,
        query_filter={
            "must": [
                {"key": "category", "match": {"value": intent.get("task_type")}}
            ]
        }
    )

    return similar_memories
```

### Benefits of Intent-Driven Retrieval

#### 1. Token Efficiency
**Without Intent Extraction**:
- Load all memories: 20K+ tokens
- Most are irrelevant
- Context budget wasted

**With Intent Extraction**:
- Load only relevant memories: 2-5K tokens
- 75-80% token savings
- More room for actual work

#### 2. Response Quality
**Without Intent Extraction**:
- Claude sees too much noise
- Distracted by irrelevant context
- Lower quality responses

**With Intent Extraction**:
- Claude sees only relevant context
- Focused on the task
- Higher quality responses

#### 3. Performance
**Without Intent Extraction**:
- Slower context processing (20K tokens)
- Higher API costs
- Longer latencies

**With Intent Extraction**:
- Faster context processing (2-5K tokens)
- Lower API costs (75% reduction)
- Shorter latencies

### Implementation Plan Addition

Add to **Phase 2: Hook Integration**:

**New Task**: Intent-Driven Memory Retrieval
- Install LangExtract: `pip install langextract`
- Create `claude_hooks/lib/intent_extractor.py`:
  - Extract intent from user prompts
  - Query memory based on intent
  - Rank memories by relevance
- Integrate with pre-prompt-submit hook
- Benchmark token savings (target: 70-80%)

**Estimated Effort**: +2 days to Phase 2 (total: 5-6 days)

### Example: Full Flow

```python
# User types in Claude Code:
user_prompt = "Help me implement JWT authentication with token refresh"

# Pre-prompt-submit hook runs:
async def pre_prompt_submit(prompt):
    # 1. Extract intent
    intent = await extract_intent(prompt)
    # {
    #     "task_type": "authentication",
    #     "entities": ["JWT", "token refresh"],
    #     "files": [],
    #     "operations": ["implement"]
    # }

    # 2. Query memory based on intent
    relevant_memories = {
        "success_patterns": {
            "authentication": {"count": 45, "success_rate": 0.96}
        },
        "jwt_patterns": {
            "name": "JWT Token Management Pattern",
            "file": "node_auth_handler_effect.py"
        },
        "recent_jwt_execution": {
            "tool": "Edit",
            "file": "auth.py",
            "success": True
        }
    }

    # 3. Inject only relevant context (2K tokens instead of 20K)
    return inject_context(prompt, relevant_memories)

# Claude receives:
# - User prompt
# - 2K tokens of highly relevant context
# - 198K tokens remaining for response
# → Better quality, faster response!
```

---

## Memory Schema Design

### Proposed Memory Categories

#### 1. Workspace State (`category: workspace`)
```python
{
    "workspace_state": {
        "current_branch": "feature/context-management",
        "modified_files": ["agents/lib/memory_client.py"],
        "last_commit": "abc123",
        "active_agents": ["agent-workflow-coordinator"],
        "project_root": "/home/user/omniclaude"
    },
    "project_context": {
        "agents/lib/memory_client.py": {
            "type": "implementation",
            "dependencies": ["anthropic", "asyncio"],
            "last_modified": "2025-11-06T14:30:00Z"
        }
    }
}
```

#### 2. Intelligence Data (`category: intelligence`)
```python
{
    "available_patterns": [
        {
            "name": "Node State Management Pattern",
            "confidence": 0.95,
            "file": "node_state_manager_effect.py"
        }
    ],
    "recent_manifest": {
        "timestamp": "2025-11-06T14:30:00Z",
        "patterns_count": 120,
        "query_time_ms": 1842
    }
}
```

#### 3. Execution History (`category: execution_history`)
```python
{
    "tool_execution_Read_1730910000": {
        "tool": "Read",
        "success": true,
        "duration_ms": 45,
        "file": "agents/lib/memory_client.py"
    },
    "tool_execution_Edit_1730910005": {
        "tool": "Edit",
        "success": false,
        "duration_ms": 120,
        "error": "File not read before edit"
    }
}
```

#### 4. Pattern Learning (`category: patterns`)
```python
{
    "success_patterns": {
        "Read → Edit": {
            "count": 142,
            "success_rate": 0.98
        },
        "Grep → Read → Edit": {
            "count": 89,
            "success_rate": 0.95
        }
    },
    "failure_patterns": {
        "Edit without Read": {
            "count": 12,
            "error": "Permission denied / file not in context"
        }
    }
}
```

#### 5. Routing History (`category: routing`)
```python
{
    "recent_routing_decisions": [
        {
            "timestamp": "2025-11-06T14:25:00Z",
            "agent": "agent-workflow-coordinator",
            "confidence": 0.92,
            "task_type": "multi-step workflow"
        }
    ],
    "agent_performance": {
        "agent-workflow-coordinator": {
            "total_invocations": 45,
            "success_rate": 0.96,
            "avg_duration_ms": 1200
        }
    }
}
```

#### 6. Workspace Events (`category: workspace_events`)
```python
{
    "file_change_1730910000": {
        "files": ["agents/lib/memory_client.py"],
        "timestamp": "2025-11-06T14:30:00Z",
        "branch": "feature/context-management",
        "change_type": "modified"
    }
}
```

### Memory Key Naming Convention

```
<category>.<subcategory>.<identifier>

Examples:
- workspace.state.current
- intelligence.patterns.available
- execution_history.tool.Read.1730910000
- patterns.success.Read_Edit
- routing.decisions.recent
- workspace_events.file_change.1730910000
```

---

## Implementation Plan

### Phase 0: Research & Design (1-2 days) ✅ IN PROGRESS
- [x] Document Anthropic's Memory Tool API capabilities
- [x] Design memory schema
- [x] Design hook integration architecture
- [ ] Review Anthropic's API documentation thoroughly
- [ ] Create proof-of-concept code examples

### Phase 1: Memory Client Foundation (2-3 days)
**Goal**: Build memory client wrapper around Anthropic's Memory Tool API

**Tasks**:
1. Create `claude_hooks/lib/memory_client.py`:
   - Memory storage methods
   - Memory retrieval methods
   - Memory update/delete methods
   - Category management
   - Error handling with fallback

2. Implement storage backend:
   - **Option A**: Filesystem (simple, matches Anthropic's design)
   - **Option B**: PostgreSQL (reuse existing database)
   - **Option C**: Hybrid (hot data → filesystem, cold data → PostgreSQL)

3. Add configuration:
   - Enable/disable memory tool
   - Storage backend selection
   - Memory categories to track
   - TTL policies per category

**Deliverables**:
- `claude_hooks/lib/memory_client.py`
- Unit tests for memory operations
- Configuration in `.env` and `config/settings.py`

### Phase 2: Hook Integration (3-4 days)
**Goal**: Integrate memory updates into existing hooks

**Tasks**:
1. **Pre-Prompt-Submit Hook**:
   - Update workspace state
   - Update available patterns
   - Update routing history
   - Update project context

2. **Post-Tool-Use Hook**:
   - Store execution results
   - Update success/failure patterns
   - Track tool usage patterns

3. **Pre-Tool-Use Hook** (optional):
   - Store tool intent
   - Update validation results

4. **Workspace-Change Hook** (new):
   - Implement file change detection
   - Update file change events
   - Update project context
   - Run in background (non-blocking)

**Deliverables**:
- Modified hook scripts with memory updates
- Integration tests for each hook
- Performance benchmarks (hook latency impact)

### Phase 3: Context Editing Integration (1-2 days)
**Goal**: Enable automatic stale context cleanup

**Tasks**:
1. Add context editing configuration:
   ```python
   ANTHROPIC_CONTEXT_EDITING_ENABLED=true
   ANTHROPIC_BETA_HEADER="anthropic-beta: context-management-2025-06-27"
   ```

2. Update manifest injector to support context editing:
   - Reduce redundant pattern injections (let context editing clean up)
   - Focus on fresh, relevant patterns only

3. Monitor context editing behavior:
   - Log what gets cleaned up
   - Track token savings
   - Measure performance impact

**Deliverables**:
- Context editing configuration
- Updated manifest injector
- Monitoring dashboards

### Phase 4: Migration from Correlation Manager (2-3 days)
**Goal**: Migrate existing correlation manager to memory tool

**Tasks**:
1. Create migration utility:
   - Read existing correlation state files
   - Convert to memory tool format
   - Store in new memory backend

2. Update existing code:
   - Replace `correlation_manager.py` calls with `memory_client.py`
   - Maintain backward compatibility (fallback to old system)
   - Add deprecation warnings

3. Update context manager:
   - Use memory tool for persistent storage
   - Remove in-memory caching (let Anthropic handle it)
   - Simplify token budget management

**Deliverables**:
- Migration utility
- Updated components (correlation manager, context manager, etc.)
- Backward compatibility tests

### Phase 5: Testing & Validation (2-3 days)
**Goal**: Validate performance improvements and correctness

**Tasks**:
1. Performance benchmarks:
   - Measure 39% improvement target
   - Compare memory tool vs. correlation manager
   - Hook latency impact analysis

2. Integration tests:
   - Multi-hook workflows
   - Cross-session persistence
   - Memory retrieval accuracy

3. Load testing:
   - High-frequency hook executions
   - Large memory datasets
   - Concurrent memory operations

**Deliverables**:
- Performance benchmark report
- Integration test suite
- Load test results

### Phase 6: Documentation & Rollout (1-2 days)
**Goal**: Document and deploy to production

**Tasks**:
1. Documentation:
   - Update `CLAUDE.md` with memory tool section
   - Create memory management guide
   - Document memory schema
   - Add troubleshooting guide

2. Deployment:
   - Enable in development environment
   - Test with real workloads
   - Gradual rollout to production

**Deliverables**:
- Updated documentation
- Deployment guide
- Production monitoring setup

### Total Effort: 12-17 days (2.5-3.5 weeks)

---

## API Integration Details

### Anthropic Memory Tool API

#### Configuration
```python
# .env
ANTHROPIC_CONTEXT_MANAGEMENT_ENABLED=true
ANTHROPIC_BETA_HEADER="anthropic-beta: context-management-2025-06-27"
MEMORY_STORAGE_BACKEND="filesystem"  # or "postgresql", "hybrid"
MEMORY_STORAGE_PATH="/home/user/.claude/memory"
```

#### Memory Client Interface
```python
from claude_hooks.lib.memory_client import MemoryClient

# Initialize
memory_client = MemoryClient(
    storage_backend="filesystem",
    storage_path="/home/user/.claude/memory"
)

# Store memory
await memory_client.store_memory(
    key="workspace_state",
    value={"branch": "main", "files": [...]},
    category="workspace"
)

# Retrieve memory
workspace_state = await memory_client.get_memory(
    key="workspace_state",
    category="workspace"
)

# Update memory (delta)
await memory_client.update_memory(
    key="success_patterns",
    delta={"Read_Edit": {"count": 1}},
    category="patterns"
)

# Delete memory
await memory_client.delete_memory(
    key="stale_pattern",
    category="patterns"
)

# List memories by category
all_workspace_memory = await memory_client.list_memory(
    category="workspace"
)
```

#### Hook Integration Pattern
```python
# In pre-prompt-submit hook
from claude_hooks.lib.memory_client import get_memory_client

async def pre_prompt_submit_hook(user_prompt: str):
    """Update memory before prompt submission"""

    memory_client = get_memory_client()

    # 1. Get workspace state
    workspace_state = {
        "branch": get_git_branch(),
        "modified_files": get_modified_files(),
        "last_commit": get_last_commit_hash()
    }

    # 2. Update memory
    await memory_client.store_memory(
        key="workspace_state",
        value=workspace_state,
        category="workspace"
    )

    # 3. Get manifest (as before)
    manifest = await get_manifest_from_intelligence()

    # 4. Update available patterns in memory
    await memory_client.store_memory(
        key="available_patterns",
        value=manifest["patterns"],
        category="intelligence"
    )

    # 5. Inject manifest (as before)
    return inject_manifest(user_prompt, manifest)
```

### Storage Backend Implementation

#### Option A: Filesystem (Recommended - Matches Anthropic's Design)
```python
class FilesystemMemoryBackend:
    """File-based storage for memory tool"""

    def __init__(self, base_path: str = "/home/user/.claude/memory"):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    async def store(self, category: str, key: str, value: Any):
        """Store memory item"""
        category_path = self.base_path / category
        category_path.mkdir(exist_ok=True)

        file_path = category_path / f"{key}.json"
        async with aiofiles.open(file_path, 'w') as f:
            await f.write(json.dumps({
                "key": key,
                "value": value,
                "category": category,
                "timestamp": datetime.utcnow().isoformat(),
                "version": 1
            }))

    async def retrieve(self, category: str, key: str) -> Optional[Any]:
        """Retrieve memory item"""
        file_path = self.base_path / category / f"{key}.json"

        if not file_path.exists():
            return None

        async with aiofiles.open(file_path, 'r') as f:
            data = json.loads(await f.read())
            return data["value"]

    async def update(self, category: str, key: str, delta: Any):
        """Update memory item with delta"""
        current = await self.retrieve(category, key) or {}

        # Merge delta (simple dict merge, can be enhanced)
        if isinstance(current, dict) and isinstance(delta, dict):
            updated = {**current, **delta}
        else:
            updated = delta

        await self.store(category, key, updated)

    async def delete(self, category: str, key: str):
        """Delete memory item"""
        file_path = self.base_path / category / f"{key}.json"
        if file_path.exists():
            file_path.unlink()
```

#### Option B: PostgreSQL Backend
```python
class PostgreSQLMemoryBackend:
    """Database storage for memory tool"""

    async def store(self, category: str, key: str, value: Any):
        """Store memory item in PostgreSQL"""
        async with get_db_connection() as conn:
            await conn.execute("""
                INSERT INTO memory_storage (category, key, value, updated_at)
                VALUES ($1, $2, $3, NOW())
                ON CONFLICT (category, key)
                DO UPDATE SET value = $3, updated_at = NOW()
            """, category, key, json.dumps(value))
```

---

## Performance Benefits

### Expected Improvements

#### 1. Context Management (from Anthropic's benchmarks)
- **Context Editing Only**: 29% performance improvement
- **Memory Tool + Context Editing**: 39% performance improvement
- **Extended Agent Runtime**: 2-3x longer without token limit issues

#### 2. Hook Latency Impact
**Current Hook Latency** (without memory updates):
- Pre-prompt-submit: ~50-100ms (manifest injection)
- Post-tool-use: ~10-20ms (metrics collection)

**Estimated Latency with Memory Updates**:
- Pre-prompt-submit: ~100-150ms (+50ms for memory writes)
- Post-tool-use: ~30-50ms (+20-30ms for memory writes)

**Mitigation**:
- Async memory writes (non-blocking)
- Batch memory updates
- Background memory writes for non-critical data

#### 3. Token Budget Savings
**Current**: Manifest injector adds 10-20K tokens per prompt

**With Context Editing**:
- Stale patterns auto-removed
- Only fresh patterns injected
- Estimated savings: 30-50% reduction in manifest size

#### 4. Cross-Session Performance
**Current**: Every session starts cold (no context)

**With Memory Tool**:
- Warm start with workspace state
- Recent patterns already in memory
- Routing history preserved
- Estimated: 40-60% reduction in cold start time

### Benchmark Plan

```python
# Performance benchmark suite
async def benchmark_memory_tool():
    """Benchmark memory tool performance"""

    # 1. Memory write latency
    start = time.time()
    await memory_client.store_memory("test_key", {"data": "test"}, "benchmark")
    write_latency = (time.time() - start) * 1000
    print(f"Memory write latency: {write_latency:.2f}ms")

    # 2. Memory read latency
    start = time.time()
    await memory_client.get_memory("test_key", "benchmark")
    read_latency = (time.time() - start) * 1000
    print(f"Memory read latency: {read_latency:.2f}ms")

    # 3. Hook latency impact
    start = time.time()
    await pre_prompt_submit_with_memory(user_prompt)
    hook_latency = (time.time() - start) * 1000
    print(f"Pre-prompt-submit latency: {hook_latency:.2f}ms")

    # 4. Cross-session context preservation
    # Measure: Time to restore full context from memory vs. regenerating
```

---

## Migration Strategy

### Phase 1: Parallel Running (2 weeks)
- Run both correlation manager AND memory tool
- Compare results for correctness
- Identify edge cases

### Phase 2: Gradual Cutover (1 week)
- Switch 20% of hooks to memory tool only
- Monitor performance and errors
- Gradually increase to 50%, 80%, 100%

### Phase 3: Deprecation (1 week)
- Remove correlation manager code
- Clean up old state files
- Update all documentation

### Backward Compatibility

```python
class MemoryClient:
    """Memory client with fallback to correlation manager"""

    async def store_memory(self, key, value, category):
        """Store with fallback"""
        try:
            # Try new memory tool
            await self._store_memory_tool(key, value, category)
        except MemoryToolError as e:
            logger.warning(f"Memory tool failed, falling back: {e}")
            # Fallback to correlation manager
            set_correlation_id(key, value)
```

---

## Risk Assessment

### Technical Risks

#### 1. Beta API Stability
**Risk**: API changes, deprecations
**Mitigation**:
- Abstract behind `MemoryClient` interface
- Easy to swap backends
- Monitor Anthropic's changelog

#### 2. Storage Backend Performance
**Risk**: Filesystem I/O becomes bottleneck
**Mitigation**:
- Async I/O throughout
- Batch writes where possible
- Consider PostgreSQL for high volume

#### 3. Memory Growth
**Risk**: Memory storage grows unbounded
**Mitigation**:
- TTL policies per category
- Auto-cleanup of old entries
- Size limits per category

#### 4. Hook Latency Impact
**Risk**: Memory writes slow down hooks
**Mitigation**:
- Non-blocking async writes
- Background writes for non-critical data
- Monitoring and alerting

### Operational Risks

#### 1. Storage Backend Failures
**Risk**: Filesystem/database unavailable
**Mitigation**:
- Graceful degradation (skip memory updates)
- Fallback to correlation manager
- Health checks

#### 2. Migration Issues
**Risk**: Data loss during migration
**Mitigation**:
- Parallel running period
- Full backup before migration
- Rollback plan

---

## Success Metrics

### Phase 1 Success Criteria
- ✅ Memory client operational with <50ms write latency
- ✅ Storage backend working (filesystem or PostgreSQL)
- ✅ Unit tests passing (>90% coverage)

### Phase 2 Success Criteria
- ✅ All hooks integrated with memory updates
- ✅ Hook latency impact <50ms
- ✅ Cross-session memory retrieval working

### Phase 3 Success Criteria
- ✅ Context editing enabled
- ✅ Token budget reduced by 30-50%
- ✅ Anthropic's 39% performance improvement validated

### Phase 4 Success Criteria
- ✅ Correlation manager deprecated
- ✅ Backward compatibility tests passing
- ✅ Migration completed with no data loss

### Overall Success Metrics
- **Performance**: 39% improvement (Anthropic's benchmark)
- **Latency**: Hook overhead <50ms
- **Persistence**: 100% cross-session memory retrieval
- **Token Savings**: 30-50% reduction in manifest size
- **Agent Runtime**: 2-3x longer without token limit issues

---

## Next Steps

### Immediate Actions (Today)
1. ✅ Complete architecture design (this document)
2. [ ] Review Anthropic's Memory Tool documentation thoroughly
3. [ ] Create proof-of-concept code for memory client
4. [ ] Get team feedback on architecture

### This Week
1. [ ] Implement memory client foundation (Phase 1)
2. [ ] Create filesystem storage backend
3. [ ] Write unit tests for memory operations

### Next Week
1. [ ] Integrate memory updates into hooks (Phase 2)
2. [ ] Test cross-session persistence
3. [ ] Benchmark performance

---

## Appendix A: Code Examples

### Example 1: Pre-Prompt-Submit with Memory
```python
async def pre_prompt_submit_with_memory(user_prompt: str) -> str:
    """Pre-prompt-submit hook with memory updates"""

    memory_client = get_memory_client()

    # Update workspace state
    await memory_client.store_memory(
        key="workspace_state",
        value={
            "branch": get_git_branch(),
            "modified_files": get_git_status(),
            "last_commit": get_last_commit(),
            "timestamp": datetime.utcnow().isoformat()
        },
        category="workspace"
    )

    # Get and update patterns
    manifest = await get_manifest_from_intelligence()
    await memory_client.store_memory(
        key="available_patterns",
        value=manifest["patterns"],
        category="intelligence"
    )

    # Update routing history
    recent_routing = await get_recent_routing_decisions()
    await memory_client.store_memory(
        key="recent_routing",
        value=recent_routing,
        category="routing"
    )

    # Inject manifest (as before)
    return inject_manifest(user_prompt, manifest)
```

### Example 2: Post-Tool-Use with Pattern Learning
```python
async def post_tool_use_with_memory(
    tool_name: str,
    success: bool,
    duration_ms: float,
    error: Optional[str] = None
):
    """Post-tool-use hook with pattern learning"""

    memory_client = get_memory_client()

    # Store execution result
    execution_id = f"tool_execution_{tool_name}_{int(time.time())}"
    await memory_client.store_memory(
        key=execution_id,
        value={
            "tool": tool_name,
            "success": success,
            "duration_ms": duration_ms,
            "error": error,
            "timestamp": datetime.utcnow().isoformat()
        },
        category="execution_history"
    )

    # Update success/failure patterns
    if success:
        await memory_client.update_memory(
            key="success_patterns",
            delta={
                tool_name: {
                    "count": 1,
                    "avg_duration_ms": duration_ms
                }
            },
            category="patterns"
        )
    else:
        await memory_client.update_memory(
            key="failure_patterns",
            delta={
                tool_name: {
                    "count": 1,
                    "error": error
                }
            },
            category="patterns"
        )
```

### Example 3: Workspace-Change Hook
```python
async def on_workspace_change(changed_files: List[str]):
    """Background hook for file changes"""

    memory_client = get_memory_client()

    # Store file change event
    event_id = f"file_change_{int(time.time())}"
    await memory_client.store_memory(
        key=event_id,
        value={
            "files": changed_files,
            "branch": get_git_branch(),
            "timestamp": datetime.utcnow().isoformat()
        },
        category="workspace_events"
    )

    # Update project context for each changed file
    for file in changed_files:
        context = await analyze_file_context(file)
        await memory_client.update_memory(
            key="project_context",
            delta={
                file: {
                    "type": context["type"],
                    "dependencies": context["dependencies"],
                    "last_modified": datetime.utcnow().isoformat()
                }
            },
            category="workspace"
        )
```

---

## Appendix B: Memory Schema Reference

See [Memory Schema Design](#memory-schema) section for complete schema.

**Categories**:
1. `workspace` - Current workspace state
2. `intelligence` - Patterns, manifest data
3. `execution_history` - Tool execution results
4. `patterns` - Success/failure patterns
5. `routing` - Routing decisions and performance
6. `workspace_events` - File changes, git events

---

**Document Version**: 1.0
**Status**: Proposal - Ready for Review
**Next Action**: Get team feedback, start Phase 1 implementation
