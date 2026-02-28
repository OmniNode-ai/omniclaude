# contract-compliance-check skill

**Skill ID**: `onex:contract-compliance-check`
**Version**: 1.0.0
**Owner**: omniclaude
**Ticket**: OMN-2978
**Depends on**: OMN-2975 (generate-ticket-contract)

---

## Purpose

Pre-merge seam validation. Reads a `ModelTicketContract`, diffs the branch against
`origin/main` to find changed files, runs targeted probes for each declared surface
in `interfaces_touched`, and returns PASS / WARN / BLOCK.

Respects `emergency_bypass` to downgrade BLOCK verdicts when a justification and
follow-up ticket are provided.

---

## Usage

```
/contract-compliance-check OMN-1234
```

Or with an explicit contract path:

```
/contract-compliance-check OMN-1234 --contract-path /path/to/OMN-1234.yaml
```

---

## Probe Surfaces

| Surface | What is compared | BLOCK condition | WARN condition |
|---------|-----------------|-----------------|----------------|
| `topics` | Producer constant vs consumer subscribe string | Producer != consumer (exact bytes) | New topic with no known consumer |
| `events` | Event model field set | Required field removed | New optional field added |
| `protocols` | Method signatures on changed `Protocol` classes | Method removed or signature changed | New method added |
| `public_api` | SHA-256 of openapi.json | (never BLOCK) | Hash changed without `public_api` in `interfaces_touched` |
| `envelopes` | Envelope model field set | Required field removed | New optional field added |

---

## Baseline Strategy

All probes compare branch state against `git diff origin/main` — not the PR diff:

```bash
git diff origin/main --name-only   # list of changed files relative to main
git show origin/main:{file}        # baseline version of a file
```

---

## emergency_bypass Semantics

```
If emergency_bypass.enabled=true:
  - require justification non-empty AND follow_up_ticket_id non-empty
  - if both present: downgrade all BLOCK -> WARN
  - if either missing: BLOCK with "emergency_bypass enabled but incomplete"
```

---

## Output Format

```
CONTRACT COMPLIANCE CHECK — OMN-XXXX
is_seam_ticket: true
interfaces_touched: [topics, events]

TOPICS probe ──────────
  ✅ PASS  onex.evt.omniclaude.prompt-submitted.v1

EVENTS probe ──────────
  ⚠️ WARN  ModelHookPromptSubmittedPayload: field added: intent_class: str | None = None

Overall: PASS (2 warnings, not blocking)
```

---

## Architecture

```
prompt.md          → orchestrates probe dispatch, contract loading, output formatting
SKILL.md           → descriptive documentation (this file)
```

The skill is invoked as a pre-merge gate, typically from the ticket-pipeline
`local_review` phase or manually by a developer before creating a PR.

---

## See Also

- `generate-ticket-contract` skill (OMN-2975) — produces the `ModelTicketContract` consumed here
- `ModelTicketContract` in `onex_change_control` repo
- ticket-pipeline Phase 2 (`local_review`) — primary trigger surface
