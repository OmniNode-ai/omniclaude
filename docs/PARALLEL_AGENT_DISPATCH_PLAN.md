# Parallel Agent Dispatch with Context Enrichment - Implementation Plan

**Status**: Planned
**Created**: 2025-10-24
**Target**: Implement while waiting for omniarchon re-ingestion
**Estimated Effort**: 7-11 hours over 1-2 days (not even full days)

## Overview

Enhance the agent dispatch system to support parallel Polly workflows with intelligent context enrichment. Pre-load agents with discovered code entities (files, classes, functions, models, enums) and relationships to enable more informed decision-making.

## Problem Statement

**Current Limitations**:
1. Single agent dispatch - sequential execution only
2. Agents start with no codebase context
3. No pre-discovery of relevant code entities
4. No safety boundaries for read-only vs. write-enabled operations
5. Manual context gathering during agent execution

**Desired State**:
1. Parallel agent dispatch for concurrent workflows
2. Pre-enriched context with discovered code entities
3. Intelligent pattern and relationship discovery before dispatch
4. Safety boundaries preventing destructive operations from read-only agents
5. Automatic context packaging from ingested codebase

## Architecture Vision

### Current Flow
```
User Prompt → Hook Detects Agent → Single Polly Dispatch → Execution
```

### Enhanced Flow
```
User Prompt → Hook Detects Agent
    ↓
Pre-Dispatch Intelligence Gathering
    ├─ Pattern Discovery (find relevant code patterns)
    ├─ Code Entity Extraction (files/classes/functions/models/enums)
    ├─ Relationship Analysis (imports, dependencies, call graphs)
    └─ Keyword Extraction (from user prompt)
    ↓
Build Enriched Context Package
    ↓
Parallel Polly Dispatch (with boundaries)
    ├─ Primary Agent (write-enabled, git-capable)
    ├─ Research Agent (read-only, intelligence gathering)
    ├─ Analysis Agent (read-only, code quality/patterns)
    └─ Documentation Agent (read-only, find relevant docs)
    ↓
Result Aggregation & Synthesis
    ↓
User Receives Enhanced Results
```

## Implementation Phases

### Phase 1: Context Enrichment Engine (2-3 hours)

**Goal**: Build intelligence gathering system for pre-dispatch context enrichment

**Components**:

1. **ContextEnrichmentEngine Class**
   - File: `claude_hooks/lib/context_enrichment_engine.py`
   - Purpose: Orchestrate intelligence gathering and context packaging
   - Methods:
     - `enrich_context(user_prompt, correlation_id)` → enriched context
     - `_extract_keywords(user_prompt)` → relevant keywords
     - `_discover_patterns(keywords)` → code patterns
     - `_extract_entities(patterns)` → files/classes/functions/models/enums
     - `_analyze_relationships(entities)` → import/dependency graph
     - `_package_context(...)` → final context object

2. **Entity Extraction Logic**
   - Parse pattern discovery results for code entities
   - Extract class names, function signatures, model definitions, enum types
   - Build entity index with file locations and line numbers
   - Include type information and docstrings where available

3. **Relationship Analysis**
   - Extract import relationships from discovered patterns
   - Build call graph from function/method usage
   - Identify data flow between components
   - Map inheritance and composition relationships

4. **Context Package Format**
   ```json
   {
     "correlation_id": "uuid",
     "timestamp": "ISO-8601",
     "user_prompt": "original prompt",
     "keywords": ["keyword1", "keyword2"],
     "discovered_entities": {
       "files": [
         {
           "path": "relative/path/to/file.py",
           "line_count": 500,
           "language": "python",
           "last_modified": "ISO-8601"
         }
       ],
       "classes": [
         {
           "name": "ClassName",
           "file": "path/to/file.py",
           "line_number": 42,
           "methods": ["method1", "method2"],
           "docstring": "Class description"
         }
       ],
       "functions": [
         {
           "name": "function_name",
           "file": "path/to/file.py",
           "line_number": 100,
           "signature": "def function_name(arg1: str) -> bool",
           "docstring": "Function description"
         }
       ],
       "models": [
         {
           "name": "ModelName",
           "file": "path/to/file.py",
           "line_number": 20,
           "fields": ["field1", "field2"],
           "type": "pydantic" | "dataclass" | "sqlalchemy"
         }
       ],
       "enums": [
         {
           "name": "EnumName",
           "file": "path/to/file.py",
           "line_number": 15,
           "values": ["VALUE1", "VALUE2"]
         }
       ]
     },
     "patterns": {
       "pattern_count": 10,
       "patterns": [
         {
           "file_path": "path/to/pattern.py",
           "similarity": 0.95,
           "pattern_type": "effect_node"
         }
       ]
     },
     "relationships": {
       "imports": [
         {"from": "file1.py", "imports": "file2.py", "symbols": ["Symbol1"]}
       ],
       "calls": [
         {"caller": "function1", "callee": "function2", "file": "path"}
       ],
       "inheritance": [
         {"child": "ChildClass", "parent": "ParentClass"}
       ]
     },
     "metadata": {
       "enrichment_latency_ms": 250,
       "total_entities": 47,
       "total_relationships": 23
     }
   }
   ```

**Deliverables**:
- `claude_hooks/lib/context_enrichment_engine.py` (300-400 lines)
- Unit tests for entity extraction
- Integration test with `/request-intelligence` skill
- Documentation of context package format

**Testing**:
```bash
# Test context enrichment
python -c "
from claude_hooks.lib.context_enrichment_engine import ContextEnrichmentEngine
import asyncio

async def test():
    engine = ContextEnrichmentEngine()
    context = await engine.enrich_context(
        user_prompt='Refactor intelligence event client',
        correlation_id='test-123'
    )
    print(json.dumps(context, indent=2))

asyncio.run(test())
"
```

### Phase 2: Agent Boundary System (1-2 hours)

**Goal**: Define and enforce safety boundaries for agent operations

**Components**:

1. **Agent Boundary Configuration**
   - File: `claude_hooks/config/agent-boundaries.yaml`
   - Define read-only vs. write-enabled agents
   - Specify allowed operations per agent type
   - Set restrictions and safety limits

   ```yaml
   # agent-boundaries.yaml

   read_only_agents:
     - agent-research
     - agent-analysis
     - agent-documentation
     - agent-qa-tester
     capabilities:
       - read_files
       - search_code
       - pattern_discovery
       - code_analysis
       - gather_intelligence
       - grep_codebase
       - glob_patterns
     restrictions:
       - no_git_branch
       - no_git_commit
       - no_file_writes
       - no_file_edits
       - no_destructive_ops
       - no_external_network_calls

   write_enabled_agents:
     - agent-implementation
     - agent-refactor
     - agent-bugfix
     - agent-feature
     capabilities:
       - all_read_only_capabilities
       - write_files
       - edit_files
       - git_branch
       - git_commit
       - run_tests
     restrictions:
       - requires_primary_agent_status
       - one_per_workflow

   git_capable_agents:
     - agent-implementation
     - agent-refactor
     - agent-bugfix
     capabilities:
       - all_write_enabled_capabilities
       - git_operations
     restrictions:
       - requires_primary_agent_status
       - no_force_push
       - no_main_branch_direct_commit
   ```

2. **Boundary Enforcement**
   - File: `claude_hooks/lib/boundary_enforcer.py`
   - Validate agent operations against boundaries
   - Reject unauthorized operations
   - Log boundary violations

3. **Boundary Validation in Dispatch**
   - Check agent type before dispatch
   - Inject boundary config into agent context
   - Monitor agent operations for violations
   - Automatic agent termination on boundary breach

**Deliverables**:
- `claude_hooks/config/agent-boundaries.yaml`
- `claude_hooks/lib/boundary_enforcer.py` (150-200 lines)
- Boundary violation logging
- Documentation of boundary system

**Testing**:
```bash
# Test boundary enforcement
python -c "
from claude_hooks.lib.boundary_enforcer import BoundaryEnforcer

enforcer = BoundaryEnforcer()

# Should pass
enforcer.validate('agent-research', 'read_files')  # True

# Should fail
enforcer.validate('agent-research', 'git_commit')  # Raises BoundaryViolation
"
```

### Phase 3: Parallel Dispatch Coordinator (2-3 hours)

**Goal**: Enable parallel Polly dispatch with result aggregation

**Components**:

1. **ParallelDispatchCoordinator Class**
   - File: `claude_hooks/lib/parallel_dispatch_coordinator.py`
   - Orchestrate parallel agent dispatch
   - Manage agent lifecycle
   - Aggregate results

2. **Workflow Planning**
   - Analyze user prompt to determine workflow type
   - Select appropriate agents for parallel execution
   - Define primary vs. supporting agents
   - Set execution order and dependencies

3. **Agent Dispatch**
   - Dispatch multiple Polly instances in parallel
   - Inject enriched context into each agent
   - Enforce boundaries for each agent type
   - Monitor progress and collect results

4. **Result Aggregation**
   - Collect results from all agents
   - Synthesize findings into unified response
   - Prioritize primary agent results
   - Include supporting agent insights as context

**Key Methods**:

```python
class ParallelDispatchCoordinator:
    async def dispatch_parallel_workflow(
        self,
        user_prompt: str,
        detected_role: str,
        context_package: Dict[str, Any],
        correlation_id: str,
        enable_parallel: bool = True,
    ) -> WorkflowResult:
        """
        Dispatch parallel agent workflow.

        Args:
            user_prompt: Original user prompt
            detected_role: Primary detected agent role
            context_package: Enriched context from Phase 1
            correlation_id: Correlation ID for tracking
            enable_parallel: Enable parallel dispatch (feature flag)

        Returns:
            WorkflowResult with aggregated findings
        """

        # 1. Plan workflow
        workflow = self._plan_workflow(detected_role, user_prompt)

        # 2. Validate boundaries
        for agent in workflow.agents:
            self._boundary_enforcer.validate_agent(agent)

        # 3. Dispatch agents
        if enable_parallel:
            results = await self._dispatch_parallel(workflow, context_package)
        else:
            results = await self._dispatch_sequential(workflow, context_package)

        # 4. Aggregate results
        return self._aggregate_results(results, workflow)

    def _plan_workflow(
        self,
        primary_role: str,
        user_prompt: str,
    ) -> WorkflowPlan:
        """
        Plan parallel workflow based on primary role and prompt.

        Example workflows:

        Implementation tasks:
          - Primary: agent-implementation (write-enabled)
          - Supporting: agent-research (read-only, pattern discovery)
          - Supporting: agent-qa-tester (read-only, test analysis)

        Refactoring tasks:
          - Primary: agent-refactor (write-enabled)
          - Supporting: agent-analysis (read-only, code quality)
          - Supporting: agent-documentation (read-only, docs search)

        Research tasks:
          - Primary: agent-research (read-only)
          - Supporting: agent-documentation (read-only)
          - Supporting: agent-analysis (read-only)
        """
        pass

    async def _dispatch_parallel(
        self,
        workflow: WorkflowPlan,
        context: Dict[str, Any],
    ) -> List[AgentResult]:
        """Dispatch agents in parallel using asyncio.gather."""
        tasks = []
        for agent in workflow.agents:
            task = self._dispatch_single_agent(
                role=agent.role,
                agent_type=agent.type,  # primary | supporting
                prompt=workflow.prompt_for_agent(agent),
                context=context,
                boundaries=agent.boundaries,
            )
            tasks.append(task)

        return await asyncio.gather(*tasks, return_exceptions=True)

    def _aggregate_results(
        self,
        results: List[AgentResult],
        workflow: WorkflowPlan,
    ) -> WorkflowResult:
        """
        Aggregate results from parallel agents.

        Priority:
        1. Primary agent results (implementation/changes)
        2. Supporting agent insights (research/analysis)
        3. Metadata and performance metrics
        """
        pass
```

**Deliverables**:
- `claude_hooks/lib/parallel_dispatch_coordinator.py` (400-500 lines)
- Workflow planning logic
- Result aggregation system
- Performance metrics tracking

**Testing**:
```bash
# Test parallel dispatch
python -c "
from claude_hooks.lib.parallel_dispatch_coordinator import ParallelDispatchCoordinator
import asyncio

async def test():
    coordinator = ParallelDispatchCoordinator()
    result = await coordinator.dispatch_parallel_workflow(
        user_prompt='Refactor intelligence event client for better error handling',
        detected_role='refactor',
        context_package=enriched_context,
        correlation_id='test-123',
    )
    print(result)

asyncio.run(test())
"
```

### Phase 4: Hook Integration (1-2 hours)

**Goal**: Integrate new system into user-prompt-submit hook

**Components**:

1. **Hook Updates**
   - File: `claude_hooks/user-prompt-submit.sh`
   - Add feature flag for parallel dispatch
   - Integrate context enrichment before dispatch
   - Add parallel dispatch logic
   - Maintain backward compatibility

2. **Feature Flag Control**
   - Environment variable: `ENABLE_PARALLEL_DISPATCH`
   - Default: `false` (opt-in for safety)
   - Easy toggle for testing

3. **Enhanced Hook Flow**
   ```bash
   #!/bin/bash

   # Existing agent detection...
   AGENT_NAME="agent-research"
   AGENT_ROLE="research"

   # NEW: Check feature flag
   ENABLE_PARALLEL_DISPATCH="${ENABLE_PARALLEL_DISPATCH:-false}"
   ENABLE_CONTEXT_ENRICHMENT="${ENABLE_CONTEXT_ENRICHMENT:-true}"

   # NEW: Context enrichment (if enabled)
   if [ "$ENABLE_CONTEXT_ENRICHMENT" = "true" ]; then
       CONTEXT_PACKAGE=$(python3 -m claude_hooks.lib.context_enrichment_engine \
           --prompt "$USER_PROMPT" \
           --correlation-id "$CORRELATION_ID")
   fi

   # NEW: Parallel dispatch (if enabled)
   if [ "$ENABLE_PARALLEL_DISPATCH" = "true" ]; then
       # Use parallel coordinator
       python3 -m claude_hooks.lib.parallel_dispatch_coordinator \
           --prompt "$USER_PROMPT" \
           --role "$AGENT_ROLE" \
           --context "$CONTEXT_PACKAGE" \
           --correlation-id "$CORRELATION_ID"
   else
       # Original single dispatch
       # (existing Task tool logic)
   fi
   ```

**Deliverables**:
- Updated `claude_hooks/user-prompt-submit.sh`
- Feature flag documentation
- Backward compatibility testing
- Performance impact measurement

**Testing**:
```bash
# Test with enrichment only (no parallel)
ENABLE_CONTEXT_ENRICHMENT=true \
ENABLE_PARALLEL_DISPATCH=false \
  echo "Test prompt" | claude-code

# Test with parallel dispatch
ENABLE_CONTEXT_ENRICHMENT=true \
ENABLE_PARALLEL_DISPATCH=true \
  echo "Refactor intelligence client" | claude-code
```

### Phase 5: Documentation & Testing (1 hour)

**Goal**: Complete documentation and comprehensive testing

**Components**:

1. **Architecture Documentation**
   - Update `docs/UNIFIED_EVENT_INFRASTRUCTURE.md`
   - Create `docs/PARALLEL_DISPATCH_ARCHITECTURE.md`
   - Document context enrichment format
   - Document workflow planning strategies

2. **Usage Examples**
   - Example: Research workflow with parallel agents
   - Example: Implementation workflow with boundaries
   - Example: Context package inspection
   - Example: Feature flag usage

3. **Performance Benchmarking**
   - Measure context enrichment latency
   - Compare parallel vs. sequential dispatch
   - Track memory usage with multiple agents
   - Monitor Kafka throughput impact

4. **Edge Case Testing**
   - Handle intelligence gathering failures
   - Test boundary violation scenarios
   - Verify agent timeout handling
   - Test result aggregation with partial failures

**Deliverables**:
- `docs/PARALLEL_DISPATCH_ARCHITECTURE.md`
- Usage examples and patterns
- Performance benchmark report
- Test coverage report

## Example Workflows

### Example 1: Refactoring Task
```
User: "Refactor the intelligence event client for better error handling"

Hook Detection:
  → Agent: agent-refactor
  → Confidence: 0.95

Pre-Dispatch Intelligence:
  → Discovers: intelligence_event_client.py (561 lines)
  → Extracts:
    - Classes: IntelligenceEventClient
    - Methods: 15 methods
    - Exception types: 3 custom exceptions
  → Finds: 23 files importing this client
  → Relationships: 47 import edges, 12 inheritance relationships

Parallel Dispatch:
  ├─ Primary (agent-refactor, write-enabled)
  │  └─ Task: Refactor error handling in IntelligenceEventClient
  │  └─ Context: Full entity list + relationships
  │  └─ Boundaries: Can write/edit/commit
  │
  ├─ Supporting (agent-research, read-only)
  │  └─ Task: Find error handling patterns in omniclaude codebase
  │  └─ Context: Same entity list
  │  └─ Boundaries: Read-only, no git ops
  │
  ├─ Supporting (agent-analysis, read-only)
  │  └─ Task: Analyze current error handling quality
  │  └─ Context: Focus on exception patterns
  │  └─ Boundaries: Read-only, no git ops
  │
  └─ Supporting (agent-documentation, read-only)
     └─ Task: Find error handling best practices in docs
     └─ Context: Documentation entities only
     └─ Boundaries: Read-only, no git ops

Result Aggregation:
  → Primary Results:
    - Refactored IntelligenceEventClient with improved error handling
    - Added 5 new exception types
    - Implemented retry logic with exponential backoff
    - Updated 23 files that import the client

  → Supporting Insights (from research):
    - Found OnexError pattern used in 47 files
    - Identified retry decorator pattern in 12 locations
    - Recommended circuit breaker pattern from similar code

  → Supporting Insights (from analysis):
    - Current error handling coverage: 67%
    - 12 bare except clauses need fixing
    - Recommended adding error telemetry

  → Supporting Insights (from documentation):
    - ONEX error handling standards documented
    - Best practices for exception chaining
    - Examples of proper error context preservation

Final Response to User:
  → Refactored code (from primary)
  → Best practices applied (from research findings)
  → Quality improvements made (from analysis recommendations)
  → Documentation references included (from doc search)
```

### Example 2: Research Task
```
User: "Find similar effect node patterns in omniarchon"

Hook Detection:
  → Agent: agent-research
  → Confidence: 0.95

Pre-Dispatch Intelligence:
  → Keywords: ["effect", "node", "patterns", "omniarchon"]
  → Pattern search: node_*_effect.py
  → Discovers: 11 effect node files
  → Extracts: Effect node class patterns, interfaces

Parallel Dispatch:
  ├─ Primary (agent-research, read-only)
  │  └─ Task: Find and analyze effect node patterns
  │  └─ Context: All discovered effect nodes
  │  └─ Boundaries: Read-only
  │
  ├─ Supporting (agent-analysis, read-only)
  │  └─ Task: Analyze pattern consistency
  │  └─ Context: Same entity list
  │  └─ Boundaries: Read-only
  │
  └─ Supporting (agent-documentation, read-only)
     └─ Task: Find effect node documentation
     └─ Context: Documentation entities
     └─ Boundaries: Read-only

Result Aggregation:
  → Primary Results: 11 effect nodes found with detailed analysis
  → Analysis Insights: 95% pattern consistency, 2 outliers
  → Documentation: ONEX effect node guidelines found
```

## File Structure

```
omniclaude/
├─ claude_hooks/
│  ├─ config/
│  │  └─ agent-boundaries.yaml          # NEW: Boundary definitions
│  ├─ lib/
│  │  ├─ context_enrichment_engine.py   # NEW: Context enrichment
│  │  ├─ boundary_enforcer.py           # NEW: Boundary enforcement
│  │  ├─ parallel_dispatch_coordinator.py # NEW: Parallel dispatch
│  │  └─ hook_event_adapter.py          # EXISTING: Event publishing
│  └─ user-prompt-submit.sh             # MODIFIED: Add enrichment + parallel
├─ docs/
│  ├─ PARALLEL_DISPATCH_ARCHITECTURE.md # NEW: Architecture docs
│  └─ UNIFIED_EVENT_INFRASTRUCTURE.md   # MODIFIED: Add new components
└─ skills/
   └─ intelligence/
      └─ request-intelligence/           # EXISTING: Used by enrichment
```

## Dependencies

**Required**:
- ✅ Intelligence event infrastructure (completed)
- ✅ `/request-intelligence` skill (completed)
- ✅ Kafka event bus operational (completed)
- ✅ Hook event adapter (completed)

**New Dependencies**:
- `pyyaml` - For agent boundary configuration
- `aiofiles` - For async file operations (if needed)

## Performance Targets

### Context Enrichment
- Enrichment latency: <500ms p95
- Entity extraction: <100 entities per query
- Relationship analysis: <200ms
- Total overhead: <1 second before dispatch

### Parallel Dispatch
- Parallel speedup: 2-3x vs. sequential for 3 agents
- Memory overhead: <100MB per additional agent
- Kafka throughput: Support 10+ concurrent agent workflows
- Result aggregation: <100ms

### Boundary Enforcement
- Validation latency: <10ms per operation
- Violation detection: Real-time
- Logging overhead: <5ms per log entry

## Success Criteria

✅ **Functional**:
- Context enrichment discovers relevant code entities
- Parallel dispatch works with 2+ agents
- Boundaries prevent unauthorized operations
- Results aggregate correctly

✅ **Performance**:
- Context enrichment <500ms p95
- Parallel execution faster than sequential for 3+ agents
- No significant memory leaks

✅ **Safety**:
- Read-only agents cannot write/commit
- Boundary violations logged and blocked
- Feature flags work correctly
- Backward compatibility maintained

## Risks and Mitigations

**Risk 1: Performance Degradation**
- Mitigation: Feature flags to disable if needed
- Mitigation: Performance benchmarking before rollout
- Mitigation: Caching of enriched context

**Risk 2: Boundary Violations**
- Mitigation: Comprehensive boundary testing
- Mitigation: Real-time monitoring and alerts
- Mitigation: Automatic agent termination on violation

**Risk 3: Result Aggregation Complexity**
- Mitigation: Start with simple aggregation (primary + supporting)
- Mitigation: Clear priority rules
- Mitigation: Extensive testing with edge cases

**Risk 4: Kafka Overload**
- Mitigation: Rate limiting on parallel dispatch
- Mitigation: Monitor Kafka metrics
- Mitigation: Circuit breaker for intelligence service

## Future Enhancements

**Phase 6: Advanced Workflow Planning** (FUTURE)
- ML-based workflow recommendation
- Historical workflow performance analysis
- Adaptive agent selection based on success rates

**Phase 7: Cross-Agent Communication** (FUTURE)
- Inter-agent messaging during execution
- Shared state management
- Dynamic workflow adaptation

**Phase 8: Intelligent Result Synthesis** (FUTURE)
- LLM-based result aggregation
- Conflict resolution between agents
- Automated decision-making from multiple perspectives

## Timeline

**Day 1**:
- Morning: Phase 1 (Context Enrichment) - 2-3 hours
- Afternoon: Phase 2 (Boundary System) - 1-2 hours

**Day 2**:
- Morning: Phase 3 (Parallel Dispatch) - 2-3 hours
- Afternoon: Phase 4 (Hook Integration) + Phase 5 (Docs/Testing) - 2-3 hours

**Total**: 7-11 hours over 1-2 days (not even full days)

## Next Steps

1. ✅ Create this plan document
2. ⏸️ Get user approval
3. ⏸️ Start Phase 1: Context Enrichment Engine
4. ⏸️ Test enrichment in isolation
5. ⏸️ Proceed to Phase 2 if successful

---

**Status**: Plan complete, ready for implementation
**Next Action**: User approval to begin Phase 1
**Estimated Start**: After approval
**Estimated Completion**: 1-2 days (7-11 hours of work, not even full days)
