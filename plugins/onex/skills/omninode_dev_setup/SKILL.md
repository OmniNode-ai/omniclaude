---
description: Take a Mac from bare to a working local onex in one run — tools, workspace, onex on the developer's model (their own key, or Ollama on the Mac with no key), and optionally the local container stack — reporting each phase as it finishes. Never connects to the lab
mode: full
version: 1.0.0
level: basic
debug: false
category: onboarding
tags:
  - onboarding
  - setup
  - macos
  - local
author: OmniClaude Team
skill_kind: methodology
args:
  - name: --preflight-only
    description: "Check this Mac against the minimum requirements and stop; changes nothing"
    required: false
  - name: --containers
    description: "Answer the Docker question yes in advance (also run the stack locally in Docker)"
    required: false
  - name: --no-containers
    description: "Answer the Docker question no in advance (native onex only)"
    required: false
  - name: --provider
    description: "The model: gemini | openrouter | openai (the developer's own key) | ollama (on this Mac, no key). Default: asked"
    required: false
  - name: --ollama-model
    description: "With --provider ollama: the model to download (default: chosen from the Mac's memory)"
    required: false
  - name: --workspace
    description: "Workspace directory (default: $OMNIBASE_PATH, else ~/code/omni)"
    required: false
  - name: --restart
    description: "Run every phase again instead of resuming"
    required: false
---

# omninode_dev_setup

**Announce at start:** "I'm using the omninode_dev_setup skill."

One script, `plugins/onex/skills/_bin/omninode-dev-setup.sh`, does the work. It runs
the same way from Claude Code or from a plain terminal, and works on a physical
Mac or inside a macOS VM. This skill starts it where the developer can answer
its prompts, then reports each phase to the developer the moment it finishes.

Everything runs on the developer's own Mac: native onex, and optionally the stack
in Docker, both on the developer's own model key or on Ollama running on the Mac. Nothing connects to the lab.

## Phases

| # | Phase | Changes the machine? |
|---|---|---|
| 0 | Preflight: macOS version, CPU, RAM, disk, VM or physical, admin rights, ports, shell profile | no |
| 1 | Base tools: Xcode command-line tools, Homebrew, gh, jq, python@3.13, uv | yes |
| 2 | Workspace: the canonical clones, and OMNIBASE_PATH and PATH in the shell profile | yes |
| 3 | onex, the local identity, the developer's model (their key, or Ollama installed with one model downloaded), one delegation on it | yes |
| 4 | Docker (optional): only if the developer says yes to the one question; Docker Desktop installed, or started if stopped, then the local stack on the same key | yes |
| 5 | Claude Code plugins: the full onex tree (`onex@omninode-tools-dev`, from the omniclaude clone), and `omni` and `onex-overlays` when this GitHub login can read omniclaude-internal and an SSH key is loaded | yes |
| 6 | Verify | no |

Minimum requirements are printed by phase 0. A Mac below them gets nothing
installed and a recommended VM size instead (exit code 3).

## Execution

### 1. Preflight first, in this session

Always run preflight before anything else and show its table to the developer:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/skills/_bin/omninode-dev-setup.sh" --preflight-only <args>
```

- Exit 3: the Mac is below the minimum. Relay the failed requirement and the
  recommended VM verbatim. **Stop.** Do not offer to install anyway.
- Exit 1: a fixable condition (not an admin account, a Rosetta shell, not macOS).
  Relay the `Next:` line and stop.
- Exit 0: relay the "Will set up" line. Native onex is set up on every run.
  If the line says Docker can be added, ask
  the developer the one question the run would ask: whether to also run the
  stack locally in Docker (about 10 GB of memory while it runs, and 10-20
  minutes the first time). Pass their answer as `--containers` or
  `--no-containers`, so the Terminal run does not ask it again. If Docker
  Desktop is installed but stopped, say the run will start it; if it is
  missing, say the run will install it. If the line says Docker is not
  offered, relay why: native onex alone covers delegations.
- The model (the run asks it before the Docker question). Unless `--provider` was given, ask which one:
  - **Gemini** (a Google AI Studio key), **OpenRouter** or **OpenAI** (their key;
    OpenAI needs credits on the account): the key
    itself is typed only in the Terminal window or a macOS dialog, at a hidden
    prompt right after preflight, before anything installs. If they have no key,
    say where to get one, or suggest Ollama.
  - **Ollama**: no key. It runs a model on the Mac, so it downloads one
    (sized to the Mac's memory, as omnimarket's model config declares) and is slower,
    especially on Intel or in a VM.
  Pass the answer as `--provider gemini|openrouter|openai|ollama`.

If `--preflight-only` was the argument, stop here.

### 2. Start the run where the developer can answer prompts

The run asks for the Mac administrator password (Homebrew, Xcode tools, Docker)
and their model key unless they chose Ollama (at the start, before anything installs). A Claude Code tool call has no
terminal, so open one:

```bash
/usr/bin/osascript -e "tell application \"Terminal\" to do script \"bash '${CLAUDE_PLUGIN_ROOT}/skills/_bin/omninode-dev-setup.sh' <args>\"" -e 'tell application "Terminal" to activate'
```

Tell the developer a Terminal window opened, that it will ask for their Mac
password once, and that they should answer its prompts there, never in this
chat. **Never ask the developer to paste a password or API key into this
session.**

If there is no desktop session (for example over ssh), run the script directly
with the Bash tool in the background instead. It then asks for the administrator
password and key through macOS dialogs if a desktop is present, and otherwise
fails the step that needs one with a `Next:` line saying so.

### 3. Report each phase as it finishes

The script appends one line per phase event to
`${TMPDIR}/omninode-onboarding/status`:

```
phase=2 name="Workspace (…)" result=PASS elapsed="1m 12s" note="…"
phase=3 name="onex, local identity and your model" result=FAIL elapsed="2m 03s" step="…" next="…"
result=COMPLETE
```

Watch that file (the Monitor tool with an until-loop on a new line, or re-read
it every 30–60 seconds). For every new `PASS`, `SKIPPED` or `FAIL` line, tell
the developer at once, in one sentence: the phase, the result, the elapsed
time, and for a FAIL the `step` and `next` fields verbatim. Do not wait for
the end to report. Stop watching at `result=COMPLETE`, a `FAIL`, or
`result=BELOW_MINIMUM`.

A FAIL means the run stopped. Re-running the same command resumes from the
failed phase; completed phases are verified, not redone.

### 4. Finish

On `result=COMPLETE`, tell the developer to open a new terminal (so `OMNIBASE_PATH`
and `PATH` apply) and to open Claude Code and sign in with their Anthropic account
(the first time it asks). In a new session the `/onex:` skills
(and `/omni:` ones, if phase 5 installed them) are loaded. A running session keeps
the plugins it started with. If phase 0 or phase 6 printed a warning about shell-profile exports,
repeat it.

## What this skill does NOT do

- Put any secret in this session. Passwords and keys go into the Terminal
  window or a macOS dialog, and from there over stdin into the tool that stores them.
- Install anything on a Mac below the minimum requirements.
- Connect to the lab in any way: no tailnet, no lab bus identity, no lab models.
- Linux or Windows.
