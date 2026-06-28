# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Behavioural tests for ``scripts/prune-worktrees.sh`` batching (OMN-13686).

The system under test is a bash script, so these tests drive it as a subprocess
with stubbed ``git`` and ``gh`` binaries on ``PATH``. No real GitHub API calls
and no real worktrees are touched.

DoD coverage (OMN-13686):
  (1) A run across >=30 worktrees spanning >=3 repos issues exactly ``N_repos``
      ``gh pr list --state merged`` calls — one per unique repo slug — instead of
      two calls per worktree. The stub ``gh`` records every invocation.
  (2) Staleness classification is unchanged: a merged-PR branch is STALE
      (PR merged), a remote-branch-gone branch is STALE (remote branch gone),
      and everything else is ACTIVE.
  (4) The script carries no ``/Volumes/`` hardcoded default paths.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "prune-worktrees.sh"

REPOS = ("omniclaude", "omnibase_core", "omnibase_infra")


# ---------------------------------------------------------------------------
# Stub binaries
# ---------------------------------------------------------------------------
# Stub `git`: derives branch/remote deterministically from the worktree path and
# reports a remote ref for every branch except those whose name contains "GONE".
_GIT_STUB = r"""#!/usr/bin/env bash
set -euo pipefail
dir="."
args=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    -C) dir="$2"; shift 2 ;;
    *) args+=("$1"); shift ;;
  esac
done
cmd="${args[0]:-}"
case "$cmd" in
  branch)
    repo="$(basename "$dir")"
    ticket="$(basename "$(dirname "$dir")")"
    printf 'jonah/%s-%s\n' "$ticket" "$repo"
    ;;
  remote)
    repo="$(basename "$dir")"
    printf 'git@github.com:OmniNode-ai/%s.git\n' "$repo"
    ;;
  ls-remote)
    all="${args[*]}"
    if [[ "$all" == *GONE* ]]; then
      :   # remote branch gone -> empty output
    else
      printf 'deadbeefdeadbeef\trefs/heads/x\n'
    fi
    ;;
  rev-parse)
    printf '%s/.git/worktrees/wt\n' "$dir"
    ;;
  *)
    : ;;
esac
exit 0
"""

# Stub `gh`: logs every invocation (one line per call) and emits the post-`--jq`
# TSV (number<TAB>headRefName) for the requested --repo slug from a fixture file.
_GH_STUB = r"""#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$GH_CALL_LOG"
slug=""
prev=""
for a in "$@"; do
  if [[ "$prev" == "--repo" ]]; then slug="$a"; fi
  prev="$a"
done
if [[ -n "${GH_MERGED_TSV:-}" && -f "$GH_MERGED_TSV" ]]; then
  while IFS=$'\t' read -r f_slug f_num f_ref; do
    [[ "$f_slug" == "$slug" ]] || continue
    printf '%s\t%s\n' "$f_num" "$f_ref"
  done < "$GH_MERGED_TSV"
fi
exit 0
"""


def _resolve_bash() -> str:
    """Pick a bash >= 4 (the script uses associative arrays)."""
    candidates = [shutil.which("bash"), "/opt/homebrew/bin/bash", "/usr/local/bin/bash"]
    for cand in candidates:
        if not cand or not Path(cand).exists():
            continue
        out = subprocess.run(
            [cand, "-c", "echo ${BASH_VERSINFO[0]}"],
            capture_output=True,
            text=True,
            check=False,
        )
        major = out.stdout.strip()
        if major.isdigit() and int(major) >= 4:
            return cand
    pytest.skip("no bash >= 4 available (script requires associative arrays)")
    raise AssertionError("pytest.skip did not terminate execution")


def _write_stub(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _make_worktrees(root: Path, tickets: list[str], repos: tuple[str, ...]) -> int:
    """Create <root>/<ticket>/<repo>/.git pointer files. Returns the count."""
    count = 0
    for ticket in tickets:
        for repo in repos:
            wt = root / ticket / repo
            wt.mkdir(parents=True)
            (wt / ".git").write_text("gitdir: /fake\n", encoding="utf-8")
            count += 1
    return count


def _run(
    tmp_path: Path,
    *,
    tickets: list[str],
    merged_tsv: str = "",
    repos: tuple[str, ...] = REPOS,
) -> tuple[subprocess.CompletedProcess[str], Path, int]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_stub(bin_dir / "git", _GIT_STUB)
    _write_stub(bin_dir / "gh", _GH_STUB)

    root = tmp_path / "omni_worktrees"
    root.mkdir()
    n_worktrees = _make_worktrees(root, tickets, repos)

    gh_log = tmp_path / "gh_calls.log"
    gh_log.write_text("", encoding="utf-8")
    merged_fixture = tmp_path / "merged.tsv"
    merged_fixture.write_text(merged_tsv, encoding="utf-8")

    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
        "GH_CALL_LOG": str(gh_log),
        "GH_MERGED_TSV": str(merged_fixture),
    }
    # Drop OMNI_HOME so the canonical-clone prune loop is exercised only via the
    # explicit --worktrees-root path under test.
    env.pop("OMNI_HOME", None)

    bash = _resolve_bash()
    proc = subprocess.run(
        [bash, str(SCRIPT), "--worktrees-root", str(root)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=120,
    )
    return proc, gh_log, n_worktrees


# ---------------------------------------------------------------------------
# DoD 1 — one merged-state gh call per unique repo slug
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_merged_state_batch_is_one_gh_call_per_repo(tmp_path: Path) -> None:
    tickets = [f"OMN-{i}" for i in range(1, 12)]  # 11 tickets x 3 repos = 33 worktrees
    proc, gh_log, n_worktrees = _run(tmp_path, tickets=tickets)

    assert proc.returncode == 0, f"script failed:\n{proc.stdout}\n{proc.stderr}"
    assert n_worktrees >= 30, f"expected >=30 worktrees, built {n_worktrees}"

    calls = [ln for ln in gh_log.read_text().splitlines() if ln.strip()]
    # Exactly one gh call per unique repo slug — the merged-state batch.
    assert len(calls) == len(REPOS), (
        f"expected {len(REPOS)} gh calls (one per repo), got {len(calls)}:\n"
        + "\n".join(calls)
    )
    # Every recorded gh call is a merged-state PR list (no per-worktree calls).
    for ln in calls:
        assert "pr list" in ln and "--state merged" in ln, f"unexpected gh call: {ln}"
    # With no merged PRs and present remote refs, all worktrees are ACTIVE.
    assert f"Active:  {n_worktrees}" in proc.stdout
    assert "Stale:   0" in proc.stdout


# ---------------------------------------------------------------------------
# DoD 2 — classification (MERGED / remote-gone / ACTIVE) is unchanged
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_classification_unchanged_merged_gone_active(tmp_path: Path) -> None:
    # OMN-1 across all repos is ACTIVE; OMN-2/omniclaude is merged; OMN-GONE is gone.
    tickets = ["OMN-1", "OMN-2", "OMN-GONE"]
    # gh reports OMN-2/omniclaude's branch as a merged PR.
    merged_tsv = "OmniNode-ai/omniclaude\t4242\tjonah/OMN-2-omniclaude\n"
    proc, _gh_log, _n = _run(tmp_path, tickets=tickets, merged_tsv=merged_tsv)

    assert proc.returncode == 0, f"script failed:\n{proc.stdout}\n{proc.stderr}"
    out = proc.stdout

    # Merged branch -> STALE (PR merged), with the PR number surfaced from the batch.
    assert "STALE (PR merged)" in out
    assert "OMN-2/omniclaude" in out
    assert "PR #4242" in out

    # Remote-branch-gone -> STALE (remote branch gone) for every repo of OMN-GONE.
    assert "STALE (remote branch gone)" in out
    for repo in REPOS:
        assert f"OMN-GONE/{repo}" in out

    # ACTIVE = OMN-1 (x3 repos) + OMN-2/core + OMN-2/infra = 5.
    # STALE = OMN-2/omniclaude merged (1) + OMN-GONE (x3 repos) = 4.
    assert "Active:  5" in out
    assert "Stale:   4" in out


# ---------------------------------------------------------------------------
# DoD 4 — no hardcoded /Volumes/ default paths remain
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_no_hardcoded_volumes_paths() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "/Volumes/" not in text, "script must not bake in a /Volumes/ default path"
