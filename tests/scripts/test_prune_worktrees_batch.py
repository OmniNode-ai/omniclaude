# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Behavioural tests for ``scripts/prune-worktrees.sh`` (OMN-13686, OMN-20977).

The system under test is a bash script, so these tests drive it as a subprocess
with stubbed ``git`` and ``onex`` binaries on ``PATH``. No real GitHub API
calls and no real worktrees are touched.

Coverage:
  (1) OMN-13686: a run across >=30 worktrees spanning >=3 repos issues exactly
      ``N_repos`` ``onex scm pr-heads <slug> --source local`` calls — one per
      unique repo slug. The stub ``onex`` records every invocation.
  (2) OMN-20977: the merged decision comes from pr-heads output — a worktree
      is stale when a MERGED row's head branch is its branch OR a MERGED row's
      head oid is its HEAD — and an OPEN row's worktree is never stale. A gh
      tripwire on PATH proves no gh read happens at all.
  (3) Remote-branch-gone classification is unchanged.
  (4) The script carries no ``/Volumes/`` hardcoded default paths.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "prune-worktrees.sh"

REPOS = ("omniclaude", "omnibase_core", "omnibase_infra")


def _worktree_oid(ticket: str, repo: str) -> str:
    """The HEAD oid the stub git reports for <ticket>/<repo>."""
    return hashlib.sha256(f"{ticket}/{repo}".encode()).hexdigest()[:40]


# ---------------------------------------------------------------------------
# Stub binaries
# ---------------------------------------------------------------------------
# Stub `git`: derives branch/remote deterministically from the worktree path and
# reports a remote ref for every branch except those whose name contains "GONE".
# `rev-parse HEAD` answers a per-worktree deterministic oid (the sha256 of
# "<ticket>/<repo>", first 40 hex chars) so head-oid matching discriminates.
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
    printf 'lane/%s-%s\n' "$ticket" "$repo"
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
    if [[ "${args[*]}" == *HEAD* && "${args[*]}" != *--git-common-dir* ]]; then
      repo="$(basename "$dir")"
      ticket="$(basename "$(dirname "$dir")")"
      if command -v sha256sum >/dev/null 2>&1; then
        printf '%s/%s' "$ticket" "$repo" | sha256sum | cut -c1-40
      else
        printf '%s/%s' "$ticket" "$repo" | shasum -a 256 | cut -c1-40
      fi
    else
      printf '%s/.git/worktrees/wt\n' "$dir"
    fi
    ;;
  *)
    : ;;
esac
exit 0
"""

# Stub `onex`: logs every invocation and prints the recorded pr-heads answer
# seeded for the requested slug (argv: ... pr-heads <slug> --source local ...).
_ONEX_STUB = r"""#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$ONEX_PR_HEADS_LOG"
slug=""
prev=""
for a in "$@"; do
  if [[ "$prev" == "pr-heads" ]]; then slug="$a"; fi
  prev="$a"
done
python3 - "$ONEX_PR_HEADS_JSON" "$slug" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    answers = json.load(handle)
print(json.dumps(answers[sys.argv[2]]))
PY
"""

# Gh tripwire: the script must make no gh read at all (OMN-20977). Any call is
# logged and fails loudly.
_GH_TRIPWIRE = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >> "$GH_TRIPWIRE_LOG"
echo "prune-worktrees.sh must not call gh (OMN-20977)" >&2
exit 99
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


def _pr_heads_answer(rows: list[dict[str, object]]) -> dict[str, object]:
    """One recorded-shape pr-heads answer."""
    return {
        "verb": "pr-heads",
        "node": "node_github_repo_gateway_effect",
        "operation": "pr_heads",
        "repo": "",
        "source": "clone",
        "outcome": "completed",
        "watcher_tick": None,
        "bus": None,
        "result": {
            "total_count": None,
            "truncated": False,
            "operation": "pr_heads",
            "repo": "",
            "prs": rows,
        },
    }


def _pr_row(
    number: int, state: str, head_ref: str | None, oid: str
) -> dict[str, object]:
    return {
        "number": number,
        "state": state,
        "head_oid": oid,
        "head_ref": head_ref,
        "base_ref": "dev",
        "merge_commit_sha": "d" * 40 if state == "MERGED" else None,
        "merged_at": None,
    }


def _run(
    tmp_path: Path,
    *,
    tickets: list[str],
    answers_by_repo: dict[str, list[dict[str, object]]] | None = None,
    repos: tuple[str, ...] = REPOS,
) -> tuple[subprocess.CompletedProcess[str], Path, Path, int]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_stub(bin_dir / "git", _GIT_STUB)
    _write_stub(bin_dir / "onex", _ONEX_STUB)
    _write_stub(bin_dir / "gh", _GH_TRIPWIRE)

    root = tmp_path / "omni_worktrees"
    root.mkdir()
    n_worktrees = _make_worktrees(root, tickets, repos)

    onex_log = tmp_path / "onex_calls.log"
    onex_log.write_text("", encoding="utf-8")
    gh_log = tmp_path / "gh_calls.log"
    gh_log.write_text("", encoding="utf-8")
    answers = {
        f"OmniNode-ai/{repo}": _pr_heads_answer(rows)
        for repo, rows in (answers_by_repo or {}).items()
    }
    # Repos with no seeded answer get an empty (but completed) answer.
    for repo in repos:
        answers.setdefault(f"OmniNode-ai/{repo}", _pr_heads_answer([]))
    fixture = tmp_path / "pr_heads_by_slug.json"
    fixture.write_text(json.dumps(answers), encoding="utf-8")

    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
        "ONEX_PR_HEADS_LOG": str(onex_log),
        "ONEX_PR_HEADS_JSON": str(fixture),
        "GH_TRIPWIRE_LOG": str(gh_log),
    }
    # Drop OMNI_HOME so the canonical-clone prune loop is exercised only via the
    # explicit --worktrees-root path under test, and the onex resolution cannot
    # find a registry venv (the PATH stub must win).
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
    return proc, onex_log, gh_log, n_worktrees


# ---------------------------------------------------------------------------
# DoD 1 — one pr-heads call per unique repo slug, and no gh read at all
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_merged_state_batch_is_one_pr_heads_call_per_repo(tmp_path: Path) -> None:
    tickets = [f"OMN-{i}" for i in range(1, 12)]  # 11 tickets x 3 repos = 33 worktrees
    proc, onex_log, gh_log, n_worktrees = _run(tmp_path, tickets=tickets)

    assert proc.returncode == 0, f"script failed:\n{proc.stdout}\n{proc.stderr}"
    assert n_worktrees >= 30, f"expected >=30 worktrees, built {n_worktrees}"

    calls = [ln for ln in onex_log.read_text().splitlines() if ln.strip()]
    assert sorted(calls) == sorted(
        f"scm pr-heads OmniNode-ai/{repo} --source local" for repo in REPOS
    ), "expected one pr-heads call per repo, got:\n" + "\n".join(calls)
    # No gh read happens at all: the tripwire stayed silent.
    assert gh_log.read_text() == "", "prune-worktrees.sh still calls gh"
    # With no merged PRs and present remote refs, all worktrees are ACTIVE.
    assert f"Active:  {n_worktrees}" in proc.stdout
    assert "Stale:   0" in proc.stdout


# ---------------------------------------------------------------------------
# DoD 2 — classification from pr-heads output (MERGED / remote-gone / OPEN /
# ACTIVE), matched by head branch OR head oid
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_classification_merged_gone_open_active(tmp_path: Path) -> None:
    # OMN-1 across all repos is ACTIVE (its PR is OPEN); OMN-2/omniclaude is
    # merged by branch name; OMN-3/omnibase_core is merged by head oid only
    # (squash-merged, branch gone); OMN-GONE is gone.
    tickets = ["OMN-1", "OMN-2", "OMN-3", "OMN-GONE"]
    answers = {
        "omniclaude": [
            _pr_row(
                4242,
                "MERGED",
                "lane/OMN-2-omniclaude",
                _worktree_oid("OMN-2", "omniclaude"),
            ),
            _pr_row(
                5000,
                "OPEN",
                "lane/OMN-1-omniclaude",
                _worktree_oid("OMN-1", "omniclaude"),
            ),
        ],
        "omnibase_core": [
            # head_ref null: only the head oid names the merged PR.
            _pr_row(4243, "MERGED", None, _worktree_oid("OMN-3", "omnibase_core")),
        ],
    }
    proc, _onex_log, _gh_log, _n = _run(
        tmp_path, tickets=tickets, answers_by_repo=answers
    )

    assert proc.returncode == 0, f"script failed:\n{proc.stdout}\n{proc.stderr}"
    out = proc.stdout

    # Merged by branch name -> STALE (PR merged), with the PR number surfaced.
    assert "STALE (PR merged)" in out
    assert "OMN-2/omniclaude" in out
    assert "PR #4242" in out
    assert "matched by branch" in out

    # Merged by head oid alone -> STALE, the squash-merge shape.
    assert "OMN-3/omnibase_core" in out
    assert "PR #4243" in out
    assert "matched by head oid" in out

    # Remote-branch-gone -> STALE (remote branch gone) for every repo of OMN-GONE.
    assert "STALE (remote branch gone)" in out
    for repo in REPOS:
        assert f"OMN-GONE/{repo}" in out

    # ACTIVE = OMN-1 (x3 repos: its only PR is OPEN) + OMN-2/core + OMN-2/infra
    #          + OMN-3/omniclaude + OMN-3/infra = 7.
    # STALE = OMN-2/omniclaude (merged by branch) + OMN-3/core (merged by oid)
    #         + OMN-GONE (x3 repos) = 5.
    assert "Active:  7" in out
    assert "Stale:   5" in out


@pytest.mark.unit
def test_an_open_pr_row_never_makes_a_worktree_stale(tmp_path: Path) -> None:
    """The negative case from the ticket: an OPEN PR's worktree is never
    removed, whatever the branch or head oid say."""
    tickets = ["OMN-OPEN"]
    answers = {
        "omniclaude": [
            _pr_row(
                6001,
                "OPEN",
                "lane/OMN-OPEN-omniclaude",
                _worktree_oid("OMN-OPEN", "omniclaude"),
            )
        ],
        "omnibase_core": [
            _pr_row(
                6002,
                "OPEN",
                "lane/OMN-OPEN-omnibase_core",
                _worktree_oid("OMN-OPEN", "omnibase_core"),
            )
        ],
        "omnibase_infra": [
            _pr_row(
                6003,
                "OPEN",
                "lane/OMN-OPEN-omnibase_infra",
                _worktree_oid("OMN-OPEN", "omnibase_infra"),
            )
        ],
    }
    proc, _onex_log, _gh_log, n_worktrees = _run(
        tmp_path, tickets=tickets, answers_by_repo=answers
    )

    assert proc.returncode == 0, f"script failed:\n{proc.stdout}\n{proc.stderr}"
    assert f"Active:  {n_worktrees}" in proc.stdout
    assert "Stale:   0" in proc.stdout


# ---------------------------------------------------------------------------
# DoD 4 — no hardcoded /Volumes/ default paths remain
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_no_hardcoded_volumes_paths() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "/Volumes/" not in text, "script must not bake in a /Volumes/ default path"


# ---------------------------------------------------------------------------
# OMN-20977 — the script's own source must name pr-heads, not gh
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_the_script_names_no_gh_pr_read() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "gh pr list" not in text, "the merged decision must ride onex scm pr-heads"
