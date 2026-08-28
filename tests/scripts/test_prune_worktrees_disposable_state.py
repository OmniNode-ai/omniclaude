# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Teardown must not be blocked by disposable ``.onex_state`` output (OMN-15989).

WHY A SECOND SURFACE IS NEEDED AT ALL
-------------------------------------
The companion fix adds the disposable-by-default rule to the repo's own
``.gitignore``. That closes the problem for worktrees created *after* it
merges, and only those: a worktree checks out its own branch's ``.gitignore``,
so a rule merged to ``dev`` today does not exist in the tree of a worktree
branched last week. Six already-existing ``omnibase_core`` worktrees were
blocked from teardown at the time of writing, and no ``.gitignore`` change can
reach them. The teardown tool has to make the same call itself.

THE RULE, IDENTICAL ON BOTH SURFACES
------------------------------------
An **untracked** path under a worktree's own ``.onex_state/`` is disposable and
does not block teardown -- **except** under the two named durable subtrees
``.onex_state/evidence/`` and ``.onex_state/friction/``, which are committed
content and do block.

Note the word *untracked*. A ``M``/``D``/``A`` line for a ``.onex_state`` path
means a tracked evidence file was modified or deleted -- real work, and it
still blocks. Only ``??`` lines are disposable.

TEST DESIGN
-----------
The system under test is bash, so it runs as a subprocess against **real** git
repositories: a bare "origin", a canonical clone, and real linked worktrees.
Only two things are faked, and both are faked to keep the test hermetic rather
than to fake the behaviour under test:

* ``gh`` is stubbed to report the branch as having a merged PR, which is what
  makes the worktree STALE and gets it into the removal loop at all;
* ``git`` is wrapped so ``fetch`` and ``ls-remote origin`` never touch the
  network. Every other git call -- including the ``status --porcelain`` under
  test and the real ``git worktree remove`` -- is the real binary.

The assertions are on the outcome that matters: is the worktree still on disk
afterwards.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import NamedTuple

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "prune-worktrees.sh"

SLUG = "OmniNode-ai/omni15989"
REMOTE_URL = f"https://github.com/{SLUG}.git"
BRANCH = "jonah/omn-15989-fixture"

# `git` wrapper: real git for everything except the two calls that would reach
# the network. `fetch` becomes a no-op; `ls-remote <...> origin <...>` returns
# nothing, which is exactly what the script sees for an unreachable remote and
# sends it down its canonical-clone fallback (a local path, real git).
_GIT_WRAPPER = r"""#!/usr/bin/env bash
set -uo pipefail
for a in "$@"; do
  case "$a" in
    fetch) exit 0 ;;
    ls-remote) LS=1 ;;
  esac
done
if [[ "${LS:-0}" == 1 ]]; then
  for a in "$@"; do
    [[ "$a" == "origin" ]] && exit 0
  done
fi
exec "$REAL_GIT" "$@"
"""

# `gh` stub: report the fixture branch as a merged PR so the worktree is STALE.
_GH_STUB = r"""#!/usr/bin/env bash
set -euo pipefail
printf '%s\t%s\n' "4242" "BRANCH_PLACEHOLDER"
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


def _clean_git_env() -> dict[str, str]:
    """Env with git's hook-exported location vars removed.

    ``GIT_DIR``/``GIT_WORK_TREE``/``GIT_INDEX_FILE``/``GIT_COMMON_DIR`` override
    both ``cwd=`` and ``git -C``. Inheriting them from a pre-commit or pre-push
    hook would point every git call in this test at the real invoking worktree.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_AUTHOR_NAME"] = env["GIT_COMMITTER_NAME"] = "omn15989"
    env["GIT_AUTHOR_EMAIL"] = env["GIT_COMMITTER_EMAIL"] = "omn15989@example.invalid"
    return env


def _git(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", *args], capture_output=True, text=True, env=env, check=False, timeout=60
    )
    assert proc.returncode == 0, f"git {' '.join(args)} failed: {proc.stderr}"
    return proc


def _write_exec(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


class Harness(NamedTuple):
    """One real canonical clone + one real linked worktree on a stale branch."""

    env: dict[str, str]
    root: Path
    worktree: Path
    tmp: Path


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    """Real bare origin + canonical clone + one linked worktree on a stale branch."""
    env = _clean_git_env()

    bare = tmp_path / "origin.git"
    _git(env, "init", "--bare", "-q", str(bare))

    canonical = tmp_path / "canonical"
    _git(env, "init", "-q", "-b", "dev", str(canonical))
    _git(env, "-C", str(canonical), "remote", "add", "origin", REMOTE_URL)
    (canonical / "src").mkdir()
    (canonical / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(env, "-C", str(canonical), "add", "-A")
    _git(env, "-C", str(canonical), "commit", "-q", "-m", "init")
    _git(env, "-C", str(canonical), "branch", BRANCH)

    # Push both refs into the bare repo and wire up remote-tracking, so the
    # script's `git log @{u}..HEAD` resolves offline and reports no unpushed
    # commits. Pushing by explicit refspec avoids depending on push.default.
    _git(
        env,
        "-C",
        str(canonical),
        "push",
        "-q",
        str(bare),
        "refs/heads/dev:refs/heads/dev",
        f"refs/heads/{BRANCH}:refs/heads/{BRANCH}",
    )
    _git(
        env,
        "-C",
        str(canonical),
        "update-ref",
        f"refs/remotes/origin/{BRANCH}",
        f"refs/heads/{BRANCH}",
    )

    root = tmp_path / "omni_worktrees"
    worktree = root / "OMN-15989" / "repo"
    worktree.parent.mkdir(parents=True)
    _git(env, "-C", str(canonical), "worktree", "add", "-q", str(worktree), BRANCH)
    _git(
        env,
        "-C",
        str(worktree),
        "branch",
        f"--set-upstream-to=origin/{BRANCH}",
        BRANCH,
    )

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_exec(bin_dir / "git", _GIT_WRAPPER)
    _write_exec(bin_dir / "gh", _GH_STUB.replace("BRANCH_PLACEHOLDER", BRANCH))

    real_git = shutil.which("git")
    assert real_git, "git not on PATH"

    run_env = {
        **env,
        "REAL_GIT": real_git,
        "PATH": f"{bin_dir}:{env.get('PATH', '')}",
    }
    run_env.pop("OMNI_HOME", None)

    return Harness(env=run_env, root=root, worktree=worktree, tmp=tmp_path)


def _run_prune(harness: Harness) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            _resolve_bash(),
            str(SCRIPT),
            "--execute",
            "--worktrees-root",
            str(harness.root),
        ],
        capture_output=True,
        text=True,
        env=harness.env,
        # A non-repo cwd: the script's staleness probe runs `git ls-remote` in
        # the CWD, and this keeps that from resolving some ambient repository.
        cwd=str(harness.tmp),
        check=False,
        timeout=180,
    )


# ---------------------------------------------------------------------------
# The class this ticket exists for: disposable output must not block teardown.
# ---------------------------------------------------------------------------
@pytest.mark.unit
@pytest.mark.parametrize(
    "rel_path",
    [
        ".onex_state/push_log.txt",
        ".onex_state/push_exit_code.txt",
        ".onex_state/MOVED_TO_201.md",
        ".onex_state/omn16507-prepush-waiter.sh",
        ".onex_state/OMN-16677-push-handoff.md",
        ".onex_state/consumer-graph.json",
        ".onex_state/local_runtime/node/run/state.yaml",
    ],
)
def test_untracked_onex_state_output_does_not_block_teardown(
    harness: Harness, rel_path: str
) -> None:
    worktree = harness.worktree
    target = worktree / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("regenerable\n", encoding="utf-8")

    proc = _run_prune(harness)

    assert proc.returncode == 0, f"script failed:\n{proc.stdout}\n{proc.stderr}"
    assert not worktree.exists(), (
        f"{rel_path} is disposable generated output but still blocked teardown:\n"
        f"{proc.stdout}"
    )


# ---------------------------------------------------------------------------
# NEGATIVE CONTROLS — the rule must not widen into a mask over real work.
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_modified_source_file_still_blocks_teardown(harness: Harness) -> None:
    worktree = harness.worktree
    (worktree / "src" / "app.py").write_text("VALUE = 2\n", encoding="utf-8")

    proc = _run_prune(harness)

    assert proc.returncode == 0, f"script failed:\n{proc.stdout}\n{proc.stderr}"
    assert worktree.exists(), (
        "a worktree with a modified tracked source file was removed — the "
        f".onex_state allowlist widened into a mask over real work:\n{proc.stdout}"
    )
    assert "has uncommitted changes" in proc.stdout


@pytest.mark.unit
def test_untracked_source_file_still_blocks_teardown(
    harness: Harness,
) -> None:
    worktree = harness.worktree
    (worktree / "src" / "new_module.py").write_text("NEW = 1\n", encoding="utf-8")

    proc = _run_prune(harness)

    assert proc.returncode == 0, f"script failed:\n{proc.stdout}\n{proc.stderr}"
    assert worktree.exists(), (
        "a worktree with an untracked source file was removed — untracked-ness "
        f"alone must never make a path disposable:\n{proc.stdout}"
    )


@pytest.mark.unit
def test_untracked_durable_evidence_subtree_still_blocks_teardown(
    harness: Harness,
) -> None:
    """`.onex_state/evidence/` is committed content, not scratch."""
    worktree = harness.worktree
    evidence = worktree / ".onex_state" / "evidence" / "OMN-15989" / "proof.md"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("durable evidence awaiting commit\n", encoding="utf-8")

    proc = _run_prune(harness)

    assert proc.returncode == 0, f"script failed:\n{proc.stdout}\n{proc.stderr}"
    assert worktree.exists(), (
        "uncommitted evidence under the named durable subtree was treated as "
        f"disposable and the worktree was deleted:\n{proc.stdout}"
    )


@pytest.mark.unit
def test_deleted_tracked_onex_state_file_still_blocks_teardown(
    harness: Harness,
) -> None:
    """A ``D``/``M`` line for a .onex_state path is real work, not scratch.

    Only untracked (``??``) entries are disposable. This is the case a naive
    ``grep -v '.onex_state'`` filter would get wrong.
    """
    worktree = harness.worktree
    env = harness.env

    tracked = worktree / ".onex_state" / "evidence" / "committed.md"
    tracked.parent.mkdir(parents=True)
    tracked.write_text("committed evidence\n", encoding="utf-8")
    _git(env, "-C", str(worktree), "add", "-f", str(tracked))
    _git(env, "-C", str(worktree), "commit", "-q", "-m", "add evidence")
    # Advance the remote-tracking ref directly rather than pushing: the fixture
    # remote URL is a GitHub-shaped string (the script parses a slug out of it)
    # and a real push would leave the hermetic sandbox. The script only reads
    # `git log @{u}..HEAD`, which this satisfies offline.
    _git(
        env,
        "-C",
        str(worktree),
        "update-ref",
        f"refs/remotes/origin/{BRANCH}",
        "HEAD",
    )
    tracked.unlink()

    proc = _run_prune(harness)

    assert proc.returncode == 0, f"script failed:\n{proc.stdout}\n{proc.stderr}"
    assert worktree.exists(), (
        "a DELETED tracked .onex_state file was treated as disposable — the "
        f"filter must key on untracked (??) status, not on the path alone:\n{proc.stdout}"
    )


@pytest.mark.unit
def test_clean_worktree_is_still_removed(harness: Harness) -> None:
    """Baseline: with nothing dirty at all, teardown proceeds as before."""
    worktree = harness.worktree

    proc = _run_prune(harness)

    assert proc.returncode == 0, f"script failed:\n{proc.stdout}\n{proc.stderr}"
    assert not worktree.exists(), (
        f"clean stale worktree was not removed:\n{proc.stdout}"
    )
