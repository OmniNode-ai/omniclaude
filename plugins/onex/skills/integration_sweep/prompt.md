<!-- persona: plugins/onex/skills/_lib/assistant-profile/persona.md -->
<!-- persona-scope: this-skill-only -- do not re-apply if polymorphic agent wraps this skill -->
Apply the persona profile above when generating outputs.

# Integration Sweep Skill Orchestration

You are executing the integration-sweep skill. This prompt defines the complete orchestration
logic for contract-driven post-merge integration verification.

---

## Step 0: Announce <!-- ai-slop-ok: skill-step-heading -->

Say: "I'm using the integration-sweep skill to run contract-driven post-merge verification."

---

## Step 1: Parse Arguments <!-- ai-slop-ok: skill-step-heading -->

Parse from `$ARGUMENTS`:

| Argument | Default | Description |
|----------|---------|-------------|
| `--date <iso-date>` | today (`date +%Y-%m-%d`) | Filter tickets by `updatedAt >= date` |
| `--tickets <ids>` | (empty) | Explicit comma-separated ticket IDs; skips Linear discovery |
| `--mode <scope>` | `omniclaude-only` | `omniclaude-only` or `full-infra` |
| `--dry-run` | false | Print table but do NOT write artifact |
| `--output <path>` | `$ONEX_CC_REPO_PATH/drift/integration/{date}.yaml` | Override artifact path |

Resolve `SWEEP_DATE`:
- If `--date` provided: use that value
- Otherwise: `date +%Y-%m-%d` (today)

Resolve `ONEX_CC_REPO_PATH`:
- Check env var `ONEX_CC_REPO_PATH`
- Fallback: `/Volumes/PRO-G40/Code/omni_home/onex_change_control`  <!-- local-path-ok -->
- If path does not exist: emit `INTEGRATION_SWEEP ERROR: ONEX_CC_REPO_PATH not found at <path>` and stop.

---

## Step 2: Discovery <!-- ai-slop-ok: skill-step-heading -->

**If `--tickets` was provided**: use those ticket IDs directly. Skip to Step 3.

**Otherwise** — discover recently completed tickets:

```
mcp__linear-server__list_issues(
  state="Done",
  updatedAfter="{SWEEP_DATE}T00:00:00Z",
  team="Omninode"
)
```

Filter to tickets whose `updatedAt` falls on or after `SWEEP_DATE`.

**IMPORTANT (OMN-5473)**: The `list_issues` API truncates descriptions to ~500 characters.
Do NOT use descriptions from this response for contract extraction. Only extract ticket IDs
here. Full descriptions MUST be fetched via `get_issue` in Step 3.

If no tickets found:
```
INTEGRATION_SWEEP: No completed tickets found for {SWEEP_DATE}. Running unconditional surface probes.
```
Skip Steps 3-5 (no ticket-gated probes to execute).
Proceed directly to Step 5b (Unconditional Surface Probes).

---

## Step 3: Contract Extraction <!-- ai-slop-ok: skill-step-heading -->

For each discovered ticket ID, fetch the **full** description (not the truncated list_issues
version) and extract the contract block:

1. Call `mcp__linear-server__get_issue(id=<ticket_id>)` -- this returns the untruncated description
2. Search the ticket description for a fenced YAML block:
   ````
   ```yaml
   # ModelTicketContract
   ...
   ```
   ````
3. Parse the YAML block as `ModelTicketContract`.
4. Extract:
   - `interfaces_touched: list[str]` — maps to `EnumIntegrationSurface` values
   - `dod_evidence: list[dict]` — checks to execute per surface

**If no contract block found**:
- Record probe result: `status=UNKNOWN`, `reason=NO_CONTRACT`
- Apply halt policy: **Halt** — stop the entire sweep and report.

**If contract is present but `dod_evidence` is empty**:
- Record probe result: `status=UNKNOWN`, `reason=NOT_APPLICABLE`
- Continue (no surfaces to probe for this ticket).

---

## Step 4: Surface Classification <!-- ai-slop-ok: skill-step-heading -->

Map each `interfaces_touched` value to `EnumIntegrationSurface`:

| Contract value | EnumIntegrationSurface |
|----------------|------------------------|
| `kafka` / `event_bus` / `topics` | `KAFKA` |
| `database` / `db` / `postgres` / `orm` | `DB` |
| `ci` / `github_actions` / `workflow` | `CI` |
| `plugin` / `omniclaude` / `skill` | `PLUGIN` |
| `github_ci` / `branch_protection` | `GITHUB_CI` |
| `script` / `scripts` / `bash` | `SCRIPT` |

Any value not matching the table above: record `status=UNKNOWN`, `reason=NOT_APPLICABLE`, continue.

---

## Step 5: Probe Execution <!-- ai-slop-ok: skill-step-heading -->

For each `(ticket_id, surface)` pair, execute the checks from `dod_evidence[*]` whose
surface classification matches.

Run checks in the order they appear in `dod_evidence`. For each check:

### Check type: `test_passes`

```bash
cd <repo_path>
uv run pytest <test_path> -x -q 2>&1
```

- PASS if exit code 0
- FAIL if exit code non-zero (capture stderr snippet as evidence)
- UNKNOWN/PROBE_UNAVAILABLE if `uv` or `pytest` not available

### Check type: `command`

```bash
<command>
```

- PASS if exit code 0
- FAIL if exit code non-zero
- UNKNOWN/PROBE_UNAVAILABLE if command not found

### Check type: `file_exists`

Check that the file at `path` exists on disk.

- PASS if file exists
- FAIL if file does not exist

### Check type: `grep`

```bash
grep -r "<pattern>" <path>
```

- PASS if at least one match found
- FAIL if no matches found
- UNKNOWN/INCONCLUSIVE if path does not exist

### Check type: `endpoint`

```bash
curl -sf --max-time 5 <url> > /dev/null
```

- PASS if HTTP 2xx
- FAIL if non-2xx or connection refused
- UNKNOWN/PROBE_UNAVAILABLE if curl not available or endpoint is outside `--mode` scope

**Surface-level result**: aggregate all check results for the surface.
- All PASS → surface `PASS`
- Any FAIL → surface `FAIL`
- No FAIL but any UNKNOWN/INCONCLUSIVE → surface `UNKNOWN/INCONCLUSIVE`
- No FAIL but any UNKNOWN/PROBE_UNAVAILABLE → surface `UNKNOWN/PROBE_UNAVAILABLE`
- No FAIL but any UNKNOWN/NOT_APPLICABLE → surface `UNKNOWN/NOT_APPLICABLE`

**Apply halt policy after each surface result** (see SKILL.md halt policy table).

---

## Step 5b: Unconditional Surface Probes <!-- ai-slop-ok: skill-step-heading -->

These probes run on EVERY integration-sweep invocation, regardless of whether
tickets were discovered or `--tickets` was empty. They detect infrastructure
drift not associated with any specific ticket.

### CONTAINER_HEALTH

1. Determine active profile:
   - If an explicit `--profile` flag was passed to the invoking skill (redeploy or autopilot), use that. This is authoritative.
   - Fallback only: infer from ambient containers. If any runtime container exists, use "runtime", else "core". When inferred, report it as "profile: inferred from running containers" in the probe detail, not as authoritative.
   - A stale container from a previous deployment does not automatically upgrade the expected profile. Explicit context outranks ambient residue.

2. Resolve expected containers from catalog for the determined profile:
   ```bash
   python3 $OMNIBASE_INFRA_DIR/src/omnibase_infra/scripts/verify_container_manifest.py \
     --catalog-dir $OMNIBASE_INFRA_DIR/docker/catalog \
     --bundles <profile> \
     --json
   ```
   - The script reads bundles.yaml + service YAMLs, extracts `container_name` (skips null entries like runtime-worker replicas).
   - If bundle resolution is ambiguous, the script exits 2 and the probe returns UNKNOWN with reason INCONCLUSIVE.

3. Parse JSON output:
   - exit_code 0: surface result = PASS
   - exit_code 1: surface result = FAIL with failures list as evidence
   - exit_code 2: surface result = UNKNOWN with reason PROBE_UNAVAILABLE (Docker not running) or INCONCLUSIVE (ambiguous manifest)

### RUNTIME_HEALTH

Runtime health expectations are profile-scoped. Only endpoints expected for the active profile contribute to PASS/FAIL; others are excluded or marked NOT_APPLICABLE.

1. Determine which endpoints to probe based on the active profile determined above:
   - **core** profile: no runtime endpoints expected. Surface result = UNKNOWN with reason NOT_APPLICABLE.
   - **runtime** profile: probe all three endpoints:
     - omninode-runtime: `curl -sf --max-time 5 http://localhost:8085/health`
     - intelligence-api: `curl -sf --max-time 5 http://localhost:8053/health`
     - omninode-contract-resolver: `curl -sf --max-time 5 http://localhost:8091/health`

2. Per endpoint:
   - HTTP 2xx: PASS
   - Connection refused or timeout: FAIL

3. Aggregate: any FAIL = surface FAIL. All PASS = surface PASS. Endpoints not in the active profile's expected set do not contribute.

Append both probe results to the main results list before proceeding to Step 6.

---

## Step 6: Artifact Assembly <!-- ai-slop-ok: skill-step-heading -->

Assemble a `ModelIntegrationRecord`:

```yaml
# ModelIntegrationRecord
sweep_date: "<SWEEP_DATE>"
tickets_swept: [<ticket_ids>]
surfaces_probed: [<distinct surfaces with at least one probe run>]
results:
  - ticket_id: "<id>"
    surface: <EnumIntegrationSurface>
    status: <PASS | FAIL | UNKNOWN>
    reason: <EnumProbeReason | null>   # NO_CONTRACT | PROBE_UNAVAILABLE | INCONCLUSIVE | NOT_APPLICABLE | null
    evidence: "<one-line summary>"
overall_status: <PASS | FAIL | PARTIAL>
artifact_written: <true | false>
```

`overall_status` rules:
- `PASS`: all probed surfaces returned PASS or UNKNOWN/NOT_APPLICABLE or UNKNOWN/PROBE_UNAVAILABLE
- `FAIL`: any surface returned FAIL or UNKNOWN/NO_CONTRACT or UNKNOWN/INCONCLUSIVE
- `PARTIAL`: mix of PASS and UNKNOWN/PROBE_UNAVAILABLE with no FAIL

**If `--dry-run`**: set `artifact_written: false`. Do NOT write the file. Skip Step 7.

---

## Step 7: Write Artifact <!-- ai-slop-ok: skill-step-heading -->

Resolve output path:
- If `--output` provided: use that path
- Otherwise: `{ONEX_CC_REPO_PATH}/drift/integration/{SWEEP_DATE}.yaml`

Ensure the parent directory exists:
```bash
mkdir -p "$(dirname <output_path>)"
```

Write the `ModelIntegrationRecord` YAML to the resolved path.

Set `artifact_written: true` in the record.

---

## Step 8: Summary Output <!-- ai-slop-ok: skill-step-heading -->

Always print a results table regardless of `--dry-run`:

```
INTEGRATION SWEEP — {SWEEP_DATE}
================================

| Ticket   | Surface   | Probe              | Status  | Evidence                                      |
|----------|-----------|--------------------|---------|-----------------------------------------------|
| OMN-5400 | KAFKA     | topic_match        | PASS    | topic constant matches consumer               |
| OMN-5401 | DB        | migration_applied  | FAIL    | migration 0043 not found in applied list      |

Summary: X PASS, Y FAIL, Z UNKNOWN (total)
Artifact: <output_path>   (or: --dry-run, no artifact written)
```

---

## Step 8b: Auto-Ticket on FAIL <!-- ai-slop-ok: skill-step-heading -->

If `overall_status` is not FAIL, skip this step.

For each probe result where `status == FAIL`:

1. **Compute failure signature**: Extract a normalized signature from the probe detail that
   distinguishes materially different failures on the same surface. For example:
   - CONTAINER_HEALTH: signature = sorted list of failing container names (e.g., `"omninode-runtime,runtime-worker-1"`)
   - RUNTIME_HEALTH: signature = sorted list of failing endpoint ports (e.g., `"8085,8091"`)
   - Other surfaces: signature = first 80 chars of detail, normalized (lowercase, whitespace-collapsed)

   This ensures: repeated identical failures dedup, but materially different failures on the
   same surface create distinct tickets.

2. **Dedup check**: Search Linear for an existing open ticket with:
   - Label: `autopilot-triage`
   - Title contains both the surface name AND the failure signature hash (first 8 chars of SHA-256 of signature)
   If found and still open, skip creating a duplicate. Print: `"DEDUP: Existing ticket {id} covers {surface}:{signature_hash}"`

3. **Determine priority** (profile-aware):
   - CONTAINER_HEALTH or RUNTIME_HEALTH with active runtime profile: Priority 1 (Urgent) -- real expected-service failure
   - CONTAINER_HEALTH or RUNTIME_HEALTH with core-only profile or optional services: Priority 2 (High) -- infrastructure issue but not runtime-critical
   - All other surfaces: Priority 2 (High)

4. **Create ticket**:
   ```
   mcp__linear-server__save_issue(
     title="[autopilot-triage] {surface} {signature_hash} -- {SWEEP_DATE}",
     description="## Context\n- Surface: {surface}\n- Sweep date: {SWEEP_DATE}\n- Failure signature: {signature}\n- Active profile: {profile}\n\n## Evidence\n{detail}\n\n## Resolution\nInvestigate and fix. Re-run /integration-sweep to verify.",
     team="Omninode",
     project="Active Sprint",
     priority=<1 or 2>,
     labels=["autopilot-triage"]
   )
   ```

5. Print: `"AUTO-TICKET: Created {ticket_id} for {surface}:{signature_hash} (priority {priority})"`

---

## Step 9: Emit Result Line <!-- ai-slop-ok: skill-step-heading -->

Always end with exactly one result line:

```
INTEGRATION_SWEEP_RESULT: <PASS|FAIL|PARTIAL> tickets=<N> surfaces=<N> fail=<N> unknown=<N>
```

If `--dry-run`, append ` [dry-run]`.

---

## Mode Constraints <!-- ai-slop-ok: skill-step-heading -->

**`omniclaude-only` mode** (default):
- Only probe surfaces: `PLUGIN`, `GITHUB_CI`, `SCRIPT`, `CI`
- Skip `KAFKA` and `DB` probes (record as UNKNOWN/NOT_APPLICABLE)

**`full-infra` mode**:
- Probe all six surfaces
- Requires local Docker infra running (`infra-up` must have been executed)
- If infra not reachable: record affected surfaces as UNKNOWN/PROBE_UNAVAILABLE, continue

---

## Error Handling <!-- ai-slop-ok: skill-step-heading -->

- If `ONEX_CC_REPO_PATH` does not exist: emit error, stop
- If Linear API call fails: emit error, stop
- If a single check raises an unexpected exception: record UNKNOWN/INCONCLUSIVE for that surface, apply halt policy
- Never silently swallow errors — always surface the exception message in `evidence`
