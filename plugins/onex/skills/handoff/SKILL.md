---
description: Assemble and validate the session handoff, or resume from the newest one, through node_handoff_check_effect; a ruling with no status refuses the handoff
mode: full
version: 3.0.0
level: advanced
debug: false
category: workflow
tags:
  - handoff
  - session
  - dispatch-only
  - routing-enforced
author: OmniClaude Team
args:
  - name: command
    description: "assemble, resume or record-slice"
    required: true
  - name: --lane
    description: "Your lane name, for the inbox reader"
    required: false
  - name: --session
    description: "Session name used in the handoff file name"
    required: false
skill_kind: methodology
---

# /onex:handoff — Session Handoff

**Skill ID**: `onex:handoff`
**Version**: 3.0.0
**Backing node**: `node_handoff_check_effect` (omnimarket)

The skill holds no logic. The handoff contract (sections, ruling statuses, stale ages,
probes) and the check live in the node; this file only says how to call it and what to do
with its answer.

**Announce at start:** "I'm using the handoff skill."

## Changelog

- **3.0.0** — Thinned to a dispatch-only shim over `node_handoff_check_effect`. The six
  prose enforcement behaviors, `prompt.md` and the terminal commit into the retired
  registry tree are removed; the node declares the contract and refuses an unaccounted ruling.
- **2.0.0** — Six prose enforcement behaviors (claim lint, supersession, terminal commit,
  stale-doc findings, scorecard, deep-dive reconcile).

## Write a handoff

`ONEX_LEDGER_PATH` must be set (there is no default). Call the node:

```bash
uv run onex run-node node_handoff_check_effect --input '{
  "command": "assemble",
  "session": "<name>",
  "lane": "<lane>",
  "goal_file": "<operator-words.txt>",
  "statuses": "<statuses.json>",
  "unverified_file": "<unverified.txt>",
  "plans": ["<plan.md>"],
  "prs": ["<repo>#<n>"]
}'
```

The terminal event carries `exit_code`, `output` (the lines the check printed) and `refused`.

1. `exit_code` 1 is `HANDOFF REFUSED`: one `UNACCOUNTED` line per ruling or consent in the
   window that has no status. An unhealthy service is a recorded line, never a refusal.
2. Fill what the node cannot read: put the operator's own words in the goal file, list what
   you did not verify in the unverified file, and give each unaccounted item a status in the
   statuses JSON: `{"<item>": {"status": "done|in_flight|dropped|held", "evidence": "<ledger row or PR>"}}`.
   Never invent evidence; if you cannot name it, the status is `held` and the item goes on the
   unverified list.
3. Call again until `exit_code` is 0 and the output says `HANDOFF OK`. Report the
   `DROPPED-DECISIONS` line it prints; do not argue with it.
4. Write it by adding `"out_dir": "<worktree of the shared document clone>/beta/handoffs"` to
   the input (a worktree cut from the clone's origin/main; never pass `now`, the clock is the
   read time), then commit and open the PR through the normal document route for that clone.
   Never write into the registry root or the plugin cache.

## Resume a handoff

```bash
uv run onex run-node node_handoff_check_effect --input '{
  "command": "resume",
  "kb_clone": "<shared document clone>"
}'
```

The node reads the newest committed `beta/handoffs/*-handoff.md` at `origin/main` from the
clone's object store (never the working tree), re-probes every line that is stale now, and
prints `CHANGED`, `UNCHANGED` or `UNREADABLE` per line plus the rulings, consents and holds
written since. `exit_code` 3 means no handoff exists. Start from the `CHANGED` lines.

## Rules the node enforces

- Every factual line ends `[src: <reader>; read: <UTC>; ttl: <s>; ...]`; past its ttl it gains `STALE`.
- A ruling or consent with a missing, unknown or evidence-free status refuses the handoff.
- A ruling on an umbrella ticket never gets a derived status; the writer declares one.
- Facts come from the readers, never from memory or a summary.

`onex run-node` needs a reachable broker and a runtime consuming the node's topics. Where
there is none, run the packaged node locally with `uv run onex node node_handoff_check_effect --input <file>`
from an omnimarket checkout.
