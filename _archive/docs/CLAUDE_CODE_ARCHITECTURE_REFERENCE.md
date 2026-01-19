# Claude Code Architecture Reference

**Purpose**: Prevent common architectural misunderstandings
**Last Updated**: 2025-10-24
**Source**: Official Claude Code Documentation

---

## ⚠️ Common Misconceptions (AVOID THESE)

### ❌ WRONG: "Subagents are Python classes that need implementation"
**Reality**: Subagents are **Markdown files with YAML frontmatter**, not Python code.

### ❌ WRONG: "We need to create executor classes to run agents"
**Reality**: Claude Code's **Task tool** executes agents directly from their Markdown definitions.

### ❌ WRONG: "Agents need entry point files like `polymorphic_agent.py`"
**Reality**: The `.md` file in `~/.claude/agents/` **IS** the complete implementation.

### ❌ WRONG: "To add logging, modify the agent's Python code"
**Reality**: Use **Claude Code hooks** that fire during agent execution lifecycle.

---

## ✅ Correct Architecture

### Subagent Definition

**Format**: Markdown file with YAML frontmatter
**Locations**:
- **User-level**: `~/.claude/agents/*.md` (highest priority)
- **Project-level**: `.claude/agents/*.md`

**Structure**:
```markdown
---
name: agent-name
description: Agent description
color: purple
category: workflow_coordinator
aliases: [polly, poly]
---

## System Prompt Content

This Markdown content becomes the agent's system prompt.
It defines how the agent behaves, what it knows, and how it responds.
```

**Key Points**:
- The YAML frontmatter defines metadata (name, description, color, etc.)
- The Markdown content **IS** the agent's instructions/prompt
- No Python code required!
- Agents are **AI personalities**, not code classes

---

### Agent Execution Flow

```
User Request
    ↓
UserPromptSubmit Hook (detects which agent to use)
    ↓
Claude Code Task Tool (loads agent .md file)
    ↓
PreToolUse Hook (fires before agent starts)
    ↓
Agent Executes (with system prompt from Markdown)
    ↓
PostToolUse Hook (fires after agent completes)
    ↓
SubagentStop Hook (fires when agent finishes responding)
    ↓
Result Returned to User
```

**Execution Details**:
1. Claude Code **reads the .md file**
2. Uses **YAML frontmatter** for configuration
3. Uses **Markdown content** as system prompt
4. Executes agent in **isolated context** (own conversation window)
5. Returns results to main conversation

---

### Hooks: The Integration Layer

**Purpose**: Inject behavior at specific points in execution lifecycle

**Available Hooks for Agent Observability**:

| Hook | When It Fires | Use For |
|------|--------------|---------|
| **UserPromptSubmit** | Before processing user input | Agent detection, routing decisions |
| **PreToolUse** (Task) | Before agent starts executing | Log execution start, generate execution ID |
| **PostToolUse** (Task) | After agent completes | Log execution end, capture results |
| **SubagentStop** | When agent finishes responding | Log completion, calculate duration |

**Hook Configuration** (`~/.claude/settings.json`):
```json
{
  "hooks": {
    "SubagentStop": [{
      "hooks": [{
        "type": "command",
        "command": "~/.claude/hooks/subagent-stop-logging.sh",
        "timeout": 2000
      }]
    }],
    "PreToolUse": [{
      "tools": ["Task"],
      "hooks": [{
        "type": "command",
        "command": "~/.claude/hooks/pre-task-use-logging.sh",
        "timeout": 2000
      }]
    }]
  }
}
```

**Key Points**:
- Hooks are **shell scripts** (can call Python if needed)
- They receive JSON input via stdin
- They should pass through input (unchanged or modified)
- Hooks run **synchronously** (block execution)
- Use timeout to prevent hanging

---

## OmniClaude Agent Observability Architecture

### The Problem We Solved

**Original Issue**: Agent execution tables exist but contain no data

**Root Cause**: Infrastructure (database, skills, Kafka) ready but never invoked

**Solution**: Use Claude Code hooks to call our logging skills

---

### Integration Pattern

```
┌──────────────────────────────────────────────────────────────┐
│ CLAUDE CODE HOOKS (Execution Lifecycle)                      │
│ - UserPromptSubmit: Detect agent, log routing decision       │
│ - PreToolUse (Task): Log execution start                     │
│ - SubagentStop: Log execution complete                       │
└──────────────────────┬───────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────┐
│ LOGGING SKILLS (in ~/.claude/skills/)                        │
│ - log-routing-decision → agent_routing_decisions table       │
│ - log-execution → agent_execution_logs table                 │
│ - log-agent-action → agent_actions table                     │
└──────────────────────┬───────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────┐
│ KAFKA EVENT BUS (async processing)                           │
│ - Topics: agent.routing.decisions, agent.execution.logs      │
│ - Consumer: agents/kafka/consumer.py                         │
└──────────────────────┬───────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────┐
│ POSTGRESQL DATABASE (omninode_bridge)                        │
│ - agent_routing_decisions (routing history)                  │
│ - agent_execution_logs (execution metrics)                   │
│ - agent_actions (tool invocations)                           │
│ - agent_detection_failures (learning data)                   │
│ - agent_transformation_events (polymorphic transforms)       │
└──────────────────────────────────────────────────────────────┘
```

---

### Skills Architecture

**Location**: `~/.claude/skills/`

**Format**: Directory per skill with execution scripts

**Example**: `skills/log-execution/`
```
log-execution/
├── skill.md                    # Skill description
├── execute.py                  # Direct database insert
├── execute_kafka.py            # Send to Kafka topic
└── execute_unified.py          # Try Kafka, fallback to DB
```

**Key Points**:
- Skills are **callable from hooks** (shell scripts call Python)
- Each skill has 3 execution modes (direct/kafka/unified)
- Use `execute_unified.py` for best reliability
- Skills are synchronous (return after completion)

---

## Reference: Agent Files in OmniClaude

### User-Level Agents (`~/.claude/agents/`)

```bash
$ ls -la ~/.claude/agents/*.md
polymorphic-agent.md           # Main workflow orchestrator (Polly)
```

### Project-Level Agents (`.claude/agents/`)

```bash
$ ls -la .claude/agents/*.md
AGENT-PARALLEL-DISPATCHER.md   # Parallel execution coordinator
```

### Agent Definition Registry (`agents/definitions/`)

**NOTE**: These are **reference YAML files**, NOT executable agents!

```bash
$ ls -la agents/definitions/*.yaml
polymorphic-agent.yaml         # YAML reference (NOT used by Claude Code)
```

**Common Confusion**:
- `agents/definitions/polymorphic-agent.yaml` is a **reference document**
- `~/.claude/agents/polymorphic-agent.md` is the **actual executable agent**
- Claude Code **ONLY reads .md files** from `~/.claude/agents/`

---

## Quick Reference: When to Use What

### "I want to create a new agent"
✅ **DO**: Create `.md` file in `~/.claude/agents/` with YAML frontmatter + Markdown prompt
❌ **DON'T**: Create Python class or executor

### "I want to add logging to agent execution"
✅ **DO**: Create hooks in `~/.claude/hooks/` that call logging skills
❌ **DON'T**: Try to modify agent's "source code" (there isn't any)

### "I want to change agent behavior"
✅ **DO**: Edit the Markdown system prompt in the `.md` file
❌ **DON'T**: Look for Python files to modify

### "I want to track agent metrics"
✅ **DO**: Use hooks (PreToolUse, PostToolUse, SubagentStop) to capture data
❌ **DON'T**: Add instrumentation code (agents are prompts, not code)

### "I want agents to use new tools"
✅ **DO**: Add tools to YAML frontmatter `allowed_tools: [Read, Write, Bash]`
❌ **DON'T**: Import libraries or create tool classes

---

## Debugging Agent Issues

### "Agent not executing"
1. ✅ Check agent exists: `ls -la ~/.claude/agents/{agent-name}.md`
2. ✅ Verify YAML frontmatter is valid
3. ✅ Check Claude Code settings for hooks that might block
4. ❌ Don't look for Python import errors (there is no Python)

### "Agent behavior is wrong"
1. ✅ Read the Markdown system prompt in the `.md` file
2. ✅ Check for conflicting instructions in prompt
3. ✅ Verify agent has access to required tools
4. ❌ Don't debug Python code (there is no code to debug)

### "Can't track agent execution"
1. ✅ Check hooks are configured in `~/.claude/settings.json`
2. ✅ Test hooks manually: `echo '{}' | ~/.claude/hooks/subagent-stop-logging.sh`
3. ✅ Verify Kafka consumer running: `docker ps | grep kafka`
4. ❌ Don't add logging to agent Python files (they don't exist)

---

## Official Documentation Links

- **Subagents**: https://docs.claude.com/en/docs/claude-code/sub-agents.md
- **Hooks**: https://docs.claude.com/en/docs/claude-code/hooks.md
- **Skills**: https://docs.claude.com/en/docs/claude-code/skills.md
- **MCP**: https://docs.claude.com/en/docs/claude-code/mcp.md

---

## Key Takeaways

1. **Agents = Markdown files** (YAML frontmatter + system prompt)
2. **Execution = Task tool** (built into Claude Code, loads .md files)
3. **Integration = Hooks** (shell scripts that fire at lifecycle points)
4. **Logging = Skills** (callable utilities invoked by hooks)
5. **No Python required** (agents are AI personalities, not code classes)

---

## When This Document Would Have Helped

**Original Mistake**: Spent hours analyzing "missing Python executors" for polymorphic agent

**What This Doc Would Have Shown**:
- ✅ `polymorphic-agent.md` IS the complete implementation
- ✅ Use hooks for logging, not Python code modifications
- ✅ Agents execute via Task tool, not custom executors
- ✅ Integration happens at hook level, not code level

**Time Saved**: ~4 hours of investigation + incorrect implementation planning

---

**Last Reviewed**: 2025-10-24
**Validated Against**: Claude Code official documentation
**Status**: ✅ Accurate and Complete
