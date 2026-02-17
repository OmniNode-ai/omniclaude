---
name: parallel-solve
description: Execute any task in parallel using polymorphic agents with requirements gathering
version: 1.0.0
category: workflow
tags:
  - parallel
  - automation
  - polymorphic
  - multi-agent
author: OmniClaude Team
---

# Parallel Solve

## Overview

Smart context-aware task executor. Gathers requirements, plans sub-tasks, executes them in parallel via polymorphic agents, validates results, and reports.

**Announce at start:** "I'm using the parallel-solve skill to execute this task in parallel."

## Quick Start

```
/parallel-solve
```

The skill reads the current conversation context to determine what to work on. No arguments required.

## Dispatch Contracts (Execution-Critical)

**This section governs execution. Follow it exactly.**

You are an orchestrator. You coordinate polymorphic agents. You do NOT implement code yourself.

**Rule: NEVER call Edit(), Write(), or Bash(code-modifying) directly.**
**Rule: ALL Task() calls MUST use subagent_type="onex:polymorphic-agent". No exceptions.**
**Rule: NO git operations in spawned agents. Git is coordinator-only, user-approved only.**

### Phase 1: Requirements Gathering -- dispatch to polymorphic agent

Before execution, analyze scope:

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="Requirements gathering: analyze task scope",
  prompt="Analyze the task and produce a structured breakdown.

    Task: {task_description}
    Context: {conversation_context}

    Produce:
    1. Independent sub-tasks (can run in parallel)
    2. Sequential dependencies (must run in order)
    3. Files/modules involved per sub-task
    4. Validation criteria per sub-task
    5. Risk assessment

    Return structured JSON:
    {
      \"parallel_tasks\": [{\"id\": \"t1\", \"description\": \"...\", \"files\": [...], \"validation\": \"...\"}],
      \"sequential_tasks\": [{\"id\": \"t2\", \"depends_on\": [\"t1\"], \"description\": \"...\"}],
      \"risks\": [\"...\"]
    }"
)
```

### Phase 2: Parallel Execution -- dispatch N polymorphic agents

For each independent task from requirements:

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="{task_type}: {description}",
  prompt="**Task**: {detailed_description}
    **Context**: {context}
    **Actions**: {numbered_list}
    **Success Criteria**: {validation}
    **DO NOT**: Run git commands."
)
```

Dispatch ALL independent tasks in a single message. Wait before dispatching dependents.

### Phase 3: Quality Validation -- dispatch to polymorphic agent

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="Quality validation: verify changes",
  prompt="Validate changes. Run linting, type checking, tests as applicable.
    Files modified: {file_list}
    Report: pass/fail per check, issues found."
)
```

### Phase 4: Refactor (if needed, max 3 attempts per task)

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="Refactor: fix quality issues (attempt {n}/3)",
  prompt="Fix quality issues: {issues}. Do NOT commit."
)
```

### Phase 5: User Approval -- NO dispatch

Present results. Ask before ANY git operations. NEVER auto-commit.

## Task Classification

**By Type**:
- **Bug Fix**: Fixing errors, crashes, incorrect behavior
- **New Feature**: Building new functionality from scratch
- **Enhancement**: Improving existing features
- **Optimization**: Performance, cost, or efficiency improvements
- **Refactoring**: Code quality, structure, or maintainability improvements
- **Documentation**: Adding or updating documentation
- **Configuration**: Setup, deployment, or infrastructure changes

**By Priority**:
- **Critical** (MUST do): Blockers, security issues, data loss risks, broken builds
- **High Priority** (SHOULD do): Important bugs, key features, significant optimizations
- **Medium Priority** (CAN do): Nice-to-have features, moderate improvements, refactoring
- **Low Priority** (NICE to have): Code style, minor optimizations, documentation polish

## Detailed Orchestration

Full orchestration logic (execution patterns, refactor tracking, examples, reporting phases)
is documented in `prompt.md`. The dispatch contracts above are sufficient to execute the skill.
Load `prompt.md` only if you need reference details for execution patterns, refactor tracking,
or edge case handling.

## See Also

- `ticket-pipeline` skill (structured ticket-based pipeline)
- `ticket-work` skill (single-ticket implementation)
- `local-review` skill (code review)
