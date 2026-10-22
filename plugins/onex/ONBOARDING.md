# Onboarding a Mac

One command takes a Mac from nothing installed to a working delegation on your own
model key. Everything runs on your Mac. **Nothing here connects to the OmniNode lab:**
the run installs no tailnet client, requests no lab identity, reads no lab address and
points no model at a lab server.

> This page assumes no tool is installed yet: not Claude Code, Python, uv, git or gh.

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

You also need **a model key of your own**, unless you pick Ollama or a local model server.
One of:

- Google AI Studio (Gemini)
- OpenRouter
- OpenAI — the account needs credits
- Ollama — runs a model on this Mac instead, no key. Slower, especially on Intel.
- A local model server by URL — one you already run (LM Studio, llama.cpp, vLLM, MLX) that
  speaks the OpenAI API, on this Mac or your network. You give its URL and the model name
  it runs; no key. Setup stops, naming the URL, if nothing answers there.

Your key is read with the input hidden, stored in onex's key store on this Mac, and is
never printed, logged, or passed as a command-line argument.

---

## Run it

Fetch the script, check it is the one this page was written against, then run it:

```bash
curl -fsSL -o lab-onboarding.sh \
  https://raw.githubusercontent.com/OmniNode-ai/omniclaude/03bb86f966e209c37f548a5a639693b07eab5792/plugins/onex/skills/_bin/lab-onboarding.sh
echo "0cf6e9c8f8d5f797bb42d4a8f6cc74a3ec20db80999163ebc23393b4d63eea74  lab-onboarding.sh" | shasum -a 256 -c -
bash lab-onboarding.sh
```

Three lines rather than one, for two reasons. The URL names a **commit**, not a branch, so the
bytes it serves cannot change after this page was written. And `shasum -c` refuses to continue
if they did change anyway — it prints `lab-onboarding.sh: OK` when the download matches, and
`FAILED` otherwise, which stops you before `bash` ever sees the file. Do not skip that line.

Inside Claude Code you can instead run `/onex:omninode_dev_setup`, which does the same thing from
the plugin's own copy and needs no download.

To see what the run would do to this machine without touching it:

```bash
bash lab-onboarding.sh --preflight-only
```

### Reading the script before you run it

You now have the script on disk, so read it before running it — sensible on any machine you
care about, and required if your employer's policy says so:

```bash
less lab-onboarding.sh
```

Because the URL above is pinned to a commit and the checksum is verified, what you read is
exactly what runs.

### Following `dev` instead

If you specifically want the newest version rather than the pinned one, replace the commit SHA
in the URL with `dev`. Understand what you are choosing: `dev` is a moving branch, there is no
checksum to verify against, and the script that runs tomorrow is not necessarily the one you
read today. The pinned form above is the recommended one, and it is what the onboarding walks
are graded against.

### What the script installs: its anchor

The pinned script freezes what you **run**. Its anchor freezes what it **installs**. The script
names one omnibase_infra commit, `INFRA_ANCHOR` near the top of phase 2, and phase 2 checks
omnibase_infra out at that commit, never at the tip of `dev`. Every other repository follows from
it:

- a repository named in that commit's `.github/sibling-pins.yaml` is checked out at its pin;
- a repository with no pin there is checked out at the last commit of its default branch at or
  before the anchor's commit time;
- the workspace runtime config phase 2 writes names the anchor, and is recorded as one commit
  dated at the anchor, so `onex delegate` reports the same config commit on every Mac.

So the same pinned script installs the same commits no matter how far `dev` has moved since it
was emailed, and two people who ran it a week apart have the same code. Every clone is left at a
detached `HEAD`, which is expected.

**A fix reaches you through a new email, never through `dev`.** When something you were sent is
broken, the fix is merged, a script naming a newer anchor is published, and a new email pins that
script by commit and sha256. Running the script you already have again installs the same anchor
again; it never picks up the fix on its own.

### What it asks you

Every question comes before anything is installed:

0. **Only on a Mac that ran an earlier setup: set its leftovers aside?** See
   [A Mac that ran an earlier setup](#a-mac-that-ran-an-earlier-setup). Asked only when
   preflight found something that would interfere.
1. **Which model.** Gemini, OpenRouter, OpenAI, Ollama or a local model server by URL. For
   a local server you are asked its URL and model name, never a key. Then your key, with the input
   hidden. If this Mac already has a key stored you are offered it rather than asked again.
2. **Your models, for each key and for Ollama, in order.** After each key, onboarding lists
   the models that key can use, read from the provider's own list for it, and you pick one or
   more by number in the order to try them, for example `2,1`; the first is tried first. The
   models onex prefers come first, marked recommended. OpenRouter lists its free models. Ollama
   lists the models this Mac has the memory for. Nothing is picked for you, and each chosen model
   is tested in phase 3. Change them later with `onex models add-model`, `onex models reorder`
   and `onex models remove`.
3. **Whether to run the local stack in Docker.** "Not now" is a complete setup — you can
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
| 0 | Preflight | Reads the machine and what an earlier setup left. Changes nothing unless you agree to set leftovers aside. Asks the questions above. |
| 1 | Base tools | Xcode command-line tools, Homebrew, gh, jq, python@3.13, uv. |
| 2 | Workspace | The clones at the script's anchor (see above), `OMNIBASE_PATH`, your `PATH`. |
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

### Where `onex` finds its runtime config

`onex delegate` reads its runtime config from a config owner. It tries these in order and
uses the first that exists:

1. **`ONEX_WORKSPACE_CONFIG_ROOT`**, when it is set to a non-blank path.
2. **A sibling `omnibase_internal` checkout**, next to your workspace. This is the owner of
   a **registry install**, a workspace operated by the OmniNode team, which keeps its config
   in that private repository.
3. **`.onex/workspace-config`** inside your workspace. This is the owner of a **developer
   install**, the one this guide builds. Phase 2 writes it and exports
   `ONEX_WORKSPACE_CONFIG_ROOT` to point at it, so a developer install needs no private
   repository and no GitHub account. Its one commit names the script's anchor, so
   "materialised at" in `onex delegate`'s output is the same commit on every Mac set up
   from the same script.

If none of the three exists, `onex delegate` refuses before dispatching. The message names
`ONEX_WORKSPACE_CONFIG_ROOT` and phase 2 of this script: re-run the script so phase 2 writes
the config, rather than pointing the variable somewhere else.

---

## When it is done

You have a working setup when the run exits 0 and phase 6 reports every check passing.
Confirm it yourself, in a new terminal (or after `exec zsh`): the run writes `OMNIBASE_PATH`,
`ONEX_WORKSPACE_CONFIG_ROOT` and your `PATH` to your shell profile, and a terminal opened
before the run has none of them.

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

## A Mac that ran an earlier setup

An earlier install leaves things behind that quietly take over: an `onex` alias or function
in your shell profile, variables such as `OMNI_HOME`, `ONEX_STATE_DIR` or
`ONEX_LAB_TENANT_STATE_DIR`, a published `onex` installed as a uv or pipx tool, a
local-model routes file under `~/.omninode/delegation`, or clones with local changes.

Before installing anything, preflight runs `onex` the way a new terminal of yours would and
lists what it found in one table. Each row marked ✗ would interfere; rows marked · are
noted and handled by the run itself (for example, a clean clone that is behind is brought up
to date in phase 2). If anything is marked ✗, you are asked once:

- **Set them aside.** Profile lines are commented out (the whole file is copied first), files
  and clones are moved beside where they were, and published installs are uninstalled with
  the command to reinstall them. Nothing is deleted. Every item and how to put it back is
  listed in `~/.omninode/onboarding/set-aside.<time>.txt`.
- **Stop.** Nothing is installed or changed.

A run with no terminal to ask on stops at preflight in this case, unless you pass
`--set-aside`.

The run itself never inherits those variables, on a first run or a resumed one. Open a new
terminal when it finishes: the one you started it from still has the old settings loaded.

## Running it again

Re-running is safe and expected. Completed phases are verified and skipped, and a failed
phase restarts from its own beginning rather than from the top. This holds for a freshly
downloaded copy of the script too, because the record of completed phases lives under
`~/.omninode/onboarding`. Preflight always runs first; on a resumed run it says which phase
the run picks up at, reuses your earlier answers (your models, your stored keys and the
Docker answer) and asks only whether to continue. Nothing already installed is moved to a
different version.

To force every phase to run again:

```bash
bash lab-onboarding.sh --restart
```

---

## Options

| Option | Effect |
|---|---|
| `--preflight-only` | Run phase 0, print the verdict, exit |
| `--containers` / `--no-containers` | Answer the Docker question in advance |
| `--provider NAME` | `gemini`, `openrouter`, `openai`, `ollama` or `local`, or several, comma-separated |
| `--ollama-model NAME` | The model Ollama downloads, instead of asking; with no terminal, the one sized to this Mac |
| `--local-url URL` | With `local`: the model server's base URL, such as `http://127.0.0.1:1234` |
| `--local-model NAME` | With `local`: the model that server runs, as it names it |
| `--workspace DIR` | Where the clones go; defaults to `$OMNIBASE_PATH`, else `~/Code/omnibase`. `OMNI_HOME` is never read |
| `--set-aside` | Answer yes in advance to setting aside what an earlier setup left |
| `--restart` | Forget completed phases and your earlier answers, and run every phase again |
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
