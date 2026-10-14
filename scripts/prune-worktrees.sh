#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# prune-worktrees.sh — Detect and remove stale git worktrees
#
# A worktree is considered stale when its branch's PR has been merged or its
# remote branch no longer exists. "Merged" is decided from
# `onex scm pr-heads OWNER/REPO --source local` output (OMN-20977): a worktree
# is merged when its branch name matches a MERGED PR's head branch, or its
# HEAD oid matches a MERGED PR's head oid. Lanes are no longer allowed to make
# the GitHub merged-PR listing read this script used to make — and which the
# guards had reduced to finding nothing.
#
# Usage:
#   ./scripts/prune-worktrees.sh                   # dry-run (default): report stale worktrees
#   ./scripts/prune-worktrees.sh --execute         # actually remove stale worktrees
#   ./scripts/prune-worktrees.sh --worktrees-root /path/to/worktrees
#   ./scripts/prune-worktrees.sh --execute --worktrees-root /path/to/worktrees
#
# Requirements:
#   - the onex CLI (scm pr-heads): $ONEX_SCM_CLI wins, else the canonical
#     omnibase_internal clone's venv entry point
#     ($OMNI_HOME/../omnibase_internal/.venv/bin/onex), else `onex` on PATH
#   - git
#   - python3 (parses the pr-heads JSON; also the pre-removal snapshot)
#
# The script scans for git worktrees (files/dirs named .git that are worktree
# pointers) under WORKTREES_ROOT, extracts branch + remote info, then reads the
# merged-PR table to classify each as stale or active.
#
# pr-heads lookups are batched: ONE `onex scm pr-heads <slug> --source local`
# call per unique repo slug (not per worktree), answered from the PR watcher
# state and the canonical clone with no GitHub API request at all — one
# `git ls-remote` over the git transport, the same read the canonical-clone
# refresh makes.

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
SNAPSHOT_HELPER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/worktree_removal_snapshot.py"

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
# The onex CLI that answers `scm pr-heads` (OMN-20977). $ONEX_SCM_CLI holds a
# full command line (e.g. "uv run --project /path onex"); otherwise prefer the
# canonical omnibase_internal clone's own venv entry point, which carries the
# omnimarket that serves the verb; otherwise a bare `onex` from PATH.
# ---------------------------------------------------------------------------
resolve_onex_command() {
  if [[ -n "${ONEX_SCM_CLI:-}" ]]; then
    printf '%s' "$ONEX_SCM_CLI"
    return
  fi
  if [[ -n "${OMNI_HOME:-}" ]]; then
    local candidate="${OMNI_HOME%/}/../omnibase_internal/.venv/bin/onex"
    if [[ -x "$candidate" ]]; then
      printf '%s' "$candidate"
      return
    fi
  fi
  printf '%s' "onex"
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

if ! command -v git &>/dev/null; then
  echo "ERROR: git not found." >&2
  exit 1
fi

if ! command -v python3 &>/dev/null; then
  echo "ERROR: python3 not found (the pr-heads JSON parser needs it)." >&2
  exit 1
fi

ONEX_COMMAND="$(resolve_onex_command)"
# Word-split the resolved command line into an argv array.
read -r -a ONEX_CMD <<< "$ONEX_COMMAND"
if [[ "${ONEX_CMD[0]}" == "onex" ]] && ! command -v onex &>/dev/null; then
  echo "ERROR: the onex CLI was not found. Set ONEX_SCM_CLI, or point OMNI_HOME at the" >&2
  echo "registry root holding omnibase_internal, or install onex on PATH." >&2
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
# Pass 1: extract (branch, head oid, repo_slug, canonical clone) for every
# worktree exactly once. Worktrees that cannot be resolved (detached HEAD, no
# remote, unparseable remote) are skipped here with the same reasons as before.
# ---------------------------------------------------------------------------
WT_DIRS=()
declare -A WT_BRANCH=()
declare -A WT_SLUG=()
declare -A WT_OID=()
declare -A WT_CLONE=()
declare -A REPO_SLUGS=()

# The canonical clone backing a linked worktree, read from its .git pointer
# file (`gitdir: <canonical>/.git/worktrees/<name>`). Empty when the pointer
# names no canonical root; pr-heads then resolves its own default clone.
canonical_root_of_git_file() {
  local gitdir line
  line="$(head -n1 "$1" 2>/dev/null || true)"
  gitdir="${line#gitdir: }"
  gitdir="${gitdir%/}"
  [[ -z "$gitdir" ]] && { echo ""; return; }
  case "$gitdir" in
    */worktrees/*) gitdir="${gitdir%/worktrees/*}" ;;
  esac
  case "$gitdir" in
    */.git) echo "${gitdir%/.git}" ;;
    *) echo "" ;;
  esac
}

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

  # HEAD oid: the second half of the merged decision (OMN-20977). A squash
  # merge deletes the head branch, so most MERGED rows carry no head_ref —
  # the oid is then the only thing that names the merged PR.
  head_oid="$(git -C "$worktree_dir" rev-parse HEAD 2>/dev/null || true)"

  WT_DIRS+=("$worktree_dir")
  WT_BRANCH["$worktree_dir"]="$branch"
  WT_SLUG["$worktree_dir"]="$repo_slug"
  WT_OID["$worktree_dir"]="$head_oid"
  REPO_SLUGS["$repo_slug"]=1
  if [[ -z "${WT_CLONE[$repo_slug]:-}" ]]; then
    WT_CLONE["$repo_slug"]="$(canonical_root_of_git_file "$git_file")"
  fi
done

# ---------------------------------------------------------------------------
# Pass 2: batch the merged-PR lookup — ONE `onex scm pr-heads <slug> --source
# local` call per unique repo slug (OMN-20977), answered from the PR watcher
# state and the canonical clone with no GitHub API request. The answer's MERGED
# rows feed two maps: "<slug>::<head branch>" -> PR number and
# "<slug>::<head oid>" -> PR number. A call that cannot answer leaves both maps
# empty for that slug (nothing is deleted through the merged path; the
# remote-branch-gone check is unaffected), exactly as a failed gh call did.
# ---------------------------------------------------------------------------
declare -A MERGED_PR_BY_KEY=()
declare -A MERGED_PR_BY_OID=()

# Reads one pr-heads JSON answer on stdin, writes one "number<TAB>head_oid<TAB>
# head_ref" line per MERGED row (head_ref empty when the source cannot name it).
_PR_HEADS_PARSER='
import json
import sys

try:
    answer = json.load(sys.stdin)
except Exception:
    sys.exit(0)
if not isinstance(answer, dict) or answer.get("outcome") != "completed":
    sys.exit(0)
for row in (answer.get("result") or {}).get("prs") or []:
    if isinstance(row, dict) and row.get("state") == "MERGED":
        oid = row.get("head_oid") or ""
        if oid:
            number = row.get("number")
            ref = row.get("head_ref") or ""
            print(f"{number}\t{oid}\t{ref}")
'

if [[ ${#REPO_SLUGS[@]} -gt 0 ]]; then
  for slug in "${!REPO_SLUGS[@]}"; do
    verbose "Reading merged PR heads for $slug"
    clone="${WT_CLONE[$slug]:-}"
    pr_heads_argv=("${ONEX_CMD[@]}" scm pr-heads "$slug" --source local)
    if [[ -n "$clone" ]]; then
      pr_heads_argv+=(--clone "$clone")
    fi
    if ! pr_heads_json="$("${pr_heads_argv[@]}" 2>/dev/null)"; then
      verbose "  pr-heads could not answer for $slug; no merged-PR decisions for it"
      continue
    fi
    while IFS=$'\t' read -r pr_number pr_oid pr_head_ref; do
      [[ -n "$pr_oid" ]] || continue
      if [[ -n "$pr_head_ref" ]]; then
        MERGED_PR_BY_KEY["${slug}::${pr_head_ref}"]="$pr_number"
      fi
      MERGED_PR_BY_OID["${slug}::${pr_oid}"]="$pr_number"
    done < <(printf '%s' "$pr_heads_json" | python3 -c "$_PR_HEADS_PARSER" || true)
  done
fi

# ---------------------------------------------------------------------------
# Pass 3: classify each worktree using local map lookups (no live calls).
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
  # Staleness check 2: is there a MERGED PR for this worktree? (local map
  # lookups; OMN-20977). Merged means: a MERGED row's head branch is this
  # worktree's branch, OR a MERGED row's head oid is its HEAD — the oid half
  # is what covers the squash-merge shape, where the head branch is gone and
  # only the commit names the merged PR.
  # ---------------------------------------------------------------------------
  pr_number="${MERGED_PR_BY_KEY[${repo_slug}::${branch}]:-}"
  matched_by="branch"
  if [[ -z "$pr_number" ]]; then
    head_oid="${WT_OID[$worktree_dir]:-}"
    if [[ -n "$head_oid" ]]; then
      pr_number="${MERGED_PR_BY_OID[${repo_slug}::${head_oid}]:-}"
      matched_by="head oid"
    fi
  fi
  if [[ -n "$pr_number" ]]; then
    log "  STALE (PR merged): $worktree_dir"
    log "         branch: $branch"
    log "         repo:   $repo_slug  PR #${pr_number} (matched by ${matched_by})"
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

  # ---------------------------------------------------------------------------
  # Save before removing (OMN-19539, operator ruling 2026-09-25). The removal
  # below is --force with an rm -rf fallback, and the dirty check above lets
  # untracked .onex_state output and every IGNORED file (.env, local settings)
  # through. Nothing is removed unless worktree_removal_snapshot.py first saved
  # the diff plus the untracked and ignored-but-not-regenerable files under
  # $OMNI_HOME/.onex_state/worktree-removal-snapshots/. A failed save keeps the
  # worktree. --allow-non-git covers the no-canonical-root fallback below.
  # ---------------------------------------------------------------------------
  if [[ ! -f "$SNAPSHOT_HELPER" ]]; then
    log "  SKIP: $wt — snapshot helper missing ($SNAPSHOT_HELPER), nothing is removed unsaved"
    SKIPPED+=("$wt (snapshot helper missing)")
    continue
  fi
  if ! snapshot_out=$(python3 "$SNAPSHOT_HELPER" "$wt" --reason prune-worktrees.sh --allow-non-git); then
    log "  SKIP: $wt — pre-removal snapshot failed, worktree kept: $snapshot_out"
    SKIPPED+=("$wt (snapshot failed)")
    continue
  fi
  log "  SAVED: $wt -> $snapshot_out"

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
