---
name: generate-ticket-contract
description: Auto-draft a ModelTicketContract YAML from ticket context with two-layer architecture — prompt generation and Python validation
---

# generate-ticket-contract skill

**Skill ID**: `onex:generate-ticket-contract`
**Version**: 1.0.0
**Owner**: omniclaude
**Ticket**: OMN-2975

---

## Purpose

Auto-draft a `ModelTicketContract` YAML from ticket context. Two-layer architecture:
the prompt generates the YAML text, a thin Python validator validates it against
`ModelTicketContract` before output.

If `ONEX_CC_REPO_PATH` is set, the contract is written to
`$ONEX_CC_REPO_PATH/contracts/{ticket_id}.yaml`. Otherwise the YAML is printed with a
warning banner.

---

## Usage

```
/generate-ticket-contract OMN-1234
```

Or with an explicit ticket description piped in:

```
/generate-ticket-contract OMN-1234 --description "Implement Kafka consumer for agent events"
```

---

## Architecture

```
Prompt layer       → generates YAML text (seam detection, inference, stubs)
Python validator   → validate_contract.py imports ModelTicketContract,
                     calls model_validate(yaml_dict), prints field-level errors
```

### Seam detection heuristics

The prompt layer scans the ticket title and description for signals that indicate
interface seams. When a seam is detected, the contract sets `is_seam_ticket: true`
and adds broader evidence requirements (unit + ci + integration).

| Signal | Detected interface |
|--------|--------------------|
| `kafka`, `topic`, `consumer`, `producer` | `topics` |
| `schema`, `payload`, `event model`, `ModelHook` | `events` |
| `SPI`, `protocol`, `interface` | `protocols` |
| `envelope`, `header` | `envelopes` |
| `endpoint`, `route`, `API`, `REST` | `public_api` |
| Multiple repo names mentioned | force `is_seam_ticket: true` |

---

## ONEX_CC_REPO_PATH preflight

- **Set**: validate path exists → write contract to
  `$ONEX_CC_REPO_PATH/contracts/{ticket_id}.yaml`
- **Not set**: print YAML with banner `WARNING: ONEX_CC_REPO_PATH not set — commit this manually`

---

## validate_contract.py

The Python validator is called by the prompt layer after YAML generation.
It exits 0 on valid YAML and exits 1 with field-level errors on invalid YAML.

```bash
# Exit 0 — valid
python plugins/onex/skills/generate-ticket-contract/validate_contract.py contract.yaml

# Exit 1 — shows field errors
python plugins/onex/skills/generate-ticket-contract/validate_contract.py bad_contract.yaml
```

---

## Output format

```yaml
ticket_id: OMN-1234
title: "Implement Kafka consumer for agent events"
description: "..."
is_seam_ticket: false
interfaces_touched: []
evidence_required:
  - unit
  - ci
requirements:
  - id: REQ-001
    statement: "..."
    acceptance:
      - "..."
verification_steps:
  - kind: unit
    command: "uv run pytest tests/unit/ -m unit"
    blocking: true
    status: pending
gates: []
```

---

## See Also

- `ModelTicketContract` — `omnibase_core.models.ticket.model_ticket_contract`
- `ticket-work` skill — consumes the generated contract
- `decision-store` skill — records architectural decisions from contracts
