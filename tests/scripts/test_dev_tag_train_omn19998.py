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


def _names(tmp_path: Path, stamps: list[str]) -> tuple[Path, list[str], dict[str, str]]:
    tags = _clone_with_tags(tmp_path / "clones", "omnibase_core", stamps)
    return tmp_path / "clones" / "omnibase_core", list(tags), tags


def _pin(mod, tag: str):
    return mod.ModelDevTagPin(
        distribution="omnibase-core", repo="omnibase_core", url=_CORE_URL, tag=tag
    )


def test_read_candidates_reads_newest_first_to_the_second_green(
    mod, tmp_path: Path
) -> None:
    clone, names, tags = _names(
        tmp_path,
        ["20261019010000", "20261019020000", "20261019030000", "20261019040000"],
    )
    verdicts = {tags[names[1]]: True, tags[names[2]]: True, tags[names[3]]: False}
    read = mod.read_candidates(
        pin=_pin(mod, names[0]), clone=clone, is_green=lambda r, s: verdicts.get(s)
    )
    # t4 is red, t3 and t2 are green, and t2 is the second green: the read stops there.
    assert read == [(names[3], False), (names[2], True), (names[1], True)]


def test_read_candidates_never_reads_at_or_behind_the_pin_nor_past_the_cap(
    mod, tmp_path: Path
) -> None:
    clone, names, _ = _names(
        tmp_path, ["20261019010000", "20261019020000", "20261019030000"]
    )
    pin = _pin(mod, names[2])
    assert mod.read_candidates(pin=pin, clone=clone, is_green=lambda r, s: True) == []

    seen: list[str] = []

    def unread(repo: str, sha: str) -> None:
        seen.append(sha)

    capped = mod.read_candidates(
        pin=_pin(mod, names[0]), clone=clone, is_green=unread, max_candidates=1
    )
    assert capped == [(names[2], None)]
    assert len(seen) == 1


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


def _planner(plans: dict[str, dict], calls: list | None = None):
    """A planner double that answers each distribution with its canned node plan."""

    def planner(path: Path, pin, read, apply: bool) -> dict:
        if calls is not None:
            calls.append((pin.distribution, [t for t, _ in read], apply))
        return plans[pin.distribution]

    return planner


def _plan(pin_tag: str | None, hook_tag: str | None = None) -> dict:
    return {"pin_tag": pin_tag, "hook_tag": hook_tag, "hook_indexes": [], "reason": "x"}


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
        planner=_planner(
            {"omnibase-core": _plan(core_names[1]), "omnibase-infra": _plan(None)}
        ),
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

    asked: list = []
    plan = mod.run_dev_tag_train(
        pyproject=pyproject,
        registry_root=str(clones),
        is_green=lambda r, s: True,
        mover=mover,
        planner=_planner({"omnibase-core": _plan(list(core)[1])}, asked),
        apply=False,
    )
    assert len(plan.moves) == 1
    assert [apply for _, _, apply in asked] == [False]
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
            planner=_planner({}),
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


# OMN-17427: the two homes of a git-tag pin. Verbatim from omniclaude PR #3130's
# `tests+coverage (shadow) (split 1/2)` job 126095752534 (run 41687138158):
#   FAIL: pyproject.toml:1: [stale_pin] stale_pin: omnimarket@dev-20261102102425-ce12119225dc
#   trails newest dev tag dev-20261103165554-199064721fcf by 106 merges and 30.5247 hours
# omniclaude pins omnimarket in `dependencies` (a direct URL) AND in
# `[tool.uv.sources]`. omnimarket's pin mover rewrites only the sources entry, so
# the nightly train left the dependency home at the old tag and the first-party-ref
# stale_pin rule kept reading it.
_MARKET_URL = "https://github.com/OmniNode-ai/omnimarket.git"
_STALE_TAG = "dev-20261102102425-ce12119225dc"
_NEWER_TAG = "dev-20261103165554-199064721fcf"


def _two_home_pyproject(path: Path) -> Path:
    path.write_text(
        "[project]\n"
        'name = "consumer"\n'
        'version = "0.0.0"\n'
        "dependencies = [\n"
        f'    "omnimarket @ git+{_MARKET_URL}@{_STALE_TAG}",\n'
        "]\n"
        f"# OMN-18639: an earlier bump named {_STALE_TAG} in prose; history stays.\n"
        "\n"
        "[tool.uv.sources]\n"
        f'omnimarket = {{ git = "{_MARKET_URL}", tag = "{_STALE_TAG}" }}\n'
    )
    return path


def test_node_mover_moves_the_dependency_home_with_the_source_home(
    mod, tmp_path: Path
) -> None:
    pyproject = _two_home_pyproject(tmp_path / "pyproject.toml")
    pin = mod.ModelDevTagPin(
        distribution="omnimarket", repo="omnimarket", url=_MARKET_URL, tag=_STALE_TAG
    )
    mod.node_mover(pyproject, pin, _NEWER_TAG)
    live = [
        line
        for line in pyproject.read_text().splitlines()
        if not line.lstrip().startswith("#")
    ]
    assert not [line for line in live if _STALE_TAG in line], live
    assert sum(_NEWER_TAG in line for line in live) == 2, live
    assert "history stays" in pyproject.read_text()
    assert f"named {_STALE_TAG} in prose" in pyproject.read_text()


def test_dependency_home_is_untouched_when_the_consumer_has_none(
    mod, tmp_path: Path
) -> None:
    pyproject = _pyproject(
        tmp_path / "pyproject.toml",
        f'omnimarket = {{ git = "{_MARKET_URL}", tag = "{_STALE_TAG}" }}\n',
    )
    pin = mod.ModelDevTagPin(
        distribution="omnimarket", repo="omnimarket", url=_MARKET_URL, tag=_STALE_TAG
    )
    assert mod.move_dependency_home(pyproject, pin, _NEWER_TAG) == 0


# ---------------------------------------------------------------------------
# OMN-22748: the train asks omnimarket's sibling-pin hook revs node for the plan.
#
# Recorded failure, omniclaude PR #3191 head f1d12f52d (job 128113517392): the train
# moved the core pin to dev-20261106133647-64d60448c3e3 and left the core hooks at
# dev-20261106041752-8377609527be, and the core hook floor refused it ("check-no-utcnow
# pins dev-20261106041752-8377609527be, older than the locked core
# dev-20261106133647-64d60448c3e3"). Which tag the pin takes and which the hooks take
# is the node's plan (omnimarket OMN-22641, OMN-22753), tested there; these tests hold
# what the train hands the node and what it does with the plan it gets back.
# ---------------------------------------------------------------------------

_NODE = (
    "omnimarket.nodes.node_sibling_pin_hook_revs_compute.runtime_sibling_pin_hook_revs"
)


def _train_tree(tmp_path: Path):
    clones = tmp_path / "clones"
    core = _clone_with_tags(
        clones, "omnibase_core", ["20261019010000", "20261019020000", "20261019030000"]
    )
    names = list(core)
    pyproject = _pyproject(
        tmp_path / "pyproject.toml",
        f'omnibase-core = {{ git = "{_CORE_URL}", tag = "{names[0]}" }}\n',
    )
    return clones, pyproject, names


def _train(mod, tree, planner, mover, apply: bool = True):
    clones, pyproject, _ = tree
    return mod.run_dev_tag_train(
        pyproject=pyproject,
        registry_root=str(clones),
        is_green=lambda r, s: True,
        mover=mover,
        planner=planner,
        apply=apply,
    )


def test_the_pin_takes_the_tag_the_plan_names_not_the_newest_green_tag(
    mod, tmp_path: Path
) -> None:
    """The failing control: the train before this change moved the pin to names[2], the newest tag."""
    tree = _train_tree(tmp_path)
    names = tree[2]
    moved: list[str] = []
    plan = _train(
        mod,
        tree,
        _planner({"omnibase-core": _plan(names[1], hook_tag=names[2])}),
        lambda path, pin, new_tag: moved.append(new_tag),
    )
    assert moved == [names[1]]
    assert plan.moves[0].new_tag == names[1]
    assert plan.hooks == {"omnibase-core": names[2]}
    assert "hook blocks" in mod.render_pr_body(plan)


def test_hooks_that_move_alone_leave_the_pin_where_it_was(mod, tmp_path: Path) -> None:
    tree = _train_tree(tmp_path)
    plan = _train(
        mod,
        tree,
        _planner({"omnibase-core": _plan(None, hook_tag=tree[2][2])}),
        lambda *a: pytest.fail("the pin must not move"),
    )
    assert plan.moves == []
    assert plan.unchanged == ["omnibase-core"]
    assert plan.hooks == {"omnibase-core": tree[2][2]}


def test_the_planner_is_handed_the_tags_read_newest_first_and_the_apply_flag(
    mod, tmp_path: Path
) -> None:
    tree = _train_tree(tmp_path)
    names = tree[2]
    asked: list = []
    _train(
        mod,
        tree,
        _planner({"omnibase-core": _plan(None)}, asked),
        lambda *a: None,
        apply=False,
    )
    assert asked == [("omnibase-core", [names[2], names[1]], False)]


def test_red_and_unread_tags_are_named_in_the_plan(mod, tmp_path: Path) -> None:
    clones, pyproject, names = _train_tree(tmp_path)
    shas = _tags_of(clones)
    verdict = {shas[names[2]]: False, shas[names[1]]: None}
    plan = mod.run_dev_tag_train(
        pyproject=pyproject,
        registry_root=str(clones),
        is_green=lambda r, s: verdict.get(s),
        mover=lambda *a: None,
        planner=_planner({"omnibase-core": _plan(None)}),
        apply=False,
    )
    assert plan.skipped == {"omnibase-core": {names[2]: "red", names[1]: "unread"}}


def _tags_of(clones: Path) -> dict[str, str]:
    out = _git(clones / "omnibase_core", "tag", "--list", "dev-*").split()
    return {t: _git(clones / "omnibase_core", "rev-list", "-n1", t) for t in out}


def test_node_planner_calls_the_node_and_returns_its_plan(
    mod, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[list[str]] = []

    def run(argv, **kwargs):
        seen.append(argv)
        out = json.dumps({"plan": {"pin_tag": "p", "hook_tag": "h"}, "hook_revs": []})
        return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")

    monkeypatch.setattr(mod.subprocess, "run", run)
    read = [
        ("dev-20261019020000-aaaaaaaaaaaa", True),
        ("dev-20261019010000-bbbbbbbbbbbb", None),
    ]
    pin = _pin(mod, "dev-20261019000000-cccccccccccc")
    plan = mod.node_planner(tmp_path / "pyproject.toml", pin, read, True)
    assert plan == {"pin_tag": "p", "hook_tag": "h"}
    argv = seen[0]
    assert argv[1:3] == ["-m", _NODE]
    assert argv[argv.index("--distribution") + 1] == "omnibase-core"
    assert json.loads(argv[argv.index("--candidates") + 1]) == [list(r) for r in read]
    assert argv[-1] == "--apply"
    mod.node_planner(tmp_path / "pyproject.toml", pin, read, False)
    assert "--apply" not in seen[1]


def test_node_planner_names_a_refusal_of_the_node(
    mod, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="KeyError: 'x'")

    monkeypatch.setattr(mod.subprocess, "run", run)
    with pytest.raises(mod.ErrorRelock, match="omnibase-core: KeyError"):
        mod.node_planner(
            tmp_path / "pyproject.toml",
            _pin(mod, "dev-20261019000000-cccccccccccc"),
            [],
            False,
        )


def test_script_holds_its_code_line_count_and_carries_the_node_call_site(mod) -> None:
    """The canonical-file-shape ratchet counts non-blank, non-comment lines of a baselined file."""
    code = [
        line
        for line in _SCRIPT.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert len(code) <= 502, (
        f"scripts/relock_git_sources.py grew to {len(code)} code lines"
    )
    assert callable(mod.node_planner)
