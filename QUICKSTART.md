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
uv tool install --with 'omnibase-infra>=0.38.4' --with 'omnimarket>=0.4.7' 'omnibase-core>=0.46.8'
# or:
pipx install 'omnibase-core>=0.46.8' && pipx inject omnibase-core 'omnibase-infra>=0.38.4' 'omnimarket>=0.4.7'
```

`omnibase-core` provides the `onex` console script; `omnibase-infra` provides the `delegate`
subcommand; `omnimarket` provides `node_delegate_skill_orchestrator`, the node the command
actually dispatches to — all three are required in the same environment (OMN-16191). Node
lookup resolves via `onex.nodes` entry points over installed distributions, so installing the
package is sufficient — there is **no** `$OMNI_HOME`/local-clone requirement despite what an
earlier revision of this file said.

> **Unpublished pin, as of 2026-08-18.** `omnimarket>=0.4.7` does not exist on PyPI yet. The pin
> is correct for when it ships, but publishing is blocked on cutting `omnimarket`'s runtime
> dependency on `onex_change_control` first (operator ruling, in progress). Until a qualifying
> `omnimarket` release is published, `uv tool install` with the line above will fail to resolve
> — check PyPI or OMN-16191 before assuming this note is stale.

Pins above are the current values from
[`plugins/onex-delegate/plugin-compat.yaml`](plugins/onex-delegate/plugin-compat.yaml), the
source of truth — check that file if these look stale.

Verify: `onex delegate --help` exits 0 from any directory.

**`--help` exiting 0 does not mean the command works.** Click answers `--help` before any
dispatch happens, so `--help` succeeds even with `omnimarket` missing entirely. The first real
failure only shows up on an actual invocation (see the known gaps below) — don't treat a clean
`--help` as proof of a working install.

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

> **Known gap 1 (tracked in OMN-16191, open as of 2026-08-18).** Until the `omnimarket` pin
> above is published (see the callout in Configure), a clean install following only the steps
> in this file omits `omnimarket` and `onex delegate` fails with
> `Error: Unknown node 'node_delegate_skill_orchestrator'`. Earlier text here attributed this to
> a missing `$OMNI_HOME`/workspace setup — that was wrong; it's simply a missing package, and
> installing `omnimarket` (once published) resolves it with no workspace convention needed.

> **Known gap 2 (tracked in OMN-16200, open as of 2026-08-18).** Even with all three packages
> installed, `onex delegate` currently fails at startup with
> `[ONEX_CORE_041_INVALID_CONFIGURATION] DELEGATION_ROUTING_TIERS_PATH is not bound` — there is
> no packaged template for this config value and no doc explaining what it should point to.
> Together with the next gap, this means the delegation route is not yet stranger-usable
> end-to-end even once OMN-16191 lands.

> **Delegation model/backend selection.** There is currently no documented, public way to
> declare which model(s) `onex delegate` routes to — `onex delegate --help` has no
> `--model`/`--backend` flag, `ModelDelegateSkillRequest.backend_id` exists on the wire model
> but the CLI never populates it, and backend resolution today comes from a secret-store key
> with no public self-serve onboarding (the file-based fallback is explicitly dev-only and on
> its way out — don't treat it as a supported config surface). Treat this as an unimplemented
> feature, not a missing doc; tracked under OMN-16200 and OMN-16194.

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
| `Error: Unknown node 'node_delegate_skill_orchestrator'` | `omnimarket` isn't installed, or its qualifying version isn't published yet. See Known gap 1 (OMN-16191) above. |
| `[ONEX_CORE_041_INVALID_CONFIGURATION] DELEGATION_ROUTING_TIERS_PATH is not bound` | See Known gap 2 (OMN-16200) above — no packaged template exists yet. |
| `claude plugin install` can't find `onex@omninode-tools` | Marketplace not registered — re-run the `marketplace add` step above; `claude plugin marketplace list` should show `omninode-tools`. |

---

## Next Steps

- [CLAUDE.md](CLAUDE.md) — development/architecture reference for OmniNode's internal tooling (insider-oriented; assumes an OmniNode canonical-clone workspace)
- [plugins/onex-delegate/skills/delegate/SKILL.md](plugins/onex-delegate/skills/delegate/SKILL.md) — the delegate skill's full usage reference
- [plugins/onex-delegate/plugin-compat.yaml](plugins/onex-delegate/plugin-compat.yaml) — source of truth for the `onex` CLI version pins above
