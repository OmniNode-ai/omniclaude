# Hook Measurement & Tiered Reintroduction Plan

> **Status:** DESIGN-FIRST — gated on user review. This document and the
> measurement harness ship together; **no hooks are re-enabled here**.
> **Date:** 2026-06-18.

---

## 1. Context: why hooks are off right now

An earlier cleanup pass removed **every** hook registration from
`plugins/onex/hooks/hooks.json` (`hooks: {}`) and synced the live plugin cache,
so Claude Code currently invokes **zero** onex hooks. That was deliberate: it
establishes a clean, no-instrumentation measurement baseline "until we get
processes up and running to measure whether the hooks actually help or hurt."

The audit that motivated the removal found:

- ~50 hook registrations across 11 lifecycle events backed by ~93 scripts.
- The per-turn `UserPromptSubmit` chain injected **~250–300 tokens/message**
  (an agent-routing block that usually matched nothing + a blanket delegation
  rule) — a per-turn tax paid on every prompt.
- ~20 scripts fire on every tool call (`PreToolUse`/`PostToolUse` cascade).

This plan is the other half of that work: **stand up the measurement, then
re-introduce hooks deliberately, tier by tier, keyed to measured impact.**

### 1.1 Why removal, not the kill-switch

An earlier pass shipped a global kill-switch — `OMNICLAUDE_HOOKS_DISABLE=1` or the file
marker `~/.claude/omniclaude-hooks-disabled` — that short-circuits a hook to
`exit 0` *before* any threshold logic. A separate pass added `ONEX_HOOKS_MASK`
for per-hook bit-gating.

So why did the cleanup gut `hooks.json` instead of just setting the kill-switch?

1. **Incomplete coverage.** The kill-switch was only wired into **19/87**
   scripts. A hook that does not read the switch keeps running regardless.
2. **The per-turn injectors honored neither the kill-switch nor `common.sh`.**
   The `UserPromptSubmit` chain — the single largest token cost — could not be
   turned off via the switch at all.
3. **`hooks.json` removal is the only reliable off switch.** When a script is
   not registered, Claude Code never invokes it, so its internal guards are
   irrelevant. This is also trivially reversible (pure config; all scripts
   remain on disk).

**Design consequence for reintroduction:** the kill-switch / mask is the right
*operational* control once a hook is trusted, but it is **not** a safe baseline
mechanism while coverage is incomplete. Tier 0 of this plan (below) closes that
gap before any per-turn injector returns, so that `hooks.json` removal stops
being the only reliable kill path.

---

## 2. Measurement harness

### 2.1 What it measures

The harness compares two windows — **hooks-off** (the removal baseline) and
**hooks-on** (any window after registrations are restored) — across the three
axes called out in the ticket:

| Axis | Surface read | Metric |
|------|--------------|--------|
| **Tokens / turn** | `cost_records` SQLite (`$ONEX_STATE_DIR/hooks/cost_accounting.db`) | `mean_tokens_per_turn` (total tokens ÷ distinct sessions), plus on/off delta and ratio |
| **Latency / tool-call** | PRM trajectory store (`$ONEX_STATE_DIR/hooks/logs/post-tool-use-trajectory.jsonl`) | `mean_latency_ms` per window, reconstructed as inter-call wall-clock gaps |
| **Outcome impact** | `cost_records.is_delegated` + trajectory escalation evidence | `delegated_call_count` / `delegated_fraction` per window (proxy for "did the gates/injectors change behavior") |

It uses **existing telemetry/event surfaces only** — no bespoke REST endpoint,
no new collection daemon. The cost-accounting hook already records per-tool-call
tokens/cost tagged with `session_id`; the trajectory hook already records the
per-call sequence. The canonical `onex.evt.omniclaude.tool-executed.v1` event
stream remains the authoritative bus-side surface for any downstream rollup.

### 2.2 Where it lives

```
src/omniclaude/hook_measurement/
  __init__.py      public API
  enums.py         EnumHookWindow, EnumTokenProvenance
  models.py        ModelToolCallRecord / ModelWindowMetrics / ModelHookComparison (frozen)
  metrics.py       load_cost_records / split_by_boundary / aggregate_window / compare_windows
  trajectory.py    parse_latency_by_session_tool (JSONL trajectory store)
  cli.py           python -m omniclaude.hook_measurement.cli
tests/hook_measurement/test_metrics.py   14 unit tests
```

Everything is read-only. `load_cost_records` opens the SQLite DB with
`mode=ro`; the rest operates on in-memory record lists and is fully unit-tested
without any live telemetry surface present.

### 2.3 How to run it

The operator records the wall-clock instant at which the hook surface was
toggled from off → on (i.e. when registrations were restored and the cache
re-synced). Pass that as `--boundary`:

```bash
# from the omniclaude repo root, with ONEX_STATE_DIR set
python -m omniclaude.hook_measurement.cli \
    --boundary 2026-06-20T17:00:00Z          # toggle instant (off → on)

# JSON form for piping into a report / dashboard:
python -m omniclaude.hook_measurement.cli \
    --boundary 2026-06-20T17:00:00Z --json
```

Records before the boundary are scored as hooks-off; records at/after it as
hooks-on. Output is a side-by-side table (tokens/turn, tokens/call, delegated
calls, latency delta) or a JSON dump of `ModelHookComparison`.

> **Measurement hygiene.** For a fair comparison, capture comparable workloads
> in each window (same kinds of tickets / sessions). The `--boundary` split is
> the simplest credible design given a single on-disk DB; if a richer A/B
> design is wanted later, prior A/B baseline work established the methodology.

---

## 3. Tiered reintroduction plan

Hooks return in tiers, **lowest cost / highest safety value first**. Each tier
has an explicit measurement gate it must pass — measured with the harness above
— before the next tier is allowed to return. No tier re-enables itself; each is
a separate reviewed PR that edits `hooks.json` and re-syncs the cache.

### Tier 0 — Close the kill-switch gap (prerequisite, no behavior return)

Before *any* hook is re-registered, make the operational off-switches complete
so removal-from-`hooks.json` stops being the only reliable kill path:

- Wire `OMNICLAUDE_HOOKS_DISABLE` (and the `~/.claude/omniclaude-hooks-disabled`
  marker) into **every** GATE/INFRA script, not 19/87.
- Confirm every re-registered hook reads its `ONEX_HOOKS_MASK` bit (per the
  bit-governance inventory) and exits 0 when cleared.
- Add a CI gate that fails if a registered hook script lacks the kill-switch
  short-circuit (enforcement, not detection — per platform doctrine).

**Gate to exit Tier 0:** a test proves that with `OMNICLAUDE_HOOKS_DISABLE=1`
set, a session fires zero hook side effects even with registrations present.

### Tier 1 — Silent exit-code safety gates (return first)

Low/zero token cost, real value, no per-turn injection:

- `pre_tool_use_branch_protection_guard.sh`
- `pre_tool_use_prepush_validator.sh`
- `pre_tool_use_dod_completion_guard.sh` / `pre_tool_use_linear_done_verify.sh`
- `post-tool-use-ruff.sh` (autoformat)

These block on exit code only; they inject ~no tokens into the context stream.

**Measurement gate:** `tokens_per_turn_delta ≈ 0` (within noise) vs the
hooks-off baseline, AND `latency_per_call_delta_ms` within the PostToolUse
performance budget (<100ms sync). Safety gates that cost no tokens and stay
in-budget are kept unconditionally.

### Tier 2 — Per-tool-call PostToolUse cascade (return second, selectively)

The ~20 PostToolUse scripts (cost-accounting, trajectory, quality, delegation
counter, etc.). These cost latency per tool-call but little context.

**Measurement gate:** each script must show `latency_per_call_delta_ms` within
budget AND a demonstrated downstream consumer (the telemetry it writes is
actually read — e.g. by this harness). PostToolUse scripts whose output nothing
consumes do **not** return.

### Tier 3 — Per-turn UserPromptSubmit injectors (return last, must justify)

The agent-routing block + blanket delegation rule — the ~250–300 tokens/turn
tax. This is the most expensive surface and the one that drove the original removal.

**Measurement gate (highest bar):** an injector returns only if it shows a
**measured outcome benefit** that justifies its per-turn token cost — e.g. a
rise in `delegated_fraction` to cheaper models that nets a token/cost win, or
evidence the injected routing actually changed agent selection. An injector that
"usually matched nothing" does not clear this bar and stays off.

### Decision record

Which hooks stay is recorded per-tier, keyed to the measured `ModelHookComparison`
output, in the Decision Store (`/onex:decision_store`) so the rationale is
durable and queryable.

---

## 4. Rollback / kill-switch story

Three layers, in priority order (from `omniclaude/CLAUDE.md`):

1. **`OMNICLAUDE_HOOKS_DISABLE=1`** (or `~/.claude/omniclaude-hooks-disabled`) —
   global emergency kill, short-circuits every hook before any logic. After
   Tier 0 this is complete coverage; today it is not (19/87), which is the gap
   Tier 0 closes.
2. **`ONEX_HOOKS_MASK`** — per-hook bit-gate (append-only ordinals, see the
   bit-governance inventory). Used for targeted disable of a single misbehaving hook via
   `onex hooks disable <NAME>`.
3. **`hooks.json` removal + cache re-sync** — the removal mechanism. The most
   reliable off switch while (1) is incomplete, and the rollback of last resort:
   `git revert` the tier's PR and re-sync the plugin cache. All scripts remain
   on disk, so re-registration is a pure config change.

**Per-tier rollback:** each tier is one PR. If a tier regresses tokens/turn or
latency past its gate, `git revert` that PR and re-sync — the prior tiers stay
live. Because Tier 0 lands the kill-switch coverage first, from Tier 1 onward a
regressing hook can also be silenced in-session via the mask without a revert.

---

## 5. Out of scope for this ticket

- Re-enabling any hook in `hooks.json` (design + harness only).
- Touching the hook scripts themselves.
- `repowise-augment` in `~/.claude/settings.json` (separate from this plugin;
  intentionally left active by the baseline removal pass).
