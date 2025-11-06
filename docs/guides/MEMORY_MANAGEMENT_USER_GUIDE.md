# Memory Management User Guide

## Overview

OmniClaude's Hook-Based Memory Management system provides Claude Code with persistent, intelligent context across sessions. This guide will help you understand and use the memory management features effectively.

## What is Hook-Based Memory Management?

Instead of loading all available context into every prompt (which wastes tokens), the memory management system:

1. **Extracts intent** from your prompts to understand what you're trying to do
2. **Queries relevant memories** based on that intent
3. **Ranks by relevance** to stay within token budgets
4. **Injects context** automatically before Claude sees your prompt
5. **Learns patterns** from successful and failed operations

This results in **75-80% token savings** while providing more relevant context.

## Quick Start

### Installation & Setup

1. **Verify hooks are installed**:
```bash
ls -la ~/.claude/hooks/
# Should see: pre_prompt_submit.py, post_tool_use.py, workspace_change.py
```

2. **Enable memory management** in `.env`:
```bash
# Copy from project root .env.example
cp .env.example .env

# Edit .env and ensure these are set:
ENABLE_MEMORY_CLIENT=true
ENABLE_INTENT_EXTRACTION=true
MEMORY_MAX_TOKENS=5000
```

3. **Create memory storage directory**:
```bash
mkdir -p ~/.claude/memory
chmod 755 ~/.claude/memory
```

4. **Test the setup**:
```bash
# Test memory client
python3 -c "from claude_hooks.lib.memory_client import get_memory_client; import asyncio; print('✅ Memory client works')"

# Test intent extraction
python3 -c "from claude_hooks.lib.intent_extractor import extract_intent; print('✅ Intent extractor works')"
```

### First Use

When you start using Claude Code, the hooks will automatically:

1. **Before each prompt** (pre-prompt-submit):
   - Extract intent from your message
   - Query relevant memories
   - Inject context into your prompt

2. **After each tool execution** (post-tool-use):
   - Record execution results
   - Learn success/failure patterns
   - Update execution history

3. **When files change** (workspace-change):
   - Track file modifications
   - Analyze dependencies
   - Update project context

**You don't need to do anything special** - the hooks work automatically in the background!

## Understanding Memory Categories

Memory is organized into 6 categories:

### 1. Workspace (`workspace/`)
**What it stores**: Current project state
- Git branch, modified files, last commit
- File context (types, dependencies, hashes)
- Project structure and file counts

**Example**:
```json
{
  "branch": "main",
  "modified_files": ["auth.py", "config.py"],
  "last_commit": "abc123",
  "cwd": "/path/to/project"
}
```

### 2. Intelligence (`intelligence/`)
**What it stores**: Available capabilities
- Agent definitions and routing decisions
- ONEX architectural patterns
- System capabilities

### 3. Execution History (`execution_history/`)
**What it stores**: Tool execution records
- Which tools were used
- Success/failure status
- Duration and error messages

**Example**:
```json
{
  "tool": "Edit",
  "file": "auth.py",
  "status": "success",
  "duration_ms": 120,
  "timestamp": "2025-11-06T14:30:00Z"
}
```

### 4. Patterns (`patterns/`)
**What it stores**: Learned success/failure patterns
- Success rates by task type
- Common tool sequences
- Best practices discovered

**Example**:
```json
{
  "task_type": "authentication",
  "success_rate": 0.95,
  "common_tools": ["Read", "Edit", "Bash"],
  "successful_sequences": [
    ["Read", "Edit"],
    ["Read", "Write", "Bash"]
  ]
}
```

### 5. Routing (`routing/`)
**What it stores**: Agent routing decisions
- Confidence scores
- Selected agents
- Routing rationale

### 6. Workspace Events (`workspace_events/`)
**What it stores**: File change events
- Created/modified/deleted timestamps
- Change type and affected files

## Common Workflows

### Workflow 1: Starting a New Feature

**Scenario**: You're implementing JWT authentication

```
You: "Help me implement JWT authentication in auth.py"
```

**What happens behind the scenes**:

1. **Pre-prompt hook extracts intent**:
   - task_type: "authentication"
   - entities: ["JWT", "auth.py"]
   - operations: ["implement"]

2. **Queries relevant memories**:
   - `workspace/file_context_auth_py` (if auth.py exists)
   - `patterns/success_patterns_authentication` (prior auth implementations)
   - `execution_history/auth_py_*` (history of working with this file)

3. **Injects context**:
```
======================================================================
CONTEXT FROM MEMORY (Intent-Driven Retrieval)
======================================================================

## Detected Intent
- Task Type: authentication
- Entities: JWT, auth.py
- Operations: implement

## Current Workspace
- Branch: feature/jwt-auth
- Modified Files: 2 files
  - config.py
  - requirements.txt

## Relevant Context (2 items)

### success_patterns_authentication
```json
{
  "success_rate": 0.92,
  "common_tools": ["Read", "Edit"],
  "best_practice": "Always read file before editing"
}
```

======================================================================

Help me implement JWT authentication in auth.py
```

Claude now sees your original prompt **plus** relevant context from memory!

### Workflow 2: Debugging an Error

**Scenario**: You encounter a database connection error

```
You: "Fix the PostgreSQL connection error in database.py"
```

**What happens**:

1. **Intent extraction**:
   - task_type: "database"
   - entities: ["PostgreSQL", "database.py"]
   - operations: ["fix"]

2. **Memory query finds**:
   - Previous database.py errors in `execution_history`
   - Successful database fixes in `patterns/success_patterns_database`
   - Current file context with dependencies

3. **Injected context shows**:
   - Similar errors that were successfully resolved
   - Tool sequences that worked (e.g., Read → Edit → Bash for testing)
   - Dependencies (psycopg2, sqlalchemy versions)

Claude can now see what worked before and avoid repeating failed approaches!

### Workflow 3: Refactoring Code

**Scenario**: Refactoring a large codebase

```
You: "Refactor the authentication module to use dependency injection"
```

**What happens**:

1. **Intent extraction**:
   - task_type: "refactoring"
   - entities: ["authentication module", "dependency injection"]
   - operations: ["refactor"]

2. **Memory provides**:
   - All files in the authentication module
   - Recent changes to these files
   - Dependencies between modules
   - Successful refactoring patterns

3. **Claude receives**:
   - Complete file context for the module
   - Known dependencies that might break
   - Successful refactoring sequences from history

## Advanced Usage

### Querying Memory Directly

You can query memory directly from Python scripts:

```python
import asyncio
from claude_hooks.lib.memory_client import get_memory_client

async def main():
    memory = get_memory_client()

    # List all categories
    categories = await memory.list_categories()
    print(f"Categories: {categories}")

    # List keys in workspace category
    workspace_keys = await memory.list_memory("workspace")
    print(f"Workspace keys: {workspace_keys}")

    # Get specific memory
    workspace_state = await memory.get_memory("workspace_state", "workspace")
    print(f"Current branch: {workspace_state['branch']}")

    # Get success patterns for authentication
    auth_patterns = await memory.get_memory("success_patterns_authentication", "patterns")
    if auth_patterns:
        print(f"Auth success rate: {auth_patterns.get('success_rate', 'N/A')}")

asyncio.run(main())
```

### Analyzing Execution History

```python
import asyncio
from claude_hooks.lib.memory_client import get_memory_client

async def analyze_file_history(filename):
    memory = get_memory_client()

    # Sanitize filename for key
    safe_name = filename.replace('/', '_').replace('.', '_')
    history_key = f"execution_history_{safe_name}"

    history = await memory.get_memory(history_key, "execution_history")

    if history:
        print(f"\n=== Execution History for {filename} ===")
        for entry in history[-10:]:  # Last 10 executions
            status = "✅" if entry['success'] else "❌"
            print(f"{status} {entry['tool']}: {entry['duration_ms']}ms")
            if entry.get('error'):
                print(f"   Error: {entry['error']}")

# Usage
asyncio.run(analyze_file_history("auth.py"))
```

### Custom Memory Storage

You can store custom memories for your workflows:

```python
import asyncio
from claude_hooks.lib.memory_client import get_memory_client

async def store_custom_memory():
    memory = get_memory_client()

    # Store a custom pattern
    await memory.store_memory(
        key="api_integration_pattern",
        value={
            "service": "Stripe",
            "best_practice": "Always validate webhooks",
            "example_file": "payments/stripe_webhook.py",
            "dependencies": ["stripe", "hmac"]
        },
        category="patterns",
        metadata={"created_by": "user", "project": "ecommerce"}
    )

    print("✅ Custom pattern stored!")

asyncio.run(store_custom_memory())
```

## Configuration Options

### Environment Variables

All configuration is in `.env`:

```bash
# Core memory settings
ENABLE_MEMORY_CLIENT=true              # Enable/disable memory system
MEMORY_STORAGE_BACKEND=filesystem      # Backend type (filesystem only for now)
MEMORY_STORAGE_PATH=~/.claude/memory  # Where to store memories
MEMORY_ENABLE_FALLBACK=true           # Fallback to correlation manager

# Intent extraction
ENABLE_INTENT_EXTRACTION=true         # Use LLM for intent (recommended)
                                       # false = keyword-based (faster but less accurate)

# Token budget
MEMORY_MAX_TOKENS=5000                # Maximum tokens for injected context
                                       # Reduce if prompts are too long
                                       # Increase for more context (up to ~10000)

# Context editing (Anthropic API integration)
ENABLE_CONTEXT_EDITING=true
ANTHROPIC_BETA_HEADER=anthropic-beta: context-management-2025-06-27
```

### Performance Tuning

**If prompts are too slow** (>100ms overhead):

1. Disable LLM-based intent extraction:
```bash
ENABLE_INTENT_EXTRACTION=false  # Uses keyword-based (1-5ms vs 100-200ms)
```

2. Reduce token budget:
```bash
MEMORY_MAX_TOKENS=2000  # Less context, faster processing
```

**If context is insufficient**:

1. Increase token budget:
```bash
MEMORY_MAX_TOKENS=8000  # More context (but slower)
```

2. Enable LLM-based intent extraction (if disabled):
```bash
ENABLE_INTENT_EXTRACTION=true  # More accurate intent detection
```

## Monitoring & Debugging

### Check Memory Status

```bash
# View memory directory size
du -sh ~/.claude/memory/
du -sh ~/.claude/memory/*/

# Count memories by category
find ~/.claude/memory -name "*.json" | cut -d'/' -f6 | sort | uniq -c

# View recent memories
ls -lt ~/.claude/memory/*/*.json | head -20
```

### View Hook Logs

```bash
# If hooks create logs (check hook implementations)
tail -f ~/.claude/hooks/logs/pre_prompt_submit.log
tail -f ~/.claude/hooks/logs/post_tool_use.log
tail -f ~/.claude/hooks/logs/workspace_change.log
```

### Test Intent Extraction

```bash
# Test with your own prompts
python3 << 'EOF'
import asyncio
from claude_hooks.lib.intent_extractor import extract_intent

async def test():
    prompts = [
        "Help me implement JWT authentication",
        "Fix the database connection error",
        "Refactor auth.py to use async/await"
    ]

    for prompt in prompts:
        intent = await extract_intent(prompt)
        print(f"\nPrompt: {prompt}")
        print(f"  Task Type: {intent.task_type}")
        print(f"  Entities: {intent.entities}")
        print(f"  Operations: {intent.operations}")
        print(f"  Confidence: {intent.confidence}")

asyncio.run(test())
EOF
```

### Run Tests

```bash
# Run all memory management tests
pytest tests/claude_hooks/ -v

# Run specific test files
pytest tests/claude_hooks/test_memory_client.py -v
pytest tests/claude_hooks/test_intent_extractor.py -v
pytest tests/claude_hooks/test_hooks_integration.py -v

# Run with coverage
pytest tests/claude_hooks/ --cov=claude_hooks.lib --cov-report=html
```

## Troubleshooting

### Issue: No context is being injected

**Symptoms**: Prompts look unchanged, no "CONTEXT FROM MEMORY" section

**Diagnosis**:
```bash
# Check if memory client is enabled
grep ENABLE_MEMORY_CLIENT .env

# Check if hooks are installed
ls -la ~/.claude/hooks/*.py

# Test memory client
python3 -c "from claude_hooks.lib.memory_client import get_memory_client; print('✅ Works')"
```

**Fix**:
1. Ensure `ENABLE_MEMORY_CLIENT=true` in `.env`
2. Restart Claude Code
3. Check hook permissions: `chmod +x ~/.claude/hooks/*.py`

### Issue: Prompts are very slow

**Symptoms**: 500ms+ delay before prompt submission

**Diagnosis**:
```bash
# Check if LLM-based intent extraction is enabled
grep ENABLE_INTENT_EXTRACTION .env

# Check token budget
grep MEMORY_MAX_TOKENS .env
```

**Fix**:
1. Disable LLM intent extraction: `ENABLE_INTENT_EXTRACTION=false`
2. Reduce token budget: `MEMORY_MAX_TOKENS=2000`
3. Clear old memories: `rm -rf ~/.claude/memory/workspace_events/*`

### Issue: Memory not persisting across sessions

**Symptoms**: Context resets every time Claude Code restarts

**Diagnosis**:
```bash
# Check storage path
ls -la ~/.claude/memory/

# Check permissions
ls -ld ~/.claude/memory/
```

**Fix**:
1. Ensure directory exists: `mkdir -p ~/.claude/memory`
2. Fix permissions: `chmod -R 755 ~/.claude/memory`
3. Check disk space: `df -h ~/.claude/`

### Issue: Irrelevant context being injected

**Symptoms**: Context doesn't match your prompt

**Diagnosis**:
```bash
# Test intent extraction with your prompt
python3 << 'EOF'
import asyncio
from claude_hooks.lib.intent_extractor import extract_intent

async def test():
    intent = await extract_intent("YOUR_PROMPT_HERE")
    print(f"Task: {intent.task_type}")
    print(f"Entities: {intent.entities}")
    print(f"Files: {intent.files}")

asyncio.run(test())
EOF
```

**Fix**:
1. Enable LLM-based intent: `ENABLE_INTENT_EXTRACTION=true`
2. Clear stale memories: `rm ~/.claude/memory/patterns/*.json`
3. Reduce token budget to prioritize top matches: `MEMORY_MAX_TOKENS=3000`

### Issue: Hook errors in logs

**Symptoms**: Errors in hook execution logs

**Diagnosis**:
```bash
# Check Python environment
python3 --version  # Should be 3.8+

# Check dependencies
pip3 list | grep -E "(aiofiles|langextract)"

# Test imports
python3 -c "import aiofiles; import langextract; print('✅ Dependencies OK')"
```

**Fix**:
1. Install dependencies: `pip3 install -r requirements.txt`
2. Check Python path: `which python3`
3. Reinstall hooks: Copy from `claude_hooks/` to `~/.claude/hooks/`

## Migration from Correlation Manager

If you were using the old correlation manager, migrate to the new memory system:

```bash
# Preview migration (dry run)
python3 claude_hooks/lib/migrate_to_memory.py --dry-run --verbose

# Perform migration with backup
python3 claude_hooks/lib/migrate_to_memory.py --backup --validate

# Verify migration
python3 << 'EOF'
import asyncio
from claude_hooks.lib.memory_client import get_memory_client

async def verify():
    memory = get_memory_client()
    categories = await memory.list_categories()

    for category in categories:
        keys = await memory.list_memory(category)
        print(f"{category}: {len(keys)} keys")

asyncio.run(verify())
EOF
```

**Migration converts**:
- `~/.claude/hooks/.state/*.json` → `~/.claude/memory/{category}/{key}.json`
- Correlation context → `routing/correlation_*`
- Agent state → `routing/agent_state_*`
- Generic state → `workspace/legacy_*`

## Best Practices

### 1. Keep Memory Clean

Periodically clean up old workspace events:
```bash
# Remove events older than 7 days
find ~/.claude/memory/workspace_events/ -name "*.json" -mtime +7 -delete
```

### 2. Monitor Memory Size

```bash
# Check total size
du -sh ~/.claude/memory/

# Alert if >100MB
SIZE=$(du -sm ~/.claude/memory/ | cut -f1)
if [ $SIZE -gt 100 ]; then
    echo "⚠️  Memory directory is large: ${SIZE}MB"
fi
```

### 3. Use Descriptive Keys

When storing custom memories:
```python
# Good: Descriptive keys
await memory.store_memory("stripe_webhook_validation_pattern", ...)
await memory.store_memory("jwt_token_refresh_implementation", ...)

# Bad: Generic keys
await memory.store_memory("pattern1", ...)
await memory.store_memory("data", ...)
```

### 4. Leverage Metadata

Always include metadata for searchability:
```python
await memory.store_memory(
    key="api_pattern",
    value={...},
    category="patterns",
    metadata={
        "service": "Stripe",
        "version": "2023-10-16",
        "author": "team_backend",
        "project": "payment_service"
    }
)
```

### 5. Test Intent Extraction

Before relying on automatic intent extraction, test it:
```python
# Test with your common prompts
prompts = [
    "Implement user registration",
    "Fix the API timeout issue",
    "Refactor database queries"
]

for prompt in prompts:
    intent = await extract_intent(prompt)
    # Verify task_type, entities, operations are correct
```

## Performance Benchmarks

**Expected Performance**:
- Pre-prompt hook: <100ms overhead
- Post-tool hook: <50ms overhead
- Workspace-change hook: <20ms per file
- Intent extraction (LLM): 100-200ms
- Intent extraction (keyword): 1-5ms

**Token Savings**:
- Without memory management: 20K+ tokens per prompt
- With memory management: 2-5K tokens per prompt
- **Savings: 75-80%**

## API Reference

See docstrings in:
- `claude_hooks/lib/memory_client.py` - Memory Client API
- `claude_hooks/lib/intent_extractor.py` - Intent Extraction API

## Further Reading

- **Architecture**: `docs/planning/HOOK_MEMORY_MANAGEMENT_INTEGRATION.md`
- **Implementation Status**: `docs/planning/HOOK_MEMORY_IMPLEMENTATION_STATUS.md`
- **CLAUDE.md**: Main documentation with memory management section
- **Anthropic Context Management**: https://claude.com/blog/context-management

## Support

If you encounter issues:

1. Check this guide's troubleshooting section
2. Run comprehensive tests: `pytest tests/claude_hooks/ -v`
3. Review implementation status: `docs/planning/HOOK_MEMORY_IMPLEMENTATION_STATUS.md`
4. Check logs (if hooks create them)

---

**Last Updated**: 2025-11-06
**Version**: 1.0.0
**Status**: Production Ready
