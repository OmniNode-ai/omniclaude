---
description: Multi-agent coordination — parallel debugging, parallel building, and sequential review workflows
mode: full
version: 1.0.0
level: advanced
debug: false
category: workflow
tags:
  - multi-agent
  - parallel
  - subagent
  - dispatch
  - coordination
author: OmniClaude Team
composable: true
args:
  - name: --mode
    description: "Mode: parallel-debug, parallel-build, or sequential-with-review"
    required: true
  - name: --tasks
    description: "Task descriptions or file paths (comma-separated for parallel modes)"
    required: false
  - name: --max-agents
    description: "Maximum concurrent agents (default: 5)"
    required: false
---

# Multi-Agent

## Overview

Multi-agent coordination with three modes:
- **parallel-debug**: Dispatch independent failures to parallel agents for investigation
- **parallel-build**: Dispatch independent implementation tasks to parallel agents
- **sequential-with-review**: Chain agents sequentially with human review between each

**Announce at start:** "I'm using the multi-agent skill in {mode} mode."

---

## parallel-debug Mode

<!-- Absorbed from dispatching-parallel-agents -->

When you have multiple unrelated failures (different test files, different subsystems, different bugs), investigating them sequentially wastes time. Each investigation is independent and can happen in parallel.

**Core principle:** Dispatch one agent per independent problem domain. Let them work concurrently.

### When to Use parallel-debug

**Use when:**
- 3+ test files failing with different root causes
- Multiple subsystems broken independently
- Each problem can be understood without context from others
- No shared state between investigations

**Don't use when:**
- Failures are related (fix one might fix others)
- Need to understand full system state
- Agents would interfere with each other (editing same files, using same resources)

### The Pattern

#### 1. Identify Independent Domains

Group failures by what's broken:
- File A tests: Tool approval flow
- File B tests: Batch completion behavior
- File C tests: Abort functionality

Each domain is independent - fixing tool approval doesn't affect abort tests.

#### 2. Create Focused Agent Tasks

Each agent gets:
- **Specific scope:** One test file or subsystem
- **Clear goal:** Make these tests pass
- **Constraints:** Don't change other code
- **Expected output:** Summary of what you found and fixed

#### 3. Dispatch in Parallel

```typescript
// In Claude Code / AI environment
Task("Fix agent-tool-abort.test.ts failures")
Task("Fix batch-completion-behavior.test.ts failures")
Task("Fix tool-approval-race-conditions.test.ts failures")
// All three run concurrently
```

#### 4. Review and Integrate

When agents return:
- Read each summary
- Verify fixes don't conflict
- Run full test suite
- Integrate all changes

#### 5. Reconcile Results

When agents return outputs that overlap (modify the same fields), use geometric conflict classification to merge intelligently.

##### 5.1 Import the Reconciliation Helper

Within hook scripts, the plugin lib directory (`plugins/onex/hooks/lib/`) is already on `sys.path`, so the import is a bare module name:

```python
from reconcile_agent_outputs import reconcile_outputs
```

If importing from tests or other code outside the plugin context, add the plugin lib to `sys.path` first:

```python
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
while not (root / "pyproject.toml").exists():
    root = root.parent
sys.path.insert(0, str(root / "plugins" / "onex" / "hooks" / "lib"))

from reconcile_agent_outputs import reconcile_outputs
```

##### 5.2 Gather Agent Outputs

```python
agent_outputs = {
    "agent-1": agent_1_result,
    "agent-2": agent_2_result,
    "agent-3": agent_3_result,
}
base_values = original_state  # state before agents ran
```

##### 5.3 Run Reconciliation

```python
result = reconcile_outputs(base_values, agent_outputs)
```

##### 5.4 Handle the Result

**If `result.requires_approval` is False**: Apply `result.merged_values` directly. To reconstruct a nested structure:

```python
from reconcile_agent_outputs import unflatten_paths

nested = unflatten_paths(result.merged_values)
```

**If `result.requires_approval` is True**: STOP. Use `AskUserQuestion` to present each approval-required field with the competing values from each agent. Do NOT attempt to resolve these yourself.

##### 5.5 Rules

- **Never hand-merge approval-required fields.** The helper returns `chosen_value=None` for these.
- **Always surface the exact competing values** and which agent produced them.
- **Apply only `result.merged_values`** from the helper. Do not construct merge results manually.
- **Review optional-review fields** (`result.optional_review_fields`) if time permits.

### Agent Prompt Structure (parallel-debug)

Good agent prompts are:
1. **Focused** - One clear problem domain
2. **Self-contained** - All context needed to understand the problem
3. **Specific about output** - What should the agent return?

```markdown
Fix the 3 failing tests in src/agents/agent-tool-abort.test.ts:

1. "should abort tool with partial output capture" - expects 'interrupted at' in message
2. "should handle mixed completed and aborted tools" - fast tool aborted instead of completed
3. "should properly track pendingToolCount" - expects 3 results but gets 0

These are timing/race condition issues. Your task:

1. Read the test file and understand what each test verifies
2. Identify root cause - timing issues or actual bugs?
3. Fix by:
   - Replacing arbitrary timeouts with event-based waiting
   - Fixing bugs in abort implementation if found
   - Adjusting test expectations if testing changed behavior

Do NOT just increase timeouts - find the real issue.

Return: Summary of what you found and what you fixed.
```

### Common Mistakes (parallel-debug)

- **Too broad:** "Fix all the tests" - agent gets lost
- **No context:** "Fix the race condition" - agent doesn't know where
- **No constraints:** Agent might refactor everything
- **Vague output:** "Fix it" - you don't know what changed

---

## parallel-build Mode

<!-- Absorbed from parallel-solve -->

Smart context-aware task executor. Gathers requirements, plans sub-tasks, executes them in parallel via polymorphic agents, validates results, and reports.

### Dispatch Contracts (Execution-Critical)

**This section governs execution. Follow it exactly.**

You are an orchestrator. You coordinate polymorphic agents. You do NOT implement code yourself.

**Rule: NEVER call Edit(), Write(), or Bash(code-modifying) directly.**
**Rule: ALL Task() calls MUST use subagent_type="onex:polymorphic-agent". No exceptions.**
**Rule: NO git operations in spawned agents. Git is coordinator-only, user-approved only.**

#### Phase 1: Requirements Gathering -- dispatch to polymorphic agent

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

#### Phase 2: Parallel Execution -- dispatch N polymorphic agents

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

#### Phase 3: Quality Validation -- dispatch to polymorphic agent

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="Quality validation: verify changes",
  prompt="Validate changes. Run linting, type checking, tests as applicable.
    Files modified: {file_list}
    Report: pass/fail per check, issues found."
)
```

#### Phase 4: Refactor (if needed, max 3 attempts per task)

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="Refactor: fix quality issues (attempt {n}/3)",
  prompt="Fix quality issues: {issues}. Do NOT commit."
)
```

#### Phase 5: User Approval -- NO dispatch

Present results. Show:
- `git status --porcelain` output (exact list of changed files)
- Test results summary (from Phase 3)
- Proposed commit message

Ask the user: "Approve committing these changes and creating a PR with automerge enabled? (yes/no)"

If user says no: stop. All changes remain on disk.
If user says yes: proceed to Phase 6.

#### Phase 6: Commit, Push, PR + Automerge (functional expansion — runs after user approves Phase 5)

> **Prerequisite:** Must be on a named branch (not detached HEAD) inside the target git repo root.

```bash
# 0. Auth + detached HEAD guard
gh auth status || { echo "ERROR: not logged into GitHub CLI"; exit 1; }
HEAD_BRANCH=$(git branch --show-current)
test -n "$HEAD_BRANCH" || { echo "ERROR: detached HEAD — cannot create PR"; exit 1; }

# 1. Show and stage changes (user already approved in Phase 5)
git status --porcelain
git add -A

# 2. Commit
git commit -m "feat: <concise description from Phase 1 task summary>"

# 3. Resolve repo and push
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
git push -u origin "$HEAD_BRANCH"

# 4. Create PR — resolve number via gh pr view on the PR URL (deterministic anchor)
PR_URL=$(gh pr create \
  --title "<commit message title>" \
  --repo "$REPO" \
  --body "$(cat <<'EOF'
## Summary
<bullet points from Phase 1 requirements>

## Test Plan
- CI must pass
- Changes validated by Phase 3 quality checks
EOF
)")
echo "$PR_URL" | grep -qE 'https://github\.com/.*/pull/[0-9]+' \
  || { echo "ERROR: PR_URL doesn't look like a PR URL: $PR_URL"; exit 1; }
PR_NUMBER=$(gh pr view "$PR_URL" --json number -q .number)
test -n "$PR_NUMBER" || { echo "ERROR: failed to resolve PR number from: $PR_URL"; exit 1; }

# 5. Enable automerge
gh pr merge --auto --squash "$PR_NUMBER" --repo "$REPO"

echo "PR #$PR_NUMBER: $PR_URL"
echo "Automerge armed. GitHub merges when all branch protection requirements are satisfied."
```

**Rule**: Phase 6 is git-only coordinator work. Do NOT dispatch to polymorphic agents.

### Task Classification

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

### Detailed Orchestration

Full orchestration logic (execution patterns, refactor tracking, examples, reporting phases)
is documented in `prompt.md`. The dispatch contracts above are sufficient to execute the skill.
Load `prompt.md` only if you need reference details for execution patterns, refactor tracking,
or edge case handling.

---

## sequential-with-review Mode

<!-- Absorbed from subagent-driven-development -->

Execute plan by dispatching fresh subagent per task, with code review after each.

**Core principle:** Fresh subagent per task + review between tasks = high quality, fast iteration

### When to Use sequential-with-review

- Staying in this session (no context switch)
- Tasks are mostly independent
- Want continuous progress with quality gates

**When NOT to use:**
- Tasks are tightly coupled (manual execution better)
- Plan needs revision (brainstorm first)

### The Process

#### 1. Load Plan

Read plan file, create TodoWrite with all tasks.

#### 2. Execute Task with Subagent

For each task:

**Dispatch fresh subagent:**
```
Task tool (general-purpose):
  description: "Implement Task N: [task name]"
  prompt: |
    You are implementing Task N from [plan-file].

    Read that task carefully. Your job is to:
    1. Implement exactly what the task specifies
    2. Write tests (following TDD if task says to)
    3. Verify implementation works
    4. Commit your work
    5. Report back

    Work from: [directory]

    Report: What you implemented, what you tested, test results, files changed, any issues
```

**Subagent reports back** with summary of work.

#### 3. Review Subagent's Work

**Dispatch code-reviewer subagent:**
```
Task tool (code-reviewer):
  Use template at ${CLAUDE_PLUGIN_ROOT}/skills/requesting-code-review/code-reviewer.md

  WHAT_WAS_IMPLEMENTED: [from subagent's report]
  PLAN_OR_REQUIREMENTS: Task N from [plan-file]
  BASE_SHA: [commit before task]
  HEAD_SHA: [current commit]
  DESCRIPTION: [task summary]
```

**Code reviewer returns:** Strengths, Issues (Critical/Important/Minor), Assessment

#### 4. Apply Review Feedback

**If issues found:**
- Fix Critical issues immediately
- Fix Important issues before next task
- Note Minor issues

**Dispatch follow-up subagent if needed:**
```
"Fix issues from code review: [list issues]"
```

#### 5. Mark Complete, Next Task

- Mark task as completed in TodoWrite
- Move to next task
- Repeat steps 2-5

#### 6. Final Review

After all tasks complete, dispatch final code-reviewer:
- Reviews entire implementation
- Checks all plan requirements met
- Validates overall architecture

#### 7. Complete Development

After final review passes:
- Announce: "I'm using the finishing-a-development-branch skill to complete this work."
- **REQUIRED SUB-SKILL:** Use ${CLAUDE_PLUGIN_ROOT}/skills/finishing-a-development-branch
- Follow that skill to verify tests, present options, execute choice

### Red Flags (sequential-with-review)

**Never:**
- Skip code review between tasks
- Proceed with unfixed Critical issues
- Dispatch multiple implementation subagents in parallel (conflicts)
- Implement without reading plan task

**If subagent fails task:**
- Dispatch fix subagent with specific instructions
- Don't try to fix manually (context pollution)

### Canonical Use Cases

#### Skill Development (Primary Use Case)

Skill development -- editing `SKILL.md`, `prompt.md`, skill helpers -- is a primary use case. Skill sessions are high-token and consistently exhaust the main context window when done inline.

**Pattern**:
```
Skill(skill="onex:multi_agent --mode sequential-with-review")
```

Then break the skill work into tasks:
1. Task: Read and understand existing skill files
2. Task: Edit SKILL.md with new section
3. Task: Edit prompt.md with new behavior
4. Task: Run verification
5. Task: Commit and report

---

## Integration

**Required workflow skills:**
- **design-to-plan** - Creates plans that sequential-with-review executes
- **requesting-code-review** - Review after each task (sequential-with-review Step 3)
- **finishing-a-development-branch** - Complete development after all tasks (sequential-with-review Step 7)

## See Also

- `ticket-pipeline` skill (structured ticket-based pipeline)
- `ticket-work` skill (single-ticket implementation)
- `local-review` skill (code review)
