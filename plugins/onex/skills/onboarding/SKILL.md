---
description: Contract-driven progressive onboarding for new users and employees
mode: full
version: 1.1.0
level: basic
debug: false
category: onboarding
tags:
  - onboarding
  - new-employee
  - setup
  - progressive-disclosure
author: OmniClaude Team
composable: true
args:
  - name: --policy
    description: "Policy name (default: setup). See the Built-in Policies tables below."
    required: false
  - name: --skip
    description: "Comma-separated step keys to skip (DAG policies only)"
    required: false
  - name: --continue-on-failure
    description: "Continue after step failures (DAG policies only)"
    required: false
  - name: --dry-run
    description: "Show resolved step plan without executing verifications"
    required: false
  - name: --env-output-path
    description: "Interactive policy only: where to write the .env file (required unless --dry-run)"
    required: false
  - name: --overlay-output-path
    description: "Interactive policy only: where to write the overlay YAML (defaults next to --env-output-path)"
    required: false
---

# onboarding

**Announce at start:** "I'm using the onboarding skill."

Contract-driven progressive onboarding for new users and employees.

Two execution paths, chosen from the policy's `policy_type`:

- **DAG policies** (8 of the 9 built-ins) resolve to a minimal set of steps via
  the onboarding graph, execute each step's verification, and render a markdown
  progress report.
- **The interactive policy** (`interactive_onboarding`) drives a branching
  prompt flow through a transition table and writes an overlay YAML (plus a
  legacy `.env`) describing the chosen deployment.

## Built-in Policies

All 9 policies below ship in `omnibase_infra/onboarding/policies/`. Step counts
are the steps the resolver selects out of the 17-step canonical graph.

### Environment Setup (DAG)
| Policy | Steps | Target |
|--------|-------|--------|
| `setup` (default) | 5 | Toolchain + Docker + secrets verified |
| `standalone_quickstart` | 3 | Python + uv + core verified |

### Full Platform / Development (DAG)
| Policy | Steps | Target |
|--------|-------|--------|
| `new_employee` | 10 | Full platform: Docker, event bus, secrets, Omnidash, first node |
| `contributor_local` | 6 | Local dev with event bus connected |
| `contributor_cloud` | 9 | Cloud-backed contributor environment |
| `contributor_hybrid` | 10 | Local inference + cloud managed data services |
| `omnimarket_quickstart` | 10 | OmniMarket workflow-package development |
| `full_platform` | 6 | All capabilities including Omnidash |

### Guided Install (interactive)
| Policy | Steps | Target |
|--------|-------|--------|
| `interactive_onboarding` | branching | Prompts for local/cloud/hybrid deployment, then writes overlay + `.env` |

## Usage

```
/onex:onboarding
/onex:onboarding --policy standalone_quickstart
/onex:onboarding --policy new_employee --dry-run
/onex:onboarding --policy contributor_local --skip start_docker_infra
/onex:onboarding --policy full_platform --continue-on-failure
/onex:onboarding --policy interactive_onboarding --dry-run
/onex:onboarding --policy interactive_onboarding --env-output-path ./onex.env
```

## Execution

Parse args into a JSON payload, then dispatch `node_onboarding` on the local
runtime. Do not import or call the handler yourself — the node owns the logic.

- `omnimarket` and `omnibase_infra` ship in the plugin venv
  (`$CLAUDE_PLUGIN_DATA/.venv`, built by `ensure-plugin-venv.sh`), which also
  provides the `onex` entrypoint. No source checkout and no `cd` are required —
  run from wherever the session already is. If that venv is missing, rebuild it
  with `bash "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/ensure-plugin-venv.sh"` (the
  same script the SessionStart hook runs).
- `env -u PYTHONPATH` is required: the ONEX hooks export `PYTHONPATH` into the
  session, and a leaked value shadows the venv's packages.
- `onex node` runs the node on the local in-memory bus, so onboarding works
  before any broker exists — which is the point.

Write the payload to a file, then dispatch:

```bash
cat > "${TMPDIR:-/tmp}/onboarding-input.json" <<'JSON'
{
  "policy_name": "<policy_name>",
  "skip_steps": [<skip_steps>],
  "continue_on_failure": <continue_on_failure>,
  "dry_run": <dry_run>,
  "env_output_path": <env_output_path>,
  "overlay_output_path": <overlay_output_path>
}
JSON

env -u PYTHONPATH "${CLAUDE_PLUGIN_DATA:?CLAUDE_PLUGIN_DATA is injected by Claude Code}/.venv/bin/onex" \
  node node_onboarding --input "${TMPDIR:-/tmp}/onboarding-input.json"
```

Substitutions (all JSON, so `true`/`false`/`null`, not Python literals):

| Placeholder | Substitute with |
|---|---|
| `<policy_name>` | the `--policy` value, or `setup` |
| `<skip_steps>` | the `--skip` values as quoted JSON strings, or nothing |
| `<continue_on_failure>` | `true` / `false` |
| `<dry_run>` | `true` / `false` |
| `<env_output_path>` | a quoted path, or `null` |
| `<overlay_output_path>` | a quoted path, or `null` |

The dispatch writes `.onex_state/workflow_result.json` under the state root and
exits `0` on COMPLETED, `1` on FAILED/TIMEOUT, `2` on PARTIAL. Read
`terminal_payload` from that file and render `rendered_output` directly to the
user.

For dry-run mode on a DAG policy, also display `resolved_steps` so the user can
see what would execute. For the interactive policy, `terminal_payload` carries
`policy_type`, `visited_steps`, `terminal_step`, and — outside dry-run —
`overlay_output_path_written` / `env_output_path_written`.

If dispatch refuses with an omnimarket-drift error, the co-installed omnimarket
build is behind the canonical clone; repair the install rather than setting
`ONEX_ALLOW_OMNIMARKET_DRIFT` (results produced under that override are not
evidence).

## Architecture

```
SKILL.md              -> thin UX wrapper (this file)
node_onboarding       -> omnimarket/nodes/node_onboarding/ (policy resolution + path selection)
handle_onboarding     -> omnibase_infra/.../handlers/handler_onboarding.py (async orchestration)
canonical.yaml        -> omnibase_infra/.../onboarding/graphs/canonical.yaml (17-step DAG)
policies/*.yaml       -> omnibase_infra/.../onboarding/policies/ (9 builtin policies)
```
