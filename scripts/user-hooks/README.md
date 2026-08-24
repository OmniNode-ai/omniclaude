# User-level Claude Code hooks (tracked sources)

Hooks in this directory are registered in `~/.claude/settings.json`, **not** in
`plugins/onex/hooks/hooks.json`. They are user-level on purpose: they must keep
working while the onex plugin is switched, broken, or mid-redeploy. As a
consequence `deploy_local_plugin` does not install them — each has its own
installer, and the installed copy under `~/.claude/hooks/` is a byte-for-byte
copy of the file here. Never edit the installed copy in place.

| Tracked source | Live location | Installer | Tests |
|---|---|---|---|
| `canonical-clone-guard.py` | `~/.claude/hooks/canonical-clone-guard.py` | `scripts/install-canonical-clone-guard.sh [--apply]` | `tests/scripts/test_canonical_clone_guard.py` |

## canonical-clone-guard.py (OMN-7018 rule 9, hardened in OMN-16496)

PreToolUse guard that keeps agents out of the canonical clones under
`$OMNI_HOME/<repo>`: denies Edit/Write/NotebookEdit into a clone and any git
mutation whose effective directory is a clone — porcelain **and** the plumbing
that moves refs/index/worktree underneath it (`update-ref`, `symbolic-ref`
writes, `read-tree`, `checkout-index`, `update-index`, `replace`,
`filter-branch`, `branch` create/-f/-D/-m/-c/-u, `clean` without `-n`,
`fetch`/`pull` with a refspec into a local branch, nested `worktree
remove|move`). Read-only forms stay allowed, as do `pull`/`fetch`, `worktree
add`, and `worktree remove` of a worktree under `omni_worktrees/`.

`cd`, `pushd` and `git -C` arguments are expanded (`$VAR`, `${VAR}`,
`${VAR:-d}`, `~`, plus `VAR=value` assignments earlier in the same command)
before matching; an unresolvable path is an unknown location and is never
glued onto cwd.

Redeploy after changing the source:

```bash
bash "$OMNI_HOME/omniclaude/scripts/install-canonical-clone-guard.sh"          # report drift
bash "$OMNI_HOME/omniclaude/scripts/install-canonical-clone-guard.sh" --apply  # install (operator action: live hook change)
```

## Converging a dirty canonical clone

The guard blanket-denies `checkout`/`restore`/`reset`/`stash` in a clone, so the
ONE sanctioned way back to upstream is:

```bash
bash "$OMNI_HOME/omniclaude/scripts/converge-canonical-clone.sh" <repo>            # dry-run report
bash "$OMNI_HOME/omniclaude/scripts/converge-canonical-clone.sh" <repo> --execute  # preserve, then reset --hard @{u}
```

It preserves `status`, staged/unstaged/full patches, untracked copies, reflog
and a sha256 manifest under `$OMNI_HOME/.onex_state/canonical-clone-converge/`,
verifies `HEAD == @{u}` with a clean tracked tree, and appends a ledger row.
Tests: `tests/scripts/test_converge_canonical_clone.py`.
