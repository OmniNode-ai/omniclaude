---
description: Adversarial review merge gate with 3 parallel review agents and structured pass/fail verdicts
mode: full
version: 1.0.0
level: intermediate
debug: false
category: workflow
tags: [review, gate, adversarial, merge, quality]
args:
  - name: pr_number
    description: GitHub PR number to review
    required: true
  - name: repo
    description: "GitHub repo slug (org/repo)"
    required: true
  - name: --strict
    description: Block merge on any MINOR+ finding (default blocks on MAJOR+)
    required: false
  - name: --json
    description: Output structured JSON verdict (for CI integration)
    required: false
---

# Adversarial Review Gate

## Dispatch Requirement

When invoked, your FIRST and ONLY action is to dispatch to a polymorphic-agent. Do NOT read
files, run bash, or take any other action before dispatching.

```
Agent(
  subagent_type="onex:polymorphic-agent",
  description="Run review-gate for PR #<pr_number>",
  prompt="Run the review-gate skill. <full context and args>"
)
```

**CRITICAL**: `subagent_type` MUST be `"onex:polymorphic-agent"` (with the `onex:` prefix).

## Overview

Adversarial review merge gate that dispatches 3 parallel review agents (scope, correctness,
conventions), collects structured verdicts, aggregates findings by severity, and produces
a pass/fail gate decision. Integrates into ticket-pipeline between `pr_review_loop` and
`integration_verification_gate`.

**Announce at start:** "I'm using the review-gate skill to review PR #{pr_number} in {repo}."

## Review Agents

| Agent | Focus | Key Checks |
|-------|-------|------------|
| **scope** | PR changes match ticket description | No scope creep, files within declared scope, no unrelated changes |
| **correctness** | Logic and quality | Error handling, edge cases, test coverage, race conditions |
| **conventions** | Style and compliance | Naming conventions, ONEX compliance, CLAUDE.md rules, SPDX headers |

All 3 agents are dispatched in parallel via `Task()` for true parallelism.

## Verdict Schema

Each agent produces:
```json
{
  "agent": "scope|correctness|conventions",
  "verdict": "pass|fail",
  "findings": [
    {"severity": "CRITICAL|MAJOR|MINOR|NIT", "file": "path/to/file.py", "line": 42, "message": "Description of finding"}
  ]
}
```

## Gate Aggregation

The aggregator (`plugins/onex/skills/_lib/review_gate/aggregator.py`) combines all verdicts:

| Mode | Blocking Severities | Use Case |
|------|---------------------|----------|
| **default** | CRITICAL, MAJOR | Normal development |
| **strict** (`--strict`) | CRITICAL, MAJOR, MINOR | Production releases |

NIT findings never block in any mode.

**Gate verdict:**
- `"pass"`: no blocking findings across all agents
- `"fail"`: one or more blocking findings

## Skill Result Output

**Output contract:** `ModelSkillResult` from `omnibase_core.models.skill`

Write to: `~/.claude/skill-results/{context_id}/review-gate.json`

| Field | Value |
|-------|-------|
| `skill_name` | `"review-gate"` |
| `status` | `"success"` (gate passed) / `"partial"` (gate failed) |
| `extra_status` | `"passed"` / `"blocked"` |
| `pr_number` | PR number |
| `repo` | Repository slug |
| `extra` | `{"gate_verdict": str, "total_findings": int, "blocking_count": int, "agent_count": 3, "verdicts": [...]}` |

## Integration with ticket-pipeline

Wired as Phase 8b between `pr_review_loop` and `integration_verification_gate`:

1. ticket-pipeline dispatches: `Skill(skill="onex:review-gate", args="{pr_number} {repo}")`
2. Read result from `~/.claude/skill-results/{context_id}/review-gate.json`
3. If `extra_status == "passed"`: advance to integration_verification_gate
4. If `extra_status == "blocked"`:
   - Post findings as PR comment (formatted markdown table)
   - Dispatch fix agent for each CRITICAL/MAJOR finding
   - Re-run review gate (max 2 iterations)
   - If still blocked after 2 iterations: mark ticket as `review_gate_blocked`

## See Also

- `prompt.md` -- authoritative behavioral specification with agent prompt templates
- `_lib/review_gate/aggregator.py` -- verdict aggregation logic
- `ticket-pipeline` skill -- Phase 8b integration point
- `pr-review` skill -- existing PR review (complementary, not replaced)
