---
name: deploy-local-plugin
description: Deploy local plugin files to Claude Code plugin cache for testing
tags: [tooling, deployment, plugin]
args:
  - name: --execute
    description: Actually perform deployment (default is dry-run)
    required: false
  - name: --no-version-bump
    description: Skip auto-incrementing the patch version
    required: false
---

# Deploy Local Plugin

Deploy the local plugin source to the Claude Code plugin cache for testing.

**Announce at start:** "Deploying local plugin to cache..."

## Execution

1. Parse arguments: `EXECUTE` = true if `--execute` present, `NO_VERSION_BUMP` = true if `--no-version-bump` present
2. Read the poly prompt from `${CLAUDE_PLUGIN_ROOT}/skills/deploy-local-plugin/POLY_PROMPT.md`
3. Dispatch to polymorphic agent:

```
Task(
  subagent_type="polymorphic-agent",
  description="Deploy local plugin",
  prompt="<POLY_PROMPT content>\n\n## Context\nEXECUTE: {execute}\nNO_VERSION_BUMP: {no_version_bump}"
)
```

4. Report the deployment result to the user.
