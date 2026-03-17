---
name: hostile_reviewer
description: Adversarial code review that attempts to break the change. Produces exactly 2 risks with confidence scores. Output is MANDATORY — cannot rubber-stamp.
version: 1.0.0
level: intermediate
debug: false
category: review
tags:
  - review
  - adversarial
  - pr
  - quality
  - risk
author: OmniClaude Team
args:
  - name: pr_number
    description: PR number to review
    required: true
  - name: repo
    description: Target GitHub repo (e.g., OmniNode-ai/omniclaude)
    required: true
  - name: ticket_id
    description: Linear ticket ID for loading TCB constraints
    required: false
---

# hostile-reviewer

## Dispatch Requirement

When invoked, dispatch to a polymorphic-agent:

```
Agent(
  subagent_type="onex:polymorphic-agent",
  description="Hostile review PR #<N>",
  prompt="Run the hostile-reviewer skill for PR #<N> in <repo>. <full context>"
)
```

**CRITICAL**: `subagent_type` MUST be `"onex:polymorphic-agent"` (with the `onex:` prefix).

## Description
Adversarial code review that attempts to break the change. Output is MANDATORY — if hostile
reviewer has no risks to flag, that itself is a finding. Cannot rubber-stamp.

## Mandate
You are a hostile reviewer. Your job is to find flaws, not to confirm everything is fine.
Assume the implementer is competent but missed edge cases.

## Required Output (Exactly This Format)
1. **Risk 1:** {concrete risk} — Detection: {what breaks, how you'd know}
2. **Risk 2:** {concrete risk} — Detection: {what breaks, how you'd know}
3. **Refactor Suggestion:** {specific structural improvement} OR "none because {concrete reason}"
4. **Invariant Checklist:**
   - [ ] {invariant from TCB} — {PASS / FAIL / NOT_CHECKED}
   - [ ] {invariant from TCB} — {PASS / FAIL / NOT_CHECKED}
5. **Breaking Test Proposal:** {test name + 3-line pseudocode that would expose Risk 1 or 2}

## Scope
- Review: the PR diff, not the rest of the codebase
- Context: load TCB constraints as the invariant checklist
- Focus: edge cases, concurrency, rollback safety, data mutations, security exposure

## When Called
- ticket-pipeline Phase 2.4 (between local_review and mergeability_gate)
- Can also be called standalone for any PR

## Output
Write result to `~/.claude/skill-results/{context_id}/hostile-reviewer.json`:
```json
{
  "risks": [
    {"id": 1, "description": "...", "detection": "..."},
    {"id": 2, "description": "...", "detection": "..."}
  ],
  "refactor_suggestion": "...",
  "refactor_reason_if_none": null,
  "invariant_checklist": [
    {"invariant": "...", "status": "PASS|FAIL|NOT_CHECKED"}
  ],
  "breaking_test_proposal": {
    "name": "test_...",
    "pseudocode": "..."
  },
  "overall_verdict": "clean | risks_noted | blocking_issue"
}
```

`blocking_issue` means a Risk is severe enough that the agent SHOULD fix it before merging.
Post result as a PR review comment.
