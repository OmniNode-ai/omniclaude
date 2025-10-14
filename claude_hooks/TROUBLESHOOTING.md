# Hook System Troubleshooting Guide

## Quick Diagnostics

### 1. Check Agent Detection
```bash
# Test agent detection manually
python3 test_agent_detection.py
```

### 2. Check Hook Logs
```bash
# View recent hook activity
tail -50 ~/.claude/hooks/hook-enhanced.log

# Check for database connection issues
grep "Database connection not available" ~/.claude/hooks/hook-enhanced.log | tail -10
```

### 3. Check Agent Registry
```bash
# Verify workflow-coordinator is registered
grep -A 10 "workflow-coordinator:" ~/.claude/agent-definitions/agent-registry.yaml
```

## Common Issues

### Issue 1: Agent Not Detected
**Symptoms**: Hook logs show "No agent detected" or wrong agent selected

**Diagnosis**:
```bash
# Check if agent is in registry
grep "agent-name" ~/.claude/agent-definitions/agent-registry.yaml

# Test pattern matching
python3 -c "
import sys
sys.path.insert(0, 'claude_hooks/lib')
from agent_detector import AgentDetector
detector = AgentDetector()
result = detector.detect_agent('Use agent-workflow-coordinator to help me')
print(f'Detected: {result}')
"
```

**Solutions**:
1. **Pattern Matching**: Ensure agent name follows `agent-[name]` format
2. **Case Sensitivity**: Use proper capitalization in prompts
3. **Registry Entry**: Verify agent is registered in `agent-registry.yaml`

### Issue 2: Database Connection Failures
**Symptoms**: Logs show "Database connection not available" repeatedly

**Diagnosis**:
```bash
# Check if Phase 4 API is running
curl -s http://localhost:8053/health

# Check database connection
curl -s http://localhost:8053/api/pattern-traceability/lineage/track
```

**Solutions**:
1. **Start Phase 4 API**: Ensure the Intelligence service is running
2. **Database Connection**: Check PostgreSQL connection in Phase 4 API
3. **Graceful Degradation**: System now handles database failures gracefully

### Issue 3: Wrong Agent Selected
**Symptoms**: AI selects wrong agent (e.g., repository-crawler instead of workflow-coordinator)

**Diagnosis**:
```bash
# Check agent detection priority
python3 -c "
import sys
sys.path.insert(0, 'claude_hooks/lib')
from hybrid_agent_selector import HybridAgentSelector
selector = HybridAgentSelector()
result = selector.select_agent('Use workflow coordinator to help me')
print(f'Agent: {result.agent_name}, Method: {result.method.value}, Confidence: {result.confidence}')
"
```

**Solutions**:
1. **Explicit Patterns**: Use explicit agent names like "Use agent-workflow-coordinator"
2. **Trigger Matching**: Ensure activation triggers are properly configured
3. **AI Fallback**: Check if AI model is selecting correctly

### Issue 4: Polymorphic Agent Not Working
**Symptoms**: Workflow coordinator doesn't assume roles from other agents

**Diagnosis**:
```bash
# Check if banners appear in context
grep -A 5 -B 5 "🐛\|🔧\|🧪\|🎯" ~/.claude/hooks/hook-enhanced.log

# Test polymorphic behavior
echo "Use workflow coordinator to debug this error" | ~/.claude/hooks/user-prompt-submit.sh
```

**Solutions**:
1. **Role Assumption**: Verify workflow-coordinator can load other agent definitions
2. **Banner Detection**: Check if banners appear in injected context
3. **Dynamic Transformation**: Ensure the transformation system is implemented

## Debugging Commands

### Test Agent Detection
```bash
# Test specific patterns
python3 -c "
import sys
sys.path.insert(0, 'claude_hooks/lib')
from agent_detector import AgentDetector
detector = AgentDetector()

test_cases = [
    'Use agent-workflow-coordinator to help me',
    'Use the agent workflow coordinator for this work',
    'Invoke agent-debug-intelligence',
    '@agent-api-architect'
]

for prompt in test_cases:
    result = detector.detect_agent(prompt)
    print(f'{prompt} -> {result}')
"
```

### Test Trigger Matching
```bash
# Test trigger-based detection
python3 -c "
import sys
sys.path.insert(0, 'claude_hooks/lib')
from agent_detector import AgentDetector
detector = AgentDetector()

test_cases = [
    'Help me debug this error',
    'Create tests for this code',
    'Coordinate a workflow for this task'
]

for prompt in test_cases:
    result = detector._detect_by_triggers(prompt)
    print(f'{prompt} -> {result}')
"
```

### Test Full Pipeline
```bash
# Test complete agent selection pipeline
python3 -c "
import sys
sys.path.insert(0, 'claude_hooks/lib')
from hybrid_agent_selector import HybridAgentSelector
selector = HybridAgentSelector()

test_cases = [
    'Use agent-workflow-coordinator to help me',
    'Help me debug this error',
    'Design an API for this service'
]

for prompt in test_cases:
    result = selector.select_agent(prompt)
    print(f'{prompt}')
    print(f'  Agent: {result.agent_name}')
    print(f'  Method: {result.method.value}')
    print(f'  Confidence: {result.confidence:.2f}')
    print()
"
```

## Configuration Files

### Agent Registry
- **Location**: `~/.claude/agent-definitions/agent-registry.yaml`
- **Purpose**: Central registry of all available agents
- **Key Fields**: `name`, `activation_triggers`, `capabilities`

### Agent Definitions
- **Location**: `~/.claude/agent-definitions/*.yaml`
- **Purpose**: Individual agent configurations
- **Banner Field**: Added for polymorphic testing

### Hook Configuration
- **Location**: `~/.claude/hooks/`
- **Files**: `user-prompt-submit.sh`, `lib/`
- **Environment**: `ARCHON_MCP_URL`, `ARCHON_INTELLIGENCE_URL`

## Performance Monitoring

### Detection Statistics
```bash
# Get detection statistics
python3 -c "
import sys
sys.path.insert(0, 'claude_hooks/lib')
from hybrid_agent_selector import HybridAgentSelector
selector = HybridAgentSelector()
stats = selector.get_stats()
for key, value in stats.items():
    print(f'{key}: {value}')
"
```

### Latency Analysis
- **Pattern Matching**: ~1-5ms (fastest)
- **Trigger Matching**: ~2-10ms (fast)
- **AI Selection**: ~1000-5000ms (slowest)

### Success Rates
- **Pattern Rate**: 44.4% (explicit requests)
- **Trigger Rate**: 44.4% (natural language)
- **AI Rate**: 11.1% (semantic analysis)
- **No Agent Rate**: 0% (all detected)

## Recovery Procedures

### Database Connection Issues
1. **Check Phase 4 API**: `curl http://localhost:8053/health`
2. **Restart Service**: If API is down, restart the Intelligence service
3. **Graceful Degradation**: System continues to work without database

### Agent Detection Issues
1. **Registry Check**: Verify agent is in `agent-registry.yaml`
2. **Pattern Test**: Test explicit patterns manually
3. **Trigger Test**: Test trigger-based detection
4. **AI Fallback**: Check if AI selection is working

### Polymorphic Agent Issues
1. **Banner Check**: Look for banners in hook logs
2. **Role Assumption**: Test if workflow-coordinator assumes roles
3. **Context Injection**: Verify banners appear in context

## Contact Information

For additional support:
- **Hook System**: Check `claude_hooks/` directory
- **Agent Registry**: Check `~/.claude/agent-definitions/`
- **Logs**: Check `~/.claude/hooks/hook-enhanced.log`
- **Database**: Check Phase 4 API at `http://localhost:8053`