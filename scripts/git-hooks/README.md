# Custom Git Hooks

This directory contains custom git hook wrappers that are tracked in version control. The hooks in `.git/hooks/` are local and untracked, so this directory serves as the canonical source.

## Hooks

### `pre-push`

Wraps the standard `pre-commit` pre-push hook with a fix for the `index.lock` race condition.

**Problem**: The `pre-commit` framework's `staged_files_only` context manager calls `git write-tree` during pre-push, which requires `.git/index.lock`. After a recent `git commit` (which also runs pre-commit hooks), the lock file can still exist momentarily, causing `git push` to fail with:

```
fatal: Unable to create '.git/index.lock': File exists.
```

**Fix**: The wrapper checks for a stale `index.lock` and removes it only if no git process that would hold the lock is currently running. It then delegates to `pre-commit` as normal.

## Installation

Copy the hooks into `.git/hooks/` and ensure they are executable:

```bash
cp scripts/git-hooks/pre-push .git/hooks/pre-push
chmod +x .git/hooks/pre-push
```

**Note**: Running `pre-commit install --hook-type pre-push` will overwrite `.git/hooks/pre-push` with the default generated version. Re-copy from this directory after re-installing pre-commit hooks.
