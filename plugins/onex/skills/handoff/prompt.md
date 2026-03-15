# /handoff — Implementation Prompt

## Behavior

When the user invokes `/handoff`, execute the following steps:

### Step 1: Gather Context

Collect the current session context:

1. **CWD**: The current working directory
2. **CWD hash**: First 8 chars of SHA-256 of the CWD path
3. **Repo slug**: Git repo name from `git remote get-url origin`, or directory name as fallback
4. **Active ticket**: From `~/.claude/pipelines/*/state.yaml` (if any pipeline is in-progress)
5. **Branch**: From `git branch --show-current`
6. **Recent commits**: Last 5 commits from `git log --oneline -5`
7. **Working files**: Changed files from `git status --short`
8. **User message**: Optional `--message` argument (free text for the next session)

### Step 2: Write Manifest

Write the manifest to `~/.claude/handoff/{cwd_hash}-{repo_slug}.json`.

**Atomicity protocol**:
1. Serialize manifest as JSON
2. Write to `{manifest_path}.tmp`
3. `mv {manifest_path}.tmp {manifest_path}` (atomic on POSIX)

```bash
HANDOFF_DIR="${HOME}/.claude/handoff"
mkdir -p "$HANDOFF_DIR"

CWD_HASH=$(echo -n "$PWD" | shasum -a 256 | cut -c1-8)
REPO_SLUG=$(basename "$(git remote get-url origin 2>/dev/null)" .git 2>/dev/null || basename "$PWD")

MANIFEST_PATH="${HANDOFF_DIR}/${CWD_HASH}-${REPO_SLUG}.json"
```

### Step 3: Confirm and Clear

Print a confirmation message:

```
Session context saved for handoff.
Manifest: ~/.claude/handoff/{cwd_hash}-{repo_slug}.json

To enable injection on next session start:
  export OMNICLAUDE_SESSION_HANDOFF=1

The next session in this directory will receive the context automatically.
```

**Do NOT automatically clear the session.** The user can `/clear` manually after reviewing
the handoff confirmation.

### Error Handling

- If git commands fail (not a git repo): proceed without git context fields
- If manifest directory creation fails: log error, do not clear session
- If atomic write fails: log error, do not clear session
- Never clear the session if the manifest write was not successful

### Manifest Schema

```json
{
  "version": 1,
  "created_at": "<ISO 8601 UTC>",
  "cwd": "<absolute path>",
  "cwd_hash": "<8-char hex>",
  "repo_slug": "<repo name>",
  "message": "<user message or null>",
  "context": {
    "active_ticket": "<OMN-XXXX or null>",
    "branch": "<branch name or null>",
    "recent_commits": ["<oneline>", ...],
    "working_files": ["<path>", ...]
  }
}
```
