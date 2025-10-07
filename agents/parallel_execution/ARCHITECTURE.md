# Parallel Dispatcher Architecture

## Executive Summary

The Parallel Dispatcher system provides intelligent orchestration of parallel agent execution, combining a Claude Code agent orchestrator with a Python parallel execution backend. This architecture enables complex multi-agent workflows with automatic tracing, dependency management, and performance optimization.

## Design Principles

1. **Separation of Concerns**: Orchestration (Claude) vs Execution (Python)
2. **Visibility First**: Every phase visible to orchestrator
3. **Trace Everything**: Automatic tracing for all executions
4. **Modularity**: Clear interfaces between components
5. **Simplicity**: Minimal tool usage, clear workflows

## System Architecture

### High-Level Overview

```
┌────────────────────────────────────────────────────────────────┐
│                    User Interface Layer                        │
│  Natural Language Request → Claude Code Agent                  │
└────────────────────────────────────────────────────────────────┘
                              ↓
┌────────────────────────────────────────────────────────────────┐
│                  Orchestration Layer (Claude Agent)            │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────┐   │
│  │   Request   │→ │     Task     │→ │     Dispatch       │   │
│  │   Analysis  │  │   Planning   │  │   Execution        │   │
│  └─────────────┘  └──────────────┘  └────────────────────┘   │
│                              ↓                                  │
│                    [Task JSON Definition]                       │
└────────────────────────────────────────────────────────────────┘
                              ↓
┌────────────────────────────────────────────────────────────────┐
│                 Execution Layer (Python System)                │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────┐   │
│  │   dispatch_ │→ │   Parallel   │→ │     Result         │   │
│  │   runner.py │  │  Coordinator │  │   Aggregator       │   │
│  └─────────────┘  └──────────────┘  └────────────────────┘   │
│                              ↓                                  │
│                    [Agent Execution Pool]                       │
│              agent_coder  |  agent_debug_intelligence          │
└────────────────────────────────────────────────────────────────┘
                              ↓
┌────────────────────────────────────────────────────────────────┐
│                    Integration Layer (MCP)                     │
│  Archon MCP Server → RAG, Quality Gates, Tracing              │
└────────────────────────────────────────────────────────────────┘
                              ↓
┌────────────────────────────────────────────────────────────────┐
│                      Storage Layer                             │
│  Generated Code  |  Trace Files  |  Execution Logs             │
└────────────────────────────────────────────────────────────────┘
```

### Component Diagram

```
┌─────────────────────────────────────────────────────────────┐
│ agent-parallel-dispatcher (Claude Agent)                    │
│                                                             │
│  Responsibilities:                                          │
│  • Natural language request parsing                         │
│  • Task breakdown and planning                              │
│  • Agent routing (coder vs debug)                           │
│  • Dependency graph construction                            │
│  • Result synthesis and presentation                        │
│                                                             │
│  Tools: Write, Bash, Read, Glob                             │
│  Input: User natural language request                       │
│  Output: Synthesized results + trace references             │
└─────────────────────────────────────────────────────────────┘
                          ↓
                [Task JSON via stdin]
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ dispatch_runner.py (Python Entry Point)                     │
│                                                             │
│  Responsibilities:                                          │
│  • JSON input parsing and validation                        │
│  • Task schema validation                                   │
│  • Parallel execution orchestration                         │
│  • Dependency graph resolution                              │
│  • Trace index generation                                   │
│                                                             │
│  Input: Task JSON (stdin)                                   │
│  Output: Result JSON (stdout)                               │
└─────────────────────────────────────────────────────────────┘
                          ↓
                [Parallel Execution]
                          ↓
┌───────────────────────┐           ┌───────────────────────┐
│ AgentRouter           │           │ ParallelDispatcher    │
│                       │           │                       │
│ • Route tasks to      │    ←──→   │ • Manage dependency   │
│   appropriate agents  │           │   graph               │
│ • Execute agent calls │           │ • Coordinate parallel │
│ • Handle errors       │           │   execution           │
│                       │           │ • Generate traces     │
└───────────────────────┘           └───────────────────────┘
          ↓                                    ↓
    [Agent Calls]                        [Coordination]
          ↓                                    ↓
┌───────────────────────┐           ┌───────────────────────┐
│ CoderAgent            │           │ DebugAgent            │
│ (Pydantic Agent)      │           │ (Pydantic Agent)      │
│                       │           │                       │
│ • Contract-driven     │           │ • BFROS debugging     │
│   code generation     │           │ • Root cause analysis │
│ • ONEX node creation  │           │ • Quality assessment  │
│ • Quality validation  │           │ • Performance analysis│
│                       │           │                       │
│ MCP Calls: assess_    │           │ MCP Calls: assess_    │
│ code_quality, etc     │           │ code_quality, etc     │
└───────────────────────┘           └───────────────────────┘
          ↓                                    ↓
    [MCP Tool Calls]                     [MCP Tool Calls]
          ↓                                    ↓
┌─────────────────────────────────────────────────────────────┐
│ Archon MCP Server                                           │
│                                                             │
│ • assess_code_quality                                       │
│ • perform_rag_query                                         │
│ • research (orchestrated intelligence)                      │
│ • Pattern traceability system                               │
│ • Quality gates validation                                  │
└─────────────────────────────────────────────────────────────┘
```

## Data Flow

### Phase 1: Request Analysis

```
User Request
    ↓
Claude Agent receives natural language input
    ↓
Agent analyzes request complexity
    ↓
Decision: Single agent vs Parallel dispatch?
    ↓
If parallel: Proceed to Phase 2
If single: Delegate directly to agent
```

**Key Decisions**:
- Task count (1 vs multiple)
- Independence (parallel vs sequential)
- Agent type (coder vs debug vs mixed)
- Complexity assessment

### Phase 2: Task Planning

```
Complex request identified
    ↓
Identify natural task boundaries
    ↓
Map tasks to agent capabilities
    • Generation → agent_coder
    • Analysis → agent_debug_intelligence
    ↓
Determine dependencies
    • Independent → parallel batch
    • Sequential → dependency chain
    ↓
Build task graph (DAG)
```

**Outputs**:
- Task list with unique IDs
- Agent assignment per task
- Dependency graph
- Estimated execution plan

### Phase 3: Task Definition

```
Task plan created
    ↓
Read task_schema.py for reference
    ↓
Build JSON task definitions
    • task_id: unique identifier
    • agent: "coder" or "debug"
    • description: human-readable
    • input_data: agent-specific schema
    • dependencies: task IDs
    ↓
Validate task definitions
    • Schema compliance
    • Dependency validity
    • No circular references
    ↓
Add execution config
    • max_workers
    • timeout_seconds
    • trace_dir
```

**Outputs**:
- Complete task JSON
- Validated dependencies
- Execution configuration

### Phase 4: Dispatch Execution

```
Task JSON ready
    ↓
Write to temporary file
    ↓
Execute dispatch_runner.py via Bash
    • stdin: task JSON
    • stdout: result JSON
    • stderr: errors/warnings
    ↓
dispatch_runner.py processes input
    ↓
AgentRouter receives tasks
    ↓
ParallelDispatcher manages execution
    • Build dependency graph
    • Identify ready tasks (no pending deps)
    • Execute batch in parallel
    • Wait for completion
    • Mark tasks complete
    • Repeat until all done
    ↓
Agents execute (agent_coder, agent_debug_intelligence)
    • Call MCP tools as needed
    • Generate outputs
    • Handle errors
    • Return results
    ↓
Results aggregated
    ↓
Trace files written
    • Individual task traces
    • Dispatch index
    ↓
Result JSON written to stdout
```

**Outputs**:
- Result JSON (success/partial/failure)
- Individual task traces
- Dispatch index file
- Generated code/analysis files

### Phase 5: Result Reading

```
Bash execution completes
    ↓
Claude Agent reads result JSON
    ↓
Parse result structure
    • Overall status
    • Individual task results
    • Summary statistics
    • Trace references
    ↓
Identify successes and failures
    ↓
Read detailed traces if needed
```

**Analysis**:
- Which tasks succeeded?
- What outputs were generated?
- What errors occurred?
- Were there dependency failures?

### Phase 6: Result Assembly

```
Results parsed and understood
    ↓
Synthesize coherent response
    • Overall status summary
    • Successful outputs highlighted
    • Failures explained
    • Next steps suggested
    ↓
Present to user
    • Clear status
    • File locations
    • Trace references
    • Actionable recommendations
```

**Outputs**:
- User-friendly response
- File references
- Trace locations
- Next step suggestions

## Task Schema Design

### Core Schema

```python
class TaskInput(BaseModel):
    task_id: str              # Unique identifier
    agent: str                # "coder" or "debug"
    description: str          # Human-readable purpose
    input_data: Dict          # Agent-specific input
    dependencies: List[str]   # Task IDs to wait for
```

### Agent-Specific Schemas

**CoderAgent Input**:
```python
{
    "contract_description": str,    # What to generate
    "node_type": Literal[...],      # ONEX node type
    "output_path": str,             # Absolute path
    "context_files": List[str],     # Reference files
    "validation_level": Literal[...] # Validation strictness
}
```

**DebugAgent Input**:
```python
{
    "problem_description": str,     # Issue description
    "affected_files": List[str],    # Files to analyze
    "error_traces": List[str],      # Stack traces
    "analysis_depth": Literal[...], # Analysis level
    "hypothesis": str               # Optional hypothesis
}
```

### Dependency Graph

**Structure**: Directed Acyclic Graph (DAG)
- Nodes: Tasks
- Edges: Dependencies (A → B means B depends on A)

**Properties**:
- Must be acyclic (no circular dependencies)
- Can have multiple independent subgraphs
- Supports fan-out (one task → many dependents)
- Supports fan-in (many tasks → one dependent)

**Execution Strategy**:
1. Identify tasks with no dependencies (ready to run)
2. Execute ready tasks in parallel
3. Mark completed tasks
4. Repeat until all tasks complete

## Parallel Execution Model

### Execution Patterns

**Pattern 1: Pure Parallel**
```
Task A ──┐
Task B ──┼──→ [Execute simultaneously] ──→ Results [A, B, C]
Task C ──┘
```

**Pattern 2: Sequential Chain**
```
Task A ──→ Task B ──→ Task C ──→ Results
```

**Pattern 3: Fan-Out**
```
           ┌──→ Task B
Task A ────┼──→ Task C ──→ Results
           └──→ Task D
```

**Pattern 4: Fan-In**
```
Task A ──┐
Task B ──┼──→ Task D ──→ Results
Task C ──┘
```

**Pattern 5: Pipeline**
```
         ┌──→ Task B1 ──┐
Task A ──┤              ├──→ Task C ──→ Results
         └──→ Task B2 ──┘
```

### Concurrency Control

**max_workers**: Controls parallel execution limit
- Default: 5
- Recommended: CPU cores × 1.5
- Consider: Memory, I/O, API rate limits

**Execution Pool**:
- asyncio-based concurrency
- Non-blocking I/O for agent calls
- Shared MCP connection pool
- Task timeout enforcement

### Error Handling

**Error Propagation**:
1. Task fails → Error captured
2. Dependent tasks blocked
3. Independent tasks continue
4. Partial results returned

**Recovery Strategies**:
- Graceful degradation (continue with successes)
- Detailed error reporting
- Trace file generation
- Retry suggestions

## Trace System

### Trace Files

**Individual Task Trace**: `traces/{task_id}.json`
```json
{
    "task_id": "unique-id",
    "agent": "coder|debug",
    "input": {...},
    "output": {...},
    "error": null,
    "execution_time_ms": 1234,
    "mcp_calls": [
        {
            "tool": "assess_code_quality",
            "input": {...},
            "output": {...},
            "duration_ms": 456
        }
    ],
    "timestamp": "2025-10-06T12:00:00Z"
}
```

**Dispatch Index**: `traces/dispatch-{timestamp}.json`
```json
{
    "correlation_id": "uuid",
    "dispatch_timestamp": "2025-10-06T12:00:00Z",
    "total_time_ms": 5678,
    "task_count": 5,
    "config": {...},
    "tasks": [
        {
            "task_id": "...",
            "agent": "...",
            "status": "success|error",
            "trace_file": "traces/task-id.json"
        }
    ]
}
```

### Correlation

**Correlation ID**: UUID generated per dispatch session
- Links all tasks in a dispatch
- Enables cross-task analysis
- Facilitates debugging

**Benefits**:
- Track related executions
- Analyze workflow patterns
- Debug dependency issues
- Performance profiling

## Performance Characteristics

### Expected Performance

**Latency Components**:
- Dispatch overhead: ~100-200ms
- Task scheduling: ~10-20ms per task
- Agent execution: Variable (500ms-5000ms)
- Result aggregation: ~50-100ms
- Trace writing: ~20-50ms per task

**Parallel Speedup**:
- 2 tasks: ~1.67x speedup
- 3 tasks: ~2.00x speedup
- 5 tasks: ~2.50x speedup
- 10 tasks: ~3.33x speedup

**Efficiency**:
- Parallel efficiency: 60-80%
- Break-even point: 3 tasks @ 500ms each
- Optimal batch size: 3-10 tasks

### Performance Tuning

**Optimization Strategies**:
1. Maximize task independence
2. Balance task complexity
3. Right-size max_workers
4. Minimize dependency chains
5. Use appropriate timeouts

**Monitoring**:
- Execution time per task
- Overall dispatch time
- Parallel efficiency ratio
- Resource utilization
- Error rates

## Integration Points

### Claude Agent Integration

**Tools Used**:
- `Write`: Create task JSON files
- `Bash`: Execute dispatch_runner.py
- `Read`: Parse results and traces
- `Glob`: Verify outputs

**Workflow**:
1. Agent receives user request
2. Agent creates task JSON (Write)
3. Agent executes runner (Bash)
4. Agent reads results (Read)
5. Agent presents response

### Python System Integration

**Dependencies**:
- Pydantic for schema validation
- asyncio for concurrency
- Existing parallel execution framework
- Agent implementations (coder, debug)

**MCP Integration**:
- Shared MCP connection
- Tool call routing
- Trace generation
- Error handling

### File System Integration

**Paths**:
- `/Volumes/PRO-G40/Code/omniclaude/agents/parallel_execution/`: System root
- `./traces/`: Trace output directory
- `/tmp/`: Temporary task/result files
- User-specified: Generated code output

**File Operations**:
- Task JSON: Temporary files
- Results: Temporary files (parsed by agent)
- Traces: Persistent (for analysis)
- Outputs: Persistent (generated code)

## Security Considerations

### Input Validation

**Task JSON**:
- Pydantic schema validation
- Type checking
- Required field enforcement
- Path sanitization

**File Paths**:
- Absolute paths required
- Path traversal prevention
- Permission checking
- Directory existence validation

### Execution Safety

**Isolation**:
- Each task executes independently
- Shared MCP connection (controlled)
- Resource limits (timeout, workers)
- Error containment

**Trace Security**:
- No sensitive data in traces
- File permissions (user-only)
- Automatic cleanup available
- Correlation ID for privacy

## Error Recovery

### Error Types

1. **Input Errors**:
   - Malformed JSON
   - Schema validation failures
   - Invalid dependencies
   - Solution: Fix and retry

2. **Execution Errors**:
   - Agent failures
   - MCP tool errors
   - Timeouts
   - Solution: Analyze trace, adjust parameters

3. **Dependency Errors**:
   - Circular dependencies
   - Missing task references
   - Solution: Restructure task graph

4. **System Errors**:
   - File I/O failures
   - Permission errors
   - Resource exhaustion
   - Solution: Fix environment, retry

### Recovery Patterns

**Partial Success**:
- Continue with successful tasks
- Report failures clearly
- Suggest retry strategy
- Provide trace references

**Complete Failure**:
- Identify root cause
- Clear error messaging
- Suggest fixes
- Enable manual retry

**Cascading Failures**:
- Identify upstream failure
- Show dependency impact
- Fix root cause first
- Retry dependent tasks

## Extension Points

### Adding New Agents

1. Implement Pydantic agent
2. Add to AgentRouter
3. Define input schema
4. Update task_schema.py
5. Document in agent-parallel-dispatcher.md

### Custom Workflows

1. Create task templates
2. Define dependency patterns
3. Build workflow scripts
4. Document usage

### Integration Hooks

1. Pre-dispatch validation
2. Post-task callbacks
3. Custom trace formatting
4. Result transformers

## Future Enhancements

### Planned Features

1. **Dynamic Worker Scaling**: Adjust max_workers based on load
2. **Retry Logic**: Automatic retry for transient failures
3. **Caching**: Cache task results for identical inputs
4. **Streaming Results**: Partial results as tasks complete
5. **Web Dashboard**: Real-time execution monitoring
6. **Advanced Scheduling**: Priority queues, resource limits

### Performance Improvements

1. **Optimized Dependency Resolution**: Faster graph algorithms
2. **Connection Pooling**: Reuse MCP connections
3. **Batch Processing**: Bulk operations where possible
4. **Lazy Evaluation**: Defer expensive operations

### Usability Enhancements

1. **Interactive Mode**: Progress updates during execution
2. **Task Templates**: Predefined task patterns
3. **Validation Tools**: Pre-flight checks
4. **Result Formatting**: Customizable output formats

## Conclusion

The Parallel Dispatcher architecture provides:
- Intelligent orchestration via Claude agent
- Robust parallel execution via Python system
- Comprehensive tracing for all operations
- Clear separation of concerns
- Extensible design for future enhancements

This architecture enables complex multi-agent workflows while maintaining visibility, control, and performance.
