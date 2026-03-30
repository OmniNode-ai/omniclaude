# Refill Sprint

You are executing the refill-sprint skill. This prompt is the authoritative operational guide. Follow it exactly.

## Argument Parsing

```
/refill-sprint [--dry-run] [--threshold N] [--batch-size N] [--skip-scope-check]
```

```python
args = "$ARGUMENTS".split() if "$ARGUMENTS".strip() else []

dry_run = "--dry-run" in args
skip_scope_check = "--skip-scope-check" in args

threshold = 5.0
if "--threshold" in args:
    idx = args.index("--threshold")
    if idx + 1 < len(args):
        threshold = float(args[idx + 1])

batch_size = 10
if "--batch-size" in args:
    idx = args.index("--batch-size")
    if idx + 1 < len(args):
        batch_size = int(args[idx + 1])
```

## Phase 1: Capacity Check

Use the Linear MCP tools to check Active Sprint capacity.

1. List issues in Active Sprint project with state "Backlog" or "Todo"
2. Filter to tickets with NO active PR (no `attachments` with GitHub PR URLs, or PR is not open)
3. Compute weighted capacity:
   - Each ticket's weight = its estimate value (if set), else 1.0 (Medium default)
   - Sum all weights
4. If weighted capacity >= `threshold`:
   - Report: "Active Sprint has sufficient capacity ({capacity} >= {threshold}). No pull needed."
   - Exit successfully

## Phase 2: Candidate Selection

Query Future project for tech debt candidates. Apply selection tiers in order until batch-size is reached:

### Tier 1: Labeled tech debt
```
List issues in Future project with labels: type-suppression, lint-suppression, any-type-narrowing, skipped-tests
Filter: estimate <= Medium (or no estimate), priority != Urgent
```

### Tier 2: Friction-labeled
```
List issues in Future project with label: friction
Same filters as Tier 1
```

### Tier 3: Keyword match (fallback)
```
Search Future project for issues matching: tech debt, tech-debt, cleanup, refactor, dead code, deprecated
Same filters as Tier 1
```

### Exclusion rules (apply to all tiers)

For each candidate, check:

1. **Estimate gate**: If estimate is Large or XL, skip with reason "too large for auto-pull"
2. **Priority gate**: If priority is Urgent, skip with reason "urgent/strategic ticket"
3. **Cross-repo gate**: Use `get_issue` with `includeRelations: true`. If ticket has children or blockers in a different repo than the ticket itself, skip with reason "cross-repo dependency"
4. **Zombie gate**: Use `list_comments` on the ticket. Count comments containing `[auto-pull-attempt]`. If count >= 2, skip with reason "2+ failed attempts"
5. **Same-day return gate**: Check comments for `[auto-pull-return]` with today's date. If found, skip with reason "returned to Future today"

Collect up to `batch_size` candidates across all tiers.

## Phase 3: Scope Verification

Skip this phase if `--skip-scope-check` is set.

For each candidate:

1. Read the ticket description
2. If the description references specific file paths, use Glob/Grep to verify they still exist
3. If the ticket has a DoD checklist (lines starting with `- [ ]`):
   - For each item, check if the referenced code/file/API still exists
   - Count stale items (referenced thing no longer exists)
   - If >50% stale, mark candidate as "needs-human-review" and skip it
4. If the ticket has no labels, suggest appropriate labels based on content

Report verification results for each candidate.

## Phase 4: Pull and Label

If `--dry-run`, report what WOULD be pulled and exit.

For each verified candidate (up to batch-size):

1. Update the ticket:
   ```
   save_issue(id=ticket_id, project="Active Sprint", labels=["auto-pulled"])
   ```

2. Add a comment:
   ```
   save_comment(issueId=ticket_id, body="**[auto-pull]** Moved to Active Sprint by `/refill-sprint`.\n\n**Time-box**: 30 min wall clock / 20 tool calls.\n**Policy**: If time-box exceeded, ticket returns to Future with `[auto-pull-return]` comment.\n**Attempt tracking**: This is attempt #{n} (counted from `[auto-pull-attempt]` comments).")
   ```

3. Track the pull in a summary list

## Phase 5: Notification and Events

### Kafka emission

Emit event to `onex.evt.omniclaude.sprint-auto-pull-completed.v1`:
```json
{
  "pulled_count": N,
  "skipped_count": M,
  "candidates_evaluated": K,
  "tiers_used": ["tier1", "tier2"],
  "exhausted": false,
  "dry_run": false
}
```

If no eligible candidates found at all, also emit to `onex.evt.omniclaude.tech-debt-queue-empty.v1`.

### Discord notification

Rate-limit: only notify if pulled_count > 0 AND no `/refill-sprint` Discord notification was sent in the last hour.

Message format:
```
**Sprint Refill**: Pulled {N} tech debt ticket(s) into Active Sprint.
Tickets: {list of OMN-XXXX titles}
Skipped: {M} (reasons: {summary})
```

If tech debt queue is exhausted:
```
**Sprint Refill**: Tech debt queue in Future is empty. No eligible tickets to pull.
```

## Output

Print a summary table:

```
## Refill Sprint Summary

| Metric | Value |
|--------|-------|
| Capacity before | {weighted_capacity} |
| Threshold | {threshold} |
| Candidates evaluated | {count} |
| Pulled | {count} |
| Skipped | {count} |
| Exhausted | {yes/no} |

### Pulled Tickets
- OMN-XXXX: {title} (tier: {tier}, estimate: {estimate})

### Skipped Tickets
- OMN-YYYY: {title} (reason: {reason})
```
