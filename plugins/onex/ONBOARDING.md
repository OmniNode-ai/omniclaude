# Onboarding a Mac

One command takes a Mac from nothing installed to a working delegation on your own
model key. Everything runs on your Mac. **Nothing here connects to the OmniNode lab:**
the run installs no tailnet client, requests no lab identity, reads no lab address and
points no model at a lab server.

> This is not [GETTING_STARTED.md](GETTING_STARTED.md). That guide is for adding the
> ONEX plugin to an existing developer machine and assumes Claude Code, Python, uv, git
> and gh are already installed. This page assumes none of them are.

---

## Before you start

| | Minimum | For the Docker stack as well |
|---|---|---|
| macOS | 14 or newer | 14 or newer |
| CPU cores | 4 | 8 |
| Memory | 8 GB | 16 GB |
| Free disk | 20 GB | 30 GB (20 GB if Docker Desktop is already installed) |

The run checks all of this before it changes anything. Below the minimum it stops and
installs nothing.

You also need **a model key of your own**, unless you pick Ollama. One of:

- Google AI Studio (Gemini)
- OpenRouter
- OpenAI — the account needs credits
- Ollama — runs a model on this Mac instead, no key. Slower, especially on Intel.

Your key is read with the input hidden, stored in onex's key store on this Mac, and is
never printed, logged, or passed as a command-line argument.

---

## Run it

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/OmniNode-ai/omniclaude/dev/plugins/onex/skills/_bin/lab-onboarding.sh)
```

Inside Claude Code you can instead run `/onex:lab_onboarding`. Both do the same thing.

To see what the run would do to this machine without touching it:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/OmniNode-ai/omniclaude/dev/plugins/onex/skills/_bin/lab-onboarding.sh) --preflight-only
```

### Reading the script before you run it

Be aware of what that one-liner is: it executes a script fetched over the network, from a
branch, with no checksum and no signature. `dev` moves, so the script you read today is not
necessarily the one that runs tomorrow. If you would rather look before you run — sensible on
any machine you care about, and required if your employer's policy says so — fetch it, read
it, then run it:

```bash
curl -fsSL -o lab-onboarding.sh https://raw.githubusercontent.com/OmniNode-ai/omniclaude/dev/plugins/onex/skills/_bin/lab-onboarding.sh
less lab-onboarding.sh
bash lab-onboarding.sh
```

To pin a fixed version rather than following `dev`, replace `dev` in either URL with a commit
SHA. GitHub shows the SHA on the file's page, under History. The script then cannot change
between reading it and running it.

### What it asks you

Two questions, both before anything is installed:

1. **Which model.** Gemini, OpenRouter, OpenAI or Ollama. Then your key, with the input
   hidden. If this Mac already has a key stored you are offered it rather than asked again.
2. **Whether to run the local stack in Docker.** "Not now" is a complete setup — you can
   add it later. In a macOS VM the question is skipped, because Docker cannot run there.

Every prompt has a **Quit setup** option. Choosing it before phase 1 leaves the machine
untouched.

---

## What happens, phase by phase

Each phase prints PASS or FAIL the moment it finishes — in the terminal, as a macOS
notification, and as a line in the status file. You never have to wait until the end to
find out something failed.

| | Phase | What it does |
|---|---|---|
| 0 | Preflight | Reads the machine. Changes nothing. Asks the two questions above. |
| 1 | Base tools | Xcode command-line tools, Homebrew, gh, jq, python@3.13, uv. |
| 2 | Workspace | The canonical clones, `OMNIBASE_PATH`, your `PATH`. |
| 3 | onex + model key | The dispatch venv, onex, a local identity, your key, and **one delegation run on it**. |
| 4 | Docker | Only if you said yes. Installs or starts Docker Desktop, then the local stack on the same key. |
| 5 | Claude Code | The onex plugin from your omniclaude clone. |
| 6 | Verify | One line per check for the modes you chose. |

**No GitHub account is needed.** The repositories the run clones are public, cloned
over HTTPS, and nothing in the run asks you to log in to GitHub.

Phase 5 is the one place that notices. Besides the onex plugin, which comes from your
own clone and always installs, it offers two internal plugins from a private
repository. Reading that needs a GitHub login with access and a loaded SSH key, so
without them the run checks, says so, and skips them — which is why the phase is
called "omni where you have access". **A skipped internal-plugins step is the correct
outcome, not a failure.** Everything the setup is for works without them.

Phase 3 is the one that matters: it ends by running a real delegation and reading back the
receipt. If phase 3 passes, the machine works.

---

## When it is done

You have a working setup when the run exits 0 and phase 6 reports every check passing.
Confirm it yourself:

```bash
onex delegate "Reply with exactly one word: hello"
```

That prints the path to a `receipt.json`. The receipt names the model that answered and
the route it took. A delegation with `status: success` and a receipt naming your own
provider is the whole point of the setup.

**Exit codes**

| | |
|---|---|
| 0 | Every selected phase passed |
| 1 | A phase failed — the message names the step and what to run next |
| 2 | Bad usage |
| 3 | This Mac is below the minimum; nothing was installed |
| 4 | You chose "Quit setup" before anything was installed |

---

## Opening the dashboard

The local dashboard is a separate command, not part of the setup run:

```bash
onex dashboard
```

It binds `127.0.0.1` only, mints a fresh token each time it starts, and **prints its
URL as its first line of output**. There is no fixed address and no fixed port — open
the URL it prints. Overview and Runs are pages on that server.

The URL is printed before the server is listening, so if the page does not load
immediately, give it a moment and reload. It is ready once it answers; the local
checks poll `/projections` until it returns 200.

Leave the command running while you use the page. Stopping it stops the dashboard.

Runs and Overview only have something to show once you have run delegations on this
machine, so do the setup first.

---

## Running it again

Re-running is safe and expected. Completed phases are verified and skipped, and a failed
phase restarts from its own beginning rather than from the top. Nothing already installed
is moved to a different version.

To force every phase to run again:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/OmniNode-ai/omniclaude/dev/plugins/onex/skills/_bin/lab-onboarding.sh) --restart
```

---

## Options

| Option | Effect |
|---|---|
| `--preflight-only` | Run phase 0, print the verdict, exit |
| `--containers` / `--no-containers` | Answer the Docker question in advance |
| `--provider NAME` | `gemini`, `openrouter`, `openai` or `ollama` |
| `--ollama-model NAME` | The model Ollama downloads; the default is sized to this Mac |
| `--workspace DIR` | Where the clones go; defaults to `$OMNIBASE_PATH`, else `~/code/omni` |
| `--restart` | Forget completed phases and run them all again |
| `-h`, `--help` | The full option list |

---

## If something fails

The failure message names the failed step and the command to run to see the error. Nothing
is retried silently: every step that touches the network is attempted at least three times,
5 to 10 seconds apart, before it is reported as a failure.

If you are running this as a walk (OMN-20220 or OMN-20221), do not work around a failure
and do not ask a builder for a command that is not on this page — record both on the walk
ticket. A command you needed that is not documented here is the finding, not a detour.

---

## Compatibility

The script runs under macOS's stock `/bin/bash` 3.2 as well as a modern bash, and on both
Apple silicon and Intel. It also runs in a macOS 14+ VM with 4 vCPU, 8 GB RAM and 40 GB
disk, where the Docker stack is not offered.
