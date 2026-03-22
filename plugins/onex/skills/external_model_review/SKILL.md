---
description: Run multi-model adversarial review on a plan file using local LLMs and optionally Codex CLI. Returns per-model findings with attribution.
mode: both
version: 1.0.0
level: intermediate
debug: false
category: review
tags:
  - review
  - adversarial
  - plan
  - multi-model
  - quality
author: OmniClaude Team
args:
  - name: file
    description: Path to the plan file to review
    required: true
---

# external-model-review

## Dispatch Requirement

When invoked, dispatch to a polymorphic-agent:

```
Agent(
  subagent_type="onex:polymorphic-agent",
  description="External model review of plan file",
  prompt="Run the external-model-review skill for <file>. <full context>"
)
```

## Purpose

Automates the manual ChatGPT copy-paste adversarial review workflow by calling
local LLMs (DeepSeek-R1, Qwen3-Coder) and optionally Codex CLI to conduct
independent adversarial reviews of technical plans.

## Execution

1. Read the plan file at the provided path.
2. Invoke the CLI wrapper:

```bash
uv run python -m omniintelligence.review_pairing.cli_review \
  --file <path> --model deepseek-r1 --model codex
```

3. Parse the `ModelMultiReviewResult` JSON from stdout.
4. Present findings in journal-critique format.
5. Persist results to `~/.claude/skill-results/{context_id}/external-model-review.json`.

## Output Format

### Per-Model Status

For each model, report:
- Model name
- Status (succeeded / failed with error)
- Finding count

Example:
```
DeepSeek-R1: 4 findings (2 critical, 1 major, 1 minor)
Codex: FAILED (codex CLI not found)

Review based on partial results (1 of 2 models succeeded).
```

### Disagreement Rendering

When models materially disagree on a major issue (one flags CRITICAL/MAJOR,
the other is silent or disagrees), surface that disagreement explicitly
BEFORE the detailed grouped findings:

```
DISAGREEMENT: DeepSeek-R1 flags "Missing retry logic" as CRITICAL.
Codex did not flag this issue. Review the evidence below.
```

### Grouped Findings

After any disagreements, present findings grouped by source model:

```
## DeepSeek-R1 (4 findings)

1. [CRITICAL] Missing retry logic
   Category: architecture
   Evidence: Task 3 step 2 assumes stable NDJSON format
   Proposed fix: Add exponential backoff
   ...

## Codex (3 findings)
...
```

### Degraded-Mode Visibility

- If one model succeeds and one fails, report partial success explicitly.
- If ALL models fail, report failure and return gracefully. Do not block
  the calling workflow (design-to-plan can continue without external review).
- Never silently omit a failed model from the output.

## Persisted Artifact

The full `ModelMultiReviewResult` JSON is written to:
```
~/.claude/skill-results/{context_id}/external-model-review.json
```

This artifact is lossless (preserves per-model attribution, all findings,
error details). The human-facing output above may summarize for readability,
but the artifact retains everything.

## Severity Mapping

Findings use canonical severity levels:
- **CRITICAL** (ERROR): Security, data loss, architectural redesign required
- **MAJOR** (WARNING): Performance, missing error handling, incomplete tests
- **MINOR** (INFO): Code quality, documentation gaps, edge cases
- **NIT** (HINT): Formatting, naming, minor refactoring
