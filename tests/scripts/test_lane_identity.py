# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for OMN-18260 — lane identity stamped into commit trailers.

Problem (fact, measured 2026-09-13). Zero commits carry a lane trailer across
the last 200 commits of each of three worked repositories, while the same window
carries `Co-authored-by:`, `Ticket:` and `Evidence-Ticket:` trailers. The
mechanism works and is simply unused. Every lane pushes under one account, so
neither authorship nor branch name says which lane produced a commit -- which is
why the 14:17Z cross-lane push on 2026-09-12 was invisible until a person
noticed.

Design of record: `beta/plans/2026-09-13-lane-identity-and-claim-index-design.md`
in knowledge-base-internal (OMN-18259), sections 3 and 9.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from omnibase_core.validators.no_unguarded_git_subprocess import (
    scrub_git_location_env,
)

from scripts import lane_identity as li


@pytest.fixture
def base(tmp_path: Path) -> Path:
    root = tmp_path / "state"
    root.mkdir()
    return root


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    wt = tmp_path / "worktrees" / "OMN-1" / "repo"
    wt.mkdir(parents=True)
    return wt


# ---------------------------------------------------------------------------
# The identifier's shape
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "lane",
    ["friction-p5", "c7-chain-realkey-rerun", "a", "lane-with-9-digits-2"],
)
def test_valid_lane_slugs_are_accepted(lane: str) -> None:
    assert li.valid_lane(lane)


@pytest.mark.parametrize(
    "lane",
    [
        "",
        "Friction-P5",
        "has space",
        "trailing-",
        "-leading",
        "has_underscore",
        "a" * 65,
    ],
)
def test_invalid_lane_slugs_are_rejected(lane: str) -> None:
    """The slug is the vocabulary the ledger already uses. A trailer that can
    hold anything cannot be compared against a claim row."""
    assert not li.valid_lane(lane)


# ---------------------------------------------------------------------------
# Registration and resolution
# ---------------------------------------------------------------------------


def test_register_then_resolve_round_trips(base: Path, worktree: Path) -> None:
    record = li.register(base, worktree, lane="friction-p5", ticket="OMN-18260")
    resolved = li.resolve(base, worktree)
    assert resolved is not None
    assert resolved.lane == "friction-p5"
    assert resolved.ticket == "OMN-18260"
    assert resolved.session_id == record.session_id
    assert resolved.session_id


def test_an_unregistered_worktree_resolves_to_nothing(
    base: Path, worktree: Path
) -> None:
    assert li.resolve(base, worktree) is None


def test_registration_is_keyed_by_resolved_path_not_by_spelling(
    base: Path, worktree: Path
) -> None:
    """Two spellings of one directory are one lane. Otherwise a lane invoked
    through a symlink or a trailing slash registers twice and resolves to
    neither."""
    li.register(base, worktree, lane="friction-p5", ticket="OMN-18260")
    same = Path(str(worktree) + "/")
    assert li.resolve(base, same) is not None
    nested = worktree / "src"
    nested.mkdir()
    assert li.resolve(base, nested) is not None, (
        "a subdirectory resolves to its worktree"
    )


def test_two_worktrees_hold_two_identities(base: Path, tmp_path: Path) -> None:
    a = tmp_path / "wt-a"
    b = tmp_path / "wt-b"
    a.mkdir()
    b.mkdir()
    li.register(base, a, lane="lane-a", ticket="OMN-1")
    li.register(base, b, lane="lane-b", ticket="OMN-2")
    ra, rb = li.resolve(base, a), li.resolve(base, b)
    assert ra is not None and rb is not None
    assert (ra.lane, rb.lane) == ("lane-a", "lane-b")
    assert ra.session_id != rb.session_id, (
        "distinct sessions must differ -- OMN-17005's D3 is exactly what happens "
        "when every lane resolves to one shared constant"
    )


def test_re_registering_the_same_worktree_replaces_the_record(
    base: Path, worktree: Path
) -> None:
    li.register(base, worktree, lane="lane-a", ticket="OMN-1")
    li.register(base, worktree, lane="lane-b", ticket="OMN-2")
    resolved = li.resolve(base, worktree)
    assert resolved is not None and resolved.lane == "lane-b"


def test_register_rejects_a_malformed_lane(base: Path, worktree: Path) -> None:
    with pytest.raises(ValueError):
        li.register(base, worktree, lane="Not A Slug", ticket="OMN-1")


def test_register_rejects_a_malformed_ticket(base: Path, worktree: Path) -> None:
    with pytest.raises(ValueError):
        li.register(base, worktree, lane="lane-a", ticket="not-a-ticket")


def test_a_corrupt_registry_entry_resolves_to_nothing_rather_than_crashing(
    base: Path, worktree: Path
) -> None:
    """An unreadable record must read as unregistered, so the commit is refused
    and the lane re-registers. It must never read as a successful resolution of
    a partial record."""
    li.register(base, worktree, lane="lane-a", ticket="OMN-1")
    path = li.record_path(base, worktree)
    path.write_text("{not json", encoding="utf-8")
    assert li.resolve(base, worktree) is None
    path.write_text(json.dumps({"lane": "lane-a"}), encoding="utf-8")
    assert li.resolve(base, worktree) is None, (
        "a record missing a session is not a resolution"
    )


# ---------------------------------------------------------------------------
# Trailers
# ---------------------------------------------------------------------------


def test_trailers_name_the_lane_and_the_session(base: Path, worktree: Path) -> None:
    li.register(base, worktree, lane="friction-p5", ticket="OMN-18260")
    lines = li.trailer_lines(base, worktree)
    assert lines[0].startswith("Onex-Lane: friction-p5")
    assert lines[1].startswith("Onex-Session: ")
    assert len(lines) == 2


def test_trailers_refuse_an_unregistered_worktree(base: Path, worktree: Path) -> None:
    with pytest.raises(li.UnregisteredLane):
        li.trailer_lines(base, worktree)


def test_apply_trailers_appends_once_and_is_idempotent(
    base: Path, worktree: Path
) -> None:
    """A commit amended or reworded twice must not accumulate trailers, and a
    second run must not contradict the first."""
    li.register(base, worktree, lane="friction-p5", ticket="OMN-18260")
    message = "feat(OMN-18260): subject\n\nbody text\n"
    once = li.apply_trailers(message, li.trailer_lines(base, worktree))
    twice = li.apply_trailers(once, li.trailer_lines(base, worktree))
    assert once == twice
    assert once.count("Onex-Lane:") == 1


def test_apply_trailers_keeps_existing_trailers(base: Path, worktree: Path) -> None:
    li.register(base, worktree, lane="friction-p5", ticket="OMN-18260")
    message = "feat(OMN-18260): subject\n\nbody\n\nCo-authored-by: someone <a@b.c>\n"
    out = li.apply_trailers(message, li.trailer_lines(base, worktree))
    assert "Co-authored-by: someone <a@b.c>" in out
    assert "Onex-Lane: friction-p5" in out


def test_apply_trailers_ignores_comment_lines(base: Path, worktree: Path) -> None:
    """git's commit template is full of `#` lines. A trailer appended after them
    is not a trailer."""
    li.register(base, worktree, lane="friction-p5", ticket="OMN-18260")
    message = "subject\n\nbody\n\n# Please enter the commit message\n# with '#' will be ignored\n"
    out = li.apply_trailers(message, li.trailer_lines(base, worktree))
    body, _, comments = out.partition("# Please enter")
    assert "Onex-Lane: friction-p5" in body
    assert "Onex-Lane" not in comments


# ---------------------------------------------------------------------------
# Reading the trailers back off a commit
# ---------------------------------------------------------------------------


def test_commit_identity_reads_a_stamped_message() -> None:
    message = "feat: x\n\nbody\n\nOnex-Lane: friction-p5\nOnex-Session: 01J0ABCDEF\n"
    ident = li.commit_identity(message)
    assert ident is not None
    assert ident == ("friction-p5", "01J0ABCDEF")


def test_commit_identity_is_none_on_an_unstamped_message() -> None:
    assert li.commit_identity("feat: x\n\nbody\n") is None


def test_commit_identity_rejects_a_malformed_lane_value() -> None:
    """A trailer that is present but not a valid slug is not a resolution. It
    fails the check the same as an absent one, because a lane identifier that
    cannot be compared to a claim row is not an identifier."""
    message = "feat: x\n\nOnex-Lane: Not A Slug\nOnex-Session: abc\n"
    assert li.commit_identity(message) is None


def test_commit_identity_ignores_a_mention_in_the_body() -> None:
    """Rule 15: prose that merely spells a trigger must not satisfy a gate. The
    trailer is read as a trailer, at the end of the message, not searched for."""
    message = (
        "feat: x\n\nThis commit adds Onex-Lane: friction-p5 to the hook.\n\nreal body\n"
    )
    assert li.commit_identity(message) is None


# ---------------------------------------------------------------------------
# The window check over real commits -- phase 5 AC3
# ---------------------------------------------------------------------------


def _clean_env(**extra: str) -> dict[str, str]:
    """The ambient environment with every GIT_* variable removed.

    These tests drive real `git commit` calls in throwaway repositories. When
    the suite itself runs inside a pre-commit hook, git exports GIT_INDEX_FILE
    and friends for its own staging, and an inherited GIT_INDEX_FILE points a
    fresh repository commit at the OUTER repository index. The tests then fail
    for a reason that has nothing to do with what they assert, which is exactly
    how a green suite becomes a red gate on an unrelated commit.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(extra)
    return env


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=scrub_git_location_env(_clean_env()),
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    # Prove the fixture is isolated before anything depends on it. Under a real
    # `git commit`, git exports repository state into the environment, and a
    # throwaway repository that silently resolved to the OUTER one turned every
    # window-check assertion into a confusing comparison against this
    # repository own history. An explicit check fails at the cause instead.
    toplevel = _git(r, "rev-parse", "--show-toplevel")
    assert Path(toplevel).resolve() == r.resolve(), (
        f"the throwaway repository resolved to {toplevel}, not {r}"
    )
    _git(r, "config", "user.email", "t@example.com")
    _git(r, "config", "user.name", "t")
    (r / "a.txt").write_text("a", encoding="utf-8")
    _git(r, "add", "a.txt")
    _git(r, "commit", "-q", "-m", "first\n\nOnex-Lane: lane-a\nOnex-Session: s1\n")
    return r


def test_window_check_passes_when_every_commit_is_stamped(repo: Path) -> None:
    for name in ("b.txt", "c.txt"):
        (repo / name).write_text(name, encoding="utf-8")
        _git(repo, "add", name)
        _git(
            repo,
            "commit",
            "-q",
            "-m",
            f"{name}\n\nOnex-Lane: lane-a\nOnex-Session: s1\n",
        )
    unstamped = li.unstamped_commits(repo, "HEAD~2..HEAD")
    assert unstamped == []


def test_window_check_names_an_unstamped_commit(repo: Path) -> None:
    """The red case the acceptance criterion names: a commit lacking a lane
    identifier fails the check, and the check says which one."""
    (repo / "c.txt").write_text("c", encoding="utf-8")
    _git(repo, "add", "c.txt")
    _git(repo, "commit", "-q", "-m", "unstamped second commit")
    unstamped = li.unstamped_commits(repo, "HEAD~1..HEAD")
    assert len(unstamped) == 1
    sha, subject = unstamped[0]
    assert subject == "unstamped second commit"
    assert len(sha) == 40


def test_window_check_positive_control_finds_rows_on_an_all_unstamped_range(
    repo: Path,
) -> None:
    """A zero from this check is only evidence if the same check returns rows on
    an input known to have them (CLAUDE.md rule 16)."""
    for name in ("d.txt", "e.txt"):
        (repo / name).write_text(name, encoding="utf-8")
        _git(repo, "add", name)
        _git(repo, "commit", "-q", "-m", f"unstamped {name}")
    assert len(li.unstamped_commits(repo, "HEAD~2..HEAD")) == 2


def test_merge_commits_are_exempt(repo: Path) -> None:
    """A merge commit is written by git, not by a lane, and refusing it would
    make the check fire on the correct behaviour."""
    _git(repo, "checkout", "-q", "-b", "side")
    (repo / "s.txt").write_text("s", encoding="utf-8")
    _git(repo, "add", "s.txt")
    _git(repo, "commit", "-q", "-m", "side\n\nOnex-Lane: lane-b\nOnex-Session: s2\n")
    _git(repo, "checkout", "-q", "main")
    (repo / "m.txt").write_text("m", encoding="utf-8")
    _git(repo, "add", "m.txt")
    _git(repo, "commit", "-q", "-m", "main\n\nOnex-Lane: lane-a\nOnex-Session: s1\n")
    _git(repo, "merge", "-q", "--no-ff", "side", "-m", "merge side")
    assert li.unstamped_commits(repo, "HEAD~2..HEAD") == []


# ---------------------------------------------------------------------------
# The hook that does the stamping
# ---------------------------------------------------------------------------


HOOK = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "hooks"
    / "prepare-commit-msg-lane"
)


def test_the_hook_script_exists_and_is_executable() -> None:
    assert HOOK.is_file(), f"{HOOK} missing"
    assert HOOK.stat().st_mode & 0o111, (
        "the hook must be executable or git silently skips it"
    )


def test_the_hook_stamps_a_registered_worktree(
    base: Path, repo: Path, tmp_path: Path
) -> None:
    li.register(base, repo, lane="lane-h", ticket="OMN-18260")
    message = tmp_path / "COMMIT_EDITMSG"
    message.write_text("feat(OMN-18260): hooked\n", encoding="utf-8")
    result = subprocess.run(  # noqa: PLW1510 - the return code IS the assertion
        [str(HOOK), str(message)],
        cwd=repo,
        env=_clean_env(ONEX_LANE_REGISTRY_ROOT=str(base)),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "Onex-Lane: lane-h" in message.read_text(encoding="utf-8")


def _run_hook(repo: Path, base: Path, message: Path) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: PLW1510 - the return code IS the assertion
        [str(HOOK), str(message)],
        cwd=repo,
        env=_clean_env(ONEX_LANE_REGISTRY_ROOT=str(base)),
        capture_output=True,
        text=True,
    )


def test_the_hook_never_stamps_an_unregistered_worktree(
    repo: Path, base: Path, tmp_path: Path
) -> None:
    """It never stamps an `unknown` lane. A trailer that can be wrong is worse
    than one that is absent, because the check downstream cannot tell the two
    apart.

    Under the DEFAULT policy it allows the commit (OMN-18273). Refusing by
    default would freeze every worktree that predates the mechanism, and the
    pre-push refusal already reports-and-allows an unstamped commit by its own
    documented design, so the absent trailer costs the downstream gate nothing.
    """
    message = tmp_path / "COMMIT_EDITMSG"
    message.write_text("feat(OMN-18260): hooked\n", encoding="utf-8")
    result = _run_hook(repo, base, message)
    assert result.returncode == 0, result.stderr
    assert "Onex-Lane" not in message.read_text(encoding="utf-8")


def test_the_hook_refuses_an_unregistered_worktree_once_armed(
    repo: Path, base: Path, tmp_path: Path
) -> None:
    """The design's refusal, kept, and reachable by one explicit verb -- the
    sequencing question OMN-18259 section 7 left open for the operator. The
    refusal prints the registration command, so it costs one command rather than
    a search."""
    li.set_unregistered_mode(base, "refuse")
    message = tmp_path / "COMMIT_EDITMSG"
    message.write_text("feat(OMN-18260): hooked\n", encoding="utf-8")
    result = _run_hook(repo, base, message)
    assert result.returncode != 0
    assert "lane_identity.py register" in result.stderr
    assert "Onex-Lane" not in message.read_text(encoding="utf-8")


def test_the_hook_leaves_a_merge_message_alone(
    base: Path, repo: Path, tmp_path: Path
) -> None:
    li.register(base, repo, lane="lane-h", ticket="OMN-18260")
    message = tmp_path / "MERGE_MSG"
    message.write_text("Merge branch 'side'\n", encoding="utf-8")
    result = subprocess.run(  # noqa: PLW1510 - the return code IS the assertion
        [str(HOOK), str(message), "merge"],
        cwd=repo,
        env=_clean_env(ONEX_LANE_REGISTRY_ROOT=str(base)),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "Onex-Lane" not in message.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Registry root resolution: fail fast, never a silent default
# ---------------------------------------------------------------------------


def test_registry_root_fails_fast_when_nothing_declares_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ONEX_LANE_REGISTRY_ROOT", raising=False)
    monkeypatch.delenv("OMNI_HOME", raising=False)
    with pytest.raises(KeyError):
        li.registry_root_from_env()


def test_registry_root_prefers_the_explicit_variable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OMNI_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ONEX_LANE_REGISTRY_ROOT", str(tmp_path / "explicit"))
    assert li.registry_root_from_env() == tmp_path / "explicit"


# ---------------------------------------------------------------------------
# Installation: the installed copy must not depend on the environment
# ---------------------------------------------------------------------------


def test_installer_bakes_the_module_path_into_the_installed_hook(
    repo: Path, base: Path, tmp_path: Path
) -> None:
    """A hook copied into .git/hooks sits beside no source tree. Discovering its
    own module from the environment at commit time is the shape that fails
    silently on the one box that does not export the workspace variable -- it
    was caught here by running a real `git commit` rather than by reading the
    script. The installer therefore writes the resolved path in.
    """
    assert li.main(["install-hook", "--repo", str(repo)]) == 0
    installed = repo / ".git" / "hooks" / "prepare-commit-msg"
    body = installed.read_text(encoding="utf-8")
    assert (
        "@LANE_IDENTITY_PATH@"
        not in body.split("INSTALLED_LANE_IDENTITY=")[1].splitlines()[0]
    )
    assert str(Path(li.__file__).resolve()) in body
    assert installed.stat().st_mode & 0o111

    li.register(base, repo, lane="lane-i", ticket="OMN-18260")
    (repo / "installed.txt").write_text("x", encoding="utf-8")
    _git(repo, "add", "installed.txt")
    env = {
        "PATH": os.environ["PATH"],
        "ONEX_LANE_REGISTRY_ROOT": str(base),
        "HOME": str(tmp_path),
    }
    result = subprocess.run(  # noqa: PLW1510 - the return code IS the assertion
        ["git", "commit", "-m", "feat(OMN-18260): through the installed hook"],
        cwd=repo,
        env=scrub_git_location_env(env),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    message = _git(repo, "log", "-1", "--format=%B")
    assert "Onex-Lane: lane-i" in message
    assert li.commit_identity(message + "\n") is not None


def test_an_unresolvable_range_is_an_error_not_an_empty_result(repo: Path) -> None:
    """A range git cannot resolve returns no commits, which reads exactly like
    "every commit is stamped". A zero that is not evidence of absence is the
    failure CLAUDE.md rule 16 exists for, and it was found by running the check
    with a bad range against a one-commit repository."""
    with pytest.raises(li.BadRange):
        li.unstamped_commits(repo, "HEAD~5..HEAD")
    assert li.main(["verify", "--repo", str(repo), "--range", "HEAD~5..HEAD"]) == 2


def test_the_hook_refuses_when_no_new_enough_interpreter_is_available(
    base: Path, repo: Path, tmp_path: Path
) -> None:
    """A git hook runs with whatever PATH git happens to have, which on macOS is
    frequently the system python 3.9. A bare `python3` produced an ImportError
    traceback and refused a commit on a correctly registered worktree -- found
    by running a real `git commit`, not by reading either file.

    The hook now picks the first candidate new enough and refuses with a message
    naming the requirement when none is. It never falls through to stamping
    nothing: a commit silently carrying no lane trailer is exactly what the
    downstream refusal cannot tell from a wrong one.
    """
    li.register(base, repo, lane="lane-old", ticket="OMN-18260")
    # A PATH carrying the shell the hook is written in, and nothing else -- so
    # the only thing missing is a usable interpreter.
    empty_path = tmp_path / "bin"
    empty_path.mkdir()
    for tool in ("bash", "command", "cat", "uname"):
        found = shutil.which(tool)
        if found:
            (empty_path / tool).symlink_to(found)
    message = tmp_path / "COMMIT_EDITMSG"
    message.write_text("feat(OMN-18260): hooked\n", encoding="utf-8")
    result = subprocess.run(  # noqa: PLW1510 - the return code IS the assertion
        [str(HOOK), str(message)],
        cwd=repo,
        env=_clean_env(
            PATH=str(empty_path),
            ONEX_LANE_REGISTRY_ROOT=str(base),
            ONEX_LANE_IDENTITY_SCRIPT=str(Path(li.__file__).resolve()),
        ),
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "3.11 or newer" in result.stderr
    assert "ONEX_LANE_PYTHON" in result.stderr
    assert "Onex-Lane" not in message.read_text(encoding="utf-8")


def test_the_window_check_ignores_an_inherited_git_dir(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Git exports GIT_DIR to the hooks it runs, frequently as the relative
    string ".git". A `git log` launched from inside a hook then reads the hook
    owner repository whatever directory it is pointed at, so the check answered
    about the wrong repository and reported its commits as findings. Found by
    running the check inside a real `git commit`, not beside one.
    """
    monkeypatch.setenv("GIT_DIR", ".git")
    monkeypatch.setenv("GIT_INDEX_FILE", ".git/index")
    (repo / "z.txt").write_text("z", encoding="utf-8")
    _git(repo, "add", "z.txt")
    _git(repo, "commit", "-q", "-m", "unstamped under an inherited GIT_DIR")
    findings = li.unstamped_commits(repo, "HEAD~1..HEAD")
    assert len(findings) == 1
    assert findings[0][1] == "unstamped under an inherited GIT_DIR"


def test_installer_never_writes_into_a_shared_hooks_directory(
    repo: Path, tmp_path: Path
) -> None:
    """A clone can point core.hooksPath at a directory SHARED by several
    repositories. Installing a commit-refusing hook there arms every one of
    them. That is not hypothetical: during OMN-18260, an inherited GIT_DIR
    pointed the installer at exactly such a directory and every canonical clone
    in the workspace began refusing commits until the file was removed by hand.

    OMN-18273 keeps that refusal and moves where it bites. The installer now
    resolves its target structurally, as `<git-common-dir>/hooks`, so the shared
    directory is never a candidate at all -- and it reports the install as NOT
    REACHABLE (exit 4) rather than pretending it worked, because on a clone with
    an overridden hooksPath git will not dispatch the file until the shared
    directory carries a chaining entry of the same name.

    The previous revision of this test asserted exit 2 and no install anywhere,
    which is what made the mechanism uninstallable on the real workspace: every
    canonical clone there sets core.hooksPath, so `install-hook` refused all of
    them and the whole phase sat inert with four tickets marked Done.
    """
    shared = tmp_path / "shared-hooks"
    shared.mkdir()
    _git(repo, "config", "core.hooksPath", str(shared))

    assert li.main(["install-hook", "--repo", str(repo)]) == 4
    assert not (shared / "prepare-commit-msg").exists()
    assert (repo / ".git" / "hooks" / "prepare-commit-msg").is_file()


def test_installer_reports_reachable_once_the_shared_directory_dispatches(
    repo: Path, tmp_path: Path
) -> None:
    """The other half of the same fact: with a dispatch entry present, the
    install is reachable and exits 0. Without this control the exit-4 assertion
    above would also be satisfied by an installer that can never succeed."""
    shared = tmp_path / "shared-hooks"
    shared.mkdir()
    entry = shared / "prepare-commit-msg"
    entry.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    entry.chmod(0o755)
    _git(repo, "config", "core.hooksPath", str(shared))

    assert li.main(["install-hook", "--repo", str(repo)]) == 0


def test_installer_preserves_a_prior_hook_and_chains_to_it(
    repo: Path, base: Path
) -> None:
    """Every canonical clone in this registry already carries a pre-commit
    framework `pre-push`, and the shipped installer wrote over its target
    unconditionally. Installing must move a foreign hook aside, keep it
    executable, and leave the installed hook chaining to it -- the governed
    test selector is exactly the gate that would have been removed."""
    hooks = repo / ".git" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    prior = hooks / "prepare-commit-msg"
    prior.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    prior.chmod(0o755)

    assert li.main(["install-hook", "--repo", str(repo)]) == 0
    preserved = hooks / f"prepare-commit-msg{li.PRIOR_SUFFIX}"
    assert preserved.is_file()
    assert preserved.stat().st_mode & 0o111
    assert li.OURS_MARKER in (hooks / "prepare-commit-msg").read_text(encoding="utf-8")
    assert li.PRIOR_SUFFIX in (hooks / "prepare-commit-msg").read_text(encoding="utf-8")

    # Re-installing must not overwrite the preserved original with our own copy.
    assert li.main(["install-hook", "--repo", str(repo)]) == 0
    assert li.OURS_MARKER not in preserved.read_text(encoding="utf-8")


def test_status_reports_an_unarmed_clone_nonzero(repo: Path, base: Path) -> None:
    """The canary the design's part 2 demands: a gate that cannot see its own
    state is not a gate. An unarmed clone must be a nonzero exit, not silence --
    silence is precisely how four Done tickets stayed inert for three days."""
    assert li.main(["--registry-root", str(base), "status", "--repo", str(repo)]) == 1
    assert li.main(["install-hook", "--repo", str(repo)]) == 0
    assert li.main(["--registry-root", str(base), "status", "--repo", str(repo)]) == 0


def test_status_refuses_to_pass_an_empty_sweep(base: Path, tmp_path: Path) -> None:
    """CLAUDE.md rule 16: an empty result is not evidence of absence. A status
    run that checked no clone must not report every clone armed."""
    assert (
        li.main(
            ["--registry-root", str(base), "status", "--repo", str(tmp_path / "nope")]
        )
        == 2
    )


def test_unregistered_policy_defaults_to_silent_and_is_armed_explicitly(
    base: Path,
) -> None:
    assert li.unregistered_mode(base) == "silent"
    li.set_unregistered_mode(base, "refuse")
    assert li.unregistered_mode(base) == "refuse"
    li.set_unregistered_mode(base, "silent")
    assert li.unregistered_mode(base) == "silent"
