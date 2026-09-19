# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for OMN-18800 — the installed hook may name only the canonical module.

THE MEASURED DEFECT, 2026-09-19T02:32Z. The arming verbs baked THEIR OWN SOURCE
PATH into every hook they wrote: both call sites passed `module=Path(__file__)`
and `install_hook` substituted that for the `@LANE_IDENTITY_PATH@` placeholder.
A lane ran `reconcile --execute` from a per-ticket worktree copy of the module,
and all 27 canonical clones came away pointing at
`<workspace>/omni_worktrees/<ticket>/omniclaude/scripts/lane_identity.py` — a
path the worktree prune deletes. The blast radius is the whole registry from one
invocation in the wrong directory, which is why this is a mechanism and not a
note in a runbook.

WHY A FALLBACK IS NOT THE FIX. The shipped hook already tries four candidates in
turn, the last of which is the workspace copy, so on this host a pruned baked
path would often still resolve and the arming would merely be different from
what the operator read back. That is the worse half of the failure, not the
milder one: the readback and the behaviour disagree, and nothing says so. So the
refusal is at ARMING time, where the wrong path is written, rather than at
commit time, where it is too late to attribute.

WHAT IS DELIBERATELY NOT COVERED HERE. The hook's INTERPRETER is not baked at
all — `prepare-commit-msg-lane` scans `ONEX_LANE_PYTHON` then python3.13/3.12/
3.11/3 at commit time and takes the first that is new enough, because a git hook
runs with whatever PATH git has. That resolution is untouched by this change and
no test here asserts anything about it.

THE TEST SEAM IS THE WORKSPACE, NOT A BYPASS. Every test below builds a
miniature workspace and points `OMNI_HOME` at it, with the module under test
reachable at the canonical slot `<root>/omniclaude/scripts/lane_identity.py`.
There is no variable that tells the installer to bake something else; naming one
would reintroduce exactly the hole these tests close.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from omnibase_core.validators.no_unguarded_git_subprocess import (
    scrub_git_location_env,
)

from scripts import lane_identity as li

MODULE = Path(li.__file__).resolve()


def _clean_env(root: Path, **extra: str) -> dict[str, str]:
    """The ambient environment, hermetic for git, pointed at `root`.

    Every `GIT_*` variable is dropped for the reason the sibling suites drop
    them: inside a pre-commit hook an inherited `GIT_INDEX_FILE` aims a
    throwaway repository's commit at the OUTER repository's index, and the test
    then fails for a reason unrelated to what it asserts.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        {
            li.WORKSPACE_ENV: str(root),
            "ONEX_LANE_REGISTRY_ROOT": str(root / ".onex_state"),
            "GIT_CONFIG_GLOBAL": str(root / "gitconfig"),
            "GIT_CONFIG_SYSTEM": str(root / "gitconfig-system"),
        }
    )
    env.update(extra)
    return scrub_git_location_env(env)


def _run(module: Path, root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run a COPY of the module as a script, exactly as a lane invokes it."""
    return subprocess.run(  # noqa: PLW1510 - the return code IS the assertion
        [sys.executable, str(module), *args],
        capture_output=True,
        text=True,
        env=_clean_env(root),
    )


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A miniature registry whose canonical omniclaude slot is the module.

    A SYMLINK, so the canonical slot and the module under test are one file
    while keeping two distinct spellings — which is the whole point of the AC1
    assertion below: the installer must bake the workspace's spelling of the
    canonical module, not whichever path it happened to be invoked through.
    """
    ws = tmp_path / "ws"
    canonical = ws / "omniclaude" / "scripts"
    canonical.mkdir(parents=True)
    (canonical / "lane_identity.py").symlink_to(MODULE)
    return ws


@pytest.fixture
def worktree_copy(root: Path) -> Path:
    """A real COPY of the module under `omni_worktrees/`, as the incident had.

    Copied rather than linked on purpose: a git worktree holds real files, so a
    symlink here would resolve to the canonical module and the refusal under
    test would never be reached — the fixture would quietly prove nothing.
    """
    scripts = root / "omni_worktrees" / "OMN-0" / "omniclaude" / "scripts"
    scripts.mkdir(parents=True)
    copy = scripts / "lane_identity.py"
    shutil.copy2(MODULE, copy)
    (scripts / "hooks").mkdir()
    shutil.copy2(
        MODULE.parent / "hooks" / "prepare-commit-msg-lane",
        scripts / "hooks" / "prepare-commit-msg-lane",
    )
    return copy


@pytest.fixture
def clone(root: Path) -> Path:
    """A clone in the registry, ready to be armed."""
    c = root / "widget"
    c.mkdir(parents=True)
    (c / "seed.txt").write_text("seed\n", encoding="utf-8")
    env = _clean_env(root)
    for args in (
        ("init", "-q", "-b", "main"),
        ("config", "user.email", "t@example.com"),
        ("config", "user.name", "t"),
        ("add", "seed.txt"),
        ("commit", "-q", "-m", "seed"),
    ):
        # `scrub_git_location_env` inline at the call, though `_clean_env`
        # already applies it: git exports GIT_DIR and friends into every hook
        # environment and they OVERRIDE `cwd=`, so a fixture that got this
        # wrong under a pre-push hook would `git init` over the real worktree.
        # The guard that enforces it reads the call site, and a guard that can
        # be satisfied by a helper three frames away is a guard that drifts.
        subprocess.run(
            ["git", *args], cwd=c, check=True, env=scrub_git_location_env(env)
        )
    return c


def _hook(clone: Path) -> Path:
    return clone / ".git" / "hooks" / "prepare-commit-msg"


# ---------------------------------------------------------------------------
# AC2 — arming from anything but the canonical module is refused
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_install_hook_from_a_worktree_copy_is_refused(
    root: Path, clone: Path, worktree_copy: Path
) -> None:
    """The incident, reproduced: the arming verb invoked from a worktree copy.

    It must refuse and write NOTHING. An install that succeeded while merely
    printing a warning is the same outcome as today — 27 clones baked with a
    path scheduled for deletion — with a line in a log nobody reads.
    """
    result = _run(worktree_copy, root, "install-hook", "--repo", str(clone))

    assert result.returncode != 0, (
        "arming from a worktree copy was ACCEPTED; stdout:\n"
        f"{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert not _hook(clone).exists(), (
        "the refusal still wrote a hook, so the wrong path was baked anyway"
    )


@pytest.mark.unit
def test_the_refusal_names_both_the_invoked_and_the_canonical_path(
    root: Path, clone: Path, worktree_copy: Path
) -> None:
    """A refusal that does not say which two paths disagree costs a search.

    Both halves are needed: the invoked path says what went wrong, the
    canonical one says what to run instead.
    """
    result = _run(worktree_copy, root, "install-hook", "--repo", str(clone))

    assert str(worktree_copy) in result.stderr, (
        f"the refusal did not name the invoked path; stderr:\n{result.stderr}"
    )
    assert str(li.canonical_module_path(root)) in result.stderr, (
        f"the refusal did not name the canonical path; stderr:\n{result.stderr}"
    )


@pytest.mark.unit
def test_reconcile_refuses_before_it_installs_into_any_clone(
    root: Path, clone: Path, worktree_copy: Path
) -> None:
    """`reconcile` arms every clone in one pass, so its refusal has to land
    BEFORE the first install. A check inside the loop would leave the registry
    half-baked with the very path the refusal exists to reject."""
    result = _run(worktree_copy, root, "reconcile", "--execute")

    assert result.returncode != 0, (
        f"reconcile from a worktree copy was accepted; stdout:\n{result.stdout}"
    )
    assert not _hook(clone).exists(), (
        "reconcile refused only after installing; the clone carries a hook baked "
        "from a worktree copy"
    )


@pytest.mark.unit
def test_a_canonical_module_that_does_not_resolve_is_refused_not_defaulted(
    tmp_path: Path, clone: Path, root: Path
) -> None:
    """FAIL CLOSED. A workspace with no omniclaude clone cannot say what its
    canonical module is, and falling back to `__file__` there would restore the
    whole defect under a different condition (CLAUDE.md rule 8)."""
    empty = tmp_path / "no-omniclaude"
    empty.mkdir()
    result = _run(MODULE, empty, "install-hook", "--repo", str(clone))

    assert result.returncode != 0, (
        f"a workspace with no canonical module armed anyway; stdout:\n{result.stdout}"
    )
    assert not _hook(clone).exists()


# ---------------------------------------------------------------------------
# AC1 — what a successful arming bakes
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_the_bake_is_the_canonical_spelling_not_the_invoked_one(
    root: Path, clone: Path
) -> None:
    """Invoked through the workspace's canonical slot, which is a link to the
    module under test. The baked value must be the WORKSPACE's spelling: that
    is the path this registry converges on, and the one every other surface —
    the reconciler, the drift finding below — names."""
    canonical = li.canonical_module_path(root)
    result = _run(canonical, root, "install-hook", "--repo", str(clone))
    assert result.returncode == 0, result.stdout + result.stderr

    baked = li.baked_module_path(_hook(clone))
    assert baked == canonical, (
        f"the hook was baked with {baked}, not the canonical {canonical}"
    )
    assert baked != MODULE, (
        "the bake followed the invoked spelling through to the real file; a "
        "workspace whose canonical slot moves would then silently keep the old one"
    )


# ---------------------------------------------------------------------------
# AC3 — a non-canonical baked path is a reported DRIFT finding
# ---------------------------------------------------------------------------


def _rebake(hook: Path, path: str) -> None:
    """Rewrite an installed hook's baked path, as the incident left it."""
    body = hook.read_text(encoding="utf-8")
    old = li.baked_module_path(hook)
    assert old is not None, "the hook carries no baked path to rewrite"
    hook.write_text(
        body.replace(
            f'INSTALLED_LANE_IDENTITY="{old}"', f'INSTALLED_LANE_IDENTITY="{path}"'
        ),
        encoding="utf-8",
    )


@pytest.mark.unit
def test_status_reports_a_worktree_baked_path_as_drift(root: Path, clone: Path) -> None:
    """The reconciler relays `status` and its exit code, so a hook armed with a
    doomed path has to be a NONZERO finding there. Reported rather than silently
    repaired: the reconciler's repair path re-arms and reads back, and a finding
    it can see is what makes that pass meaningful."""
    canonical = li.canonical_module_path(root)
    assert _run(canonical, root, "install-hook", "--repo", str(clone)).returncode == 0
    doomed = str(
        root
        / "omni_worktrees"
        / "OMN-0"
        / "omniclaude"
        / "scripts"
        / "lane_identity.py"
    )
    _rebake(_hook(clone), doomed)

    result = _run(canonical, root, "status", "--repo", str(clone), "--json")

    assert result.returncode != 0, (
        f"a non-canonical baked path reported a pass; stdout:\n{result.stdout}"
    )
    report = json.loads(result.stdout)
    row = report["repos"][0]
    assert row["baked"] == doomed, row
    assert row["baked_canonical"] is False, row
    assert report["drifted"] == 1, report


@pytest.mark.unit
def test_the_drift_finding_carries_its_remedy(root: Path, clone: Path) -> None:
    """A finding with no remedy is a finding somebody has to research. The
    remedy names the canonical module, because running the arming verb from
    anywhere else is the thing that produced the finding."""
    canonical = li.canonical_module_path(root)
    assert _run(canonical, root, "install-hook", "--repo", str(clone)).returncode == 0
    _rebake(_hook(clone), str(root / "omni_worktrees" / "gone" / "lane_identity.py"))

    result = _run(canonical, root, "status", "--repo", str(clone))

    assert f"{canonical} reconcile --execute" in result.stderr, (
        f"the drift finding printed no canonical remedy; stderr:\n{result.stderr}"
    )


@pytest.mark.unit
def test_a_canonically_baked_clone_is_not_reported_as_drift(
    root: Path, clone: Path
) -> None:
    """The positive control (CLAUDE.md rule 16). Without it the two assertions
    above are also satisfied by a checker that calls every clone drifted."""
    canonical = li.canonical_module_path(root)
    assert _run(canonical, root, "install-hook", "--repo", str(clone)).returncode == 0

    result = _run(canonical, root, "status", "--repo", str(clone), "--json")

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["drifted"] == 0, report
    assert report["repos"][0]["baked_canonical"] is True, report["repos"][0]


@pytest.mark.unit
def test_an_unarmed_clone_reports_no_baked_path_rather_than_a_false_one(
    root: Path, clone: Path
) -> None:
    """A clone with no hook has no baked path, and `null` is the honest answer.
    Reporting it as drift would drown the real finding in rows that only say
    the clone is unarmed, which `status` already says in its own column."""
    result = _run(
        li.canonical_module_path(root), root, "status", "--repo", str(clone), "--json"
    )

    assert result.returncode == 1, result.stdout + result.stderr
    row = json.loads(result.stdout)["repos"][0]
    assert row["installed"] is False, row
    assert row["baked"] is None, row


# ---------------------------------------------------------------------------
# The resolution itself
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_canonical_module_path_is_the_omniclaude_clone_under_the_root(
    tmp_path: Path,
) -> None:
    assert li.canonical_module_path(tmp_path) == (
        tmp_path / "omniclaude" / "scripts" / "lane_identity.py"
    )


@pytest.mark.unit
def test_canonical_module_path_fails_fast_with_no_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(li.WORKSPACE_ENV, raising=False)
    with pytest.raises(KeyError):
        li.canonical_module_path()


@pytest.mark.unit
def test_baked_module_path_is_none_for_a_hook_that_is_not_ours(
    tmp_path: Path,
) -> None:
    """A third-party hook carries no baked line at all, and reading one out of
    it would invent a finding about a file this mechanism does not own."""
    foreign = tmp_path / "prepare-commit-msg"
    foreign.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    assert li.baked_module_path(foreign) is None
