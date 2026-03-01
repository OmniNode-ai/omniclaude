# ADR: AI-Slop Checker Rule Set v1.0

**Date**: 2026-03-02
**Status**: Accepted
**Ticket**: OMN-3191
**Author**: Pipeline (omniclaude)
**Repos affected**: omniclaude, omnibase_core, omnibase_infra, omnibase_spi, omniintelligence, omnimemory, onex_change_control

---

## Context

The AI-slop checker (`scripts/validation/check_ai_slop.py`) was rolled out across 7 repos on 2026-02-28 (OMN-2971). This document records the findings from the 48-hour post-rollout audit (OMN-3191) and locks the canonical v1.0 rule set.

---

## 48h Rollout Audit Findings

### CI Failure Summary

| Repo | Workflow | Result | Cause |
|------|---------|--------|-------|
| omniintelligence | CI (ai-slop-check) | FAILED | step_narration false positives (exit code 2, strict) |
| omniclaude | CI (ai-slop-check) | PASSED | No violations in changed files |
| omnibase_core | CI (ai-slop-check) | PASSED | No violations in changed files |
| omnibase_infra | CI (ai-slop-check) | PASSED | No violations in changed files |
| omnibase_spi | CI (ai-slop-check) | PASSED | No violations in changed files |
| onex_change_control | CI (ai-slop-check) | PASSED | No violations in changed files |
| omnimemory | N/A | N/A | Checker not deployed (missing from rollout) |

Other failures in the 48h window (Docker build, pre-commit) were unrelated to the AI-slop checker.

### Classification of omniintelligence Failure

The omniintelligence main-branch CI failure (run 22524715869) contained these violations:

| File | Line | Check | Classification | Verdict |
|------|------|-------|----------------|---------|
| `handler_claude_event.py` | 7 | boilerplate_docstring | "This module provides HandlerClaudeHookEvent, a handler class that processes" | TRUE POSITIVE |
| `handler_claude_event.py` | 884 | step_narration | `# Step 1: Classify intent (if classifier available)` | FALSE POSITIVE |
| `handler_claude_event.py` | 947 | step_narration | `# Step 2: Emit to Kafka (if producer and topic available)` | FALSE POSITIVE |
| `registry_claude_hook_event_effect.py` | 7 | boilerplate_docstring | "This module provides RegistryClaudeHookEventEffect, which creates and registers" | TRUE POSITIVE |
| `dispatch_handlers.py` | 7 | boilerplate_docstring | "This module provides bridge handlers that adapt between the MessageDispatchEngine" | TRUE POSITIVE |

### False Positive Analysis: step_narration in Python Code

The `step_narration` rule uses `re.compile(r"#\s*Step\s+\d+\s*[:\-]", re.IGNORECASE)` which matches any `# Step N:` comment in both Python and Markdown files.

In Python code, `# Step N:` is a standard documentation pattern for multi-step functions:
```python
# Step 1: Fetch session snapshot (DB READ-ONLY, with fallback)
snapshot = self._fetch_snapshot(session_id)

# Step 2: Run pattern extraction (pure compute)
insights = self._extract_patterns(snapshot)
```

This pattern is idiomatic and appears across the ONEX codebase:
- **omniintelligence**: 110 instances (dispatch handlers, model selector, decision store replay)
- **omniclaude**: 25 instances (replay engine, checkpoint manager, pattern enforcement)
- **omnibase_infra**: 105 instances (service runtime host, startup sequence)

These are NOT AI slop. They are legitimate documentation aids for ordered execution steps in complex functions.

The intended target of `step_narration` was Markdown documentation where LLMs generate structural boilerplate:
```markdown
## Step 1: Install the package
Run pip install.

## Step 2: Configure settings
Edit your config.
```

### True Positive Confirmation: boilerplate_docstring

The `boilerplate_docstring` rule correctly flags generic opener phrases like:
- `"This module provides HandlerClaudeHookEvent..."` — yes, informative, but still AI-pattern
- `"This module provides bridge handlers that adapt..."` — yes, even with specifics

These ARE AI-generated docstring patterns (LLMs default to "This module provides...").
The rule correctly identifies them as warnings. Engineers should rewrite these as:
```python
# Instead of:
"""This module provides HandlerClaudeHookEvent, a handler class that processes..."""

# Use:
"""HandlerClaudeHookEvent: processes Claude hook events and routes to intent classification."""
```

---

## Rule Changes (v1.0)

### Change 1: step_narration scoped to Markdown files only

**Before (v0.1)**:
`step_narration` fired on any `# Step N:` comment in both Python (`.py`) and Markdown (`.md`) files.

**After (v1.0)**:
`step_narration` fires only in Markdown (`.md`) files. Python inline comments are excluded.

**Rationale**: 48h audit confirmed 240+ false positives in Python code across 2 repos.
Python `# Step N:` comments are legitimate ordered-step documentation. Only Markdown step
headings (`## Step 1:`, `### Step 2:`) are LLM boilerplate.

**Implementation**: `_check_lines()` checks `filename.endswith(".md")` before applying the
step narration check.

---

## Canonical Rule Set v1.0

The following rules are locked as of 2026-03-02. Changes require updating `check_ai_slop.py`
in ALL 7 repos simultaneously (byte-identical file, no per-repo variations).

| Rule | Check ID | Severity | Applies To | Pattern |
|------|----------|----------|------------|---------|
| Sycophantic opener | `sycophancy` | ERROR | Python docstrings | "Excellent\|Great\|Sure\|Certainly..." at docstring start |
| reST-style markers | `rest_docstring` | ERROR | Python docstrings | `:param:`, `:type:`, `:returns:`, `:rtype:` |
| Boilerplate opener | `boilerplate_docstring` | WARNING | Python docstrings | "This module/class/function provides/implements/contains..." |
| Step narration | `step_narration` | WARNING | Markdown files only | `# Step N:` or `## Step N:` headings |
| Markdown separator | `md_separator` | WARNING | Python docstrings | Four or more `=` signs |

### Suppression

Add `# ai-slop-ok: <reason>` on:
- The `def`/`class` line itself
- The docstring's opening triple-quote line
- The line immediately preceding the `def`/`class` line

---

## Change Policy

**Critical invariant**: `check_ai_slop.py` MUST be byte-identical across all 7 repos.

Rules for modifying the rule set:
1. Edit `check_ai_slop.py` in omniclaude (canonical location)
2. Propagate the identical file to: omnibase_core, omnibase_infra, omnibase_spi, omniintelligence, omnimemory, onex_change_control
3. Update the Rule change log section in the module docstring
4. Update this ADR with the new rule and rationale
5. Per-repo overrides are NOT permitted. Suppression comments are the only exception mechanism.

**Why no per-repo overrides**: The checker enforces cross-repo consistency. If a pattern is
legitimate in one repo, it is legitimate in all repos. If a pattern needs suppression, use
`# ai-slop-ok: reason` at the call site.

---

## omnimemory Status

omnimemory was not included in the Phase 2 rollout (2026-02-28). The AI-slop checker is
not yet deployed there. A follow-up ticket should add it to complete 7-repo coverage.
