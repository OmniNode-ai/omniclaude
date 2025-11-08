---
name: parallel-solve
description: Auto-detect issues and solve them in parallel using polymorphic agents
tags: [automation, parallel, planning, fix, build]
---

# Parallel Solve - Smart Context-Aware Problem Solving

You are an intelligent problem solver that automatically detects what needs to be fixed or built, creates a plan, and executes it in parallel using multiple polymorphic agents.

## Phase 1: Context Detection

Analyze the **current conversation context** to determine what needs to be done:

1. **Extract the Current Issue**:
   - Identify what the user is asking you to work on
   - Look for the main task/problem described in recent messages
   - Extract any specific requirements or constraints mentioned

2. **Check Conversation History**:
   - Review recent messages for identified issues or sub-tasks
   - Look for "TODO", "FIXME", "blocker", "critical" mentions
   - Extract any prioritized issue lists from previous analysis
   - Identify if test failures or errors were mentioned in conversation

3. **Understand the Task Context**:
   - What files/modules are involved?
   - What's the expected outcome?
   - Are there dependencies between sub-tasks?
   - What validation is needed?

**❌ DO NOT**: Check PRs, run CI checks, or look for external issues unless explicitly mentioned in the conversation

## Phase 2: Issue Classification

Categorize detected issues:

- **Blockers** (MUST fix): Import errors, syntax errors, critical bugs
- **High Priority** (SHOULD fix): Logic bugs, security issues, test failures
- **Medium Priority** (CAN fix): Configuration improvements, refactoring, documentation
- **Low Priority** (NICE to have): Code style, minor optimizations

## Phase 3: Parallel Execution Plan

Create a plan to fix issues in parallel:

1. **Group issues** by independence (can be fixed simultaneously)
2. **Identify dependencies** (must be fixed sequentially)
3. **Allocate to agents** based on specialization:
   - Import/dependency issues → dependency agent
   - Test failures → testing agent
   - Security issues → security agent
   - Logic bugs → debugging agent
   - Documentation → documentation agent

4. **Define validation** for each fix:
   - What tests should pass?
   - What checks should succeed?
   - How to verify the fix?

## Phase 4: Execute Plan

**🚨 CRITICAL REQUIREMENT: YOU MUST USE THE TASK TOOL 🚨**

**DO NOT execute fixes yourself** - you MUST dispatch EVERY task to a polymorphic agent using the Task tool.

### ❌ WRONG (Running commands directly):
```
DO NOT DO THIS:
- Bash: git add file.py && git commit
- Edit: file.py to change code
- Write: file.py with new content
```

### ✅ CORRECT (Dispatching to polymorphic agent):

**For EACH task, you MUST call Task tool like this:**

```
Task(
  description="Fix import errors in reducer node",
  subagent_type="polymorphic-agent",
  prompt="Load configuration for role 'polymorphic-agent' and execute:

  **Task**: Fix import errors in node_user_reducer.py

  **Context**: [Detailed problem description]

  **Required Actions**:
  1. Analyze import errors
  2. Fix missing imports
  3. Verify code compiles

  **Success Criteria**:
  - Code compiles without errors
  - All imports resolve correctly

  **Intelligence Context**:
  - Correlation ID: [from hook]
  - RAG Domain Intelligence: [path]
  - RAG Implementation Intelligence: [path]
  "
)
```

### Parallel Execution Pattern

**To run multiple tasks in parallel, dispatch multiple Task tools in ONE message:**

Example - fixing 3 independent issues:
1. Call Task tool for issue 1
2. Call Task tool for issue 2
3. Call Task tool for issue 3
4. Send all 3 in one message (parallel execution)

**Sequential tasks** - wait for Task results before dispatching next task.

## Phase 5: Validation & Quality Gates

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
   - ✅ Completed tasks (with file:line references if applicable)
   - 🔧 Refactored tasks (with attempt count)
   - ⏭️ Skipped tasks (with reasons)
   - ⚠️ Quality issues (if still present after 3 refactor attempts)

## Phase 6: Final Reporting

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

## Phase 7: Optional Next Steps

Ask user if they want to:
- Commit the changes
- Continue with remaining issues
- Review captured debug intelligence

---

## Execution Instructions

**MANDATORY PROCESS:**

1. Analyze **current conversation context** to understand the task
2. Break down the task into independent sub-tasks
3. Create parallel execution plan (identify what can run in parallel vs sequential)
4. **🚨 USE TASK TOOL TO DISPATCH TO POLYMORPHIC AGENTS 🚨**
5. Wait for agent results
6. Validate results
7. Report summary

**DO NOT**:
- Run Bash/Edit/Write commands directly to fix issues
- Execute fixes yourself instead of using Task tool
- Skip dispatching to polymorphic agents

**DO**:
- Use Task tool for EVERY fix in your plan
- Dispatch multiple independent tasks in parallel
- Provide detailed context in each Task prompt
- Include Intelligence Context from hooks
- Track refactor attempts per task (use internal state tracking)
- Capture debug information after each agent cycle
- Run quality checks after each cycle, not just at the end

**REFACTOR ATTEMPT TRACKING**:
```
task_refactor_counts = {}  # Track attempts per task

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

If NO issues are detected, respond with:
"✅ No issues detected in current context. Everything looks good!"
