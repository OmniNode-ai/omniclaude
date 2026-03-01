#!/usr/bin/env bash
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

set -euo pipefail

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
WORKTREES_ROOT="/Volumes/PRO-G40/Code/omni_worktrees"
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
  # Handle SSH: git@github.com:OmniNode-ai/foo  →  OmniNode-ai/foo
  if [[ "$url" =~ ^git@github\.com:(.+)$ ]]; then
    echo "${BASH_REMATCH[1]}"
    return
  fi
  # Handle HTTPS: https://github.com/OmniNode-ai/foo  →  OmniNode-ai/foo
  if [[ "$url" =~ ^https://github\.com/(.+)$ ]]; then
    echo "${BASH_REMATCH[1]}"
    return
  fi
  echo ""
}

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
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
mapfile -t GIT_FILES < <(
  find "$WORKTREES_ROOT" -maxdepth 4 -name ".git" -type f 2>/dev/null | sort
)

if [[ ${#GIT_FILES[@]} -eq 0 ]]; then
  log "No worktrees found under $WORKTREES_ROOT"
  exit 0
fi

log "Found ${#GIT_FILES[@]} worktree(s) to check."
log ""

for git_file in "${GIT_FILES[@]}"; do
  worktree_dir="$(dirname "$git_file")"
  repo_name="$(basename "$worktree_dir")"

  verbose "Checking: $worktree_dir"

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
  # Staleness check 2: Is there a merged PR for this branch?
  # ---------------------------------------------------------------------------
  pr_state="$(gh pr list \
    --repo "$repo_slug" \
    --head "$branch" \
    --state merged \
    --json number,state \
    --jq '.[0].state' \
    2>/dev/null || echo "")"

  if [[ "$pr_state" == "MERGED" ]]; then
    pr_number="$(gh pr list \
      --repo "$repo_slug" \
      --head "$branch" \
      --state merged \
      --json number \
      --jq '.[0].number' \
      2>/dev/null || echo "?")"
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
  log "  $0 --execute $( [[ "$WORKTREES_ROOT" != "/Volumes/PRO-G40/Code/omni_worktrees" ]] && echo "--worktrees-root $WORKTREES_ROOT" || true )"
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

# Run git worktree prune on all canonical repos to clean up dangling refs
log ""
log "Pruning dangling worktree references from canonical clones..."
OMNI_HOME="/Volumes/PRO-G40/Code/omni_home"
for repo_dir in "$OMNI_HOME"/*/; do
  [[ -d "$repo_dir/.git" ]] || continue
  if git -C "$repo_dir" worktree prune 2>/dev/null; then
    verbose "Pruned: $repo_dir"
  fi
done

log "Done."
