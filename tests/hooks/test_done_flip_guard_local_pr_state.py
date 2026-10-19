# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""The Done-flip guard reads PR merge state locally, never through gh [OMN-20368].

A lane cannot call ``gh`` (the gh shim refuses every GitHub read, OMN-19856), so
the guard's PR-state read used to answer ``pr_not_merged`` for a PR that merged.
It now asks the PR watcher state (``pr_state_local.py``) first and, for a PR the
watcher no longer tracks, the canonical clone's base branch: a squash commit
whose subject ends ``(#N)``. It fails closed only when neither source can prove
the merge, and the error names the PR.
"""

from __future__ import annotations

import importlib
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from omnibase_core.validators.no_unguarded_git_subprocess import (
    scrub_git_location_env,
)

pytestmark = pytest.mark.unit

_LIB_DIR = Path(__file__).parents[2] / "plugins" / "onex" / "hooks" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

ldv: Any = importlib.import_module("linear_done_verify")

_REPO = "OmniNode-ai/omnimarket"
_NUMBER = 2299
_HEAD = "a" * 40


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=True,
        env=scrub_git_location_env(os.environ),
    )
    return done.stdout.strip()


def _clone(registry: Path, *subjects: str) -> tuple[Path, list[str]]:
    """A canonical clone of omnimarket whose origin/dev holds one commit per subject."""
    clone = registry / "omnimarket"
    clone.mkdir(parents=True)
    _git(clone, "init", "-q", "-b", "dev")
    _git(clone, "config", "user.email", "t@example.invalid")
    _git(clone, "config", "user.name", "t")
    _git(clone, "config", "commit.gpgsign", "false")
    _git(clone, "config", "onex.repo", _REPO)
    shas: list[str] = []
    for index, subject in enumerate(subjects):
        (clone / f"f{index}").write_text(subject)
        _git(clone, "add", ".")
        _git(clone, "commit", "-q", "-m", subject)
        shas.append(_git(clone, "rev-parse", "HEAD"))
    _git(clone, "update-ref", "refs/remotes/origin/dev", shas[-1])
    _git(clone, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/dev")
    return clone, shas


def _fake_pr_state_local(plugin_root: Path, record: dict[str, Any] | None) -> None:
    """A pr_state_local.py that prints ``record`` as ``--json`` would, or reports MISSING."""
    script = plugin_root / "skills" / "merge-drain" / "scripts" / "pr_state_local.py"
    script.parent.mkdir(parents=True)
    if record is None:
        body = (
            "import sys\n"
            "print('PR-STATE MISSING: not in the state; read GitHub instead')\n"
            "sys.exit(3)\n"
        )
    else:
        body = f"import sys\nprint({json.dumps(json.dumps(record))})\nsys.exit(0)\n"
    script.write_text(body)


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """No gh on PATH (git only), an empty registry, and no watcher unless a test installs one."""
    empty_bin = tmp_path / "bin"
    empty_bin.mkdir()
    git = shutil.which("git")
    assert git is not None
    (empty_bin / "git").symlink_to(git)
    registry = tmp_path / "registry"
    registry.mkdir()
    plugin_root = tmp_path / "omni-plugin"
    plugin_root.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin))
    monkeypatch.setenv("OMNI_HOME", str(registry))
    monkeypatch.setenv("OMNI_PLUGIN_ROOT", str(plugin_root))
    monkeypatch.delenv("ONEX_REGISTRY_ROOTS", raising=False)
    monkeypatch.delenv("OMNIBASE_INTERNAL_HOME", raising=False)

    real_run = subprocess.run

    def no_gh(argv: list[str], **_kwargs: Any) -> Any:
        if argv and Path(str(argv[0])).name == "gh":
            raise AssertionError(f"PR state must not be read through gh: {argv}")
        return real_run(argv, **_kwargs)

    monkeypatch.setattr(ldv.subprocess, "run", no_gh)
    return {"registry": registry, "plugin_root": plugin_root}


def _ref() -> Any:
    return ldv.PRRef(number=_NUMBER, repo=_REPO)


def test_merged_pr_proven_by_the_clone_passes_with_no_gh(env: dict[str, Path]) -> None:
    _clone_dir, shas = _clone(
        env["registry"], "base", f"feat(OMN-1): the change (#{_NUMBER})", "later (#7)"
    )

    status = ldv.fetch_pr_status(_ref())

    assert status.error is None, status.error
    assert status.state == "MERGED"
    assert status.merge_commit_sha == shas[1]
    assert ldv.classify_blocking(status) is False


def test_unmerged_pr_unknown_to_the_clone_still_refuses_and_names_the_pr(
    env: dict[str, Path],
) -> None:
    _clone(env["registry"], "base", "an unrelated change (#7)")

    status = ldv.fetch_pr_status(_ref())

    assert status.state != "MERGED"
    assert status.error is not None
    assert f"{_REPO}#{_NUMBER}" in status.error
    assert ldv.classify_blocking(status) is True


@pytest.mark.parametrize(
    "subject",
    [
        f"fix: mentions (#{_NUMBER}) mid-subject and then goes on",
        f"fix: a different PR (#{_NUMBER}0)",
        f"fix: a different PR (#{_NUMBER // 10})",
        f"Revert something, see #{_NUMBER}",
    ],
)
def test_clone_match_needs_the_subject_to_end_with_the_exact_number(
    env: dict[str, Path], subject: str
) -> None:
    _clone(env["registry"], "base", subject)

    status = ldv.fetch_pr_status(_ref())

    assert status.state != "MERGED"
    assert ldv.classify_blocking(status) is True


def test_a_body_mention_does_not_prove_a_merge(env: dict[str, Path]) -> None:
    _clone(env["registry"], "base", f"chore: no number here\n\nfollows (#{_NUMBER})")

    assert ldv.fetch_pr_status(_ref()).state != "MERGED"


def test_no_clone_and_no_watcher_fails_closed_naming_the_pr(
    env: dict[str, Path],
) -> None:
    status = ldv.fetch_pr_status(_ref())

    assert status.state != "MERGED"
    assert status.error is not None
    assert f"{_REPO}#{_NUMBER}" in status.error
    assert "watcher" in status.error
    assert "clone" in status.error
    assert ldv.classify_blocking(status) is True


def test_watcher_merged_record_passes_with_no_gh(env: dict[str, Path]) -> None:
    _fake_pr_state_local(
        env["plugin_root"],
        {
            "facts": {
                "state": "MERGED",
                "repo": "omnimarket",
                "number": _NUMBER,
                "head_sha": _HEAD,
                "merged_at": "2026-10-19T10:00:00Z",
                "title": "feat(OMN-1): the change",
            }
        },
    )

    status = ldv.fetch_pr_status(_ref())

    assert status.error is None, status.error
    assert status.state == "MERGED"
    assert status.head_sha == _HEAD
    assert status.merged_at == "2026-10-19T10:00:00Z"


def test_watcher_merged_record_takes_its_merge_commit_from_the_clone(
    env: dict[str, Path],
) -> None:
    _clone_dir, shas = _clone(env["registry"], "base", f"feat: the change (#{_NUMBER})")
    _fake_pr_state_local(
        env["plugin_root"],
        {
            "facts": {
                "state": "MERGED",
                "repo": "omnimarket",
                "number": _NUMBER,
                "head_sha": _HEAD,
                "merged_at": "2026-10-19T10:00:00Z",
            }
        },
    )

    status = ldv.fetch_pr_status(_ref())

    assert status.state == "MERGED"
    assert status.head_sha == _HEAD
    assert status.merge_commit_sha == shas[-1]


def test_watcher_open_record_refuses_even_if_the_clone_cannot_help(
    env: dict[str, Path],
) -> None:
    _fake_pr_state_local(
        env["plugin_root"],
        {
            "facts": {
                "state": "OPEN",
                "repo": "omnimarket",
                "number": _NUMBER,
                "head_sha": _HEAD,
            }
        },
    )

    status = ldv.fetch_pr_status(_ref())

    assert status.state == "OPEN"
    assert status.error is None
    assert ldv.classify_blocking(status) is True


def test_watcher_closed_record_carries_its_body_as_the_closing_note(
    env: dict[str, Path],
) -> None:
    _fake_pr_state_local(
        env["plugin_root"],
        {
            "facts": {
                "state": "CLOSED",
                "repo": "omnimarket",
                "number": _NUMBER,
                "title": "chore(OMN-1): first try",
                "body": "Superseded by #3000.",
            }
        },
    )

    status = ldv.fetch_pr_status(_ref())

    assert status.state == "CLOSED"
    assert status.title == "chore(OMN-1): first try"
    assert "Superseded by #3000." in status.closing_notes
    assert ldv.classify_blocking(status) is True


def test_watcher_missing_the_pr_falls_through_to_the_clone(
    env: dict[str, Path],
) -> None:
    _fake_pr_state_local(env["plugin_root"], None)
    _clone(env["registry"], "base", f"feat: the change (#{_NUMBER})")

    status = ldv.fetch_pr_status(_ref())

    assert status.state == "MERGED"
    assert status.error is None


def test_watcher_record_for_a_different_pr_is_not_trusted(env: dict[str, Path]) -> None:
    _fake_pr_state_local(
        env["plugin_root"],
        {"facts": {"state": "MERGED", "repo": "omnimarket", "number": 1}},
    )

    status = ldv.fetch_pr_status(_ref())

    assert status.state != "MERGED"
    assert ldv.classify_blocking(status) is True


def test_a_pr_without_a_repo_still_refuses_without_any_read(
    env: dict[str, Path],
) -> None:
    status = ldv.fetch_pr_status(ldv.PRRef(number=_NUMBER, repo=None))

    assert status.error is not None
    assert "no associated repo" in status.error


def test_the_guard_decide_path_accepts_a_clone_proven_merge(
    env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end through ``verify``: the cited PR merged per the clone, so no pr_not_merged."""
    _clone(env["registry"], "base", f"feat: the change (#{_NUMBER})")
    description = f"Implemented in https://github.com/{_REPO}/pull/{_NUMBER}\n"

    result = ldv.verify(description, [], fetcher=ldv.fetch_pr_status)

    assert result.allowed, result.reason
    assert result.reason == "all_prs_merged"
    assert [s.state for s in result.pr_statuses] == ["MERGED"]


def test_the_guard_decide_path_refuses_an_unmerged_pr_naming_it(
    env: dict[str, Path],
) -> None:
    _clone(env["registry"], "base")
    description = f"Implemented in https://github.com/{_REPO}/pull/{_NUMBER}\n"

    result = ldv.verify(description, [], fetcher=ldv.fetch_pr_status)

    assert not result.allowed
    assert f"{_REPO}#{_NUMBER}" in result.reason


def test_the_watcher_script_is_located_through_omni_home_when_no_plugin_root(
    env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OMNI_PLUGIN_ROOT")
    internal = env["registry"] / "plugin-clone" / "plugins" / "omni"
    _fake_pr_state_local(
        internal,
        {
            "facts": {
                "state": "MERGED",
                "repo": "omnimarket",
                "number": _NUMBER,
                "head_sha": _HEAD,
            }
        },
    )

    assert ldv.fetch_pr_status(_ref()).state == "MERGED"


def test_a_watcher_script_that_cannot_run_is_a_miss_not_a_crash(
    env: dict[str, Path],
) -> None:
    script = (
        env["plugin_root"] / "skills" / "merge-drain" / "scripts" / "pr_state_local.py"
    )
    script.parent.mkdir(parents=True)
    script.write_text("import sys\nsys.exit(1)\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    _clone(env["registry"], "base", f"feat: the change (#{_NUMBER})")

    assert ldv.fetch_pr_status(_ref()).state == "MERGED"


def test_omniclaude_not_importable_fails_closed_naming_the_pr(
    env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(
        sys.modules,
        "omniclaude.nodes.node_linear_effect.handlers.handler_local_pr_state",
        None,
    )

    status = ldv.fetch_pr_status(_ref())

    assert status.state != "MERGED"
    assert status.error is not None
    assert f"{_REPO}#{_NUMBER}" in status.error
    assert ldv.classify_blocking(status) is True
