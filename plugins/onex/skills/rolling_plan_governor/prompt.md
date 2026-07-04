# /onex:rolling_plan_governor — Execution Prompt

**Announce at start:** "I'm using the rolling_plan_governor skill."

Five ordered phases. The goal is the **smallest evidence-backed delta** that
makes `docs/plans/ROLLING_SEVEN_DAY_PLAN.md` true again. Do not rewrite stable
sections. Behavioral contracts and hard-fails are in `SKILL.md`.

Resolve paths from the environment — never hardcode absolute paths:
```
PLAN="${PLAN:-$OMNI_HOME/docs/plans/ROLLING_SEVEN_DAY_PLAN.md}"   # local-path-ok: OMNI_HOME = canonical omni_home repo root (root CLAUDE.md rule #6); --plan overrides
# --ledger, or default to the newest handoff:
LEDGER="$(ls -t "$OMNI_HOME"/docs/handoff/*handoff*.md 2>/dev/null | head -1)"   # local-path-ok: OMNI_HOME = canonical omni_home repo root
```

---

## Phase 1 — Understand the project (read the plan)

Read the full current plan. Extract, without editing anything yet:

- **Objective / current milestone** — from §0 and §1 (and any linked roadmap).
- **§0 preamble** — the durable operating model. Note it as READ-ONLY for this
  cycle unless the ledger carries an explicit operator directive changing it.
- **§1 current state** — the last verified snapshot and its `state_as_of` time.
- **§2 work queue** — the ranked WS work-streams and their tasks/PRs/tickets.
- **§3/§4/§5** — open decisions (operator, AWS/Daniyal, parked).
- **§6 revision log** — the last delta's timestamp (your new delta appends after it).
- Architectural constraints, dependencies, and the critical path (usually the P0 WS).

## Phase 2 — Process the ledger

Read the ledger doc(s). Identify, as a structured list:

- **Completed work** — items the ledger reports done/merged.
- **Failed / partial work** — attempts that died, resumed run IDs, partial worktrees.
- **New discoveries** — defects, incidents, new tickets (OMN-XXXX), new requirements.
- **Blockers** — anything wedged (zombie CI runs, degraded runners, missing grants).
- **Architectural changes / decisions** — rulings given, decisions recorded.

Then **verify the probeable claims against live surfaces** — the ledger is a
report, not truth. Batch these:

```
# PR states cited in the ledger (merged? open? red?)
gh pr view <n> --repo OmniNode-ai/<repo> --json number,state,mergedAt,mergeStateStatus
gh pr checks <n> --repo OmniNode-ai/<repo>

# Ticket states (via the linear MCP tools, when a Done/Started flip is claimed)
# Runtime/lane claims (only when §1 asserts lane health):
ssh <host> '<lane health probe>'
```

Record each claim as `confirmed` (live surface agrees), `contradicted` (live
surface disagrees — the live surface wins), or `[reported: <surface>]` (could
not re-probe this cycle). Contradicted claims are the highest-value corrections.

## Phase 3 — Compare plan vs. reality

Produce the delta set. For each, note reason + impact + priority:

- **Stale state** — §1 claims the ledger/live surfaces contradict → correct them.
- **Completed tasks** — §2 items now done → remove from queue (record in §6 delta).
- **Missing work** — ledger work-items absent from §2 → add them under the right WS.
- **Obsolete work** — §2 items the ledger shows superseded/dropped → remove with the signal.
- **Dependency / sequencing changes** — a blocker cleared or appeared → re-rank per the ladder.
- **Duplicated work** — same task in two streams → collapse.
- **Hidden risks** — degraded runners, empty grant registries, un-applied migrations, etc.

Apply the priority ladder (SKILL.md (e)) only where dependencies/blockers
actually moved. **Do not reshuffle for cosmetics.** Confirm no change violates a
hard-fail (churn without evidence, work dropped without evidence, §0 mutated,
day-buckets, revision-log edit).

## Phase 4 — Update the plan (apply the minimal diff)

Edit `$PLAN` in place with targeted edits — **never** a full rewrite:

1. **§1** — replace only the contradicted/stale lines with the corrected,
   source-tagged state (executed probe, or `[reported: <surface>]`, or
   `[unverified]`). Update the section's `state_as_of` timestamp.
2. **§2** — remove completed/obsolete tasks; add new work under the correct WS;
   re-rank streams only if a blocker/dependency moved. Keep unfinished work.
   Keep the WS-ranked shape — no day buckets.
3. **§3/§4/§5** — strike through resolved decisions
   (`~~text~~ — DECIDED <date>: <ruling>`), append new ones. Never
   unilaterally act on a §4 AWS/Daniyal item — surface only.
4. **§0** — untouched unless a cited operator directive changes the operating
   model; if so, edit and cite the directive in the report.
5. **§6** — append ONE dated delta (do not edit prior deltas): what cleared,
   what §1 corrected to, §2 moves, §3 resolutions — cite the ledger by path.
6. Update the header `Current window` / `Last re-cut` line to the new UTC time.

## Phase 5 — Emit report + terminal write

1. Emit the governor report in the SKILL.md **Output Format** (Project Status →
   Ledger Summary → Required Plan Changes → Updated Work Queue → Risks →
   Recommended Next Actions → Assumptions).
2. Unless `--dry-run` or `--no-commit`: stage and commit.
   ```
   git -C "$OMNI_HOME" add docs/plans/ROLLING_SEVEN_DAY_PLAN.md   # local-path-ok: OMNI_HOME = canonical omni_home repo root
   git -C "$OMNI_HOME" commit -m "docs(OMN-XXXX): rolling-plan governor re-cut <date> — <one-line>"   # local-path-ok: OMNI_HOME repo root
   ```
   Use the OMN-XXXX from the ledger's driving work (or a plan-maintenance
   ticket). Report the commit sha. `--no-commit` writes but leaves it dirty;
   `--dry-run` prints the proposed diff and writes nothing.
3. Print the terminal status line:
   ```
   PLAN UPDATED — docs/plans/ROLLING_SEVEN_DAY_PLAN.md
   window: <start> → <end>   re-cut: <UTC>
   commit: <sha>   changed sections: <§ list>   churn: <+adds/-dels>
   ```

If a hard-fail condition triggers, emit `PLAN_GOVERNOR_BLOCKED: <condition> —
<reason>` and stop. Do not write a partial plan.

---

## Output Format (recap)

Governor report sections (console), then the terminal write status line. The
updated `ROLLING_SEVEN_DAY_PLAN.md` is the canonical rolling plan until the next
cycle. Keep every change concrete, actionable, and evidence-backed; optimize for
successful delivery over document elegance.
