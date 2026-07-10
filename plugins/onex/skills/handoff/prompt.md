# /onex:handoff — Execution Prompt

Execute the six phases in order. Each phase is a hard-gate: if it fails, report
`HANDOFF_BLOCKED: <phase> — <reason>` and stop. Do NOT emit the handoff summary
until all six phases complete without a hard-fail.

**Probe time**: record `PROBE_TIME=$(date -u +%Y-%m-%dT%H:%M:%SZ)` at the start
of Phase 1 and carry it through all phases.

---

## Phase 1 — Claim-Certification Lint

### 1.1 Collect all probeable claims from session notes

Identify every claim in the draft handoff body that asserts:
- Lane existence or container counts
- Deployed SHAs or image digests
- Runtime endpoint health (alive/dead)
- Group counts, topic counts, partition counts

### 1.2 Run one probe per claim

For each claim, run the minimum command that directly proves or refutes it:

```bash
# RUNTIME_HOST resolves from the environment (set in ~/.omnibase/.env)
RUNTIME_HOST="${RUNTIME_HOST:?RUNTIME_HOST must be set to the runtime server address}"
SSH_USER="${SSH_USER:?SSH_USER must be set to the runtime ssh login}"

# Lane/container count
ssh "${SSH_USER}@${RUNTIME_HOST}" "docker ps --filter 'label=compose.project=<project>' --format '{{.Names}}' | wc -l"
# Deployed SHA
ssh "${SSH_USER}@${RUNTIME_HOST}" "docker inspect <container> --format '{{.Config.Image}}'"
# Endpoint health
curl -sf "http://${RUNTIME_HOST}:<port>/v1/health" || echo "DEAD"
# PR/group counts
env -u GITHUB_TOKEN gh pr list --repo OmniNode-ai/<repo> --state open --json number | jq length
```

### 1.3 Annotate each claim

Inline the probe command and its stdout immediately after the claim in the draft.
Use `[reported: <surface>]` for values from authoritative read-only surfaces
(e.g. `[reported: gh pr list --state open]`).

**Hard-fail**: any claim without a probe or `[reported: ...]` label →
`CLAIM_UNCERTIFIED: <claim text>`.

---

## Phase 2 — Supersession Handling

Skip this phase if there is no prior handoff to supersede (new session, no standing
orders). Otherwise:

### 2.1 Identify the prior handoff

```bash
cat docs/handoff/LATEST.md 2>/dev/null || echo "no LATEST.md"
```

### 2.2 Retract-or-reaffirm standing directives

Read every directive in the prior handoff. For each, add one inline marker:
- `[RETRACTED]` — no longer applies
- `[REAFFIRMED]` — still applies unchanged
- `[UPDATED: <new text>]` — applies with modification

### 2.3 Tombstone the prior handoff

```bash
PRIOR=$(cat docs/handoff/LATEST.md)
echo "" >> "$PRIOR"
echo "> SUPERSEDED by <this_handoff_path> at ${PROBE_TIME}" >> "$PRIOR"
```

### 2.4 Update LATEST.md pointer

```bash
echo "docs/handoff/<this_handoff_filename>.md" > docs/handoff/LATEST.md
```

---

## Phase 3 — Typed Stale-Doc Findings

### 3.1 Identify stale docs

List documentation files cited in the handoff that are known to contain outdated
claims (e.g. CLAUDE.md lane table, architecture diagrams, deep-dive runtime state).

### 3.2 Classify each finding

For every stale doc, determine:
- **FIXED:<sha>** — the fix was committed in commit SHA `<sha>` during this session.
- **DEFERRED:<OMN-XXXX>** — a ticket will track the fix.

**Hard-fail**: any finding that cannot be expressed as `FIXED:` or `DEFERRED:` is
an unclosed debt item. Create a Linear ticket for it and use `DEFERRED:<new-ticket>`
as the resolution. Free text is not a valid resolution.

### 3.3 Emit typed findings block

```markdown
## Stale-Doc Findings

- docs/CLAUDE.md: FIXED:a1b2c3d
- docs/architecture/lane-census.md: DEFERRED:<TICKET>
```

Validate each finding against `ModelStaleDocFinding` from
`src/omniclaude/skills/handoff/stale_doc_finding.py` before finalizing.

---

## Phase 4 — Live-gh Scorecard

### 4.1 Determine session window

```bash
# Default: 8 hours ago
SESSION_START=$(date -u -v-8H +%Y-%m-%dT%H:%M:%SZ 2>/dev/null \
  || date -u -d '8 hours ago' +%Y-%m-%dT%H:%M:%SZ)
# Override with --session-window if provided
```

### 4.2 Query all session-window PRs

```bash
env -u GITHUB_TOKEN gh pr list \
  --repo OmniNode-ai/<primary-repo> \
  --state all \
  --search "updated:>=${SESSION_START}" \
  --json number,title,state,statusCheckRollup,headRefName \
  --jq '.[] | {number, title, state, ci: (.statusCheckRollup // [] | map(.conclusion) | if any(. == "FAILURE") then "red" elif all(. == "SUCCESS") then "green" else "pending" end)}'
```

Run this query for every repo touched during the session.

### 4.3 Build the scorecard table

```markdown
## Session Scorecard

| PR | Repo | Title | State | CI | Owner/Note |
|----|------|-------|-------|----|------------|
| #N | repo | desc  | MERGED | green | — |
```

### 4.4 Hard-fail conditions

- Any PR that was opened or pushed during the session window is **absent** from the
  table → `SCORECARD_BLOCKED: PR #N missing`
- Any PR with `CI: red` has no `Owner/Note` row explaining the failure and next step
  → `SCORECARD_BLOCKED: PR #N red with no owner`

**Do not proceed to Phase 5 until the scorecard passes.**

---

## Phase 5 — Deep-Dive Reconcile

### 5.1 Identify cited same-day deep-dives

From the handoff body, collect paths to any deep-dive document written today
(date matches today's UTC date).

### 5.2 Check state_as_of

For each deep-dive:

```bash
STATE_AS_OF=$(grep '^state_as_of:' "$DEEP_DIVE" | awk '{print $2}')
if [[ -z "$STATE_AS_OF" ]] || [[ "$STATE_AS_OF" < "$PROBE_TIME" ]]; then
  cat >> "$DEEP_DIVE" <<EOF

> **SUPERSEDED** — runtime state as of this document (${STATE_AS_OF:-epoch}) is
> older than the final handoff probe time (${PROBE_TIME}). Do not use this
> document's runtime claims for planning. See: docs/handoff/<this_handoff>
EOF
fi
```

Deep-dives without a `state_as_of` field are treated as epoch (always appended).

---

## Phase 6 — Terminal Commit+Push

After all five phases pass, commit every modified file.

### 6.1 Stage handoff artifacts

```bash
git add docs/handoff/<this_handoff_filename>.md
git add docs/handoff/LATEST.md
# Stage every docs/** file cited in the handoff body that was modified:
git add <each cited docs/** path>
```

### 6.2 Report remaining dirt

```bash
git status --short docs/
```

List any untracked or modified `docs/` files that were NOT staged above. Report them
to the operator as out-of-scope dirt — do NOT silently add them.

### 6.3 Commit and push

```bash
DATE=$(date -u +%Y-%m-%d)
git commit -m "docs: night-final handoff ${DATE} [OMN-session]"
# Publish the current HEAD to origin using the repository-approved push helper.
```

On `--dry-run`: print the staged file list and commit message; skip steps 6.3.

**Hard-fail**: if the handoff file is not committed by end of Phase 6 →
`TERMINAL_COMMIT_MISSING`.

---

## Output Format

After all six phases pass, emit the handoff summary to the operator:

```
HANDOFF COMPLETE — <date> at <PROBE_TIME>
commit: <sha>
scorecard: <N> PRs — <M> MERGED, <K> OPEN
stale-doc findings: <count> (FIXED:<n>, DEFERRED:<m>)
deep-dive reconcile: <count> SUPERSEDED banners appended
```

If any phase hard-failed, emit:
```
HANDOFF_BLOCKED: <phase> — <reason>
```
and stop. Do not emit a partial handoff.
