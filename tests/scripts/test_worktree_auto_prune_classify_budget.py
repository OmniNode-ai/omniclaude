# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The per-worktree classification budget [OMN-19399].

On 2026-09-26 the unattended prune sat at ``classified 400/686`` for over 30
minutes at host load ~80: each git probe was capped at 60 s, but one worktree
runs about a dozen of them in sequence and nothing bounded the total. These
tests pin the fix: once a worktree's budget is spent its remaining probes are
not run, the row is ``timed_out`` (never removed), and the scan moves on to the
next worktree.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import time
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType

import pytest

from omniclaude.hooks.lib.worktree_prune_policy import (
    EnumPruneBlockReason,
    EnumPruneDisposition,
)

pytestmark = pytest.mark.unit

_MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "worktree_auto_prune.py"
)


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "worktree_auto_prune_budget", _MODULE_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = _load_module()


@pytest.fixture(autouse=True)
def _scratch_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OMNI_HOME", str(tmp_path / "scratch_registry"))


def scrub_git_location_env(env: Mapping[str, str]) -> dict[str, str]:
    """Drop the git location variables that OVERRIDE ``git -C`` (OMN-18434)."""
    scrubbed = dict(env)
    for key in (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_COMMON_DIR",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    ):
        scrubbed.pop(key, None)
    return scrubbed


_GIT_ENV = {
    **{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
    "GIT_AUTHOR_NAME": "omn19399",
    "GIT_COMMITTER_NAME": "omn19399",
    "GIT_AUTHOR_EMAIL": "omn19399@example.invalid",
    "GIT_COMMITTER_EMAIL": "omn19399@example.invalid",
}


def _git_ok(cwd: Path, *args: str) -> None:
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        env=scrub_git_location_env(_GIT_ENV),
        check=False,
        timeout=60,
    )
    assert proc.returncode == 0, f"git {' '.join(args)} failed: {proc.stderr}"


@pytest.fixture
def worktree_pair(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A canonical clone with two clean worktrees under ``omni_worktrees``."""
    canonical = tmp_path / "canonical" / "omnibase_infra"
    canonical.mkdir(parents=True)
    _git_ok(canonical, "init", "-q", "-b", "dev")
    (canonical / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git_ok(canonical, "add", "-A")
    _git_ok(canonical, "commit", "-q", "-m", "init")
    root = tmp_path / "omni_worktrees"
    first = root / "OMN-1" / "omnibase_infra"
    second = root / "OMN-2" / "omnibase_infra"
    for path, branch in ((first, "wt-one"), (second, "wt-two")):
        path.parent.mkdir(parents=True)
        _git_ok(canonical, "worktree", "add", "-q", str(path), "-b", branch)
    return root, first, second


def _collect(worktree: Path, root: Path, deadline: float | None):  # noqa: ANN202
    return mod.collect_facts(
        worktree,
        root,
        {},
        {},
        {},
        {},
        None,
        None,
        deadline=deadline,
    )


class TestGitRunDeadline:
    def test_a_spent_deadline_runs_nothing_and_reports_a_timeout(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spawned: list[object] = []
        monkeypatch.setattr(
            mod.subprocess, "run", lambda *a, **k: spawned.append(a) or None
        )
        monkeypatch.setattr(mod, "host_load_average", lambda: 83.0)

        result = mod._git_run(
            tmp_path, "status", "--porcelain", deadline=time.monotonic() - 1
        )

        assert spawned == [], "a probe past the budget must not be spawned"
        assert result.timed_out is True
        assert result.ok is False
        assert result.stderr == mod.BUDGET_EXHAUSTED_STDERR
        assert result.load_average == 83.0

    def test_the_time_left_caps_the_probe_timeout(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[int] = []

        def fake_run(*_a: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            timeout = kwargs["timeout"]
            assert isinstance(timeout, int)
            seen.append(timeout)
            return subprocess.CompletedProcess([], 0, "", "")

        monkeypatch.setattr(mod.subprocess, "run", fake_run)

        mod._git_run(tmp_path, "status", deadline=time.monotonic() + 5)
        mod._git_run(tmp_path, "status", deadline=None)

        assert 1 <= seen[0] <= 5, "the probe may not outlive the worktree's budget"
        assert seen[1] == mod.GIT_TIMEOUT_SECONDS


class TestCollectFactsBudget:
    def test_a_spent_budget_makes_the_row_timed_out_not_prunable(
        self, worktree_pair: tuple[Path, Path, Path]
    ) -> None:
        root, first, _ = worktree_pair

        facts = _collect(first, root, deadline=time.monotonic() - 1)
        decision = mod.classify_worktree_prune(facts)

        assert "git status --porcelain" in facts.timed_out_probes
        assert "git branch --show-current" in facts.timed_out_probes
        assert decision.disposition is EnumPruneDisposition.TIMED_OUT
        assert EnumPruneBlockReason.PROBE_TIMEOUT in decision.block_reasons
        assert first.is_dir()

    def test_with_budget_left_the_same_tree_classifies_normally(
        self, worktree_pair: tuple[Path, Path, Path]
    ) -> None:
        """Positive control: the budget, not the fixture, produced the timeout."""
        root, first, _ = worktree_pair

        facts = _collect(first, root, deadline=time.monotonic() + 120)

        assert facts.timed_out_probes == ()
        assert facts.unreadable_probes == ()
        assert facts.branch == "wt-one"
        assert facts.dirty_files == ()

    def test_the_rescue_only_mtime_walk_stops_at_the_deadline(
        self, worktree_pair: tuple[Path, Path, Path]
    ) -> None:
        _, first, _ = worktree_pair
        now = time.time()

        assert (
            mod.newest_git_visible_mtime_age_days(
                first, now, deadline=time.monotonic() - 1
            )
            is None
        )
        assert (
            mod.newest_git_visible_mtime_age_days(
                first, now, deadline=time.monotonic() + 120
            )
            is not None
        )


class TestScanMovesOn:
    def test_one_stuck_worktree_is_timed_out_and_the_next_is_classified(
        self,
        worktree_pair: tuple[Path, Path, Path],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The falsifier for the 2026-09-26 stall, end to end through main()."""
        root, first, second = worktree_pair
        real_run = mod._git_run
        clock = {"now": 1000.0}

        def fake_monotonic() -> float:
            return clock["now"]

        def fake_git_run(
            cwd: Path,
            *args: str,
            timeout: int = mod.GIT_TIMEOUT_SECONDS,
            deadline: float | None = None,
        ):  # noqa: ANN202
            # The FIRST worktree's status probe hangs: it burns the whole
            # budget. Every other probe answers normally.
            if Path(cwd) == first and args[:1] == ("status",):
                clock["now"] += 10_000
            return real_run(cwd, *args, timeout=timeout, deadline=deadline)

        monkeypatch.setattr(mod.time, "monotonic", fake_monotonic)
        monkeypatch.setattr(mod, "_git_run", fake_git_run)

        report = tmp_path / "report.json"
        ledger = tmp_path / "ledger.md"
        ledger.write_text("", encoding="utf-8")
        code = mod.main(
            [
                "--worktrees-root",
                str(root),
                "--ledger",
                str(ledger),
                "--no-tracker",
                "--no-pr-state",
                "--no-debris",
                "--no-checkpoint",
                "--worktree-budget-seconds",
                "30",
                "--report-json",
                str(report),
            ]
        )

        assert code == 0
        out = capsys.readouterr().out
        assert f"budget 30s spent on {first}" in out
        assert "classified 2/2" in out
        import json

        rows = {
            row["path"]: row
            for row in json.loads(report.read_text(encoding="utf-8"))["decisions"]
        }
        assert rows[str(first)]["disposition"] == "timed_out"
        assert rows[str(second)]["disposition"] != "timed_out"
        assert first.is_dir() and second.is_dir(), "a dry run removes nothing"
