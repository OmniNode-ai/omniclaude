# generate-ticket-contract prompt

**Invocation**: `Skill(skill="onex:generate-ticket-contract", args="<ticket_id> [--description <text>]")`

---

## Overview

You are drafting a `ModelTicketContract` YAML for a Linear ticket. Follow the steps below
exactly. Do not skip validation.

---

## Step 1: Gather ticket context

1. Fetch the ticket from Linear using `mcp__linear-server__get_issue` with the provided ticket ID.
2. Extract: `title`, `description`, `labels`, parent epic (if any).
3. If `--description` was passed as an argument, use that text as the description (overrides Linear).

---

## Step 2: Seam detection

Scan the ticket title + description (case-insensitive) for the signals below.
Set `is_seam_ticket: true` if ANY signal is found, OR if more than one repository name
appears in the text.

| Signal keywords | Detected interface field |
|-----------------|--------------------------|
| `kafka`, `topic`, `consumer`, `producer` | `topics` |
| `schema`, `payload`, `event model`, `modelhook` | `events` |
| `spi`, `protocol`, `interface` | `protocols` |
| `envelope`, `header` | `envelopes` |
| `endpoint`, `route`, `api`, `rest` | `public_api` |

Collect all detected interface names into `interfaces_touched: [...]`.

**Evidence requirements:**
- Seam ticket (`is_seam_ticket: true`): `evidence_required: [unit, ci, integration]`
- Non-seam ticket: `evidence_required: [unit, ci]`

---

## Step 3: Draft the YAML

Generate a complete YAML block conforming to `ModelTicketContract`. Use the field reference below.

**Required fields:**

```yaml
ticket_id: <ticket_id>               # string, e.g. "OMN-1234"
title: <title>                        # string
description: <description>            # string
phase: intake                         # always "intake" for new contracts
is_seam_ticket: <bool>               # from Step 2
interfaces_touched: [...]             # list of strings from Step 2 (may be empty)
evidence_required: [...]              # [unit, ci] or [unit, ci, integration]
requirements:                         # list of ModelRequirement
  - id: REQ-001
    statement: <requirement text>
    acceptance:
      - <acceptance criterion>
verification_steps:                   # list of ModelVerificationStep
  - kind: unit
    command: "uv run pytest tests/unit/ -m unit -v"
    blocking: true
    status: pending
  - kind: ci
    command: "gh pr checks --repo <repo>"
    blocking: true
    status: pending
gates: []                             # empty for new contracts
interfaces_provided: []               # fill if seam ticket (see below)
interfaces_consumed: []               # fill if seam ticket (see below)
questions: []                         # clarifying questions if spec is ambiguous
```

**Seam ticket additions** — add one entry per detected interface in `interfaces_provided`:

```yaml
interfaces_provided:
  - name: <interface_name>
    kind: <topics|events|protocols|envelopes|public_api>
    surface: kafka|http|grpc|python
    definition_format: avro|json_schema|pydantic|openapi
    definition_location: src/...
    provided_by: <ticket_id>
    stub_ok: false
```

**Infer reasonable values** from the ticket description. Use `stub_ok: false` by default.
Use `stub_ok: true` only if the ticket explicitly states the interface is not yet finalized.

---

## Step 4: Validate the YAML

After drafting, call `validate_contract.py` to validate the YAML:

```bash
# Write the YAML to a temp file, then validate
TMPFILE=$(mktemp /tmp/contract-XXXX.yaml)
cat > "$TMPFILE" << 'YAML_EOF'
<paste the full YAML here>
YAML_EOF

python plugins/onex/skills/generate-ticket-contract/validate_contract.py "$TMPFILE"
EXIT_CODE=$?
```

If exit code is 1, read the error output, fix the YAML, and re-validate. Repeat until exit 0.

---

## Step 5: ONEX_CC_REPO_PATH preflight

```bash
if [ -n "$ONEX_CC_REPO_PATH" ]; then
    # Validate path exists
    if [ ! -d "$ONEX_CC_REPO_PATH" ]; then
        echo "ERROR: ONEX_CC_REPO_PATH is set but directory does not exist: $ONEX_CC_REPO_PATH"
        exit 1
    fi
    # Write contract
    mkdir -p "$ONEX_CC_REPO_PATH/contracts"
    cp "$TMPFILE" "$ONEX_CC_REPO_PATH/contracts/<ticket_id>.yaml"
    echo "Contract written to $ONEX_CC_REPO_PATH/contracts/<ticket_id>.yaml"
else
    echo "WARNING: ONEX_CC_REPO_PATH not set — commit this manually"
    cat "$TMPFILE"
fi
```

---

## Step 6: Output

Report to the user:
1. Whether `is_seam_ticket` was detected and which interfaces were found.
2. The full generated YAML (always print even if written to file).
3. Where the file was written (or the warning banner if not written).
4. Any validation errors encountered and how they were resolved.

---

## Error handling

- If the Linear ticket cannot be fetched: exit with an error message. Do not generate a contract.
- If validation fails after 3 attempts: print the last error and the draft YAML with a note
  that manual review is required.
- If `ONEX_CC_REPO_PATH` is set but the directory does not exist: print error and exit.
