# Self-Correcting Epic Agent — Behavioral Specification

> This is the authoritative behavioral specification for the self-correcting-epic skill.
> When SKILL.md and prompt.md conflict, prompt.md wins.

## Purpose

Wrap `epic_team` with per-agent validation gates that catch scope violations, test failures,
broken parent links, and repeated failures — without human correction. The goal is to push
the fully_achieved rate on epic orchestration from ~60% to 90%+.

---

## Gate Behaviors

### Gate 1: Pre-flight Scope Check

**When**: Before dispatching `ticket-pipeline` for each ticket.

**How**:
1. Run `epic_preflight_gate.sh` with env: `TICKET_ID`, `TICKET_REPO`, `EPIC_ID`
2. If TICKET_REPO is empty or the ticket description doesn't map to exactly one repo, the
   gate exits 1 and the ticket is SKIPPED (not dispatched).
3. If `scope_check` skill has been run for this epic (producing a scope manifest), verify the
   ticket's declared files fall within the manifest. Warn on ambiguous adjacent files; hard
   block on clearly out-of-scope files.

**On failure**: Log the skip to `state.yaml` with `skipped_reason: "preflight_failed"`.
Continue to the next ticket in the wave.

---

### Gate 2: Post-action Validation

**When**: After each `ticket-pipeline` completes (regardless of pipeline outcome).

**How**:
1. Run `epic_postaction_gate.sh` with env: `WORKTREE_PATH`, `TICKET_ID`
2. The gate runs `pytest -x --timeout=120` and `pre-commit run --all-files` in the worktree
3. If either fails, the gate exits 1 and writes structured JSON to GATE_RESULT_FILE

**On failure**: Retry the ticket once (re-dispatch `ticket-pipeline`). If the retry also
fails post-action, escalate via Gate 5.

**Structured result** (written to `GATE_RESULT_FILE`):
```json
{"ticket_id": "OMN-XXXX", "pytest_exit": 0, "precommit_exit": 1, "passed": 0}
```

---

### Gate 3: Parent Epic Verification

**When**: After each wave completes (all tickets in the wave have been dispatched and resolved).

**How**:
1. For each completed ticket in the wave, query Linear:
   ```bash
   gh api graphql -f query='{ issue(id: "<ticket_id>") { parent { id identifier } } }'
   ```
2. Verify the parent matches the expected EPIC_ID.

**On failure**: Log a WARNING but do NOT block. Parent re-parenting is usually accidental and
non-critical. The log entry includes the mismatched parent ID for manual review.

---

### Gate 4: Coordinator Audit

**When**: Before auto-merge of each PR.

**How**:
1. Get the PR diff file list: `gh pr diff {pr_number} --stat`
2. Extract the list of changed files from the diff
3. Compare against the ticket's declared scope (from Linear description or scope manifest)
4. If files outside the declared scope are modified, the audit FAILS

**On failure**: Block auto-merge. Log a scope violation with the specific out-of-scope files.
The PR remains open for manual review. This uses the same scope detection pattern as the
changeset guard hook (PR #883).

---

### Gate 5: Failure Escalation (Two-Strike Diagnosis Protocol)

**When**: After 2 failed retries of any ticket (Gate 2 failure -> retry -> Gate 2 failure again).

**How**:
1. Write `docs/diagnosis-{ticket-id}.md` with the required four sections:
   - **What is known** — observable facts, error messages, gate result JSON
   - **What was tried and why it failed** — both attempts with their outcomes
   - **Root cause hypothesis** — best current understanding
   - **Proposed fix with rationale** — the next step a human should try
2. Update `state.yaml` for that ticket: `escalated: true`, `escalation_doc: "docs/diagnosis-{ticket-id}.md"`
3. Skip the ticket and continue with remaining tickets in the epic

**Important**: This follows the Two-Strike Diagnosis Protocol from `~/.claude/CLAUDE.md`.
The agent MUST NOT attempt a third fix. Write the diagnosis and move on.

---

## Orchestration Flow

```
self-correcting-epic OMN-XXXX
  -> Fetch child tickets from Linear (same as epic_team)
  -> Group into waves (same as epic_team)
  -> For each wave:
      -> For each ticket in wave:
          -> [GATE 1] Pre-flight scope check
          -> IF pass: Dispatch ticket-pipeline
          -> [GATE 2] Post-action validation
          -> IF fail: Retry once, then [GATE 5] escalate
      -> [GATE 3] Parent epic verification for all completed tickets
  -> For each PR ready to merge:
      -> [GATE 4] Coordinator audit
      -> IF pass: auto-merge
      -> IF fail: leave PR open, log scope violation
  -> Write final report
```

## Integration with epic_team

This skill WRAPS epic_team. It does NOT replace it. The composition is:

1. Self-correcting-epic calls epic_team's wave planning and ticket grouping logic
2. For each ticket dispatch, self-correcting-epic inserts gates before and after
3. epic_team's Slack notifications, worktree creation, and lifecycle management are unchanged

If `--skip-gates` is passed, the specified gates are disabled and the skill behaves like
vanilla epic_team for those checkpoints.

## Dry-Run Mode

When `--dry-run` is passed:
1. Fetch child tickets from Linear
2. Group into waves
3. For each ticket, print what gates would fire and what checks would run
4. Do NOT dispatch ticket-pipeline or run any gate scripts
5. Print a summary: "Would dispatch N tickets across M waves with gates: [list]"

## Report Output

Final report written to `~/.claude/skill-results/{context_id}/self-correcting-epic.json`:

```json
{
  "skill_name": "self-correcting-epic",
  "status": "success|partial|error",
  "extra_status": "all_passed|some_escalated|failed",
  "extra": {
    "tickets_total": 15,
    "tickets_passed": 12,
    "tickets_skipped_preflight": 1,
    "tickets_escalated": 2,
    "gates_triggered": 45,
    "gates_passed": 40,
    "gates_failed": 5,
    "parent_mismatches": 0,
    "scope_violations": 1
  }
}
```

## See Also

- `SKILL.md` — front-matter, gate table, script references
- `epic_team` skill — base orchestration (wrapped by this skill)
- `scope_check` skill — pre-flight scope validation (PR #883)
- `epic_preflight_gate.sh` — pre-flight gate script
- `epic_postaction_gate.sh` — post-action gate script
- Two-Strike Diagnosis Protocol — `~/.claude/CLAUDE.md`
