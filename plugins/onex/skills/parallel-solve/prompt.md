# Parallel Solve Orchestration

You are executing parallel-solve. This defines the complete orchestration logic.

## Phase 1: Context Detection

Analyze the **current conversation context** to determine what needs to be done:

1. **Extract the Current Task**:
   - Identify what the user is asking you to work on
   - Look for the main task/objective described in recent messages
   - Extract any specific requirements or constraints mentioned
   - Understand if this is a bug fix, new feature, enhancement, optimization, or requirement

2. **Check Conversation History**:
   - Review recent messages for identified tasks or sub-tasks
   - Look for "TODO", "FIXME", "blocker", "critical", "enhancement", "feature", "optimize" mentions
   - Extract any prioritized task lists from previous analysis
   - Identify if test failures, errors, or new requirements were mentioned

3. **Understand the Task Context**:
   - What files/modules are involved?
   - What's the expected outcome?
   - Are there dependencies between sub-tasks?
   - What validation is needed?
   - Is this building something new or fixing something existing?

**DO NOT**: Check PRs, run CI checks, or look for external issues unless explicitly mentioned in the conversation.

## Phase 2: Requirements Gathering (Dispatch)

Before any execution, dispatch a polymorphic agent to analyze scope:

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

Use the structured output to plan Phase 3.

## Phase 3: Task Classification

Categorize detected tasks by priority and type:

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

## Phase 4: Parallel Execution Plan

Create a plan to execute tasks in parallel:

1. **Group tasks** by independence (can be done simultaneously)
2. **Identify dependencies** (must be done sequentially)
3. **Allocate to agents** based on specialization:
   - Import/dependency issues -> dependency agent
   - Test failures -> testing agent
   - Security issues -> security agent
   - Logic bugs -> debugging agent
   - New features -> feature development agent
   - Performance optimization -> performance agent
   - Infrastructure/deployment -> devops agent
   - Documentation -> documentation agent

4. **Define validation** for each task:
   - What tests should pass?
   - What checks should succeed?
   - How to verify completion?
   - What are the success criteria?

## Phase 5: Execute Plan

**CRITICAL REQUIREMENT: ALWAYS DISPATCH POLYMORPHIC AGENTS**

**DO NOT execute tasks yourself** - you MUST dispatch EVERY task to a **polymorphic-agent** using the Task tool.

### MANDATORY: subagent_type="onex:polymorphic-agent"

**EVERY Task tool call MUST use:**
```
subagent_type="onex:polymorphic-agent"
```

**NEVER use these subagent_types:**
- `general-purpose` - NO, use polymorphic-agent
- `Explore` - NO, use polymorphic-agent
- `Plan` - NO, use polymorphic-agent
- Any other type - NO, ALWAYS use polymorphic-agent

**WHY**: Polymorphic agents (pollys) have full ONEX capabilities, intelligence integration,
quality gates, and proper observability. Generic agents do not.

### WRONG (Running commands directly):
```
DO NOT DO THIS IN COORDINATOR:
- Edit: file.py to change code
- Write: file.py with new content
- Bash: running implementation commands directly
- Task with subagent_type="general-purpose"
- Task with subagent_type="Explore"

DO NOT DO THIS IN SPAWNED AGENTS:
- Bash: git add file.py && git commit
- Bash: git add . && git commit -m "message"
- Bash: git push
- Bash: git stash
- Any git operations (add, commit, push, stash, rebase, etc.)

Git operations are ONLY for the main coordinator when EXPLICITLY requested by the user,
not for spawned polymorphic agents.
```

### CORRECT (Dispatching to polymorphic-agent):

**For EACH task, you MUST call Task tool like this:**

**Example 1: Bug Fix**
```
Task(
  description="Fix import errors in reducer node",
  subagent_type="onex:polymorphic-agent",
  prompt="**Task**: Fix import errors in node_user_reducer.py

  **Context**: [Detailed problem description]

  **Required Actions**:
  1. Analyze import errors
  2. Fix missing imports
  3. Verify code compiles

  **Success Criteria**:
  - Code compiles without errors
  - All imports resolve correctly"
)
```

**Example 2: New Feature**
```
Task(
  description="Implement Docker optimization feature",
  subagent_type="onex:polymorphic-agent",
  prompt="**Task**: Add multi-stage Docker build optimization

  **Context**: Reduce Docker image size and build time

  **Required Actions**:
  1. Analyze current Dockerfile
  2. Implement multi-stage build
  3. Add build caching
  4. Test image builds correctly

  **Success Criteria**:
  - Image size reduced by >30%
  - Build time reduced by >20%
  - All services start correctly"
)
```

**Example 3: Enhancement**
```
Task(
  description="Enhance caching strategy",
  subagent_type="onex:polymorphic-agent",
  prompt="**Task**: Improve Valkey caching hit rate

  **Context**: Current hit rate is 60%, target 80%

  **Required Actions**:
  1. Analyze cache miss patterns
  2. Implement cache warming
  3. Optimize TTL values
  4. Add cache metrics

  **Success Criteria**:
  - Cache hit rate >80%
  - Cache metrics visible in Grafana"
)
```

### Parallel Execution Pattern

**To run multiple tasks in parallel, dispatch multiple Task tools in ONE message:**

Example - working on 3 independent tasks:
1. Call Task tool for task 1 (bug fix)
2. Call Task tool for task 2 (new feature)
3. Call Task tool for task 3 (optimization)
4. Send all 3 in one message (parallel execution)

**Sequential tasks** - wait for Task results before dispatching next task.

## Phase 6: Validation and Quality Gates

After **each polymorphic agent cycle** completes:

1. **Run tests** if code was modified and validation was required
2. **Check code quality** (linting, type checking, security scan)
3. **Auto-refactor if needed**:
   - If code quality issues persist after agent completion
   - Trigger refactor agent to fix quality issues
   - **Limit: Maximum 3 refactor attempts** to avoid infinite loops
   - Track refactor attempts per task
4. **Capture debug information**:
   - Agent execution logs
   - Performance metrics (execution time, success/failure)
   - Intelligence used (which patterns, what queries)
   - Decisions made and reasoning
   - Store in observability system if available
5. **Generate cycle summary**:
   - Completed tasks (with file:line references if applicable)
   - Refactored tasks (with attempt count)
   - Skipped tasks (with reasons)
   - Quality issues (if still present after 3 refactor attempts)

## Phase 7: Final Reporting

Generate final summary across **all polymorphic agent cycles**:

1. **Overall Statistics**:
   - Total tasks completed
   - Total refactors triggered
   - Quality gate pass rate
   - Average execution time per task

2. **Debug Intelligence Captured**:
   - Agent execution patterns observed
   - Common failure modes (if any)
   - Performance bottlenecks identified
   - Intelligence effectiveness (pattern match rates)

3. **Remaining Work** (if any):
   - Tasks that exceeded refactor limit (3 attempts)
   - Manual intervention required
   - Recommendations for next steps

## Phase 8: User-Controlled Next Steps

**IMPORTANT: NEVER automatically commit changes**

After all fixes are complete, **ASK the user** if they want to:
- **Review the changes** (git diff, file-by-file review)
- **Commit the changes** (ONLY if user explicitly requests it)
- **Run tests** to verify fixes
- **Continue with remaining tasks**
- **Review captured debug intelligence**
- **Deploy the changes**

**Git operations require explicit user approval:**
- User says "commit these changes" -> OK to run git commands
- User says "create a commit" -> OK to run git commands
- User says "fix this bug" -> DO NOT commit automatically
- User says "implement this feature" -> DO NOT commit automatically
- Silence from user -> DO NOT commit automatically

**Wait for explicit user approval before ANY git operations.**

---

## Execution Instructions

**MANDATORY PROCESS:**

1. Analyze **current conversation context** to understand the task (bug, feature, enhancement, optimization, etc.)
2. Dispatch requirements gathering agent to break down into sub-tasks
3. Classify tasks by type and priority
4. Create parallel execution plan (identify what can run in parallel vs sequential)
5. **USE TASK TOOL TO DISPATCH TO POLYMORPHIC AGENTS**
6. Wait for agent results
7. Validate results (dispatch validation agent)
8. Refactor if needed (max 3 attempts per task)
9. Report summary
10. Ask user about next steps

**DO NOT**:
- Run Bash/Edit/Write commands directly to execute tasks
- Execute tasks yourself instead of using Task tool
- Skip dispatching to polymorphic agents
- **Use any subagent_type other than "polymorphic-agent"**
- Use `general-purpose`, `Explore`, `Plan`, or any other agent type
- Reject tasks because they're "enhancements" or "features" instead of bugs
- **Run git commands in spawned agents** (git add, git commit, git push, git stash, etc.)
- **Automatically commit changes** without explicit user approval
- **Assume user wants changes committed** - always ask first

**DO**:
- **ALWAYS use subagent_type="onex:polymorphic-agent"** for EVERY Task dispatch
- Dispatch multiple independent pollys in parallel
- Provide detailed context in each Task prompt
- Include Intelligence Context from hooks
- Track refactor attempts per task (use internal state tracking)
- Capture debug information after each agent cycle
- Run quality checks after each cycle, not just at the end
- **Accept ANY type of work** - bugs, features, enhancements, optimizations, requirements, documentation, infrastructure

## Refactor Attempt Tracking

```
task_refactor_counts: dict[str, int] = {}  # Track attempts per task

After each cycle:
  if code_quality_issues_found:
    task_id = generate_task_id(task)
    refactor_count = task_refactor_counts.get(task_id, 0)

    if refactor_count < 3:
      # Trigger refactor agent
      task_refactor_counts[task_id] = refactor_count + 1
      dispatch_refactor_agent(task, attempt=refactor_count + 1)
    else:
      # Max attempts reached, report to user
      report_quality_issue_limit_reached(task)
```

**IMPORTANT**: If no specific tasks are mentioned in the conversation, respond with:
"No specific tasks detected in current context. What would you like me to work on?"

**DO NOT** say "no issues detected" if the user is asking you to build features or enhancements - those are valid tasks!
