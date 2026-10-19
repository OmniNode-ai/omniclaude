# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-19998: the nightly sibling-pin train in ``scripts/relock_git_sources.py``.

RULING 2026-10-19T10:11:00Z: once a night, one bump per consumer moving every
internal sibling pinned by dev merge tag to its newest dev merge tag whose dev
CI is green. These tests pin the choice (newest green, forward only, never a
red or unread tag), the plan for a consumer with several tag pins, and that the
rewrite goes through omnimarket's ``node_dev_tag_pin_mover_compute``.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from omnibase_core.validators.no_unguarded_git_subprocess import scrub_git_location_env

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "relock_git_sources.py"
_CORE_URL = "https://github.com/OmniNode-ai/omnibase_core.git"
_INFRA_URL = "https://github.com/OmniNode-ai/omnibase_infra.git"


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


def _clone_with_tags(root: Path, repo: str, stamps: list[str]) -> dict[str, str]:
    """A clone at ``root/repo`` with one commit and one dev tag per stamp."""
    clone = root / repo
    clone.mkdir(parents=True)
    _git(clone, "init", "-q", "-b", "dev")
    tags: dict[str, str] = {}
    for stamp in stamps:
        (clone / "f").write_text(stamp)
        _git(clone, "add", "f")
        _git(clone, "commit", "-q", "-m", stamp)
        sha = _git(clone, "rev-parse", "HEAD")
        tag = f"dev-{stamp}-{sha[:12]}"
        _git(clone, "tag", tag)
        tags[tag] = sha
    return tags


def _pyproject(path: Path, sources: str) -> Path:
    path.write_text(
        "[project]\n"
        'name = "consumer"\n'
        'version = "0.0.0"\n'
        'dependencies = ["omnibase-core>=0.47.0", "omnibase-infra>=0.38.0"]\n'
        "\n"
        "[tool.uv.sources]\n"
        f"{sources}"
    )
    return path


def test_parse_dev_tag_pins_reads_only_omninode_tag_pins(mod, tmp_path: Path) -> None:
    text = _pyproject(
        tmp_path / "pyproject.toml",
        f'omnibase-core = {{ git = "{_CORE_URL}", tag = "dev-20261019000000-aaaaaaaaaaaa" }}\n'
        'omnimarket = { git = "https://github.com/OmniNode-ai/omnimarket.git", rev = "'
        + "a"
        * 40
        + '" }\n'
        'other = { git = "https://github.com/someone/other.git", tag = "dev-20261019000000-bbbbbbbbbbbb" }\n'
        f'omnibase-infra = {{ git = "{_INFRA_URL}", tag = "v0.38.29" }}\n',
    ).read_text()
    pins = mod.parse_dev_tag_pins(text)
    assert [(p.distribution, p.repo, p.tag) for p in pins] == [
        ("omnibase-core", "omnibase_core", "dev-20261019000000-aaaaaaaaaaaa"),
    ]


def test_pick_newest_green_tag_skips_red_and_unread(mod, tmp_path: Path) -> None:
    tags = _clone_with_tags(
        tmp_path / "clones",
        "omnibase_core",
        ["20261019010000", "20261019020000", "20261019030000", "20261019040000"],
    )
    names = list(tags)
    pin = mod.ModelDevTagPin(
        distribution="omnibase-core",
        repo="omnibase_core",
        url=_CORE_URL,
        tag=names[0],
    )
    verdicts = {tags[names[1]]: True, tags[names[2]]: True, tags[names[3]]: False}

    def green(repo: str, sha: str) -> bool | None:
        assert repo == "omnibase_core"
        return verdicts.get(sha)

    choice = mod.pick_train_tag(
        pin=pin, clone=tmp_path / "clones" / "omnibase_core", is_green=green
    )
    assert choice.new_tag == names[2]
    assert choice.examined == [names[3], names[2]]
    assert choice.skipped == {names[3]: "red"}


def test_pick_never_moves_backwards_or_to_unread(mod, tmp_path: Path) -> None:
    tags = _clone_with_tags(
        tmp_path / "clones", "omnibase_core", ["20261019010000", "20261019020000"]
    )
    names = list(tags)
    pin = mod.ModelDevTagPin(
        distribution="omnibase-core", repo="omnibase_core", url=_CORE_URL, tag=names[1]
    )
    choice = mod.pick_train_tag(
        pin=pin, clone=tmp_path / "clones" / "omnibase_core", is_green=lambda r, s: True
    )
    assert choice.new_tag is None
    assert choice.examined == []

    pin_old = dataclasses.replace(pin, tag=names[0])
    unread = mod.pick_train_tag(
        pin=pin_old,
        clone=tmp_path / "clones" / "omnibase_core",
        is_green=lambda r, s: None,
    )
    assert unread.new_tag is None
    assert unread.skipped == {names[1]: "unread"}


def test_check_runs_verdict(mod) -> None:
    assert mod.check_runs_verdict([]) is None
    assert mod.check_runs_verdict([("completed", "success"), ("completed", "skipped")])
    assert (
        mod.check_runs_verdict([("completed", "success"), ("in_progress", "")]) is None
    )
    assert (
        mod.check_runs_verdict([("completed", "success"), ("completed", "failure")])
        is False
    )
    assert mod.check_runs_verdict([("completed", "cancelled")]) is False


def test_train_moves_every_pin_in_one_plan_through_the_mover(
    mod, tmp_path: Path
) -> None:
    clones = tmp_path / "clones"
    core = _clone_with_tags(
        clones, "omnibase_core", ["20261019010000", "20261019020000"]
    )
    infra = _clone_with_tags(
        clones, "omnibase_infra", ["20261019010000", "20261019020000"]
    )
    core_names, infra_names = list(core), list(infra)
    pyproject = _pyproject(
        tmp_path / "pyproject.toml",
        f'omnibase-core = {{ git = "{_CORE_URL}", tag = "{core_names[0]}" }}\n'
        f'omnibase-infra = {{ git = "{_INFRA_URL}", tag = "{infra_names[1]}" }}\n',
    )
    calls: list[tuple[str, str, str]] = []

    def mover(path: Path, pin, new_tag: str) -> None:
        calls.append((pin.distribution, pin.tag, new_tag))
        path.write_text(path.read_text().replace(pin.tag, new_tag))

    plan = mod.run_dev_tag_train(
        pyproject=pyproject,
        registry_root=str(clones),
        is_green=lambda r, s: True,
        mover=mover,
        apply=True,
    )
    assert calls == [("omnibase-core", core_names[0], core_names[1])]
    assert [(m.distribution, m.old_tag, m.new_tag) for m in plan.moves] == [
        ("omnibase-core", core_names[0], core_names[1]),
    ]
    assert plan.unchanged == ["omnibase-infra"]
    assert core_names[1] in pyproject.read_text()


def test_dry_run_writes_nothing(mod, tmp_path: Path) -> None:
    clones = tmp_path / "clones"
    core = _clone_with_tags(
        clones, "omnibase_core", ["20261019010000", "20261019020000"]
    )
    first = next(iter(core))
    pyproject = _pyproject(
        tmp_path / "pyproject.toml",
        f'omnibase-core = {{ git = "{_CORE_URL}", tag = "{first}" }}\n',
    )
    before = pyproject.read_bytes()

    def mover(path: Path, pin, new_tag: str) -> None:
        raise AssertionError("dry run called the mover")

    plan = mod.run_dev_tag_train(
        pyproject=pyproject,
        registry_root=str(clones),
        is_green=lambda r, s: True,
        mover=mover,
        apply=False,
    )
    assert len(plan.moves) == 1
    assert pyproject.read_bytes() == before


def test_missing_clone_is_a_refusal_not_a_skip(mod, tmp_path: Path) -> None:
    pyproject = _pyproject(
        tmp_path / "pyproject.toml",
        f'omnibase-core = {{ git = "{_CORE_URL}", tag = "dev-20261019000000-aaaaaaaaaaaa" }}\n',
    )
    with pytest.raises(mod.ErrorRelock, match="no canonical clone"):
        mod.run_dev_tag_train(
            pyproject=pyproject,
            registry_root=str(tmp_path / "nowhere"),
            is_green=lambda r, s: True,
            mover=lambda *a: None,
            apply=False,
        )


def test_mover_command_names_the_omnimarket_node(mod, tmp_path: Path) -> None:
    pin = mod.ModelDevTagPin(
        distribution="omnibase-core",
        repo="omnibase_core",
        url=_CORE_URL,
        tag="dev-20261019000000-aaaaaaaaaaaa",
    )
    argv = mod.mover_argv(
        tmp_path / "pyproject.toml", pin, "dev-20261019010000-bbbbbbbbbbbb"
    )
    assert argv[1:4] == [
        "-m",
        "omnimarket.nodes.node_dev_tag_pin_mover_compute",
        "--pyproject",
    ]
    assert argv[argv.index("--tests") + 1] == "not_run"
    assert argv[argv.index("--repository-url") + 1] == _CORE_URL


def test_plan_json_lists_moves(mod, tmp_path: Path) -> None:
    plan = mod.ModelTrainPlan(
        moves=[
            mod.ModelTrainMove(
                distribution="omnibase-core",
                repo="omnibase_core",
                old_tag="dev-20261019000000-aaaaaaaaaaaa",
                new_tag="dev-20261019010000-bbbbbbbbbbbb",
            )
        ],
        unchanged=["omnibase-infra"],
        skipped={},
    )
    data = json.loads(plan.to_json())
    assert data["moves"][0]["new_tag"] == "dev-20261019010000-bbbbbbbbbbbb"
