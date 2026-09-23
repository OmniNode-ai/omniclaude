# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The dispatch skill injects committed text, never the working-tree copy [OMN-19255].

The lane-dispatch skill's step 4 used to say "read the rules block in full", and
a session did that with a file read. In a clone several sessions share, that
read picked up another session's uncommitted edits: 13,383 bytes in the working
tree against 10,256 at HEAD on the skill's first dry run. A real dispatch would
have injected them into every lane it started. The brief was read the same way,
so an untracked brief of the right name would have been dispatched too.

The negative control is the point of this file: a DIRTY working-tree copy sits
beside the committed one, and the helper must return the committed bytes. The
same fixture read the old way returns the dirty bytes, which proves the fixture
is dirty and the assertion is not vacuous.

Hermetic: each case builds its own repository under ``tmp_path``, with the
global and system git config pointed at empty files.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from omnibase_core.validators.no_unguarded_git_subprocess import (
    scrub_git_location_env,
)

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HELPER = _REPO_ROOT / "plugins" / "onex" / "scripts" / "read_committed_file.py"
_LANE_DISPATCH = _REPO_ROOT / "plugins" / "onex" / "skills" / "lane_dispatch"

RULES = ".claude/workflows/_shared/lane-rules-block.md"
BRIEFS = ".claude/workflows"
COMMITTED_RULES = b"## Standing rules\n\n- committed rule one\n"
DIRTY_RULES = COMMITTED_RULES + b"- a peer session's uncommitted edit\n"


def _isolated(tmp_path: Path) -> dict[str, str]:
    return {
        "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"),
        "GIT_CONFIG_SYSTEM": str(tmp_path / "gitconfig-system"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def _env(tmp_path: Path) -> dict[str, str]:
    return {**scrub_git_location_env(os.environ), **_isolated(tmp_path)}


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    repo = tmp_path / "workspace"
    repo.mkdir()

    def git(*args: str) -> None:
        subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            env={**scrub_git_location_env(os.environ), **_isolated(tmp_path)},
        )

    git("init", "-q", "-b", "main")
    git("config", "user.email", "fixture@example.com")
    git("config", "user.name", "fixture")
    (repo / RULES).parent.mkdir(parents=True)
    (repo / RULES).write_bytes(COMMITTED_RULES)
    (repo / BRIEFS / "hourly-tick.js").write_text("// committed brief\n")
    (repo / "empty.md").write_bytes(b"")
    git("add", "-A")
    git("commit", "-q", "-m", "seed")
    return repo


def _run(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, str(_HELPER), *args],
        capture_output=True,
        env=_env(tmp_path),
        check=False,
    )


def test_reads_the_committed_rules_block(tmp_path: Path, workspace: Path) -> None:
    proc = _run(tmp_path, "--repo", str(workspace), "--path", RULES)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == COMMITTED_RULES
    assert f"{len(COMMITTED_RULES)} bytes".encode() in proc.stderr
    assert b"at HEAD (" in proc.stderr


def test_dirty_working_tree_copy_is_not_what_gets_injected(
    tmp_path: Path, workspace: Path
) -> None:
    (workspace / RULES).write_bytes(DIRTY_RULES)
    # Control: the old read, a plain file read, sees the peer's edit. Without
    # this the assertion below could pass on a fixture that was never dirty.
    assert (workspace / RULES).read_bytes() == DIRTY_RULES

    proc = _run(tmp_path, "--repo", str(workspace), "--path", RULES)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == COMMITTED_RULES
    assert b"peer session" not in proc.stdout
    assert b"working-tree copy differs and was NOT read" in proc.stderr


def test_dirty_and_staged_copy_is_not_injected_either(
    tmp_path: Path, workspace: Path
) -> None:
    (workspace / RULES).write_bytes(DIRTY_RULES)
    subprocess.run(
        ["git", "-C", str(workspace), "add", RULES],
        check=True,
        env={**scrub_git_location_env(os.environ), **_isolated(tmp_path)},
    )
    proc = _run(tmp_path, "--repo", str(workspace), "--path", RULES)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == COMMITTED_RULES


def test_clean_tree_reports_no_difference(tmp_path: Path, workspace: Path) -> None:
    proc = _run(tmp_path, "--repo", str(workspace), "--path", RULES)
    assert b"differs" not in proc.stderr


def test_brief_resolves_by_stem_from_the_committed_tree(
    tmp_path: Path, workspace: Path
) -> None:
    proc = _run(
        tmp_path, "--repo", str(workspace), "--dir", BRIEFS, "--stem", "hourly-tick"
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == b"// committed brief\n"


def test_dirty_untracked_brief_is_never_dispatched(
    tmp_path: Path, workspace: Path
) -> None:
    (workspace / BRIEFS / "merge-sweep.js").write_text("// untracked, uncommitted\n")
    assert (workspace / BRIEFS / "merge-sweep.js").is_file()  # control: it is on disk
    proc = _run(
        tmp_path, "--repo", str(workspace), "--dir", BRIEFS, "--stem", "merge-sweep"
    )
    assert proc.returncode == 2
    assert proc.stdout == b""
    assert b"0 committed entries" in proc.stderr


@pytest.mark.parametrize(
    ("args", "fragment"),
    [
        (("--path", "missing.md"), b"is not committed"),
        (("--path", "empty.md"), b"committed empty"),
        (("--path", RULES, "--ref", "no-such-ref"), b"does not resolve"),
    ],
)
def test_refusals_exit_2_and_print_nothing(
    tmp_path: Path, workspace: Path, args: tuple[str, ...], fragment: bytes
) -> None:
    proc = _run(tmp_path, "--repo", str(workspace), *args)
    assert proc.returncode == 2
    assert proc.stdout == b""
    assert fragment in proc.stderr


def test_a_repository_that_is_not_one_refuses(tmp_path: Path) -> None:
    proc = _run(tmp_path, "--repo", str(tmp_path / "nowhere"), "--path", RULES)
    assert proc.returncode == 2
    assert proc.stdout == b""


@pytest.mark.parametrize("name", ["prompt.md", "SKILL.md"])
def test_lane_dispatch_reads_rules_and_brief_through_the_helper(name: str) -> None:
    text = (_LANE_DISPATCH / name).read_text(encoding="utf-8")
    assert "scripts/read_committed_file.py" in text
    assert "--path <rules_block_path>" in text
    assert "--dir <brief_directory> --stem <brief>" in text


def test_lane_dispatch_no_longer_reads_the_rules_block_from_disk() -> None:
    prompt = (_LANE_DISPATCH / "prompt.md").read_text(encoding="utf-8")
    assert "Read `rules_block_path` in full" not in prompt
