---
description: Session environment preflight — runs the declared checks and prints one line per check with its fix command, at a volume set by the session intent (quiet, normal, tick).
version: 2.1.0
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

Run this block, passing the skill's own arguments (`--intent`, `--all`, `--receipt`, `--overlay`)
in place of `"$@"`. It first resolves the session's role, then runs the runner with the profile
that role allows:

```bash
# onex:preflight profile selection
# The role comes from the team identity resolver (omnimarket node_team_identity_compute), never
# from a guess here. Only a clean, successful answer naming the operator selects operator; any
# other outcome - a member, an unknown or unauthenticated identity, a missing or failing
# resolver, an unreadable answer - selects team. Unknown identity gets team restrictions.
PREFLIGHT_PROFILE=team
identity_login="$(gh api user --jq .login 2>/dev/null)" || identity_login=""
if [ -n "$identity_login" ] && command -v onex >/dev/null 2>&1; then
  identity_dir="$(mktemp -d)"
  python3 -c 'import json, sys; print(json.dumps({"claims": [{"source": "github_auth", "value": sys.argv[1]}]}))' \
    "$identity_login" > "$identity_dir/request.json"
  if identity_receipt="$(onex node node_team_identity_compute --input "$identity_dir/request.json" \
      --output receipt --state-root "$identity_dir/state" --timeout 60 2>/dev/null)"; then
    PREFLIGHT_PROFILE="$(printf '%s' "$identity_receipt" | python3 -c '
import json, sys
try:
    receipt = json.loads(sys.stdin.read())
except ValueError:
    receipt = None
result = receipt.get("result") if isinstance(receipt, dict) else None
operator = (
    isinstance(result, dict)
    and receipt.get("status") == "success"
    and result.get("privileges") == "operator"
    and result.get("role") == "operator"
)
print("operator" if operator else "team")
' 2>/dev/null)" || PREFLIGHT_PROFILE=team
  fi
  rm -rf "$identity_dir"
fi
[ "$PREFLIGHT_PROFILE" = operator ] || PREFLIGHT_PROFILE=team
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/session_preflight.py" --profile "$PREFLIGHT_PROFILE" "$@"
```

The runner's own usage, for a caller that has already resolved the profile:

```text
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/session_preflight.py" --profile <operator|team> [--intent <intent>] [--all] [--receipt <path>] [--overlay <path>]
```

From a source checkout the same file is `plugins/onex/scripts/session_preflight.py`.

## Profiles: operator and team

The runner takes `--profile operator|team` (default `operator`). A check in the overlay may carry
`profile: operator`, meaning it reads something only the operator's machine has (a local
controller, a coordination host). Under `team` those checks do not run; every other check still
runs and still blocks. A check with no `profile` key runs in every profile, so an overlay with no
profile keys gives the same result under `operator` as it always has.

The skill picks the profile from the team identity resolver, through `onex node
node_team_identity_compute`, with the session's authenticated GitHub login as the claim. It runs
`operator` only when the resolver positively matches the operator. A member, an identity the
declaration does not name, no authenticated login, a resolver that is not installed, fails or
answers something unreadable all run `team`, never `operator`.

These are refused with exit status `2`: a check whose `profile` is anything but `operator` (any
other value or type), an unknown `--profile`, and a `team` run whose filtered set is empty. A typo
must never remove a blocker from a run.

The receipt keeps its fields (`intent`, `verdict`, `passed`, `total`, `checks`) and adds
`profile`, `overlay_path`, `overlay_sha256`, `included_check_ids`, `skipped_check_ids`,
`passed_check_ids` and `failed_check_ids`, so a reader can validate what actually ran.

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
| `2` | the run refused: no overlay, an unreadable or malformed overlay, a check with no fix line, an unknown check kind, an unknown profile on a check or on the command line, a `team` run with no check left to run, or `tick` with no receipt path. The reason names what to change. |

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
