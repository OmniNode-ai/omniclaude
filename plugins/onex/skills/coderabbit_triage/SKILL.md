---
description: Auto-triage CodeRabbit review threads — classify severity and auto-reply to Minor/Nitpick findings with acknowledgment, resolving the thread so it no longer blocks merge.
mode: full
version: 1.0.0
level: intermediate
debug: false
category: quality
tags:
  - coderabbit
  - pr-review
  - triage
  - auto-reply
author: OmniClaude Team
composable: true
args:
  - name: repo
    description: "GitHub repo in owner/name format (e.g., OmniNode-ai/omniclaude)"
    required: true
  - name: pr
    description: "PR number to triage"
    required: true
  - name: --dry-run
    description: "Classify threads but do not post replies or resolve"
    required: false
---

# CodeRabbit Thread Auto-Triage

Auto-triage CodeRabbit review threads on a PR. Classifies each thread by
severity and auto-replies to Minor/Nitpick findings with an acknowledgment
message, then resolves the thread. Major/Critical findings are left for
substantive fixes.

## Usage

```
/coderabbit-triage OmniNode-ai/omniclaude 42
/coderabbit-triage OmniNode-ai/omniclaude 42 --dry-run
```

## Severity Classification

| Severity | Action | Markers |
|----------|--------|---------|
| Critical | Leave for fix | "critical", red circle emoji |
| Major | Leave for fix | "major", orange circle emoji, "important" |
| Minor | Auto-reply + resolve | "minor", yellow circle emoji, "suggestion" |
| Nitpick | Auto-reply + resolve | "nitpick", "nit", green circle emoji, "style" |

## Auto-Reply Template

> Acknowledged — tracking in tech-debt backlog. This is a minor/nitpick
> finding that does not block merge. Auto-triaged by CodeRabbit auto-triage
> hook [OMN-6739].
