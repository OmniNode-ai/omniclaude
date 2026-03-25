# Adversarial Review Gate -- Authoritative Behavioral Specification

> **Authoritative behavior is defined here; `SKILL.md` is descriptive. When docs conflict,
> `prompt.md` wins.**

## JSON Output Mode

When `--json` is passed, output the raw aggregated verdict JSON to stdout instead of
formatting as markdown. This enables CI integration where the verdict is parsed programmatically.

## Agent Dispatch

All 3 review agents are dispatched in parallel in a single message:

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="review-gate: scope review PR #{pr_number}",
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
  description="review-gate: correctness review PR #{pr_number}",
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
  description="review-gate: conventions review PR #{pr_number}",
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

## Verdict Collection

After all 3 agents return, collect their JSON verdicts. Parse each verdict and pass to the
aggregator:

```python
from plugins.onex.skills._lib.review_gate.aggregator import aggregate_verdicts

verdicts = [scope_verdict, correctness_verdict, conventions_verdict]
result = aggregate_verdicts(verdicts, strict=is_strict_mode)
```

## Gate Decision

Based on `result["gate_verdict"]`:

- **"pass"**: Write `ModelSkillResult` with `extra_status="passed"` and proceed
- **"fail"**: Write `ModelSkillResult` with `extra_status="blocked"`, post findings to PR

## Posting Findings to PR

When the gate fails, post a structured comment to the PR:

```markdown
## Review Gate: BLOCKED

| Severity | Agent | File | Line | Finding |
|----------|-------|------|------|---------|
| CRITICAL | scope | src/foo.py | 42 | Scope creep: file not in ticket scope |
| MAJOR | correctness | src/bar.py | 15 | Missing error handling for None case |

**{blocking_count} blocking finding(s).** Fix CRITICAL and MAJOR issues before merge.
```

## Retry Logic

When integrated with ticket-pipeline (Phase 8b):
1. If gate fails, dispatch fix agents for each CRITICAL/MAJOR finding
2. Re-run review gate (iteration 2 of 2 max)
3. If still blocked after 2 iterations, mark ticket as `review_gate_blocked` and skip

## Severity Guidelines

| Severity | Definition | Examples |
|----------|-----------|----------|
| CRITICAL | Security, data loss, crashes | SQL injection, unhandled None dereference, infinite loop |
| MAJOR | Bugs, missing tests, API issues | Logic error, untested branch, breaking API change |
| MINOR | Code quality, docs | Missing docstring, suboptimal algorithm, unclear naming |
| NIT | Style, preference | Trailing whitespace, import order, line length |
