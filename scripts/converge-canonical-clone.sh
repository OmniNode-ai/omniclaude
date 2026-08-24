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
#                               [--ticket OMN-XXXX] [--lane <name>]
#
# Refuses (exit 2): a target that is not a direct child of $OMNI_HOME with a .git
# DIRECTORY (worktrees carry a .git file and are never converged here), detached
# HEAD, a branch without an upstream, unknown options. Exit 0 on success or when
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
while [[ $# -gt 0 ]]; do
  case "$1" in
    --execute) execute=1 ;;
    --clean-untracked) clean_untracked=1 ;;
    --ticket) [[ $# -ge 2 ]] || refuse "--ticket needs a value"; ticket="$2"; shift ;;
    --lane) [[ $# -ge 2 ]] || refuse "--lane needs a value"; lane="$2"; shift ;;
    -h|--help) usage; exit 0 ;;
    -*) refuse "unknown option: $1" ;;
    *) [[ -z "$target" ]] || refuse "exactly one target is accepted (got '$target' and '$1')"; target="$1" ;;
  esac
  shift
done
[[ -n "$target" ]] || { usage >&2; exit 2; }

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

branch="$(g symbolic-ref -q --short HEAD 2>/dev/null)" \
  || refuse "detached HEAD in $clone; converging requires a checked-out branch with an upstream"
upstream="$(g rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null)" \
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

if [[ -z "$status" && "$head_before" == "$target_sha" ]]; then
  echo "already converged: $repo ($clone) HEAD == $upstream ($target_sha), clean tree"
  exit 0
fi

evidence_root="$OMNI_HOME/.onex_state/canonical-clone-converge"

if (( ! execute )); then
  cat <<EOF
DRY-RUN: would converge canonical clone '$repo' ($clone)
  branch=$branch upstream=$upstream
  HEAD $head_before -> $target_sha
  dirty paths: $dirty_total ($staged staged, $unstaged worktree-modified, $untracked untracked)
  would preserve status/patches/untracked copies/reflog/MANIFEST under $evidence_root/$repo-<utc>/
  then run: git -C $clone reset --hard $target_sha$( (( clean_untracked )) && printf ' && git clean -fd' || true )
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
while IFS= read -r f; do
  [[ -n "$f" ]] || continue
  mkdir -p "$evidence/untracked/$(dirname "$f")"
  cp -p "$clone/$f" "$evidence/untracked/$f"
done <<< "$untracked_list"

{
  echo "repo=$repo"
  echo "clone=$clone"
  echo "branch=$branch"
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
} > "$evidence/MANIFEST.txt"
patch_sha="$(sha256_of "$evidence/full-vs-HEAD.patch")"

# --- converge ----------------------------------------------------------------
g reset --hard --quiet "$target_sha" || fail "git reset --hard $target_sha failed (evidence kept at $evidence)"
clean_note=""
if (( clean_untracked )); then
  g clean -fd --quiet || fail "git clean -fd failed (evidence kept at $evidence)"
  clean_note=" + git clean -fd"
fi

head_after="$(g rev-parse HEAD)"
[[ "$head_after" == "$target_sha" ]] || fail "HEAD is $head_after after reset, expected $target_sha"
[[ "$(g rev-parse '@{u}')" == "$head_after" ]] || fail "HEAD != @{u} after reset"
[[ -z "$(g status --porcelain --untracked-files=no)" ]] || fail "tracked tree still dirty after reset"

# --- record ------------------------------------------------------------------
row="$(date -u +%Y-%m-%dT%H:%M:%SZ) | $lane | ${ticket:-$repo} | CONVERGED | converge-canonical-clone.sh $repo ($clone): branch $branch upstream $upstream; HEAD ${head_before:0:7} -> ${head_after:0:7}; $dirty_total dirty paths ($staged staged, $unstaged worktree-modified, $untracked untracked) preserved at $evidence (full-vs-HEAD.patch sha256 ${patch_sha:0:12}); git reset --hard $target_sha$clean_note; verified HEAD==@{u} and clean tracked tree. No secrets printed."
ledger="$OMNI_HOME/docs/tracking/ROLLING_WORK_LEDGER.md"
lock="$OMNI_HOME/scripts/ledger_lock.py"
if [[ -f "$lock" ]]; then
  python3 "$lock" "$ledger" --append "$row" || fail "ledger append via ledger_lock.py failed (clone IS converged; evidence at $evidence)"
elif [[ -f "$ledger" ]]; then
  printf '%s\n' "$row" >> "$ledger"
else
  echo "WARN: no ledger at $ledger; row not recorded:" >&2
  echo "$row" >&2
fi

cat <<EOF
CONVERGED: $repo ($clone)
  branch=$branch upstream=$upstream
  HEAD $head_before -> $head_after
  preserved: $evidence (full-vs-HEAD.patch sha256 $patch_sha)
  dirty paths: $dirty_total ($staged staged, $unstaged worktree-modified, $untracked untracked)${clean_note:+; untracked removed after preservation}
EOF
