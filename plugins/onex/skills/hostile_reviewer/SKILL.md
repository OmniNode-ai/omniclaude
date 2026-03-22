---
description: Multi-model adversarial code review using local LLMs (DeepSeek-R1, Qwen3-Coder) and optionally Codex CLI. Returns per-model findings with attribution. Output is MANDATORY.
mode: both
version: 2.0.0
level: intermediate
debug: false
category: review
tags:
  - review
  - adversarial
  - pr
  - plan
  - multi-model
  - quality
  - risk
author: OmniClaude Team
args:
  - name: pr
    description: PR number to review (mutually exclusive with --file)
    required: false
  - name: repo
    description: Target GitHub repo (e.g., OmniNode-ai/omniclaude). Required with --pr.
    required: false
  - name: file
    description: Path to a plan file to review (mutually exclusive with --pr)
    required: false
  - name: ticket_id
    description: Linear ticket ID for loading TCB constraints
    required: false
  - name: models
    description: Comma-separated model list (default deepseek-r1,qwen3-coder). Available models are deepseek-r1, qwen3-coder, qwen3-14b, codex.
    required: false
---

# hostile-reviewer

## Dispatch Requirement

When invoked, dispatch to a polymorphic-agent:

```
Agent(
  subagent_type="onex:polymorphic-agent",
  description="Hostile review PR #<N> / plan file",
  prompt="Run the hostile-reviewer skill for PR #<N> in <repo> (or --file <path>). <full context>"
)
```

**CRITICAL**: `subagent_type` MUST be `"onex:polymorphic-agent"` (with the `onex:` prefix).

## Description

Multi-model adversarial review that calls local LLMs (DeepSeek-R1, Qwen3-Coder, Qwen3-14B)
and optionally Codex CLI to conduct independent adversarial reviews. Returns all findings
with per-model attribution. Output is MANDATORY -- if no risks are found, that itself is a
finding. Cannot rubber-stamp.

This skill consolidates the former `hostile-reviewer` (PR-only, Claude-only, exactly-2-risks)
and `external-model-review` (file-only, multi-model) into a single unified skill.

## Modes

### PR Mode (`--pr <N> --repo <owner/repo>`)

Reviews a PR diff using multi-model adversarial review.

```bash
/hostile-reviewer --pr 433 --repo OmniNode-ai/omniintelligence
```

### File Mode (`--file <path>`)

Reviews a plan or design document using multi-model adversarial review.
This replaces the former `/external-model-review` skill.

```bash
/hostile-reviewer --file docs/plans/my-plan.md
```

## Execution

1. Determine mode (PR or file) from arguments.
2. Invoke the multi-model review CLI:

**PR mode:**
```bash
uv run python -m omniintelligence.review_pairing.cli_review \
  --pr <N> --repo <owner/repo> --model deepseek-r1 --model qwen3-coder
```

**File mode:**
```bash
uv run python -m omniintelligence.review_pairing.cli_review \
  --file <path> --model deepseek-r1 --model qwen3-coder
```

3. Parse the `ModelMultiReviewResult` JSON from stdout.
4. If `--ticket_id` is provided, load TCB constraints from
   `$ONEX_STATE_DIR/tcb/{ticket_id}/bundle.json` and cross-reference findings
   against TCB invariants.
5. Post findings as a GitHub PR review comment (PR mode only).
6. Persist results.

## Model Selection

Default models: `deepseek-r1,qwen3-coder`

Override with `--models`:
```bash
/hostile-reviewer --pr 433 --repo OmniNode-ai/omniintelligence --models deepseek-r1,qwen3-14b,codex
```

Available models (see omniintelligence `review_pairing/models.py` for registry):
- `deepseek-r1` -- DeepSeek-R1-Distill-Qwen-32B (M2 Ultra, reasoning/code review)
- `qwen3-coder` -- Qwen3-Coder-30B-A3B AWQ-4bit (RTX 5090, long context code)
- `qwen3-14b` -- Qwen3-14B-AWQ (RTX 4090, mid-tier)
- `codex` -- OpenAI Codex CLI (requires `codex` binary)

## Output Format

### Per-Model Status

For each model, report:
- Model name
- Status (succeeded / failed with error)
- Finding count by severity

### Disagreement Rendering

When models materially disagree on a major issue (one flags CRITICAL/MAJOR,
the other is silent or disagrees), surface that disagreement explicitly
BEFORE the detailed grouped findings:

```
DISAGREEMENT: DeepSeek-R1 flags "Missing retry logic" as CRITICAL.
Qwen3-Coder did not flag this issue. Review the evidence below.
```

### Grouped Findings

Present findings grouped by source model:

```
## DeepSeek-R1 (4 findings)

1. [CRITICAL] Missing retry logic
   Category: architecture
   Evidence: ...
   Proposed fix: ...

## Qwen3-Coder (3 findings)
...
```

### Degraded-Mode Visibility

- If one model succeeds and one fails, report partial success explicitly.
- If ALL models fail, report failure and return gracefully. Do not block
  the calling workflow.
- Never silently omit a failed model from the output.

## Severity Mapping

Findings use canonical severity levels:
- **CRITICAL** (ERROR): Security, data loss, architectural redesign required
- **MAJOR** (WARNING): Performance, missing error handling, incomplete tests
- **MINOR** (INFO): Code quality, documentation gaps, edge cases
- **NIT** (HINT): Formatting, naming, minor refactoring

## Verdict Determination

- `clean`: no findings above MINOR severity across all models
- `risks_noted`: MAJOR findings exist but are not blocking -- implementer should address
- `blocking_issue`: at least one CRITICAL finding from any model -- must fix before merge

## When Called

- **ticket-pipeline Phase 2.4** (between local_review and mergeability_gate) -- PR mode
- **design-to-plan Phase 2c** (after R1-R7 convergence) -- file mode
- **Standalone** for any PR or plan file

## Persisted Artifact

Write result to `$ONEX_STATE_DIR/skill-results/{context_id}/hostile-reviewer.json`:
```json
{
  "mode": "pr|file",
  "target": "<pr_number or file_path>",
  "models_requested": ["deepseek-r1", "qwen3-coder"],
  "models_succeeded": ["deepseek-r1"],
  "models_failed": [{"model": "qwen3-coder", "error": "..."}],
  "findings": [
    {
      "model": "deepseek-r1",
      "severity": "CRITICAL|MAJOR|MINOR|NIT",
      "category": "...",
      "description": "...",
      "evidence": "...",
      "proposed_fix": "..."
    }
  ],
  "disagreements": [
    {
      "issue": "...",
      "model_a": "deepseek-r1",
      "model_a_severity": "CRITICAL",
      "model_b": "qwen3-coder",
      "model_b_severity": null
    }
  ],
  "invariant_checklist": [
    {"invariant": "...", "status": "PASS|FAIL|NOT_CHECKED"}
  ],
  "overall_verdict": "clean|risks_noted|blocking_issue"
}
```

Post result as a PR review comment (PR mode). For `blocking_issue`, use REQUEST_CHANGES;
otherwise use COMMENT.
