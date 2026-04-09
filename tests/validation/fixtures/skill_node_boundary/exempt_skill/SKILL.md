---
description: Skill with boundary_exempt declared — suppresses all checks
mode: full
version: 1.0.0
level: advanced
boundary_exempt: true
---

# Exempt Skill

This skill has boundary_exempt: true in its frontmatter.
All boundary checks are suppressed.

gh pr list --repo example/repo --json number

for each pr in prs:
  process pr

state["key"] = "value"
