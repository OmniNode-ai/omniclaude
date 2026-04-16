# Hostile Reviewer Prompt

You are executing a multi-model adversarial review with **iterative convergence**.
Your job is to orchestrate local LLMs to find flaws, apply fixes, and re-run until
the code reaches stability. The models provide independent perspectives that you
synthesize. A single pass catches ~60% of issues -- you must iterate.

## Determine Mode

Check arguments:
- `--plan-path <path>` is an alias for `--file <path>` — normalize it first: if `--plan-path` is provided and `--file` is not, treat it as `--file <path>`.
- If `--static`: static analysis mode (see Static Mode section below). Mutually exclusive with `--pr` and `--file`.
- If `--gate` is set AND `--pr <N> --repo <owner/repo>`: **gate mode** (see Gate Mode section below)
- If `--gate` is set AND `--file`: error -- `--gate` requires `--pr`, not `--file`
- If `--pr <N> --repo <owner/repo>` (no `--gate`): PR mode
- If `--pr <N>` without `--repo`: error -- `--repo` is required with `--pr`
- If `--file <path>` (or `--plan-path <path>`): file mode
- If both `--pr` and `--file`/`--plan-path` are provided: error -- they are mutually exclusive
- If `--static` and `--pr` or `--file` are provided: error -- `--static` is mutually exclusive with `--pr` and `--file`
- If neither `--static`, `--pr`, nor `--file`: error -- one of `--static`, `--pr`, or `--file` is required

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
uv run python -m omniintelligence.review_pairing.cli_review \  # local-path-ok: omniintelligence direct CLI invocation until OMN-8770 onex run migration
  --pr {pr_number} --repo {repo} --persona analytical-strict {model_args}
```

#### File Mode

**STEP 0: Validate target file path (MANDATORY — do not skip)**

Before invoking cli_review, execute this validation block:

```python
from pathlib import Path
import sys

raw_path = "{file_path}"
resolved = Path(raw_path).expanduser().resolve()

if not resolved.exists():
    print(f"ERROR: File not found: {resolved}", file=sys.stderr)
    print(f"  Raw input was: {raw_path}", file=sys.stderr)
    print("  hostile-reviewer --file requires an existing file. Refusing to substitute.", file=sys.stderr)
    sys.exit(1)

if not resolved.is_file():
    print(f"ERROR: Path is not a regular file: {resolved}", file=sys.stderr)
    sys.exit(1)

TARGET_FILE = str(resolved)
```

If the script exits non-zero, **stop immediately**. Do NOT proceed. Do NOT substitute a different file.
The `target` field in the result JSON MUST equal `TARGET_FILE` (the resolved absolute path).

```bash
uv run python -m omniintelligence.review_pairing.cli_review \  # local-path-ok: omniintelligence direct CLI invocation until OMN-8770 onex run migration
  --file {TARGET_FILE} --persona analytical-strict {model_args}
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

**File mode invariant**: `target` field MUST equal `str(Path(file_path).expanduser().resolve())`.
Never write a raw user-supplied path or a different file's path in the `target` field.
If file validation (STEP 0 above) was skipped and a different file was reviewed, this is a hard failure.

- `iteration_history` array with per-pass data
- `convergence_verdict` field
- `total_passes` count
- `consecutive_clean_at_end` count
- Final pass `findings`, `per_model_severity_counts`, `disagreements`

## Gate Mode (`--gate`)

When `--gate` is set, skip the iterative convergence loop entirely and instead run 3 parallel
review agents (scope, correctness, conventions) to produce a structured merge gate verdict.

**This mode requires `--pr` and `--repo`. `--file` is incompatible with `--gate`.**

### Dispatch 3 Parallel Review Agents

All 3 agents are dispatched in a single message (true parallelism):

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="hostile-reviewer gate: scope review PR #{pr_number}",
  prompt="You are a scope review agent for PR #{pr_number} in {repo}.

    Read the PR diff:
    ```bash
    gh pr diff {pr_number} --repo {repo}
    ```

    Read the ticket description from the PR body or linked Linear ticket.

    Review the PR for scope violations:
    - Are all changed files within the declared scope of the ticket?
    - Are there unrelated changes bundled into this PR?
    - Does the PR introduce changes beyond what the ticket requires?

    Produce a structured verdict as JSON:
    {\"agent\": \"scope\", \"verdict\": \"pass|fail\", \"findings\": [{\"severity\": \"CRITICAL|MAJOR|MINOR|NIT\", \"file\": \"path\", \"line\": N, \"message\": \"...\"}]}

    Report the JSON verdict as your final output."
)

Task(
  subagent_type="onex:polymorphic-agent",
  description="hostile-reviewer gate: correctness review PR #{pr_number}",
  prompt="You are a correctness review agent for PR #{pr_number} in {repo}.

    Read the PR diff:
    ```bash
    gh pr diff {pr_number} --repo {repo}
    ```

    Review the PR for correctness issues:
    - Logic errors, off-by-one, missing error handling
    - Edge cases not covered by tests
    - Race conditions or concurrency issues
    - Missing or inadequate test coverage for new code
    - Security concerns (injection, path traversal, etc.)

    Produce a structured verdict as JSON:
    {\"agent\": \"correctness\", \"verdict\": \"pass|fail\", \"findings\": [{\"severity\": \"CRITICAL|MAJOR|MINOR|NIT\", \"file\": \"path\", \"line\": N, \"message\": \"...\"}]}

    Report the JSON verdict as your final output."
)

Task(
  subagent_type="onex:polymorphic-agent",
  description="hostile-reviewer gate: conventions review PR #{pr_number}",
  prompt="You are a conventions review agent for PR #{pr_number} in {repo}.

    Read the PR diff:
    ```bash
    gh pr diff {pr_number} --repo {repo}
    ```

    Read the repo's CLAUDE.md for conventions:
    ```bash
    cat CLAUDE.md
    ```

    Review the PR for convention violations:
    - Naming conventions (Model prefix, Enum prefix, PEP 604 unions)
    - ONEX compliance (frozen models, explicit timestamps, SPDX headers)
    - CLAUDE.md rules (no backwards-compat shims, no over-engineering)
    - Code structure (single class per file where applicable)
    - Import patterns (no cross-boundary imports)

    Produce a structured verdict as JSON:
    {\"agent\": \"conventions\", \"verdict\": \"pass|fail\", \"findings\": [{\"severity\": \"CRITICAL|MAJOR|MINOR|NIT\", \"file\": \"path\", \"line\": N, \"message\": \"...\"}]}

    Report the JSON verdict as your final output."
)
```

### Aggregate Gate Verdict

After all 3 agents return, collect their JSON verdicts and aggregate:

```python
from plugins.onex.skills._lib.review_gate.aggregator import aggregate_verdicts

verdicts = [scope_verdict, correctness_verdict, conventions_verdict]
result = aggregate_verdicts(verdicts, strict=is_strict_mode)
# result["gate_verdict"] is "pass" or "fail"
# result["blocking_count"] is number of blocking findings
# result["total_findings"] is total findings across all agents
```

`is_strict_mode` = True when `--strict` flag is present (blocks on MINOR+; default blocks on MAJOR+).

### Gate Decision and Output

Based on `result["gate_verdict"]`:

- **"pass"**: Write `ModelSkillResult` with `status="success"`, `extra_status="passed"`. Then write sentinel:
  ```bash
  mkdir -p "$ONEX_STATE_DIR/hostile-review-pass"
  echo '{"pr":"{pr_number}","repo":"{repo}","verdict":"pass","ts":"{iso_timestamp}"}' \
    > "$ONEX_STATE_DIR/hostile-review-pass/{pr_number}.json"
  ```
- **"fail"**: Write `ModelSkillResult` with `status="partial"`, `extra_status="blocked"`, post findings to PR

When the gate fails, post a structured comment to the PR:

```markdown
## Hostile Reviewer Gate: BLOCKED

| Severity | Agent | File | Line | Finding |
|----------|-------|------|------|---------|
| CRITICAL | scope | src/foo.py | 42 | Scope creep: file not in ticket scope |
| MAJOR | correctness | src/bar.py | 15 | Missing error handling for None case |

**{blocking_count} blocking finding(s).** Fix all blocking issues for the active gate mode before merge.
<!-- default mode: MAJOR+ blocks; strict mode: MINOR+ blocks -->
```

Use `--request-changes` for blocked gate:
```bash
gh pr review {pr_number} --repo {repo} --request-changes --body "{findings_table}"
```

### Gate Result Artifact

Write to `$ONEX_STATE_DIR/skill-results/{context_id}/hostile-reviewer.json` (same path as PR/file mode):

```json
{
  "mode": "gate",
  "target": "{pr_number}",
  "gate_verdict": "pass|fail",
  "total_findings": N,
  "blocking_count": N,
  "strict": false,
  "agent_count": 3,
  "verdicts": [...]
}
```

Also set top-level `"overall_verdict"` to `"pass"` or `"blocking_issue"` for compatibility
with ticket-pipeline consumers that check `result["overall_verdict"]`.

### Retry Logic (when called from ticket-pipeline)

When integrated with ticket-pipeline (Phase 5.5 review_gate):
1. If gate fails, dispatch fix agents for each CRITICAL/MAJOR finding
2. Re-run `hostile-reviewer --gate` (max 2 iterations total)
3. If still blocked after 2 iterations, mark ticket as `review_gate_blocked` in state.yaml

## Static Mode Execution (`--static`)

When `--static` is set, skip the adversarial multi-model review entirely and run the
static analysis pipeline. This is the full logic from the former `code-review-sweep` skill.

**Announce**: "I'm using the hostile-reviewer skill in --static mode."

### Parse Arguments

```
repos     = args.repos.split(",") if args.repos else CODE_REVIEW_REPOS
categories = args.categories.split(",") if args.categories else ALL_CATEGORIES
dry_run   = args.dry_run  # forced true on first run (no state file)
ticket    = args.ticket
max_tickets = int(args.max_tickets) if args.max_tickets else 10
```

```
CODE_REVIEW_REPOS = [
  "omniclaude", "omnibase_core", "omnibase_infra",
  "omnibase_spi", "omniintelligence", "omnimemory",
  "onex_change_control", "omnibase_compat"
]

ALL_CATEGORIES = [
  "dead-code", "missing-error-handling", "stubs-shipped",
  "missing-kafka-wiring", "schema-mismatches", "hardcoded-values", "missing-tests"
]
```

### Generate run_id

```
run_id = f"{YYYYMMDD-HHMMSS}-{random6}"
```

### Load State

Load from `.onex_state/code-review-state.json`:
- If file does not exist: initialize empty state, force `dry_run = true`
- State fields: `file_hashes` (git object hashes), `finding_fingerprints`

### Phase 1: Scan (parallel, up to 4 repos)

**Path exclusions** — apply to every grep/scan:
```
.git/  .venv/  node_modules/  __pycache__/  *.pyc  dist/  build/
docs/  examples/  fixtures/  _golden_path_validate/  migrations/  *.generated.*  vendored/
```

**File Hash Check**: before scanning any file:
```bash
git hash-object <file>
```
If hash matches `state.file_hashes[repo:relative_path]`, skip file. After scanning, update hash.

#### Category: dead-code

Module-level (single-file scope only): identify functions/classes not referenced within same file.
Cross-file (vulture subprocess):
```bash
uv run vulture src/ --min-confidence 80 --exclude .venv,__pycache__,docs 2>/dev/null || true
```
Parse lines: `<file>:<line>: unused <kind> '<name>' (confidence: <N>%)`
- confidence >= 90%: severity=ERROR, confidence=HIGH
- confidence 80-89%: severity=WARNING, confidence=MEDIUM

#### Category: missing-error-handling

```bash
grep -rn "except.*:\s*$\|except Exception.*:\s*$" \
  --include="*.py" src/ \
  --exclude-dir=.git --exclude-dir=.venv --exclude-dir=__pycache__ \
  --exclude-dir=tests --exclude-dir=docs
```
Flag bare `except:` or `except Exception:` where the next non-blank line is `pass`.
Severity: WARNING, confidence: HIGH.

#### Category: stubs-shipped

```bash
grep -rn "TODO\|FIXME\|raise NotImplementedError" \
  --include="*.py" src/ \
  --exclude-dir=.git --exclude-dir=.venv --exclude-dir=__pycache__ \
  --exclude-dir=tests --exclude-dir=docs --exclude-dir=fixtures
```
Exclude abstract base class methods and `*_protocol.py` / `*_abstract.py` files.
`NotImplementedError`: severity=ERROR, confidence=HIGH. `TODO/FIXME`: severity=INFO, confidence=LOW.

#### Category: missing-kafka-wiring

For each `contract.yaml` in the repo: extract topics from `subscribe`/`publish` sections,
grep for actual producer/consumer references. Flag declared but unwired topics.
Severity: ERROR, confidence: HIGH.

#### Category: schema-mismatches

For each Pydantic model in `src/`: check `model_fields` against contract `config_keys`,
detect imports referencing renamed/deleted models.
Severity: ERROR, confidence: HIGH.

#### Category: hardcoded-values

```bash
grep -rn "\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b" \
  --include="*.py" src/ \
  --exclude-dir=.git --exclude-dir=.venv --exclude-dir=__pycache__ \
  --exclude-dir=tests --exclude-dir=docs
```
Exclude `127.0.0.1`, `0.0.0.0`. Also grep for `postgresql://`, `redis://`, port numbers.
Severity: WARNING, confidence: MEDIUM.

#### Category: missing-tests

For each `src/<pkg>/<subpkg>/module.py`, check if `tests/**/test_module.py` exists.
Severity: INFO, confidence: LOW.

### Phase 2: Triage

For each finding:
1. Compute fingerprint: `f"{repo}:{path}:{line}:{category}"`
2. Check `state.finding_fingerprints` — mark `is_new = fingerprint not in state`

### Phase 3: Report

Print findings table grouped by category. If no findings, print clean summary.

### Phase 4: Ticket Creation

Only if `--ticket` and NOT `--dry-run`.

**HARD CAP: `max_tickets` (default 10). Never exceed.**

Priority order:
1. `missing-kafka-wiring` (ERROR, HIGH)
2. `schema-mismatches` (ERROR, HIGH)
3. `stubs-shipped` with NotImplementedError (ERROR, HIGH)
4. `dead-code` with vulture >=90% (ERROR, HIGH)
5. `missing-error-handling` (WARNING, HIGH)
6. `hardcoded-values` (WARNING, MEDIUM)
7. `dead-code` lower confidence (WARNING, MEDIUM)
8. `stubs-shipped` with TODO/FIXME (INFO, LOW)
9. `missing-tests` (INFO, LOW)

For each `is_new=true` finding in priority order, create Linear ticket until cap reached.

### Phase 5: State Update

Only if NOT `--dry-run`. Update `.onex_state/code-review-state.json`:
- `last_run_id`, `last_run_at`, `file_hashes`, `finding_fingerprints`

### Phase 6: Write Static Result

Write to `$ONEX_STATE_DIR/skill-results/{context_id}/hostile-reviewer-static.json`
with the schema in SKILL.md (mode="static" result format).

### Static Mode Failure Handling

| Error | Behavior |
|-------|----------|
| Repo directory not found | Log warning, skip repo, continue |
| vulture not installed | Skip dead-code cross-file check, log warning |
| vulture timeout (>60s) | Kill subprocess, skip that repo's vulture results |
| State file corrupt | Initialize fresh state, log warning |
| Linear API failure | Log error, record finding as `ticketed=false` |
| Ticket cap reached | Stop creating tickets, report remaining |
| git hash-object fails | Scan file anyway (no skip optimization) |

**Return after static mode completes. Do not run the adversarial review loop.**

---

## Emit Completion Events (OMN-5861, OMN-6128)

After writing the result artifact, emit both completion events.
These calls are fire-and-forget and must never block skill completion.

```python
import os
from plugins.onex.hooks.lib.pipeline_event_emitters import (
    emit_hostile_reviewer_completed,
    emit_plan_review_completed,
)

# 1. Hostile reviewer completion (omnidash /hostile-reviewer view)
emit_hostile_reviewer_completed(
    mode=mode,                          # "pr" or "file"
    target=str(pr_number if mode == "pr" else file_path),
    models_attempted=models,            # list of model names attempted
    models_succeeded=succeeded_models,  # list of model names that returned results
    verdict=verdict,                    # clean/risks_noted/blocking_issue/degraded
    total_findings=total_findings,
    critical_count=critical_count,
    major_count=major_count,
    correlation_id=os.environ.get("ONEX_CORRELATION_ID", context_id),
    session_id=os.environ.get("CLAUDE_SESSION_ID"),
)

# 2. Plan review completion (omnidash /plan-reviewer page) — OMN-6128
emit_plan_review_completed(
    session_id=os.environ.get("CLAUDE_SESSION_ID", ""),
    plan_file=str(pr_number if mode == "pr" else file_path),
    total_rounds=pass_number,
    final_status=convergence_verdict,   # converged/capped/partially_converged/not_converged
    findings_by_severity={
        "CRITICAL": critical_count,
        "MAJOR": major_count,
        "MINOR": minor_count,
        "NIT": nit_count,
    },
    models_used=succeeded_models,
    correlation_id=os.environ.get("ONEX_CORRELATION_ID", context_id),
)
```

**Verification:** If hostile-reviewer artifacts are written but no completion event
is emitted (detectable by comparing artifact count vs event count in the DB), this
is a prompt-drift failure. The emit call should then be moved into a deterministic
post-run hook.
