# Parallel Dispatcher System

**Intelligent orchestration for parallel agent execution**

## Overview

The Parallel Dispatcher system combines a Claude Code agent orchestrator with a Python parallel execution backend to enable complex multi-agent workflows with automatic tracing, dependency management, and performance optimization.

### Key Features

- **Intelligent Orchestration**: Claude agent analyzes requests and plans optimal task breakdown
- **Parallel Execution**: Python backend executes independent tasks simultaneously
- **Automatic Tracing**: Every execution generates detailed trace files
- **Dependency Management**: Supports complex task dependencies with cycle detection
- **Multi-Agent Support**: Routes tasks to specialized agents (coder, debug)
- **Performance Optimization**: 60-80% speedup for parallel workflows

## Quick Start

### 1. Via Claude Agent (Recommended)

Simply ask the Claude Code agent:

```
"Generate three ONEX Effect nodes for database operations:
 user writer, product reader, and order updater"
```

The agent will:
1. Analyze your request
2. Break into 3 parallel tasks
3. Execute via dispatch_runner.py
4. Present synthesized results

### 2. Direct Python Usage

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
cd ${PROJECT_ROOT}/agents/parallel_execution
python dispatch_runner.py < tasks.json

# View results
cat traces/dispatch-*.json | jq .
```

## Architecture

```
User Request → Claude Agent (Orchestrator) → dispatch_runner.py
                    ↓                              ↓
              [Task Planning]              [Parallel Execution]
                    ↓                              ↓
              [Task JSON]                [agent_coder + agent_debug]
                    ↓                              ↓
                                          [Results + Traces]
                    ↓                              ↓
              [Result Assembly] ← [Result JSON + Trace Files]
                    ↓
            Final Response to User
```

### Components

1. **agent-parallel-dispatcher** (Claude Agent)
   - Natural language request parsing
   - Intelligent task planning
   - Agent routing (coder vs debug)
   - Result synthesis

2. **dispatch_runner.py** (Python Entry Point)
   - JSON input/output handling
   - Parallel execution coordination
   - Dependency graph resolution
   - Trace generation

3. **AgentRouter** (Task Executor)
   - Routes tasks to appropriate Pydantic agents
   - Handles agent-specific inputs
   - Manages execution lifecycle

4. **ParallelDispatcher** (Coordinator)
   - Manages dependency graph
   - Coordinates parallel execution
   - Generates trace index

5. **Agents** (Execution)
   - **agent_coder**: Contract-driven code generation, ONEX nodes
   - **agent_debug_intelligence**: BFROS debugging, root cause analysis

## Documentation

- **[QUICK_START.md](QUICK_START.md)**: Quick reference and common patterns
- **[ARCHITECTURE.md](ARCHITECTURE.md)**: Detailed architecture documentation
- **[AGENT-PARALLEL-DISPATCHER.md](AGENT-PARALLEL-DISPATCHER.md)**: Agent instructions and workflow
- **[task_schema.py](task_schema.py)**: Task schema definitions and examples
- **[dispatch_runner.py](dispatch_runner.py)**: Main execution script

## Examples

### Example 1: Parallel Code Generation

**Request**: Generate 3 database Effect nodes

```json
{
  "tasks": [
    {
      "task_id": "gen-user-writer",
      "agent": "coder",
      "description": "Generate user writer",
      "input_data": {
        "contract_description": "User database writer Effect node",
        "node_type": "Effect",
        "output_path": "/tmp/node_user_writer_effect.py"
      },
      "dependencies": []
    }
    // ... 2 more similar tasks
  ]
}
```

**Result**: All 3 nodes generated in parallel, ~2x faster than sequential

### Example 2: Debug Then Fix

**Request**: Investigate auth failure, then generate fix

```json
{
  "tasks": [
    {
      "task_id": "debug-auth",
      "agent": "debug",
      "description": "Debug authentication",
      "input_data": {
        "problem_description": "401 errors during login",
        "affected_files": ["/path/to/auth.py"]
      },
      "dependencies": []
    },
    {
      "task_id": "gen-fix",
      "agent": "coder",
      "description": "Generate fix",
      "input_data": {
        "contract_description": "Fixed authentication Effect",
        "node_type": "Effect",
        "output_path": "/tmp/auth_fixed.py"
      },
      "dependencies": ["debug-auth"]
    }
  ]
}
```

**Result**: Debug findings inform code generation, sequential execution

### Example 3: Mixed Workflow

See `examples/03_mixed_workflow.json` for complex workflow with:
- Parallel debug + generation
- Sequential validation
- Multiple agent types
- Dependency coordination

## Task Schema

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
    "error_traces": ["Stack trace"],
    "analysis_depth": "quick|standard|deep",
    "hypothesis": "Optional hypothesis"
  },
  "dependencies": []
}
```

## Performance

### Expected Speedup

| Tasks | Sequential | Parallel | Speedup |
|-------|-----------|----------|---------|
| 1     | 1x        | 1x       | 1.00x   |
| 3     | 3x        | 1.5x     | 2.00x   |
| 5     | 5x        | 2.0x     | 2.50x   |
| 10    | 10x       | 3.0x     | 3.33x   |

### Overhead

- Dispatch coordination: ~100-200ms
- Task scheduling: ~10-20ms per task
- Result aggregation: ~50-100ms
- Trace writing: ~20-50ms per task

**Break-Even Point**: 3+ tasks with >500ms execution time each

## Tracing

### Individual Task Trace

Location: `traces/{task_id}.json`

Contains:
- Task input/output
- Agent execution details
- MCP tool calls
- Timing information

### Dispatch Index

Location: `traces/dispatch-{timestamp}.json`

Contains:
- Correlation ID
- All task definitions
- Status summary
- Links to individual traces

**Usage**:
```bash
# View specific task trace
cat traces/gen-effect.json | jq .

# View dispatch summary
cat traces/dispatch-*.json | jq '.summary'

# Find failed tasks
cat traces/dispatch-*.json | jq '.tasks[] | select(.status=="error")'
```

## Configuration

```json
{
  "config": {
    "max_workers": 5,           // Parallel task limit
    "timeout_seconds": 300,     // Per-task timeout
    "trace_dir": "./traces"     // Trace output directory
  }
}
```

**Tuning**:
- `max_workers`: CPU cores × 1.5 (typical)
- `timeout_seconds`: 60 (simple), 300 (moderate), 600 (complex)

## Error Handling

### Common Errors

1. **Invalid Input**: Fix task JSON structure
2. **Missing Dependencies**: Add missing task or fix reference
3. **Circular Dependencies**: Restructure task graph
4. **Agent Failure**: Read trace file, adjust inputs
5. **Timeout**: Increase timeout or simplify task

### Recovery

- **Partial Success**: Retry failed tasks individually
- **Complete Failure**: Analyze error pattern, fix root cause
- **Dependency Failures**: Fix upstream task first

## Best Practices

1. **Use Absolute Paths**: Never use relative paths
2. **Validate Before Dispatch**: Check JSON structure
3. **Minimize Dependencies**: More parallelism = better performance
4. **Right-Size Tasks**: Balance granularity vs overhead
5. **Monitor Traces**: Use for debugging and optimization
6. **Set Realistic Timeouts**: Consider task complexity
7. **Handle Partial Success**: Plan for some failures

## When to Use

### Use Parallel Dispatch When:
- 3+ independent tasks identified
- Mixed agent types (coder + debug)
- Complex workflows with dependencies
- Performance benefits from parallelism

### Don't Use When:
- Single simple task
- High dependency complexity
- User requests specific agent
- Overhead outweighs benefits

## Integration

### Claude Agent

The Claude Code agent provides intelligent orchestration:
- Natural language interface
- Automatic task breakdown
- Agent routing
- Result synthesis

### Python System

Direct Python usage for:
- Scripting/automation
- Predefined workflows
- Batch processing
- CI/CD pipelines

### MCP Integration

All agents connect to Archon MCP for:
- Quality assessment
- RAG intelligence
- Pattern traceability
- Performance monitoring

## Directory Structure

```
parallel_execution/
├── dispatch_runner.py          # Main entry point
├── task_schema.py              # Task definitions & validation
├── AGENT-PARALLEL-DISPATCHER.md # Agent instructions
├── ARCHITECTURE.md             # Detailed architecture
├── QUICK_START.md              # Quick reference
├── README.md                   # This file
├── examples/                   # Example task files
│   ├── 01_parallel_generation.json
│   ├── 02_debug_then_fix.json
│   └── 03_mixed_workflow.json
└── traces/                     # Trace output (generated)
    ├── {task_id}.json
    └── dispatch-{timestamp}.json
```

## Requirements

- Python 3.9+
- Pydantic 2.0+
- Existing agent implementations (agent_coder, agent_debug_intelligence)
- Archon MCP server running
- Claude Code CLI

## Testing

```bash
# Run example workflows
cd ${PROJECT_ROOT}/agents/parallel_execution

# Test parallel generation
python dispatch_runner.py < examples/01_parallel_generation.json

# Test debug then fix
python dispatch_runner.py < examples/02_debug_then_fix.json

# Test mixed workflow
python dispatch_runner.py < examples/03_mixed_workflow.json

# Validate traces
ls -la traces/
```

## Troubleshooting

See [QUICK_START.md](QUICK_START.md#troubleshooting) for detailed troubleshooting guide.

**Quick Checks**:
```bash
# Verify working directory
pwd
# Should be: ${PROJECT_ROOT}/agents/parallel_execution

# Test agent imports
python -c "from agents.agent_coder import CoderAgent; print('OK')"

# Validate task JSON
cat tasks.json | jq . > /dev/null && echo "Valid JSON"

# Check traces
ls -la traces/
```

## Future Enhancements

- Dynamic worker scaling
- Automatic retry logic
- Result caching
- Streaming results
- Web dashboard
- Advanced scheduling

## Support

- Issues: Check trace files first
- Questions: Review ARCHITECTURE.md
- Examples: See examples/ directory
- Schema: Reference task_schema.py

## Version

**Current Version**: 1.0.0
**Last Updated**: 2025-10-06

---

## Quick Command Reference

```bash
# Execute dispatch
python dispatch_runner.py < tasks.json

# View results
cat traces/dispatch-*.json | jq .summary

# Check specific task
cat traces/{task_id}.json | jq .

# Validate JSON
cat tasks.json | jq . > /dev/null

# Clean traces
rm -rf traces/*.json

# Run example
python dispatch_runner.py < examples/01_parallel_generation.json
```

---

Built with ❤️ for intelligent parallel agent orchestration.
