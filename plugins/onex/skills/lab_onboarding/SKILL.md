---
description: Take a Mac from bare to lab-ready in one run — tools, workspace, tailnet, onex, a model, this machine's own lab bus identity, and optionally the local container stack — reporting each phase as it finishes
mode: full
version: 1.0.0
level: basic
debug: false
category: onboarding
tags:
  - onboarding
  - setup
  - macos
  - lab
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
    description: "Answer the Docker question no in advance (lab only)"
    required: false
  - name: --provider
    description: "Your own model key's provider: openrouter | gemini (default: asked). The lab's models are never used"
    required: false
  - name: --workspace
    description: "Workspace directory (default: $OMNIBASE_PATH, else ~/code/omni)"
    required: false
  - name: --restart
    description: "Run every phase again instead of resuming"
    required: false
  - name: --reissue-identity
    description: "Request a fresh lab bus identity even if one is stored"
    required: false
---

# lab_onboarding

**Announce at start:** "I'm using the lab_onboarding skill."

One script, `plugins/onex/skills/_bin/lab-onboarding.sh`, does the work. It runs
the same way from Claude Code or from a plain terminal, and works on a physical
Mac or inside a macOS VM. This skill starts it where the developer can answer
its prompts, then reports each phase to the developer the moment it finishes.

## Phases

| # | Phase | Changes the machine? |
|---|---|---|
| 0 | Preflight: macOS version, CPU, RAM, disk, VM or physical, admin rights, ports, shell profile | no |
| 1 | Base tools: Xcode command-line tools, Homebrew, gh, jq, python@3.13, uv | yes |
| 2 | Workspace: the canonical clones, and OMNIBASE_PATH and PATH in the shell profile | yes |
| 3 | Tailnet: Tailscale installed and signed in | yes |
| 4 | onex, the local identity, one model path, one delegation | yes |
| 5 | This machine's lab bus identity, issued automatically; one delegation on the lab dev lane | yes |
| 6 | Docker (optional, in addition to the lab): only if the developer says yes to the one question; Docker Desktop installed, or started if stopped, then the local stack | yes |
| 7 | Claude Code plugin `onex@omninode-tools` | yes |
| 8 | Verify | no |

Minimum requirements are printed by phase 0. A Mac below them gets nothing
installed and a recommended VM size instead (exit code 3).

## Execution

### 1. Preflight first, in this session

Always run preflight before anything else and show its table to the developer:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/skills/_bin/lab-onboarding.sh" --preflight-only <args>
```

- Exit 3: the Mac is below the minimum. Relay the failed requirement and the
  recommended VM verbatim. **Stop.** Do not offer to install anyway.
- Exit 1: a fixable condition (not an admin account, a Rosetta shell, not macOS).
  Relay the `Next:` line and stop.
- Exit 0: relay the "Will set up" line. The lab (this machine's own bus
  identity) is set up on every run. If the line says Docker can be added, ask
  the developer the one question the run would ask: whether to also run the
  stack locally in Docker (about 10 GB of memory while it runs, and 10-20
  minutes the first time). Pass their answer as `--containers` or
  `--no-containers`, so the Terminal run does not ask it again. If Docker
  Desktop is installed but stopped, say the run will start it; if it is
  missing, say the run will install it. If the line says Docker is not
  offered, relay why: the lab alone covers delegations.
- Then the model key. Developers bring their own key; the lab's models are
  never used. Unless `--provider` was given, ask which provider their key is
  from: OpenRouter or Gemini (a Google AI Studio key); the beta offers only
  these two. Pass it as `--provider openrouter|gemini`.
  The key itself is typed only in the Terminal window, at a hidden prompt that
  comes right after preflight, before anything installs. If they have no key
  yet, say where to get one and stop: the run refuses to start without one.

If `--preflight-only` was the argument, stop here.

### 2. Start the run where the developer can answer prompts

The run asks for the Mac administrator password (Homebrew, Xcode tools, Docker),
a Tailscale sign-in, and their model key (at the start, before anything installs). A Claude Code tool call has no
terminal, so open one:

```bash
/usr/bin/osascript -e "tell application \"Terminal\" to do script \"bash '${CLAUDE_PLUGIN_ROOT}/skills/_bin/lab-onboarding.sh' <args>\"" -e 'tell application "Terminal" to activate'
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
phase=3 name="Tailnet (…)" result=PASS elapsed="1m 12s" note="…"
phase=5 name="Lab bus identity (…)" result=FAIL elapsed="2m 03s" step="…" next="…"
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
and `PATH` apply) and that `/onex:delegate` is available in a new Claude Code
session. If phase 0 or phase 8 printed a warning about shell-profile exports,
repeat it.

## What this skill does NOT do

- Put any secret in this session. Passwords and keys go into the Terminal
  window or a macOS dialog, and from there over stdin into the tool that stores them.
- Install anything on a Mac below the minimum requirements.
- Set up a dedicated lab lane (compose project, ports, host account); the
  bus identity it issues is on the shared lab dev lane.
- Linux or Windows.
