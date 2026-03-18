# Mergeability Gate

You are evaluating PR #{pr_number} in {repo} for mergeability.

Import the PR safety library before any mutations:

```
@_lib/pr-safety/helpers.md
```

## Fetch PR state

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

## Evaluate blocked criteria

Check each criterion:
1. Template validation: `validate_pr_template(body)` → if `(False, reasons)`, add reasons to `blocked_reasons`
2. CI status: if any check is `FAILURE`, add `"CI failing: {check_name}"` to `blocked_reasons`
3. Conflicts: if `mergeable == "CONFLICTING"`, add `"merge conflicts present"` to `blocked_reasons`

## Evaluate needs-split criteria

1. Net diff: if `additions + deletions > 500` and not waived, add to `split_reasons`
2. Mixed concerns: if more than 2 top-level directories changed (excluding tests/docs), add to `split_reasons`
3. Migrations: count files matching `*/migrations/*.py`; if more than 3, add to `split_reasons`

**File-type threshold override:** If ALL changed files are test files or documentation files
(matching `tests/`, `docs/`, `*.md`, `*_test.py`), the net diff threshold rises to 1000 lines
before triggering `needs-split`.

## Determine final status

```
if blocked_reasons is not empty → status = "blocked"
else if split_reasons is not empty → status = "needs-split"
else → status = "mergeable"
```

## Apply label and write result

Apply GitHub label via `mutate_pr()` from `@_lib/pr-safety/helpers.md`:

```python
pr_key = validate_pr_key(f"{repo}#{pr_number}")

def apply_label(fresh_record):
    # Add status label and remove the other two
    label_map = {
        "mergeable": ("mergeable", ["blocked", "needs-split"]),
        "needs-split": ("needs-split", ["mergeable", "blocked"]),
        "blocked": ("blocked", ["mergeable", "needs-split"]),
    }
    add_label, remove_labels = label_map[status]

    # Create label if missing
    result = subprocess.run(
        ["gh", "label", "create", add_label, "--repo", repo, "--color", "#0075ca"],
        capture_output=True
    )
    # Apply add
    subprocess.run(["gh", "label", "add", add_label, "--issue", str(pr_number), "--repo", repo])
    # Remove others (ignore errors for missing labels)
    for lbl in remove_labels:
        subprocess.run(
            ["gh", "label", "remove", lbl, "--issue", str(pr_number), "--repo", repo],
            capture_output=True
        )
    return {"applied_label": add_label, "removed_labels": remove_labels}

mutate_pr(pr_key, action="apply_mergeability_label", run_id=run_id, fn=apply_label)
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

## Post comment on blocked or needs-split

Route comment through `mutate_pr()`:

```python
if status in ("blocked", "needs-split"):
    if status == "blocked":
        body = (
            "**Mergeability Gate: BLOCKED**\n\n"
            "The following issues must be resolved before this PR can merge:\n"
            + "\n".join(f"{i+1}. {r}" for i, r in enumerate(blocked_reasons))
        )
    else:
        body = (
            "**Mergeability Gate: NEEDS SPLIT (advisory)**\n\n"
            "This PR may benefit from being split:\n"
            + "\n".join(f"{i+1}. {r}" for i, r in enumerate(split_reasons))
            + "\n\nThis is advisory — the pipeline will continue but the agent should consider restructuring."
        )

    def post_comment(fresh_record, _body=body):
        subprocess.run(
            ["gh", "issue", "comment", str(pr_number), "--repo", repo, "--body", _body]
        )
        return {"comment_posted": True}

    mutate_pr(pr_key, action="post_mergeability_comment", run_id=run_id, fn=post_comment)
```

## If blocked — post HIGH_RISK Slack gate

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
