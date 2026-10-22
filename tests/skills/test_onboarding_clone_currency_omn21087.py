# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-21087: a returning machine's clones are brought current, or named, and a
resumed run picks up at the phase that failed.

Phase 2 checks every clean clone out at its anchored commit (OMN-21255 replaced
the fast-forward to origin). A clone that holds work stops the phase, named with its
state, how far behind origin it is and the command that moves it aside; a clean
detached clone is put back at its anchored commit, and a dirty detached clone stops. An
old clone that lacks a file origin has is reported as behind, never as a file to
restore. A resumed run (including from a freshly downloaded copy of the script)
skips the phases an earlier run passed and runs the one that failed, and says
why when a passed phase has to run again.
"""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
_ps = importlib.import_module("test_lab_onboarding_proven_set_omn20381")
Harness: Any = _ps.Harness
REPOS: tuple[str, ...] = _ps.REPOS
SCRIPT: Path = _ps.SCRIPT


def _git(repo: Path, *args: str, stdin: str | None = None) -> str:
    return str(_ps._git(repo, *args, stdin=stdin))


pytestmark = pytest.mark.unit

PINNED = ("omnimarket", "omnibase_core")
STAMP = "20261014-174000"


@pytest.fixture
def harness(tmp_path: Path) -> Any:
    return Harness(tmp_path)


def _passed(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 0, result.stdout + result.stderr


def _stopped(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 1, result.stdout + result.stderr
    assert "PASS" not in result.stdout, result.stdout


def _move_aside(harness: Any, repo: str) -> str:
    ws = harness.workspace
    return (
        f'to move it aside: mkdir -p "{ws}/.set-aside" && '
        f'mv "{ws / repo}" "{ws}/.set-aside/{repo}.{STAMP}"'
    )


def _heads(harness: Any) -> dict[str, str]:
    return {r: _git(harness.workspace / r, "rev-parse", "HEAD") for r in REPOS}


def _third_infra_commit(harness: Any) -> str:
    """origin's omnibase_infra moves one more commit ahead, so an old clone is 2 behind."""
    remote = harness.remotes / "omnibase_infra.git"
    newer = harness.commits["omnibase_infra"][1]
    tree = _git(remote, "rev-parse", f"{newer}^{{tree}}")
    third = _git(remote, "commit-tree", tree, "-p", newer, stdin="third\n")
    _git(remote, "update-ref", "refs/heads/dev", third)
    return third


# ---------------------------------------------------------------------------
# AC1: a clean clone on its branch is moved to its anchored commit (OMN-21255)
# ---------------------------------------------------------------------------


def test_ac1_a_clean_clone_on_its_branch_is_moved_to_its_anchored_commit(
    harness: Any,
) -> None:
    """OMN-21255 supersedes the fast-forward: every clean clone, on a branch or
    not, is checked out detached at its anchored commit, never at origin's tip."""
    harness.make_remotes()
    _passed(harness.run("phase2"))
    for repo in REPOS:
        _git(
            harness.workspace / repo,
            "checkout",
            "--quiet",
            "-B",
            "dev",
            harness.commits[repo][0],
        )
    result = harness.run("phase2")
    _passed(result)
    for repo in REPOS:
        clone = harness.workspace / repo
        older, newer = harness.commits[repo]
        expected = older if repo in PINNED else newer
        assert _git(clone, "rev-parse", "HEAD") == expected, repo
        assert _git(clone, "rev-parse", "--abbrev-ref", "HEAD") == "HEAD", repo
    assert (
        "omnibase_spi: clone is 1 commit behind origin/dev; "
        "checking out its anchored commit"
    ) in result.stdout


# ---------------------------------------------------------------------------
# AC2: dirty stops, named; a clean detached clone is put back at its anchored
# commit (OMN-21255); a dirty detached clone stops
# ---------------------------------------------------------------------------


def test_ac2_a_dirty_clone_stops_naming_its_state_distance_and_fix(
    harness: Any,
) -> None:
    harness.make_remotes()
    _passed(harness.run("phase2"))
    spi = harness.workspace / "omnibase_spi"
    older = harness.commits["omnibase_spi"][0]
    _git(spi, "checkout", "--quiet", "-B", "dev", older)
    (spi / "README").write_text("mine\n")
    result = harness.run("phase2")
    _stopped(result)
    assert (
        "✗ omnibase_spi: 1 tracked file(s) changed or deleted "
        "(on branch dev, 1 commit(s) behind origin/dev)"
    ) in result.stdout
    assert _move_aside(harness, "omnibase_spi") in result.stdout
    assert _git(spi, "rev-parse", "HEAD") == older
    assert (spi / "README").read_text() == "mine\n"


def test_ac2_a_clean_clone_that_cannot_fast_forward_stops_and_moves_nothing(
    harness: Any,
) -> None:
    harness.make_remotes()
    _passed(harness.run("phase2"))
    spi = harness.workspace / "omnibase_spi"
    older = harness.commits["omnibase_spi"][0]
    _git(spi, "checkout", "--quiet", "-B", "dev", older)
    (spi / "local.txt").write_text("mine\n")
    _git(spi, "add", "local.txt")
    _git(spi, "commit", "--quiet", "-m", "local work")
    _git(spi, "checkout", "--quiet", "-B", "feature", older)
    before = _heads(harness)
    result = harness.run("phase2")
    _stopped(result)
    assert (
        "✗ omnibase_spi: its dev branch has 1 commit(s) that origin does not "
        "have, so it cannot fast-forward (on branch feature, 1 commit(s) behind "
        "origin/dev)"
    ) in result.stdout
    assert _move_aside(harness, "omnibase_spi") in result.stdout
    assert _git(spi, "rev-parse", "--abbrev-ref", "HEAD") == "feature"
    assert _heads(harness) == before


def test_ac2_a_clean_detached_clone_is_put_back_at_its_anchored_commit(
    harness: Any,
) -> None:
    harness.make_remotes()
    _passed(harness.run("phase2"))
    spi = harness.workspace / "omnibase_spi"
    older, newer = harness.commits["omnibase_spi"]
    _git(spi, "checkout", "--quiet", "--detach", older)
    _passed(harness.run("phase2"))
    assert _git(spi, "rev-parse", "HEAD") == newer
    assert _git(spi, "rev-parse", "--abbrev-ref", "HEAD") == "HEAD"


def test_ac2_a_dirty_detached_clone_stops(harness: Any) -> None:
    harness.make_remotes()
    _passed(harness.run("phase2"))
    spi = harness.workspace / "omnibase_spi"
    older = harness.commits["omnibase_spi"][0]
    _git(spi, "checkout", "--quiet", "--detach", older)
    (spi / "README").write_text("mine\n")
    result = harness.run("phase2")
    _stopped(result)
    assert (
        "✗ omnibase_spi: 1 tracked file(s) changed or deleted "
        "(detached HEAD, 1 commit(s) behind origin/dev)"
    ) in result.stdout
    assert _move_aside(harness, "omnibase_spi") in result.stdout
    assert _git(spi, "rev-parse", "--abbrev-ref", "HEAD") == "HEAD"
    assert _git(spi, "rev-parse", "HEAD") == older


# ---------------------------------------------------------------------------
# AC3: an old clone missing a file is reported as N commits behind
# ---------------------------------------------------------------------------


def _old_infra_without_pins(harness: Any) -> tuple[Path, str, str]:
    harness.make_remotes(pins_in_older=False)
    _passed(harness.run("phase2"))
    third = _third_infra_commit(harness)
    infra = harness.workspace / "omnibase_infra"
    older = harness.commits["omnibase_infra"][0]
    _git(infra, "checkout", "--quiet", "-B", "dev", older)
    assert not (infra / ".github" / "sibling-pins.yaml").exists()
    return infra, older, third


def test_ac3_an_old_clean_clone_missing_the_pins_file_is_reported_as_behind(
    harness: Any,
) -> None:
    infra, _older, third = _old_infra_without_pins(harness)
    result = harness.run("phase2")
    _passed(result)
    assert (
        "omnibase_infra: clone is 2 commits behind origin/dev and predates "
        ".github/sibling-pins.yaml, which origin has; checking out its anchored "
        "commit"
    ) in result.stdout
    assert "restore the pins file" not in result.stdout
    # OMN-21255: the anchor, not origin's tip.
    assert _git(infra, "rev-parse", "HEAD") == harness.commits["omnibase_infra"][1]
    assert _git(infra, "rev-parse", "HEAD") != third


def test_ac3_an_old_dirty_clone_missing_the_pins_file_is_reported_as_behind(
    harness: Any,
) -> None:
    infra, older, _third = _old_infra_without_pins(harness)
    (infra / "README").unlink()
    result = harness.run("phase2")
    _stopped(result)
    assert (
        "      omnibase_infra: clone is 2 commits behind origin/dev and predates "
        ".github/sibling-pins.yaml, which origin has"
    ) in result.stdout
    assert _move_aside(harness, "omnibase_infra") in result.stdout
    assert "restore the pins file" not in result.stdout
    assert _git(infra, "rev-parse", "HEAD") == older


# ---------------------------------------------------------------------------
# AC4: a resumed run picks up at the failed phase, including from a fresh
# download of the script, or says why a passed phase runs again
# ---------------------------------------------------------------------------

# Phase 0 asks its questions and probes this Mac; here it only prints where the
# run picks up. Phases 1 and 2 are the script's own, with their checks passing;
# any install step they reach prints INSTALLED. Phase 3 is the script's own and
# stops at its second step.
_RESUME_STUBS = """
phase0() { phase_start 0 "Preflight"; resume_banner; phase_pass; }
phase1_verified() { return 0; }
phase2_verified() { return "${PHASE2_BROKEN:-0}"; }
install_clt() { echo INSTALLED clt; }
brew_install() { echo INSTALLED "$1"; }
refuse_foreign_workspace() { :; }
sync_clone() { echo INSTALLED "clone $1"; return 1; }
dispatch_venv_current() { echo "PHASE3 checked the dispatch venv"; return 0; }
link_onex() { return 1; }
"""

# The first run: phases 1 and 2 pass (phase_pass records them), phase 3 fails.
_FIRST_RUN_STUBS = """
phase0() { phase_start 0 "Preflight"; phase_pass; }
phase1() { phase_start 1 "Base tools"; phase_pass; }
phase2() { phase_start 2 "Workspace"; phase_pass; }
dispatch_venv_current() { return 0; }
link_onex() { return 1; }
"""


def _download(tmp_path: Path, where: str, stubs: str) -> Path:
    """A copy of the script in its own directory, main run after the stubs."""
    body = SCRIPT.read_text()
    assert body.rstrip().endswith("\nmain")
    copy = tmp_path / where / "lab-onboarding.sh"
    copy.parent.mkdir(parents=True)
    copy.write_text(body.rstrip()[: -len("main")] + "\n" + stubs + "\nmain\n")
    return copy


def _run_copy(
    tmp_path: Path, copy: Path, **env: str
) -> subprocess.CompletedProcess[str]:
    (tmp_path / "run").mkdir(exist_ok=True)
    return subprocess.run(
        ["/bin/bash", str(copy), "--no-containers", "--provider", "openrouter"],
        env={
            "HOME": str(tmp_path / "home"),
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "TMPDIR": str(tmp_path / "run") + "/",
            "OMNIBASE_PATH": str(tmp_path / "ws"),
            "ONBOARD_NOTIFY": "0",
            "ONBOARD_TEST_NO_USER_SHELL": "1",
            **env,
        },
        cwd=str(SCRIPT.parents[4]),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_ac4_a_resumed_run_from_a_fresh_download_runs_the_failed_phase(
    tmp_path: Path,
) -> None:
    (tmp_path / "home").mkdir()
    first = _run_copy(tmp_path, _download(tmp_path, "first", _FIRST_RUN_STUBS))
    assert first.returncode == 1, first.stdout + first.stderr
    assert "✘ Phase 3/6 FAILED" in first.stdout, first.stdout
    done = tmp_path / "home" / ".omninode" / "onboarding" / "phases.v2.done"
    assert done.read_text().split() == ["1", "2"]

    # A fresh download: another copy of the script, somewhere else.
    second = _run_copy(tmp_path, _download(tmp_path, "downloads", _RESUME_STUBS))
    out = second.stdout
    assert second.returncode == 1, out + second.stderr
    assert "picks up at phase 3" in out
    assert "Phase 1/6 PASSED: Base tools" in out and "already installed" in out
    assert "Phase 2/6 PASSED: Workspace" in out and "already in place" in out
    assert "INSTALLED" not in out
    assert "PHASE3 checked the dispatch venv" in out
    assert "▶ Phase 3/6" in out
    assert "✘ Phase 3/6 FAILED" in out
    assert "Step:      point ~/.local/bin/onex at the workspace wrapper" in out
    assert "runs again" not in out


def test_ac4_a_passed_phase_that_must_run_again_says_why(tmp_path: Path) -> None:
    state = tmp_path / "home" / ".omninode" / "onboarding"
    state.mkdir(parents=True)
    (state / "phases.v2.done").write_text("1\n2\n")
    result = _run_copy(
        tmp_path, _download(tmp_path, "downloads", _RESUME_STUBS), PHASE2_BROKEN="1"
    )
    out = result.stdout
    assert result.returncode == 1, out + result.stderr
    assert "Phase 1/6 PASSED" in out and "already installed" in out
    assert (
        "Phase 2 passed in an earlier run, but the workspace no longer checks out"
    ) in out
    assert "so it runs again." in out
    assert "Phase 3/6" not in out
