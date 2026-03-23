---
description: Multi-model adversarial code review using Codex CLI (primary) and local LLMs (DeepSeek-R1) for cross-check. Returns per-model findings with attribution. Output is MANDATORY.
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
    description: Comma-separated model list (default codex,deepseek-r1). Available models are codex, deepseek-r1, qwen3-coder, qwen3-14b.
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

Multi-model adversarial review that calls Codex CLI (primary, ChatGPT-class model) and
local LLMs (DeepSeek-R1) for independent cross-check. Returns all findings with per-model
attribution. Output is MANDATORY -- the skill always produces a result artifact even when
verdict is `clean` (empty `findings` array is valid for `clean`). Cannot rubber-stamp
without running the models.

Codex CLI is the primary reviewer because it produces high signal-to-noise findings
(typically 5-15 precise structural observations vs 40-55 pattern-level noise from local
models alone). DeepSeek-R1 provides a local reasoning cross-check. Additional local
models (qwen3-coder, qwen3-14b) are available via `--models` override when broader
coverage is needed.

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

**PR mode (default models):**
```bash
uv run python -m omniintelligence.review_pairing.cli_review \
  --pr <N> --repo <owner/repo> --model codex --model deepseek-r1
```

**File mode (default models):**
```bash
uv run python -m omniintelligence.review_pairing.cli_review \
  --file <path> --model codex --model deepseek-r1
```

When `--models` is provided, expand into repeated `--model` args dynamically:
```bash
# Example: --models deepseek-r1,qwen3-14b,codex
uv run python -m omniintelligence.review_pairing.cli_review \
  --pr <N> --repo <owner/repo> --model deepseek-r1 --model qwen3-14b --model codex
```

3. Parse the `ModelMultiReviewResult` JSON from stdout.
4. If `--ticket_id` is provided, load TCB constraints from
   `$ONEX_STATE_DIR/tcb/{ticket_id}/bundle.json` and cross-reference findings
   against TCB invariants.
5. Post findings as a GitHub PR review comment (PR mode only).
6. Persist results.

## Model Selection

Default models: `codex,deepseek-r1`

Codex CLI is the primary reviewer (ChatGPT-class model, highest signal-to-noise ratio).
DeepSeek-R1 provides a local reasoning cross-check without network dependency.

Override with `--models`:
```bash
/hostile-reviewer --pr 433 --repo OmniNode-ai/omniintelligence --models codex,qwen3-coder,deepseek-r1
```

Available models (see omniintelligence `review_pairing/models.py` for registry):
- `codex` -- Codex CLI (ChatGPT-class model, requires `codex` binary in PATH)
- `deepseek-r1` -- DeepSeek-R1-Distill-Qwen-32B (M2 Ultra, reasoning/code review)
- `qwen3-coder` -- Qwen3-Coder-30B-A3B AWQ-4bit (RTX 5090, long context code)
- `qwen3-14b` -- Qwen3-14B-AWQ (RTX 4090, mid-tier)

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
Codex did not flag this issue. Review the evidence below.
```

### Grouped Findings

Present findings grouped by source model:

```
## DeepSeek-R1 (4 findings)

1. [CRITICAL] Missing retry logic
   Category: architecture
   Evidence: ...
   Proposed fix: ...

## Codex (6 findings)
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

- `clean`: no findings above MINOR severity across all models (findings array may be empty or contain only NIT/MINOR entries). Requires at least one model to have succeeded.
- `risks_noted`: MAJOR findings exist but are not blocking -- implementer should address
- `blocking_issue`: at least one CRITICAL finding from any model -- must fix before merge
- `degraded`: ALL requested models failed. No findings were produced. This is NOT `clean` -- it means review could not be performed. The calling workflow decides whether to proceed or block.

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
  "models_requested": ["codex", "deepseek-r1"],
  "models_succeeded": ["codex", "deepseek-r1"],
  "models_failed": [],
  "per_model_severity_counts": {
    "codex": {"CRITICAL": 0, "MAJOR": 2, "MINOR": 3, "NIT": 1},
    "deepseek-r1": {"CRITICAL": 1, "MAJOR": 2, "MINOR": 1, "NIT": 0}
  },
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
      "model_b": "codex",
      "model_b_severity": null
    }
  ],
  "invariant_checklist": [
    {"invariant": "...", "status": "PASS|FAIL|NOT_CHECKED"}
  ],
  "overall_verdict": "clean|risks_noted|blocking_issue|degraded"
}
```

Post result as a PR review comment (PR mode). For `blocking_issue`, use REQUEST_CHANGES;
otherwise use COMMENT.
