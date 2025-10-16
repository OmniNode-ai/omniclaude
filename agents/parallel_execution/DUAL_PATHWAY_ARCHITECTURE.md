# Dual-Pathway Agent Invocation Architecture

## Overview

This document defines the architecture for three distinct agent invocation pathways in the OmniClaude hook system:

1. **Coordinator Dispatch**: Spawn agent-workflow-coordinator for complex multi-agent orchestration
2. **Direct Hook Agent**: Execute single agent directly from hook context (lightweight)
3. **Parallel Direct Agents**: Execute multiple agents in parallel from hook context

## Design Principles

- **Explicit over implicit**: Clear syntax distinguishes invocation pathways
- **Backward compatible**: Existing agent detection continues to work
- **Performance optimized**: Direct hook agents bypass orchestration overhead
- **Context preserved**: All pathways maintain correlation ID tracking
- **Database tracked**: All invocations logged to agent_routing_decisions

## Pathway 1: Coordinator Dispatch

### When to Use
- Complex multi-step workflows requiring agent transformations
- Need enhanced router for intelligent agent selection
- Tasks requiring quality gates and performance validation
- Unknown agent requirements (let coordinator decide)

### Trigger Patterns
```
coordinate: <task description>
@workflow-coordinator <task description>
orchestrate: <task description>
```

### Examples
```
coordinate: Implement user authentication with JWT tokens
@workflow-coordinator Analyze and optimize database schema
orchestrate: Refactor payment processing module
```

### Behavior
1. Hook detects coordinator trigger
2. Spawns agent-workflow-coordinator via Task tool
3. Coordinator uses enhanced router for agent selection
4. Full orchestration with delegation, transformations, quality gates
5. Database logs routing decisions and transformations

### Implementation Flow
```
UserPromptSubmit Hook
  ↓
Detect "coordinate:" pattern
  ↓
Inject coordinator context
  ↓
Claude uses Task tool to spawn agent-workflow-coordinator
  ↓
ParallelCoordinator executes with full framework
  ↓
Database: agent_routing_decisions + agent_transformation_events
```

## Pathway 2: Direct Hook Agent (Single)

### When to Use
- Simple, focused tasks for a known agent
- Performance-sensitive operations (<100ms overhead requirement)
- Agent-specific analysis or validation
- Quick agent identity assumption by Claude

### Trigger Patterns
```
@agent-<name> <task description>
use agent-<name> to <task>
invoke agent-<name> for <task>
```

### Examples
```
@agent-testing Analyze test coverage for hooks module
use agent-commit to review staged changes before commit
invoke agent-debug-intelligence for error analysis
```

### Behavior
1. Hook detects agent name
2. Loads agent YAML config
3. Injects complete agent identity into Claude's context
4. Claude assumes agent identity (polymorphic behavior)
5. Lightweight execution, no orchestration overhead
6. Database logs detection in hook_events

### Implementation Flow
```
UserPromptSubmit Hook
  ↓
Detect "@agent-<name>" pattern
  ↓
Load agent YAML config from ~/.claude/agents/configs/
  ↓
Inject full YAML into Claude's prompt context
  ↓
Claude reads identity and adapts behavior
  ↓
Database: hook_events with agent detection
```

## Pathway 3: Parallel Direct Agents

### When to Use
- Multiple independent tasks that can run concurrently
- Distributed analysis across different agent specializations
- Task decomposition with parallel execution
- Performance optimization through concurrency

### Trigger Patterns
```
parallel: @agent-1, @agent-2, @agent-3 <task description>
concurrently: use agent-testing and agent-commit for <task>
@parallel @agent-devops, @agent-security, @agent-performance <task>
```

### Examples
```
parallel: @agent-testing, @agent-commit, @agent-security Review PR #123
concurrently: use agent-performance and agent-debug-intelligence to analyze API latency
@parallel @agent-python-expert, @agent-fastapi-expert, @agent-testing Implement user registration endpoint
```

### Behavior
1. Hook detects parallel trigger + multiple agent names
2. Loads all agent YAML configs
3. Invokes agent_invoker.py with parallel mode
4. Uses ParallelCoordinator for execution coordination
5. Each agent maintains independent context
6. Results aggregated and returned
7. Database logs all routing decisions

### Implementation Flow
```
UserPromptSubmit Hook
  ↓
Detect "parallel:" pattern + agent list
  ↓
Parse agent names (@agent-testing, @agent-commit, ...)
  ↓
Invoke agent_invoker.py --mode parallel --agents "agent-testing,agent-commit,..."
  ↓
AgentInvoker creates AgentTask for each agent
  ↓
ParallelCoordinator.execute_parallel([task1, task2, task3])
  ↓
Each agent executes with YAML context injection
  ↓
Results aggregated and logged
  ↓
Database: agent_routing_decisions (one per agent)
```

## Trigger Detection Priority

```python
def detect_invocation_pathway(prompt: str) -> Dict[str, Any]:
    """
    Detect which invocation pathway to use.

    Returns:
        {
            "pathway": "coordinator" | "direct_single" | "direct_parallel",
            "agents": List[str],  # Agent names to invoke
            "task": str  # Cleaned task description
        }
    """
    # Priority 1: Explicit coordinator request
    if re.search(r'\b(coordinate|orchestrate):', prompt, re.IGNORECASE):
        return {
            "pathway": "coordinator",
            "agents": ["agent-workflow-coordinator"],
            "task": extract_task_after_trigger(prompt)
        }

    if re.search(r'@workflow-coordinator\b', prompt):
        return {
            "pathway": "coordinator",
            "agents": ["agent-workflow-coordinator"],
            "task": prompt
        }

    # Priority 2: Parallel direct agents
    if re.search(r'\b(parallel|concurrently):', prompt, re.IGNORECASE):
        agents = extract_multiple_agents(prompt)
        if len(agents) > 1:
            return {
                "pathway": "direct_parallel",
                "agents": agents,
                "task": extract_task_after_agents(prompt)
            }

    if re.search(r'@parallel\b', prompt):
        agents = extract_multiple_agents(prompt)
        if len(agents) > 1:
            return {
                "pathway": "direct_parallel",
                "agents": agents,
                "task": extract_task_after_agents(prompt)
            }

    # Priority 3: Single direct agent
    agent_match = re.search(r'@(agent-[\w-]+)', prompt)
    if agent_match:
        return {
            "pathway": "direct_single",
            "agents": [agent_match.group(1)],
            "task": prompt
        }

    # Priority 4: Trigger-based detection (fallback)
    agent_name = detect_agent_by_triggers(prompt)
    if agent_name:
        return {
            "pathway": "direct_single",
            "agents": [agent_name],
            "task": prompt
        }

    # No agent invocation needed
    return {
        "pathway": None,
        "agents": [],
        "task": prompt
    }
```

## Agent Configuration Extensions

Agent YAML configs can specify invocation preferences:

```yaml
# ~/.claude/agents/configs/agent-testing.yaml
agent_identity:
  name: "agent-testing"
  invocation:
    preferred_pathway: "direct_single"  # or "coordinator" or "direct_parallel"
    parallel_compatible: true  # Can this agent run in parallel with others?
    max_parallel_instances: 3  # How many concurrent instances allowed?
    coordination_required: false  # Does this agent need coordinator oversight?
```

## Database Schema Updates

### agent_routing_decisions (updated)
```sql
ALTER TABLE agent_routing_decisions
ADD COLUMN invocation_pathway text,  -- 'coordinator' | 'direct_single' | 'direct_parallel'
ADD COLUMN parallel_execution_id uuid,  -- Groups parallel executions
ADD COLUMN parallel_agent_count integer,  -- How many agents in parallel group
ADD COLUMN pathway_overhead_ms integer;  -- Overhead specific to pathway
```

### New table: parallel_executions
```sql
CREATE TABLE parallel_executions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    correlation_id uuid NOT NULL,
    agent_names text[] NOT NULL,
    task_description text NOT NULL,
    total_agents integer NOT NULL,
    completed_agents integer DEFAULT 0,
    failed_agents integer DEFAULT 0,
    execution_status text DEFAULT 'running',  -- 'running' | 'completed' | 'failed'
    start_time timestamp with time zone DEFAULT now(),
    end_time timestamp with time zone,
    total_duration_ms integer,
    results jsonb DEFAULT '{}',
    created_at timestamp with time zone DEFAULT now()
);

CREATE INDEX idx_parallel_executions_correlation ON parallel_executions(correlation_id);
CREATE INDEX idx_parallel_executions_status ON parallel_executions(execution_status);
```

## Performance Targets

### Pathway 1: Coordinator Dispatch
- **Detection overhead**: <10ms
- **Coordinator spawn**: <500ms
- **Total end-to-end**: <5000ms (complex workflows acceptable)
- **Database logging**: <50ms

### Pathway 2: Direct Hook Agent
- **Detection overhead**: <10ms
- **YAML loading**: <30ms
- **Context injection**: <20ms
- **Total overhead**: <100ms
- **Database logging**: <30ms

### Pathway 3: Parallel Direct Agents
- **Detection overhead**: <15ms
- **YAML loading (all agents)**: <50ms per agent
- **Coordination setup**: <200ms
- **Parallel execution**: Depends on slowest agent
- **Result aggregation**: <100ms
- **Total overhead**: <500ms + max(agent_execution_times)
- **Database logging**: <50ms per agent

## Implementation Files

### 1. agent_pathway_detector.py (NEW)
Location: `/Users/jonah/.claude/hooks/lib/agent_pathway_detector.py`

Purpose: Detect which invocation pathway to use

### 2. agent_invoker.py (UPDATED)
Location: `/Users/jonah/.claude/hooks/lib/agent_invoker.py`

Purpose: Execute agents via detected pathway

### 3. user-prompt-submit-enhanced.sh (UPDATED)
Location: `/Users/jonah/.claude/hooks/user-prompt-submit-enhanced.sh`

Purpose: Hook integration for pathway detection and invocation

### 4. parallel_direct_executor.py (NEW)
Location: `agents/parallel_execution/parallel_direct_executor.py`

Purpose: Lightweight parallel executor for direct hook agents (without full coordinator overhead)

## Migration Path

### Phase 1: Pathway Detection (Week 1)
- Implement agent_pathway_detector.py
- Add detection to UserPromptSubmit hook
- Test all trigger patterns
- Database logging of detections

### Phase 2: Direct Single Agent (Week 2)
- Implement direct_single pathway
- Context injection mechanism
- Integration tests
- Performance validation (<100ms overhead)

### Phase 3: Coordinator Dispatch (Week 3)
- Implement coordinator spawning
- Task tool invocation from hook
- Full orchestration integration
- Routing decision logging

### Phase 4: Parallel Direct Agents (Week 4)
- Implement parallel_direct_executor.py
- Parallel coordination without full overhead
- Result aggregation
- Performance optimization

### Phase 5: Production Validation (Week 5)
- End-to-end testing all pathways
- Performance benchmarking
- Database tracking validation
- Documentation and examples

## Examples

### Example 1: Coordinator Dispatch
```
User: coordinate: Implement user authentication system with JWT tokens, database migrations, and API endpoints

Hook Detection:
  pathway: "coordinator"
  agents: ["agent-workflow-coordinator"]

Flow:
  1. Hook injects coordinator context
  2. Claude uses Task tool: agent-workflow-coordinator
  3. Coordinator analyzes task
  4. Enhanced router selects: agent-api-architect
  5. Agent-api-architect delegates to: agent-fastapi-expert
  6. Agent-fastapi-expert delegates to: agent-database-migration
  7. All routing decisions logged to database
  8. Quality gates validate at each step
```

### Example 2: Direct Single Agent
```
User: @agent-testing Analyze test coverage for the hooks module and identify gaps

Hook Detection:
  pathway: "direct_single"
  agents: ["agent-testing"]

Flow:
  1. Hook loads agent-testing.yaml (323 lines)
  2. Full config injected into Claude's prompt
  3. Claude reads identity: "I am a Testing & Quality Assurance Specialist"
  4. Claude adapts behavior to testing specialist patterns
  5. Performs coverage analysis using testing methodology
  6. Returns results in testing-specific format
  7. Database logs detection in hook_events
```

### Example 3: Parallel Direct Agents
```
User: parallel: @agent-testing, @agent-security, @agent-performance Review PR #123 for production readiness

Hook Detection:
  pathway: "direct_parallel"
  agents: ["agent-testing", "agent-security", "agent-performance"]

Flow:
  1. Hook loads 3 YAML configs
  2. Creates 3 AgentTask objects
  3. Invokes ParallelCoordinator.execute_parallel()
  4. Agent-testing: Analyzes test coverage and quality
  5. Agent-security: Reviews for vulnerabilities and auth issues
  6. Agent-performance: Identifies optimization opportunities
  7. Results aggregated with cross-agent insights
  8. Database logs 3 routing decisions + 1 parallel_execution record
```

## Testing Strategy

### Unit Tests
- `test_pathway_detection()`: Test all trigger patterns
- `test_agent_config_loading()`: YAML loading for single/multiple agents
- `test_parallel_task_creation()`: AgentTask generation for parallel mode
- `test_coordinator_spawning()`: Coordinator invocation from hook

### Integration Tests
- `test_direct_single_end_to_end()`: Full flow for single agent
- `test_parallel_direct_end_to_end()`: Full flow for parallel agents
- `test_coordinator_dispatch_end_to_end()`: Full flow for coordinator
- `test_database_tracking_all_pathways()`: Validate all DB writes

### Performance Tests
- `test_direct_single_overhead()`: Must be <100ms
- `test_parallel_coordination_overhead()`: Must be <500ms
- `test_coordinator_spawn_time()`: Must be <500ms
- `test_yaml_loading_performance()`: Must be <30ms per agent

### Error Handling Tests
- `test_missing_agent_config()`: Graceful degradation
- `test_parallel_agent_failure()`: One agent fails, others succeed
- `test_coordinator_unavailable()`: Fallback to direct mode
- `test_database_connection_failure()`: Non-blocking logging failure

## Success Metrics

### Accuracy
- Pathway detection accuracy: >99%
- Agent selection accuracy (direct mode): 100% (explicit)
- Parallel coordination success rate: >95%

### Performance
- Direct single overhead: <100ms (target: 60ms avg)
- Parallel coordination overhead: <500ms (target: 300ms avg)
- Coordinator spawn time: <500ms (target: 400ms avg)
- Database logging latency: <50ms (target: 30ms avg)

### Reliability
- Zero blocking failures (all pathways degrade gracefully)
- Database tracking coverage: 100% of invocations
- Context preservation: 100% across all pathways
- Error recovery rate: 100% (no hung processes)

## Future Enhancements

### Phase 2 Features
- **Adaptive pathway selection**: System learns optimal pathway per task type
- **Smart parallel grouping**: Automatically group compatible agents
- **Coordinator optimization**: Cache routing decisions for similar tasks
- **Performance profiling**: Real-time pathway performance analysis

### Phase 3 Features
- **Multi-level coordination**: Parallel groups within coordinator workflows
- **Agent chaining**: Sequential agent execution in direct mode
- **Conditional agents**: Execute agents based on previous results
- **Resource-aware scheduling**: Optimize parallel execution based on system load

---

**Document Version**: 1.0
**Last Updated**: 2025-01-10
**Status**: Design Complete, Implementation Pending
