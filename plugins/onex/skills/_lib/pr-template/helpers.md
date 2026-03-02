# PR Template Helpers

## Required PR Template Sections

Every PR created by the pipeline MUST include all five sections below. Missing sections
cause the PR to stay as Draft and trigger a `pr-blocked` label.

### Template

```
## Scope
- **Changes:** {what changed — be specific, not "added feature"}
- **Explicitly NOT changing:** {what was in scope but excluded}

## Touch List
- {path/to/file.py}: {why this file was modified}
- {path/to/other.py}: {why this file was modified}

## Risks
1. {risk description} — Detection: {how you would know if this broke}
2. {risk description} — Detection: {how you would know if this broke}

## Test Evidence
- **Ran:** {exact pytest command(s) run}
- **Result:** {PASSED / N tests, 0 failures}
- **Skipped (and why):** {list or "none"}

## Rollback Plan
- **Revert safe:** YES / NO
- **Notes:** {migration files? data mutations? downstream consumers?}

## Ticket Context Bundle
- **Bundle ID:** {tcb id or "none — not generated"}
- **Created:** {date or "N/A"}
- **Top entrypoints:** {comma-separated or "N/A"}
- **Top tests cited:** {comma-separated or "N/A"}
- **Top constraints:** {comma-separated or "N/A"}
```

## Validation Logic

When `validate_pr_template(body)` is called:

1. Check for presence of all six headers: `## Scope`, `## Touch List`, `## Risks`,
   `## Test Evidence`, `## Rollback Plan`, `## Ticket Context Bundle`
2. Check that `## Risks` section contains at least two lines starting with `1.` and `2.`
3. Check that `## Scope` contains both `Changes:` and `NOT changing:` (or equivalent)
4. Check that `## Test Evidence` contains `Ran:` and `Result:`
5. Return `(True, [])` if all pass
6. Return `(False, [list of missing/incomplete sections])` if any fail

## Template Generation

When `generate_pr_template(ticket_id, tcb_id=None, tcb_entrypoints=None, tcb_tests=None, tcb_constraints=None)` is called:

Return the template above with TCB fields populated if provided, or filled with "N/A" placeholders.

If `tcb_entrypoints` is a non-empty list, render as comma-separated string (max 5 items).
If `tcb_tests` is a non-empty list, render as comma-separated string (max 8 items).
If `tcb_constraints` is a non-empty list, render as comma-separated string (max 5 items).
