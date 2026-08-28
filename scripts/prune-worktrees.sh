#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# prune-worktrees.sh — Detect and remove stale git worktrees
#
# A worktree is considered stale when its branch's PR has been merged
# (state=MERGED via gh pr list) or its remote branch no longer exists.
#
# Usage:
#   ./scripts/prune-worktrees.sh                   # dry-run (default): report stale worktrees
#   ./scripts/prune-worktrees.sh --execute         # actually remove stale worktrees
#   ./scripts/prune-worktrees.sh --worktrees-root /path/to/worktrees
#   ./scripts/prune-worktrees.sh --execute --worktrees-root /path/to/worktrees
#
# Requirements:
#   - gh (GitHub CLI) authenticated
#   - git
#
# The script scans for git worktrees (files/dirs named .git that are worktree
# pointers) under WORKTREES_ROOT, extracts branch + remote info, then queries
# GitHub PR state to classify each as stale or active.
#
# Merged-PR lookups are batched: ONE `gh pr list --state merged` call per unique
# repo slug (not two calls per worktree), so a 50+ worktree run stays well under
# the GitHub API rate/timeout budget that previously killed overnight sweeps.

set -euo pipefail

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
# WORKTREES_ROOT defaults to "$OMNI_HOME/omni_worktrees" when OMNI_HOME is set;
# override explicitly with --worktrees-root. No machine-specific path is baked in.
DEFAULT_WORKTREES_ROOT="${OMNI_HOME:+${OMNI_HOME%/}/omni_worktrees}"
WORKTREES_ROOT="$DEFAULT_WORKTREES_ROOT"
EXECUTE=false
VERBOSE=false

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --execute)
      EXECUTE=true
      shift
      ;;
    --worktrees-root)
      WORKTREES_ROOT="$2"
      shift 2
      ;;
    --verbose|-v)
      VERBOSE=true
      shift
      ;;
    --help|-h)
      grep '^#' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log() { echo "$*"; }
verbose() { [[ "$VERBOSE" == true ]] && echo "  [debug] $*" || true; }

# Extract GitHub org/repo slug from a remote URL.
# Handles: git@github.com:OmniNode-ai/foo.git and https://github.com/OmniNode-ai/foo.git
remote_to_slug() {
  local url="$1"
  # Strip trailing .git
  url="${url%.git}"
  case "$url" in
    # SSH: git@github.com:OmniNode-ai/foo  →  OmniNode-ai/foo
    git@github.com:*) echo "${url#git@github.com:}" ;;
    # HTTPS: https://github.com/OmniNode-ai/foo  →  OmniNode-ai/foo
    https://github.com/*) echo "${url#https://github.com/}" ;;
    *) echo "" ;;
  esac
}

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
if [[ -z "$WORKTREES_ROOT" ]]; then
  echo "ERROR: WORKTREES_ROOT is empty. Set OMNI_HOME or pass --worktrees-root <path>." >&2
  exit 1
fi

if [[ ! -d "$WORKTREES_ROOT" ]]; then
  echo "ERROR: WORKTREES_ROOT does not exist: $WORKTREES_ROOT" >&2
  exit 1
fi

if ! command -v gh &>/dev/null; then
  echo "ERROR: gh (GitHub CLI) not found. Install it and authenticate first." >&2
  exit 1
fi

if ! command -v git &>/dev/null; then
  echo "ERROR: git not found." >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Discovery: find all worktree .git pointer files (depth <= 4 to catch
# nested structures like OMN-XXXX/repo/.git and OMN-XXXX/OMN-YYYY/repo/.git)
# ---------------------------------------------------------------------------
log ""
log "Scanning worktrees under: $WORKTREES_ROOT"
log "Mode: $( [[ "$EXECUTE" == true ]] && echo "EXECUTE (will remove stale)" || echo "DRY RUN (report only)" )"
log ""

STALE=()
ACTIVE=()
SKIPPED=()
ERRORS=()

# We look for .git files (not directories) — git worktrees use a .git file
# that points back to the parent repo's worktrees dir.
GIT_FILES=()
while IFS= read -r line; do
  GIT_FILES+=("$line")
done < <(find "$WORKTREES_ROOT" -maxdepth 4 -name ".git" -type f 2>/dev/null | sort)

if [[ ${#GIT_FILES[@]} -eq 0 ]]; then
  log "No worktrees found under $WORKTREES_ROOT"
  exit 0
fi

log "Found ${#GIT_FILES[@]} worktree(s) to check."
log ""

# ---------------------------------------------------------------------------
# Pass 1: extract (branch, repo_slug) for every worktree exactly once.
# Worktrees that cannot be resolved (detached HEAD, no remote, unparseable
# remote) are skipped here with the same reasons as before.
# ---------------------------------------------------------------------------
WT_DIRS=()
declare -A WT_BRANCH=()
declare -A WT_SLUG=()
declare -A REPO_SLUGS=()

for git_file in "${GIT_FILES[@]}"; do
  worktree_dir="$(dirname "$git_file")"

  verbose "Discovering: $worktree_dir"

  # Get branch name
  branch="$(git -C "$worktree_dir" branch --show-current 2>/dev/null || true)"
  if [[ -z "$branch" ]]; then
    verbose "  Skipping (detached HEAD or no branch)"
    SKIPPED+=("$worktree_dir (detached HEAD)")
    continue
  fi

  # Get remote URL
  remote_url="$(git -C "$worktree_dir" remote get-url origin 2>/dev/null || true)"
  if [[ -z "$remote_url" ]]; then
    verbose "  Skipping (no remote 'origin')"
    SKIPPED+=("$worktree_dir (no remote)")
    continue
  fi

  repo_slug="$(remote_to_slug "$remote_url")"
  if [[ -z "$repo_slug" ]]; then
    verbose "  Skipping (cannot parse repo slug from: $remote_url)"
    SKIPPED+=("$worktree_dir (unparseable remote: $remote_url)")
    continue
  fi

  WT_DIRS+=("$worktree_dir")
  WT_BRANCH["$worktree_dir"]="$branch"
  WT_SLUG["$worktree_dir"]="$repo_slug"
  REPO_SLUGS["$repo_slug"]=1
done

# ---------------------------------------------------------------------------
# Pass 2: batch the merged-PR lookup — ONE `gh pr list` per unique repo slug.
# Previously this was two `gh pr list` calls per worktree; at 50+ worktrees that
# meant 100+ sequential gh API calls and frequent overnight timeouts. The batch
# collapses that to one-call-per-repo. Map key: "<slug>::<branch>" -> PR number.
# ---------------------------------------------------------------------------
declare -A MERGED_PR_BY_KEY=()

if [[ ${#REPO_SLUGS[@]} -gt 0 ]]; then
  for slug in "${!REPO_SLUGS[@]}"; do
    verbose "Fetching merged PRs for $slug"
    while IFS=$'\t' read -r pr_number head_ref; do
      [[ -z "$head_ref" ]] && continue
      key="${slug}::${head_ref}"
      # gh returns most-recent-first; keep the first (newest) merged PR seen for
      # a branch to match the previous `.[0]` selection.
      [[ -n "${MERGED_PR_BY_KEY[$key]:-}" ]] || MERGED_PR_BY_KEY["$key"]="$pr_number"
    done < <(gh pr list \
      --repo "$slug" \
      --state merged \
      --json number,headRefName \
      --limit 200 \
      --jq '.[] | "\(.number)\t\(.headRefName)"' \
      2>/dev/null || true)
  done
fi

# ---------------------------------------------------------------------------
# Pass 3: classify each worktree using local map lookups (no live gh calls).
# Classification order is unchanged from prior behaviour: the remote-branch-gone
# check runs before the merged-PR check.
# ---------------------------------------------------------------------------
for worktree_dir in "${WT_DIRS[@]}"; do
  branch="${WT_BRANCH[$worktree_dir]}"
  repo_slug="${WT_SLUG[$worktree_dir]}"

  verbose "Checking: $worktree_dir"

  # ---------------------------------------------------------------------------
  # Staleness check 1: Is the remote branch gone?
  # ---------------------------------------------------------------------------
  remote_exists="$(git ls-remote --heads origin "$branch" 2>/dev/null || true)"
  if [[ -z "$remote_exists" ]]; then
    # Fetch to ensure we have latest remote refs from the canonical clone
    # Try to find canonical clone for this repo
    canonical="$(git -C "$worktree_dir" rev-parse --git-common-dir 2>/dev/null | xargs dirname 2>/dev/null || true)"
    if [[ -n "$canonical" ]] && [[ -d "$canonical" ]]; then
      git -C "$canonical" fetch origin --prune --quiet 2>/dev/null || true
      remote_exists="$(git ls-remote --heads "$canonical" "refs/heads/$branch" 2>/dev/null || true)"
    fi
  fi

  if [[ -z "$remote_exists" ]]; then
    log "  STALE (remote branch gone): $worktree_dir"
    log "         branch: $branch"
    log "         repo:   $repo_slug"
    STALE+=("$worktree_dir")
    continue
  fi

  # ---------------------------------------------------------------------------
  # Staleness check 2: Is there a merged PR for this branch? (local map lookup)
  # ---------------------------------------------------------------------------
  pr_number="${MERGED_PR_BY_KEY[${repo_slug}::${branch}]:-}"
  if [[ -n "$pr_number" ]]; then
    log "  STALE (PR merged): $worktree_dir"
    log "         branch: $branch"
    log "         repo:   $repo_slug  PR #${pr_number}"
    STALE+=("$worktree_dir")
    continue
  fi

  # ---------------------------------------------------------------------------
  # Active worktree
  # ---------------------------------------------------------------------------
  verbose "  Active: $worktree_dir (branch: $branch)"
  ACTIVE+=("$worktree_dir")
done

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
log ""
log "============================================================"
log "  Summary"
log "============================================================"
log "  Active:  ${#ACTIVE[@]}"
log "  Stale:   ${#STALE[@]}"
log "  Skipped: ${#SKIPPED[@]}"
log "  Errors:  ${#ERRORS[@]}"
log ""

if [[ ${#STALE[@]} -eq 0 ]]; then
  log "No stale worktrees found. Nothing to do."
  exit 0
fi

if [[ "$EXECUTE" == false ]]; then
  log "Dry-run mode — run with --execute to remove the following:"
  for wt in "${STALE[@]}"; do
    log "  $wt"
  done
  log ""
  log "Command to prune all stale worktrees:"
  log "  $0 --execute $( [[ "$WORKTREES_ROOT" != "$DEFAULT_WORKTREES_ROOT" ]] && echo "--worktrees-root $WORKTREES_ROOT" || true )"
  exit 0
fi

# ---------------------------------------------------------------------------
# Execute: remove stale worktrees
# ---------------------------------------------------------------------------
log "Removing ${#STALE[@]} stale worktree(s)..."
log ""

REMOVED=0
FAILED_REMOVE=()

for wt in "${STALE[@]}"; do
  # ---------------------------------------------------------------------------
  # Safety check: unpushed commits (OMN-7021)
  # Before removing, verify no unique local commits exist that would be lost.
  # Missing upstream defaults to SKIP (not DELETE). Detached HEAD already
  # skipped earlier in the discovery loop.
  # ---------------------------------------------------------------------------
  UNPUSHED=$(git -C "$wt" log "@{u}..HEAD" --oneline 2>/dev/null || echo "NO_UPSTREAM")
  if [[ "$UNPUSHED" == "NO_UPSTREAM" ]]; then
    log "  SKIP: $wt has no upstream configured — cannot verify push state"
    SKIPPED+=("$wt (no upstream)")
    continue
  elif [[ -n "$UNPUSHED" ]]; then
    log "  SKIP: $wt has unpushed commits:"
    echo "$UNPUSHED" | while IFS= read -r line; do log "    $line"; done
    SKIPPED+=("$wt (unpushed commits)")
    continue
  fi

  # ---------------------------------------------------------------------------
  # Safety check: uncommitted changes (dirty working tree), with the
  # disposable-.onex_state carve-out (OMN-15989)
  #
  # THE RULE (identical to the one in each repo's .gitignore):
  #   An UNTRACKED path under the worktree's own .onex_state/ is regenerable
  #   output and does NOT block teardown -- except under the two named durable
  #   subtrees .onex_state/evidence/ and .onex_state/friction/, which hold
  #   committed content and DO block.
  #
  # Why the tool needs its own copy of the rule rather than deferring to
  # .gitignore: a worktree checks out its own branch's .gitignore, so an ignore
  # rule merged to dev today does not exist in the tree of a worktree branched
  # before it. Six omnibase_core worktrees were blocked from teardown this way
  # at the time of writing and no .gitignore change can reach them.
  #
  # Two details that are load-bearing:
  #   * --untracked-files=all: with git's default `normal`, a wholly-untracked
  #     directory collapses to a single `?? .onex_state/` line and a prefix
  #     filter could not tell whether durable evidence was inside it.
  #   * only `??` lines qualify. A tracked .onex_state file that is modified or
  #     deleted (` M` / ` D` / `A `) is real work and still blocks -- which is
  #     exactly what a naive `grep -v .onex_state` would get wrong.
  # ---------------------------------------------------------------------------
  DIRTY=$(git -C "$wt" status --porcelain --untracked-files=all 2>/dev/null || true)
  BLOCKING_DIRTY=$(printf '%s' "$DIRTY" | awk '
    # git quotes paths containing special characters, hence the optional ".
    /^\?\? "?\.onex_state\// && !/^\?\? "?\.onex_state\/(evidence|friction)\// { next }
    { print }
  ')
  if [[ -n "$BLOCKING_DIRTY" ]]; then
    log "  SKIP: $wt has uncommitted changes"
    SKIPPED+=("$wt (dirty working tree)")
    continue
  fi
  if [[ -n "$DIRTY" ]]; then
    log "  NOTE: $wt carries only disposable .onex_state output — not a block (OMN-15989)"
  fi

  # Find the canonical clone to run git worktree remove from
  canonical_gitdir="$(git -C "$wt" rev-parse --git-common-dir 2>/dev/null || true)"
  # git-common-dir for a worktree is e.g.:
  #   /path/to/canonical_repo/.git/worktrees/foo
  # We need the canonical repo root = two levels up from that
  canonical_root="$(dirname "$(dirname "$canonical_gitdir")" 2>/dev/null || true)"

  if [[ -d "$canonical_root/.git" ]] || [[ -f "$canonical_root/.git" ]]; then
    # Run git worktree remove from the canonical repo
    if git -C "$canonical_root" worktree remove --force "$wt" 2>/dev/null; then
      log "  REMOVED: $wt"
      (( REMOVED++ )) || true
    else
      log "  FAILED to remove via git worktree: $wt — trying rm -rf"
      if rm -rf "$wt"; then
        # Also prune the dangling worktree reference
        git -C "$canonical_root" worktree prune 2>/dev/null || true
        log "  REMOVED (rm -rf): $wt"
        (( REMOVED++ )) || true
      else
        log "  ERROR: could not remove $wt" >&2
        FAILED_REMOVE+=("$wt")
      fi
    fi
  else
    # No canonical root found — fall back to rm -rf
    log "  REMOVED (rm -rf, no canonical): $wt"
    rm -rf "$wt"
    (( REMOVED++ )) || true
  fi
done

log ""
log "Removed: $REMOVED / ${#STALE[@]} stale worktrees."
if [[ ${#FAILED_REMOVE[@]} -gt 0 ]]; then
  log "Failed to remove ${#FAILED_REMOVE[@]} worktree(s):"
  for f in "${FAILED_REMOVE[@]}"; do
    log "  $f"
  done
  exit 1
fi

# Run git worktree prune on all canonical repos to clean up dangling refs.
# The canonical registry root is OMNI_HOME; skip cleanly when it is unset or
# missing so no machine-specific path is baked in.
log ""
log "Pruning dangling worktree references from canonical clones..."
ONEX_REGISTRY_ROOT="${OMNI_HOME:-}"
if [[ -z "$ONEX_REGISTRY_ROOT" ]] || [[ ! -d "$ONEX_REGISTRY_ROOT" ]]; then
  verbose "Skipping canonical-clone prune (OMNI_HOME unset or not a directory: '${ONEX_REGISTRY_ROOT}')"
else
  for repo_dir in "$ONEX_REGISTRY_ROOT"/*/; do
    [[ -d "$repo_dir/.git" ]] || continue
    if git -C "$repo_dir" worktree prune 2>/dev/null; then
      verbose "Pruned: $repo_dir"
    fi
  done
fi

log "Done."
