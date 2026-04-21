# dod-verify

**Skill ID**: `onex:dod_verify`
**Version**: 1.0.0
**Ticket**: OMN-9414

## Purpose

Run DoD evidence checks against a ticket's ModelTicketContract and produce a
structured verification receipt. Dispatches to `node_dod_verify` via
`onex run-node`.

## Announce

Say: "I'm using the dod-verify skill to run DoD evidence checks for {ticket_id}."

## Parse arguments

Extract from `$ARGUMENTS`:

- First positional argument → `ticket_id` (required, e.g. `OMN-1234`)
- `--contract-path <path>` (optional) → override contract YAML location
- `--dry-run` (optional) → run without side effects

**Validation:**
- If no `ticket_id` is provided, ask the user for one — do not proceed without it.
- If `ticket_id` does not match pattern `OMN-\d+`, reject with usage message.

## Step 1: Resolve paths <!-- ai-slop-ok: skill-step-heading -->

```bash
OMNI_HOME="${OMNI_HOME:-$HOME/Code/omni_home}"  # local-path-ok: env var default fallback
ONEX_STATE_DIR="${ONEX_STATE_DIR:-$HOME/.onex/state}"
```

**Contract auto-detection** (when `--contract-path` is not provided):

```bash
# Check common locations in order:
# 1. Ticket-specific contract in the worktree or repo
# 2. Drift contracts directory
CONTRACT_PATH="${ARG_CONTRACT_PATH:-}"

if [ -z "$CONTRACT_PATH" ]; then
  # Try ticket-specific contract in onex_change_control drift dir
  CC_REPO="${ONEX_CC_REPO_PATH:-$OMNI_HOME/onex_change_control}"
  if [ -f "$CC_REPO/drift/${ticket_id}.yaml" ]; then
    CONTRACT_PATH="$CC_REPO/drift/${ticket_id}.yaml"
  fi
fi
```

If no contract is found, offer to run `/onex:generate_node` to create one, then exit.

## Step 2: Dispatch to node_dod_verify <!-- ai-slop-ok: skill-step-heading -->

```bash
cd "$OMNI_HOME/omnimarket"

# Build the input payload
INPUT_JSON=$(cat <<EOF
{
  "ticket_id": "${ticket_id}",
  "dry_run": ${DRY_RUN:-false}
}
EOF
)

# Add contract_path if provided/found
if [ -n "$CONTRACT_PATH" ]; then
  INPUT_JSON=$(echo "$INPUT_JSON" | python3 -c "
import sys, json
d = json.load(sys.stdin)
d['contract_path'] = '$CONTRACT_PATH'
json.dump(d, sys.stdout)
")
fi

onex run-node node_dod_verify \
  --input "$INPUT_JSON" \
  --timeout 60
```

On non-zero exit code, surface the error directly and stop. Do not produce prose
speculation about what went wrong.

## Step 3: Parse and render results <!-- ai-slop-ok: skill-step-heading -->

The node outputs a `ModelDodVerifyState` JSON object with these fields:

```json
{
  "ticket_id": "OMN-1234",
  "status": "verified | failed | skipped",
  "total_checks": 3,
  "verified_count": 2,
  "failed_count": 1,
  "skipped_count": 0,
  "checks": [
    {
      "evidence_id": "dod-001",
      "description": "Tests exist and pass",
      "status": "verified",
      "message": null
    }
  ],
  "error_message": null
}
```

**Render as a human-readable table:**

```
DoD Verification Report: {ticket_id}
======================================

| # | Evidence ID | Description | Status | Message |
|---|------------|-------------|--------|---------|
| 1 | dod-001 | Tests exist and pass | ✅ verified | |
| 2 | dod-002 | Config file created | ❌ failed | No files matching config/*.yaml |
| 3 | dod-003 | API health check | ⏭️ skipped | |

Summary: 1 verified, 1 failed, 1 skipped (3 total)
Overall: FAILED
```

## Step 4: Next steps based on result <!-- ai-slop-ok: skill-step-heading -->

**If `status == "verified"`:**
- Confirm all checks passed
- Suggest marking the ticket as Done in Linear

**If `status == "failed"`:**
- List each failed check with its `message`
- For each failure, suggest the remediation action based on the evidence type:
  - `file_existence` → "Create the missing file(s)"
  - `test_execution` → "Fix the failing tests"
  - `api_content` → "Check the endpoint and assertions"
- Offer to re-run after fixes

**If `status == "skipped"`:**
- Report that the contract had no `dod_evidence` entries or all checks were skipped
- Suggest adding evidence items to the ticket contract

## Error handling

| Condition | Action |
|-----------|--------|
| No `ticket_id` provided | Ask user, do not proceed |
| Invalid `ticket_id` format | Reject with usage message |
| Contract not found | Offer to generate via `/onex:generate_node`, exit |
| Contract has no `dod_evidence` | Report cleanly, exit 0 |
| Node times out (>60s) | Report timeout, suggest `--dry-run` to skip I/O |
| Node returns non-zero exit | Surface error JSON, do not speculate |
