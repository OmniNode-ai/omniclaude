# contract-compliance-check prompt

**Invocation**: `Skill(skill="onex:contract-compliance-check", args="<ticket_id> [--contract-path <path>]")`

---

## Overview

You are running a pre-merge seam validation check for a Linear ticket. You will:
1. Load the `ModelTicketContract` for the ticket
2. Determine which files changed relative to `origin/main`
3. Run probes for each surface declared in `interfaces_touched`
4. Apply `emergency_bypass` rules if enabled
5. Emit a structured PASS / WARN / BLOCK verdict

Do not skip any probe for a declared surface. Do not add probes for surfaces not declared.

---

## Step 1: Parse arguments

Extract from the invocation arguments:
- `ticket_id`: required (e.g. `OMN-1234`)
- `--contract-path <path>`: optional override for the contract YAML location

---

## Step 2: Load contract

**If `--contract-path` is provided:**
- Read the YAML file at that path

**Otherwise, resolve automatically:**
1. Check `$ONEX_CC_REPO_PATH/contracts/{ticket_id}.yaml` if `ONEX_CC_REPO_PATH` is set
2. Check `~/.claude/contracts/{ticket_id}.yaml`
3. If neither exists: emit error and stop

```
ERROR: No contract found for {ticket_id}.
Generate one first: Skill(skill="onex:generate-ticket-contract", args="{ticket_id}")
```

Parse the YAML into the contract fields. Extract:
- `ticket_id`
- `is_seam_ticket`
- `interfaces_touched` (list of strings)
- `emergency_bypass` (dict or null)

---

## Step 3: Determine changed files

Run:
```bash
git diff origin/main --name-only
```

If the command fails (not in a git repo, no `origin/main`):
```
ERROR: Cannot determine changed files. Ensure you are in a git worktree with origin/main available.
```

Store the list as `changed_files`.

---

## Step 4: Check emergency_bypass

Before running probes, evaluate the bypass:

```
If emergency_bypass is null or emergency_bypass.enabled == false:
    bypass_active = false

If emergency_bypass.enabled == true:
    justification = emergency_bypass.justification (string, may be empty)
    follow_up_ticket_id = emergency_bypass.follow_up_ticket_id (string, may be empty)

    If justification is empty OR follow_up_ticket_id is empty:
        bypass_active = false
        bypass_error = "emergency_bypass enabled but incomplete (missing justification or follow_up_ticket_id)"
    Else:
        bypass_active = true
```

`bypass_active` is used in Step 6 to downgrade BLOCK → WARN.
`bypass_error` (if set) will itself produce a BLOCK result that bypass cannot downgrade.

---

## Step 5: Run probes

Run one probe per surface listed in `interfaces_touched`. If `interfaces_touched` is empty
and `is_seam_ticket` is false, skip all probes and output:

```
No interface surfaces declared. Skipping seam probes.
Overall: PASS (0 warnings, 0 blocks)
```

### Probe: `topics`

**Goal**: Verify producer topic strings match consumer subscribe strings exactly.

**Scope**: Scan all repos under `$OMNI_HOME`.
The topic probe must cross repo boundaries because a producer in `omniclaude` may have
its consumer in `omniintelligence` or `omnibase_infra`.

**Procedure:**
1. Find all changed `.py` files in `changed_files`
2. For each file, scan for topic string constants (patterns: `= "onex.`, `= 'onex.`, uppercase variable names assigned string values matching `onex.*\.v\d+`)
3. Resolve the multi-repo scan root from the environment variable `$OMNI_HOME`.
   If `$OMNI_HOME` is not set, emit a warning and fall back to scanning only the current repo's
   `src/` and `plugins/` directories.
4. For each topic constant found, check if the same exact string appears as a subscriber
   argument (`subscribe(`, `.subscribe(`, `TOPICS =`, `topics =`) in ANY Python file under
   `$OMNI_HOME` (recursive, all repos):
   ```bash
   grep -rn "<topic_string>" "$OMNI_HOME" --include="*.py" | head -50
   ```
5. If a producer string exists in changed files and no consumer string matches exactly
   (exact bytes, case-sensitive) anywhere in `$OMNI_HOME`: BLOCK
6. If topic constant exists but no consumer found anywhere in `$OMNI_HOME`: WARN

Run:
```bash
# Find topic constants in changed files
grep -rn "onex\.[a-z]" <changed_py_files> | grep -E '= ["\']' | head -50

# Search for consumers of each topic found across all repos
# OMNI_HOME must be set in the environment (e.g. export OMNI_HOME=/path/to/omni_home)
grep -rn "<topic_string>" "$OMNI_HOME" --include="*.py" | head -50
```

### Probe: `events`

**Goal**: Detect removed required fields from event models.

**Procedure:**
1. Find all changed `.py` files that define Pydantic models (contain `class Model` + `BaseModel` or `(BaseModel)`)
2. For each changed model class, compare field definitions against `origin/main` baseline:
   ```bash
   git show origin/main:{file_path}
   ```
3. For each field in the baseline version:
   - If it has no default value (required field) and it is absent in the branch version: BLOCK
   - If a new field is present in branch but absent in baseline and has `= None` or a default: WARN

### Probe: `protocols`

**Goal**: Detect breaking changes to `Protocol` class method signatures.

**Procedure:**
1. Find all changed `.py` files that define `Protocol` classes (contain `class.*Protocol` or `(Protocol)`)
2. For each changed `Protocol` class, compare method signatures against baseline:
   ```bash
   git show origin/main:{file_path}
   ```
3. For each method in the baseline version:
   - If the method is absent in the branch: BLOCK
   - If the method signature (parameter names, types, return type) changed: BLOCK
4. If a new method is present in branch but absent in baseline: WARN

### Probe: `public_api`

**Goal**: Detect unannounced openapi.json changes.

**Procedure:**
1. Search for `openapi.json` in `changed_files`
2. If not found: PASS (no public API changes)
3. If found:
   - Compute SHA-256 of the branch version of the file
   - Compute SHA-256 of `git show origin/main:openapi.json`
   - If hashes differ AND `"public_api"` is NOT in `interfaces_touched`: WARN
   - If hashes differ AND `"public_api"` IS in `interfaces_touched`: PASS (expected change)
   - Never emit BLOCK for this probe

Run:
```bash
python3 -c "
import hashlib, subprocess, sys
branch_content = open('openapi.json', 'rb').read()
branch_hash = hashlib.sha256(branch_content).hexdigest()
main_content = subprocess.check_output(['git', 'show', 'origin/main:openapi.json'])
main_hash = hashlib.sha256(main_content).hexdigest()
print(f'branch={branch_hash[:12]} main={main_hash[:12]} changed={branch_hash != main_hash}')
"
```

### Probe: `envelopes`

**Goal**: Detect removed required fields from envelope models.

**Procedure:**
Same as `events` probe, but targeted at files matching:
- Filename contains `envelope` (case-insensitive)
- OR class name contains `Envelope` (case-insensitive)

Apply the same BLOCK (required field removed) / WARN (optional field added) logic.

---

## Step 6: Apply emergency_bypass

After all probes have run, collect results:
- `blocks`: list of BLOCK findings (probe name + detail)
- `warnings`: list of WARN findings (probe name + detail)

If `bypass_error` is set:
- Add one additional BLOCK: `emergency_bypass: {bypass_error}`
- Do NOT downgrade any existing BLOCKs (bypass is incomplete, cannot be applied)

If `bypass_active == true`:
- Downgrade all BLOCK findings (except `bypass_error` BLOCK) to WARN
- Append to each downgraded finding: `(downgraded by emergency_bypass: {follow_up_ticket_id})`

---

## Step 7: Determine overall verdict

```
If any BLOCK findings remain after bypass processing: verdict = BLOCK
Else if any WARN findings exist: verdict = WARN (PASS with warnings)
Else: verdict = PASS
```

Map to emoji:
- BLOCK → ❌ BLOCK
- WARN → ⚠️ WARN (displayed as "PASS" in the summary if no blocks)
- PASS → ✅ PASS

---

## Step 8: Emit output

Print the following format exactly:

```
CONTRACT COMPLIANCE CHECK — {ticket_id}
is_seam_ticket: {true|false}
interfaces_touched: [{comma-separated list}]

{For each probe that was run:}
{PROBE_NAME} probe ──────────
  {emoji} {verdict_label}  {detail}
  {emoji} {verdict_label}  {detail}
  ... (one line per finding; if no findings: "  ✅ PASS  No issues detected")

{If emergency_bypass was active:}
emergency_bypass: active (follow-up: {follow_up_ticket_id})
  All BLOCK findings downgraded to WARN.

{If bypass_error:}
emergency_bypass: INCOMPLETE — {bypass_error}

Overall: {PASS|WARN|BLOCK} ({N} warnings, {M} blocks)
```

**Verdict label mapping:**
- BLOCK finding → `❌ BLOCK`
- WARN finding → `⚠️ WARN`
- PASS (no finding for this probe) → `✅ PASS`

**Overall line:**
- PASS: `Overall: PASS (0 warnings, 0 blocks)`
- WARN: `Overall: PASS (N warnings, not blocking)`
- BLOCK: `Overall: BLOCK (N warnings, M blocks — merge prevented)`

---

## Examples

### Clean ticket (no seam surfaces declared)

```
CONTRACT COMPLIANCE CHECK — OMN-1100
is_seam_ticket: false
interfaces_touched: []

No interface surfaces declared. Skipping seam probes.
Overall: PASS (0 warnings, 0 blocks)
```

### Seam ticket with one warning

```
CONTRACT COMPLIANCE CHECK — OMN-2978
is_seam_ticket: true
interfaces_touched: [topics, events]

TOPICS probe ──────────
  ✅ PASS  onex.evt.omniclaude.prompt-submitted.v1

EVENTS probe ──────────
  ⚠️ WARN  ModelHookPromptSubmittedPayload: field added: intent_class: str | None = None

Overall: PASS (1 warning, not blocking)
```

### Seam ticket with BLOCK

```
CONTRACT COMPLIANCE CHECK — OMN-2001
is_seam_ticket: true
interfaces_touched: [protocols]

PROTOCOLS probe ──────────
  ❌ BLOCK  NodeIntelligenceBaseSpi: method removed: execute_compute()

Overall: BLOCK (0 warnings, 1 block — merge prevented)
```

### BLOCK downgraded by emergency_bypass

```
CONTRACT COMPLIANCE CHECK — OMN-2001
is_seam_ticket: true
interfaces_touched: [protocols]

PROTOCOLS probe ──────────
  ⚠️ WARN  NodeIntelligenceBaseSpi: method removed: execute_compute() (downgraded by emergency_bypass: OMN-2099)

emergency_bypass: active (follow-up: OMN-2099)
  All BLOCK findings downgraded to WARN.

Overall: PASS (1 warning, not blocking)
```

### Incomplete emergency_bypass

```
CONTRACT COMPLIANCE CHECK — OMN-2001
is_seam_ticket: true
interfaces_touched: [protocols]

PROTOCOLS probe ──────────
  ❌ BLOCK  NodeIntelligenceBaseSpi: method removed: execute_compute()

emergency_bypass: INCOMPLETE — emergency_bypass enabled but incomplete (missing justification or follow_up_ticket_id)

Overall: BLOCK (0 warnings, 2 blocks — merge prevented)
```
