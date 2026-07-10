---
description: Final session handoff with six mechanical enforcement behaviors — claim-certification lint, supersession tombstones, terminal commit+push, typed stale-doc findings (FIXED/DEFERRED schema), live-gh scorecard (hard-fail on missing/red PRs), and deep-dive reconcile (SUPERSEDED banner on stale state_as_of). Replaces free-form prose handoffs that silently emit phantom topology, folklore SHAs, or missing PRs.
mode: full
version: 2.0.0
level: advanced
debug: false
category: workflow
tags:
  - handoff
  - session
  - enforcement
  - scorecard
  - stale-doc
  - supersession
  - claim-certification
author: OmniClaude Team
args:
  - name: --lane
    description: "Target runtime lane context for topology claims: dev | stability | prod"
    required: false
  - name: --session-window
    description: "ISO 8601 UTC start time of the current session window (default: 8h ago)"
    required: false
  - name: --dry-run
    description: "Print all probe outputs and the handoff draft without committing or pushing"
    required: false
skill_kind: methodology
---

# /onex:handoff — Final Session Handoff

**Skill ID**: `onex:handoff`
**Version**: 2.0.0
**Retro source**: PROCESS_FAILURE_RETRO.md §3.C, item C-1

**Announce at start:** "I'm using the handoff skill."

A night-final handoff with phantom topology, folklore SHA, a missing red PR,
or an uncommitted self CANNOT be emitted. This skill enforces six mechanical
behaviors — every gate is a hard-fail, not advisory.

---

## Invocation

```
/onex:handoff
/onex:handoff --lane dev
/onex:handoff --dry-run
```

Full execution instructions live in `prompt.md` (six ordered phases). This
document defines the behavioral contracts for each phase.

---

## Enforcement Behaviors

### (a) Claim-Certification Lint

Every probeable claim in the handoff body — lane existence, topology container
counts, deployed SHAs, group counts — must carry exactly ONE of:

- **Inline probe+output**: the bash command that was run and its stdout/stderr on
  the same or adjacent line.
- **`[reported: <source>]`**: the authoritative surface that provided the value
  (e.g. `[reported: PR inventory projection]`, `[reported: projection endpoint]`).

**One claim → one label → one probe.** Run-on paragraphs that fuse multiple
claims (e.g. "407 Stable / 50 Empty groups was a false read, corrected by the
recent batch") violate this rule — split into per-claim lines.

The handoff MUST NOT emit any lane, container-count, SHA, or group-count value
that lacks a same-session probe. "From earlier this session" is not a probe; it
is folklore. If a claim cannot be re-probed, prefix it with `[unverified]` and
exclude it from the Verified State block.

### (b) Supersession

When a prior handoff or standing-orders directive is superseded:

1. **Retract-or-reaffirm every standing directive** from the superseded doc: each
   directive gets one of `[RETRACTED]`, `[REAFFIRMED]`, or `[UPDATED: <new text>]`
   inline.
2. **Tombstone edit**: write a one-line tombstone to the superseded handoff file:
   ```
   > SUPERSEDED by <path-to-this-handoff> at <UTC timestamp>
   ```
   This edit is part of the terminal commit (behavior c).
3. **LATEST.md pointer**: write or overwrite `docs/handoff/LATEST.md` with a
   one-line pointer to the new handoff path. Include in the terminal commit.

Failing to tombstone means the next session operator may resume from stale context.

### (c) Terminal Commit+Push

The handoff session MUST NOT end with uncommitted handoff artifacts. Before
emitting the handoff summary to the operator:

1. `git add <handoff_file>` — the primary handoff document.
2. `git add docs/handoff/LATEST.md` — the LATEST pointer (behavior b).
3. `git add <every docs/** path cited in the handoff body>` — stale-doc fixes,
   tombstoned prior handoffs, plan updates referenced by name.
4. `git commit -m "docs: night-final handoff <date> [OMN-session]"`
5. Publish the current HEAD to `origin` using the repository-approved push helper.
6. Report remaining untracked/dirty docs that were NOT in scope (do not silently
   add them; list them explicitly so the operator can decide).

On `--dry-run`, print the would-be `git add` file list and commit message without
executing steps 4–5.

### (d) Typed Stale-Doc Findings

Stale-doc findings must use the schema-validated format. Free text is not
representable. Each finding entry must be one of:

```
- docs/path/to/file.md: FIXED:<sha>
- docs/path/to/file.md: DEFERRED:<OMN-XXXX>
```

Where:
- `FIXED:<sha>` — the fix was committed in the specified commit SHA (7+ hex chars).
- `DEFERRED:<OMN-XXXX>` — the fix is tracked in a Linear ticket.

The backing Pydantic model is `ModelStaleDocFinding` in
`src/omniclaude/skills/handoff/stale_doc_finding.py`. The prompt validates
each finding against this model before the handoff body is finalized. A finding
that cannot be expressed as FIXED or DEFERRED is an open debt item — create a
ticket for it (behavior e lists it in the scorecard gap, not as a stale-doc entry).

### (e) Live-gh Scorecard

The scorecard is generated from a live `gh` query scoped to the current session
window. It is NEVER hand-authored.

**Hard-fail conditions** (emit `SCORECARD_BLOCKED` and stop):
- Any session-window PR is OPEN and missing from the scorecard.
- Any session-window PR has a failing CI check and no `owner:` row explaining the
  failure and next step.

**Scorecard format** (one row per session-window PR):

```
| PR | Title | State | CI | Owner/Note |
|----|-------|-------|----|------------|
| #N | desc  | MERGED | green | — |
| #M | desc  | OPEN   | red   | owner: <person> — <next step> |
```

The session window defaults to PRs opened or updated within the last 8 hours.
Override with `--session-window <ISO UTC>`.

### (f) Deep-Dive Reconcile

For every same-day deep-dive document cited in the handoff:

1. Read `state_as_of` from the deep-dive frontmatter.
2. Compare it against the handoff's `probe_time` (the UTC time when this handoff's
   topology probes were run).
3. If `state_as_of < probe_time`: auto-append the following banner to the deep-dive
   file (included in the terminal commit, behavior c):

```markdown
> **SUPERSEDED** — runtime state as of this document (<state_as_of>) is older than
> the final handoff probe time (<probe_time>). Do not use this document's runtime
> claims for planning. See: <handoff_path>
```

4. If the deep-dive has no `state_as_of` field: treat it as `state_as_of: epoch`
   (oldest possible → always appends the banner).

---

## Hard-Fail Summary

| Condition | Failure mode |
|-----------|-------------|
| Claim with no probe and no `[reported: ...]` label | `CLAIM_UNCERTIFIED` |
| Stale-doc finding with free-text resolution | `STALE_DOC_SCHEMA_VIOLATION` |
| Session-window PR absent from scorecard | `SCORECARD_BLOCKED` |
| Session-window PR red with no owner row | `SCORECARD_BLOCKED` |
| Handoff file not committed before emit | `TERMINAL_COMMIT_MISSING` |

---

## Anti-Patterns

| Anti-pattern | Rejection |
|---|---|
| Prose lane state without a probe (`dev lane UNTOUCHED`) | `CLAIM_UNCERTIFIED` |
| `fix opportunistically` as a stale-doc resolution | `STALE_DOC_SCHEMA_VIOLATION` |
| Hand-authored scorecard row | `SCORECARD_BLOCKED` (regenerate from live `gh`) |
| Emitting handoff without `git commit` | `TERMINAL_COMMIT_MISSING` |
| Citing a prior handoff body as a source for current state | Not a live truth surface; probe directly |

---

## Architecture

```
SKILL.md     → behavioral contracts for the 6 enforcement behaviors (this file)
prompt.md    → exact execution steps (six ordered phases)
src/omniclaude/skills/handoff/stale_doc_finding.py → ModelStaleDocFinding — typed schema for behavior (d)
topics.yaml  → no Kafka topics (local enforcement only)
```

## See Also

- `docs/evidence/2026-06-11-architecture-investigation/PROCESS_FAILURE_RETRO.md` in the canonical registry §3.C item C-1
- `/onex:session` — runtime session orchestrator (session state, health gates, dispatch)
- `/onex:runtime_closeout` — deploy + proof-matrix closeout (runtime artifacts)
