---
description: Session environment preflight — runs the declared checks and prints one line per check with its fix command, at a volume set by the session intent (quiet, normal, tick).
version: 2.0.0
user_invocable: true
mode: full
level: intermediate
debug: false
category: operations
tags:
  - preflight
  - session-readiness
  - session-intent
  - environment
  - health-check
author: OmniClaude Team
composable: true
args:
  - name: --intent
    description: "Session intent: quiet (print nothing but a blocker), normal (summary plus every check to act on), tick (print nothing; write the verdict to --receipt). Defaults to the resolved session intent."
    required: false
  - name: --all
    description: "Print one line for every check, including the ones that passed."
    required: false
  - name: --receipt
    description: "Path to write the verdict to as JSON. Required under --intent tick."
    required: false
---

# Preflight

Runs the session environment checks and prints, for each one that is not a clean pass, a single
line carrying that check's own fix command.

This skill is a **shim**. It holds no check recipe: the checks run in one place, the runner below,
so a check body has exactly one home and cannot drift between a script and a prose copy of itself.

## Run it

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/session_preflight.py" [--intent <intent>] [--all] [--receipt <path>] [--overlay <path>]
```

From a source checkout the same file is `plugins/onex/scripts/session_preflight.py`.

## What it needs

A **preflight overlay** — the YAML file declaring this environment's checks. The runner carries
none: a run against an absent overlay would report a green preflight that checked nothing, which is
worse than no preflight at all.

The overlay is **discovered**, not guessed. Locations are searched in this order, and the first one
that resolves wins:

| Order | Location | Kind |
| -- | -- | -- |
| 1 | `--overlay <path>` | explicit pointer |
| 2 | `SESSION_PREFLIGHT_OVERLAY_PATH` | explicit pointer |
| 3 | each root in `ONEX_SKILL_OVERLAY_ROOTS`, joined with `session_preflight/overlay.yaml` | discovered |
| 4 | `$XDG_CONFIG_HOME/onex/overlays/session_preflight/overlay.yaml`, or `~/.config/...` | discovered |

An **explicit** pointer that names a file that is not there is a hard stop, never a fall-through: a
run told to use one overlay and silently handed another is the wrong answer, quietly. A
**discovered** location that is empty falls through to the next.

When none of them resolves, the run refuses and names every location it tried, plus the command
that fixes it:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/session_preflight.py" --install-overlay <path to your overlay>
```

That copies the overlay into location 4, so a machine that sets no variables at all has a reachable
preflight from then on. It validates before it writes, so an overlay that could not have run is
refused at install time rather than at the start of the next session. It moves a file you already
have; it never writes check content of its own.

The overlay declares, per check: an id, a title, a kind (`env_set`, `env_path`, `path_exists`,
`command`), a severity (`blocker` or `warning`), and a `fix` line. The `fix` is required. A check
declared without one is a configuration error and the whole run refuses, because a failure a reader
cannot act on is the thing this skill exists to remove.

## Session intent decides the volume

Intent is resolved by the shared resolver the SessionStart hooks use, so the hooks and this skill
never disagree about what kind of session this is. Highest precedence first: the `--intent`
argument, then `OMNICLAUDE_SESSION_INTENT`, then a fresh per-session marker file, then the
persistent preference, then `normal`.

| Intent | What it prints |
| -- | -- |
| `quiet` | nothing when every check passes; otherwise only the blockers, one line each, no summary. A session opened to re-authenticate or to check connectivity asked for silence, and it gets silence or a blocker. |
| `normal` | one summary line, then one line per check that is not a clean pass. `--all` widens that to every check. |
| `tick` | nothing at all; the same verdict is written as JSON to `--receipt`, which is required under this intent. A verdict with nowhere to go is a verdict nobody reads. |

Nothing ever *infers* `quiet`. Every fall-through in the resolver lands on `normal`: a
wrongly-quiet session hides a blocker, a wrongly-normal session costs one line.

## Reading the result

Exit status is the verdict, so a caller does not have to parse the text:

| Status | Meaning |
| -- | -- |
| `0` | every blocker passed. Warnings may still have been printed; they never block. |
| `1` | at least one blocker failed. Each one printed its own fix command. |
| `2` | the run refused: no overlay, an unreadable or malformed overlay, a check with no fix line, an unknown check kind, or `tick` with no receipt path. The reason names what to change. |

Present the runner's own lines. Do not summarise them, re-word a fix command, or add a verdict
banner: the line a reader has to act on is the fix command exactly as the overlay spells it.

## Verification contract

The run is done when every failing check has been printed with its fix command, and, under `tick`,
when the receipt exists and carries the same verdict as the exit status.

## What replaces this

A prose skill is a temporary interface. The mechanical replacement is the session orchestrator's
own health gate calling this runner directly, so the checks run whether or not anybody remembers
the skill name. That work is not ticketed yet; until it is, this skill is the only path from a
person to the checks, which is the state the previous revision of this file failed at — it declared
itself non-invocable and named a replacement skill that performs no preflight.

## See also

- `/onex:start_environment` — bring services up before checking them.
- `/onex:system_status` — the fuller health picture, after a session has started.
