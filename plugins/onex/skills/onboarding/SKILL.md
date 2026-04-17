---
description: Contract-driven progressive onboarding for new users and employees
mode: full
version: 1.0.0
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
    description: "Policy name: new_employee (default), standalone_quickstart, contributor_local, full_platform"
    required: false
  - name: --skip
    description: "Comma-separated step keys to skip"
    required: false
  - name: --continue-on-failure
    description: "Continue after step failures"
    required: false
  - name: --dry-run
    description: "Show resolved step plan without executing verifications"
    required: false
---

# onboarding

**Announce at start:** "I'm using the onboarding skill."

Contract-driven progressive onboarding for new users and employees. Resolves a
policy to a minimal set of steps via the onboarding graph DAG, executes
step verifications, and renders a markdown progress report.

## Built-in Policies

| Policy | Time | Target |
|--------|------|--------|
| `new_employee` | ~45 min (target estimate, unvalidated on fresh machine) | Full platform: Python, uv, core, Docker, Redpanda, secrets, Omnidash |
| `standalone_quickstart` | ~5 min | First standalone node running |
| `contributor_local` | ~20 min | Local dev with event bus connected |
| `full_platform` | ~45 min | All capabilities including Omnidash |

## Usage

```
/onex:onboarding
/onex:onboarding --policy standalone_quickstart
/onex:onboarding --policy new_employee --dry-run
/onex:onboarding --policy contributor_local --skip start_docker_infra
/onex:onboarding --policy full_platform --continue-on-failure
```

## Execution

Parse args, then run the node handler directly:

```bash
cd /Users/jonah/Code/omni_home/omnimarket && uv run python -c "  # local-path-ok: example command in documentation
import json
from omnimarket.nodes.node_onboarding.handlers.handler_onboarding import HandlerOnboarding
from omnimarket.nodes.node_onboarding.models.model_onboarding_start_command import ModelOnboardingStartCommand
cmd = ModelOnboardingStartCommand(
    policy_name='<policy_name>',
    skip_steps=[s.strip() for s in '<skip>'.split(',') if s.strip()],
    continue_on_failure=<continue_on_failure>,
    dry_run=<dry_run>,
)
result = HandlerOnboarding().handle(cmd)
print(result['rendered_output'])
"
```

Render the `rendered_output` field from the handler result directly to the user.

For dry-run mode, also display the `resolved_steps` list so the user can see what
would execute.

## Architecture

```
SKILL.md              -> thin UX wrapper (this file)
node_onboarding       -> omnimarket/nodes/node_onboarding/ (policy resolution + dispatch)
handle_onboarding     -> omnibase_infra/.../handlers/handler_onboarding.py (async orchestration)
canonical.yaml        -> omnibase_infra/.../onboarding/graphs/canonical.yaml (10-step DAG)
policies/*.yaml       -> omnibase_infra/.../onboarding/policies/ (builtin policies)
```
