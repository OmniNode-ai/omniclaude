# Polymorphic Agents - Quick Reference Card

## 🚀 **You're Already Using Them!**

Every prompt automatically goes through agent detection. **No setup needed!**

---

## Quick Usage

### Method 1: Just Ask (AI-Powered) ✨

```
help me write pytest tests
→ agent-testing activated

debug this memory leak
→ agent-debug activated

implement user authentication
→ agent-code-generator activated
```

**Speed**: ~2.5s | **Accuracy**: 95%

---

### Method 2: Explicit Invocation 🎯

```
@agent-testing write unit tests for api.py
@agent-debug investigate performance issue
@agent-workflow-coordinator plan migration
```

**Speed**: <2ms | **Accuracy**: 100%

---

### Method 3: Use Keywords ⚡

```
write pytest tests → agent-testing
debug error → agent-debug
parallel process → agent-parallel-dispatcher
```

**Speed**: ~5ms | **Accuracy**: 85%

---

## Available Agents

| Agent | Use For | Keywords |
|-------|---------|----------|
| **agent-testing** | Writing tests, coverage | test, pytest, unittest, coverage |
| **agent-debug** | Debugging, troubleshooting | debug, error, bug, issue |
| **agent-code-generator** | Writing code, features | write, create, implement, build |
| **agent-workflow-coordinator** | Multi-step workflows | workflow, orchestrate, plan |
| **agent-parallel-dispatcher** | Parallel execution | parallel, concurrent, batch |

---

## Configuration

```bash
# Disable AI (faster, less accurate)
export ENABLE_AI_AGENT_SELECTION=false

# Change AI model
export AI_MODEL_PREFERENCE=5090  # RTX 5090 (default)

# Adjust confidence
export AI_AGENT_CONFIDENCE_THRESHOLD=0.8
```

---

## Troubleshooting

**Wrong agent selected?**
- Use explicit: `@agent-name your task`
- Or clearer keywords: "debug" not "check"

**Too slow?**
- Disable AI: `export ENABLE_AI_AGENT_SELECTION=false`
- Or use explicit invocation

**No agent detected?**
- Add trigger words: "test", "debug", "write"
- Check logs: `tail ~/.claude/hooks/hook-enhanced.log`

---

## Examples

### Writing Tests
```
@agent-testing write pytest tests for user_service.py
```

### Debugging
```
investigate why the database query is slow
```

### Building Features
```
@agent-code-generator create REST API for authentication
```

### Parallel Work
```
@agent-workflow-coordinator use two agents in parallel to:
- Agent 1: Write tests
- Agent 2: Write docs
```

---

## Checking Status

**In responses:**
Look for `🤖 [Agent Framework Context]` header

**In logs:**
```bash
tail -50 ~/.claude/hooks/hook-enhanced.log | grep "Agent detected"
```

**In database:**
```bash
psql -h localhost -p 5436 -U postgres -d omninode_bridge \
  -c "SELECT * FROM hook_events WHERE source='UserPromptSubmit' ORDER BY created_at DESC LIMIT 5;"
```

---

## Key Files

- **User Guide**: `HOW_TO_USE_POLYMORPHIC_AGENTS.md`
- **Testing**: `TESTING_README.md`
- **Test Plan**: `POLYMORPHIC_AGENT_TEST_PLAN.md`
- **Logs**: `~/.claude/hooks/hook-enhanced.log`

---

**Pro Tip**: The system learns from your patterns. The more you use it, the better it gets at selecting the right agent!
