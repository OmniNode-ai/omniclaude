---
description: "DoD compliance sweep -- retroactive batch audit or targeted pre-close gate"
version: 1.0.0
mode: full
level: advanced
debug: false
category: verification
tags: [dod, sweep, compliance, contracts, evidence, autonomous]
composable: true
args:
  - name: target
    description: "Optional OMN-XXXX epic/ticket ID for targeted mode (omit for batch)"
    required: false
  - name: --since-days
    description: "Look-back window for batch mode (default: 7)"
    required: false
  - name: --dry-run
    description: "Report only, no follow-up tickets"
    required: false
---

# DoD Compliance Sweep

Validate Definition of Done compliance across closed epics/tickets. Operates in
two modes: **batch** (retroactive sweep of recently completed tickets) and
**targeted** (pre-close gate for a specific epic or ticket).

## Dual Mode

- **Batch** (`/dod-sweep`): Query Linear for tickets completed in the lookback
  window via `mcp__linear-server__list_issues`, filter by `completedAt`.
- **Targeted** (`/dod-sweep OMN-1234`): If the target is an epic, expand child
  tickets. If a single ticket, sweep just that one.

## Check Confidence Tiers

The 6 per-ticket checks are organized into two confidence tiers:

### Primary (Artifact Checks -- High Confidence)

Deterministic file existence and content parsing. If the file is there and
parseable, the check is authoritative.

1. **CONTRACT_EXISTS**: `ls $ONEX_CC_REPO_PATH/contracts/{ticket_id}.yaml`
2. **RECEIPT_EXISTS**: Check deterministic location
   `$ONEX_CC_REPO_PATH/.evidence/{ticket_id}/dod_report.json` first, then
   `$ONEX_STATE_DIR` as fallback. In targeted mode, also validate receipt
   freshness -- receipt must be newer than the ticket's `completedAt` date.
3. **RECEIPT_CLEAN**: Parse receipt JSON, verify `result.failed == 0`.

### Supporting (Operational Checks -- Medium Confidence)

Depends on cross-repo search, SHA linkage, and drift artifact grep. Can produce
UNKNOWN when linkage cannot be established cleanly.

4. **PR_MERGED**: `gh pr list --search "{ticket_id}" --state merged --json number`
   across repos. If no PR found, record `UNKNOWN` with detail "No merged PR found
   matching ticket ID -- may indicate PR title/branch naming mismatch" rather than
   hard FAIL.
5. **CI_GREEN**: `gh api repos/{org}/{repo}/commits/{merge_sha}/check-runs` --
   verify all conclusions are "success". If merge SHA cannot be determined, record
   `UNKNOWN`.
6. **INTEGRATION_SWEEP_EVIDENCE**: If contract has `interfaces_touched`, grep
   `$ONEX_CC_REPO_PATH/drift/integration/*.yaml` for ticket_id. This verifies
   presence of sweep evidence linked to the ticket, not substantive correctness
   of every relevant integration surface. If no `interfaces_touched`, this check
   is automatically PASS (not applicable).

## Receipt Freshness Doctrine (Targeted Mode Only)

In targeted mode (pre-close gate), receipts must be associated with the
completion being audited, not merely exist from some historical run:

- Validate: receipt timestamp > ticket's `completedAt` date, OR receipt was
  generated within the current session.
- Deterministic ticket-specific receipt locations
  (`$ONEX_CC_REPO_PATH/.evidence/{ticket_id}/dod_report.json`) are preferred
  over broad `find` discovery to prevent false association.
- In batch mode (retroactive sweep), existence-only is acceptable since the
  goal is historical audit, not real-time gating.

## UNKNOWN Semantics

UNKNOWN is not a single state. It may represent:

| Meaning | Example | Gate behavior |
|---------|---------|---------------|
| Exempt / not checked | Ticket predates contract system | Non-blocking |
| Inconclusive linkage | PR search found no match by ticket ID | Non-blocking if primary checks pass |
| Mixed check state | Some checks PASS, others UNKNOWN | Non-blocking but flagged |
| No evidence-backed passes | All tickets exempt | Non-blocking (rollout accommodation) |

## Targeted-Mode Gate Decision Matrix

| Primary checks | Supporting checks | Gate result | Action |
|---------------|-------------------|-------------|--------|
| Any FAIL | anything | BLOCK | Create follow-up tickets |
| All PASS | All PASS | ALLOW CLEAN | Mark epic Done |
| All PASS | Some UNKNOWN | ALLOW WITH WARNING | Mark epic Done, post warning |
| All PASS | Any FAIL | ALLOW WITH FOLLOW-UP | Mark epic Done, create follow-up |
| All exempt | n/a | ALLOW UNKNOWN-REVIEW | Mark epic Done (rollout accommodation) |

## Exemption Handling

1. Load `$ONEX_CC_REPO_PATH/dod_sweep_exemptions.yaml`
2. Skip tickets completed before cutoff_date
3. Skip explicitly exempted ticket IDs
4. Check `expires_on` if present -- expired exemptions are no longer valid

## Follow-Up Ticket Creation and Dedup

For each failed ticket (when not `--dry-run`):

1. Search existing open tickets for `[dod-sweep-gap:{ticket_id}]` marker in
   description. If found and still open, update the existing ticket's description
   with the current failed check set rather than creating a duplicate.
2. If found but closed (gap recurred), create a new ticket with reference to the
   previous closed one.
3. On recurrence, record the delta explicitly (prior state vs current failed state)
   rather than silently overwriting history.

Follow-up ticket format:
- Title: `fix: DoD gap -- {ticket_id} -- {failed_check_names}`
- Parent: same epic as the original ticket
- Description includes: which checks failed, passed, and UNKNOWN, with confidence
  tier of each failed check

## Report Output

1. Write `ModelDodSweepResult` YAML to
   `$ONEX_CC_REPO_PATH/drift/dod_sweep/{date}.yaml`
2. Print summary table to stdout -- table distinguishes passed, failed, exempted,
   and UNKNOWN counts
3. Emit `dod.sweep.completed` Kafka event (non-blocking)

## Recurring Usage

```
/loop 2h /onex:dod_sweep --dry-run
/loop daily /onex:dod_sweep
```
