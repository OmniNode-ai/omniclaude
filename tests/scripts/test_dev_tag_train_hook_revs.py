# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-22636: the sibling-pin train moves the core hook revs with the core source pin.

omniclaude#3188 moved the omnibase-core source tag to the newest green tag and left the
omnibase_core hook blocks of ``.pre-commit-config.yaml`` behind, so the pin-floor tests failed
(a hook older than the pin) and setting the hooks to the pin's tag was refused by first-party-ref
(one home per tag literal). The one state that passes both is a hook strictly newer than the pin.
These tests pin that the train plans it and writes it, through omnimarket's
``node_sibling_pin_hook_revs_compute``.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest
from omnibase_core.validators.no_unguarded_git_subprocess import scrub_git_location_env

pytestmark = pytest.mark.unit

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "relock_git_sources.py"
_CORE_URL = "https://github.com/OmniNode-ai/omnibase_core.git"
_CORE_REPO_URL = "https://github.com/OmniNode-ai/omnibase_core"
_OTHER_URL = "https://github.com/OmniNode-ai/omnibase_infra"
_STAMPS = [
    "20261101000000",
    "20261102000000",
    "20261103000000",
    "20261104000000",
    "20261105000000",
]


def _load():
    spec = importlib.util.spec_from_file_location("relock_git_sources", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["relock_git_sources"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def mod():
    return _load()


def _git(cwd: Path, *args: str) -> str:
    identity = ["-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    return subprocess.run(
        ["git", "-C", str(cwd), *identity, *args],
        check=True,
        capture_output=True,
        text=True,
        env=scrub_git_location_env(os.environ),
    ).stdout.strip()


def _core_clone(root: Path) -> dict[str, str]:
    """A core clone with one dev tag per stamp; returns tag -> sha."""
    clone = root / "omnibase_core"
    clone.mkdir(parents=True)
    _git(clone, "init", "-q", "-b", "dev")
    tags: dict[str, str] = {}
    for stamp in _STAMPS:
        (clone / "f").write_text(stamp)
        _git(clone, "add", "f")
        _git(clone, "commit", "-q", "-m", stamp)
        sha = _git(clone, "rev-parse", "HEAD")
        tag = f"dev-{stamp}-{sha[:12]}"
        _git(clone, "tag", tag)
        tags[tag] = sha
    return tags


def _consumer(root: Path, pin: str, hook_revs: list[str]) -> tuple[Path, Path]:
    """A consumer whose core source pin is ``pin`` and whose pre-commit file holds a core
    hook block per rev in ``hook_revs``, with an unrelated block and a comment between."""
    pyproject = root / "pyproject.toml"
    pyproject.write_text(
        "[project]\n"
        'name = "consumer"\n'
        'version = "0.0.0"\n'
        'dependencies = ["omnibase-core>=0.47.0"]\n'
        "\n"
        "[tool.uv.sources]\n"
        f'omnibase-core = {{ git = "{_CORE_URL}", tag = "{pin}" }}\n'
    )
    blocks = "".join(
        f"  # a comment above block {i}\n"
        f"  - repo: {_CORE_REPO_URL}\n"
        f"    rev: {rev}  # trailing comment\n"
        f"    hooks:\n"
        f"      - id: hook-{i}\n"
        for i, rev in enumerate(hook_revs)
    )
    config = root / ".pre-commit-config.yaml"
    config.write_text(
        "repos:\n"
        f"  - repo: {_OTHER_URL}\n"
        "    rev: dev-20261101000000-aaaaaaaaaaaa\n"
        "    hooks:\n"
        "      - id: other\n" + blocks
    )
    return pyproject, config


def _node_free_mover(path: Path, pin, new_tag: str) -> None:
    path.write_text(path.read_text().replace(pin.tag, new_tag))


def _source_tag(pyproject: Path) -> str:
    return next(
        line.split('tag = "')[1].split('"')[0]
        for line in pyproject.read_text().splitlines()
        if line.startswith("omnibase-core =")
    )


def _hook_revs(mod, config: Path) -> list[str]:
    """The rev of every core hook block, in file order."""
    revs: list[str] = []
    in_core = False
    for line in config.read_text().splitlines():
        if line.strip().startswith("- repo:"):
            in_core = line.split()[-1] == _CORE_REPO_URL
        elif in_core and line.strip().startswith("rev:"):
            revs.append(line.split()[1])
    return revs


def test_hook_stamp_ends_strictly_above_the_pin_stamp(mod, tmp_path: Path) -> None:
    clones = tmp_path / "clones"
    tags = _core_clone(clones)
    names = list(tags)
    # The pin and the core hook blocks sit at the same tag, as they did before the train ran.
    pyproject, config = _consumer(tmp_path, names[0], [names[0], names[0]])

    plan = mod.run_dev_tag_train(
        pyproject=pyproject,
        registry_root=str(clones),
        is_green=lambda repo, sha: True,
        mover=_node_free_mover,
        apply=True,
    )

    assert _hook_revs(mod, config) == [names[4], names[4]]
    assert _source_tag(pyproject) == names[3]
    assert mod.dev_merge_tag_stamp(names[4]) > mod.dev_merge_tag_stamp(names[3])
    [move] = plan.moves
    assert (move.old_tag, move.new_tag) == (names[0], names[3])
    assert (move.hook_tag, move.hook_blocks) == (names[4], 2)


def test_a_red_newest_tag_is_passed_over_for_both_homes(mod, tmp_path: Path) -> None:
    clones = tmp_path / "clones"
    tags = _core_clone(clones)
    names = list(tags)
    pyproject, config = _consumer(tmp_path, names[0], [names[0]])

    mod.run_dev_tag_train(
        pyproject=pyproject,
        registry_root=str(clones),
        is_green=lambda repo, sha: sha != tags[names[4]],
        mover=_node_free_mover,
        apply=True,
    )

    assert _hook_revs(mod, config) == [names[3]]
    assert _source_tag(pyproject) == names[2]


def test_a_hook_block_older_than_the_pin_is_left_alone(mod, tmp_path: Path) -> None:
    clones = tmp_path / "clones"
    tags = _core_clone(clones)
    names = list(tags)
    pyproject, config = _consumer(tmp_path, names[2], [names[0], names[2]])

    mod.run_dev_tag_train(
        pyproject=pyproject,
        registry_root=str(clones),
        is_green=lambda repo, sha: True,
        mover=_node_free_mover,
        apply=True,
    )

    assert _hook_revs(mod, config) == [names[0], names[4]]
    assert _source_tag(pyproject) == names[3]


def test_hook_move_keeps_comments_and_unrelated_blocks(mod, tmp_path: Path) -> None:
    clones = tmp_path / "clones"
    tags = _core_clone(clones)
    names = list(tags)
    pyproject, config = _consumer(tmp_path, names[0], [names[0]])
    before = config.read_text()

    mod.run_dev_tag_train(
        pyproject=pyproject,
        registry_root=str(clones),
        is_green=lambda repo, sha: True,
        mover=_node_free_mover,
        apply=True,
    )

    assert config.read_text() == before.replace(
        f"rev: {names[0]}  # trailing comment", f"rev: {names[4]}  # trailing comment"
    )


def test_dry_run_plans_the_hooks_and_writes_neither_file(mod, tmp_path: Path) -> None:
    clones = tmp_path / "clones"
    tags = _core_clone(clones)
    names = list(tags)
    pyproject, config = _consumer(tmp_path, names[0], [names[0]])
    before = (pyproject.read_bytes(), config.read_bytes())

    plan = mod.run_dev_tag_train(
        pyproject=pyproject,
        registry_root=str(clones),
        is_green=lambda repo, sha: True,
        mover=_node_free_mover,
        apply=False,
    )

    assert (pyproject.read_bytes(), config.read_bytes()) == before
    assert [(m.new_tag, m.hook_tag) for m in plan.moves] == [(names[3], names[4])]


def test_no_hook_blocks_moves_the_pin_to_the_newest_green_tag(
    mod, tmp_path: Path
) -> None:
    clones = tmp_path / "clones"
    tags = _core_clone(clones)
    names = list(tags)
    pyproject, config = _consumer(tmp_path, names[0], [])

    plan = mod.run_dev_tag_train(
        pyproject=pyproject,
        registry_root=str(clones),
        is_green=lambda repo, sha: True,
        mover=_node_free_mover,
        apply=True,
    )

    assert _source_tag(pyproject) == names[4]
    assert [(m.new_tag, m.hook_tag, m.hook_blocks) for m in plan.moves] == [
        (names[4], None, 0)
    ]


def test_pr_body_names_the_hook_move(mod, tmp_path: Path) -> None:
    clones = tmp_path / "clones"
    tags = _core_clone(clones)
    names = list(tags)
    pyproject, _ = _consumer(tmp_path, names[0], [names[0]])

    plan = mod.run_dev_tag_train(
        pyproject=pyproject,
        registry_root=str(clones),
        is_green=lambda repo, sha: True,
        mover=_node_free_mover,
        apply=False,
    )

    body = mod.render_pr_body(plan)
    assert f"`{names[3]}`" in body
    assert f"{1} hook block(s) to `{names[4]}`" in body


def test_hooks_stay_when_no_green_tag_sits_under_them(mod, tmp_path: Path) -> None:
    clones = tmp_path / "clones"
    tags = _core_clone(clones)
    names = list(tags)
    pyproject, config = _consumer(tmp_path, names[0], [names[0]])
    before = (pyproject.read_bytes(), config.read_bytes())

    plan = mod.run_dev_tag_train(
        pyproject=pyproject,
        registry_root=str(clones),
        is_green=lambda repo, sha: sha == tags[names[1]],
        mover=_node_free_mover,
        apply=True,
    )

    # The only green tag would equal the hook's stamp, which first-party-ref refuses.
    assert plan.moves == [] and plan.unchanged == ["omnibase-core"]
    assert (pyproject.read_bytes(), config.read_bytes()) == before
