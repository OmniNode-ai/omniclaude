# Intelligent Context Management Proxy

**Status**: Planning - Phase 0 (Architecture Design - **REVISED FOR EVENT-DRIVEN NODES**)
**Created**: 2025-11-08
**Last Updated**: 2025-11-09
**Priority**: Critical - Revolutionary Feature
**Correlation ID**: TBD
**Architecture**: Event-driven ONEX 5-node system with Kafka/Redpanda communication

---

## Executive Summary

This document proposes a **revolutionary Intelligent Context Management Proxy** that sits transparently between Claude Code and Anthropic's API, providing complete control over conversation context while integrating with OmniClaude's full intelligence infrastructure.

### Problem Statement

**Current Limitations**:
- ❌ **200K token hard limit** - Conversations must be compacted when context fills
- ❌ **Compaction loses history** - Older messages permanently deleted
- ❌ **5K token budget** - Hooks can only inject limited context
- ❌ **No context control** - Can't remove stale messages or rewrite context
- ❌ **Intelligence underutilized** - Qdrant, Memgraph, PostgreSQL data not accessible during conversations

### Solution: Layered Intelligence Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 1: HOOK-BASED MEMORY (Baseline - Always Available)      │
├─────────────────────────────────────────────────────────────────┤
│  • Pre-prompt hook: 5K tokens (lightweight, <100ms)             │
│  • Post-tool hook: Pattern capture (learning)                   │
│  • Workspace hook: File tracking (awareness)                    │
│  • Works standalone WITHOUT proxy                               │
└─────────────────────────────────────────────────────────────────┘
                               ↓ enhances
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 2: INTELLIGENT PROXY (Enhancement - Optional)            │
├─────────────────────────────────────────────────────────────────┤
│  • FastAPI HTTP entry point (Claude Code compatibility)         │
│  • Event-driven internal architecture (Kafka/Redpanda)          │
│  • 5 ONEX nodes (Reducer, Orchestrator, 2 Effects, 1 Compute)   │
│  • Intent emission pattern (Reducer → Intents → Orchestrator)   │
│  • Reuses ManifestInjector + IntelligenceEventClient            │
│  • Rewrites ENTIRE context (remove stale, inject intelligence)  │
│  • Injects 50K+ tokens of intelligence                          │
│  • Never hits 200K limit (proactive management)                 │
│  • Falls back to hooks if unavailable                           │
└─────────────────────────────────────────────────────────────────┘
```

### Key Benefits

| Feature | Value | Impact |
|---------|-------|--------|
| **Infinite conversations** | Never compact again | Cross-session continuity |
| **Intelligence injection** | 50K+ tokens | Patterns, examples, debug intel |
| **Token savings** | 75-80% | vs full memory dump |
| **Context control** | Complete | Remove stale, keep relevant |
| **Graceful degradation** | Hooks still work | If proxy down |
| **OAuth transparent** | No API key needed | Passes through Claude Code auth |
| **Pattern learning** | Continuous | Every conversation improves system |
| **Event-driven** | Kafka/Redpanda | Scalable, distributed, observable |

### Architecture Highlights

**NEW: Event-Driven ONEX Architecture**:
- **FastAPI Entry** - HTTP endpoint for Claude Code (`ANTHROPIC_BASE_URL=http://localhost:8080`)
- **Kafka Event Bus** - ALL internal communication via Redpanda (no direct HTTP between nodes)
- **5 ONEX Nodes** - Reducer (intent emission), Orchestrator (LlamaIndex Workflow), 2 Effects (I/O), 1 Compute (pure logic)
- **Intent Pattern** - Reducer emits intents → Orchestrator coordinates → Nodes execute
- **Reuses Existing Code** - ManifestInjector (3300 LOC), IntelligenceEventClient, Memory Client
- **Topic Layers** - Intent topics (coordination) + Event topics (domain) + Existing topics (reuse)

### ROI Analysis

**Development Cost**: ~20-30 days (5 phases)

**Benefits**:
- **Time Saved**: No manual context management, no compaction interruptions
- **Intelligence Utilization**: 120+ patterns from Qdrant finally accessible in conversations
- **Cross-Session Memory**: Resume any conversation from any session
- **Pattern Learning**: System improves automatically from every interaction
- **Token Efficiency**: 75-80% reduction in memory context (5K → 50K targeted vs 200K full)

**Cost vs. Benefit**: High-ROI feature - unlocks full intelligence infrastructure

---

## Background & Motivation

### Current Architecture

**Hook-Based Memory** (Phase 2 - Complete):
- `claude_hooks/pre_prompt_submit.py` - Injects 5K tokens of relevant memories
- `claude_hooks/post_tool_use.py` - Captures execution patterns
- `claude_hooks/workspace_change.py` - Tracks file modifications
- `claude_hooks/lib/memory_client.py` - Filesystem storage (~/.claude/memory/)
- `claude_hooks/lib/intent_extractor.py` - Extract task type, entities, operations

**Strengths**:
- ✅ Lightweight (<100ms overhead)
- ✅ Works out-of-the-box (no proxy needed)
- ✅ Already implemented and tested
- ✅ Graceful (non-blocking failures)

**Limitations**:
- ⚠️ Limited to 5K token budget
- ⚠️ Can only ADD context (not remove)
- ⚠️ Still subject to Claude Code's compaction
- ⚠️ No control over message array

**Intelligence Infrastructure** (Available but Underutilized):
- `agents/lib/manifest_injector.py` - Queries intelligence for agent manifests (3300 LOC)
- `agents/lib/intelligence_event_client.py` - Kafka event bus communication
- **Qdrant** (192.168.86.101:6333) - 120+ patterns (execution + code)
- **Memgraph** (192.168.86.101:7687) - Relationship graphs
- **PostgreSQL** (192.168.86.200:5436) - Debug intelligence, execution logs
- **Valkey** (localhost:6379) - Caching layer

**Current Usage**: Only available to agents via manifest injection, NOT during normal Claude Code conversations

### Existing Proxy (omnibase)

**tool_capture_proxy** (`/Users/jonah/Code/omnibase/src/omnibase/services/tool_capture_proxy.py`):
- ✅ Transparent HTTP proxy (Claude Code → Anthropic)
- ✅ OAuth passthrough (no API key modification)
- ✅ Request/response capture
- ✅ Brain emoji injection (🧠) - proves response modification works
- ✅ Kafka event publishing

**What it does**:
- Intercepts all Claude Code ↔ Anthropic communication
- Captures system prompts, user messages, tool calls
- Publishes events to Kafka topics
- Modifies responses (brain emoji proves this works!)

**What it DOESN'T do** (yet):
- ❌ Intent extraction
- ❌ Intelligence queries
- ❌ Context rewriting
- ❌ Message pruning
- ❌ Pattern learning

### Why Proxy + Hooks Together?

**Complementary, Not Competing**:

```
User Prompt
    ↓
Pre-prompt hook adds 5K tokens (fast, always works)
    ↓
Enhanced prompt with memory context
    ↓
Proxy intercepts (reads hook-enhanced context)
    ↓
Proxy adds 50K+ tokens from intelligence systems (via Kafka events)
    ↓
Final prompt = Memory (5K) + Intelligence (50K+)
    ↓
Anthropic API
    ↓
Response
    ↓
Proxy captures (stores in Qdrant, PostgreSQL, Kafka)
    ↓
Post-tool hook captures (stores in Memory Client)
    ↓
Both contribute to learning loop!
```

**Graceful Degradation**:
- Proxy down? → Hooks still work (5K tokens, better than nothing)
- Hooks disabled? → Proxy still works (50K+ intelligence)
- Both running? → **Maximum intelligence!** (55K+ tokens)

---

## Architecture Overview

### High-Level Flow (Event-Driven with Intent Pattern)

```
┌─────────────────────────────────────────────────────────────────┐
│  1. CLAUDE CODE → FASTAPI PROXY (HTTP Entry Point)             │
│     URL: http://localhost:8080                                  │
│     OAuth: Passed through unchanged                             │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│  2. FASTAPI → NodeContextRequestReducer (Kafka Event)           │
│     Topic: context.request.received.v1                          │
│     Envelope: { event_id, correlation_id, payload: { request } }│
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│  3. NodeContextRequestReducer (FSM State Tracking)              │
│     Consumes: context.request.received.v1 event                 │
│     FSM Logic: Transition state: idle → request_received        │
│     Emits Intent: PERSIST_STATE → intents.persist-state.v1      │
│     Pure: In-memory FSM state updates, no decisions             │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│  4. NodeContextProxyOrchestrator (LlamaIndex Workflow)          │
│     Reads FSM state from Reducer (check current state)          │
│     Step 1: Publish query event → intelligence query Effect     │
│     Waits for FSM: request_received → intelligence_queried      │
│     Step 2: Publish rewrite event → context rewriter Compute    │
│     Waits for FSM: intelligence_queried → context_rewritten     │
│     Step 3: Publish forward event → Anthropic forwarder Effect  │
│     Waits for FSM: context_rewritten → completed                │
│     Coordination: Drives workflow, reads FSM for progress       │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│  5. NodeIntelligenceQueryEffect (External I/O via Kafka)        │
│     ✅ REUSES: ManifestInjector (3300 LOC)                      │
│     ✅ REUSES: IntelligenceEventClient                          │
│     Queries:                                                    │
│       - Qdrant (execution_patterns, code_patterns)              │
│       - PostgreSQL (debug_intelligence)                         │
│       - Memory Client (archived context)                        │
│     Topics:                                                     │
│       - Request: dev.archon-intelligence.intelligence           │
│                   .code-analysis-requested.v1                   │
│       - Response: *.code-analysis-completed.v1                  │
│       - Error: *.code-analysis-failed.v1                        │
│     Returns: { patterns: [], debug_intel: {}, memory: {} }     │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│  6. NodeContextRewriterCompute (Pure Computation)               │
│     Input: { messages, intelligence, intent }                   │
│     Processing:                                                 │
│       - Remove stale messages (keep recent + relevant + tools)  │
│       - Format intelligence manifest                            │
│       - Inject manifest into system prompt                      │
│       - Ensure token limit (<180K)                              │
│     Output: { rewritten_messages, rewritten_system_prompt }    │
│     Deterministic: Yes (cacheable)                              │
│     No I/O: Pure transformation                                 │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│  7. NodeAnthropicForwarderEffect (External I/O to Anthropic)    │
│     Input: { rewritten_request }                                │
│     Processing:                                                 │
│       - Forward to Anthropic API (HTTPS)                        │
│       - OAuth token passthrough (no modification)               │
│       - Capture response                                        │
│     Output: { response, success: true }                         │
│     Side Effects: HTTP request to Anthropic                     │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│  8. NodeContextRequestReducer (FSM State Tracking - Final)      │
│     Consumes: context.forward.completed.v1 event                │
│     FSM Logic: Transition state: context_rewritten → completed  │
│     Emits Intent: PERSIST_STATE → intents.persist-state.v1      │
│     Pure: FSM state update only, no aggregation decisions       │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│  9. Orchestrator Sends Response (Workflow Complete)            │
│     Reads FSM state (check completed = true)                    │
│     Publishes: context.response.completed.v1                    │
│     Returns to FastAPI via Kafka event                          │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│  10. FASTAPI → CLAUDE CODE (HTTP Response)                      │
│      User sees enhanced response (never knows proxy exists!)    │
└─────────────────────────────────────────────────────────────────┘
```

### Event Flow Diagram (Intent Pattern)

```
┌──────────────┐
│ Claude Code  │
└──────┬───────┘
       │ HTTP POST /v1/messages
       │ (OAuth token in headers)
       ↓
┌──────────────────────────┐
│ FastAPI Proxy (Port 8080)│
│  • Receives HTTP request │
│  • Publishes Kafka event │
└──────┬───────────────────┘
       │ Event: context.request.received.v1
       │ {
       │   event_id: "xyz",
       │   correlation_id: "abc-123",
       │   payload: { request_data, oauth_token }
       │ }
       ↓
┌─────────────────────────────────────────────────────────────┐
│ NodeContextRequestReducer (FSM State Tracker)               │
│  • Consumes: context.request.received.v1                    │
│  • FSM Logic: Update state (idle → request_received)        │
│  • Emit Intent (persistence I/O):                           │
│    ↓ PERSIST_STATE → intents.persist-state.v1               │
│  • Pure: In-memory FSM state transitions only               │
└─────────────────────────────────────────────────────────────┘
       │ Intent Layer (coordination)
       ↓
┌─────────────────────────────────────────────────────────────┐
│ NodeContextProxyOrchestrator (Workflow Coordinator)         │
│  • Reads FSM state from Reducer (via shared state)          │
│  • LlamaIndex Workflow: Coordinate execution                │
│                                                             │
│  Step 1: Query Intelligence (check FSM: request_received)   │
│    ↓ publishes: context.query.requested.v1 (domain event)  │
│    ↓ waits for FSM transition → intelligence_queried       │
│                                                             │
│  Step 2: Rewrite Context (check FSM: intelligence_queried)  │
│    ↓ publishes: context.rewrite.requested.v1               │
│    ↓ waits for FSM transition → context_rewritten          │
│                                                             │
│  Step 3: Forward to Anthropic (check FSM: context_rewritten)│
│    ↓ publishes: context.forward.requested.v1               │
│    ↓ waits for FSM transition → completed                  │
└─────────────────────────────────────────────────────────────┘
       ↓ Domain Event Layer      ↓                    ↓
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ Intelligence │  │   Context    │  │  Anthropic   │
│ Query Effect │  │ Rewriter Cmp │  │ Forwarder Eff│
│              │  │              │  │              │
│ Consumes:    │  │ Consumes:    │  │ Consumes:    │
│ *.query.req  │  │ *.rewrite.req│  │ *.forward.req│
│              │  │              │  │              │
│ REUSES:      │  │ Pure Logic:  │  │ External I/O:│
│ Manifest     │  │ - Prune msgs │  │ - HTTP POST  │
│ Injector +   │  │ - Format     │  │ - OAuth pass │
│ Event Client │  │ - Inject     │  │ - Capture    │
│              │  │ - Token mgmt │  │              │
│ Queries via  │  │              │  │ Publishes:   │
│ Kafka:       │  │ Publishes:   │  │ *.forward    │
│ - Qdrant     │  │ *.rewrite    │  │  .completed  │
│ - Postgres   │  │  .completed  │  │              │
│ - Memory     │  │              │  │              │
│              │  │              │  │              │
│ Publishes:   │  │              │  │              │
│ *.query      │  │              │  │              │
│  .completed  │  │              │  │              │
└──────┬───────┘  └──────┬───────┘  └──────┬───────┘
       │ Domain Events   │                  │
       └─────────────────┴──────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│ NodeContextRequestReducer (FSM State Tracker - Final)       │
│  • Consumes: context.forward.completed.v1 (final event)     │
│  • FSM Logic: Update state (context_rewritten → completed)  │
│  • Emit Intent: PERSIST_STATE → intents.persist-state.v1    │
│  • Pure: FSM state transition only, no aggregation          │
└─────────────────────────────────────────────────────────────┘
       ↓ FSM state updated: completed
┌─────────────────────────────────────────────────────────────┐
│ NodeContextProxyOrchestrator (Workflow Complete)            │
│  • Reads FSM state (check completed = true)                 │
│  • Publishes: context.response.completed.v1                 │
│  • Returns to FastAPI via event                             │
└─────────────────────────────────────────────────────────────┘
       ↓ context.response.completed.v1
┌──────────────────────────┐
│ FastAPI Proxy            │
│  • Awaits response event │
│  • Returns HTTP response │
└──────┬───────────────────┘
       ↓ HTTP 200 OK
┌──────────────┐
│ Claude Code  │
└──────────────┘
```

**Key Pattern Insights**:
- **Intent Topics** (persistence layer): `intents.persist-state.v1` - FSM state persistence commands
- **Domain Event Topics** (execution layer): `context.{action}.{status}.v1` - Actual work execution
- **Reducer Role**: FSM state tracking ONLY (consumes events → updates state → emits persistence intent)
- **Orchestrator Role**: Workflow coordination (reads FSM state → publishes domain events → drives workflow)
- **Pure Separation**: Reducer = FSM state machine, Orchestrator = workflow engine, Nodes = execution
- **State Flow**: Events → Reducer (FSM update) → Orchestrator (reads FSM) → Domain Events → Nodes

### Total Latency Budget

| Stage | Time | Cumulative |
|-------|------|------------|
| Pre-prompt hook | <100ms | 100ms |
| FastAPI → Orchestrator | <10ms | 110ms |
| Intent extraction | <100ms | 210ms |
| Intelligence queries (via Kafka) | <2000ms | 2210ms |
| Context rewriting | <100ms | 2310ms |
| Forward to Anthropic | ~500ms | 2810ms |
| **Total overhead** | **~2.8s** | **Acceptable** |

**Optimization Opportunities**:
- Cache intelligence queries (60%+ hit rate)
- Parallel processing (already doing via Kafka)
- Reduce intelligence query timeout (1000ms instead of 2000ms)

---

## Component Specifications (ONEX Nodes)

### Node Overview

**5 ONEX Nodes** (FSM-Driven Pattern):

1. **NodeContextRequestReducer** (Reducer) - FSM state tracker (consumes events, updates state, emits persistence intents)
2. **NodeContextProxyOrchestrator** (Orchestrator) - Workflow coordinator (reads FSM state, publishes domain events, drives workflow)
3. **NodeIntelligenceQueryEffect** (Effect) - Intelligence queries via Kafka
4. **NodeContextRewriterCompute** (Compute) - Pure context rewriting logic
5. **NodeAnthropicForwarderEffect** (Effect) - HTTP forwarding to Anthropic

**FSM-Driven Pattern Flow**:
```
FastAPI → Reducer (FSM: idle → request_received) →
Orchestrator (reads FSM, starts workflow) →
Step 1: Orchestrator publishes query event → Intelligence Effect executes → Reducer (FSM: request_received → intelligence_queried) →
Step 2: Orchestrator reads FSM, publishes rewrite event → Context Rewriter executes → Reducer (FSM: intelligence_queried → context_rewritten) →
Step 3: Orchestrator reads FSM, publishes forward event → Anthropic Forwarder executes → Reducer (FSM: context_rewritten → completed) →
Orchestrator reads FSM (completed), publishes response → FastAPI
```

---

### 1. NodeContextRequestReducer (FSM State Tracker)

**Purpose**: Track request workflow state via FSM contracts, persist state changes via intents

**Type**: ONEX Reducer Node

**Base Class**: `omnibase_core.nodes.NodeReducer`

**Mixins**: `MixinIntentPublisher` (for persistence intent emission)

**Single Role**: FSM State Tracking ONLY
- Consume domain events (*.completed.v1)
- Update FSM state in-memory (state transitions)
- Emit persistence intent (PERSIST_STATE)
- NO decision logic, NO aggregation, PURE FSM state machine

#### Key Responsibilities

**FSM State Tracking** (Pure State Machine):

1. **Consume Domain Events** (from all nodes)
   - `context.request.received.v1` → Trigger: REQUEST_RECEIVED
   - `context.query.completed.v1` → Trigger: INTELLIGENCE_QUERIED
   - `context.rewrite.completed.v1` → Trigger: CONTEXT_REWRITTEN
   - `context.forward.completed.v1` → Trigger: ANTHROPIC_FORWARDED

2. **FSM State Transitions** (in-memory, pure logic)
   - idle → request_received (on REQUEST_RECEIVED)
   - request_received → intelligence_queried (on INTELLIGENCE_QUERIED)
   - intelligence_queried → context_rewritten (on CONTEXT_REWRITTEN)
   - context_rewritten → completed (on ANTHROPIC_FORWARDED)
   - any_state → failed (on ERROR)

3. **Emit Persistence Intent** (coordination I/O, no direct PostgreSQL)
   - `PERSIST_STATE` → `intents.persist-state.v1`
   - Payload: FSM state snapshot (current_state, previous_state, transition_history, metadata)
   - Target: Store Effect node (handles actual PostgreSQL write)

4. **Provide FSM State** (for Orchestrator reads)
   - `get_state(correlation_id) → current_state`
   - `get_transition_history(correlation_id) → list[transitions]`
   - Orchestrator polls FSM state to understand progress

#### Method Signatures

```python
from omnibase_core.nodes.node_reducer import NodeReducer
from omnibase_core.mixins.mixin_intent_publisher import MixinIntentPublisher
from omnibase_core.models.container import ModelONEXContainer
from omnibase_core.models.contracts.model_contract_reducer import ModelContractReducer
from omnibase_core.models.contracts.subcontracts import ModelFSMSubcontract
from uuid import UUID
from datetime import datetime, UTC
from typing import Optional

class NodeContextRequestReducer(NodeReducer, MixinIntentPublisher):
    """
    Reducer node for intelligent context proxy.

    Single Role: FSM State Tracking ONLY

    FSM Logic:
    - Track workflow state via FSM subcontract
    - Validate state transitions
    - Emit intents for persistence (no direct I/O)

    NO Decision Logic:
    - Does NOT decide what operations to run
    - Does NOT aggregate results
    - Does NOT emit workflow coordination intents

    Pure FSM State Machine:
    - Consumes domain events → Updates FSM state → Emits persistence intent
    """

    def __init__(self, container: ModelONEXContainer) -> None:
        """Initialize with dependency injection."""
        super().__init__(container)

        # FSM State Manager (pure in-memory state tracking)
        self._fsm_manager = FSMStateManager(
            container=container,
            fsm_config=self._load_fsm_config()
        )

        # State cache (correlation_id → FSM state)
        self._state_cache: dict[str, dict] = {}

    async def execute_reduction(
        self,
        contract: ModelContractReducer,
    ) -> ModelReducerOutput:
        """
        Execute FSM state tracking.

        Pure FSM Logic:
        1. Extract event data from contract
        2. Determine FSM trigger from event_type
        3. Update FSM state in-memory (transition validation)
        4. Emit persistence intent (no direct PostgreSQL)
        5. Return updated FSM state
        """
        # Extract event data
        event_type = contract.input_state.get("event_type")
        correlation_id = UUID(contract.correlation_id)

        # Map event type to FSM trigger
        trigger = self._map_event_to_trigger(event_type)

        # Update FSM state (pure in-memory)
        success = await self._fsm_manager.transition(
            workflow_id=correlation_id,
            trigger=trigger,
            metadata=contract.input_state.get("metadata", {})
        )

        if not success:
            raise ModelOnexError(
                message=f"Invalid FSM transition: {event_type}",
                error_code=EnumCoreErrorCode.INVALID_STATE_TRANSITION,
                correlation_id=correlation_id,
            )

        # Get updated FSM state
        current_state = self._fsm_manager.get_state(correlation_id)

        # Emit persistence intent (no direct PostgreSQL)
        await self._emit_persist_state_intent(
            correlation_id=correlation_id,
            fsm_state=current_state,
            transition_history=self._fsm_manager.get_transition_history(correlation_id)
        )

        # Return FSM state (for observability)
        return ModelReducerOutput(
            result={
                "current_state": current_state,
                "trigger": trigger,
                "timestamp": datetime.now(UTC).isoformat(),
            },
            success=True,
            correlation_id=correlation_id,
        )

    def _map_event_to_trigger(self, event_type: str) -> str:
        """Map domain event type to FSM trigger."""
        event_to_trigger = {
            "REQUEST_RECEIVED": "REQUEST_RECEIVED",
            "QUERY_COMPLETED": "INTELLIGENCE_QUERIED",
            "REWRITE_COMPLETED": "CONTEXT_REWRITTEN",
            "FORWARD_COMPLETED": "ANTHROPIC_FORWARDED",
            "ERROR": "ERROR",
        }
        return event_to_trigger.get(event_type, "UNKNOWN")

    async def _emit_persist_state_intent(
        self,
        correlation_id: UUID,
        fsm_state: str,
        transition_history: list[dict],
    ) -> None:
        """Emit intent for FSM state persistence (no direct PostgreSQL)."""
        await self.publish_event_intent(
            target_topic="fsm.state.persisted",  # Target for Store Effect
            event=PersistStateIntent(
                correlation_id=str(correlation_id),
                current_state=fsm_state,
                transition_history=transition_history,
                timestamp=datetime.now(UTC).isoformat(),
            ),
            intent_type=EnumIntentType.PERSIST_STATE,
        )

    def _load_fsm_config(self) -> ModelFSMSubcontract:
        """Load FSM subcontract configuration."""
        return ModelFSMSubcontract(
            states=["idle", "request_received", "intelligence_queried", "context_rewritten", "completed", "failed"],
            transitions={
                "idle": ["request_received"],
                "request_received": ["intelligence_queried", "failed"],
                "intelligence_queried": ["context_rewritten", "failed"],
                "context_rewritten": ["completed", "failed"],
                "completed": [],
                "failed": [],
            },
            initial_state="idle",
        )

    # Public API for Orchestrator
    def get_state(self, correlation_id: UUID) -> Optional[str]:
        """Get current FSM state for workflow."""
        return self._fsm_manager.get_state(correlation_id)

    def get_transition_history(self, correlation_id: UUID) -> list[dict]:
        """Get FSM transition history for workflow."""
        return self._fsm_manager.get_transition_history(correlation_id)

# Supporting models
class PersistStateIntent(BaseModel):
    """Intent payload for FSM state persistence."""
    correlation_id: str
    current_state: str
    transition_history: list[dict]
    timestamp: str

class EnumIntentType(str, Enum):
    """Intent types for Reducer."""
    PERSIST_STATE = "PERSIST_STATE"

class ModelFSMState(BaseModel):
    """FSM state data model."""
    current_state: str
    previous_state: Optional[str] = None
    transition_count: int = 0
    created_at: datetime
    updated_at: datetime
```

#### Kafka Topics

**Input Topics** (Domain Events):
- `context.request.received.v1` (from FastAPI) - Trigger: REQUEST_RECEIVED
- `context.query.completed.v1` (from Intelligence Effect) - Trigger: INTELLIGENCE_QUERIED
- `context.rewrite.completed.v1` (from Rewriter Compute) - Trigger: CONTEXT_REWRITTEN
- `context.forward.completed.v1` (from Forwarder Effect) - Trigger: ANTHROPIC_FORWARDED
- `context.*.failed.v1` (from any node) - Trigger: ERROR

**Output Topics** (Intent Layer):
- `intents.persist-state.v1` - FSM state persistence (consumed by Store Effect)

**Key Pattern**:
- **Consumes**: Domain events (all *.completed.v1, *.failed.v1)
- **Emits**: Persistence intent ONLY (PERSIST_STATE)
- **Pure Logic**: FSM state transitions (no decisions, no aggregation)
- **NO Direct I/O**: All PostgreSQL writes via Store Effect node (intent-driven)

---

### 2. NodeContextProxyOrchestrator (Workflow Coordination)

**Purpose**: Coordinate workflow execution by reading FSM state from Reducer and publishing domain events using LlamaIndex Workflow pattern

**Type**: ONEX Orchestrator Node

**Base Class**: `omnibase_core.nodes.NodeOrchestrator`

**Dependencies**:
- `ModelONEXContainer` - Dependency injection
- `omnibase_core.models.contracts.ModelContractOrchestrator` - Workflow contract
- LlamaIndex Workflow framework (multi-step workflows with dependencies)
- NodeContextRequestReducer reference (for FSM state reads)

#### Key Responsibilities

1. **Read FSM State** (from Reducer - NOT via events)
   - Poll `reducer.get_state(correlation_id)` to check current FSM state
   - Understand workflow progress: idle → request_received → intelligence_queried → context_rewritten → completed
   - Make workflow decisions based on FSM state

2. **Coordinate Workflow Steps** (FSM-driven, NOT intent-driven)
   - Step 1: Check FSM (request_received?) → Publish `context.query.requested.v1` → Wait for FSM transition to intelligence_queried
   - Step 2: Check FSM (intelligence_queried?) → Publish `context.rewrite.requested.v1` → Wait for FSM transition to context_rewritten
   - Step 3: Check FSM (context_rewritten?) → Publish `context.forward.requested.v1` → Wait for FSM transition to completed

3. **Publish Domain Events** (workflow coordination)
   - Publish domain events to trigger node execution
   - Monitor FSM state transitions (via Reducer.get_state())
   - Track workflow progress

4. **Send Response** (when FSM = completed)
   - Check FSM state (completed = true)
   - Publish `context.response.completed.v1` event
   - Return to FastAPI via Kafka

**CRITICAL PATTERN**:
- Orchestrator **reads** FSM state from Reducer (via method calls or shared state)
- Orchestrator **publishes** domain events (triggers node execution)
- Reducer **tracks** FSM state (consumes domain events, updates state)
- **NO** intents from Reducer to Orchestrator (Orchestrator drives workflow independently)

#### Method Signatures

```python
from omnibase_core.nodes.node_orchestrator import NodeOrchestrator
from omnibase_core.models.container import ModelONEXContainer
from omnibase_core.models.model_orchestrator_input import ModelOrchestratorInput
from omnibase_core.enums.enum_orchestrator_types import EnumExecutionMode
from uuid import UUID
import asyncio

class NodeContextProxyOrchestrator(NodeOrchestrator):
    """
    Orchestrator for intelligent context proxy workflow.

    Coordinates 3 sequential steps by reading FSM state from Reducer:
    1. Intelligence Query (Effect) - waits for FSM: request_received → intelligence_queried
    2. Context Rewriting (Compute) - waits for FSM: intelligence_queried → context_rewritten
    3. Anthropic Forwarding (Effect) - waits for FSM: context_rewritten → completed

    FSM-Driven Pattern:
    - Reads FSM state from Reducer (NOT via events, via method calls)
    - Publishes domain events to trigger node execution
    - Waits for FSM transitions before proceeding to next step
    """

    def __init__(self, container: ModelONEXContainer, reducer: NodeContextRequestReducer) -> None:
        """Initialize with dependency injection."""
        super().__init__(container)

        # Reducer reference (for FSM state reads)
        self.reducer = reducer

        # Workflow configuration
        self.max_concurrent_workflows = 10
        self.default_step_timeout_ms = 10000
        self.fsm_poll_interval_ms = 100  # Poll FSM state every 100ms

    async def process(
        self,
        input_data: ModelOrchestratorInput,
    ) -> ModelOrchestratorOutput:
        """
        Execute proxy workflow with 3 sequential steps.

        Flow:
        1. Validate input
        2. Build dependency graph (Step 2 depends on Step 1, Step 3 depends on Step 2)
        3. Execute workflow in sequential mode
        4. Aggregate results
        5. Return to FastAPI
        """
        # Validate input
        self._validate_input(input_data)

        # Execute workflow (sequential mode)
        result = await self._execute_workflow_sequential(input_data)

        # Return aggregated results
        return result

    async def orchestrate_proxy_request(
        self,
        request_data: dict,
        correlation_id: UUID,
    ) -> dict:
        """
        High-level orchestration method for proxy requests.

        FSM-Driven Workflow:
        1. Read FSM state from Reducer
        2. If state = request_received, start workflow
        3. Publish domain events for each step
        4. Wait for FSM transitions before proceeding
        5. Return response when FSM = completed

        Args:
            request_data: Original HTTP request from Claude Code
            correlation_id: Request correlation ID

        Returns:
            Modified response for return to Claude Code
        """
        # Step 1: Read FSM state from Reducer
        current_state = self.reducer.get_state(correlation_id)

        if current_state != "request_received":
            # Already processing or completed
            if current_state == "completed":
                return await self._get_cached_response(correlation_id)
            else:
                raise WorkflowError(f"Invalid FSM state: {current_state}")

        # Step 2: Query Intelligence
        await self._publish_domain_event(
            topic="context.query.requested.v1",
            payload={"request_data": request_data, "correlation_id": str(correlation_id)}
        )

        # Wait for FSM transition: request_received → intelligence_queried
        await self._wait_for_fsm_transition(
            correlation_id=correlation_id,
            expected_state="intelligence_queried",
            timeout_ms=5000
        )

        # Step 3: Rewrite Context
        intelligence_result = await self._get_step_result(correlation_id, "intelligence")

        await self._publish_domain_event(
            topic="context.rewrite.requested.v1",
            payload={
                "messages": request_data.get("messages", []),
                "system_prompt": request_data.get("system", ""),
                "intelligence": intelligence_result,
                "correlation_id": str(correlation_id)
            }
        )

        # Wait for FSM transition: intelligence_queried → context_rewritten
        await self._wait_for_fsm_transition(
            correlation_id=correlation_id,
            expected_state="context_rewritten",
            timeout_ms=2000
        )

        # Step 4: Forward to Anthropic
        rewrite_result = await self._get_step_result(correlation_id, "rewrite")

        await self._publish_domain_event(
            topic="context.forward.requested.v1",
            payload={
                "rewritten_request": rewrite_result,
                "oauth_token": request_data.get("oauth_token"),
                "correlation_id": str(correlation_id)
            }
        )

        # Wait for FSM transition: context_rewritten → completed
        await self._wait_for_fsm_transition(
            correlation_id=correlation_id,
            expected_state="completed",
            timeout_ms=30000
        )

        # Step 5: Get final response and publish response event
        final_response = await self._get_step_result(correlation_id, "forward")

        await self._publish_domain_event(
            topic="context.response.completed.v1",
            payload={"response_data": final_response, "correlation_id": str(correlation_id)}
        )

        return final_response

    async def _wait_for_fsm_transition(
        self,
        correlation_id: UUID,
        expected_state: str,
        timeout_ms: int
    ) -> None:
        """
        Wait for FSM state transition by polling Reducer.

        Args:
            correlation_id: Workflow ID
            expected_state: Expected FSM state
            timeout_ms: Timeout in milliseconds

        Raises:
            TimeoutError: If FSM state does not transition within timeout
        """
        start_time = asyncio.get_event_loop().time()
        timeout_seconds = timeout_ms / 1000.0

        while True:
            # Read current FSM state from Reducer
            current_state = self.reducer.get_state(correlation_id)

            if current_state == expected_state:
                # FSM transitioned successfully
                return

            if current_state == "failed":
                # Workflow failed
                raise WorkflowError("Workflow failed during FSM transition")

            # Check timeout
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > timeout_seconds:
                raise TimeoutError(
                    f"FSM state did not transition to {expected_state} within {timeout_ms}ms "
                    f"(current state: {current_state})"
                )

            # Poll interval
            await asyncio.sleep(self.fsm_poll_interval_ms / 1000.0)
```

#### Kafka Topics

**Input** (from FastAPI):
- `proxy.context.orchestration.requested.v1`

**Output** (to FastAPI):
- `proxy.context.orchestration.completed.v1`
- `proxy.context.orchestration.failed.v1`

**Event Envelope**:

```python
from pydantic import BaseModel, Field
from uuid import uuid4
from datetime import datetime, UTC

class ProxyOrchestrationRequest(BaseModel):
    """Request payload for proxy orchestration."""

    request_data: dict  # Original HTTP request from Claude Code
    oauth_token: str  # OAuth token for Anthropic API
    correlation_id: str

class ProxyOrchestrationResponse(BaseModel):
    """Response payload for proxy orchestration."""

    response_data: dict  # Modified response for Claude Code
    correlation_id: str
    intelligence_query_time_ms: int
    context_rewrite_time_ms: int
    anthropic_forward_time_ms: int
    total_time_ms: int

# Event envelope
{
  "event_id": str(uuid4()),
  "event_type": "PROXY_ORCHESTRATION_REQUESTED",
  "correlation_id": "abc-123",
  "timestamp": datetime.now(UTC).isoformat(),
  "service": "intelligent-context-proxy",
  "payload": ProxyOrchestrationRequest(...),
  "version": "v1"
}
```

---

### 2. NodeIntelligenceQueryEffect (External I/O via Kafka)

**Purpose**: Query intelligence systems (Qdrant, PostgreSQL, Memory) via existing event bus infrastructure

**Type**: ONEX Effect Node

**Base Class**: `omnibase_core.nodes.NodeEffect`

**CRITICAL**: **REUSES EXISTING CODE** - This node is a thin wrapper around:
- `agents/lib/manifest_injector.py` (3300 LOC) - Already queries all intelligence sources
- `agents/lib/intelligence_event_client.py` - Already handles Kafka communication
- `claude_hooks/lib/memory_client.py` - Already manages memory storage

#### Key Responsibilities

1. **Extract Intent** (from request)
   - Use existing `claude_hooks/lib/intent_extractor.py`
   - Extract task_type, entities, operations, files

2. **Query Intelligence** (via existing code)
   - Call `ManifestInjector.generate_dynamic_manifest_async()`
   - Uses `IntelligenceEventClient` under the hood
   - Queries: Qdrant, PostgreSQL, Memgraph, Memory
   - Topics: `dev.archon-intelligence.intelligence.code-analysis-*.v1` (already exists!)

3. **Return Results**
   - Return intelligence data to Orchestrator
   - No transformation needed (pass-through)

#### Method Signatures

```python
from omnibase_core.nodes.node_effect import NodeEffect
from omnibase_core.models.container import ModelONEXContainer
from omnibase_core.models.model_effect_input import ModelEffectInput
from agents.lib.manifest_injector import ManifestInjector
from agents.lib.intelligence_event_client import IntelligenceEventClient
from claude_hooks.lib.intent_extractor import extract_intent
from uuid import UUID

class NodeIntelligenceQueryEffect(NodeEffect):
    """
    Effect node for querying intelligence systems.

    REUSES EXISTING CODE:
    - ManifestInjector (3300 LOC)
    - IntelligenceEventClient
    - Memory Client

    No reimplementation needed!
    """

    def __init__(self, container: ModelONEXContainer) -> None:
        """Initialize with dependency injection."""
        super().__init__(container)

        # REUSE: Existing components
        self.manifest_injector = ManifestInjector()
        self.event_client = IntelligenceEventClient(
            bootstrap_servers=settings.kafka_bootstrap_servers
        )

    async def execute_effect(
        self,
        contract: ModelContractEffect,
    ) -> ModelEffectOutput:
        """
        Execute intelligence query effect.

        REUSES: ManifestInjector.generate_dynamic_manifest_async()

        Flow:
        1. Extract intent from request
        2. Call ManifestInjector (queries Qdrant, PostgreSQL, Memory via Kafka)
        3. Return intelligence data
        """
        # Extract payload
        request_data = contract.input_state.get("request_data", {})
        correlation_id = UUID(contract.correlation_id)

        # Extract intent
        user_prompt = self._extract_latest_user_message(request_data)
        intent = await extract_intent(user_prompt)

        # REUSE: Call existing ManifestInjector
        # This already queries everything via Kafka events!
        manifest_data = await self.manifest_injector.generate_dynamic_manifest_async(
            correlation_id=correlation_id
        )

        # Return results
        return ModelEffectOutput(
            result=manifest_data,
            success=True,
            correlation_id=correlation_id,
        )

    def _extract_latest_user_message(self, request_data: dict) -> str:
        """Extract latest user message for intent extraction."""
        messages = request_data.get("messages", [])
        if not messages:
            return ""

        # Find last user message
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, list):
                    # Handle multi-part content
                    text_parts = [p["text"] for p in content if p.get("type") == "text"]
                    return " ".join(text_parts)
                return content

        return ""
```

#### Kafka Topics

**Input** (from Orchestrator):
- `proxy.intelligence.query.requested.v1`

**Output** (to Orchestrator):
- `proxy.intelligence.query.completed.v1`
- `proxy.intelligence.query.failed.v1`

**External Topics** (used by ManifestInjector - ALREADY EXISTS):
- Request: `dev.archon-intelligence.intelligence.code-analysis-requested.v1`
- Response: `dev.archon-intelligence.intelligence.code-analysis-completed.v1`
- Error: `dev.archon-intelligence.intelligence.code-analysis-failed.v1`

**Event Envelope**:

```python
class IntelligenceQueryRequest(BaseModel):
    """Request payload for intelligence query."""

    request_data: dict  # Original HTTP request
    correlation_id: str
    intent: dict | None = None  # Optional pre-extracted intent

class IntelligenceQueryResponse(BaseModel):
    """Response payload for intelligence query."""

    patterns: list[dict]  # Qdrant patterns
    debug_intelligence: dict  # PostgreSQL debug data
    memory_context: dict  # Memory client data
    query_time_ms: int
    correlation_id: str
```

---

### 3. NodeContextRewriterCompute (Pure Computation)

**Purpose**: Rewrite conversation context by pruning stale messages, formatting intelligence manifest, and managing token budget

**Type**: ONEX Compute Node

**Base Class**: `omnibase_core.nodes.NodeCompute`

**Characteristics**:
- **Pure function** - No I/O, no side effects
- **Deterministic** - Same input always produces same output
- **Cacheable** - Results can be cached for identical inputs
- **Fast** - Target <100ms processing time

#### Key Responsibilities

1. **Message Pruning**
   - Keep recent messages (last 20)
   - Keep tool-heavy messages (Read, Edit, Bash)
   - Keep messages relevant to intent
   - Archive excluded messages to memory

2. **Intelligence Manifest Formatting**
   - Format execution patterns (from Qdrant)
   - Format code examples (from Qdrant)
   - Format debug intelligence (from PostgreSQL)
   - Format archived context summary (from Memory)

3. **Manifest Injection**
   - Append manifest to system prompt
   - Use same format as agent manifests

4. **Token Budget Management**
   - Estimate tokens (tiktoken library)
   - Ensure total < 180K tokens (20K buffer)
   - Aggressive pruning if over limit
   - Manifest truncation if needed

#### Method Signatures

```python
from omnibase_core.nodes.node_compute import NodeCompute
from omnibase_core.models.container import ModelONEXContainer
from omnibase_core.models.model_compute_input import ModelComputeInput
import tiktoken

class NodeContextRewriterCompute(NodeCompute):
    """
    Compute node for context rewriting.

    Pure computation:
    - No I/O operations
    - Deterministic (same input → same output)
    - Cacheable results
    """

    def __init__(self, container: ModelONEXContainer) -> None:
        """Initialize with dependency injection."""
        super().__init__(container)

        # Configuration
        self.token_limit = 180000  # Leave 20K buffer for response
        self.recent_message_count = 20

        # Tokenizer (for accurate token counting)
        self.encoding = tiktoken.get_encoding("cl100k_base")

    async def process(
        self,
        input_data: ModelComputeInput,
    ) -> ModelComputeOutput:
        """
        Execute context rewriting.

        Flow:
        1. Validate input
        2. Prune messages (recent + relevant + tool-heavy)
        3. Format intelligence manifest
        4. Inject manifest into system prompt
        5. Ensure token limit (<180K)
        6. Return rewritten context
        """
        # Extract inputs
        messages = input_data.data.get("messages", [])
        system_prompt = input_data.data.get("system_prompt", "")
        intelligence = input_data.data.get("intelligence", {})
        intent = input_data.data.get("intent", {})

        # Prune messages
        pruned_messages = await self._prune_messages(messages, intent)

        # Format intelligence manifest
        manifest = self._build_intelligence_manifest(intelligence, intent)

        # Inject manifest into system prompt
        enhanced_system = f"{system_prompt}\n\n{manifest}"

        # Ensure token limit
        final_messages, final_system = self._ensure_token_limit(
            pruned_messages,
            enhanced_system
        )

        # Return results
        return ModelComputeOutput(
            result={
                "messages": final_messages,
                "system": final_system,
            },
            cache_hit=False,
            processing_time_ms=0,  # Set by base class
        )

    async def _prune_messages(
        self,
        messages: list[dict],
        intent: dict,
    ) -> list[dict]:
        """Prune messages keeping recent + relevant + tool-heavy."""
        # Strategy:
        # 1. Keep recent messages (last 20)
        # 2. Keep tool-heavy messages (Read, Edit, Bash)
        # 3. Keep messages relevant to intent

        recent = messages[-self.recent_message_count:]
        tool_heavy = self._find_tool_heavy(messages[:-self.recent_message_count])
        relevant = self._find_relevant(messages[:-self.recent_message_count], intent)

        # Combine (with deduplication)
        kept_messages = self._deduplicate(recent + tool_heavy + relevant)

        return kept_messages

    def _find_tool_heavy(self, messages: list[dict]) -> list[dict]:
        """Find messages with tool usage."""
        tool_messages = []
        for msg in messages:
            content = str(msg.get("content", ""))
            if any(tool in content for tool in ["Read", "Edit", "Write", "Bash"]):
                tool_messages.append(msg)
        return tool_messages

    def _find_relevant(self, messages: list[dict], intent: dict) -> list[dict]:
        """Find messages relevant to current intent."""
        relevant = []
        entities = intent.get("entities", [])
        files = intent.get("files", [])
        operations = intent.get("operations", [])

        for msg in messages:
            content = str(msg.get("content", "")).lower()

            # Check for entity overlap
            if any(entity.lower() in content for entity in entities):
                relevant.append(msg)
                continue

            # Check for file references
            if any(file in content for file in files):
                relevant.append(msg)
                continue

            # Check for operation keywords
            if any(op in content for op in operations):
                relevant.append(msg)

        return relevant

    def _deduplicate(self, messages: list[dict]) -> list[dict]:
        """Remove duplicate messages (preserve order)."""
        seen = set()
        unique = []
        for msg in messages:
            msg_id = id(msg)
            if msg_id not in seen:
                seen.add(msg_id)
                unique.append(msg)
        return unique

    def _build_intelligence_manifest(
        self,
        intelligence: dict,
        intent: dict,
    ) -> str:
        """Build intelligence manifest (same format as agent manifests)."""
        parts = []

        # Header
        parts.append("""
======================================================================
INTELLIGENCE CONTEXT (Dynamic)
======================================================================
""")

        # Intent Summary
        parts.append(f"""
## DETECTED INTENT
- Task Type: {intent.get('task_type', 'unknown')}
- Entities: {', '.join(intent.get('entities', []))}
- Operations: {', '.join(intent.get('operations', []))}
- Files: {', '.join(intent.get('files', []))}
- Confidence: {intent.get('confidence', 0.0):.2%}
""")

        # Execution Patterns (from Qdrant)
        execution_patterns = intelligence.get("execution_patterns", [])
        if execution_patterns:
            parts.append(f"""
## RELEVANT EXECUTION PATTERNS ({len(execution_patterns)} found)
""")
            for pattern in execution_patterns[:10]:  # Top 10
                parts.append(f"""
- **{pattern['name']}** ({pattern['confidence']:.0%} match)
  File: {pattern['file_path']}
  Node Types: {', '.join(pattern['node_types'])}
  Use Cases: {', '.join(pattern['use_cases'])}
""")

        # Code Examples (from Qdrant)
        code_patterns = intelligence.get("code_patterns", [])
        if code_patterns:
            parts.append(f"""
## REAL CODE EXAMPLES ({len(code_patterns)} found)
""")
            for code in code_patterns[:5]:  # Top 5
                parts.append(f"""
- **{code['description']}**
  Location: {code['file_path']}:{code['line_number']}
  ```python
  {code['code_snippet'][:200]}...
  ```
""")

        # Debug Intelligence (from PostgreSQL)
        debug_intel = intelligence.get("debug_intelligence", {})
        successes = debug_intel.get("successes", [])
        failures = debug_intel.get("failures", [])

        if successes or failures:
            parts.append(f"""
## DEBUG INTELLIGENCE (Similar Workflows)
Total Similar: {len(successes)} successes, {len(failures)} failures
""")

            if successes:
                parts.append("""
✅ **SUCCESSFUL APPROACHES** (what worked):
""")
                for success in successes[:5]:
                    parts.append(f"  - {success['approach']} (quality: {success['quality_score']:.2%})")

            if failures:
                parts.append("""
❌ **FAILED APPROACHES** (avoid these):
""")
                for failure in failures[:3]:
                    parts.append(f"  - {failure['approach']} (reason: {failure['failure_reason']})")

        # Footer
        parts.append("""
======================================================================
""")

        return "\n".join(parts)

    def _ensure_token_limit(
        self,
        messages: list[dict],
        system_prompt: str,
    ) -> tuple[list[dict], str]:
        """Ensure total tokens don't exceed limit."""
        # Estimate tokens
        message_tokens = sum(
            len(self.encoding.encode(str(m.get("content", ""))))
            for m in messages
        )
        system_tokens = len(self.encoding.encode(system_prompt))
        total_tokens = message_tokens + system_tokens

        if total_tokens <= self.token_limit:
            return messages, system_prompt

        # Over limit - prune messages more aggressively
        if message_tokens > self.token_limit * 0.7:  # Messages taking >70%
            messages = messages[-(self.token_limit // 200):]  # Keep fewer messages

        # Recalculate
        message_tokens = sum(
            len(self.encoding.encode(str(m.get("content", ""))))
            for m in messages
        )
        total_tokens = message_tokens + len(self.encoding.encode(system_prompt))

        if total_tokens <= self.token_limit:
            return messages, system_prompt

        # Still over - truncate manifest
        allowed_system_tokens = self.token_limit - message_tokens
        max_system_chars = allowed_system_tokens * 4

        if len(system_prompt) > max_system_chars:
            system_prompt = system_prompt[:max_system_chars] + "\n\n[Truncated due to token limit]"

        return messages, system_prompt
```

#### Kafka Topics

**Input** (from Orchestrator):
- `proxy.context.rewrite.requested.v1`

**Output** (to Orchestrator):
- `proxy.context.rewrite.completed.v1`
- `proxy.context.rewrite.failed.v1`

**Event Envelope**:

```python
class ContextRewriteRequest(BaseModel):
    """Request payload for context rewriting."""

    messages: list[dict]  # Original message array
    system_prompt: str  # Original system prompt
    intelligence: dict  # Intelligence data from query effect
    intent: dict  # Extracted intent
    correlation_id: str

class ContextRewriteResponse(BaseModel):
    """Response payload for context rewriting."""

    messages: list[dict]  # Rewritten message array
    system: str  # Enhanced system prompt with manifest
    messages_before: int
    messages_after: int
    tokens_before: int
    tokens_after: int
    processing_time_ms: int
    correlation_id: str
```

---

### 4. NodeAnthropicForwarderEffect (External I/O to Anthropic API)

**Purpose**: Forward rewritten request to Anthropic API with OAuth passthrough

**Type**: ONEX Effect Node

**Base Class**: `omnibase_core.nodes.NodeEffect`

**Characteristics**:
- **External I/O** - HTTPS request to Anthropic API
- **OAuth Passthrough** - No token modification
- **Response Capture** - Store for learning

#### Key Responsibilities

1. **Forward Request**
   - Build HTTPS request to Anthropic API
   - Pass OAuth token unchanged
   - Include rewritten messages + system prompt

2. **Capture Response**
   - Receive response from Anthropic
   - Extract response data
   - Capture for learning (async, non-blocking)

3. **Return Response**
   - Return response to Orchestrator
   - Include timing metrics

#### Method Signatures

```python
from omnibase_core.nodes.node_effect import NodeEffect
from omnibase_core.models.container import ModelONEXContainer
from omnibase_core.models.model_effect_input import ModelEffectInput
import httpx

class NodeAnthropicForwarderEffect(NodeEffect):
    """
    Effect node for forwarding requests to Anthropic API.

    External I/O:
    - HTTPS POST to Anthropic API
    - OAuth token passthrough
    - Response capture
    """

    def __init__(self, container: ModelONEXContainer) -> None:
        """Initialize with dependency injection."""
        super().__init__(container)

        # Configuration
        self.anthropic_base_url = "https://api.anthropic.com"
        self.default_timeout_seconds = 300  # 5 minutes

    async def execute_effect(
        self,
        contract: ModelContractEffect,
    ) -> ModelEffectOutput:
        """
        Execute Anthropic API forwarding.

        Flow:
        1. Extract rewritten request + OAuth token
        2. Build HTTPS request
        3. Forward to Anthropic API
        4. Capture response
        5. Return response
        """
        # Extract payload
        rewritten_request = contract.input_state.get("rewritten_request", {})
        oauth_token = contract.input_state.get("oauth_token", "")
        correlation_id = UUID(contract.correlation_id)

        # Build headers
        headers = {
            "Authorization": oauth_token,  # Pass through unchanged
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }

        # Forward to Anthropic
        async with httpx.AsyncClient(timeout=self.default_timeout_seconds) as client:
            response = await client.post(
                f"{self.anthropic_base_url}/v1/messages",
                json=rewritten_request,
                headers=headers,
            )

        # Check response status
        if response.status_code != 200:
            raise ModelOnexError(
                message=f"Anthropic API error: {response.status_code}",
                error_code=EnumCoreErrorCode.EXTERNAL_SERVICE_ERROR,
                correlation_id=correlation_id,
                context={"status_code": response.status_code, "body": response.text},
            )

        # Parse response
        response_data = response.json()

        # Capture response (async, non-blocking)
        asyncio.create_task(
            self._capture_response(response_data, correlation_id)
        )

        # Return response
        return ModelEffectOutput(
            result=response_data,
            success=True,
            correlation_id=correlation_id,
        )

    async def _capture_response(
        self,
        response_data: dict,
        correlation_id: UUID,
    ) -> None:
        """Capture response for learning (async, non-blocking)."""
        try:
            # Log to PostgreSQL
            await self._log_to_postgres(response_data, correlation_id)

            # Publish to Kafka
            await self._publish_to_kafka(response_data, correlation_id)

            # Update memory client
            await self._update_memory(response_data, correlation_id)

        except Exception as e:
            logger.warning(f"Failed to capture response: {e}")
            # Non-blocking - don't fail request
```

#### Kafka Topics

**Input** (from Orchestrator):
- `proxy.anthropic.forward.requested.v1`

**Output** (to Orchestrator):
- `proxy.anthropic.forward.completed.v1`
- `proxy.anthropic.forward.failed.v1`

**Event Envelope**:

```python
class AnthropicForwardRequest(BaseModel):
    """Request payload for Anthropic forwarding."""

    rewritten_request: dict  # Rewritten messages + system prompt
    oauth_token: str  # OAuth token (passthrough)
    correlation_id: str

class AnthropicForwardResponse(BaseModel):
    """Response payload for Anthropic forwarding."""

    response_data: dict  # Anthropic API response
    status_code: int
    forward_time_ms: int
    correlation_id: str
```

---

## FastAPI Entry Point

### Purpose

Provide HTTP endpoint for Claude Code compatibility while publishing events to Kafka for internal processing.

### Implementation

```python
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse
from uuid import uuid4
import json

app = FastAPI(title="Intelligent Context Proxy")

# Kafka producer (initialized on startup)
kafka_producer = None

@app.on_event("startup")
async def startup_event():
    """Initialize Kafka producer."""
    global kafka_producer
    kafka_producer = AIOKafkaProducer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        value_serializer=lambda v: json.dumps(v).encode('utf-8'),
    )
    await kafka_producer.start()

@app.on_event("shutdown")
async def shutdown_event():
    """Close Kafka producer."""
    if kafka_producer:
        await kafka_producer.stop()

@app.post("/v1/messages")
async def proxy_messages(request: Request) -> Response:
    """
    Proxy endpoint for Claude Code requests.

    Flow:
    1. Receive HTTP request from Claude Code
    2. Extract OAuth token
    3. Publish event to Kafka (proxy.context.orchestration.requested.v1)
    4. Wait for response event (proxy.context.orchestration.completed.v1)
    5. Return response to Claude Code
    """
    # Read request
    body = await request.body()
    request_data = json.loads(body) if body else {}

    # Extract OAuth token
    oauth_token = request.headers.get("authorization", "")

    # Generate correlation ID
    correlation_id = str(uuid4())

    # Create event envelope
    envelope = {
        "event_id": str(uuid4()),
        "event_type": "PROXY_ORCHESTRATION_REQUESTED",
        "correlation_id": correlation_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "service": "intelligent-context-proxy",
        "payload": {
            "request_data": request_data,
            "oauth_token": oauth_token,
            "correlation_id": correlation_id,
        },
        "version": "v1",
    }

    # Publish event to Kafka
    await kafka_producer.send_and_wait(
        topic="proxy.context.orchestration.requested.v1",
        value=envelope,
        key=correlation_id.encode("utf-8"),
    )

    # Wait for response (consumer stores in _pending_requests)
    try:
        result = await asyncio.wait_for(
            pending_requests[correlation_id],
            timeout=30.0,  # 30 second timeout
        )

        # Return Anthropic response to Claude Code
        return Response(
            content=json.dumps(result["response_data"]).encode("utf-8"),
            status_code=200,
            headers={"Content-Type": "application/json"},
        )

    except asyncio.TimeoutError:
        return Response(
            content=json.dumps({"error": "Proxy timeout"}).encode("utf-8"),
            status_code=504,
            headers={"Content-Type": "application/json"},
        )

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "services": {
            "kafka": "connected" if kafka_producer else "disconnected",
        }
    }
```

---

## Integration Strategy

### Integration with Existing Code

**CRITICAL: REUSE, DON'T REIMPLEMENT**

1. **ManifestInjector (3300 LOC)**:
   - Location: `agents/lib/manifest_injector.py`
   - Reuse: `generate_dynamic_manifest_async()` method
   - Already queries: Qdrant, PostgreSQL, Memgraph, Memory
   - Already uses: IntelligenceEventClient for Kafka communication
   - **NO CHANGES NEEDED** - Use as-is!

2. **IntelligenceEventClient**:
   - Location: `agents/lib/intelligence_event_client.py`
   - Reuse: Request-response pattern via Kafka
   - Topics: `dev.archon-intelligence.intelligence.code-analysis-*.v1`
   - **NO CHANGES NEEDED** - Already implements request-response!

3. **Memory Client**:
   - Location: `claude_hooks/lib/memory_client.py`
   - Reuse: `get_memory()`, `store_memory()`, `update_memory()`
   - Storage: Filesystem-backed (`~/.claude/memory/`)
   - **NO CHANGES NEEDED** - Use existing API!

4. **Intent Extractor**:
   - Location: `claude_hooks/lib/intent_extractor.py`
   - Reuse: `extract_intent()` function
   - Returns: Intent(task_type, entities, files, operations, confidence)
   - **NO CHANGES NEEDED** - Use existing function!

### Integration with Hook-Based Memory

**Shared Backend**:

Both hooks and proxy use the same `claude_hooks/lib/memory_client.py`:

```python
# Pre-prompt hook (5K tokens)
memory = get_memory_client()
workspace_state = await memory.get_memory("workspace_state", "workspace")

# Proxy (50K+ tokens, reads same backend)
memory = get_memory_client()
archived_context = await memory.get_memory("archived_context_*", "execution_history")
```

**Hook Enhancement Flow**:

```
1. User submits prompt
   ↓
2. Pre-prompt hook runs
   - Extracts intent (keyword-based)
   - Queries memory client (5K budget)
   - Injects into system prompt
   ↓
3. Claude Code sends request (now with 5K context)
   ↓
4. Proxy intercepts (FastAPI entry)
   ↓
5. Orchestrator coordinates workflow (via Kafka events)
   ↓
6. Intelligence Query Effect (reuses ManifestInjector)
   - Queries Qdrant, PostgreSQL, Memory
   - Returns 50K+ tokens
   ↓
7. Context Rewriter Compute (pure logic)
   - Prunes stale messages
   - Formats intelligence manifest
   - Injects into system prompt
   ↓
8. Anthropic Forwarder Effect (HTTP to Anthropic)
   - OAuth passthrough
   - Captures response
   ↓
9. Total context = Original + Hook (5K) + Proxy (50K) = 55K+ intelligence
```

**Graceful Degradation**:

```python
# Proxy checks if hook already ran
def detect_hook_context(system_prompt: str) -> bool:
    """Check if pre-prompt hook already injected context."""
    return "CONTEXT FROM MEMORY" in system_prompt

# If hook ran, proxy knows it already has 5K context
# Proxy adds 50K more (not 55K, to avoid duplication)
```

---

## Event Topics and Schemas

### Topic Naming Convention

**Two Topic Layers**:

1. **Intent Topics** (Coordination Layer)
   - **Pattern**: `intents.{action}.v1`
   - **Purpose**: Coordination commands (Reducer → Orchestrator)
   - **Examples**:
     - `intents.query-intelligence.v1`
     - `intents.rewrite-context.v1`
     - `intents.forward-anthropic.v1`
     - `intents.send-response.v1`

2. **Domain Event Topics** (Execution Layer)
   - **Pattern**: `context.{action}.{status}.v1`
   - **Purpose**: Actual work execution (Orchestrator → Nodes → Reducer)
   - **Examples**:
     - `context.request.received.v1`
     - `context.query.requested.v1`
     - `context.query.completed.v1`
     - `context.rewrite.requested.v1`
     - `context.rewrite.completed.v1`
     - `context.forward.requested.v1`
     - `context.forward.completed.v1`
     - `context.response.completed.v1`

**Why Two Layers?**:
- **Intent Layer**: High-level coordination (what should happen)
- **Domain Layer**: Actual execution (what is happening)
- **Separation**: Reducers emit intents, Orchestrators consume intents and emit domain events, Nodes consume/produce domain events

### Event Schemas

**Envelope Structure** (all events follow this pattern):

```python
{
  "event_id": str(uuid4()),           # Unique event ID
  "event_type": "EVENT_TYPE",         # Uppercase snake_case
  "correlation_id": "abc-123",        # Request correlation ID
  "timestamp": "2025-11-09T14:30:00Z", # ISO 8601
  "service": "intelligent-context-proxy", # Source service
  "payload": {...},                   # Event-specific payload
  "version": "v1"                     # Schema version
}
```

### Complete Topic Reference

**Intent Topics** (Coordination Layer):

| Topic | Intent Type | Payload | Producer | Consumer |
|-------|------------|---------|----------|----------|
| `intents.query-intelligence.v1` | `QUERY_INTELLIGENCE_INTENT` | `QueryIntelligenceIntent` | Reducer | Orchestrator |
| `intents.rewrite-context.v1` | `REWRITE_CONTEXT_INTENT` | `RewriteContextIntent` | Reducer | Orchestrator |
| `intents.forward-anthropic.v1` | `FORWARD_TO_ANTHROPIC_INTENT` | `ForwardToAnthropicIntent` | Reducer | Orchestrator |
| `intents.send-response.v1` | `SEND_RESPONSE_INTENT` | `SendResponseIntent` | Reducer | Orchestrator |

**Domain Event Topics** (Execution Layer):

| Topic | Event Type | Payload | Producer | Consumer |
|-------|-----------|---------|----------|----------|
| `context.request.received.v1` | `REQUEST_RECEIVED` | `RequestPayload` | FastAPI | Reducer |
| `context.query.requested.v1` | `QUERY_REQUESTED` | `IntelligenceQueryRequest` | Orchestrator | Intelligence Effect |
| `context.query.completed.v1` | `QUERY_COMPLETED` | `IntelligenceQueryResponse` | Intelligence Effect | Reducer |
| `context.rewrite.requested.v1` | `REWRITE_REQUESTED` | `ContextRewriteRequest` | Orchestrator | Rewriter Compute |
| `context.rewrite.completed.v1` | `REWRITE_COMPLETED` | `ContextRewriteResponse` | Rewriter Compute | Reducer |
| `context.forward.requested.v1` | `FORWARD_REQUESTED` | `AnthropicForwardRequest` | Orchestrator | Forwarder Effect |
| `context.forward.completed.v1` | `FORWARD_COMPLETED` | `AnthropicForwardResponse` | Forwarder Effect | Reducer |
| `context.response.completed.v1` | `RESPONSE_COMPLETED` | `ResponsePayload` | Orchestrator | FastAPI |
| `context.*.failed.v1` | `*_FAILED` | `ErrorPayload` | Any Node | Reducer/Orchestrator |

**External Topics** (Reused from Existing Infrastructure):
- `dev.archon-intelligence.intelligence.code-analysis-requested.v1` (used by ManifestInjector)
- `dev.archon-intelligence.intelligence.code-analysis-completed.v1` (consumed by ManifestInjector)
- `dev.archon-intelligence.intelligence.code-analysis-failed.v1` (consumed by ManifestInjector)

**Topic Flow Summary**:
```
FastAPI → context.request.received.v1 → Reducer
Reducer → intents.*.v1 (4 intent topics) → Orchestrator
Orchestrator → context.*.requested.v1 (3 domain topics) → Nodes
Nodes → context.*.completed.v1 (3 domain topics) → Reducer
Reducer → intents.send-response.v1 → Orchestrator
Orchestrator → context.response.completed.v1 → FastAPI
```

---

## Implementation Phases

### Phase 1: Foundation (3-5 days)

**Goal**: Working FastAPI entry point that publishes events to Kafka

**Tasks**:

**Day 1: FastAPI Entry Point**
- [ ] Create `services/intelligent_context_proxy/main.py` (FastAPI app)
- [ ] Add `/v1/messages` endpoint (receive requests from Claude Code)
- [ ] Add OAuth token passthrough
- [ ] Add Kafka producer initialization
- [ ] Test: Proxy receives requests and publishes events

**Day 2: Kafka Event Publishing**
- [ ] Create event envelope models (Pydantic)
- [ ] Implement event publishing to `proxy.context.orchestration.requested.v1`
- [ ] Add correlation ID tracking
- [ ] Test: Events published to Kafka successfully

**Day 3: Event Consumer Skeleton**
- [ ] Create NodeContextProxyOrchestrator skeleton
- [ ] Subscribe to `proxy.context.orchestration.requested.v1`
- [ ] Publish to `proxy.context.orchestration.completed.v1`
- [ ] Test: Round-trip event flow (FastAPI → Orchestrator → FastAPI)

**Day 4: Testing & Documentation**
- [ ] Unit tests for FastAPI endpoints
- [ ] Integration tests with Kafka
- [ ] Document proxy setup (Docker, environment vars)
- [ ] Create `services/intelligent_context_proxy/README.md`

**Day 5: Deployment Prep**
- [ ] Create `deployment/docker-compose.proxy.yml`
- [ ] Add health check endpoint (`/health`)
- [ ] Add metrics endpoint (`/metrics`)
- [ ] Test: Docker container runs successfully

**Deliverables**:
- ✅ FastAPI entry point with Kafka event publishing
- ✅ Orchestrator skeleton with round-trip event flow
- ✅ Docker deployment configuration
- ✅ Documentation and tests

**Success Criteria**:
- FastAPI receives requests from Claude Code
- Events published to Kafka successfully
- Orchestrator consumes and responds to events
- Round-trip latency <100ms

---

### Phase 2: Node Implementations (5-7 days)

**Goal**: Implement 4 ONEX nodes with event-driven communication

**Tasks**:

**Day 6: NodeIntelligenceQueryEffect**
- [ ] Create node class (extends `omnibase_core.nodes.NodeEffect`)
- [ ] Import ManifestInjector and IntelligenceEventClient
- [ ] Implement `execute_effect()` method
- [ ] Subscribe to `proxy.intelligence.query.requested.v1`
- [ ] Publish to `proxy.intelligence.query.completed.v1`
- [ ] Test: Intelligence queries work via Kafka

**Day 7: NodeContextRewriterCompute**
- [ ] Create node class (extends `omnibase_core.nodes.NodeCompute`)
- [ ] Implement message pruning logic
- [ ] Implement intelligence manifest formatting
- [ ] Subscribe to `proxy.context.rewrite.requested.v1`
- [ ] Publish to `proxy.context.rewrite.completed.v1`
- [ ] Test: Context rewriting works correctly

**Day 8: NodeAnthropicForwarderEffect**
- [ ] Create node class (extends `omnibase_core.nodes.NodeEffect`)
- [ ] Implement HTTPS forwarding to Anthropic
- [ ] Implement OAuth passthrough
- [ ] Subscribe to `proxy.anthropic.forward.requested.v1`
- [ ] Publish to `proxy.anthropic.forward.completed.v1`
- [ ] Test: Forwarding to Anthropic works

**Day 9: NodeContextProxyOrchestrator Integration**
- [ ] Implement workflow coordination (LlamaIndex or manual)
- [ ] Add dependency management (Step 2 depends on Step 1, etc.)
- [ ] Implement result aggregation
- [ ] Test: Full workflow end-to-end

**Day 10: Error Handling**
- [ ] Add timeout handling (per step and total)
- [ ] Add fallback for failed steps (return partial results)
- [ ] Add circuit breaker for repeated failures
- [ ] Test: Proxy works even if nodes unavailable

**Day 11-12: Testing & Optimization**
- [ ] Unit tests for all nodes
- [ ] Integration tests with full stack
- [ ] Load tests (100 requests/second)
- [ ] Optimize event processing latency

**Deliverables**:
- ✅ 4 ONEX nodes fully implemented
- ✅ Event-driven communication working
- ✅ Error handling and fallbacks
- ✅ All tests passing

**Success Criteria**:
- Intelligence queries complete in <2000ms
- Context rewriting completes in <100ms
- Anthropic forwarding completes in <500ms
- Total workflow latency <3000ms

---

### Phase 3: Integration & Testing (3-5 days)

**Goal**: Full integration with Claude Code, hooks, and intelligence systems

**Tasks**:

**Day 13: Claude Code Integration**
- [ ] Configure Claude Code to use proxy (`ANTHROPIC_BASE_URL=http://localhost:8080`)
- [ ] Test full conversation flow
- [ ] Verify OAuth passthrough works
- [ ] Verify responses return to Claude Code correctly

**Day 14: Hook Integration**
- [ ] Verify pre-prompt hook works with proxy
- [ ] Test: Hook adds 5K context, proxy adds 50K more
- [ ] Verify no duplication of context
- [ ] Test graceful degradation (proxy down, hooks still work)

**Day 15: Intelligence Integration**
- [ ] Verify ManifestInjector queries work
- [ ] Verify Qdrant patterns retrieved
- [ ] Verify PostgreSQL debug intelligence retrieved
- [ ] Verify Memory Client archived context retrieved

**Day 16: End-to-End Testing**
- [ ] Test: Full conversation with context rewriting
- [ ] Test: Long conversations (>200 messages) never compact
- [ ] Test: Token limits respected (<180K)
- [ ] Test: Intelligence manifest formatted correctly

**Day 17: Performance Testing**
- [ ] Load test (100 requests/second for 10 minutes)
- [ ] Measure latency (p50, p95, p99)
- [ ] Measure cache hit rate
- [ ] Optimize slow queries

**Deliverables**:
- ✅ Full integration with Claude Code
- ✅ Hook enhancement working
- ✅ Intelligence systems integrated
- ✅ Performance targets met

**Success Criteria**:
- Conversations never hit 200K token limit
- Intelligence manifest injected correctly
- Total latency <3s (p95)
- Cache hit rate >60%

---

### Phase 4: Learning & Optimization (3-5 days)

**Goal**: Proxy captures responses and learns from them

**Tasks**:

**Day 18: Response Capture**
- [ ] Implement response logging to PostgreSQL
- [ ] Add quality metrics extraction
- [ ] Make async/non-blocking
- [ ] Test: Logs written successfully

**Day 19: Event Publishing**
- [ ] Publish to Kafka (intelligence events)
- [ ] Event 1: context-enhanced
- [ ] Event 2: pattern-discovered
- [ ] Event 3: learning-event
- [ ] Test: Events published successfully

**Day 20: Pattern Learning**
- [ ] Update memory client with patterns
- [ ] Track success/failure patterns by task_type
- [ ] Store high-quality responses in Qdrant (async)
- [ ] Test: Patterns updated correctly

**Day 21: Performance Optimization**
- [ ] Add caching layer (Valkey)
- [ ] Cache intelligence queries (60 min TTL)
- [ ] Add request deduplication
- [ ] Test: Cache hit rate >60%

**Day 22: Monitoring**
- [ ] Add Prometheus metrics
- [ ] Track: request latency, query times, cache hit rate
- [ ] Add Grafana dashboard (optional)
- [ ] Test: Metrics exposed correctly

**Deliverables**:
- ✅ Response capture working
- ✅ Learning loop active
- ✅ Performance optimized
- ✅ Monitoring in place

**Success Criteria**:
- Responses logged successfully
- Patterns learned from executions
- Cache hit rate >60%
- Latency <3s per request

---

### Phase 5: Production Hardening (3-5 days)

**Goal**: Production-ready proxy with error handling, monitoring, and documentation

**Tasks**:

**Day 23: Error Handling**
- [ ] Add comprehensive try/catch blocks
- [ ] Add retry logic with exponential backoff
- [ ] Add circuit breakers (prevent cascading failures)
- [ ] Add rate limiting (prevent abuse)
- [ ] Test: Handles all error scenarios gracefully

**Day 24: Monitoring & Alerting**
- [ ] Set up Prometheus alerts (latency, errors, cache misses)
- [ ] Add logging (structured, JSON format)
- [ ] Add distributed tracing (OpenTelemetry)
- [ ] Test: Monitoring works in production

**Day 25: Load Testing**
- [ ] Create load test scenarios
- [ ] Test with 100 requests/second
- [ ] Test with 1000 concurrent connections
- [ ] Identify bottlenecks
- [ ] Optimize

**Day 26: Documentation**
- [ ] Complete `services/intelligent_context_proxy/README.md`
- [ ] Add architecture diagrams
- [ ] Add deployment guide
- [ ] Add troubleshooting guide
- [ ] Add API documentation

**Day 27: Security Review**
- [ ] Audit OAuth handling (ensure no token leakage)
- [ ] Audit data storage (ensure no sensitive data logged)
- [ ] Add input validation
- [ ] Add rate limiting
- [ ] Security scan (vulnerability check)

**Day 28: Final Testing & Deployment**
- [ ] Full end-to-end testing
- [ ] Staging deployment
- [ ] Production deployment (gradual rollout)
- [ ] Monitor for 24 hours
- [ ] Document lessons learned

**Deliverables**:
- ✅ Production-ready proxy
- ✅ Comprehensive documentation
- ✅ Monitoring & alerting
- ✅ Security audit complete

**Success Criteria**:
- All tests passing
- No errors in production (>99.9% uptime)
- Latency <3s (p95)
- Security review passed

---

## Performance Targets

### Latency Targets

| Operation | Target | Acceptable | Critical |
|-----------|--------|------------|----------|
| **FastAPI → Orchestrator** | <10ms | <50ms | >100ms |
| **Intelligence queries (Kafka)** | <2000ms | <3000ms | >5000ms |
| **Context rewriting** | <100ms | <200ms | >500ms |
| **Anthropic forwarding** | <500ms | <1000ms | >2000ms |
| **Response capture** | <50ms | <100ms | >200ms |
| **Total overhead** | <3000ms | <5000ms | >10000ms |

### Token Targets

| Metric | Target | Limit |
|--------|--------|-------|
| **Hook context** | 5K tokens | 10K tokens |
| **Intelligence manifest** | 50K tokens | 100K tokens |
| **Total context** | <180K tokens | 200K tokens (hard limit) |
| **Message array** | <100K tokens | 150K tokens |
| **System prompt** | <80K tokens | 100K tokens |

### Cache Targets

| Metric | Target | Good | Poor |
|--------|--------|------|------|
| **Cache hit rate** | >60% | >40% | <20% |
| **Cache latency** | <10ms | <50ms | >100ms |
| **Cache TTL** | 60 min | 30 min | 10 min |

### Quality Targets

| Metric | Target | Acceptable | Poor |
|--------|--------|------------|------|
| **Intent accuracy** | >90% | >80% | <70% |
| **Pattern relevance** | >85% | >70% | <60% |
| **Context relevance** | >90% | >80% | <70% |
| **Uptime** | >99.9% | >99% | <95% |

---

## Deployment Considerations

### Docker Compose

**docker-compose.proxy.yml**:

```yaml
version: '3.8'

services:
  # FastAPI Entry Point
  proxy-api:
    build:
      context: .
      dockerfile: deployment/Dockerfile.proxy-api
    ports:
      - "8080:8080"
    environment:
      - KAFKA_BOOTSTRAP_SERVERS=${KAFKA_BOOTSTRAP_SERVERS:-192.168.86.200:29092}
      - ANTHROPIC_API_URL=https://api.anthropic.com
    networks:
      - omninode-bridge-network
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    restart: unless-stopped

  # NodeContextRequestReducer (5th Node - NEW!)
  context-reducer:
    build:
      context: .
      dockerfile: deployment/Dockerfile.context-reducer
    environment:
      - KAFKA_BOOTSTRAP_SERVERS=${KAFKA_BOOTSTRAP_SERVERS:-192.168.86.200:29092}
    networks:
      - omninode-bridge-network
    depends_on:
      - proxy-api
    restart: unless-stopped

  # NodeContextProxyOrchestrator
  orchestrator:
    build:
      context: .
      dockerfile: deployment/Dockerfile.orchestrator
    environment:
      - KAFKA_BOOTSTRAP_SERVERS=${KAFKA_BOOTSTRAP_SERVERS:-192.168.86.200:29092}
    networks:
      - omninode-bridge-network
    depends_on:
      - context-reducer
    restart: unless-stopped

  # NodeIntelligenceQueryEffect
  intelligence-query:
    build:
      context: .
      dockerfile: deployment/Dockerfile.intelligence-query
    environment:
      - KAFKA_BOOTSTRAP_SERVERS=${KAFKA_BOOTSTRAP_SERVERS:-192.168.86.200:29092}
      - QDRANT_URL=${QDRANT_URL:-http://192.168.86.101:6333}
      - POSTGRES_HOST=${POSTGRES_HOST:-192.168.86.200}
      - POSTGRES_PORT=${POSTGRES_PORT:-5436}
    networks:
      - omninode-bridge-network
    depends_on:
      - orchestrator
    restart: unless-stopped

  # NodeContextRewriterCompute
  context-rewriter:
    build:
      context: .
      dockerfile: deployment/Dockerfile.context-rewriter
    environment:
      - KAFKA_BOOTSTRAP_SERVERS=${KAFKA_BOOTSTRAP_SERVERS:-192.168.86.200:29092}
    networks:
      - omninode-bridge-network
    depends_on:
      - orchestrator
    restart: unless-stopped

  # NodeAnthropicForwarderEffect
  anthropic-forwarder:
    build:
      context: .
      dockerfile: deployment/Dockerfile.anthropic-forwarder
    environment:
      - KAFKA_BOOTSTRAP_SERVERS=${KAFKA_BOOTSTRAP_SERVERS:-192.168.86.200:29092}
      - ANTHROPIC_API_URL=https://api.anthropic.com
    networks:
      - omninode-bridge-network
    depends_on:
      - orchestrator
    restart: unless-stopped

networks:
  omninode-bridge-network:
    external: true
    name: omninode-bridge-network
```

**Service Count**: 6 containers (1 FastAPI + 5 ONEX nodes)

### Environment Variables

**Required**:
- `KAFKA_BOOTSTRAP_SERVERS` - Kafka broker address (default: `192.168.86.200:29092`)
- `ANTHROPIC_API_URL` - Anthropic API base URL (default: `https://api.anthropic.com`)

**Optional**:
- `QDRANT_URL` - Qdrant endpoint (default: `http://192.168.86.101:6333`)
- `POSTGRES_HOST` - PostgreSQL host (default: `192.168.86.200`)
- `POSTGRES_PORT` - PostgreSQL port (default: `5436`)
- `MEMORY_STORAGE_PATH` - Memory storage directory (default: `~/.claude/memory/`)
- `INTELLIGENCE_QUERY_TIMEOUT_MS` - Query timeout (default: `2000`)
- `ENABLE_INTELLIGENCE_CACHE` - Enable caching (default: `true`)

---

## Success Metrics

### Primary Metrics

| Metric | Baseline (Hooks Only) | Target (Proxy + Hooks) | Measurement |
|--------|----------------------|------------------------|-------------|
| **Conversation length** | ~200 messages (before compact) | Infinite (no compact needed) | Average messages per session |
| **Intelligence injection** | 5K tokens | 55K+ tokens | Average manifest size |
| **Token savings** | N/A | 75-80% | vs full memory dump (200K) |
| **Cross-session continuity** | None (lost on compact) | 100% (memory persists) | Restoration success rate |
| **Pattern learning rate** | Manual only | Automatic (every conversation) | Patterns added per week |

### Secondary Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Latency overhead** | <3s (p95) | Request latency distribution |
| **Uptime** | >99.9% | Service availability |
| **Cache hit rate** | >60% | Cache hits / total queries |
| **Intent accuracy** | >90% | Manual review of sample |
| **Pattern relevance** | >85% | User feedback + quality score |

### Business Metrics

| Metric | Value | Impact |
|--------|-------|--------|
| **Time saved** | ~30 min/day | No manual context management |
| **Intelligence utilization** | 120+ patterns | Now accessible in conversations |
| **Developer productivity** | +20% | Less context switching, better continuity |
| **System learning** | Continuous | Every conversation improves intelligence |

---

## Conclusion

The **Intelligent Context Management Proxy** represents a revolutionary enhancement to OmniClaude's capabilities. By combining:

- ✅ **FastAPI HTTP entry point** (Claude Code compatibility)
- ✅ **Event-driven ONEX architecture** (Kafka/Redpanda communication)
- ✅ **5 ONEX nodes** (Reducer, Orchestrator, 2 Effects, 1 Compute)
- ✅ **FSM-driven pattern** (Reducer tracks state → Orchestrator reads FSM → coordinates workflow)
- ✅ **Pure FSM Reducer** (consumes events, updates state, emits persistence intents ONLY)
- ✅ **Independent Orchestrator** (reads FSM state, publishes domain events, drives workflow)
- ✅ **Reuses existing code** (ManifestInjector, IntelligenceEventClient, Memory Client)
- ✅ **Hook-based memory** (lightweight, always available)
- ✅ **Shared memory backend** (cross-session persistence)
- ✅ **Intelligence infrastructure** (120+ patterns, debug intel, code examples)

We create a system where:

- **Conversations never need compaction** (infinite length)
- **Intelligence is always accessible** (50K+ tokens injected)
- **Context is always relevant** (pruned intelligently)
- **System continuously learns** (every conversation improves patterns)
- **Graceful degradation** (hooks work if proxy down)
- **Scalable architecture** (event-driven, distributed)
- **Observable workflows** (correlation ID tracking across all events)
- **Pure separation of concerns** (Reducer = FSM state machine, Orchestrator = workflow engine, Nodes = execution)
- **Correct ONEX pattern** (Reducer does NOT emit workflow coordination intents, Orchestrator drives workflow independently)

**Total Development Time**: 20-30 days (5 phases)
**ROI**: High - Unlocks full intelligence infrastructure, enables infinite conversations, provides complete context control
**Architecture**: Event-driven ONEX with FSM Pattern (Reducer = FSM Tracker, Orchestrator = Workflow Engine, reads FSM state)

**Status**: Ready for implementation after plan approval

---

**Document Version**: 4.0 (FSM-Driven ONEX Architecture - Reducer/Orchestrator Corrected)
**Last Updated**: 2025-11-09
**Next Review**: After Phase 1 completion
**Architecture Pattern**: ONEX 5-node with FSM Pattern (Reducer tracks state via FSM, Orchestrator reads FSM and coordinates workflow)
