# aislop_sweep prompt

You are executing the **aislop-sweep** skill. This skill is a thin dispatch-only
shim that routes to the `node_aislop_sweep` node in omnimarket. All scanning,
triage, ticket-creation, and reporting logic lives in the node handler — the
shim does not implement any scan logic itself.

## Announce

Say: "I'm using the aislop-sweep skill to detect AI-generated quality anti-patterns."

## Parse arguments

Extract from `$ARGUMENTS`:

- `--repos <comma-list>` — Repos to scan (default: all supported repos; node resolves the default list)
- `--checks <comma-list>` — Check categories: phantom-callables, compat-shims, prohibited-patterns, hardcoded-topics, hardcoded-paths, todo-fixme, empty-impls (default: all)
- `--dry-run` — Report only, no tickets
- `--ticket` — Create Linear tickets for findings above severity threshold
- `--severity-threshold <level>` — Minimum severity: WARNING | ERROR | CRITICAL (default: WARNING)

The node owns the default repo list (`AISLOP_REPOS`: omniclaude, omnibase_core,
omnibase_infra, omnibase_spi, omniintelligence, omnimemory, onex_change_control,
omnibase_compat). Do not re-declare it here.

## Execution: Dispatch to node_aislop_sweep

Build the argument list from parsed flags and dispatch to the omnimarket node
via local RuntimeLocal (`onex node`, the in-process runtime — never the Kafka
remote dispatch path). No script fallback, no inline grep, no subprocess wrappers.

```bash
ARGS=""
if [ -n "$REPOS" ]; then
  ARGS="$ARGS --repos $REPOS"
fi
if [ -n "$CHECKS" ]; then
  ARGS="$ARGS --checks $CHECKS"
fi
if [ "$DRY_RUN" = "true" ]; then
  ARGS="$ARGS --dry-run"
fi
if [ -n "$SEVERITY_THRESHOLD" ]; then
  ARGS="$ARGS --severity-threshold $SEVERITY_THRESHOLD"
fi

uv run onex node node_aislop_sweep -- $ARGS
```

Capture the JSON output from stdout. The node produces a `ModelSkillResult`
(aislop-specific) containing per-check and per-severity counts, plus per-finding
details (repo, path, line, check, message, severity, confidence, ticketable,
autofixable).

Exit codes: `0` = clean (no findings), `1` = findings present or node error.
On non-zero exit, a `SkillRoutingError` JSON envelope is returned — surface it
directly, do not produce prose.

## Post-dispatch: Render results

Parse the node output and render a human-readable summary:

```
AI Slop Sweep
=============
Run: <run_id>
Repos scanned: <N>
Total findings: <N>

By severity:
  CRITICAL: <N>
  ERROR:    <N>
  WARNING:  <N>
  INFO:     <N>

By check:
  phantom-callables:   <N>
  compat-shims:        <N>
  prohibited-patterns: <N>
  hardcoded-topics:    <N>
  hardcoded-paths:     <N>
  todo-fixme:          <N>
  empty-impls:         <N>

Findings (CRITICAL → ERROR → WARNING → INFO):
  <repo>:<path>:<line>  <check>  <severity>/<confidence>  <message>
  ...

Tickets created: <N>
Auto-fixed: <N>
```

## Post-dispatch: Ticket creation (`--ticket`)

Ticket creation is handled by the node itself when `--ticket` is passed through.
The node deduplicates against existing open tickets, applies the severity
threshold, and creates at most one ticket per `(repo, check_family, path)`
group with label `aislop-sweep` in Active Sprint.

If `--dry-run` is set, no tickets are created regardless of `--ticket`.

## Error handling

- If `uv run onex node node_aislop_sweep` fails: surface the `SkillRoutingError`
  JSON envelope from stdout/stderr and exit non-zero.
- Do not fall back to inline grep, scripts, or subprocess wrappers. The node is
  the single source of truth for aislop scan logic (A4 amendment).
