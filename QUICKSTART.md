# OmniClaude Quickstart

OmniClaude ships as a single Claude Code plugin, **`onex@omninode-tools`**. It exposes two
customer delegation siblings: `/onex:delegate` for customer-local work and
`/onex:cloud_delegate` for the dashboard-key gateway path. It has no hooks and no agents. It does **not**
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

## Configure — install the `onex` CLI and dashboard key

Both skills shell out to the `onex` CLI. The CLI is **not** bundled with the
plugin and must be installed separately into an environment on `PATH`:

```bash
uv tool install --with 'omnibase-infra>=0.38.4' --with 'omnimarket @ git+https://github.com/OmniNode-ai/omnimarket.git@dev' 'omnibase-core>=0.46.8'
# or:
pipx install 'omnibase-core>=0.46.8' && pipx inject omnibase-core 'omnibase-infra>=0.38.4' 'omnimarket @ git+https://github.com/OmniNode-ai/omnimarket.git@dev'
```

`omnibase-core` provides the `onex` console script; `omnibase-infra` provides the `delegate`
subcommand; `omnimarket` provides `node_delegate_skill_orchestrator`, the node the command
actually dispatches to — all three are required in the same environment (OMN-16191). Node
lookup resolves via `onex.nodes` entry points over installed distributions, so installing the
package is sufficient — there is **no** `$OMNI_HOME`/local-clone requirement despite what an
earlier revision of this file said.

Pins above are the current values from
[`plugins/onex-delegate/plugin-compat.yaml`](plugins/onex-delegate/plugin-compat.yaml), the
source of truth — check that file if these look stale.

Package presence checks: `onex delegate --help` and `onex cloud delegate --help` exit 0 from
any directory. **These are not proof a live run works** — they establish only that both customer
command paths are registered in the installed CLI.

**`--help` exiting 0 does not mean the command works.** Click answers `--help` before any
dispatch happens, so `--help` succeeds even with `omnimarket` missing entirely. The first real
failure only shows up on an actual invocation (see the known gaps below). The real verification
step is running a real delegation — `onex delegate "say hello in one word"` — not `--help`.

**Do not run `uv run onex delegate`.** `uv run` resolves the venv of whatever project the
current directory belongs to, so it only works by coincidence inside a repo that happens to
co-install `omnibase-infra`. Install the CLI as a tool (above) and call the bare `onex` on
`PATH`.

---

## Run — cloud first for a dashboard-only customer

Create an `onxk_` key in the dashboard, then give it to the CLI through stdin — never put the
key in a Claude prompt, command argument, or environment variable:

```bash
read -rs ONXK && printf '%s' "$ONXK" | \
  onex cloud login --base-url https://dev.api.omninode.ai --api-key-stdin
```

Inside Claude Code, run:

```
/onex:cloud_delegate --task-type summarization summarize this changelog
```

The CLI, not the plugin, submits over HTTPS. It prints the result and writes
`result.txt`, `receipt.json`, and `run.json` under `onex-delegations/<workflow_id>/` by default.
Keep and report those paths; they are the run evidence. A missing or rejected dashboard key is a
typed refusal, never a fallback to a direct provider call or to Claude answering the task.

## Run — customer-local

```
/onex:delegate explain what a calendar app needs
```

which runs `onex delegate "<prompt>"` under the hood. This is local-first by default: with
zero Kafka/Postgres configuration, delegation runs the orchestrator in-process against an
in-memory event bus, with SQLite as the evidence fallback — no external services required to
try it.

> **Known local-path gap (tracked in OMN-16200, open as of 2026-08-18).** Even with all three packages
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
| `Error: Unknown node 'node_delegate_skill_orchestrator'` | `omnimarket` is not installed in the same environment as `omnibase-core`; use the direct-git install command above. |
| `[ONEX_CORE_041_INVALID_CONFIGURATION] DELEGATION_ROUTING_TIERS_PATH is not bound` | See Known gap 2 (OMN-16200) above — no packaged template exists yet. |
| `claude plugin install` can't find `onex@omninode-tools` | Marketplace not registered — re-run the `marketplace add` step above; `claude plugin marketplace list` should show `omninode-tools`. |

---

## Next Steps

- [CLAUDE.md](CLAUDE.md) — development/architecture reference for OmniNode's internal tooling (insider-oriented; assumes an OmniNode canonical-clone workspace)
- [plugins/onex-delegate/skills/delegate/SKILL.md](plugins/onex-delegate/skills/delegate/SKILL.md) — the delegate skill's full usage reference
- [plugins/onex-delegate/skills/cloud_delegate/SKILL.md](plugins/onex-delegate/skills/cloud_delegate/SKILL.md) — dashboard-key cloud delegation and receipt-file reference
- [plugins/onex-delegate/plugin-compat.yaml](plugins/onex-delegate/plugin-compat.yaml) — source of truth for the `onex` CLI version pins above
