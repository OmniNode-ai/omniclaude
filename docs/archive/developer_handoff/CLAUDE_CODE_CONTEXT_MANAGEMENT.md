# Claude Code Context Management: Complete Guide

**Correlation ID**: ad12146a-b7d0-4a47-86bf-7ec298ce2c81
**Last Updated**: 2025-10-21
**Version**: 1.0

## Executive Summary

Claude Code manages a **200,000 token context window** (approximately 150,000 words) to maintain conversation continuity, file understanding, and task execution state. This guide explains how context works internally, how our framework leverages it, and best practices for efficient context utilization.

**Key Metrics**:
- **Context Window**: 200,000 tokens (~150,000 words)
- **Context Refresh**: Automatic across session restarts
- **File Context**: Loaded on-demand via Read tool
- **Agent Context Inheritance**: Manual propagation via correlation IDs
- **Token Estimation**: ~4 characters per token (rough estimate)

---

## Table of Contents

1. [Context Window Architecture](#context-window-architecture)
2. [Session Continuity](#session-continuity)
3. [File Context Management](#file-context-management)
4. [Agent Context Inheritance](#agent-context-inheritance)
5. [Context Optimization Strategies](#context-optimization-strategies)
6. [Best Practices](#best-practices)
7. [OmniClaude Framework Integration](#omniclaude-framework-integration)
8. [Troubleshooting](#troubleshooting)

---

## Context Window Architecture

### How Claude Code Manages 200K Tokens

Claude Code (powered by Claude 3.5 Sonnet) maintains a **200,000 token context window** that includes:

1. **System Instructions** (~5-10K tokens)
   - Tool definitions and schemas
   - Environment information (working directory, git status)
   - Global instructions (CLAUDE.md, CORE_PRINCIPLES.md)
   - Project-specific instructions (project CLAUDE.md)

2. **Conversation History** (~150-180K tokens available)
   - User messages and tool calls
   - Assistant responses and reasoning
   - Function results and outputs
   - Tool invocation history

3. **Active File Context** (variable, typically 10-50K tokens)
   - Files explicitly read via Read tool
   - Code snippets from tool outputs
   - Grep/search results

### Context Prioritization

Claude Code uses intelligent context management to keep the most relevant information:

**Priority Hierarchy** (from highest to lowest):
1. **Current turn**: User's latest message and immediate context
2. **Recent interactions**: Last 5-10 tool calls and responses
3. **Key files**: Files read multiple times or recently
4. **Conversation history**: Earlier messages (may be summarized)
5. **System context**: Static environment information

**Automatic Summarization**:
- When context approaches 200K limit, older messages may be summarized
- Key information is preserved (e.g., user requirements, decisions)
- Tool results are condensed while maintaining critical data
- File contents may be truncated to key sections

### Token Estimation

**Rule of Thumb**: ~4 characters per token

```python
def estimate_tokens(text: str) -> int:
    """Rough token estimation"""
    return len(text) // 4

# Examples:
# - 400 characters → ~100 tokens
# - 4,000 characters → ~1,000 tokens
# - 40,000 characters → ~10,000 tokens
# - 400,000 characters → ~100,000 tokens (50% of context window)
```

**Context Budget Planning**:
```
System Instructions:     ~10,000 tokens (5%)
Conversation History:   ~140,000 tokens (70%)
Active File Context:     ~50,000 tokens (25%)
------------------------
Total:                   200,000 tokens (100%)
```

---

## Session Continuity

### How Sessions Work

**Session Lifecycle**:
1. **Session Start**: Claude Code initializes with system instructions + environment
2. **Conversation**: Context accumulates with each user/assistant exchange
3. **Session End**: Context is **not persisted** by default
4. **Session Restart**: New session starts fresh (no automatic context carry-over)

### Session State Persistence

**Built-in Limitations**:
- ❌ Claude Code **does not automatically persist** conversation history between sessions
- ❌ No built-in "session resume" feature
- ❌ Context is lost when Claude Code restarts

**Workarounds**:
1. **Manual Context Capture** (our approach):
   - Use correlation IDs to track session state
   - Store critical context in files (e.g., `~/.claude/hooks/.state/`)
   - Reload context explicitly when needed

2. **Session Summary Files**:
   - Create markdown summaries of important conversations
   - Store in project directory (e.g., `docs/SESSION_NOTES.md`)
   - Reference via Read tool in new sessions

3. **Git-Based Context**:
   - Commit important decisions/context to git
   - Use commit messages as session memory
   - Review git log to reconstruct context

### OmniClaude Session Tracking

Our framework implements **correlation-based session tracking**:

**Correlation Manager** (`claude_hooks/lib/correlation_manager.py`):
```python
from claude_hooks.lib.correlation_manager import (
    set_correlation_id,
    get_correlation_context,
    get_correlation_id
)

# Store session context
set_correlation_id(
    correlation_id="ad12146a-b7d0-4a47-86bf-7ec298ce2c81",
    agent_name="agent-research",
    agent_domain="research",
    prompt_preview="Research context management..."
)

# Retrieve context (within 1 hour)
context = get_correlation_context()
# Returns:
# {
#     "correlation_id": "ad12146a-b7d0-4a47-86bf-7ec298ce2c81",
#     "agent_name": "agent-research",
#     "agent_domain": "research",
#     "prompt_preview": "Research context management...",
#     "prompt_count": 3,
#     "created_at": "2025-10-21T10:30:00Z",
#     "last_accessed": "2025-10-21T10:45:00Z"
# }
```

**State File Location**: `~/.claude/hooks/.state/correlation_id.json`
**TTL**: 1 hour (auto-cleanup after inactivity)

---

## File Context Management

### How Files Enter Context

Files are loaded into Claude Code's context through explicit tool usage:

**Primary Method: Read Tool**
```bash
# Reading a file loads it into context
Read file_path=/path/to/file.py

# File contents now in context for current conversation
# Token cost: file_size / 4 (approximate)
```

**Context Lifetime**:
- ✅ File content persists **for the entire conversation session**
- ❌ File content is **lost on session restart** (must re-read)
- ⚠️ Large files may be truncated if context limit approached

### Read Tool Best Practices

**1. Read Before Write/Edit (MANDATORY)**
```python
# ❌ WRONG: Edit without reading
Edit(file_path="file.py", old_string="...", new_string="...")

# ✅ CORRECT: Read first
Read(file_path="file.py")
Edit(file_path="file.py", old_string="...", new_string="...")
```

**2. Selective Reading for Large Files**
```python
# Option 1: Read with offset/limit for large files
Read(file_path="large_file.py", offset=100, limit=100)  # Lines 100-200

# Option 2: Use Grep to find relevant sections first
Grep(pattern="def important_function", path="large_file.py", output_mode="content", -n=True)
# Then read only the relevant file
```

**3. Parallel Reads for Independent Files**
```python
# ✅ GOOD: Read multiple independent files in parallel
Read(file_path="file1.py")
Read(file_path="file2.py")
Read(file_path="file3.py")
# All execute concurrently, faster context loading
```

### Context-Aware File Discovery

**Strategy**: Build understanding progressively

```bash
# Step 1: Discover project structure
Glob(pattern="**/*.py", path="/project/root")

# Step 2: Read high-level files first
Read(file_path="/project/root/README.md")
Read(file_path="/project/root/ARCHITECTURE.md")

# Step 3: Search for specific patterns
Grep(pattern="class.*Agent", path="/project/root", output_mode="files_with_matches")

# Step 4: Read relevant implementation files
Read(file_path="/project/root/agents/core_agent.py")
```

---

## Agent Context Inheritance

### Context Propagation Challenges

**Problem**: Claude Code does not have a built-in "Task" or "Agent spawn" tool
- ❌ No automatic context inheritance between "agent instances"
- ❌ Each conversation turn is isolated (no sub-agents)
- ❌ Context must be manually propagated

### OmniClaude Agent Context Pattern

Our framework implements **manual context inheritance** via:

1. **Correlation ID Propagation**
2. **Structured Context Packages**
3. **Context Optimization & Learning**

#### 1. Correlation ID Propagation

**Pattern**: Thread context through agent lifecycle

```python
from uuid import uuid4
from claude_hooks.lib.correlation_manager import set_correlation_id

# Parent agent establishes correlation context
correlation_id = uuid4()
set_correlation_id(
    correlation_id=str(correlation_id),
    agent_name="agent-workflow-coordinator",
    agent_domain="workflow_orchestration",
    prompt_preview="Complex multi-step task..."
)

# Child agents can retrieve this context
# (within same Claude Code session, or via state files)
context = get_correlation_context()
child_correlation_id = uuid4()  # New ID for child, but linked to parent
```

#### 2. Structured Context Packages

**Context Manager** (`agents/parallel_execution/context_manager.py`):

```python
from agents.parallel_execution.context_manager import ContextManager
from mcp_client import ArchonMCPClient

# Initialize context manager
mcp_client = ArchonMCPClient()
context_manager = ContextManager(mcp_client)

# Phase 0: Gather global context once
global_context = await context_manager.gather_global_context(
    user_prompt="Implement JWT authentication",
    workspace_path="/project/root",
    rag_queries=[
        "JWT authentication best practices",
        "ONEX authentication patterns"
    ],
    max_rag_results=5
)

# Returns:
# {
#     "rag:JWT authentication best practices": ContextItem(...),
#     "rag:ONEX authentication patterns": ContextItem(...),
#     "rag:domain-patterns": ContextItem(...),
#     "structure:/project/root": ContextItem(...),
#     "pattern:onex-architecture": ContextItem(...)
# }

# Phase 2: Filter context for specific agent
agent_context = context_manager.filter_context(
    context_requirements=[
        "rag:JWT authentication best practices",
        "pattern:onex-architecture",
        "file:auth.py"
    ],
    max_tokens=5000  # Budget for this agent
)

# Returns focused context dictionary (≤5000 tokens)
```

**Context Item Structure**:
```python
@dataclass
class ContextItem:
    context_type: str      # "file", "pattern", "rag", "structure"
    key: str              # Identifier (e.g., "file:auth.py")
    content: Any          # Actual content
    tokens_estimate: int  # Estimated token count
    metadata: Dict        # Additional metadata
```

#### 3. Context Optimization & Learning

**Context Optimizer** (`agents/lib/context_optimizer.py`):

```python
from agents.lib.context_optimizer import (
    predict_context_needs,
    optimize_context_for_task,
    learn_from_execution
)

# Predict context needs from user prompt
predicted_contexts = await predict_context_needs(
    user_prompt="Implement secure password reset flow"
)
# Returns: ["rag:security-patterns", "rag:auth-design", "pattern:onex-architecture"]

# Optimize context selection based on task type
optimized_contexts = await optimize_context_for_task(
    task_type="authentication_implementation",
    available_contexts=["rag:jwt", "rag:oauth", "rag:security", "pattern:onex"],
    max_contexts=3
)
# Returns top 3 contexts based on historical success rates

# Learn from execution outcomes
await learn_from_execution(
    task_type="authentication_implementation",
    context_keys=["rag:jwt", "pattern:onex-architecture"],
    success=True,
    duration_ms=1500
)
# Updates learning database for future optimization
```

**Learning Database** (PostgreSQL):
```sql
CREATE TABLE context_learning (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_type TEXT NOT NULL,
    context_keys TEXT[] NOT NULL,
    success_rate NUMERIC(5,4) NOT NULL,
    sample_count INT NOT NULL,
    avg_duration_ms NUMERIC(10,2) NOT NULL,
    last_updated TIMESTAMPTZ NOT NULL,
    UNIQUE(task_type, context_keys)
);
```

---

## Context Optimization Strategies

### 1. Token Budget Management

**Strategy**: Allocate context budget by priority

```python
# Define token budget allocation
CONTEXT_BUDGET = {
    "system_instructions": 10_000,   # Fixed, ~5%
    "conversation_history": 140_000, # Dynamic, ~70%
    "file_context": 50_000,          # Controlled, ~25%
}

# Track token usage
def track_context_usage():
    """Monitor context consumption"""
    current_usage = {
        "files_loaded": 0,
        "tokens_used": 0,
        "tokens_remaining": 200_000
    }

    # When reading a file
    file_tokens = estimate_tokens(file_content)
    if current_usage["tokens_used"] + file_tokens > CONTEXT_BUDGET["file_context"]:
        print(f"⚠️  File context budget exceeded: {file_tokens} tokens")
        # Consider: Read only critical sections, use Grep, or defer

    current_usage["tokens_used"] += file_tokens
    current_usage["tokens_remaining"] -= file_tokens
```

### 2. Selective Context Loading

**Pattern**: Just-in-time context gathering

```python
# ❌ WRONG: Load everything upfront
for file in all_project_files:
    Read(file_path=file)  # Massive context waste

# ✅ CORRECT: Load on-demand
# 1. Start with high-level understanding
Read(file_path="README.md")
Read(file_path="ARCHITECTURE.md")

# 2. Search for relevant areas
grep_results = Grep(
    pattern="authentication",
    path="/project",
    output_mode="files_with_matches"
)

# 3. Read only relevant files
for file in grep_results[:5]:  # Limit to top 5
    Read(file_path=file)
```

### 3. Context Refresh vs. Preservation

**When to Refresh Context**:
- ✅ File has been modified externally
- ✅ Working on a new, unrelated task
- ✅ Context is stale (>1 hour old)

**When to Preserve Context**:
- ✅ Iterating on same task
- ✅ File hasn't changed
- ✅ Context is still relevant

**Selective Refresh Pattern**:
```python
from agents.lib.context_optimizer import refresh_context_selectively

# Only refresh changed files
await refresh_context_selectively(
    context_keys=["file:auth.py", "file:config.py"],
    check_modifications=True  # Check git/filesystem timestamps
)
```

### 4. Context Compression Techniques

**Technique 1: Summarization**
```markdown
# Instead of including full file (5000 tokens)
Read(file_path="large_module.py")

# Summarize key points (500 tokens)
Summary of large_module.py:
- Classes: AuthHandler, TokenValidator, SessionManager
- Key methods: authenticate(), validate_token(), create_session()
- Dependencies: JWT, bcrypt, Redis
- ONEX compliance: Uses ModelContractEffect, OnexError
```

**Technique 2: Code Extraction**
```python
# Instead of reading entire file
Read(file_path="utils.py")  # 10,000 tokens

# Extract only relevant function via Grep
Grep(
    pattern="def hash_password",
    path="utils.py",
    output_mode="content",
    -A=10,  # 10 lines after
    -B=2    # 2 lines before
)
# Returns ~300 tokens instead of 10,000
```

**Technique 3: Reference-Based Context**
```markdown
# Instead of full content
Read(file_path="node_database_writer_effect.py")  # 3000 tokens

# Provide reference
File: node_database_writer_effect.py
- Type: ONEX Effect Node
- Purpose: PostgreSQL write operations
- Key method: async def execute_effect(contract: ModelContractEffect)
- Compliance: Full ONEX naming, OnexError handling
- Location: Available for detailed review if needed
# Only 150 tokens
```

---

## Best Practices

### 1. Context Lifecycle Management

**Pattern**: Initialize → Use → Cleanup

```python
async def task_with_context_lifecycle(correlation_id: str):
    """Example of proper context lifecycle"""

    # 1. INITIALIZE: Establish context
    from agents.lib.log_context import async_log_context

    async with async_log_context(
        correlation_id=correlation_id,
        component="agent-researcher"
    ):
        # 2. GATHER: Load necessary context
        context_manager = ContextManager()
        global_context = await context_manager.gather_global_context(
            user_prompt="Research task...",
            rag_queries=["research patterns"],
            max_rag_results=5
        )

        # 3. FILTER: Extract only what's needed
        task_context = context_manager.filter_context(
            context_requirements=["rag:research patterns"],
            max_tokens=5000
        )

        # 4. USE: Execute with focused context
        result = await execute_research(task_context)

        # 5. LEARN: Capture execution outcome
        await learn_from_execution(
            task_type="research",
            context_keys=list(task_context.keys()),
            success=True,
            duration_ms=1500
        )

        # 6. CLEANUP: Close resources
        await context_manager.cleanup()

    return result
```

### 2. Correlation ID Guidelines

**Pattern**: Thread correlation IDs through execution

```python
from uuid import uuid4

# Generate correlation ID once per user request
correlation_id = uuid4()

# Propagate through all operations
set_correlation_id(str(correlation_id), agent_name="agent-workflow")

# Use in all tool calls, logs, database operations
logger.info("Task started", correlation_id=correlation_id)
await database.execute(query, correlation_id=correlation_id)

# Retrieve in downstream operations
context = get_correlation_context()
if context:
    logger.info(f"Linked to session: {context['created_at']}")
```

### 3. Multi-Agent Context Sharing

**Pattern**: Centralized context gathering + distributed filtering

```python
async def multi_agent_workflow(user_prompt: str):
    """Coordinate multiple agents with shared context"""

    # Step 1: Gather global context ONCE
    context_manager = ContextManager()
    global_context = await context_manager.gather_global_context(
        user_prompt=user_prompt,
        workspace_path="/project",
        rag_queries=["ONEX patterns", "API design"],
        max_rag_results=10
    )

    # Step 2: Create agent-specific context packages
    agents = [
        {
            "name": "agent-api-architect",
            "requirements": ["rag:API design", "pattern:onex-architecture"],
            "token_budget": 3000
        },
        {
            "name": "agent-code-generator",
            "requirements": ["pattern:onex-architecture", "file:base_node.py"],
            "token_budget": 5000
        }
    ]

    # Step 3: Filter context for each agent
    agent_contexts = {}
    for agent in agents:
        agent_contexts[agent["name"]] = context_manager.filter_context(
            context_requirements=agent["requirements"],
            max_tokens=agent["token_budget"]
        )

    # Step 4: Execute agents with focused context
    results = await asyncio.gather(*[
        execute_agent(agent["name"], agent_contexts[agent["name"]])
        for agent in agents
    ])

    # Step 5: Cleanup
    await context_manager.cleanup()

    return results
```

### 4. Context Validation

**Pattern**: Verify context integrity before execution

```python
async def validate_context_integrity(context: Dict[str, Any]) -> bool:
    """Ensure context is complete and valid"""

    checks = {
        "has_required_keys": all(
            key in context
            for key in ["rag:domain-patterns", "pattern:onex-architecture"]
        ),
        "token_budget_ok": sum(
            item.tokens_estimate
            for item in context.values()
        ) < 10_000,
        "context_fresh": all(
            item.metadata.get("timestamp", 0) > time.time() - 3600
            for item in context.values()
        )
    }

    if not all(checks.values()):
        logger.error("Context validation failed", checks=checks)
        return False

    logger.info("Context validation passed", checks=checks)
    return True
```

---

## OmniClaude Framework Integration

### Framework Context Features

Our framework provides production-ready context management:

**1. Correlation Management** (`claude_hooks/lib/correlation_manager.py`)
- Session state persistence (1-hour TTL)
- Correlation ID propagation
- Cross-hook context sharing

**2. Context Optimization** (`agents/lib/context_optimizer.py`)
- Predictive context gathering
- Historical learning (PostgreSQL-backed)
- Task-type specific optimization
- Performance analytics

**3. Context Managers** (`agents/parallel_execution/context_manager.py`)
- Global context gathering (Phase 0)
- Selective context filtering (Phase 2)
- Multi-agent context distribution
- Token budget management

**4. Logging Context** (`agents/lib/log_context.py`)
- Thread-safe context propagation
- Async context managers
- Decorator support for auto-propagation

### Integration Example

```python
#!/usr/bin/env python3
"""Complete OmniClaude context management example"""

from uuid import uuid4
from agents.lib.context_optimizer import predict_context_needs
from agents.parallel_execution.context_manager import ContextManager
from claude_hooks.lib.correlation_manager import set_correlation_id
from agents.lib.log_context import async_log_context

async def omniclaude_workflow(user_prompt: str):
    """Full framework integration example"""

    # 1. Establish correlation context
    correlation_id = uuid4()
    set_correlation_id(
        str(correlation_id),
        agent_name="agent-workflow-coordinator",
        prompt_preview=user_prompt[:100]
    )

    # 2. Set up logging context
    async with async_log_context(
        correlation_id=correlation_id,
        component="workflow-coordinator"
    ):
        # 3. Predict context needs (ML-based)
        predicted_contexts = await predict_context_needs(user_prompt)
        logger.info("Predicted context needs", contexts=predicted_contexts)

        # 4. Gather global context
        context_manager = ContextManager()
        global_context = await context_manager.gather_global_context(
            user_prompt=user_prompt,
            rag_queries=predicted_contexts,
            max_rag_results=5
        )

        # 5. Get context summary
        summary = context_manager.get_context_summary()
        logger.info("Context gathered", summary=summary)

        # 6. Filter for execution
        execution_context = context_manager.filter_context(
            context_requirements=predicted_contexts[:3],
            max_tokens=5000
        )

        # 7. Execute with context
        result = await execute_task(execution_context)

        # 8. Learn from outcome
        await learn_from_execution(
            task_type="workflow_coordination",
            context_keys=list(execution_context.keys()),
            success=True,
            duration_ms=1500
        )

        # 9. Cleanup
        await context_manager.cleanup()

    return result
```

---

## Troubleshooting

### Common Context Issues

#### Issue 1: Context Limit Exceeded

**Symptom**: Responses truncated, "context window full" errors

**Solution**:
```python
# Check context usage
def estimate_current_context():
    """Rough estimate of current context usage"""
    # Files read: ~30,000 tokens
    # Conversation: ~150,000 tokens
    # System: ~10,000 tokens
    # Total: ~190,000 tokens (95% capacity)

    return {
        "files": 30_000,
        "conversation": 150_000,
        "system": 10_000,
        "total": 190_000,
        "remaining": 10_000,
        "utilization": "95%"
    }

# If near limit:
# 1. Stop reading new files
# 2. Summarize key points
# 3. Focus on critical context only
# 4. Consider starting new conversation
```

#### Issue 2: Lost Context After Restart

**Symptom**: Claude Code doesn't remember previous conversation

**Solution**:
```bash
# Create session summary before ending
cat > docs/SESSION_$(date +%Y%m%d_%H%M%S).md << EOF
# Session Summary

## Correlation ID
$(uuidgen)

## Context
- Task: Implementing JWT authentication
- Files modified: auth.py, config.py, test_auth.py
- Key decisions:
  - Using bcrypt for password hashing
  - Redis for token storage
  - 15-minute token expiration

## Next Steps
- [ ] Implement token refresh endpoint
- [ ] Add rate limiting
- [ ] Write integration tests

## Relevant Files
- agents/auth/node_auth_handler_effect.py
- config/auth_config.yaml
- tests/test_auth_flow.py
EOF

# In new session, read this file first
Read file_path=docs/SESSION_20251021_103000.md
```

#### Issue 3: Inconsistent Agent Context

**Symptom**: Agents missing critical context from parent

**Solution**:
```python
# Use context manager for consistent distribution
context_manager = ContextManager()

# Gather once
global_context = await context_manager.gather_global_context(...)

# Distribute consistently to all agents
for agent in agents:
    agent_context = context_manager.filter_context(
        context_requirements=agent.requirements,
        max_tokens=agent.budget
    )
    await execute_agent(agent.name, agent_context)

# Ensures all agents get same base context, filtered appropriately
```

#### Issue 4: Slow Context Gathering

**Symptom**: Context gathering takes >30 seconds

**Solution**:
```python
# Use parallel RAG queries
rag_queries = [
    "ONEX patterns",
    "authentication best practices",
    "API design patterns"
]

# ❌ SLOW: Sequential (3 x 5s = 15s)
for query in rag_queries:
    result = await mcp_client.perform_rag_query(query)

# ✅ FAST: Parallel (max 5s)
results = await asyncio.gather(*[
    mcp_client.perform_rag_query(query)
    for query in rag_queries
])

# Use context optimizer's predictive gathering
predicted = await predict_context_needs(user_prompt)
# Returns only relevant contexts, reducing unnecessary queries
```

---

## Appendix: Context Management APIs

### Correlation Manager API

**File**: `claude_hooks/lib/correlation_manager.py`

```python
# Store correlation context
set_correlation_id(
    correlation_id: str,
    agent_name: Optional[str] = None,
    agent_domain: Optional[str] = None,
    prompt_preview: Optional[str] = None
)

# Retrieve context
get_correlation_context() -> Optional[Dict[str, Any]]

# Get just the ID
get_correlation_id() -> Optional[str]

# Clear context
clear_correlation_context()
```

### Context Manager API

**File**: `agents/parallel_execution/context_manager.py`

```python
# Initialize
context_manager = ContextManager(mcp_client: Optional[ArchonMCPClient])

# Gather global context
await context_manager.gather_global_context(
    user_prompt: str,
    workspace_path: Optional[str] = None,
    rag_queries: Optional[List[str]] = None,
    max_rag_results: int = 5
) -> Dict[str, ContextItem]

# Filter context
context_manager.filter_context(
    context_requirements: List[str],
    max_tokens: int = 5000
) -> Dict[str, Any]

# Add custom context
context_manager.add_file_context(file_path: str, content: str) -> str
context_manager.add_pattern_context(pattern_name: str, pattern_data: Dict) -> str

# Get summary
context_manager.get_context_summary() -> Dict[str, Any]

# Cleanup
await context_manager.cleanup()
```

### Context Optimizer API

**File**: `agents/lib/context_optimizer.py`

```python
# Predict context needs
await predict_context_needs(user_prompt: str) -> List[str]

# Optimize context selection
await optimize_context_for_task(
    task_type: str,
    available_contexts: List[str],
    max_contexts: int = 5
) -> List[str]

# Learn from execution
await learn_from_execution(
    task_type: str,
    context_keys: List[str],
    success: bool,
    duration_ms: float,
    metadata: Optional[Dict] = None
)

# Get effectiveness analysis
await get_context_effectiveness_analysis(days: int = 30) -> Dict[str, Any]

# Get learning stats
get_learning_stats() -> Dict[str, Any]
```

### Log Context API

**File**: `agents/lib/log_context.py`

```python
# Context manager (sync)
with log_context(
    correlation_id: Optional[UUID|str] = None,
    session_id: Optional[UUID|str] = None,
    component: Optional[str] = None
):
    # All logs automatically tagged
    logger.info("Message")

# Context manager (async)
async with async_log_context(
    correlation_id: Optional[UUID|str] = None,
    session_id: Optional[UUID|str] = None,
    component: Optional[str] = None
):
    # All logs automatically tagged
    await async_operation()

# Decorator
@with_log_context(component="agent-researcher")
async def research_task(correlation_id: UUID):
    # Logs automatically tagged with correlation_id and component
    logger.info("Research started")
```

---

## Summary

**Key Takeaways**:

1. **200K Token Window**: Claude Code provides substantial context capacity
2. **No Auto-Persistence**: Context is lost between sessions; manual persistence required
3. **Read Tool**: Primary method for loading file context
4. **Correlation IDs**: Our framework's solution for context threading
5. **Context Optimization**: ML-based prediction and learning for efficiency
6. **Token Budgets**: Critical for multi-agent scenarios to prevent overflow
7. **Parallel Gathering**: Always use for independent RAG queries
8. **Selective Loading**: Just-in-time context gathering over eager loading

**Best Practices Checklist**:
- ✅ Always Read before Write/Edit
- ✅ Use correlation IDs for context threading
- ✅ Implement token budget tracking
- ✅ Gather context in parallel when possible
- ✅ Filter context per agent requirements
- ✅ Learn from execution outcomes
- ✅ Validate context integrity before execution
- ✅ Create session summaries for continuity
- ✅ Monitor context utilization
- ✅ Cleanup resources after execution

---

**Document Version**: 1.0
**Last Updated**: 2025-10-21
**Maintained By**: OmniClaude Framework Team
**Related Documentation**:
- [Agent Framework README](../agents/README.md)
- [Correlation Manager Source](../claude_hooks/lib/correlation_manager.py)
- [Context Manager Source](../agents/parallel_execution/context_manager.py)
- [Context Optimizer Source](../agents/lib/context_optimizer.py)
