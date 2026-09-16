# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""The end-to-end canary for the lane-identity mechanism (OMN-18273).

WHY THIS FILE EXISTS. OMN-18259 designed lane identity, and OMN-18260, OMN-18261,
OMN-18262 and OMN-18263 implemented it. All four merged and all four were marked
Done on 2026-09-13. Measured on 2026-09-16 in the canonical clones: **zero**
commits carried a lane trailer over the last 200 commits of each of three worked
repositories, against a `Co-authored-by` positive control of 52, 196 and 67 in
the same windows. Nothing had changed. Meanwhile peer lanes pushed onto each
other's branches three more times in the two days after the mechanism shipped.

Nothing was red. Every unit test passed against a scratch repository built the
way the tests build one, and the shipped mechanism could not be installed on the
workspace it was written for.

THE TWO FAULTS, BOTH NECESSARY AND NEITHER SUFFICIENT:

  1. The installer resolved its target through `git rev-parse --git-path hooks`,
     which HONOURS `core.hooksPath`. Every canonical clone in this registry
     points that at one shared guard directory, so the installer's own
     shared-directory refusal fired on every clone and `install-hook` exited 2
     everywhere. It was not that nobody ran it; running it could not succeed.

  2. `core.hooksPath` REPLACES git's hook lookup outright. The shared guard
     dispatches only the hook types it has an entry for -- `pre-commit`,
     `commit-msg`, `pre-push`, `pre-merge-commit` -- and `prepare-commit-msg`
     was not among them. So even a hook written into the right directory would
     never have been invoked.

The design anticipated exactly this class and asked for exactly this file:
"a gate that passes when it cannot see its own state is not a gate" (section 4),
and OMN-17005's eighth criterion, adopted by OMN-18262 -- "a canary proving a
synthetic violation is actually refused end to end, and failing if the guard is
unregistered".

SO THESE TESTS RUN REAL GIT. A real clone whose `core.hooksPath` points at a
real chaining guard, a real linked worktree, a real `git commit`, a real
`git push` to a real remote. Every assertion below is on an observed exit status
or on bytes git itself wrote. Reading a script proves nothing about it: the most
expensive defect of OMN-18260 was invisible to every test that only read one.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts import lane_identity as li

REPO_ROOT = Path(__file__).resolve().parents[2]
LEDGER_NAME = "SCRATCH_LEDGER.md"

# A chaining guard with the same shape as the workspace's real one: it does its
# own work, then hands control to the clone's own hook of the same type. This is
# what makes a hook installed in `<git-common-dir>/hooks` reachable at all.
GUARD = """#!/usr/bin/env bash
set -euo pipefail
hook_name="$(basename "$0")"
common="$(git rev-parse --path-format=absolute --git-common-dir)"
real="$common/hooks/$hook_name"
if [ -x "$real" ]; then
  exec "$real" "$@"
fi
exit 0
"""


def _stamp(offset_hours: float = 0.0) -> str:
    return (datetime.now(UTC) - timedelta(hours=offset_hours)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _claim_index_module() -> Path:
    """Where the claim index module is, resolved fail-fast.

    No fallback and no skip. A test that SKIPPED when it could not find the
    module would turn "the canary could not run" into a green run, which is the
    precise failure this file exists to remove.
    """
    explicit = os.environ.get("ONEX_CLAIM_INDEX_MODULE")
    if explicit:
        return Path(explicit).resolve()
    workspace = os.environ.get(li.WORKSPACE_ENV)
    if workspace:
        return Path(workspace) / "docs" / "workflows" / "_shared" / "claim_index.py"
    raise AssertionError(
        f"neither ONEX_CLAIM_INDEX_MODULE nor {li.WORKSPACE_ENV} is set, so the claim "
        "index "
        "module cannot be located and this canary cannot run. It FAILS rather than "
        "skips: a gate that cannot run has not passed."
    )


@pytest.fixture
def workspace(tmp_path: Path) -> dict:
    """A miniature of the real workspace.

    One bare remote, one clone whose `core.hooksPath` points at a shared
    chaining guard directory, one linked worktree under
    `omni_worktrees/<TICKET>/<repo>`, and a scratch claim store. Every structural
    property that made the shipped mechanism inert is reproduced here, so a
    regression reproduces with it.
    """
    home = tmp_path / "home"
    home.mkdir()
    shared = home / "scripts" / "git-hooks" / "canonical-clone"
    shared.mkdir(parents=True)
    guard = home / "scripts" / "git-hooks" / "guard.sh"
    guard.write_text(GUARD, encoding="utf-8")
    guard.chmod(0o755)
    # Only the hook types the real workspace's installer script creates. The
    # missing `prepare-commit-msg` entry is fault 2, reproduced.
    for hook_name in ("pre-commit", "commit-msg", "pre-push", "pre-merge-commit"):
        (shared / hook_name).symlink_to(os.path.relpath(guard, shared))

    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True
    )

    repo = home / "widget"
    repo.mkdir()
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"),
        "GIT_CONFIG_SYSTEM": str(tmp_path / "gitconfig-system"),
        li.WORKSPACE_ENV: str(home),
        "ONEX_LANE_REGISTRY_ROOT": str(home / ".onex_state"),
        "ONEX_LANE_PYTHON": sys.executable,
        "ONEX_BRANCH_CLAIM_LEDGER": str(home / LEDGER_NAME),
        "ONEX_BRANCH_CLAIM_LEDGER_NAME": LEDGER_NAME,
        "ONEX_BRANCH_CLAIM_INDEX_MODULE": str(_claim_index_module()),
    }
    for leaked in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE"):
        env.pop(leaked, None)

    def git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=str(cwd or repo),
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )

    git("init", "-q", "-b", "main")
    git("config", "user.email", "canary@example.com")
    git("config", "user.name", "canary")
    git("config", "core.hooksPath", str(shared))
    git("remote", "add", "origin", str(remote))
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    git("add", "seed.txt")
    git("commit", "-q", "-m", "seed")
    git("push", "-q", "origin", "main")

    (home / LEDGER_NAME).write_text("# scratch claim store\n", encoding="utf-8")

    return {"home": home, "repo": repo, "shared": shared, "env": env, "git": git}


def _add_worktree(workspace: dict, ticket: str, branch: str) -> Path:
    path = workspace["home"] / "omni_worktrees" / ticket / "widget"
    path.parent.mkdir(parents=True, exist_ok=True)
    workspace["git"]("worktree", "add", "-q", str(path), "-b", branch, "main")
    return path


def _lane_identity(workspace: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: PLW1510 - the return code IS the assertion
        [sys.executable, str(REPO_ROOT / "scripts" / "lane_identity.py"), *args],
        capture_output=True,
        text=True,
        env=workspace["env"],
    )


def _branch_claim(workspace: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: PLW1510 - the return code IS the assertion
        [sys.executable, str(REPO_ROOT / "scripts" / "branch_claim.py"), *args],
        capture_output=True,
        text=True,
        env=workspace["env"],
    )


def _claim(workspace: dict, lane: str, ticket: str, offset_hours: float = 0.0) -> None:
    ledger = workspace["home"] / LEDGER_NAME
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(
            f"{_stamp(offset_hours)} | CLAIM | lane={lane} | tickets={ticket} | taking it\n"
        )


def _commit(workspace: dict, worktree: Path, name: str) -> str:
    (worktree / name).write_text(name, encoding="utf-8")
    workspace["git"]("add", name, cwd=worktree)
    workspace["git"]("commit", "-q", "-m", f"fix: {name}", cwd=worktree)
    return workspace["git"]("log", "-1", "--format=%B", cwd=worktree).stdout


# ---------------------------------------------------------------------------
# The canary: the mechanism is inert until it is armed, and says so
# ---------------------------------------------------------------------------


def test_the_shipped_state_is_inert_and_status_says_so(workspace: dict) -> None:
    """The measured 2026-09-16 state, reproduced. A registered worktree, a real
    commit, and no trailer -- because nothing is installed and the shared guard
    has no entry to dispatch. `status` must report this NONZERO: silence here is
    how four Done tickets stayed inert for three days."""
    worktree = _add_worktree(workspace, "OMN-9901", "lane/omn-9901-thing")
    assert (
        _lane_identity(
            workspace,
            "register",
            "--lane",
            "alpha",
            "--ticket",
            "OMN-9901",
            "--worktree",
            str(worktree),
        ).returncode
        == 0
    )

    message = _commit(workspace, worktree, "a.txt")
    assert li.LANE_TRAILER not in message

    status = _lane_identity(workspace, "status", "--repo", str(workspace["repo"]))
    assert status.returncode == 1, status.stdout + status.stderr
    assert "UNARMED" in status.stdout


def test_reconcile_arms_the_workspace_and_a_real_commit_carries_the_trailer(
    workspace: dict,
) -> None:
    """THE CANARY. Arm, commit for real, and read the trailer back out of git.

    This is the assertion that would have been red on 2026-09-13 and every day
    since, and the one the repository had no test for: every existing test built
    its scratch repository WITHOUT a `core.hooksPath` override, so none of them
    could observe either fault.
    """
    worktree = _add_worktree(workspace, "OMN-9902", "lane/omn-9902-thing")
    _lane_identity(
        workspace,
        "register",
        "--lane",
        "alpha",
        "--ticket",
        "OMN-9902",
        "--worktree",
        str(worktree),
    )

    reconcile = _lane_identity(workspace, "reconcile", "--execute")
    assert reconcile.returncode == 0, reconcile.stdout + reconcile.stderr
    assert (workspace["shared"] / "prepare-commit-msg").exists()

    status = _lane_identity(workspace, "status", "--repo", str(workspace["repo"]))
    assert status.returncode == 0, status.stdout + status.stderr

    message = _commit(workspace, worktree, "b.txt")
    assert f"{li.LANE_TRAILER}: alpha" in message
    assert li.SESSION_TRAILER in message

    # The commit resolves to exactly one lane by the same reader the gate uses.
    assert li.commit_identity(message) is not None
    assert li.commit_identity(message)[0] == "alpha"


def test_the_canary_goes_red_when_the_hook_is_removed(workspace: dict) -> None:
    """The positive control's negative half. If deleting the installed hook left
    this green, the test above would be asserting nothing -- which is exactly
    the state the repository was in."""
    worktree = _add_worktree(workspace, "OMN-9903", "lane/omn-9903-thing")
    _lane_identity(
        workspace,
        "register",
        "--lane",
        "alpha",
        "--ticket",
        "OMN-9903",
        "--worktree",
        str(worktree),
    )
    assert _lane_identity(workspace, "reconcile", "--execute").returncode == 0
    assert li.LANE_TRAILER in _commit(workspace, worktree, "c.txt")

    (workspace["repo"] / ".git" / "hooks" / "prepare-commit-msg").unlink()

    assert li.LANE_TRAILER not in _commit(workspace, worktree, "d.txt")
    assert (
        _lane_identity(workspace, "status", "--repo", str(workspace["repo"])).returncode
        == 1
    )


def test_the_canary_goes_red_when_the_shared_dispatch_entry_is_removed(
    workspace: dict,
) -> None:
    """Fault 2 on its own. The hook file is present and correct; git simply never
    invokes it. This is the half no amount of reading `.git/hooks` would reveal,
    and the half that made `ls .git/hooks` a misleading probe."""
    worktree = _add_worktree(workspace, "OMN-9904", "lane/omn-9904-thing")
    _lane_identity(
        workspace,
        "register",
        "--lane",
        "alpha",
        "--ticket",
        "OMN-9904",
        "--worktree",
        str(worktree),
    )
    assert _lane_identity(workspace, "reconcile", "--execute").returncode == 0
    assert li.LANE_TRAILER in _commit(workspace, worktree, "e.txt")

    (workspace["shared"] / "prepare-commit-msg").unlink()

    assert (workspace["repo"] / ".git" / "hooks" / "prepare-commit-msg").is_file()
    assert li.LANE_TRAILER not in _commit(workspace, worktree, "f.txt")
    assert (
        _lane_identity(workspace, "status", "--repo", str(workspace["repo"])).returncode
        == 1
    )


def test_reconcile_backfills_only_a_worktree_with_a_live_holder(
    workspace: dict,
) -> None:
    """Backfill never invents a lane, and never resurrects a dead one.

    Registration comes from the AUTHORITATIVE claim index, not from a second
    parser of the same store, so its three outcomes are the index's own: a live
    claim registers; a released claim does not; a ticket nobody ever claimed does
    not. A lane whose claim was released is exactly as wrong to stamp as a lane
    that never existed -- both produce a trailer naming somebody who is not
    working there.
    """
    live = _add_worktree(workspace, "OMN-9905", "lane/omn-9905-a")
    released = _add_worktree(workspace, "OMN-9906", "lane/omn-9906-a")
    never = _add_worktree(workspace, "OMN-9907", "lane/omn-9907-a")

    _claim(workspace, "alpha", "OMN-9905")
    _claim(workspace, "beta", "OMN-9906", offset_hours=2)
    ledger = workspace["home"] / LEDGER_NAME
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(
            f"{_stamp(1)} | RELEASE | lane=beta | tickets=OMN-9906 | done with it\n"
        )

    assert _lane_identity(workspace, "reconcile", "--execute").returncode == 0

    base = workspace["home"] / ".onex_state"
    resolved = li.resolve(base, live)
    assert resolved is not None
    assert resolved.lane == "alpha"
    assert li.resolve(base, released) is None
    assert li.resolve(base, never) is None


def test_reconcile_backfills_nothing_when_the_claim_index_is_unreachable(
    workspace: dict,
) -> None:
    """Fail closed on the backfill, and say so. The hooks still install -- they
    are safe without any registration -- but a holder is never guessed by a
    local parser standing in for the module that decides who a holder is."""
    worktree = _add_worktree(workspace, "OMN-9909", "lane/omn-9909-a")
    _claim(workspace, "alpha", "OMN-9909")
    env = dict(workspace["env"])
    env["ONEX_BRANCH_CLAIM_INDEX_MODULE"] = str(workspace["home"] / "absent.py")
    result = subprocess.run(  # noqa: PLW1510 - the return code IS the assertion
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "lane_identity.py"),
            "reconcile",
            "--execute",
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "did not load" in result.stderr
    assert li.resolve(workspace["home"] / ".onex_state", worktree) is None
    # The install half still happened.
    assert (workspace["repo"] / ".git" / "hooks" / "prepare-commit-msg").is_file()


# ---------------------------------------------------------------------------
# The three 2026-09-15/16 incidents, reproduced synthetically and refused
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ticket", "branch", "holder", "intruder"),
    [
        # 2026-09-15T14:08:31Z -- a credential-binding commit pushed into the
        # omn14894-migration-0041-release lane's branch, out of scope for the
        # receiving lane's own consent row.
        (
            "OMN-14894",
            "lane/omn-14894-desired-clients",
            "omn14894-migration-0041-release",
            "peer-lane-one",
        ),
        # 2026-09-16T01:38:55Z -- two commits onto the OMN-18079 branch, one of
        # them carrying the receiving lane's own uncommitted comment block.
        (
            "OMN-18079",
            "lane/omn-18079-vendor-overlay-provider-backfill",
            "omn18079-owner",
            "peer-lane-two",
        ),
        # 2026-09-16T07:36:03Z -- 4b8c2d22 pushed onto the OMN-17228 branch.
        (
            "OMN-17228",
            "lane/omn-17228-verdict-envelope-tenant",
            "omn17228-owner",
            "peer-lane-three",
        ),
    ],
)
def test_a_peer_lane_push_onto_a_held_branch_is_refused(
    workspace: dict, ticket: str, branch: str, holder: str, intruder: str
) -> None:
    """The three incidents of 2026-09-15 and 2026-09-16, each as a real
    `git push` that must fail, with the holder and the citable row named.

    The holder's own push on the same branch is the green control in the test
    below. Without that control a refusal here would be consistent with a hook
    that simply refuses everything.
    """
    worktree = _add_worktree(workspace, ticket, branch)
    _lane_identity(
        workspace,
        "register",
        "--lane",
        intruder,
        "--ticket",
        ticket,
        "--worktree",
        str(worktree),
    )
    assert _lane_identity(workspace, "reconcile", "--execute").returncode == 0
    assert (
        _branch_claim(
            workspace, "install-hook", "--repo", str(workspace["repo"])
        ).returncode
        == 0
    )

    _claim(workspace, holder, ticket)
    _commit(workspace, worktree, "intruder.txt")

    push = subprocess.run(  # noqa: PLW1510 - the return code IS the assertion
        ["git", "push", "-q", "origin", f"HEAD:refs/heads/{branch}"],
        cwd=str(worktree),
        capture_output=True,
        text=True,
        env=workspace["env"],
    )
    combined = push.stdout + push.stderr
    assert push.returncode != 0, combined
    assert holder in combined
    assert LEDGER_NAME in combined


def test_the_holder_pushing_the_same_branch_is_the_green_control(
    workspace: dict,
) -> None:
    """The positive control for the three refusals above. Identical setup, one
    field different: the pushing lane IS the claim holder."""
    ticket, branch, holder = (
        "OMN-18079",
        "lane/omn-18079-vendor-overlay",
        "omn18079-owner",
    )
    worktree = _add_worktree(workspace, ticket, branch)
    _lane_identity(
        workspace,
        "register",
        "--lane",
        holder,
        "--ticket",
        ticket,
        "--worktree",
        str(worktree),
    )
    assert _lane_identity(workspace, "reconcile", "--execute").returncode == 0
    assert (
        _branch_claim(
            workspace, "install-hook", "--repo", str(workspace["repo"])
        ).returncode
        == 0
    )

    _claim(workspace, holder, ticket)
    _commit(workspace, worktree, "holder.txt")

    push = subprocess.run(  # noqa: PLW1510 - the return code IS the assertion
        ["git", "push", "-q", "origin", f"HEAD:refs/heads/{branch}"],
        cwd=str(worktree),
        capture_output=True,
        text=True,
        env=workspace["env"],
    )
    assert push.returncode == 0, push.stdout + push.stderr


def test_the_pre_push_install_preserves_and_chains_the_repository_own_hook(
    workspace: dict,
) -> None:
    """Every canonical clone already carries a pre-commit framework `pre-push`
    that runs the governed impacted-test selector. The shipped installer wrote
    over it. It must be preserved, still run, and still be able to refuse --
    a chained gate whose exit status is swallowed is a silent bypass."""
    hooks = workspace["repo"] / ".git" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    marker = workspace["home"] / "prior-ran.txt"
    prior = hooks / "pre-push"
    prior.write_text(
        f'#!/usr/bin/env bash\ncat > "{marker}"\nexit 7\n',
        encoding="utf-8",
    )
    prior.chmod(0o755)

    assert (
        _branch_claim(
            workspace, "install-hook", "--repo", str(workspace["repo"])
        ).returncode
        == 0
    )
    assert (hooks / f"pre-push{li.PRIOR_SUFFIX}").is_file()

    worktree = _add_worktree(workspace, "OMN-9908", "lane/omn-9908-chain")
    _lane_identity(
        workspace,
        "register",
        "--lane",
        "alpha",
        "--ticket",
        "OMN-9908",
        "--worktree",
        str(worktree),
    )
    _lane_identity(workspace, "reconcile", "--execute")
    _commit(workspace, worktree, "chain.txt")

    push = subprocess.run(  # noqa: PLW1510 - the return code IS the assertion
        ["git", "push", "-q", "origin", "HEAD:refs/heads/lane/omn-9908-chain"],
        cwd=str(worktree),
        capture_output=True,
        text=True,
        env=workspace["env"],
    )
    # The chained hook refused, so the push failed with ITS status, not ours.
    assert push.returncode != 0
    # And it received the ref lines git wrote, rather than an stdin this hook
    # had already drained.
    assert marker.is_file()
    assert "refs/heads/lane/omn-9908-chain" in marker.read_text(encoding="utf-8")
