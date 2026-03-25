# CI Recovery -- Authoritative Behavioral Specification

> **Authoritative behavior is defined here; `SKILL.md` is descriptive. When docs conflict,
> `prompt.md` wins.**

## Failure Classification Heuristics

The classifier (`plugins/onex/skills/_lib/ci_recovery/classifier.py`) uses a priority-ordered
cascade. The first matching rule wins.

### 1. flaky_test

**Triggers:**
- Test name substring appears in the known-flaky list
- Same test passed on a re-run within the last 7 days (query via `gh run list`)

**Remediation:**
```bash
gh run rerun {run_id} --failed --repo {repo}
```

Re-run only failed jobs, not the entire workflow. This minimizes compute cost.

### 2. infra_issue

**Triggers (case-insensitive):**
- Log contains any of: `runner`, `timeout`, `network`, `connection refused`, `503`, `lost connection`

**Remediation:**
```bash
gh run rerun {run_id} --repo {repo}
```

Full re-run (not `--failed`) because infrastructure issues may affect all jobs.
Log the failure for infrastructure team review.

### 3. config_error

**Triggers (case-insensitive):**
- Log contains any of: `lock file`, `uv.lock`, `version mismatch`, `missing dependency`

**Remediation:**
```
Skill(skill="onex:ci-fix-pipeline", args="--pr {N} --ticket-id {T}")
```

Dispatch a fix agent to update configuration files (lock files, dependency versions).

### 4. real_failure

**Triggers:**
- None of the above patterns match (default classification)

**Remediation:**
```
Skill(skill="onex:ci-fix-pipeline", args="--pr {N} --ticket-id {T}")
```

Dispatch a targeted fix agent. The ci-fix-pipeline will analyze the failure log and
apply the appropriate fix strategy (via `RepairStrategy` rotation in `node_ci_repair_effect`).

## Execution Protocol

1. **Scan**: List all open PRs across repos
   ```bash
   gh pr list --state open --repo {repo} --json number,headRefName,statusCheckRollup --limit 100
   ```

2. **Filter**: Select PRs where `statusCheckRollup` contains any `FAILURE` or `ERROR` conclusion

3. **Classify**: For each failing PR:
   ```bash
   # Get the latest failed run
   BRANCH=$(gh pr view {pr_number} --repo {repo} --json headRefName -q '.headRefName')
   RUN_ID=$(gh run list --branch "$BRANCH" --repo {repo} -L 1 --json databaseId,conclusion \
     -q '[.[] | select(.conclusion == "failure")][0].databaseId')

   # Extract failure log
   gh run view "$RUN_ID" --repo {repo} --log-failed 2>/dev/null | tail -200
   ```

4. **Remediate**: Apply the classification-specific remediation (see above)

5. **Report**: Write structured report to `~/.claude/ci-recovery/reports/`

## Budget Controls

- `--max-fixes-per-cycle` (default 10): Stop dispatching fix agents after this many
- Each fix dispatch counts against the budget regardless of classification
- Re-runs (`gh run rerun`) do NOT count against the budget (they are cheap)
- When budget is exhausted, remaining failures are logged but not remediated

## Dry Run Behavior

With `--dry-run`:
- Scan and classify all PRs normally
- Log what remediation WOULD be applied
- Write the report with `"result": "dry_run"` for each classification
- Do not execute any `gh run rerun` or fix dispatch commands

## Integration with Overnight Scheduling

The `scripts/ci-recovery-overnight.plist` launchd agent (from PR #883) runs this skill
at configured intervals. The plist invokes:

```bash
claude -p "Run /onex:ci-recovery --max-fixes-per-cycle 10"
```

Environment variables required:
- `ANTHROPIC_API_KEY` -- for Claude API access
- `GITHUB_TOKEN` -- for `gh` CLI access
- `LINEAR_API_KEY` -- for ticket updates (optional)
