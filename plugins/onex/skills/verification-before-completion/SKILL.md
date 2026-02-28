---
name: verification-before-completion
description: Use when about to claim work is complete, fixed, or passing, before committing or creating PRs - requires running verification commands and confirming output before making any success claims; evidence before assertions always
version: 1.0.0
category: workflow
tags:
  - verification
  - quality
  - completion
  - testing
  - discipline
author: OmniClaude Team
---

# Verification Before Completion

## Overview

Claiming work is complete without verification is dishonesty, not efficiency.

**Core principle:** Evidence before claims, always.

**Violating the letter of this rule is violating the spirit of this rule.**

## The Iron Law

```
NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE
```

If you haven't run the verification command in this message, you cannot claim it passes.

## The Gate Function

```
BEFORE claiming any status or expressing satisfaction:

1. IDENTIFY: What command proves this claim?
2. RUN: Execute the FULL command (fresh, complete)
3. READ: Full output, check exit code, count failures
4. VERIFY: Does output confirm the claim?
   - If NO: State actual status with evidence
   - If YES: State claim WITH evidence
5. ONLY THEN: Make the claim

Skip any step = lying, not verifying
```

## Common Failures

| Claim | Requires | Not Sufficient |
|-------|----------|----------------|
| Tests pass | Test command output: 0 failures | Previous run, "should pass" |
| Linter clean | Linter output: 0 errors | Partial check, extrapolation |
| Build succeeds | Build command: exit 0 | Linter passing, logs look good |
| Bug fixed | Test original symptom: passes | Code changed, assumed fixed |
| Regression test works | Red-green cycle verified | Test passes once |
| Agent completed | VCS diff shows changes | Agent reports "success" |
| Requirements met | Line-by-line checklist | Tests passing |

## Red Flags - STOP

- Using "should", "probably", "seems to"
- Expressing satisfaction before verification ("Great!", "Perfect!", "Done!", etc.)
- About to commit/push/PR without verification
- Trusting agent success reports
- Relying on partial verification
- Thinking "just this once"
- Tired and wanting work over
- **ANY wording implying success without having run verification**

## Rationalization Prevention

| Excuse | Reality |
|--------|---------|
| "Should work now" | RUN the verification |
| "I'm confident" | Confidence ≠ evidence |
| "Just this once" | No exceptions |
| "Linter passed" | Linter ≠ compiler |
| "Agent said success" | Verify independently |
| "I'm tired" | Exhaustion ≠ excuse |
| "Partial check is enough" | Partial proves nothing |
| "Different words so rule doesn't apply" | Spirit over letter |

## Key Patterns

**Tests:**
```
✅ [Run test command] [See: 34/34 pass] "All tests pass"
❌ "Should pass now" / "Looks correct"
```

**Regression tests (TDD Red-Green):**
```
✅ Write → Run (pass) → Revert fix → Run (MUST FAIL) → Restore → Run (pass)
❌ "I've written a regression test" (without red-green verification)
```

**Build:**
```
✅ [Run build] [See: exit 0] "Build passes"
❌ "Linter passed" (linter doesn't check compilation)
```

**Requirements:**
```
✅ Re-read plan → Create checklist → Verify each → Report gaps or completion
❌ "Tests pass, phase complete"
```

**Agent delegation:**
```
✅ Agent reports success → Check VCS diff → Verify changes → Report actual state
❌ Trust agent report
```

## Why This Matters

From 24 failure memories:
- your human partner said "I don't believe you" - trust broken
- Undefined functions shipped - would crash
- Missing requirements shipped - incomplete features
- Time wasted on false completion → redirect → rework
- Violates: "Honesty is a core value. If you lie, you'll be replaced."

## When To Apply

**ALWAYS before:**
- ANY variation of success/completion claims
- ANY expression of satisfaction
- ANY positive statement about work state
- Committing, PR creation, task completion
- Moving to next task
- Delegating to agents

**Rule applies to:**
- Exact phrases
- Paraphrases and synonyms
- Implications of success
- ANY communication suggesting completion/correctness

## Evidence Requirements Check

Run this check **before claiming any ticket is complete** (before committing, PR creation, or marking Done).

### Preflight: determine ticket_id

```bash
git rev-parse --abbrev-ref HEAD | grep -oiE 'omn-[0-9]+'
```

If no ticket_id found: skip, log "cannot determine ticket from branch" and continue with standard verification.

### Locate contract

```
Primary:  $ONEX_CC_REPO_PATH/contracts/{ticket_id}.yaml   (if ONEX_CC_REPO_PATH is set)
Fallback: $OMNI_HOME/onex_change_control/contracts/{ticket_id}.yaml
```

If no contract found: skip, log "no contract for {ticket_id} — evidence check skipped" and continue.

### For each evidence_requirement in contract

**kind: tests**
```bash
# Run the command declared in the contract verification_steps
{command_from_contract}
# Require exit 0
```

**kind: ci**
```bash
# Find PR for current branch
PR=$(gh pr list --head $(git branch --show-current) --json number --jq '.[0].number')

# If no PR: WARN "no PR yet — CI check skipped"
# If PR found: check CI status
gh pr view $PR --json statusCheckRollup
# Require all checkRuns.conclusion == SUCCESS or NEUTRAL
```

**kind: integration**
```bash
# Check for golden-path artifact for today with matching ticket_id and status=pass
ls ~/.claude/golden-path/$(date +%Y-%m-%d)/
# Look for artifact JSON where: artifact.ticket_id == {ticket_id} AND artifact.status == "pass"
# If not found: offer to run /golden-path-validate now
```

**kind: manual**

Ask the user: "Have you verified: {description}?" [yes/no]
Block completion if the answer is no.

### emergency_bypass semantics

If `emergency_bypass.enabled=true` with non-empty `justification` and `follow_up_ticket_id`:
downgrade all BLOCK verdicts to WARN. Completion may proceed with warning logged.

---

## The Bottom Line

**No shortcuts for verification.**

Run the command. Read the output. THEN claim the result.

This is non-negotiable.
