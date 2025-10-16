# Parallel Dispatcher Integration Guide

**Complete guide for integrating the Parallel Dispatcher system**

## Overview

This guide covers:
1. System prerequisites
2. Integration with Claude Code agent
3. Integration with existing Python agents
4. Testing and validation
5. Production deployment

---

## Prerequisites

### 1. Environment Setup

**Required Software**:
- Python 3.9+
- Claude Code CLI
- jq (for JSON processing)
- Archon MCP server

**Python Dependencies**:
```bash
pip install pydantic>=2.0.0 pyyaml>=6.0 httpx>=0.27.0 aiofiles>=23.0.0
```

### 2. Directory Structure

Ensure the following structure exists:
```
${PROJECT_ROOT}/
├── agents/
│   ├── parallel_execution/
│   │   ├── dispatch_runner.py
│   │   ├── task_schema.py
│   │   ├── examples/
│   │   └── traces/
│   ├── agent_coder.py
│   └── agent_debug_intelligence.py
└── ~/.claude/
    └── agent-definitions/
        └── agent-parallel-dispatcher.yaml
```

### 3. Archon MCP Server

**Verify MCP server is running**:
```bash
curl http://localhost:8051/health
```

Expected response:
```json
{
  "status": "healthy",
  "version": "1.0.0"
}
```

If not running, start it:
```bash
# Navigate to your MCP server directory
cd /path/to/archon-mcp
docker-compose up -d
```

---

## Integration with Claude Code Agent

### Step 1: Register Agent Definition

Create agent definition file:

```bash
cat > ~/.claude/agent-definitions/agent-parallel-dispatcher.yaml << 'EOF'
name: agent-parallel-dispatcher
version: 1.0.0
title: Parallel Dispatcher
description: Intelligent orchestrator for parallel agent execution

capabilities:
  - Parallel task coordination
  - Intelligent agent routing
  - Dependency management
  - Result synthesis

triggers:
  - "parallel"
  - "multiple tasks"
  - "generate multiple"
  - "debug and fix"
  - "batch"

instructions:
  path: ${PROJECT_ROOT}/agents/agent-parallel-dispatcher.md

metadata:
  domain: orchestration
  complexity: high
  requires_mcp: true
  requires_tracing: true
EOF
```

### Step 2: Verify Registration

```bash
# List registered agents
cat ~/.claude/agent-definitions/agent-registry.yaml | grep -A 5 "agent-parallel-dispatcher"
```

### Step 3: Test Agent Invocation

Ask Claude Code:
```
"Use agent-parallel-dispatcher to generate three ONEX Effect nodes"
```

Claude should:
1. Load agent-parallel-dispatcher.md instructions
2. Analyze the request
3. Create task JSON
4. Execute dispatch_runner.py
5. Present results

---

## Integration with Python Agents

### Step 1: Verify Existing Agents

**Check agent_coder**:
```bash
python -c "
from agents.agent_coder import CoderAgent, CoderInput
agent = CoderAgent()
print('CoderAgent loaded successfully')
"
```

**Check agent_debug_intelligence**:
```bash
python -c "
from agents.agent_debug_intelligence import DebugAgent, DebugInput
agent = DebugAgent()
print('DebugAgent loaded successfully')
"
```

### Step 2: Test Agent Execution

**Test CoderAgent directly**:
```python
import asyncio
from agents.agent_coder import CoderAgent, CoderInput

async def test_coder():
    agent = CoderAgent()
    input_data = CoderInput(
        contract_description="Simple Effect node for testing",
        node_type="Effect",
        output_path="/tmp/test_effect.py",
        validation_level="moderate"
    )
    result = await agent.run(input_data)
    print(f"Success: {result.success}")
    print(f"Output: {result.output}")

asyncio.run(test_coder())
```

**Test DebugAgent directly**:
```python
import asyncio
from agents.agent_debug_intelligence import DebugAgent, DebugInput

async def test_debug():
    agent = DebugAgent()
    input_data = DebugInput(
        problem_description="Test analysis",
        affected_files=["/tmp/test_file.py"],
        analysis_depth="quick"
    )
    result = await agent.run(input_data)
    print(f"Success: {result.success}")
    print(f"Findings: {result.findings}")

asyncio.run(test_debug())
```

### Step 3: Test via Dispatcher

```bash
# Create test task
cat > /tmp/test-task.json << 'EOF'
{
  "tasks": [
    {
      "task_id": "test-coder",
      "agent": "coder",
      "description": "Test code generation",
      "input_data": {
        "contract_description": "Test Effect node",
        "node_type": "Effect",
        "output_path": "/tmp/test_output.py",
        "validation_level": "moderate"
      },
      "dependencies": []
    }
  ]
}
EOF

# Execute
cd ${PROJECT_ROOT}/agents/parallel_execution
python dispatch_runner.py < /tmp/test-task.json

# Check results
echo $?  # Should be 0 for success
```

---

## Testing and Validation

### Unit Tests

**Test 1: Task Schema Validation**
```bash
cd ${PROJECT_ROOT}/agents/parallel_execution

# Valid task should succeed
cat > /tmp/valid-task.json << 'EOF'
{
  "tasks": [
    {
      "task_id": "test-1",
      "agent": "coder",
      "description": "Test",
      "input_data": {
        "contract_description": "Test",
        "node_type": "Effect",
        "output_path": "/tmp/test.py"
      },
      "dependencies": []
    }
  ]
}
EOF

python -c "
from dispatch_runner import DispatchInput
import json

with open('/tmp/valid-task.json') as f:
    data = json.load(f)

input_obj = DispatchInput.model_validate(data)
print('✅ Valid task schema')
"

# Invalid task should fail
cat > /tmp/invalid-task.json << 'EOF'
{
  "tasks": [
    {
      "task_id": "test-1",
      "agent": "invalid_agent",
      "description": "Test"
    }
  ]
}
EOF

python -c "
from dispatch_runner import DispatchInput
import json

try:
    with open('/tmp/invalid-task.json') as f:
        data = json.load(f)
    input_obj = DispatchInput.model_validate(data)
    print('❌ Should have failed')
except Exception as e:
    print(f'✅ Correctly rejected invalid schema: {type(e).__name__}')
"
```

**Test 2: Dependency Graph**
```bash
# Create task with dependencies
cat > /tmp/dep-task.json << 'EOF'
{
  "tasks": [
    {
      "task_id": "task-1",
      "agent": "coder",
      "description": "First task",
      "input_data": {
        "contract_description": "First",
        "node_type": "Effect",
        "output_path": "/tmp/first.py"
      },
      "dependencies": []
    },
    {
      "task_id": "task-2",
      "agent": "coder",
      "description": "Second task",
      "input_data": {
        "contract_description": "Second",
        "node_type": "Effect",
        "output_path": "/tmp/second.py"
      },
      "dependencies": ["task-1"]
    }
  ]
}
EOF

python -c "
from task_schema import validate_task_dependencies, detect_circular_dependencies
import json

with open('/tmp/dep-task.json') as f:
    data = json.load(f)

dep_errors = validate_task_dependencies(data['tasks'])
cycle_errors = detect_circular_dependencies(data['tasks'])

if not dep_errors and not cycle_errors:
    print('✅ Valid dependency graph')
else:
    print(f'❌ Dependency errors: {dep_errors}')
    print(f'❌ Circular dependencies: {cycle_errors}')
"
```

**Test 3: Parallel Execution**
```bash
# Run example parallel generation
cd ${PROJECT_ROOT}/agents/parallel_execution
python dispatch_runner.py < examples/01_parallel_generation.json

# Check exit code
if [ $? -eq 0 ]; then
    echo "✅ Parallel execution succeeded"
else
    echo "❌ Parallel execution failed"
fi

# Verify traces
if [ -d "traces" ] && [ -n "$(ls -A traces 2>/dev/null)" ]; then
    echo "✅ Trace files generated"
    ls -lh traces/
else
    echo "❌ No trace files found"
fi
```

### Integration Tests

**Test 4: End-to-End Workflow**
```bash
# Test complete workflow
cat > /tmp/e2e-test.json << 'EOF'
{
  "tasks": [
    {
      "task_id": "gen-1",
      "agent": "coder",
      "description": "Generate Effect node",
      "input_data": {
        "contract_description": "User authentication Effect",
        "node_type": "Effect",
        "output_path": "/tmp/e2e_auth_effect.py",
        "validation_level": "moderate"
      },
      "dependencies": []
    },
    {
      "task_id": "gen-2",
      "agent": "coder",
      "description": "Generate Compute node",
      "input_data": {
        "contract_description": "Data validation Compute",
        "node_type": "Compute",
        "output_path": "/tmp/e2e_validation_compute.py",
        "validation_level": "moderate"
      },
      "dependencies": []
    }
  ],
  "config": {
    "max_workers": 2,
    "timeout_seconds": 120,
    "trace_dir": "./traces"
  }
}
EOF

# Execute
cd ${PROJECT_ROOT}/agents/parallel_execution
python dispatch_runner.py < /tmp/e2e-test.json > /tmp/e2e-result.json

# Validate results
python -c "
import json

with open('/tmp/e2e-result.json') as f:
    result = json.load(f)

print(f'Status: {result[\"status\"]}')
print(f'Total tasks: {result[\"summary\"][\"total_tasks\"]}')
print(f'Successful: {result[\"summary\"][\"successful\"]}')
print(f'Failed: {result[\"summary\"][\"failed\"]}')

if result['status'] == 'success':
    print('✅ End-to-end test passed')
else:
    print('❌ End-to-end test failed')
    for task_result in result['results']:
        if task_result['status'] == 'error':
            print(f'Task {task_result[\"task_id\"]} error: {task_result[\"error\"]}')
"
```

**Test 5: Claude Agent Integration**
```bash
# Test via Claude Code CLI
echo "Generate two ONEX Effect nodes using agent-parallel-dispatcher: user writer and product reader" | claude

# Expected: Claude should invoke agent-parallel-dispatcher and execute tasks
```

---

## Production Deployment

### Configuration

**Environment Variables**:
```bash
export ARCHON_MCP_URL=http://localhost:8051
export PARALLEL_DISPATCH_TRACE_DIR=/var/log/parallel-dispatch/traces
export PARALLEL_DISPATCH_MAX_WORKERS=10
export PARALLEL_DISPATCH_TIMEOUT=600
```

**Configuration File** (`/etc/parallel-dispatch/config.yaml`):
```yaml
dispatcher:
  max_workers: 10
  timeout_seconds: 600
  trace_dir: /var/log/parallel-dispatch/traces

agents:
  coder:
    timeout_seconds: 300
    validation_level: strict

  debug:
    timeout_seconds: 600
    analysis_depth: deep

mcp:
  url: http://localhost:8051
  timeout_seconds: 30
  retry_attempts: 3

logging:
  level: INFO
  format: json
  destination: /var/log/parallel-dispatch/app.log
```

### Monitoring

**Health Check Endpoint**:
```python
# Add to dispatch_runner.py
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "version": "1.0.0",
        "mcp_connected": await check_mcp_connection(),
        "agents_available": ["coder", "debug"]
    }
```

**Metrics Collection**:
```python
# Add prometheus metrics
from prometheus_client import Counter, Histogram

task_counter = Counter('dispatch_tasks_total', 'Total tasks processed', ['agent', 'status'])
task_duration = Histogram('dispatch_task_duration_seconds', 'Task execution time', ['agent'])
```

### Error Handling

**Retry Logic**:
```python
# Add to AgentRouter
async def execute_task_with_retry(self, task: TaskInput, max_retries: int = 3) -> TaskOutput:
    for attempt in range(max_retries):
        try:
            return await self.execute_task(task)
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(2 ** attempt)  # Exponential backoff
```

**Circuit Breaker**:
```python
# Add circuit breaker for MCP calls
from circuitbreaker import CircuitBreaker

@CircuitBreaker(failure_threshold=5, recovery_timeout=60)
async def call_mcp_tool(tool_name: str, input_data: dict):
    # MCP call implementation
    pass
```

### Scaling

**Horizontal Scaling**:
- Run multiple dispatch_runner.py instances
- Use load balancer (nginx/haproxy)
- Shared trace storage (S3/NFS)

**Vertical Scaling**:
- Increase max_workers based on CPU cores
- Tune timeout values
- Optimize agent implementations

---

## Troubleshooting

### Common Issues

**Issue 1: Import Errors**
```
ModuleNotFoundError: No module named 'agents.agent_coder'
```

**Solution**:
```bash
# Add to PYTHONPATH
export PYTHONPATH=${PROJECT_ROOT}:$PYTHONPATH

# Or use absolute imports in dispatch_runner.py
```

**Issue 2: MCP Connection Failures**
```
Error: Connection refused to localhost:8051
```

**Solution**:
```bash
# Check MCP server
curl http://localhost:8051/health

# Restart if needed
docker-compose restart archon-mcp
```

**Issue 3: Trace Directory Permissions**
```
PermissionError: [Errno 13] Permission denied: 'traces/dispatch-*.json'
```

**Solution**:
```bash
# Create directory with proper permissions
mkdir -p traces
chmod 755 traces
```

**Issue 4: Task Timeout**
```
Task exceeded timeout_seconds
```

**Solution**:
```json
{
  "config": {
    "timeout_seconds": 600  // Increase timeout
  }
}
```

### Debug Mode

**Enable verbose logging**:
```bash
export DISPATCH_DEBUG=1
python dispatch_runner.py < tasks.json 2>&1 | tee debug.log
```

**Validate task JSON**:
```bash
cat tasks.json | jq . > /dev/null && echo "Valid JSON" || echo "Invalid JSON"
```

**Check agent connectivity**:
```bash
python -c "
import asyncio
from agents.agent_coder import CoderAgent

async def test():
    agent = CoderAgent()
    print('✅ CoderAgent initialized')

asyncio.run(test())
"
```

---

## Performance Tuning

### Optimal Settings

**For CPU-bound tasks** (code generation):
```json
{
  "config": {
    "max_workers": "cpu_cores * 1.5",
    "timeout_seconds": 300
  }
}
```

**For I/O-bound tasks** (debugging, analysis):
```json
{
  "config": {
    "max_workers": "cpu_cores * 3",
    "timeout_seconds": 600
  }
}
```

**For mixed workloads**:
```json
{
  "config": {
    "max_workers": "cpu_cores * 2",
    "timeout_seconds": 450
  }
}
```

### Benchmarking

```bash
# Run benchmark
time python dispatch_runner.py < examples/01_parallel_generation.json

# Compare sequential vs parallel
time python run_sequential.py < examples/01_parallel_generation.json
time python dispatch_runner.py < examples/01_parallel_generation.json

# Calculate speedup
# Speedup = Sequential Time / Parallel Time
```

---

## Maintenance

### Log Rotation

```bash
# Setup logrotate
cat > /etc/logrotate.d/parallel-dispatch << 'EOF'
/var/log/parallel-dispatch/*.log {
    daily
    rotate 7
    compress
    delaycompress
    notifempty
    create 0644 appuser appuser
}
EOF
```

### Trace Cleanup

```bash
# Clean old traces (keep last 30 days)
find traces/ -name "*.json" -mtime +30 -delete

# Archive traces
tar -czf traces-$(date +%Y%m%d).tar.gz traces/
```

### Updates

```bash
# Pull latest code
cd ${PROJECT_ROOT}
git pull origin main

# Update dependencies
pip install -U pydantic pyyaml httpx aiofiles

# Restart services
systemctl restart parallel-dispatch
```

---

## Support

- **Documentation**: Review ARCHITECTURE.md and QUICK_START.md
- **Examples**: Check examples/ directory
- **Traces**: Examine trace files for debugging
- **Logs**: Check application logs
- **MCP Status**: Verify Archon MCP server health

---

Built with ❤️ for production-ready parallel agent orchestration.
