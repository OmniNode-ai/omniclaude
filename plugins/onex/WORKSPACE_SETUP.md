# Multi-Repo Workspace Setup

Instructions for Claude Code agents to set up or work within a multi-repo workspace.

---

## When a User Asks You to Set Up a Multi-Repo Workspace

Execute the following steps. All commands are yours to run — do not give the user manual steps.

---

## Directory Structure

```
my_home/                    ← open Claude Code here
├── CLAUDE.md               ← shared context: standards, infra, repo registry, worktree policy
├── docs/
│   └── tools/
│       └── pull-all.sh    ← syncs all repos to latest main
├── repo-a/                 ← clone of github.com/you/repo-a
│   └── CLAUDE.md           ← repo-specific: architecture, patterns, commands
├── repo-b/
│   └── CLAUDE.md
└── repo-c/
    └── CLAUDE.md

my_worktrees/               ← all feature branches live here (separate directory)
└── TICKET-123/
    ├── repo-a/             ← git worktree branched from my_home/repo-a
    └── repo-b/
```

**Invariant**: repos under `my_home/` always track `main` and are never committed to directly. All feature work happens in worktrees under `my_worktrees/`.

---

## Create the Workspace Root

```bash
mkdir ~/Code/my_home
cd ~/Code/my_home
git init
mkdir ~/Code/my_worktrees
```

---

## Clone Repos as Children

```bash
cd ~/Code/my_home
git clone https://github.com/you/repo-a.git
git clone https://github.com/you/repo-b.git
git clone https://github.com/you/repo-c.git
```

Verify each is on `main`:

```bash
for repo in repo-a repo-b repo-c; do
  echo "$repo: $(git -C $repo branch --show-current)"
done
```

---

## Write the Root CLAUDE.md

Generate and write a `CLAUDE.md` at `~/Code/my_home/CLAUDE.md` with the following sections populated for the user's specific project:

- **What This Workspace Is** — one paragraph describing the project and the canonical-repo rule
- **Repository Registry** — table of directory, GitHub repo, and purpose for each repo
- **Shared Development Standards** — language versions, package managers, linter, test framework, and any non-negotiable rules (e.g. never `--no-verify`)
- **Worktree-Based Development** — exact commands for creating and cleaning up worktrees
- **Key Commands** — reference to `pull-all.sh` and any other workspace-level scripts
- **Infrastructure** — shared service endpoints (database, message bus, etc.)

Keep the root CLAUDE.md focused on cross-repo concerns. Anything relevant to only one repo belongs in that repo's CLAUDE.md.

---

## Write Per-Repo CLAUDE.md Files

For each child repo, write a `CLAUDE.md` that includes:

- A one-line reference to the root CLAUDE.md for shared standards
- Internal architecture and directory structure
- Key files table
- How to run tests
- Patterns and idioms specific to this repo

Do not repeat shared standards — Claude loads both the root and the repo-specific file.

---

## Create pull-all.sh

Write the following to `~/Code/my_home/docs/tools/pull-all.sh` and make it executable:

```bash
#!/usr/bin/env bash
# pull-all.sh — Sync all canonical repos to latest main
#
# Usage:
#   ./pull-all.sh              # sync all repos
#   ./pull-all.sh repo-a       # sync specific repos

set -euo pipefail

MY_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

REPOS=(
  repo-a
  repo-b
  repo-c
)

if [[ $# -gt 0 ]]; then
  REPOS=("$@")
fi

OK=0
FAILED=()

for repo in "${REPOS[@]}"; do
  dir="$MY_HOME/$repo"
  if [[ ! -d "$dir" ]]; then
    echo "  MISSING  $repo"
    FAILED+=("$repo (missing)")
    continue
  fi
  if git -C "$dir" pull --ff-only 2>&1 | grep -q "Already up to date"; then
    echo "  OK       $repo (already current)"
  else
    echo "  UPDATED  $repo"
  fi
  (( OK++ )) || true
done

echo ""
echo "Synced $OK repos"
if [[ ${#FAILED[@]} -gt 0 ]]; then
  echo "Failed: ${FAILED[*]}"
  exit 1
fi
```

```bash
chmod +x ~/Code/my_home/docs/tools/pull-all.sh
```

Replace `repo-a`, `repo-b`, `repo-c` with the actual repo names.

---

## Commit the Workspace Root

```bash
cd ~/Code/my_home
git add CLAUDE.md docs/tools/pull-all.sh
git commit -m "chore: initialize workspace root with CLAUDE.md and pull-all.sh"
```

---

## Working on a Ticket

When a user asks you to work on a ticket in this workspace:

```bash
# 1. Sync to latest main
~/Code/my_home/docs/tools/pull-all.sh

# 2. Create a worktree
git -C ~/Code/my_home/repo-a worktree add \
  ~/Code/my_worktrees/PROJ-123/repo-a \
  -b yourname/proj-123-description

# 3. Install pre-commit hooks in the worktree
cd ~/Code/my_worktrees/PROJ-123/repo-a
pre-commit install

# 4. Work happens here — my_home/repo-a stays clean
```

If the OmniClaude plugin is active, run `/ticket-pipeline PROJ-123` instead of steps 2–4.

---

## Multi-Repo Tickets

When a ticket touches multiple repos:

```bash
TICKET="PROJ-456"

git -C ~/Code/my_home/repo-a worktree add \
  ~/Code/my_worktrees/$TICKET/repo-a \
  -b yourname/proj-456-description

git -C ~/Code/my_home/repo-c worktree add \
  ~/Code/my_worktrees/$TICKET/repo-c \
  -b yourname/proj-456-description-types
```

Open Claude Code from `my_worktrees/PROJ-456/` to see both repos simultaneously.

---

## Cleanup After Merge

```bash
TICKET="PROJ-123"
REPO="repo-a"
BRANCH="yourname/proj-123-description"

git worktree remove ~/Code/my_worktrees/$TICKET/$REPO
git -C ~/Code/my_home/$REPO branch -d $BRANCH
rmdir ~/Code/my_worktrees/$TICKET 2>/dev/null || true
```

For batch cleanup, query merged PRs with `gh pr list --state merged` and prune their worktrees.

---

## CLAUDE.md Content Guidelines

### Root CLAUDE.md — include

- The "never commit to canonical repos" rule, stated prominently
- Repo registry table
- Shared tooling standards
- Worktree workflow with exact commands
- Infrastructure endpoints
- Cross-repo conventions

### Per-repo CLAUDE.md — include

- What this repo does
- Internal directory structure and key files
- Repo-specific patterns
- How to run tests
- Common pitfalls

### Both — exclude

- Credentials (use `.env` files, reference by name)
- Implementation details Claude can read from code
- Anything that changes frequently
