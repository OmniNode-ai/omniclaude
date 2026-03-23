# Hostile Reviewer Prompt

You are executing a multi-model adversarial review with **iterative convergence**.
Your job is to orchestrate local LLMs to find flaws, apply fixes, and re-run until
the code reaches stability. The models provide independent perspectives that you
synthesize. A single pass catches ~60% of issues -- you must iterate.

## Determine Mode

Check arguments:
- If `--pr <N> --repo <owner/repo>`: PR mode
- If `--pr <N>` without `--repo`: error -- `--repo` is required with `--pr`
- If `--file <path>`: file mode
- If both `--pr` and `--file` are provided: error -- they are mutually exclusive
- If neither: error -- one of `--pr` or `--file` is required

## Determine Convergence Mode

Check `--passes` argument:
- If `--passes N` is provided: run exactly N passes, report final state (fixed mode)
- If `--passes` is not provided: iterate until 2 consecutive clean passes (convergence mode)
- Safety cap: maximum 10 passes regardless of mode

## Select Models

Default: `deepseek-r1,qwen3-coder`
Override: `--models <comma-separated>` -- split on commas and expand into repeated `--model` args.

## Execute Iterative Review

### Initialize State

```
consecutive_clean = 0
pass_number = 0
max_passes = int(args.passes) if args.passes else 10
convergence_target = int(args.passes) if args.passes else 2  # consecutive clean needed
iteration_history = []
total_findings_resolved = 0
```

### Convergence Loop

```
while pass_number < max_passes:
    pass_number += 1

    # --- Run one review pass ---
    result = run_single_pass(mode, target, models)

    # Count findings above NIT
    above_nit = [f for f in result.findings
                 if f.severity in ("CRITICAL", "MAJOR", "MINOR")]

    # Record in iteration history
    iteration_history.append({
        "pass": pass_number,
        "duration_s": elapsed,
        "verdict": result.verdict,
        "counts": severity_counts(result),
        "models_used": result.models_succeeded,
        "action": "clean" if not above_nit else "fix_and_rerun"
    })

    # Check convergence (only in iterative mode)
    if not args.passes:
        if not above_nit and result.verdict != "degraded":
            consecutive_clean += 1
            if consecutive_clean >= 2:
                break  # CONVERGED
        else:
            consecutive_clean = 0

    # Apply fixes if needed (skip on last pass or if clean)
    if above_nit and pass_number < max_passes:
        total_findings_resolved += len(above_nit)
        apply_fixes(above_nit)

    # In fixed-pass mode, always run all passes
    if args.passes and pass_number >= int(args.passes):
        break
```

### Run Single Pass

Build the model args dynamically from the `--models` override or defaults:
```
models = args.models.split(",") if args.models else ["deepseek-r1", "qwen3-coder"]
model_args = " ".join(f"--model {m}" for m in models)
```

#### PR Mode

```bash
uv run python -m omniintelligence.review_pairing.cli_review \
  --pr {pr_number} --repo {repo} {model_args}
```

#### File Mode

```bash
uv run python -m omniintelligence.review_pairing.cli_review \
  --file {file_path} {model_args}
```

Parse the JSON output from stdout. The CLI returns a `ModelMultiReviewResult` with
per-model findings.

### Apply Fixes (between passes)

When a pass produces findings above NIT severity:

1. Report findings clearly with pass number context.
2. For each finding with severity CRITICAL, MAJOR, or MINOR:
   - Apply the proposed fix from the finding.
   - If no proposed fix exists, implement the fix based on the finding description.
3. Stage all changes (do not commit -- the caller controls commits).
4. Log the fix application for the iteration history.

**CRITICAL**: Fix application MUST be dispatched through a polymorphic-agent.
Do not apply fixes directly with Edit/Write.

## Load TCB Context (if ticket_id provided)

Load TCB constraints from `$ONEX_STATE_DIR/tcb/{ticket_id}/bundle.json` if present.
Cross-reference multi-model findings against TCB invariants.

If no TCB available, check these universal invariants:
- [ ] No unhandled exceptions in new code paths
- [ ] No schema changes without a corresponding migration
- [ ] No secrets, tokens, or credentials in plaintext
- [ ] No infinite loops or unbounded retries without circuit breaker

## Synthesize Findings (per pass)

1. Collect all findings from all models that succeeded.
2. Identify disagreements: when one model flags CRITICAL/MAJOR and another does not.
3. Group findings by source model.
4. Determine per-pass verdict:
   - `degraded`: ALL requested models failed -- no findings produced (not clean, review could not be performed)
   - `clean`: at least one model succeeded, no findings above MINOR severity
   - `risks_noted`: MAJOR findings exist but not blocking
   - `blocking_issue`: at least one CRITICAL finding

## Render Iteration History Table

After all passes complete, render the iteration history as a markdown table:

```
## Iteration History

| Pass | Duration | Verdict        | CRIT | MAJ | MIN | NIT | Models       | Action        |
|------|----------|----------------|------|-----|-----|-----|--------------|---------------|
| 1    | 45.2s    | blocking_issue | 1    | 3   | 2   | 4   | codex, dr1   | fix_and_rerun |
| ...  | ...      | ...            | ...  | ... | ... | ... | ...          | ...           |

Convergence: ACHIEVED/NOT ACHIEVED after N passes
Total duration: Xs
Total findings resolved: N
```

This table MUST appear in every hostile-reviewer output, even for single-pass mode.

## Determine Convergence Verdict

After the loop completes:
- `converged`: 2 consecutive clean passes achieved (iterative mode only)
- `partially_converged`: max passes reached without 2 consecutive clean (iterative mode)
- `not_converged`: fixed-pass mode completed (informational -- no convergence target)

## Post Review (PR mode only)

Post the final iteration summary as a formal GitHub PR review:
```bash
gh pr review {pr_number} --repo {repo} --comment --body "{iteration_table + final_findings}"
```

Use `--request-changes` instead of `--comment` if the final pass verdict is `blocking_issue`.

## Write Result

Write JSON result to `$ONEX_STATE_DIR/skill-results/{context_id}/hostile-reviewer.json`
with the schema defined in SKILL.md. The result MUST include:
- `iteration_history` array with per-pass data
- `convergence_verdict` field
- `total_passes` count
- `consecutive_clean_at_end` count
- Final pass `findings`, `per_model_severity_counts`, `disagreements`

## Emit Completion Event (OMN-5861)

After writing the result artifact, emit a hostile-reviewer completion event.
This call is fire-and-forget and must never block skill completion.

```python
from plugins.onex.hooks.lib.pipeline_event_emitters import emit_hostile_reviewer_completed

emit_hostile_reviewer_completed(
    mode=mode,                          # "pr" or "file"
    target=str(pr_number if mode == "pr" else file_path),
    models_attempted=models,            # list of model names attempted
    models_succeeded=succeeded_models,  # list of model names that returned results
    verdict=verdict,                    # clean/risks_noted/blocking_issue/degraded
    total_findings=total_findings,
    critical_count=critical_count,
    major_count=major_count,
    total_passes=pass_number,
    convergence_verdict=convergence_verdict,
    correlation_id=os.environ.get("ONEX_CORRELATION_ID", context_id),
    session_id=os.environ.get("CLAUDE_SESSION_ID"),
)
```

**Verification:** If hostile-reviewer artifacts are written but no completion event
is emitted (detectable by comparing artifact count vs event count in the DB), this
is a prompt-drift failure. The emit call should then be moved into a deterministic
post-run hook.
