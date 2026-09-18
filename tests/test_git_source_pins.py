# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-18752: git-sourced siblings answer to the canonical clone, not the lock.

Two sanctioned reconcilers claimed the plugin CLI venv with opposite
authorities. ``ensure-plugin-venv.sh`` syncs it exactly to ``uv.lock``, which
pins omnimarket by immutable git rev; ``check-omnimarket-venv-drift.sh``
converges it to the canonical clone HEAD and its in-process guard refuses every
``onex delegate`` when the two differ. Whichever ran last left the other's gate
red, and the skew gate's only remedy was a 22-commit downgrade.

These tests pin the resolution: for a git source the canonical clone is the
authority on every surface, and the lock follows it. The classification is
therefore about COMMITS and ANCESTRY, never about version strings.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


# OMN-18434: git exports GIT_DIR / GIT_WORK_TREE / GIT_INDEX_FILE /
# GIT_COMMON_DIR into every hook environment, and those OVERRIDE both ``cwd=``
# and ``git -C``. A fixture that shells out to git under a pre-commit hook
# would therefore rewrite the REAL invoking worktree rather than tmp_path.
_GIT_LOCATION_VARS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_CEILING_DIRECTORIES",
    "GIT_NAMESPACE",
)


def scrub_git_location_env(env: Mapping[str, str]) -> dict[str, str]:
    return {k: v for k, v in env.items() if k not in _GIT_LOCATION_VARS}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        env=scrub_git_location_env(os.environ),
    ).stdout.strip()


@pytest.fixture
def fixture_clone(tmp_path: Path) -> Path:
    """A three-commit git repo standing in for a canonical clone."""
    repo = tmp_path / "omnimarket"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "dev")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    for n in range(3):
        (repo / "f.txt").write_text(f"{n}\n", encoding="utf-8")
        _git(repo, "add", "f.txt")
        _git(repo, "commit", "-q", "-m", f"c{n}")
    return repo


# --------------------------------------------------------------------------
# parsing git sources out of uv.lock
# --------------------------------------------------------------------------


def test_parse_git_sources_extracts_name_url_and_rev(tmp_path: Path) -> None:
    """A git-sourced [[package]] yields its url and its pinned rev."""
    from scripts import git_source_pins as gsp  # noqa: PLC0415

    lock = tmp_path / "uv.lock"
    lock.write_text(
        "version = 1\n\n"
        "[[package]]\n"
        'name = "omnimarket"\n'
        'version = "0.4.114"\n'
        'source = { git = "https://github.com/OmniNode-ai/omnimarket.git'
        "?rev=9818ae563581c762e91968a65f6cc035bfe4b400"
        '#9818ae563581c762e91968a65f6cc035bfe4b400" }\n\n'
        "[[package]]\n"
        'name = "omnibase-core"\n'
        'version = "0.47.17"\n'
        'source = { registry = "https://pypi.org/simple" }\n',
        encoding="utf-8",
    )

    sources = gsp.parse_git_sources(lock)

    assert set(sources) == {"omnimarket"}, (
        "a registry-sourced package must not be reported as a git source"
    )
    assert sources["omnimarket"].rev == "9818ae563581c762e91968a65f6cc035bfe4b400"
    assert sources["omnimarket"].url == "https://github.com/OmniNode-ai/omnimarket.git"
    assert sources["omnimarket"].repo == "omnimarket"


# --------------------------------------------------------------------------
# ancestry classification — the whole point
# --------------------------------------------------------------------------


def test_classify_at_clone_head_is_in_sync(fixture_clone: Path) -> None:
    """AC6: installed exactly at the clone head is IN_SYNC, whatever the lock says.

    This is the live condition that stopped OMN-18746: the venv carried the
    clone head while the lock still named a rev 22 commits older.
    """
    from scripts import git_source_pins as gsp  # noqa: PLC0415

    head = _git(fixture_clone, "rev-parse", "HEAD")
    older = _git(fixture_clone, "rev-parse", "HEAD~2")

    verdict = gsp.classify(
        clone=fixture_clone, installed=head, locked=older, clone_head=head
    )

    assert verdict.state is gsp.EnumGitPinState.IN_SYNC
    assert verdict.finding is None


def test_classify_behind_clone_is_a_named_finding_not_pin_drift(
    fixture_clone: Path,
) -> None:
    """AC5: behind the clone is reported, named, and never remedied backwards."""
    from scripts import git_source_pins as gsp  # noqa: PLC0415

    head = _git(fixture_clone, "rev-parse", "HEAD")
    older = _git(fixture_clone, "rev-parse", "HEAD~2")

    verdict = gsp.classify(
        clone=fixture_clone, installed=older, locked=older, clone_head=head
    )

    assert verdict.state is gsp.EnumGitPinState.BEHIND_CLONE
    assert verdict.finding is not None
    finding = verdict.finding
    assert "pin drift" not in finding, (
        "a git source behind the clone must not borrow the registry pin-drift "
        "wording — that wording carries a remedy that would move it backwards"
    )
    assert gsp.CLONE_RECONCILER in finding, (
        "the finding must name the reconciler that owns converging this surface"
    )
    assert older[:12] in finding and head[:12] in finding


def test_classify_ahead_of_clone_is_a_finding(fixture_clone: Path) -> None:
    """Installed ahead of the clone means the clone was never advanced."""
    from scripts import git_source_pins as gsp  # noqa: PLC0415

    head = _git(fixture_clone, "rev-parse", "HEAD")
    older = _git(fixture_clone, "rev-parse", "HEAD~1")

    verdict = gsp.classify(
        clone=fixture_clone, installed=head, locked=head, clone_head=older
    )

    assert verdict.state is gsp.EnumGitPinState.AHEAD_OF_CLONE
    assert verdict.finding is not None


def test_classify_unrelated_commit_is_a_finding(
    fixture_clone: Path, tmp_path: Path
) -> None:
    """An installed commit the clone does not contain fails closed."""
    from scripts import git_source_pins as gsp  # noqa: PLC0415

    head = _git(fixture_clone, "rev-parse", "HEAD")
    absent = "0" * 40

    verdict = gsp.classify(
        clone=fixture_clone, installed=absent, locked=head, clone_head=head
    )

    assert verdict.state is gsp.EnumGitPinState.UNKNOWN
    assert verdict.finding is not None


def test_lock_behind_clone_is_reported_against_the_refresh_workflow(
    fixture_clone: Path,
) -> None:
    """AC1/AC5: the lock lagging the clone names the surface that owns re-locking.

    The venv can be exactly right while the lock is stale — that is the normal
    state in the window between an omnimarket merge and the bump PR landing.
    It is reported, and it is reported against the refresh workflow, never
    against the venv.
    """
    from scripts import git_source_pins as gsp  # noqa: PLC0415

    head = _git(fixture_clone, "rev-parse", "HEAD")
    older = _git(fixture_clone, "rev-parse", "HEAD~2")

    finding = gsp.lock_lag_finding(
        name="omnimarket", locked=older, clone_head=head, clone=fixture_clone
    )

    assert finding is not None
    assert gsp.LOCK_RELOCK_OWNER in finding
    assert gsp.CLONE_RECONCILER not in finding, (
        "re-locking is not the venv reconciler's job; naming it here sends the "
        "reader to the surface that cannot fix this"
    )


def test_lock_at_clone_head_produces_no_lag_finding(fixture_clone: Path) -> None:
    from scripts import git_source_pins as gsp  # noqa: PLC0415

    head = _git(fixture_clone, "rev-parse", "HEAD")
    assert (
        gsp.lock_lag_finding(
            name="omnimarket", locked=head, clone_head=head, clone=fixture_clone
        )
        is None
    )


# --------------------------------------------------------------------------
# forward-only re-lock
# --------------------------------------------------------------------------


def test_relock_rewrites_every_occurrence_of_the_rev(
    tmp_path: Path, fixture_clone: Path
) -> None:
    """AC1: a re-lock moves the pyproject rev to the clone head.

    The sha appears twice in omniclaude's pyproject — once in the dependency
    string and once in [tool.uv.sources]. Moving one and not the other produces
    a lock uv cannot resolve, so both must move in the same write.
    """
    from scripts import relock_git_sources as relock  # noqa: PLC0415

    head = _git(fixture_clone, "rev-parse", "HEAD")
    older = _git(fixture_clone, "rev-parse", "HEAD~2")

    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        "[project]\n"
        "name = 'x'\n"
        "dependencies = [\n"
        f'  "omnimarket @ git+https://github.com/OmniNode-ai/omnimarket.git@{older}",\n'
        "]\n\n"
        "[tool.uv.sources]\n"
        'omnimarket = { git = "https://github.com/OmniNode-ai/omnimarket.git", '
        f'rev = "{older}" }}\n',
        encoding="utf-8",
    )

    changed = relock.rewrite_rev(
        pyproject=pyproject, package="omnimarket", old_rev=older, new_rev=head
    )

    assert changed == 2, "both the dependency string and the source rev must move"
    text = pyproject.read_text(encoding="utf-8")
    assert older not in text
    assert text.count(head) == 2


def test_relock_refuses_a_non_descendant(tmp_path: Path, fixture_clone: Path) -> None:
    """AC2: the lock must never drag the venv backwards.

    A candidate that is not a strict descendant of the current rev is refused
    and nothing is written — the file is byte-identical afterwards.
    """
    from scripts import relock_git_sources as relock  # noqa: PLC0415

    head = _git(fixture_clone, "rev-parse", "HEAD")
    older = _git(fixture_clone, "rev-parse", "HEAD~2")

    pyproject = tmp_path / "pyproject.toml"
    body = (
        "[tool.uv.sources]\n"
        'omnimarket = { git = "https://github.com/OmniNode-ai/omnimarket.git", '
        f'rev = "{head}" }}\n'
    )
    pyproject.write_text(body, encoding="utf-8")

    with pytest.raises(relock.ErrorNotADescendant):
        relock.plan_rev_advance(
            clone=fixture_clone, package="omnimarket", current=head, candidate=older
        )

    assert pyproject.read_text(encoding="utf-8") == body, (
        "a refused advance must write nothing"
    )


def test_relock_plan_accepts_a_strict_descendant(fixture_clone: Path) -> None:
    from scripts import relock_git_sources as relock  # noqa: PLC0415

    head = _git(fixture_clone, "rev-parse", "HEAD")
    older = _git(fixture_clone, "rev-parse", "HEAD~2")

    plan = relock.plan_rev_advance(
        clone=fixture_clone, package="omnimarket", current=older, candidate=head
    )
    assert plan.old_rev == older
    assert plan.new_rev == head


def test_relock_plan_is_a_noop_when_already_at_head(fixture_clone: Path) -> None:
    from scripts import relock_git_sources as relock  # noqa: PLC0415

    head = _git(fixture_clone, "rev-parse", "HEAD")
    plan = relock.plan_rev_advance(
        clone=fixture_clone, package="omnimarket", current=head, candidate=head
    )
    assert plan is None


# --------------------------------------------------------------------------
# authority is DECLARED, never inferred
# --------------------------------------------------------------------------


def test_authority_is_read_from_the_declaration_not_inferred(tmp_path: Path) -> None:
    """Only a declared clone-governed source answers to the clone.

    omnimarket has an in-process guard (OMN-18675) that refuses every
    ``onex delegate`` when the installed commit differs from the canonical
    clone HEAD, so the clone really is its authority. No such guard exists for
    the other git-pinned siblings, whose revs are deliberately reviewed pins.
    Inferring clone authority from "is a git source" would drive unrequested
    bumps on a governance repo, so the authority is declared and reviewable.
    """
    from scripts import git_source_pins as gsp  # noqa: PLC0415

    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[tool.onex.git-source-authority]\nomnimarket = "clone"\n',
        encoding="utf-8",
    )

    authority = gsp.read_authority(pyproject)

    assert authority["omnimarket"] is gsp.EnumGitSourceAuthority.CLONE
    assert (
        authority.get("onex-change-control", gsp.EnumGitSourceAuthority.LOCK)
        is gsp.EnumGitSourceAuthority.LOCK
    ), "an undeclared git source defaults to lock authority, never clone"


def test_lock_governed_source_is_compared_to_the_lock_not_the_clone(
    fixture_clone: Path,
) -> None:
    """A lock-governed git source is still checked — just against the lock.

    Not silent: installed must equal the rev the lock names. What it must NOT
    do is chase the clone head, which nothing has declared as its authority.
    """
    from scripts import git_source_pins as gsp  # noqa: PLC0415

    head = _git(fixture_clone, "rev-parse", "HEAD")
    locked = _git(fixture_clone, "rev-parse", "HEAD~2")

    at_lock = gsp.classify_lock_governed(
        name="onex-change-control", installed=locked, locked=locked
    )
    assert at_lock.state is gsp.EnumGitPinState.IN_SYNC
    assert at_lock.finding is None

    off_lock = gsp.classify_lock_governed(
        name="onex-change-control", installed=head, locked=locked
    )
    assert off_lock.state is not gsp.EnumGitPinState.IN_SYNC
    assert off_lock.finding is not None
    assert "onex-change-control" in off_lock.finding


def test_the_repo_declares_omnimarket_clone_governed_and_nothing_else() -> None:
    """The live declaration in this repo is exactly the guarded package.

    A second entry here silently widens which pins the refresh workflow will
    advance, so the set is pinned by a test rather than by review.
    """
    from scripts import git_source_pins as gsp  # noqa: PLC0415

    repo_root = Path(__file__).resolve().parent.parent
    authority = gsp.read_authority(repo_root / "pyproject.toml")

    clone_governed = {
        name
        for name, value in authority.items()
        if value is gsp.EnumGitSourceAuthority.CLONE
    }
    assert clone_governed == {"omnimarket"}


# --------------------------------------------------------------------------
# the GIT_DIR trap
# --------------------------------------------------------------------------


def test_probes_ignore_an_inherited_git_dir(
    fixture_clone: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An exported GIT_DIR must not retarget the ancestry probe.

    pre-commit exports GIT_DIR and GIT_INDEX_FILE to every hook it runs, and an
    exported GIT_DIR overrides ``git -C <path>``. On this module's first
    registered pre-commit run that made the probe report that the canonical
    clone did not contain a commit which was literally its own HEAD, and the
    gate failed closed on a fiction. The same class is already recorded against
    this repo in .pre-commit-config.yaml (OMN-18434).
    """
    from scripts import git_source_pins as gsp  # noqa: PLC0415

    other = tmp_path / "unrelated"
    other.mkdir()
    _git(other, "init", "-q", "-b", "dev")
    _git(other, "config", "user.email", "t@example.invalid")
    _git(other, "config", "user.name", "t")
    (other / "x.txt").write_text("x\n", encoding="utf-8")
    _git(other, "add", "x.txt")
    _git(other, "commit", "-q", "-m", "unrelated")

    head = _git(fixture_clone, "rev-parse", "HEAD")
    older = _git(fixture_clone, "rev-parse", "HEAD~2")

    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_INDEX_FILE", str(other / ".git" / "index"))

    verdict = gsp.classify(
        clone=fixture_clone, installed=older, locked=older, clone_head=head
    )

    assert verdict.state is gsp.EnumGitPinState.BEHIND_CLONE, (
        "an inherited GIT_DIR retargeted the probe at an unrelated repository"
    )
    assert gsp.clone_head(fixture_clone) == head


# --------------------------------------------------------------------------
# the rewrite must not edit prose
# --------------------------------------------------------------------------


def test_rewrite_leaves_comment_lines_alone(
    tmp_path: Path, fixture_clone: Path
) -> None:
    """A rev named in a comment is history, not a pin.

    ``pyproject.toml`` carries a running commentary of every past bump, and
    those comments name commits. A blanket string replace would silently
    rewrite that history the moment a comment happened to name the current
    rev -- turning an accurate record of what was pinned when into a false
    one. Only the live values move.
    """
    from scripts import relock_git_sources as relock  # noqa: PLC0415

    head = _git(fixture_clone, "rev-parse", "HEAD")
    older = _git(fixture_clone, "rev-parse", "HEAD~2")

    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        f"# OMN-18639: advanced to {older}, the v0.4.114 release commit.\n"
        "[tool.uv.sources]\n"
        'omnimarket = { git = "https://github.com/OmniNode-ai/omnimarket.git", '
        f'rev = "{older}" }}\n',
        encoding="utf-8",
    )

    changed = relock.rewrite_rev(
        pyproject=pyproject, package="omnimarket", old_rev=older, new_rev=head
    )

    text = pyproject.read_text(encoding="utf-8")
    assert changed == 1, "only the live rev should have moved"
    assert f"# OMN-18639: advanced to {older}" in text, (
        "the historical comment was rewritten; that record is now false"
    )
    assert f'rev = "{head}"' in text


def test_rewrite_refuses_when_the_rev_appears_only_in_comments(
    tmp_path: Path, fixture_clone: Path
) -> None:
    """Nothing live to move is a refusal, not a silent success."""
    from scripts import relock_git_sources as relock  # noqa: PLC0415

    head = _git(fixture_clone, "rev-parse", "HEAD")
    older = _git(fixture_clone, "rev-parse", "HEAD~2")

    pyproject = tmp_path / "pyproject.toml"
    body = f"# historical note naming {older}\n[tool.uv.sources]\n"
    pyproject.write_text(body, encoding="utf-8")

    with pytest.raises(relock.ErrorRevNotFound):
        relock.rewrite_rev(
            pyproject=pyproject, package="omnimarket", old_rev=older, new_rev=head
        )
    assert pyproject.read_text(encoding="utf-8") == body


# --------------------------------------------------------------------------
# the lag is reported, and it does not block
# --------------------------------------------------------------------------


def test_lock_lag_is_reported_as_a_note_not_a_blocking_finding(
    fixture_clone: Path,
) -> None:
    """The lock lagging the clone is stated, owned, and does not fail the gate.

    Measured on the operator Mac 2026-09-18: omnimarket published five
    releases in three hours. omnimarket is release-on-merge, so the interval
    in which this repo's lock equals the canonical clone head is the interval
    between one merge and the next — minutes. A blocking finding here would
    leave the gate red on a developer host essentially always, on a condition
    the person committing cannot fix and a scheduled workflow closes on its
    own. That is a gate people learn to ignore, which is rule 5's failure
    approached from the other side.

    What must never happen is silence. The lag is always reported, with the
    workflow that owns it and the command to run now, so the difference
    between "lagging, known, owned" and "nobody is looking" stays visible.

    The findings that DO block are unchanged and are the ones that actually
    break something: a venv whose git source disagrees with the clone means
    the OMN-18675 guard refuses every `onex delegate` on that interpreter.
    """
    from scripts import git_source_pins as gsp  # noqa: PLC0415

    head = _git(fixture_clone, "rev-parse", "HEAD")
    older = _git(fixture_clone, "rev-parse", "HEAD~2")

    note = gsp.lock_lag_finding(
        name="omnimarket", locked=older, clone_head=head, clone=fixture_clone
    )
    assert note is not None, "the lag must still be stated"
    assert gsp.LOCK_RELOCK_OWNER in note

    assert gsp.lock_lag_blocks() is False, (
        "the lock lag must not fail the gate: it is unactionable by the "
        "committer and a scheduled owner closes it"
    )


def test_a_venv_behind_the_clone_still_blocks(fixture_clone: Path) -> None:
    """The teeth stay where the breakage is."""
    from scripts import git_source_pins as gsp  # noqa: PLC0415

    head = _git(fixture_clone, "rev-parse", "HEAD")
    older = _git(fixture_clone, "rev-parse", "HEAD~2")

    verdict = gsp.classify(
        clone=fixture_clone, installed=older, locked=older, clone_head=head
    )
    assert verdict.state is gsp.EnumGitPinState.BEHIND_CLONE
    assert verdict.finding is not None
