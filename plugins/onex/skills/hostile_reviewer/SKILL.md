---
description: Multi-model adversarial code review with iterative convergence. Loops automatically until 2 consecutive clean passes (nothing above NIT). Uses Codex CLI (primary) and local LLMs (DeepSeek-R1) for cross-check. Output is MANDATORY.
mode: both
version: 3.0.0
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
  - convergence
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
  - name: passes
    description: "Fixed number of passes to run. Default: iterates until 2 consecutive clean passes. Use --passes 1 for single-pass mode (backwards compat)."
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

Multi-model adversarial review with **iterative convergence**. The skill loops automatically,
applying fixes after each pass, until **2 consecutive passes produce nothing above NIT severity**.
A single pass catches ~60% of issues; fixes from pass N introduce new issues caught in pass N+1.
Iterating to convergence eliminates this false-completeness problem.

Calls Codex CLI (primary, ChatGPT-class model) and local LLMs (DeepSeek-R1) for independent
cross-check. Returns all findings with per-model attribution. Output is MANDATORY -- the skill
always produces a result artifact even when verdict is `clean` (empty `findings` array is valid
for `clean`). Cannot rubber-stamp without running the models.

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

### Convergence Loop (default behavior)

The skill iterates until convergence. **Convergence** = 2 consecutive passes where no
finding is above NIT severity. This is the default behavior.

Override with `--passes N` for a fixed number of passes (e.g., `--passes 1` for
single-pass backwards compatibility).

**Algorithm:**

```
consecutive_clean = 0
pass_number = 0
max_passes = args.passes or 10  # safety cap to prevent infinite loops
iteration_history = []

while consecutive_clean < 2 and pass_number < max_passes:
    pass_number += 1
    start_time = now()

    # 1. Run multi-model review
    result = run_review(mode, target, models)

    # 2. Count findings above NIT
    above_nit = [f for f in result.findings if f.severity in (CRITICAL, MAJOR, MINOR)]

    # 3. Record pass in iteration history
    iteration_history.append({
        "pass": pass_number,
        "duration_s": elapsed(start_time),
        "verdict": result.verdict,
        "counts": {
            "CRITICAL": count(CRITICAL),
            "MAJOR": count(MAJOR),
            "MINOR": count(MINOR),
            "NIT": count(NIT)
        },
        "models_used": result.models_succeeded,
        "action": "clean" if not above_nit else "fix_and_rerun"
    })

    # 4. Check convergence
    if not above_nit and result.verdict != "degraded":
        consecutive_clean += 1
    else:
        consecutive_clean = 0

    # 5. If not converged, apply fixes and loop
    if consecutive_clean < 2 and above_nit:
        apply_fixes(above_nit)  # dispatch to polymorphic-agent for code changes

    # If --passes N was specified and we hit it, stop regardless
    if args.passes and pass_number >= args.passes:
        break
```

**Safety cap**: The loop runs at most 10 passes (configurable via `--passes`). If
convergence is not reached in 10 passes, the skill reports partial convergence with
the full iteration history.

### Single Pass Steps

Each pass within the loop executes:

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

### Fix Application (between passes)

When a pass produces findings above NIT:

1. Report findings to the caller.
2. Dispatch a polymorphic-agent to apply fixes for all CRITICAL, MAJOR, and MINOR findings.
3. Stage the fixes (but do not commit -- the caller controls commits).
4. Re-run the review on the updated code.

### Post-Convergence

After convergence (or max passes reached):

1. Post the final findings summary as a GitHub PR review comment (PR mode only).
2. Persist results including full iteration history.
3. Emit completion event.

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

### Iteration History Table

The final output MUST include an iteration history table summarizing all passes:

```
## Iteration History

| Pass | Duration | Verdict        | CRIT | MAJ | MIN | NIT | Models       | Action        |
|------|----------|----------------|------|-----|-----|-----|--------------|---------------|
| 1    | 45.2s    | blocking_issue | 1    | 3   | 2   | 4   | codex, dr1   | fix_and_rerun |
| 2    | 38.7s    | risks_noted    | 0    | 1   | 1   | 2   | codex, dr1   | fix_and_rerun |
| 3    | 32.1s    | clean          | 0    | 0   | 0   | 1   | codex, dr1   | clean (1/2)   |
| 4    | 30.5s    | risks_noted    | 0    | 1   | 0   | 0   | codex, dr1   | fix_and_rerun |
| 5    | 29.8s    | clean          | 0    | 0   | 0   | 0   | codex, dr1   | clean (2/2)   |

Convergence: ACHIEVED after 5 passes (2 consecutive clean)
Total duration: 176.3s
Total findings resolved: 27
```

This table is the primary human-readable output of the iterative review. It is always
rendered even when `--passes 1` is used (showing a single row).

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

## Convergence Criteria

Default: **2 consecutive clean passes** (no findings above NIT severity).

A "clean pass" means:
- At least one model succeeded (not degraded)
- No CRITICAL, MAJOR, or MINOR findings across all models
- NIT findings are allowed and do not reset the consecutive counter

The 2-consecutive requirement prevents false convergence from a single lucky pass.
Evidence from the ModelPlanContract review (5 passes, 27 total findings) shows that
pass N fixes routinely introduce 2-4 new issues caught in pass N+1.

Override: `--passes N` sets a fixed pass count. The skill runs exactly N passes and
reports the final state regardless of convergence. Use `--passes 1` for single-pass
backwards compatibility.

## Verdict Determination

Per-pass verdict (unchanged from v2):
- `clean`: no findings above MINOR severity across all models (findings array may be empty or contain only NIT/MINOR entries). Requires at least one model to have succeeded.
- `risks_noted`: MAJOR findings exist but are not blocking -- implementer should address
- `blocking_issue`: at least one CRITICAL finding from any model -- must fix before merge
- `degraded`: ALL requested models failed. No findings were produced. This is NOT `clean` -- it means review could not be performed. The calling workflow decides whether to proceed or block.

Overall convergence verdict (new in v3):
- `converged`: 2 consecutive clean passes achieved. The code is stable.
- `partially_converged`: max passes reached with fewer than 2 consecutive clean passes. Findings may still exist.
- `not_converged`: fixed-pass mode (`--passes N`) completed without achieving convergence. Informational only.

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
  "convergence_mode": "iterative|fixed",
  "passes_requested": null,
  "total_passes": 5,
  "consecutive_clean_at_end": 2,
  "convergence_verdict": "converged|partially_converged|not_converged",
  "iteration_history": [
    {
      "pass": 1,
      "duration_s": 45.2,
      "verdict": "blocking_issue",
      "counts": {"CRITICAL": 1, "MAJOR": 3, "MINOR": 2, "NIT": 4},
      "models_used": ["codex", "deepseek-r1"],
      "action": "fix_and_rerun"
    },
    {
      "pass": 2,
      "duration_s": 38.7,
      "verdict": "risks_noted",
      "counts": {"CRITICAL": 0, "MAJOR": 1, "MINOR": 1, "NIT": 2},
      "models_used": ["codex", "deepseek-r1"],
      "action": "fix_and_rerun"
    },
    {
      "pass": 3,
      "duration_s": 32.1,
      "verdict": "clean",
      "counts": {"CRITICAL": 0, "MAJOR": 0, "MINOR": 0, "NIT": 1},
      "models_used": ["codex", "deepseek-r1"],
      "action": "clean"
    },
    {
      "pass": 4,
      "duration_s": 30.5,
      "verdict": "risks_noted",
      "counts": {"CRITICAL": 0, "MAJOR": 1, "MINOR": 0, "NIT": 0},
      "models_used": ["codex", "deepseek-r1"],
      "action": "fix_and_rerun"
    },
    {
      "pass": 5,
      "duration_s": 29.8,
      "verdict": "clean",
      "counts": {"CRITICAL": 0, "MAJOR": 0, "MINOR": 0, "NIT": 0},
      "models_used": ["codex", "deepseek-r1"],
      "action": "clean"
    }
  ],
  "models_requested": ["codex", "deepseek-r1"],
  "models_succeeded": ["codex", "deepseek-r1"],
  "models_failed": [],
  "per_model_severity_counts": {
    "codex": {"CRITICAL": 0, "MAJOR": 0, "MINOR": 0, "NIT": 0},
    "deepseek-r1": {"CRITICAL": 0, "MAJOR": 0, "MINOR": 0, "NIT": 0}
  },
  "findings": [],
  "disagreements": [],
  "invariant_checklist": [
    {"invariant": "...", "status": "PASS|FAIL|NOT_CHECKED"}
  ],
  "overall_verdict": "clean|risks_noted|blocking_issue|degraded"
}
```

**Note**: `findings`, `per_model_severity_counts`, and `disagreements` reflect the **final pass only**.
The full per-pass breakdown is in `iteration_history`.

Post result as a PR review comment (PR mode). For `blocking_issue`, use REQUEST_CHANGES;
otherwise use COMMENT.
