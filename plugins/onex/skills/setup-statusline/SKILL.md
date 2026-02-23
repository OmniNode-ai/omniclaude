---
name: setup-statusline
description: Configure Claude Code status line to show folder name, git branch, and PR number
version: 1.0.0
category: configuration
tags: [statusline, setup, configuration]
author: OmniClaude Team
---

# Setup ONEX Status Line

Configure your Claude Code status line to show folder name, git branch, and PR number.

## What This Does

1. Creates a symlink from `~/.claude/statusline.sh` to the plugin's statusline script
2. Updates `~/.claude/settings.json` to use the custom status line

## Status Line Format

```
[folder_name] branch_name #PR_number
```

- **Folder**: Cyan - Shows which worktree you're in (e.g., `omniclaude`)
- **Branch**: Green - Current git branch
- **PR**: Magenta - PR number if one exists for the branch (cached, background refresh)

## Installation

Run this command to set up the status line:

```bash
# Create symlink to plugin's statusline script
ln -sf "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/statusline.sh" ~/.claude/statusline.sh

# The settings.json update needs to be done manually or via the command below
```

Then update your `~/.claude/settings.json` to include:

```json
{
  "statusLine": {
    "type": "command",
    "command": "~/.claude/statusline.sh",
    "padding": 0
  }
}
```

## Execution

When you run `/setup-statusline`, perform these actions:

1. Create the symlink:
   ```bash
   ln -sf "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/statusline.sh" ~/.claude/statusline.sh
   ```

2. Read the user's current `~/.claude/settings.json`

3. Update the `statusLine` field to:
   ```json
   "statusLine": {
     "type": "command",
     "command": "~/.claude/statusline.sh",
     "padding": 0
   }
   ```

4. Verify the setup works by testing the script

5. Inform the user to restart their Claude session to see the new status line
