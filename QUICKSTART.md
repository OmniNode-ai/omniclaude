# OmniClaude Quickstart

OmniClaude ships as a single Claude Code plugin, **`onex@omninode-tools`**. As of OMN-14688
it is **delegate-only**: one skill (`/onex:delegate`), no hooks, no agents. It does **not**
inject a SessionStart capability banner or auto-load 100+ skills — that described an older,
larger plugin (`plugins/onex`, now `NO_AUTOLOAD`/dead source) that this file used to document.
If you're looking for that plugin's hooks/agents/routing architecture, see
[CLAUDE.md](CLAUDE.md) — it is internal OmniNode tooling, not part of the public plugin below.

---

## Install (5 min)

Requires the [Claude Code CLI](https://claude.com/claude-code) and Python 3.12+.

```bash
# 1. Register the marketplace (one-time; reads directly from GitHub, no local clone needed)
claude plugin marketplace add OmniNode-ai/omniclaude

# 2. Install the plugin
claude plugin install onex@omninode-tools

# 3. Restart your Claude Code session to load the skill
```

Verify: `claude plugin list` shows `onex@omninode-tools` with status `enabled`.

---

## Configure — install the `onex` CLI

The `/onex:delegate` skill shells out to the `onex` CLI. The CLI is **not** bundled with the
plugin and must be installed separately into an environment on `PATH`:

```bash
uv tool install --with 'omnibase-infra>=0.38.4' 'omnibase-core>=0.46.8'
# or:
pipx install 'omnibase-core>=0.46.8' && pipx inject omnibase-core 'omnibase-infra>=0.38.4'
```

`omnibase-core` provides the `onex` console script; `omnibase-infra` provides the `delegate`
subcommand — both are required in the same environment, or `onex delegate` exits 2 with
`Error: No such command 'delegate'`. Pins above are the current values from
[`plugins/onex-delegate/plugin-compat.yaml`](plugins/onex-delegate/plugin-compat.yaml), the
source of truth — check that file if these look stale.

Verify: `onex delegate --help` exits 0 from any directory.

**Do not run `uv run onex delegate`.** `uv run` resolves the venv of whatever project the
current directory belongs to, so it only works by coincidence inside a repo that happens to
co-install `omnibase-infra`. Install the CLI as a tool (above) and call the bare `onex` on
`PATH`.

---

## Run

```
/onex:delegate explain what a calendar app needs
```

which runs `onex delegate "<prompt>"` under the hood. This is local-first by default: with
zero Kafka/Postgres configuration, delegation runs the orchestrator in-process against an
in-memory event bus, with SQLite as the evidence fallback — no external services required to
try it.

> **Known gap (tracked in OMN-16191, open as of 2026-08-18).** On a byte-for-byte clean
> install following only the steps above, `onex delegate` currently fails with
> `Error: Unknown node 'node_delegate_skill_orchestrator'` — the CLI resolves its backing node
> from OmniNode's internal `omnimarket` workspace convention (`--omni-home` / `$OMNI_HOME`),
> which this install path never sets up. Check OMN-16191 for current status before assuming
> this note is stale.

> **Delegation model/backend selection.** There is currently no documented, public way to
> declare which model(s) `onex delegate` routes to — `onex delegate --help` has no
> `--model`/`--backend` flag, and backend resolution today comes from a repo-committed default
> configuration, not a public per-user setting. Treat this as an unimplemented feature, not a
> missing doc; tracked under OMN-16194.

---

## Tier 1 (self-hosted) / Tier 2 (cloud)

The intended composable architecture lets `onex delegate` point at a self-hosted or cloud
backend via a contract overlay. **As of this writing there is no public documentation of that
mechanism** — tracked in OMN-16194. (This section previously described a different, older
full-ONEX Docker Compose stack — Redpanda + omnimemory + omniintelligence — bundled with the
`plugins/onex` hooks plugin above. That stack is unrelated to the plugin this file now
describes; the old instructions were removed rather than left stale.)

---

## Troubleshooting

| Symptom | Likely cause |
|---------|-------------|
| `onex: command not found` | The `uv tool install`/`pipx` step above hasn't run, or its install bin dir isn't on `PATH`. |
| `Error: No such command 'delegate'. Did you mean 'gate'?` | Only `omnibase-core` is installed — `omnibase-infra` provides the `delegate` subcommand; both must be in the same environment (see Configure above). |
| `Error: Unknown node 'node_delegate_skill_orchestrator'` | See the known gap above (OMN-16191). |
| `claude plugin install` can't find `onex@omninode-tools` | Marketplace not registered — re-run the `marketplace add` step above; `claude plugin marketplace list` should show `omninode-tools`. |

---

## Next Steps

- [CLAUDE.md](CLAUDE.md) — development/architecture reference for OmniNode's internal tooling (insider-oriented; assumes an OmniNode canonical-clone workspace)
- [plugins/onex-delegate/skills/delegate/SKILL.md](plugins/onex-delegate/skills/delegate/SKILL.md) — the delegate skill's full usage reference
- [plugins/onex-delegate/plugin-compat.yaml](plugins/onex-delegate/plugin-compat.yaml) — source of truth for the `onex` CLI version pins above
