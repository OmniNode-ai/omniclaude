#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# converge-canonical-clone.sh — the ONE sanctioned way to bring a dirty canonical
# clone under $OMNI_HOME back to its upstream (OMN-16496, guard gap G4).
#
# Why this exists: the canonical-clone guard (scripts/user-hooks/
# canonical-clone-guard.py) blanket-denies checkout/restore/reset/stash inside
# $OMNI_HOME/<repo>, so once a canonical clone is dirty no agent can converge it.
# The 2026-08-24 omnimarket forensics counted 13 denied attempts on one clone and
# one plumbing bypass (`git update-ref`, 2026-08-23T21:06:54Z) that made things
# worse. This script is what the guard's deny message points at. It PRESERVES
# first (per-area patches, the full diff vs HEAD, copies of untracked files,
# reflog, sha256 manifest), then performs exactly `git reset --hard <upstream
# sha>`, verifies the result, and appends a ledger row.
#
# Usage:
#   converge-canonical-clone.sh <repo-name | clone-path | .>                 # dry-run report
#   converge-canonical-clone.sh <repo> --execute [--clean-untracked]
#                               [--to-branch <name>]
#                               [--ticket OMN-XXXX] [--lane <name>]
#   converge-canonical-clone.sh <repo> --branch <name> [--execute]
#                               [--ticket OMN-XXXX] [--lane <name>]
#
# --branch <name> (OMN-16500) converges a NON-checked-out local branch to its
# configured upstream without touching the working tree or the index: it
# preserves the branch's unique commits first (log + per-commit patches +
# branch reflog + sha256 manifest), then performs exactly
# `git branch -f <name> <upstream sha>`. Built for the release-synced-main
# policy, where origin/main is rewritten to the release tag and a canonical
# clone's local main -- still holding the pre-rewrite promotion commits -- can
# never fast-forward again.
#
# DETACHED HEAD (OMN-17313) is converged, not refused. Before this ticket the
# default mode refused it outright -- and that refusal was a dead end, because
# the canonical-clone guard (scripts/user-hooks/canonical-clone-guard.py) also
# blanket-denies `checkout`/`switch` inside a canonical clone and points the
# operator AT THIS SCRIPT. A clone left detached by a stray `git checkout
# FETCH_HEAD` therefore had no sanctioned repair path at all, and pull-all.sh
# inherited the same dead end because its drift-repair stage delegates here.
# Live case: $OMNI_HOME/omnimarket sat detached at an unmerged PR-branch commit
# for two days, which is what re-broke the OMN-6790 GLM endpoint on the client
# path -- both BIFROST_CONTRACT_PATH and the reconciled venv (pinned to the
# clone HEAD by OMN-16366) faithfully served that frozen tree.
#
# The re-attachment target is DERIVED, never guessed: the most recent
# `checkout: moving from <branch> to ...` entry in the clone's HEAD reflog,
# accepted only when that local branch still exists AND has an upstream.
# --to-branch <name> overrides the derivation. When neither resolves the script
# refuses rather than picking a default. Commits reachable only from the
# detached HEAD are preserved as patches first, exactly like branch mode's
# ahead-commits.
#
# Refuses (exit 2): a target that is not a direct child of $OMNI_HOME with a .git
# DIRECTORY (worktrees carry a .git file and are never converged here), a branch
# without an upstream, a detached HEAD whose re-attachment target cannot be
# derived and was not named, unknown options. With --branch, also
# refuses the currently checked-out branch (use the default mode for that), a
# nonexistent local branch, and the --clean-untracked combination (the working
# tree is out of scope in branch mode). Exit 0 on success or when
# the clone is already converged; exit 1 on a failed git step.
#
# Evidence: $OMNI_HOME/.onex_state/canonical-clone-converge/<repo>-<utc>/
# Ledger:   $OMNI_HOME/docs/tracking/ROLLING_WORK_LEDGER.md, appended through
#           $OMNI_HOME/scripts/ledger_lock.py when present (direct append otherwise).
# Never prints file contents or secrets; only paths, SHAs, counts and hashes.

set -euo pipefail

usage() {
  sed -n '/^# Usage:/,/^# Refuses/p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' | sed '$d'
}

refuse() { echo "REFUSED: $*" >&2; exit 2; }
fail() { echo "ERROR: $*" >&2; exit 1; }

abs_dir() { (cd -P -- "$1" 2>/dev/null && pwd -P); }

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

count_lines() { printf '%s' "$1" | grep -c . || true; }

OMNI_HOME="${OMNI_HOME:?set OMNI_HOME to the omni_home registry path}"

target=""
execute=0
clean_untracked=0
ticket=""
lane="converge-canonical-clone"
branch_opt=""
to_branch_opt=""
branch_source=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --execute) execute=1 ;;
    --clean-untracked) clean_untracked=1 ;;
    --branch) [[ $# -ge 2 ]] || refuse "--branch needs a value"; branch_opt="$2"; shift ;;
    --to-branch) [[ $# -ge 2 ]] || refuse "--to-branch needs a value"; to_branch_opt="$2"; shift ;;
    --ticket) [[ $# -ge 2 ]] || refuse "--ticket needs a value"; ticket="$2"; shift ;;
    --lane) [[ $# -ge 2 ]] || refuse "--lane needs a value"; lane="$2"; shift ;;
    -h|--help) usage; exit 0 ;;
    -*) refuse "unknown option: $1" ;;
    *) [[ -z "$target" ]] || refuse "exactly one target is accepted (got '$target' and '$1')"; target="$1" ;;
  esac
  shift
done
[[ -n "$target" ]] || { usage >&2; exit 2; }
if [[ -n "$branch_opt" && "$clean_untracked" == "1" ]]; then
  refuse "--clean-untracked cannot be combined with --branch: branch mode never touches the working tree"
fi
if [[ -n "$branch_opt" && -n "$to_branch_opt" ]]; then
  refuse "--to-branch cannot be combined with --branch: --branch converges a non-checked-out ref and never moves HEAD, --to-branch names where a DETACHED HEAD re-attaches"
fi

# --- target must be a canonical clone: direct child of $OMNI_HOME with a .git DIRECTORY
omni_home_abs="$(abs_dir "$OMNI_HOME")" || fail "OMNI_HOME does not exist: $OMNI_HOME"
if [[ "$target" == */* || "$target" == "." ]]; then
  clone="$(abs_dir "$target")" || refuse "not a directory: $target"
else
  clone="$(abs_dir "$OMNI_HOME/$target")" || refuse "no such canonical clone: \$OMNI_HOME/$target"
fi
[[ "$(dirname "$clone")" == "$omni_home_abs" ]] \
  || refuse "$clone is not a direct child of \$OMNI_HOME ($omni_home_abs); only canonical clones are converged, never worktrees or nested paths"
repo="$(basename "$clone")"
[[ "$repo" != "omni_worktrees" ]] || refuse "omni_worktrees is the work root, not a clone"
[[ -d "$clone/.git" ]] \
  || refuse "$clone has no .git directory (a worktree has a .git FILE; worktrees are mutable and are not converged by this script)"

g() { git -C "$clone" "$@"; }

append_ledger_row() {
  local row="$1"
  local ledger="$OMNI_HOME/docs/tracking/ROLLING_WORK_LEDGER.md"
  local lock="$OMNI_HOME/scripts/ledger_lock.py"
  if [[ -f "$lock" ]]; then
    python3 "$lock" "$ledger" --append "$row" \
      || fail "ledger append via ledger_lock.py failed (the ref IS converged; evidence at $evidence)"
  elif [[ -f "$ledger" ]]; then
    printf '%s\n' "$row" >> "$ledger"
  else
    echo "WARN: no ledger at $ledger; row not recorded:" >&2
    echo "$row" >&2
  fi
}

# --- branch mode (OMN-16500): converge a NON-checked-out branch ref -----------
if [[ -n "$branch_opt" ]]; then
  checked_out="$(g symbolic-ref -q --short HEAD 2>/dev/null || true)"
  [[ "$branch_opt" != "$checked_out" ]] \
    || refuse "'$branch_opt' is the checked-out branch in $clone; branch mode never moves HEAD -- use the default mode (preserve + reset --hard) for the checked-out branch"
  g show-ref --verify --quiet "refs/heads/$branch_opt" \
    || refuse "no local branch '$branch_opt' in $clone"
  upstream="$(g rev-parse --abbrev-ref --symbolic-full-name "${branch_opt}@{u}" 2>/dev/null)" \
    || refuse "branch '$branch_opt' in $clone has no upstream configured; refusing to guess a convergence target"
  remote="${upstream%%/*}"

  g fetch --quiet "$remote" || fail "git fetch $remote failed in $clone"

  branch_before="$(g rev-parse "refs/heads/$branch_opt")"
  target_sha="$(g rev-parse --verify "${upstream}^{commit}")" || fail "cannot resolve $upstream"
  ahead="$(g rev-list --count "$upstream..refs/heads/$branch_opt")"
  behind="$(g rev-list --count "refs/heads/$branch_opt..$upstream")"

  if [[ "$branch_before" == "$target_sha" ]]; then
    echo "already converged: $repo ($clone) $branch_opt == $upstream ($target_sha)"
    exit 0
  fi

  evidence_root="$OMNI_HOME/.onex_state/canonical-clone-converge"

  if (( ! execute )); then
    cat <<EOF
DRY-RUN: would converge branch '$branch_opt' of canonical clone '$repo' ($clone)
  upstream=$upstream (checked-out branch '$checked_out' and working tree untouched)
  $branch_opt $branch_before -> $target_sha (ahead $ahead, behind $behind)
  would preserve ahead-commit log/patches/branch-reflog/MANIFEST under $evidence_root/$repo-branch-$branch_opt-<utc>/
  then run: git -C $clone branch -f $branch_opt $target_sha
Nothing was changed. Re-run with --execute to perform it.
EOF
    exit 0
  fi

  # --- preserve: the branch's unique commits, as log + per-commit patches ----
  ts="$(date -u +%Y%m%dT%H%M%SZ)"
  evidence="$evidence_root/${repo}-branch-${branch_opt}-${ts}"
  mkdir -p "$evidence/ahead-patches"
  g log --format='%H %ci %s' "$upstream..refs/heads/$branch_opt" \
    > "$evidence/ahead-commits.log"
  if (( ahead > 0 )); then
    g format-patch --quiet -o "$evidence/ahead-patches" \
      "$upstream..refs/heads/$branch_opt" >/dev/null
  fi
  g reflog show "$branch_opt" -n 20 > "$evidence/branch-reflog.txt" 2>/dev/null || true

  {
    echo "mode=branch"
    echo "repo=$repo"
    echo "clone=$clone"
    echo "branch=$branch_opt"
    echo "upstream=$upstream"
    echo "branch_before=$branch_before"
    echo "target=$target_sha"
    echo "utc=$ts"
    echo "ahead=$ahead behind=$behind"
    echo "checked_out=${checked_out:-<detached>}"
    echo "ticket=${ticket:-none}"
    echo "lane=$lane"
    for f in ahead-commits.log branch-reflog.txt; do
      [[ -f "$evidence/$f" ]] && echo "sha256 $(sha256_of "$evidence/$f")  $f"
    done
    find "$evidence/ahead-patches" -type f | sort | while IFS= read -r f; do
      echo "sha256 $(sha256_of "$f")  ahead-patches/${f#"$evidence/ahead-patches/"}"
    done
  } > "$evidence/MANIFEST.txt"

  # --- converge: exactly one ref move, nothing else --------------------------
  g branch -f "$branch_opt" "$target_sha" \
    || fail "git branch -f $branch_opt $target_sha failed (evidence kept at $evidence)"
  branch_after="$(g rev-parse "refs/heads/$branch_opt")"
  [[ "$branch_after" == "$target_sha" ]] \
    || fail "$branch_opt is $branch_after after branch -f, expected $target_sha"

  # --- record -----------------------------------------------------------------
  row="$(date -u +%Y-%m-%dT%H:%M:%SZ) | $lane | ${ticket:-$repo} | BRANCH-CONVERGED | converge-canonical-clone.sh $repo ($clone): branch $branch_opt upstream $upstream; $branch_opt ${branch_before:0:7} -> ${branch_after:0:7} ($ahead ahead / $behind behind); unique commits preserved at $evidence (ahead-commits.log + per-commit patches); git branch -f $branch_opt $target_sha; checked-out branch '${checked_out:-<detached>}' and working tree untouched. No secrets printed."
  append_ledger_row "$row"

  cat <<EOF
BRANCH-CONVERGED: $repo ($clone)
  branch=$branch_opt upstream=$upstream
  $branch_opt $branch_before -> $branch_after (was ahead $ahead, behind $behind)
  preserved: $evidence
  checked-out branch '${checked_out:-<detached>}' and working tree untouched
EOF
  exit 0
fi
# --- end branch mode ----------------------------------------------------------

# --- resolve the branch HEAD is on, or the one a detached HEAD re-attaches to.
#
# OMN-17313: a detached HEAD used to be refused here, which left the clone with
# no sanctioned repair path at all (the guard denies checkout/switch and points
# at this script; pull-all.sh delegates to this script). It is now converged,
# with the re-attachment target DERIVED from the reflog rather than guessed.
detached=0
branch="$(g symbolic-ref -q --short HEAD 2>/dev/null || true)"
if [[ -z "$branch" ]]; then
  detached=1
  if [[ -n "$to_branch_opt" ]]; then
    branch="$to_branch_opt"
    branch_source="--to-branch"
  else
    # The most recent "checkout: moving from <X> to <Y>" in HEAD's reflog names
    # the branch this clone was on before it was detached. Walk newest-first and
    # take the first <X> that is still a local branch WITH an upstream; a name
    # that no longer resolves is skipped rather than accepted, so a stale entry
    # can never select a dead target.
    while IFS= read -r cand; do
      [[ -n "$cand" ]] || continue
      g show-ref --verify --quiet "refs/heads/$cand" || continue
      g rev-parse --abbrev-ref --symbolic-full-name "${cand}@{u}" >/dev/null 2>&1 || continue
      branch="$cand"
      break
    done < <(g reflog show HEAD --format='%gs' 2>/dev/null \
               | sed -n 's/^checkout: moving from \([^ ]*\) to .*$/\1/p')
    branch_source="derived from HEAD reflog"
  fi
  [[ -n "$branch" ]] || refuse "detached HEAD in $clone and no re-attachment target could be derived from the HEAD reflog (no prior 'checkout: moving from <branch>' entry names a local branch that still exists and has an upstream). Name one explicitly: --to-branch <name>"
  g show-ref --verify --quiet "refs/heads/$branch" \
    || refuse "detached HEAD in $clone; re-attachment target '$branch' ($branch_source) is not a local branch"
fi

upstream="$(g rev-parse --abbrev-ref --symbolic-full-name "${branch}@{u}" 2>/dev/null)" \
  || refuse "branch '$branch' in $clone has no upstream configured; refusing to guess a convergence target"
remote="${upstream%%/*}"

g fetch --quiet "$remote" || fail "git fetch $remote failed in $clone"

head_before="$(g rev-parse HEAD)"
target_sha="$(g rev-parse --verify "${upstream}^{commit}")" || fail "cannot resolve $upstream"
status="$(g status --porcelain --untracked-files=all)"
untracked_list="$(g ls-files --others --exclude-standard)"
dirty_total="$(count_lines "$status")"
staged="$(count_lines "$(g diff --cached --name-only)")"
unstaged="$(count_lines "$(g diff --name-only)")"
untracked="$(count_lines "$untracked_list")"

# A DETACHED HEAD is never "already converged", even when its sha happens to
# equal the upstream tip: the clone still has no branch, so the next `git pull`
# has nothing to fast-forward and every downstream consumer stays frozen.
if (( ! detached )) && [[ -z "$status" && "$head_before" == "$target_sha" ]]; then
  echo "already converged: $repo ($clone) HEAD == $upstream ($target_sha), clean tree"
  exit 0
fi

evidence_root="$OMNI_HOME/.onex_state/canonical-clone-converge"

# Commits reachable only from the detached HEAD. These live nowhere else once
# HEAD moves (the reflog expires), so they are preserved as patches before the
# re-attach -- the same guarantee branch mode gives a branch's ahead-commits.
detached_ahead=0
if (( detached )); then
  detached_ahead="$(g rev-list --count "${upstream}..HEAD" 2>/dev/null || echo 0)"
fi

if (( ! execute )); then
  cat <<EOF
DRY-RUN: would converge canonical clone '$repo' ($clone)
  HEAD state: $( (( detached )) && printf 'DETACHED at %s; would re-attach to %s (%s)' "${head_before:0:12}" "$branch" "$branch_source" || printf 'on branch %s' "$branch")
  branch=$branch upstream=$upstream
  HEAD $head_before -> $target_sha
  dirty paths: $dirty_total ($staged staged, $unstaged worktree-modified, $untracked untracked)$( (( detached )) && printf '\n  detached-only commits: %s (preserved as patches)' "$detached_ahead" || true)
  would preserve status/patches/untracked copies/reflog/MANIFEST under $evidence_root/$repo-<utc>/
  then run: $( (( detached )) && printf 'git -C %s checkout --force %s && ' "$clone" "$branch" || true)git -C $clone reset --hard $target_sha$( (( clean_untracked )) && printf ' && git clean -fd' || true )
Nothing was changed. Re-run with --execute to perform it.
EOF
  exit 0
fi

# --- preserve ---------------------------------------------------------------
ts="$(date -u +%Y%m%dT%H%M%SZ)"
evidence="$evidence_root/${repo}-${ts}"
mkdir -p "$evidence/untracked"
printf '%s\n' "$status" > "$evidence/status.txt"
g diff --cached --binary > "$evidence/staged.patch"
g diff --binary > "$evidence/unstaged.patch"
g diff --binary HEAD > "$evidence/full-vs-HEAD.patch"
g reflog -n 20 > "$evidence/reflog.txt" || true
if (( detached )); then
  mkdir -p "$evidence/detached-patches"
  g log --format='%H %ci %s' "${upstream}..HEAD" > "$evidence/detached-commits.log" 2>/dev/null || true
  if (( detached_ahead > 0 )); then
    g format-patch --quiet -o "$evidence/detached-patches" "${upstream}..HEAD" >/dev/null || true
  fi
fi
while IFS= read -r f; do
  [[ -n "$f" ]] || continue
  mkdir -p "$evidence/untracked/$(dirname "$f")"
  cp -p "$clone/$f" "$evidence/untracked/$f"
done <<< "$untracked_list"

{
  echo "repo=$repo"
  echo "clone=$clone"
  echo "branch=$branch"
  echo "detached_before=$detached"
  if (( detached )); then
    echo "reattach_target_source=$branch_source"
    echo "detached_only_commits=$detached_ahead"
  fi
  echo "upstream=$upstream"
  echo "head_before=$head_before"
  echo "target=$target_sha"
  echo "utc=$ts"
  echo "dirty_paths=$dirty_total staged=$staged unstaged=$unstaged untracked=$untracked"
  echo "clean_untracked=$clean_untracked"
  echo "ticket=${ticket:-none}"
  echo "lane=$lane"
  for f in status.txt staged.patch unstaged.patch full-vs-HEAD.patch reflog.txt; do
    echo "sha256 $(sha256_of "$evidence/$f")  $f"
  done
  find "$evidence/untracked" -type f | sort | while IFS= read -r f; do
    echo "sha256 $(sha256_of "$f")  untracked/${f#"$evidence/untracked/"}"
  done
  if [[ -f "$evidence/detached-commits.log" ]]; then
    echo "sha256 $(sha256_of "$evidence/detached-commits.log")  detached-commits.log"
  fi
  if [[ -d "$evidence/detached-patches" ]]; then
    find "$evidence/detached-patches" -type f | sort | while IFS= read -r f; do
      echo "sha256 $(sha256_of "$f")  detached-patches/${f#"$evidence/detached-patches/"}"
    done
  fi
} > "$evidence/MANIFEST.txt"
patch_sha="$(sha256_of "$evidence/full-vs-HEAD.patch")"

# --- converge ----------------------------------------------------------------
# Re-attach BEFORE the reset so the reset moves a real branch ref, not a
# detached HEAD. --force is safe here and only here: every tracked modification
# and every untracked file was copied into $evidence immediately above, and the
# detached-only commits were written out as patches. Without --force the
# checkout aborts on the same dirty tree this script exists to converge.
if (( detached )); then
  g checkout --force --quiet "$branch" \
    || fail "git checkout --force $branch failed while re-attaching detached HEAD (evidence kept at $evidence)"
  [[ "$(g symbolic-ref -q --short HEAD)" == "$branch" ]] \
    || fail "HEAD is still detached after checkout $branch (evidence kept at $evidence)"
fi
g reset --hard --quiet "$target_sha" || fail "git reset --hard $target_sha failed (evidence kept at $evidence)"
clean_note=""
if (( clean_untracked )); then
  g clean -fd --quiet || fail "git clean -fd failed (evidence kept at $evidence)"
  clean_note=" + git clean -fd"
fi

head_after="$(g rev-parse HEAD)"
[[ "$head_after" == "$target_sha" ]] || fail "HEAD is $head_after after reset, expected $target_sha"
# Assert ATTACHMENT explicitly, not just the sha: a detached HEAD sitting on the
# upstream tip looks converged by sha and is not -- that is the exact state this
# ticket exists to repair, and a sha-only check would let it survive.
[[ "$(g symbolic-ref -q --short HEAD)" == "$branch" ]] \
  || fail "HEAD is not attached to $branch after converge"
[[ "$(g rev-parse '@{u}')" == "$head_after" ]] || fail "HEAD != @{u} after reset"
[[ -z "$(g status --porcelain --untracked-files=no)" ]] || fail "tracked tree still dirty after reset"

# --- record ------------------------------------------------------------------
detached_note=""
if (( detached )); then
  detached_note=" re-attached DETACHED HEAD to $branch ($branch_source), $detached_ahead detached-only commit(s) preserved as patches;"
fi
row="$(date -u +%Y-%m-%dT%H:%M:%SZ) | $lane | ${ticket:-$repo} | CONVERGED | converge-canonical-clone.sh $repo ($clone): branch $branch upstream $upstream;$detached_note HEAD ${head_before:0:7} -> ${head_after:0:7}; $dirty_total dirty paths ($staged staged, $unstaged worktree-modified, $untracked untracked) preserved at $evidence (full-vs-HEAD.patch sha256 ${patch_sha:0:12}); git reset --hard $target_sha$clean_note; verified HEAD==@{u} and clean tracked tree. No secrets printed."
append_ledger_row "$row"

cat <<EOF
CONVERGED: $repo ($clone)
  branch=$branch upstream=$upstream$( (( detached )) && printf '\n  re-attached DETACHED HEAD to %s (%s); %s detached-only commit(s) preserved' "$branch" "$branch_source" "$detached_ahead" || true)
  HEAD $head_before -> $head_after
  preserved: $evidence (full-vs-HEAD.patch sha256 $patch_sha)
  dirty paths: $dirty_total ($staged staged, $unstaged worktree-modified, $untracked untracked)${clean_note:+; untracked removed after preservation}
EOF
