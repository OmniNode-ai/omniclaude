# ONEX onboarding

ONEX provides one setup command for model connections, delegation, the local
dashboard, and selected Claude integrations:

```bash
onex setup
```

This branch contains the OMN-23413 preview. Its new CLI and packaged Claude assets
must be built and tested together; these instructions do not claim the preview
is already available in a public release.

`Onboarding Verify` checks the stock Bash compatibility boundary and actual
installed-wheel customer assets on macOS. This boundary suite does not prove inference.
The combined delegation and gateway journey is verified in the primary CLI's
installed-wheel E2E suite with the exact matching artifacts. Public distribution
requires the corresponding reviewed releases.

## Install an explicit package

Install uv and Python separately. Select a released version or a local preview
wheel, then use uv's tool installer to expose the ONEX executable owned by
omnibase-core:

```bash
uv tool install --no-python-downloads --with-executables-from omnibase-core --python 3.12 /absolute/path/to/omnimarket.whl
```

Replace the example with your actual wheel path or selected package specification.
Use `uv tool dir --bin` to find the executable directory and add it to your shell's
PATH if needed. No repository checkout is required.

For the Claude customer plugin, install the matching `omninode-claude` wheel
through the CLI's package owner:

```bash
onex install /absolute/path/to/omninode_claude.whl
```

The wheel carries its own local marketplace and hook assets. Setup resolves that
installed bundle instead of cloning a GitHub repository. Claude Code itself and
any required external service must be available; the CLI reports missing
components with their recovery action.

## Connect your models

Start Ollama or your other model service yourself. ONEX accepts its endpoint,
discovers the advertised models, and lets you choose which to use. ONEX never
installs, starts, or downloads Ollama or its models. Hosted providers use an
endpoint plus a secret reference where authentication is required.

Use the installed command help for the provider and connection options:

```bash
onex models connect --help
onex models connections
onex setup --help
onex plugins list
```

Keep keys out of chat, logs, and command-line arguments. Model discovery verifies
the model list; an actual model request is required to prove inference works.

## Set up and verify

```bash
onex setup --preflight-only
onex setup
onex setup --action verify
onex setup --action repair
```

The installed plugin manifests determine available components and dependencies.
Setup preserves unrelated configuration, records each component's result, and
reports actionable failures. The dashboard runs locally. Routing every Claude
model request requires a native Messages-compatible endpoint and explicit gateway
selection; ordinary OpenAI model discovery is insufficient.

No global RAM, SSD, CPU, VM, or administrator requirement applies to the CLI.
Optional services have their own requirements and are selected explicitly.
Developer checkout setup is a separate opt-in profile.

Completion audio is also opt-in: select `--component completion-audio` and,
optionally, `--completion-name YOUR_NAME`. The reviewed setup selection is
consent to use the already installed system voice after the other selected steps
succeed. It downloads no audio, never plays during verification, and does not
automatically replay on repair or rerun. Your operating system may request audio
permission when it runs; a declined or interrupted playback is reported as an
action-required result. Deselect the optional component to continue silently.

## Existing script users

### Where `onex` finds its runtime config

Both a registry install from an installed package and a developer install use
the selected workspace's `config/onex/runtime/runtime_config.yaml` for the setup
runtime. Setup writes its own marked configuration and reports a conflict when a
hand-written file occupies that path; the existing file is preserved. This path
needs no private repository.

The user configuration directory holds `config.yaml`, plugin preferences, and
`setup.json`, the versioned setup choices and component observations. A saved
observation is a recovery checkpoint: verify reads the actual component again.
The package also carries the standalone runtime defaults used before a workspace
has been selected. No source checkout is needed to resolve the installed CLI.

`lab-onboarding.sh` is now a thin compatibility entry point to `onex setup`.
With an existing ONEX installation it invokes the CLI directly. If it is absent,
the script requires `--install-package` with the user's explicit package choice;
it never silently installs uv, Python, Homebrew, Docker, or a model service.

`--no-containers` and `--containers` map to setup path selections;
`--local-url` and `--compat-url` map to `--url`;
`--local-model` and `--ollama-model` map to `--model`;
`--restart` maps to repair. `--set-aside` currently refuses while preserving
existing files; canonical backup and restore integration is still required.

The historical pinned provisioning script is not the package-based preview.
Use a reviewed release artifact or the checked-out preview bootstrap with an
explicit local wheel; do not assume an old public script checksum describes it.

---

## Tell us what broke

If setup, the plugin or a delegation fails, or does not do what you expected, open an
[MVP feedback report](https://github.com/OmniNode-ai/omniclaude/issues/new?template=mvp-feedback.yml)
(the form is `.github/ISSUE_TEMPLATE/mvp-feedback.yml`). It asks where it broke, then for the exact
command you ran and the error or output you got. If a delegation ran, add the receipt's
correlation id and the output of `onex doctor`; if install failed before `onex` or a receipt
existed, leave those two empty.
