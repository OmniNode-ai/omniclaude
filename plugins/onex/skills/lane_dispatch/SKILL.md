---
description: Dispatch a worker lane from a named brief with the standing rules block resolved and injected, a claim row appended before the lane's first write, and the model named explicitly. Thin process interface — the overlay names the brief directory, the rules block and the claim surface.
version: 1.0.0
mode: full
level: advanced
debug: false
category: workflow
tags:
  - process
  - dispatch
  - lane
  - overlay-configured
author: OmniClaude Team
composable: false
user_invocable: true
process_catalogue_row: lane_dispatch
skill_kind: methodology
overlay_env: LANE_DISPATCH_OVERLAY_PATH
args:
  - name: --brief
    description: "Name of the brief to dispatch, resolved inside the overlay's brief directory."
    required: true
  - name: --lane
    description: "Lane name. Must be unique among live lanes and is the identifier every later row cites."
    required: true
  - name: --model
    description: "Model the lane runs on. Required — never inherited."
    required: true
  - name: --intent
    description: "Session intent — quiet | normal | tick. Controls how much preflight output reaches the transcript."
    required: false
  - name: --dry-run
    description: boolean flag
    required: false
---

# Lane dispatch

**Catalogue row**: `lane_dispatch` · **Replacement**: none yet

This skill is a **temporary prose interface** over the most-repeated process in
the catalogue and the one most often run from memory. It owns no orchestration.

## What it wraps

A brief from the overlay's brief directory, plus the standing rules block that
every lane is meant to inherit. Which briefs exist, where the rules block lives,
and where a claim is appended are **overlay content**.

## Why the rules block is resolved rather than assumed

A lane driven by a brief inherits the standing rules; a lane dispatched raw does
not, and a lane that has never read them behaves like the last one it saw. So
the rules block is **read from the overlay and injected into the dispatch as
text**, every time. A dispatch that could not resolve the rules block is a hard
stop, not a dispatch with the rules omitted.

**Committed, never the working tree.** The rules block and the brief are read
at a commit with the shared helper, never opened from disk:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/read_committed_file.py" --repo <root> --path <rules_block_path>
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/read_committed_file.py" --repo <root> --dir <brief_directory> --stem <brief>
```

A clone that several sessions share carries their uncommitted edits in its
working tree, so reading from disk injects another session's unreviewed text
into every lane this dispatch starts, and an untracked brief of the right name
would be dispatched as if it were a real one. The helper refuses, exit `2`, on a
missing or empty file, and names the commit it read on stderr.

## Overlay

Resolve the overlay with the shared resolver, the same search order every
overlay-configured skill uses:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/resolve_skill_overlay.py" lane_dispatch
```

| Order | Location | Kind |
| -- | -- | -- |
| 1 | `LANE_DISPATCH_OVERLAY_PATH` | explicit pointer — a miss is a hard stop, never a fall-through |
| 2 | each root in `ONEX_SKILL_OVERLAY_ROOTS`, joined with `lane_dispatch/overlay.yaml` | discovered |

It prints the resolved path, or exits non-zero naming every location it
tried. **A non-zero exit is a hard stop**, not a fall back to a default —
there is no default. Report its standard error and stop.

| Field | What it holds |
| -- | -- |
| `brief_directory` | where named briefs are resolved from |
| `rules_block_path` | the standing rules every dispatch injects |
| `claim_command` | how a claim row is appended, under its lock |
| `claim_surface` | what a later row cites to resolve the authorization |
| `model_choices` | the models a lane may be given, and what each is for |

## Preflight, by intent

Run the preflight at the given intent before dispatching. A blocker stops the
dispatch: a lane started into a broken environment spends its budget finding
that out.

## Verification contract

**A claim row is appended before the lane's first write; the rules block is
resolved and injected rather than assumed; and the model is named explicitly.**

Each half is separately checkable and each fails silently on its own:

- **Claim before first write.** The row is appended through `claim_command`, so
  the append is serialized against every other lane. Appended *after* the first
  write, it records a lane that was already unobservable to its peers.
- **Rules resolved, not assumed.** Report the byte count, the path and the
  commit of the injected block. A dispatch reporting zero bytes injected did
  not inject them, and one that cannot name a commit read the working tree.
- **Model named.** `--model` is required and is never inherited from the
  dispatching session. A lane whose model was inherited cannot be costed, and
  cheaper is not the same work.

## Mechanical replacement

**none yet.** The replacement is a refusal at the dispatch seam: no lane starts
without a resolvable brief, an injected rules block and a named model, with the
claim appended by the seam itself rather than by the caller. That is the same
primitive as an admission guard — refuse the write where the omission is
observable — and it is the only form that survives somebody being in a hurry.

## What this skill does NOT do

- Dispatch without an injected rules block
- Inject a rules block or a brief read from the working tree
- Infer a model, or let one be inherited
- Message a lane after dispatch; a message resumes a stopped lane and it
  resumes spending
- Name a brief, a lane, a path or a repository in this file
