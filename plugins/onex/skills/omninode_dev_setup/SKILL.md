---
description: Configure ONEX onboarding, delegation, dashboard, and selected Claude integrations using the installed CLI and user-managed model endpoints.
mode: full
debug: false
version: 2.0.0
level: basic
category: onboarding
tags: [onboarding, setup, local]
author: OmniClaude Team
skill_kind: methodology
args:
  - name: --preflight-only
    description: Inspect the selected setup without applying changes
    required: false
  - name: --install-package
    description: Explicit package version or local wheel to install when bootstrapping ONEX
    required: false
  - name: --provider
    description: Provider identifier from the installed provider registry
    required: false
  - name: --workspace
    description: Selected setup workspace
    required: false
---

# omninode_dev_setup

Announce: "I'm using the omninode_dev_setup skill."

The installed ONEX CLI owns setup, saved state, model connections, delegation,
dashboard, and selected Claude integrations. The compatibility script
`plugins/onex/skills/_bin/lab-onboarding.sh` forwards to `onex setup`.
It does not clone repositories, install system tools, or manage Ollama.

## Execution

1. Inspect `onex setup --help` and `onex plugins list` for installed options.
   Run `onex setup --preflight-only` with the requested components.
2. Run `onex setup` in the user's terminal for guided configuration. For an
   unattended run, supply the documented options and required endpoint choices.
   Credentials belong in the terminal's protected prompts or configured secret
   references; never request API keys in chat or command-line arguments.
3. Read the command's result and report each failed component with its recovery
   action. Rerun `onex setup --action repair` after addressing that failure.
4. Run `onex setup --action verify` to check the saved installation. A configured
   endpoint alone is not proof of a successful inference or delegation.

The user starts Ollama or another model service separately, supplies its endpoint,
and selects a discovered model. Setup never starts that service or downloads a
model. Claude gateway routing additionally requires the endpoint's explicit native
Messages support; an OpenAI-compatible endpoint alone does not prove it.

The customer Claude marketplace comes from the installed `omninode-claude`
package. If it is missing, follow the CLI's named package-install recovery.
Developer checkout integration is an explicit separate profile.

## Bootstrap compatibility

When ONEX is already installed:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/skills/_bin/lab-onboarding.sh" --preflight-only
```

When installing an explicitly selected local wheel or released package, the
user must already have uv and a compatible Python interpreter:

```bash
bash lab-onboarding.sh --install-package /absolute/path/to/omnimarket.whl --bootstrap-python /absolute/path/to/python3.12
```

Replace the example with the actual artifact path. The bootstrap exposes the
`onex` executable from omnibase-core through uv's canonical tool installer.
It forbids automatic Python downloads and never requests an administrator password.
Legacy URL/model flags are forwarded to endpoint configuration. `--set-aside`
is not yet available here and refuses without moving existing files; use the
canonical recovery flow once available.

There is no universal RAM, SSD, CPU, or VM requirement. Each selected external
service reports its own availability. A first-run sign-in to Claude remains the
user's action; restart Claude sessions after changing installed plugins or hooks.
