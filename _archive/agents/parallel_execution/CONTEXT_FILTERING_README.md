# Context Filtering System - Quick Start

## What is Context Filtering?

An intelligent system that gathers context **once** and distributes filtered, relevant portions to each agent, reducing token usage by 60-80% and eliminating duplicate RAG queries.

## Quick Start

### Enable Context Filtering

```bash
cd ${PROJECT_ROOT}/agents/parallel_execution

# Run with context filtering
python dispatch_runner.py --enable-context < your_tasks.json
```

### Run Example

```bash
# Test with provided example
./test_context_filtering.sh

# Or manually
python dispatch_runner.py --enable-context < example_context_filtering.json
```

## Task Format

Add `context_requirements` to each task:

```json
{
  "tasks": [
    {
      "task_id": "gen-1",
      "agent": "coder",
      "description": "Generate ONEX node",
      "input_data": { ... },
      "context_requirements": [
        "pattern:onex-architecture",
        "rag:domain-patterns"
      ],
      "dependencies": []
    }
  ]
}
```

## Context Types

- `file:<path>` - Specific file contents
- `pattern:<name>` - Code pattern examples
- `rag:<query>` - RAG query results
- `structure:<path>` - Directory structure

## Performance

| Scenario | Without Filtering | With Filtering | Speedup |
|----------|-------------------|----------------|---------|
| 2 agents | ~3000ms | ~1700ms | 43% faster |
| 3 agents | ~4500ms | ~1850ms | 59% faster |
| 5 agents | ~7500ms | ~2150ms | 71% faster |

**Token Reduction**: 60-80% across all agents

## When to Use

✅ **Use context filtering when**:
- 2+ agents in workflow
- Agents need similar domain knowledge
- Multiple RAG queries expected
- Token usage is a concern

❌ **Don't use context filtering when**:
- Single agent task
- Agent needs no external context
- Real-time response required (<100ms)

## Files

- **`context_manager.py`** - Core implementation
- **`example_context_filtering.json`** - Example task definition
- **`test_context_filtering.sh`** - Test script
- **`CONTEXT_FILTERING_IMPLEMENTATION.md`** - Full documentation

## Troubleshooting

### No context filtering logs?
- Ensure `--enable-context` flag is used
- Check MCP server is running

### Empty filtered context?
- Verify `context_requirements` match global context keys
- Check global context gathering succeeded

### Performance worse?
- Only use for 2+ agents (overhead > savings for 1 agent)
- Ensure MCP server is responsive

## Example Output

```
[DispatchRunner] Context filtering enabled
[DispatchRunner] Phase 0: Gathering global context...
[ContextManager] Gathered 4 context items in 1234ms
[DispatchRunner] Context gathered: 4 items, ~2000 tokens
[DispatchRunner] Filtering context for task gen-1: 2 requirements
[ContextManager] Filtered to 2 items (1500 tokens) in 45ms
[DispatchRunner] Task gen-1: 2 context items attached
[DispatchRunner] Phase 3: Executing 4 tasks in parallel...
```

## Integration

### For New Agents

Check for pre-gathered context in your agent:

```python
# In your agent's execute method
pre_gathered_context = task.input_data.get("pre_gathered_context", {})

if pre_gathered_context:
    # Use pre-filtered context
    for key, context_item in pre_gathered_context.items():
        content = context_item.get("content")
        # Use content...
else:
    # Fall back to independent gathering
    intelligence = await self._gather_intelligence(...)
```

### For Task Planning

Review available context and declare requirements:

```python
"context_requirements": [
    "pattern:onex-compute-node",  # Specific pattern
    "rag:jwt-refresh-tokens",     # Specific RAG query
    "file:auth.py"                # Specific file
]
```

## Next Steps

1. Read **CONTEXT_FILTERING_IMPLEMENTATION.md** for full details
2. Run **test_context_filtering.sh** to see it in action
3. Review **AGENT-PARALLEL-DISPATCHER.md** for workflow details
4. Integrate into your agents following examples in **agent_coder.py** and **agent_debug_intelligence.py**

## Architecture

```
Phase 0: Global Context Gathering (once)
    ↓
Phase 1: Task Planning (with context awareness)
    ↓
Phase 2: Context Filtering (per task, <200ms)
    ↓
Phase 3: Parallel Execution (with filtered context)
```

## Support

- Implementation: `${PROJECT_ROOT}/agents/parallel_execution/`
- Documentation: `CONTEXT_FILTERING_IMPLEMENTATION.md`
- Examples: `example_context_filtering.json`
- Tests: `test_context_filtering.sh`
