---
description: Non-compliant skill — iterates over PRs inline
mode: full
version: 1.0.0
level: advanced
---

# Non-Compliant Skill: For Loop Over PRs

## How It Works

Iterate over all PRs and process each one:

for each pr in pr_list:
  - Check if PR is ready
  - Enable auto-merge if ready

Then for each repo in repos:
  - Scan open issues
  - Create tickets for issues

This is non-compliant because it contains orchestration logic inline.
