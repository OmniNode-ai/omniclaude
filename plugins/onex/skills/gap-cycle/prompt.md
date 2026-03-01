<!-- persona: plugins/onex/skills/_lib/assistant-profile/persona.md -->

# gap-cycle Orchestration (v0.1)

You are orchestrating a gap investigation cycle. Execute phases in order,
capturing artifact paths from sub-skill stdout markers. If a required marker
is absent, emit a hard error — do NOT reconstruct paths or check fallback files.

---

## Phase 0 — Intake

Parse flags from the invocation:

1. **Mutual exclusion**: `--epic`, `--report`, `--resume` are XOR.
   If more than one is provided: emit error, stop.

2. **`--epic <id>`**: Set `epic_id`. Set `phases_executed.detect = true`.

3. **`--report <path>`**: Load the JSON file. Extract `epic_id` from
   `report.epic_id`. Hard error if field is absent or file unreadable.
   Set `phases_executed.detect = false`.
   Populate detect result immediately:
   ```json
   "phase_results": {
     "detect": {
       "status": "skipped",
       "artifact": "<report path>",
       "findings_count": <report.findings.length>
     }
   }
   ```
   Set `source_report_path = <report path>`.

4. **`--resume <path>`**: Load `summary.json`. Identify the first phase
   where `phase_results[phase] == null` AND `phases_executed[phase] == true`.
   Jump to that phase. Emit:
   `[gap-cycle] Resuming from phase: {phase}`

5. **`--dry-run`**: Record flag. gap-fix will receive `--dry-run`.
   golden-path-validate is suppressed entirely (`phases_executed.verify = false`).
   Local artifact files (report, gap-fix-output.json, summary.json) are still written.

6. Generate: `run_id = gap-cycle-{YYYY-MM-DDThh:mm:ss}Z` (UTC, Z suffix required).

7. Initialize `summary.json` structure in memory:
   ```json
   {
     "epic_id": null,
     "run_id": "gap-cycle-...Z",
     "source_report_path": null,
     "phases_executed": {"detect": true, "audit": false, "fix": true, "verify": false},
     "phase_results": {"detect": null, "audit": null, "fix": null, "verify": null},
     "prs_created": [],
     "gated_findings_count": 0,
     "nothing_to_fix": false,
     "composite_status": "error",
     "dry_run": false
   }
   ```
   Update `phases_executed` per flags:
   - `audit = true` if `--audit`
   - `fix = false` if `--no-fix`
   - `verify = true` if `--verify` AND NOT `--dry-run`
   - `dry_run = true` if `--dry-run`

---

## Phase 1 — Detect

**Skip if**: `--report` provided OR `--resume` past this phase.

1. Invoke gap-analysis:
   ```
   Use skill: gap-analysis --epic {epic_id} [--dry-run if set]
   ```

2. **Require ARTIFACT marker**: scan the sub-skill's output for the last line
   matching `ARTIFACT: <path>`. If not found: emit hard error:
   `[gap-cycle] ERROR: gap-analysis did not emit an ARTIFACT: marker. Cannot continue.`
   Stop.

3. Verify the path from the marker is a readable file. If not: emit:
   `[gap-cycle] ERROR: ARTIFACT path is not readable: {path}. Cannot continue.`
   Stop.

4. Record:
   - `phase_results.detect.status = "complete"`
   - `phase_results.detect.artifact = {marker path}`
   - `phase_results.detect.findings_count = report.findings.length`
   - `source_report_path = {marker path}`

5. **Zero findings check**: if `findings_count == 0`:
   - Set `nothing_to_fix = true`
   - Set `composite_status = "complete"`
   - Write `summary.json` (see Rollup section)
   - Emit: `[gap-cycle] Phase 1: zero findings. Status: complete.`
   - Exit.

6. Emit: `[gap-cycle] Phase 1 complete: {N} findings across {K} repos`

---

## Phase 2 — Audit Note (v0.1)

**Only if**: `--audit` flag set.

pipeline-audit chaining is deferred to v0.2. In v0.1:

- Record `phases_executed.audit = true`.
- Set `phase_results.audit = {"status": "deferred", "note": "pipeline-audit chaining not implemented in v0.1; run pipeline-audit separately then link artifacts manually"}`.
- Emit: `[gap-cycle] Phase 2: pipeline-audit chaining deferred to v0.2. Run manually if needed.`
- Continue to Phase 3. Do NOT modify source_report_path.

---

## Phase 3 — Fix

**Skip if**: `--no-fix` flag set.

1. Invoke gap-fix:
   ```
   Use skill: gap-fix --report {source_report_path} [--auto-only if set] [--dry-run if set]
   ```

2. **Require GAP_FIX_OUTPUT marker**: scan the sub-skill's output for the last line
   matching `GAP_FIX_OUTPUT: <path>`. If not found: emit hard error:
   `[gap-cycle] ERROR: gap-fix did not emit a GAP_FIX_OUTPUT: marker. Cannot continue.`
   Stop.

3. Verify the path from the marker is a readable file. If not: emit:
   `[gap-cycle] ERROR: GAP_FIX_OUTPUT path is not readable: {path}. Cannot continue.`
   Stop.

4. Load `gap-fix-output.json`. Extract:
   - `prs_created`: list of `{repo, number, url}` objects
   - `gated_count`: count of findings still at GATE status

5. Record:
   - `phase_results.fix.status = "complete"`
   - `phase_results.fix.artifact = {gap-fix-output.json path}`
   - `phase_results.fix.prs_created_count = prs_created.length`
   - `phase_results.fix.gated_count = gated_count`
   - Update `prs_created` list in summary
   - Set `gated_findings_count = gated_count`

6. **--auto-only gate**: if `gated_count > 0` AND `prs_created.length == 0`:
   - Set `composite_status = "gate_pending"`
   - Set `phases_executed.verify = false`
   - Write `summary.json`
   - Emit: `[gap-cycle] Phase 3: all findings gated. Status: gate_pending.`
   - Exit.

7. Emit: `[gap-cycle] Phase 3 complete: {N} PRs created, {G} gated`

---

## Phase 3.5 — Redeploy Gate

**Only if**: `phases_executed.verify == true` AND `prs_created.length > 0`.

Emit this exact prompt to the user and wait for response:

```
[gap-cycle] Phase 4 requires the changes from created PRs to be deployed.
Have you redeployed the affected services? [y/N]
```

- If user responds `y` (case-insensitive): continue to Phase 4.
- Any other response (N, empty, or other input):
  - Set `phases_executed.verify = false`
  - Write `summary.json`
  - Emit: `[gap-cycle] Phase 4 skipped — redeploy not confirmed.`
  - Jump to Rollup.

---

## Phase 4 — Verify

**Only if**: `phases_executed.verify == true` AND Phase 3.5 confirmed AND NOT `--dry-run`.

Run exactly ONE canonical verification — the routing golden path:

```
Use skill: golden-path-validate
```

Consult `golden-path-validate`'s own documentation for the canonical routing fixture path.
Do not invent or derive a fixture path — use what the skill documents as its default routing fixture.

Require nontrivial assertions: at minimum one field equality check on the output event.

Collect result:
- `status`: pass | fail | timeout
- `latency_ms`, `correlation_id`, `assertions`

Record:
- `phase_results.verify.status = "complete"` if pass; else `"failed"`
- `phase_results.verify.result = {status, latency_ms, correlation_id, assertions}`

Emit: `[gap-cycle] Phase 4 complete: {status}`

---

## Rollup

After all enabled phases complete (or on early exit):

### 1. Compute composite_status

Apply this deterministic mapping (in order of precedence):

| Condition | composite_status |
|-----------|-----------------|
| Any phase threw an exception or returned error | `error` |
| `blocked` set in Phase 0 (prerequisite missing) | `blocked` |
| `gate_pending` set in Phase 3 | `gate_pending` |
| `nothing_to_fix == true` | `complete` |
| All enabled phases ran AND `gated_findings_count == 0` AND (verify not enabled OR verify passed) | `complete` |
| Otherwise (phases skipped by flags, verify disabled, `gated_findings_count > 0`) | `partial` |

**Rule:** `gated_findings_count > 0` always prevents `complete`, yielding `partial` at minimum.

### 2. Write summary.json

```
mkdir -p ~/.claude/gap-cycle/{epic_id}/{run_id}/
Write to: ~/.claude/gap-cycle/{epic_id}/{run_id}/summary.json
```

Create parent directories first. Write the complete summary object.

### 3. Print composite verdict

```
[gap-cycle] ─────────────────────────────────────
  Epic:    {epic_id}
  Run:     {run_id}
  Status:  {composite_status}
  Phases:  detect={T/F} audit={T/F} fix={T/F} verify={T/F}
  PRs:     {prs_created.length} created
  Gated:   {gated_findings_count}
  Report:  {source_report_path}
  Summary: ~/.claude/gap-cycle/{epic_id}/{run_id}/summary.json
[gap-cycle] ─────────────────────────────────────
```

---

## Error Handling

- **Missing ARTIFACT marker**: hard error — `[gap-cycle] ERROR: gap-analysis did not emit an ARTIFACT: marker.` Do NOT attempt path reconstruction.
- **Missing GAP_FIX_OUTPUT marker**: hard error — `[gap-cycle] ERROR: gap-fix did not emit a GAP_FIX_OUTPUT: marker.` Do NOT attempt path reconstruction.
- **File not readable**: set `composite_status = "blocked"`, emit clear message with the attempted path, write summary.json, exit cleanly (no exception crash).
- **Sub-skill exception**: catch, set `composite_status = "error"`, record error in `phase_results[current_phase].error`, write summary.json, re-raise to surface to user.
- **epic_id missing from --report file**: `[gap-cycle] ERROR: --report file missing epic_id field at report.epic_id`. Hard stop.

---

## Dry-Run Behavior

Policy: local artifact writes allowed; external writes (Linear, GitHub, Kafka mutations) forbidden; verify suppressed.

When `--dry-run`:
- Phase 1 (gap-analysis): runs normally (read-only, writes local report file)
- Phase 2 (audit note): emitted if --audit; no chaining in v0.1 regardless
- Phase 3 (gap-fix): receives `--dry-run`; outputs plan only; no PRs; no Linear writes
- Phase 3.5: skipped (no PRs were created)
- Phase 4: suppressed entirely (`phases_executed.verify = false`)
- summary.json: written with `"dry_run": true`
