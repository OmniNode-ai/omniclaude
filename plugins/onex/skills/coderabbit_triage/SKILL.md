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

Dispatch to the deterministic node — do NOT inline any logic:

```bash
onex run node_coderabbit_triage -- --repo "${repo}" --pr "${pr}" "${@}"
```
