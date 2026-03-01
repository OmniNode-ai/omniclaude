# CDQA Gate Helpers

**Shared gate protocol for all merge paths.**

Every merge path (ticket-pipeline Phase 5.5, auto-merge direct invocation) MUST run
these gates before invoking the merge mutation. There is no valid bypass that does not
require an explicit HIGH_RISK Slack gate.

**Implements**: OMN-3189
**Used by**: ticket-pipeline (Phase 5.5), auto-merge (pre-condition)

---

## Required Gates

All three gates must pass (or be explicitly bypassed via the bypass protocol below)
before any merge proceeds:

| Gate | Skill | BLOCK condition | WARN condition |
|------|-------|-----------------|----------------|
| **Contract Compliance** | `contract-compliance-check` | Required interface removed, topic mismatch | New optional field, hash change |
| **Arch Invariants CI** | CI check `arch-invariants` | Check conclusion `failure` or `cancelled` | Check conclusion `skipped` |
| **AI-Slop CI** | CI check `check-ai-slop` | Check conclusion `failure` or `cancelled` | Check conclusion `skipped` |

### Gate 1: contract-compliance-check

Run the `contract-compliance-check` skill against the PR:

```
Invoke: Skill(skill="onex:contract-compliance-check", args="{ticket_id}")
```

**Result routing**:
- `PASS` → proceed to Gate 2
- `WARN` → log warning, proceed to Gate 2 (warnings are non-blocking)
- `BLOCK` → post Slack HIGH_RISK bypass gate (see Bypass Protocol); halt until resolved

### Gate 2: arch-invariants CI check

Query the CI check named `arch-invariants` on the PR:

```bash
gh pr checks {pr_number} --repo {repo} --json name,conclusion \
  | python3 -c "import json,sys; checks=json.load(sys.stdin); \
    match=[c for c in checks if 'arch-invariants' in c['name']]; \
    print(match[0]['conclusion'] if match else 'not_found')"
```

**Result routing**:
- `success` → proceed to Gate 3
- `skipped` → log warning, proceed to Gate 3
- `failure` or `cancelled` → BLOCK; post Slack HIGH_RISK bypass gate
- `not_found` → log warning "arch-invariants check not found — skipping gate", proceed to Gate 3

### Gate 3: AI-slop CI check

Query the CI check named `check-ai-slop` on the PR:

```bash
gh pr checks {pr_number} --repo {repo} --json name,conclusion \
  | python3 -c "import json,sys; checks=json.load(sys.stdin); \
    match=[c for c in checks if 'check-ai-slop' in c['name'] or 'ai-slop' in c['name']]; \
    print(match[0]['conclusion'] if match else 'not_found')"
```

**Result routing**:
- `success` → all gates passed; proceed to merge
- `skipped` → log warning, proceed to merge
- `failure` or `cancelled` → BLOCK; post Slack HIGH_RISK bypass gate
- `not_found` → log warning "ai-slop check not found — skipping gate", proceed to merge

---

## Gate Result Recording

After all gates complete (pass or bypass), append a JSON record to:
`~/.claude/skill-results/{context_id}/cdqa-gate-log.json`

### Schema

```json
{
  "ticket_id": "OMN-XXXX",
  "pr_number": 123,
  "repo": "org/repo",
  "run_id": "run-omn-xxxx-001",
  "evaluated_at": "2026-02-28T12:00:00Z",
  "gates": {
    "contract_compliance": {
      "result": "PASS | WARN | BLOCK | bypassed",
      "detail": "free-text summary or bypass justification"
    },
    "arch_invariants_ci": {
      "result": "success | skipped | failure | not_found | bypassed",
      "check_conclusion": "success"
    },
    "ai_slop_ci": {
      "result": "success | skipped | failure | not_found | bypassed",
      "check_conclusion": "success"
    }
  },
  "overall": "PASS | WARN | BLOCK | bypassed",
  "bypass_used": false,
  "bypass_justification": null,
  "bypass_follow_up_ticket": null
}
```

**Append semantics**: if the file already exists (from a prior run or retry), append the new
record as an array element. The file is a JSON array of gate log records.

**File creation**: create with `[]` if it does not exist, then append.

---

## Bypass Protocol

A BLOCK result can only be bypassed via an explicit HIGH_RISK Slack gate. There is no
`--no-verify` flag, no silent skip, and no retry-without-fix.

### Anti-pattern: soft-pass

**INVALID**: Running the gate a second time without fixing the underlying issue is not a
valid bypass. A retry that passes only because the check was flaky must be logged as `WARN`,
not `PASS`. Do not retry BLOCK results to fish for a PASS.

### Bypass flow

When any gate returns BLOCK:

1. Post HIGH_RISK Slack gate:
   ```
   [HIGH_RISK] CDQA gate blocked for {ticket_id} PR #{pr_number}

   Gate: {gate_name}
   Result: BLOCK
   Detail: {block_reason}

   To bypass, reply:
     "cdqa-bypass {ticket_id} <justification> <follow_up_ticket_id>"

   Example:
     "cdqa-bypass OMN-1234 Emergency hotfix for prod outage OMN-1235"

   Silence = HOLD. No merge proceeds without explicit bypass or gate fix.
   ```

2. Wait for operator reply (poll every 5 minutes, up to `merge_gate_timeout_hours`):
   - `cdqa-bypass {ticket_id} <justification> <follow_up_ticket_id>`:
     - Validate: justification non-empty AND follow_up_ticket_id non-empty
     - If valid: downgrade BLOCK → WARN, record bypass in gate log, proceed to merge
     - If invalid (missing fields): re-post gate with error message, continue polling
   - Any other reply (hold, cancel, no): exit with `status: held`
   - Timeout: exit with `status: timeout`

3. Record bypass in gate log:
   ```json
   "bypass_used": true,
   "bypass_justification": "<justification text>",
   "bypass_follow_up_ticket": "<follow_up_ticket_id>"
   ```

---

## Usage in ticket-pipeline

The CDQA gate runs as **Phase 5.5** — after pr_review_loop (Phase 5) approves the PR
and before auto-merge (Phase 6) executes the merge.

```
Phase 5: pr_review_loop  → status: approved
Phase 5.5: cdqa_gate     → all gates PASS (or bypassed)  ← this phase
Phase 6: auto_merge      → merge executes
```

The orchestrator calls `run_cdqa_gate(ticket_id, pr_number, repo, context_id)` inline
(no separate Task dispatch — gates are fast CI reads and a single skill invocation).

If any gate BLOCKs and the operator holds (`status: held`), the pipeline exits cleanly.
The ledger entry is NOT cleared (same as Phase 6 held behavior). A new run resumes at
Phase 5.5 when the underlying issue is resolved.

---

## Usage in auto-merge (direct invocation)

When `auto-merge` is called directly (not from ticket-pipeline), it MUST run the CDQA
gates before proceeding. This prevents bypass via direct skill invocation.

Check whether CDQA gates have already run for this PR:
```
Read: ~/.claude/skill-results/{context_id}/cdqa-gate-log.json
If record exists with overall=PASS or overall=bypassed: skip re-run, proceed
If no record: run all 3 gates before merge
```

---

## See Also

- `contract-compliance-check` skill (OMN-2978) — Gate 1 implementation
- `ticket-pipeline` skill — Phase 5.5 orchestration
- `auto-merge` skill — direct invocation pre-condition
- `slack-gate` skill — HIGH_RISK gate primitives used in bypass flow
- OMN-3189 — implementation ticket
