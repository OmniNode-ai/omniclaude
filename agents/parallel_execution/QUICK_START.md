# Parallel Dispatcher Quick Start Guide

## Overview

The Parallel Dispatcher system enables intelligent orchestration of parallel agent execution through a Claude Code agent (`agent-parallel-dispatcher`) that controls a Python parallel execution system.

## Architecture at a Glance

```
User Request
     ↓
Claude Agent (Orchestrator)
     ↓ (analyzes, plans, creates task JSON)
     ↓
dispatch_runner.py
     ↓ (executes tasks in parallel)
     ↓
[agent_coder] + [agent_debug_intelligence]
     ↓
Results + Trace Files
     ↓
Claude Agent (Assembly)
     ↓
Final Response to User
```

## Quick Start

### 1. Direct Python Usage

```bash
# Create task definition
cat > tasks.json << 'EOF'
{
  "tasks": [
    {
      "task_id": "gen-effect",
      "agent": "coder",
      "description": "Generate database Effect node",
      "input_data": {
        "contract_description": "Effect node for database writes",
        "node_type": "Effect",
        "output_path": "/tmp/node_db_effect.py",
        "validation_level": "moderate"
      },
      "dependencies": []
    }
  ]
}
EOF

# Execute
cd /Volumes/PRO-G40/Code/omniclaude/agents/parallel_execution
python dispatch_runner.py < tasks.json

# View results
ls traces/
```

### 2. Via Claude Agent

Simply ask the Claude Code agent:

```
"Generate three ONEX Effect nodes for user operations:
 create user, update user, delete user"
```

The agent will:
1. Analyze your request
2. Create 3 parallel tasks
3. Execute via dispatch_runner.py
4. Present results with trace references

### 3. Mixed Workflows

```
"Debug the authentication module, then generate a fixed version"
```

The agent will:
1. Create debug task (agent_debug_intelligence)
2. Create generation task (agent_coder) with dependency
3. Execute sequentially (debug → generate)
4. Show findings + generated fix

## Common Patterns

### Pattern 1: Parallel Code Generation

**Use Case**: Generate multiple independent code files

**User Request**: "Generate database Effect nodes for: users, products, orders"

**Task Breakdown**:
- 3 independent coder tasks
- All execute in parallel
- ~60-80% faster than sequential

### Pattern 2: Debug Then Fix

**Use Case**: Investigate issue and create solution

**User Request**: "Debug the API performance issue and generate a caching layer"

**Task Breakdown**:
- 1 debug task (analyzes existing code)
- 1 coder task (depends on debug findings)
- Sequential execution
- Debug informs generation

### Pattern 3: Parallel Analysis

**Use Case**: Analyze multiple components simultaneously

**User Request**: "Analyze authentication, authorization, and session management for security issues"

**Task Breakdown**:
- 3 independent debug tasks
- All execute in parallel
- Results aggregated for comprehensive view

### Pattern 4: Validate and Regenerate

**Use Case**: Quality check existing code and regenerate if needed

**User Request**: "Validate all ONEX nodes in /path/to/nodes/ directory, regenerate any non-compliant ones"

**Task Breakdown**:
- Multiple debug tasks (validate each file) → parallel
- Multiple coder tasks (regenerate if needed) → depends on validation
- Two-phase execution

## Task Schema Reference

### CoderAgent Task

```json
{
  "task_id": "unique-id",
  "agent": "coder",
  "description": "What this task does",
  "input_data": {
    "contract_description": "Natural language description",
    "node_type": "Effect|Compute|Reducer|Orchestrator",
    "output_path": "/absolute/path/output.py",
    "context_files": ["/absolute/path/context.py"],
    "validation_level": "strict|moderate|lenient"
  },
  "dependencies": []
}
```

### DebugAgent Task

```json
{
  "task_id": "unique-id",
  "agent": "debug",
  "description": "What this task does",
  "input_data": {
    "problem_description": "Issue to investigate",
    "affected_files": ["/absolute/path/file.py"],
    "error_traces": ["Stack trace or error message"],
    "analysis_depth": "quick|standard|deep",
    "hypothesis": "Optional initial hypothesis"
  },
  "dependencies": []
}
```

## Configuration Options

```json
{
  "config": {
    "max_workers": 5,              // Parallel task limit
    "timeout_seconds": 300,        // Per-task timeout
    "trace_dir": "./traces"        // Trace output directory
  }
}
```

**Tuning Guide**:
- `max_workers`: CPU cores × 1.5 (typical)
- `timeout_seconds`: 60 (simple), 300 (moderate), 600 (complex)
- `trace_dir`: Relative to execution directory

## Output Structure

### Success Output

```json
{
  "status": "success",
  "results": [
    {
      "task_id": "gen-effect",
      "status": "success",
      "output": {
        "generated_file": "/tmp/node_db_effect.py",
        "validation_passed": true
      },
      "execution_time_ms": 1234,
      "trace_file": "traces/gen-effect.json"
    }
  ],
  "summary": {
    "total_tasks": 1,
    "successful": 1,
    "failed": 0,
    "total_time_ms": 1234
  },
  "trace_index": "traces/dispatch-20251006_120000.json"
}
```

### Error Output

```json
{
  "status": "failure",
  "results": [
    {
      "task_id": "gen-effect",
      "status": "error",
      "error": "Invalid node_type: invalid",
      "execution_time_ms": 50,
      "trace_file": "traces/gen-effect.json"
    }
  ],
  "summary": {
    "total_tasks": 1,
    "successful": 0,
    "failed": 1,
    "total_time_ms": 50
  }
}
```

## Trace Files

### Individual Task Trace

Location: `traces/{task_id}.json`

Contains:
- Task input data
- Agent execution details
- MCP tool calls (if applicable)
- Output or error details
- Timing information

### Dispatch Index

Location: `traces/dispatch-{timestamp}.json`

Contains:
- Correlation ID for entire dispatch
- All task definitions
- Task status summary
- Links to individual traces

**Usage**:
```bash
# View specific task trace
cat traces/gen-effect.json | jq .

# View dispatch index
cat traces/dispatch-20251006_120000.json | jq .

# Find all failed tasks
cat traces/dispatch-*.json | jq '.tasks[] | select(.status=="error")'
```

## Performance Expectations

### Parallel Speedup

| Tasks | Sequential | Parallel | Speedup |
|-------|-----------|----------|---------|
| 1     | 1x        | 1x       | 1.00x   |
| 2     | 2x        | 1.2x     | 1.67x   |
| 3     | 3x        | 1.5x     | 2.00x   |
| 5     | 5x        | 2.0x     | 2.50x   |
| 10    | 10x       | 3.0x     | 3.33x   |

*Assumes similar task complexity and sufficient CPU resources*

### Overhead

- Dispatch coordination: ~100-200ms
- Task scheduling: ~10-20ms per task
- Result aggregation: ~50-100ms
- Trace writing: ~20-50ms per task

**Break-Even Point**: 3+ tasks with >500ms execution time each

## Troubleshooting

### Common Issues

#### 1. "No module named 'agents.agent_coder'"

**Cause**: Wrong working directory or Python path
**Solution**:
```bash
cd /Volumes/PRO-G40/Code/omniclaude/agents/parallel_execution
export PYTHONPATH=/Volumes/PRO-G40/Code/omniclaude:$PYTHONPATH
python dispatch_runner.py < tasks.json
```

#### 2. "Invalid input format: validation error"

**Cause**: Malformed task JSON
**Solution**: Validate against task_schema.py examples

#### 3. "Circular dependency detected"

**Cause**: Task graph has cycles
**Solution**: Review dependencies, ensure DAG structure

#### 4. "Task timeout exceeded"

**Cause**: Task took longer than timeout_seconds
**Solution**: Increase timeout or simplify task

#### 5. All tasks fail with same error

**Cause**: Environment issue (MCP server down, missing dependencies)
**Solution**:
```bash
# Test single agent manually
python -c "from agents.agent_coder import CoderAgent; print('OK')"

# Check MCP server
# (verify Archon MCP is running)
```

### Debug Strategy

1. **Check Trace Files**: Always start with individual task traces
2. **Validate Input**: Ensure task JSON matches schema exactly
3. **Test Isolation**: Try running single task first
4. **Review Dependencies**: Draw dependency graph to visualize
5. **Increase Verbosity**: Check stderr output from dispatch_runner.py

## Advanced Usage

### Custom Task Builders

```python
from task_schema import TaskBuilder

builder = TaskBuilder()

# Create coder task
task1 = builder.create_coder_task(
    task_id="gen-1",
    description="Generate Effect node",
    contract_description="Database writer",
    node_type="Effect",
    output_path="/tmp/output.py"
)

# Create debug task
task2 = builder.create_debug_task(
    task_id="debug-1",
    description="Analyze performance",
    problem_description="Slow API responses",
    affected_files=["/path/to/api.py"]
)

# Validate
from task_schema import validate_task_dependencies, detect_circular_dependencies

errors = validate_task_dependencies([task1, task2])
cycles = detect_circular_dependencies([task1, task2])

print(f"Validation: {errors or 'OK'}")
print(f"Cycles: {cycles or 'None'}")
```

### Programmatic Execution

```python
import asyncio
import json
from dispatch_runner import DispatchInput, ParallelDispatcher

async def run_dispatch():
    # Create input
    input_data = {
        "tasks": [
            {
                "task_id": "test-1",
                "agent": "coder",
                "description": "Test task",
                "input_data": {
                    "contract_description": "Test",
                    "node_type": "Effect",
                    "output_path": "/tmp/test.py"
                },
                "dependencies": []
            }
        ]
    }

    # Parse and execute
    dispatch_input = DispatchInput.model_validate(input_data)
    dispatcher = ParallelDispatcher(dispatch_input.config)
    result = await dispatcher.dispatch(dispatch_input.tasks)

    print(result.model_dump_json(indent=2))

asyncio.run(run_dispatch())
```

## Best Practices

1. **Use Absolute Paths**: Always provide absolute paths for files
2. **Validate Before Dispatch**: Check task JSON structure
3. **Minimize Dependencies**: More parallelism = better performance
4. **Right-Size Tasks**: Balance granularity vs overhead
5. **Monitor Traces**: Use trace files for debugging
6. **Set Realistic Timeouts**: Consider task complexity
7. **Handle Partial Success**: Plan for some tasks failing
8. **Keep Tasks Focused**: One clear objective per task

## Integration with Claude Agent

The Claude Code agent (`agent-parallel-dispatcher`) provides intelligent orchestration:

### Agent Advantages

1. **Natural Language Interface**: Describe what you want in plain English
2. **Intelligent Planning**: Agent breaks down complex requests optimally
3. **Agent Routing**: Automatically selects coder vs debug agents
4. **Dependency Analysis**: Identifies parallelization opportunities
5. **Result Synthesis**: Assembles coherent responses from multiple tasks
6. **Error Recovery**: Suggests fixes for failed tasks

### When to Use Agent vs Direct Python

**Use Agent (Recommended)**:
- Complex requests requiring analysis
- Natural language descriptions
- Mixed coder/debug workflows
- Want intelligent task breakdown
- Need help with result interpretation

**Use Direct Python**:
- Scripting/automation
- Predefined task workflows
- Integration with other tools
- Batch processing
- CI/CD pipelines

## Examples Library

See `examples/` directory for complete examples:

- `01_parallel_generation.json` - Generate multiple files in parallel
- `02_debug_then_fix.json` - Sequential debug → fix workflow
- `03_validation_workflow.json` - Validate then regenerate pattern
- `04_mixed_analysis.json` - Combined coder + debug tasks
- `05_complex_dependencies.json` - Multi-stage workflow with dependencies

## Next Steps

1. **Try Examples**: Run provided example tasks
2. **Create Custom Tasks**: Use TaskBuilder for your use cases
3. **Explore Traces**: Understand trace file structure
4. **Optimize Performance**: Tune max_workers and dependencies
5. **Integrate with Workflows**: Add to your development process

## Support

- **Task Schema Reference**: `task_schema.py`
- **Agent Instructions**: `agent-parallel-dispatcher.md`
- **Architecture Details**: `ARCHITECTURE.md`
- **Trace Analysis Guide**: `TRACE_GUIDE.md`

## Version

Current Version: 1.0.0
Last Updated: 2025-10-06
