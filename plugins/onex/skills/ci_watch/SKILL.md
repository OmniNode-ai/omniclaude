---
description: Poll GitHub Actions CI for a PR, auto-fix failures, and report terminal state
mode: full
version: 1.0.0
level: basic
debug: false
category: workflow
tags: [ci, github-actions, automation, polling]
author: OmniClaude Team
runtime: skill-bootstrapper
composable: true
inputs:
  - name: pr_number
    type: int
    description: GitHub PR number to watch
    required: true
  - name: repo
    type: str
    description: "GitHub repo slug (org/repo)"
    required: true
  - name: timeout_minutes
    type: int
    description: Max minutes to wait for CI (default 60)
    required: false
  - name: max_fix_cycles
    type: int
    description: Max auto-fix attempts before escalating (default 3)
    required: false
  - name: auto_fix
    type: bool
    description: Auto-fix CI failures (default true)
    required: false
outputs:
  - name: skill_result
    type: ModelSkillResult
    description: "Written to $ONEX_STATE_DIR/skill-results/{context_id}/ci-watch.json"
    fields:
      - status: '"success" | "partial" | "error"  # EnumSkillResultStatus canonical values'
      - extra_status: '"passed" | "capped" | "timeout" | null  # domain-specific granularity'
      - pr_number: int
      - repo: str
      - extra: "{fix_cycles_used, elapsed_minutes, preexisting_fixes_dispatched}"
args:
  - name: pr_number
    description: GitHub PR number to watch
    required: true
  - name: repo
    description: "GitHub repo slug (org/repo)"
    required: true
  - name: --timeout-minutes
    description: Max minutes to wait for CI (default 60)
    required: false
  - name: --max-fix-cycles
    description: Max auto-fix cycles before escalating (default 3)
    required: false
  - name: --no-auto-fix
    description: Poll only, don't attempt fixes
    required: false
---

# CI Watch

Dispatch to the deterministic node — do NOT inline any logic:

```bash
onex run node_ci_watch -- --repo "${repo}" --pr "${pr_number}" "${@}"
```
