---
description: Non-compliant skill — makes direct gh calls
mode: full
version: 1.0.0
level: advanced
---

# Non-Compliant Skill: Direct gh Calls

This skill iterates PRs and calls gh directly instead of dispatching to a node.

## How It Works

1. List all open PRs:

```bash
gh pr list --repo OmniNode-ai/omniclaude --json number,title
```

2. For each result, enable auto-merge:

```bash
gh pr merge --auto --squash 123
```

3. Report results.
