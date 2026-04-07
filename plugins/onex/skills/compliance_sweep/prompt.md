# compliance_sweep prompt

You are executing the **compliance-sweep** skill. This skill dispatches to the
`node_compliance_sweep` node in omnimarket for handler contract compliance scanning.

## Announce

Say: "I'm using the compliance-sweep skill to audit handler contract compliance across all repos."

## Parse arguments

Extract from `$ARGUMENTS`:

- `--repos <comma-list>` -- Repos to scan (default: all Python repos)
- `--dry-run` -- Report only, no ticket creation
- `--create-tickets` -- Create Linear tickets for untracked violations
- `--max-tickets <N>` -- Max tickets per run (default: 10)
- `--json` -- Output ModelComplianceSweepReport JSON
- `--allowlist-dir <path>` -- Override allowlist directory

**Default repo list** (scan all unless `--repos` overrides):
```
omnibase_infra, omniintelligence, omnimemory, omnibase_core,
omniclaude, onex_change_control, omnibase_spi
```

## Preamble: Pull bare clones

Before scanning, pull all bare clones to ensure findings reflect latest `main`:

```bash
bash /Volumes/PRO-G40/Code/omni_home/omnibase_infra/scripts/pull-all.sh  # local-path-ok
```

If `pull-all.sh` exits non-zero, **warn but continue** -- stale clones may produce
slightly outdated findings but this is not a blocking failure.

## Execution: Dispatch to node_compliance_sweep

Build the `onex run` command from parsed arguments and dispatch to the omnimarket node.
The node handles all scanning phases internally (discovery, AST-based compliance checks,
wire schema validation, infrastructure coupling detection, aggregation, and report saving).

```bash
cd /Volumes/PRO-G40/Code/omni_home/omnimarket  # local-path-ok

# Build argument list from parsed flags
ARGS=""
if [ -n "$REPOS" ]; then
  ARGS="$ARGS --repos $REPOS"
fi
if [ "$DRY_RUN" = "true" ]; then
  ARGS="$ARGS --dry-run"
fi
if [ -n "$ALLOWLIST_DIR" ]; then
  ARGS="$ARGS --allowlist-dir $ALLOWLIST_DIR"
fi

uv run onex run node_compliance_sweep -- $ARGS
```

Capture the JSON output from stdout. The node produces a `ModelComplianceSweepReport`
with all violation details, verdicts, and per-repo breakdowns.

## Post-dispatch: Render results

Parse the node output and render the human-readable summary:

```
Handler Contract Compliance Sweep
===================================
Repos scanned: <N>
Total handlers: <N>
Compliant: <N> (<pct>%)
Imperative: <N> (<pct>%)
Hybrid: <N> (<pct>%)
Allowlisted: <N> (<pct>%)
Missing contract: <N> (<pct>%)

Per-repo breakdown:
  <repo>: <total> handlers (<compliant> compliant, <imperative> imperative, <hybrid> hybrid)
  ...

Top violations:
  <violation_type>: <count>
  ...

Infrastructure coupling: <N> violations (<critical> critical, <warn> warn)

Overall compliance: <pct>%
Report: docs/registry/compliance-scan-<date>.json
```

If `--json` flag was set, output the raw JSON from the node instead.

## Post-dispatch: Ticket creation (--create-tickets)

**Skip entirely** if `--dry-run` is set or `--create-tickets` is NOT set.
Print: "Use --create-tickets to create Linear tickets for violations."

Otherwise, use the node output violations to create Linear tickets:

1. Group violations by node directory (one ticket per node, not per handler)
2. Dedup against existing Linear tickets with "compliance" in the title
3. Create tickets (up to `--max-tickets`, default 10) via `mcp__linear-server__save_issue`
4. Title format: `fix(compliance): migrate <node_name> to declarative pattern`
5. Project: Active Sprint, label: `contract-compliance`

After creating tickets, print:

```
Tickets created: <N>
  OMN-XXXX: fix(compliance): migrate node_foo to declarative pattern
  ...

Remaining untracked nodes: <N> (use --max-tickets to increase limit)
```

## Error handling

- If `onex run` fails: report the error and exit
- If a repo is not found at `$OMNI_HOME/<repo>`: skip, record in report
- If Linear API fails during ticket creation: log error, continue with remaining tickets
