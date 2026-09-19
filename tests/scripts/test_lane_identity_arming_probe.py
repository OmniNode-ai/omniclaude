# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for OMN-18288 acceptance criterion (c) — the per-clone arming readback.

WHAT THE CRITERION ASKS FOR, in its own words: "a readback after installation
proves zero canonical clones refuse a commit from a registered worktree — run a
real commit (or dry-run equivalent) in each clone/worktree pair post-install and
record the result per clone, not a single spot check."

WHY A SPOT CHECK IS NOT ENOUGH, which is the whole reason this is a subcommand
rather than one shell line. Three independent things have to be right for a
clone to let a registered lane commit, and each of them is per-something: the
hook file is installed PER CLONE, the shared guard's dispatch entry is PER HOOK
TYPE, and the registration is PER WORKTREE. Every one of those can be correct
in one clone and wrong in the next, so a clone answering correctly is evidence
about that clone and nothing else. OMN-18273 is the measured precedent: the
mechanism was merged, Done, and inert in all twenty-six clones at once, for
three days, because two of those three were wrong.

WHY THE PROBE DRIVES THE INSTALLED BYTES rather than importing the module. The
refusal path this criterion is about lives in the shell file — the baked-in
module path, the interpreter search, the chained prior hook — and none of it is
reached by importing `lane_identity`. Every test that only read the script
passed throughout the three inert days.

RED/GREEN. The first three tests below are the direction that matters: a clone
that refuses a registered worktree, and a clone whose hook allows the commit
while stamping nothing, both have to come back as defects with a nonzero exit.
An `ALLOWED` that stamped nothing is an inert hook, and an inert hook is
indistinguishable from an absent one to the refusal downstream — which is why
it is graded as a refusal here rather than a pass with a note.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from omnibase_core.validators.no_unguarded_git_subprocess import (
    scrub_git_location_env,
)

from scripts import lane_identity as li


def _clean_env(**extra: str) -> dict[str, str]:
    """The ambient environment with every GIT_* variable removed.

    Same reason as the sibling suite: when this runs inside a pre-commit hook,
    an inherited GIT_INDEX_FILE points a throwaway repository's commit at the
    OUTER repository's index, and the test then fails for a reason unrelated to
    what it asserts.
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
def base(tmp_path: Path) -> Path:
    root = tmp_path / "state"
    root.mkdir()
    return root


@pytest.fixture
def clone(tmp_path: Path, lane_registry_root: Path) -> Path:
    """A throwaway clone with the stamping hook installed, as a lane's box has.

    Placed inside `lane_registry_root`, which is what makes the install legal:
    since OMN-18800 the arming verb writes only the registry's own canonical
    module path into a hook, so a test that arms anything has to name the
    registry it is arming.
    """
    c = lane_registry_root / "clones" / "repo"
    c.mkdir(parents=True)
    _git(c, "init", "-q", "-b", "main")
    toplevel = _git(c, "rev-parse", "--show-toplevel")
    assert Path(toplevel).resolve() == c.resolve(), (
        f"the throwaway clone resolved to {toplevel}, not {c}"
    )
    _git(c, "config", "user.email", "t@example.com")
    _git(c, "config", "user.name", "t")
    (c / "a.txt").write_text("a", encoding="utf-8")
    _git(c, "add", "a.txt")
    _git(c, "commit", "-q", "-m", "first")
    assert li.main(["install-hook", "--repo", str(c)]) == 0
    return c


@pytest.fixture
def lane_worktree(clone: Path) -> Path:
    """A second working tree of the same clone, which is where a lane works.

    Kept distinct from the clone root on purpose: CLAUDE.md rule 9 says lanes
    commit in worktrees and never in the canonical clone, so the two probe
    cases -- a registered worktree and an unregistered clone root -- are the
    real pair a sweep meets on this host.
    """
    wt = clone.parent / "lane-worktree"
    _git(clone, "worktree", "add", "-q", "-b", "lane", str(wt))
    return wt


def _probe(base: Path, clone: Path) -> list[li.ProbeResult]:
    return li.probe_clone(base, clone)


def _make_the_clone_refuse(clone: Path) -> None:
    """Make this clone refuse every commit, through a SHIPPED refusal path.

    The installed hook's last act is `exec`-ing the prior hook it moved aside,
    deliberately, so a pre-existing gate keeps its exit status rather than
    being swallowed. A clone carrying a refusing prior hook therefore refuses
    every commit including a registered lane's -- which is the 2026-09-13
    incident class exactly: a hook arrangement that refuses commits from
    worktrees that did nothing wrong.

    Simulated this way rather than by breaking the module path: the hook
    resolves its module from four candidates, the last of which is the
    workspace copy, so deleting one of them proves nothing on a box that has
    the workspace.
    """
    prior = clone / ".git" / "hooks" / f"prepare-commit-msg{li.PRIOR_SUFFIX}"
    prior.write_text(
        "#!/usr/bin/env bash\necho 'prior hook refuses' >&2\nexit 1\n",
        encoding="utf-8",
    )
    prior.chmod(0o755)


def _by_case(results: list[li.ProbeResult], prefix: str) -> li.ProbeResult:
    matches = [r for r in results if r.case.startswith(prefix)]
    assert len(matches) == 1, f"expected exactly one {prefix!r} row, got {matches}"
    return matches[0]


# ---------------------------------------------------------------------------
# The passing direction
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_an_armed_clone_allows_and_stamps_a_registered_worktree(
    base: Path, clone: Path, lane_worktree: Path
) -> None:
    """The criterion's own sentence, as an assertion: a registered worktree's
    commit is allowed, and the trailer naming that lane is actually written.

    Allowed alone is not the property. A hook that allows everything and stamps
    nothing satisfies "does not refuse" while leaving every downstream gate
    without its operand, which is the state the whole phase exists to leave.
    """
    li.register(base, lane_worktree, lane="lane-probe", ticket="OMN-18288")
    row = _by_case(_probe(base, clone), "registered")
    assert row.outcome == li.PROBE_ALLOWED, row.detail
    assert row.stamped is True
    assert "lane-probe" in row.detail
    assert li.probe_refusals(_probe(base, clone), base) == []


@pytest.mark.unit
def test_the_probe_writes_nothing_into_the_working_tree(
    base: Path, clone: Path, lane_worktree: Path
) -> None:
    """The probe sweeps clones whose worktrees belong to OTHER live lanes.

    A scratch file appearing in a peer's `git status`, even for the length of
    one subprocess, is the probe manufacturing the interference it exists to
    audit for. The message file therefore lives in a temporary directory and
    only the working DIRECTORY is the worktree.
    """
    li.register(base, lane_worktree, lane="lane-probe", ticket="OMN-18288")
    before = _git(lane_worktree, "status", "--porcelain")
    _probe(base, clone)
    assert _git(lane_worktree, "status", "--porcelain") == before
    assert not list(lane_worktree.glob("*COMMIT_EDITMSG*"))
    assert not list(clone.glob("*COMMIT_EDITMSG*"))


@pytest.mark.unit
def test_a_clone_with_no_live_registration_is_still_probed_and_labelled(
    base: Path, clone: Path
) -> None:
    """Most clones hold no live lane at any given moment, and reporting those
    as unprobed would answer the criterion for some clones and not the rest.

    The registered path is exercised against a registration the probe makes for
    itself in a throwaway registry, and the row says `registered-synthetic` so
    it is never read as a live lane's evidence. The identity is synthetic; the
    code path is the same one.
    """
    row = _by_case(_probe(base, clone), "registered")
    assert row.case == "registered-synthetic"
    assert row.outcome == li.PROBE_ALLOWED, row.detail
    assert row.stamped is True
    # And it left no trace in the real registry.
    assert li.resolve(base, clone) is None


# ---------------------------------------------------------------------------
# The failing direction — the half that makes the probe worth running
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_a_clone_that_refuses_a_registered_worktree_is_a_refusal(
    base: Path, clone: Path, lane_worktree: Path
) -> None:
    """The 2026-09-13 incident class, reproduced: a clone whose installed hook
    refuses a commit it should have allowed.

    Reproduced through a shipped refusal path (the chained prior hook) rather
    than by editing the assertion, so this stays a test of the mechanism.
    """
    li.register(base, lane_worktree, lane="lane-probe", ticket="OMN-18288")
    _make_the_clone_refuse(clone)
    results = _probe(base, clone)
    row = _by_case(results, "registered")
    assert row.outcome == li.PROBE_REFUSED, row.detail
    assert li.probe_refusals(results, base), "a refusal must be graded as a defect"


@pytest.mark.unit
def test_a_hook_that_allows_but_stamps_nothing_is_a_refusal_not_a_pass(
    base: Path, clone: Path, lane_worktree: Path
) -> None:
    """An inert hook is the failure OMN-18273 measured three days of, and it
    presents as success: exit 0, no trailer, commit lands.

    Grading it ALLOWED would make this probe report a pass over exactly the
    state it was written to detect. Reproduced by replacing the installed hook
    with one that exits 0 and does nothing, which is what an inert install
    behaves like from the outside.
    """
    li.register(base, lane_worktree, lane="lane-probe", ticket="OMN-18288")
    hook = clone / ".git" / "hooks" / "prepare-commit-msg"
    hook.write_text(
        f"#!/usr/bin/env bash\n{li.OURS_MARKER}\nexit 0\n", encoding="utf-8"
    )
    hook.chmod(0o755)
    results = _probe(base, clone)
    row = _by_case(results, "registered")
    assert row.outcome == li.PROBE_REFUSED
    assert row.stamped is False
    assert "inert" in row.detail
    assert li.probe_refusals(results, base)


@pytest.mark.unit
def test_an_unarmed_clone_reports_unprobed_rather_than_allowed(
    base: Path, tmp_path: Path
) -> None:
    """A clone with no hook installed refuses nothing, and saying ALLOWED there
    would let an un-armed fleet read as a clean readback.

    UNPROBED is the honest answer: the question was not asked of this clone.
    """
    bare = tmp_path / "clones" / "unarmed"
    bare.mkdir(parents=True)
    _git(bare, "init", "-q", "-b", "main")
    rows = _probe(base, bare)
    assert [r.outcome for r in rows] == [li.PROBE_UNPROBED]
    assert "not armed" in rows[0].detail


# ---------------------------------------------------------------------------
# Policy-relative grading
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_an_unregistered_directory_is_graded_against_the_declared_policy(
    base: Path, clone: Path
) -> None:
    """Under `refuse`, an unregistered directory refusing is the mechanism
    working. Grading it as a defect would make the probe red exactly when the
    workspace is most strictly armed, which is the shape of gate that gets
    turned off.
    """
    hook = clone / ".git" / "hooks" / "prepare-commit-msg"
    probed = {"ONEX_LANE_REGISTRY_ROOT": str(base)}

    li.set_unregistered_mode(base, "silent")
    status_silent, _, _ = li.run_installed_hook(clone, hook, env_overrides=probed)
    assert status_silent == 0, "under `silent` an unregistered worktree must commit"
    row = _by_case(_probe(base, clone), "unregistered/")
    assert row.outcome == li.PROBE_ALLOWED
    assert li.probe_refusals([row], base) == []

    li.set_unregistered_mode(base, "refuse")
    status_refuse, _, stderr = li.run_installed_hook(clone, hook, env_overrides=probed)
    assert status_refuse != 0, "under `refuse` an unregistered worktree must not"
    assert "no lane identity" in stderr
    row = _by_case(_probe(base, clone), "unregistered/")
    assert row.outcome == li.PROBE_REFUSED
    assert li.probe_refusals([row], base) == [], (
        "under `refuse` a refused unregistered directory is the mechanism working"
    )


# ---------------------------------------------------------------------------
# The empty sweep
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_probing_nothing_is_refused_rather_than_reported_as_a_pass(
    base: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Zero refusals over zero clones reads exactly like a clean bill of health.

    CLAUDE.md rule 16: an empty result is not evidence of absence, and every
    zero this tool reports has to have been a real sweep. Exit 2, not 0.
    """
    empty = tmp_path / "no-clones"
    empty.mkdir()
    code = li.main(
        ["--registry-root", str(base), "probe", "--repo", str(empty / "absent")]
    )
    assert code == 2
    assert "empty sweep" in capsys.readouterr().err


@pytest.mark.unit
def test_the_json_report_carries_one_row_per_clone_worktree_pair(
    base: Path, clone: Path, lane_worktree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """ "Record the result per clone, not a single spot check" — so the report is
    a row per pair with its own outcome, not one aggregate verdict."""
    li.register(base, lane_worktree, lane="lane-probe", ticket="OMN-18288")
    code = li.main(
        ["--registry-root", str(base), "probe", "--repo", str(clone), "--json"]
    )
    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["clones"] == 1
    assert report["refusals"] == 0
    assert report["unprobed"] == 0
    cases = {row["case"] for row in report["results"]}
    assert cases == {"registered", "unregistered/silent"}
    for row in report["results"]:
        assert row["outcome"] == li.PROBE_ALLOWED
        assert row["detail"]


@pytest.mark.unit
def test_the_cli_exits_nonzero_when_any_clone_refuses(
    base: Path, clone: Path, lane_worktree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The readback has to be usable as a gate, which means its exit status —
    not its prose — carries the verdict."""
    li.register(base, lane_worktree, lane="lane-probe", ticket="OMN-18288")
    _make_the_clone_refuse(clone)
    code = li.main(["--registry-root", str(base), "probe", "--repo", str(clone)])
    assert code == 1
    assert "did not behave" in capsys.readouterr().err
