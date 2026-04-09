---
description: Thin skill that dispatches to a node — compliant example
mode: full
version: 1.0.0
level: basic
debug: false
category: quality
args:
  - name: --repos
    description: "Comma-separated repo names"
    required: false
  - name: --dry-run
    description: Report only
    required: false
---

# Example Thin Trigger Skill

## Overview

Thin skill that dispatches to `node_example` via `onex run`.

**Announce at start:** "I'm using the example skill."

## How It Works

1. Parse arguments from the frontmatter `args:` block.
2. Dispatch to the node:

```bash
uv run onex run node_example -- \
  --repos "${REPOS}" \
  --dry-run
```

3. Read result from `$ONEX_STATE_DIR/skill-results/`.
4. Report results to the user.

## Wiring

```
skill  -> plugins/onex/skills/example/ (thin wrapper)
node   -> omnimarket/src/omnimarket/nodes/node_example/ (all logic)
```

This skill is a **thin wrapper** — it parses arguments, dispatches to the omnimarket
node via `onex run node_example`, and renders results.
