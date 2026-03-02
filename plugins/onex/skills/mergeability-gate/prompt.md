# Mergeability Gate

You are evaluating PR #{pr_number} in {repo} for mergeability.

## Step 1: Fetch PR state

Run:
```
gh pr view {pr_number} --repo {repo} --json body,mergeable,statusCheckRollup,additions,deletions,files,labels
```

Extract:
- `body` → run `validate_pr_template(body)` from `@_lib/pr-template/helpers.md`
- `mergeable` → check for `CONFLICTING`
- `statusCheckRollup` → check for any `FAILURE` state
- `additions + deletions` → net diff size
- `files` → count distinct module prefixes

## Step 2: Evaluate blocked criteria

Check each criterion:
1. Template validation: `validate_pr_template(body)` → if `(False, reasons)`, add reasons to `blocked_reasons`
2. CI status: if any check is `FAILURE`, add `"CI failing: {check_name}"` to `blocked_reasons`
3. Conflicts: if `mergeable == "CONFLICTING"`, add `"merge conflicts present"` to `blocked_reasons`

## Step 3: Evaluate needs-split criteria

1. Net diff: if `additions + deletions > 500` and not waived, add to `split_reasons`
2. Mixed concerns: if more than 2 top-level directories changed (excluding tests/docs), add to `split_reasons`
3. Migrations: count files matching `*/migrations/*.py`; if more than 3, add to `split_reasons`

**File-type threshold override:** If ALL changed files are test files or documentation files
(matching `tests/`, `docs/`, `*.md`, `*_test.py`), the net diff threshold rises to 1000 lines
before triggering `needs-split`.

## Step 4: Determine final status

```
if blocked_reasons is not empty → status = "blocked"
else if split_reasons is not empty → status = "needs-split"
else → status = "mergeable"
```

## Step 5: Apply label and write result

Apply GitHub label. Use the gh CLI to add the appropriate label and remove the others:

For status "mergeable":
```
gh pr edit {pr_number} --repo {repo} --add-label "mergeable"
gh pr edit {pr_number} --repo {repo} --remove-label "blocked"
gh pr edit {pr_number} --repo {repo} --remove-label "needs-split"
```

For status "needs-split":
```
gh pr edit {pr_number} --repo {repo} --add-label "needs-split"
gh pr edit {pr_number} --repo {repo} --remove-label "mergeable"
gh pr edit {pr_number} --repo {repo} --remove-label "blocked"
```

For status "blocked":
```
gh pr edit {pr_number} --repo {repo} --add-label "blocked"
gh pr edit {pr_number} --repo {repo} --remove-label "mergeable"
gh pr edit {pr_number} --repo {repo} --remove-label "needs-split"
```

Run each label command independently. If a remove-label command fails because the label
does not exist, that is not an error — continue.

If a label does not exist in the repo, create it first:
```
gh label create {label_name} --repo {repo} --color "#0075ca"
```

Write result JSON to `~/.claude/skill-results/{context_id}/mergeability-gate.json`:
```json
{
  "status": "<mergeable|needs-split|blocked>",
  "pr_number": <pr_number>,
  "repo": "<repo>",
  "blocked_reasons": [],
  "split_reasons": [],
  "waived_reasons": [],
  "evaluated_at": "<ISO8601 timestamp>"
}
```

## Step 6: Post comment on blocked or needs-split

If status is "blocked":
Post a PR comment listing each blocked reason:
```
gh pr comment {pr_number} --repo {repo} --body "**Mergeability Gate: BLOCKED**

The following issues must be resolved before this PR can merge:
{blocked_reasons as numbered list}"
```

If status is "needs-split":
Post a PR comment listing each split reason:
```
gh pr comment {pr_number} --repo {repo} --body "**Mergeability Gate: NEEDS SPLIT (advisory)**

This PR may benefit from being split:
{split_reasons as numbered list}

This is advisory — the pipeline will continue but the agent should consider restructuring."
```

## Step 7: If blocked — post HIGH_RISK Slack gate

If status is "blocked", post a HIGH_RISK Slack gate notification and halt:

```
[HIGH_RISK] Mergeability gate BLOCKED for {ticket_id} PR #{pr_number}
Repo: {repo}
Blocked reasons:
{blocked_reasons as bullet list}

Reply "unblock {ticket_id}" once issues are resolved to re-run the gate.
Reply "skip-gate {ticket_id} <justification>" to bypass (use only when justified).
```

Wait for operator reply before continuing.
- "unblock {ticket_id}": re-run the gate from Step 1
- "skip-gate {ticket_id} <justification>": record justification in result JSON, set status to "mergeable", advance
- No reply within 48 hours: expire with status "timeout", clear ledger entry
