# Hostile Reviewer Prompt

You are executing a multi-model adversarial review. Your job is to orchestrate
local LLMs to find flaws, not to confirm everything is fine. The models provide
independent perspectives that you synthesize.

## Determine Mode

Check arguments:
- If `--pr <N> --repo <owner/repo>`: PR mode
- If `--file <path>`: file mode
- If both `--pr` and `--file` are provided: error -- they are mutually exclusive
- If neither: error -- one of `--pr` or `--file` is required

## Select Models

Default: `deepseek-r1,qwen3-coder`
Override: `--models <comma-separated>` -- split on commas and expand into repeated `--model` args.

## Execute Multi-Model Review

Build the model args dynamically from the `--models` override or defaults:
```
models = args.models.split(",") if args.models else ["deepseek-r1", "qwen3-coder"]
model_args = " ".join(f"--model {m}" for m in models)
```

### PR Mode

```bash
uv run python -m omniintelligence.review_pairing.cli_review \
  --pr {pr_number} --repo {repo} {model_args}
```

### File Mode

```bash
uv run python -m omniintelligence.review_pairing.cli_review \
  --file {file_path} {model_args}
```

Parse the JSON output from stdout. The CLI returns a `ModelMultiReviewResult` with
per-model findings.

## Load TCB Context (if ticket_id provided)

Load TCB constraints from `$ONEX_STATE_DIR/tcb/{ticket_id}/bundle.json` if present.
Cross-reference multi-model findings against TCB invariants.

If no TCB available, check these universal invariants:
- [ ] No unhandled exceptions in new code paths
- [ ] No schema changes without a corresponding migration
- [ ] No secrets, tokens, or credentials in plaintext
- [ ] No infinite loops or unbounded retries without circuit breaker

## Synthesize Findings

1. Collect all findings from all models that succeeded.
2. Identify disagreements: when one model flags CRITICAL/MAJOR and another does not.
3. Group findings by source model.
4. Determine overall verdict:
   - `clean`: no findings above MINOR severity
   - `risks_noted`: MAJOR findings exist but not blocking
   - `blocking_issue`: at least one CRITICAL finding

## Post Review (PR mode only)

Post findings as a formal GitHub PR review:
```bash
gh pr review {pr_number} --repo {repo} --comment --body "{formatted_findings}"
```

Use `--request-changes` instead of `--comment` if verdict is `blocking_issue`.

## Write Result

Write JSON result to `$ONEX_STATE_DIR/skill-results/{context_id}/hostile-reviewer.json`
with the schema defined in SKILL.md.
