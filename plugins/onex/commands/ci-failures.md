---
name: ci-failures
description: CI Failures Command - Quick Review
tags: [ci, github-actions, debugging, automation]
args:
  - name: pr_number
    description: PR number (defaults to current branch PR)
    required: false
  - name: workflow
    description: Workflow name filter
    required: false
---

# CI Failures — Quick Review

Analyze CI/CD failures and provide a concise summary with severity classification.

**Announce at start:** "Checking CI failures..."

## Execution

1. Parse arguments: `pr_or_branch` = `$pr_number` or current branch, `workflow_filter` = `$workflow`
2. Read the poly prompt from `${CLAUDE_PLUGIN_ROOT}/skills/ci-failures/POLY_PROMPT.md` (`CLAUDE_PLUGIN_ROOT` is set automatically by the plugin runtime)
3. Dispatch to polymorphic agent:

```
Task(
  subagent_type="polymorphic-agent",
  description="Analyze CI failures",
  prompt="<POLY_PROMPT content>\n\n## Context\nPR_OR_BRANCH: {pr_or_branch}\nWORKFLOW_FILTER: {workflow_filter}"
)
```

4. Report the agent's findings to the user.
