# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for the Mac worktree_reaper.py (OMN-13228, T4 of OMN-13008).

The reaper reads the onex.evt.github.pr-merged.v1 projection over HTTP and drives
the canonical prune-worktrees.sh (this repo) for each newly-merged PR since a
persisted cursor. All HTTP and subprocess I/O is injected, so these tests make no
network calls and spawn no real subprocesses.

DoD coverage (per the T4 ticket):
  (a) a merged-PR-with-clean-worktree row is passed to prune-worktrees.sh,
  (b) a dirty/unpushed worktree is SKIPPED (prune reports non-zero; the reaper does
      NOT advance and never deletes it itself),
  (c) the cursor advances ONLY on a fully-successful execute pass,
  (d) dry-run never deletes (prune invoked without --execute) and never advances.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

_MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "worktree_reaper.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("worktree_reaper", _MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


worktree_reaper = _load_module()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _projection_body(rows: list[dict[str, object]], next_cursor: int) -> str:
    return json.dumps({"rows": rows, "next_cursor": next_cursor})


def _row(
    pr_number: int = 101,
    cursor: int = 5,
    repo: str = "OmniNode-ai/omniclaude",
    branch: str = "jonah/omn-1-feature",
) -> dict[str, object]:
    return {
        "repo": repo,
        "branch": branch,
        "pr_number": pr_number,
        "ticket": "OMN-1",
        "merged_at": "2026-06-18T12:00:00Z",
        "projection_cursor": cursor,
    }


class _PruneRecorder:
    """Injectable prune runner that records argv and returns a scripted exit code."""

    def __init__(self, exit_code: int = 0, output: str = "OK") -> None:
        self.exit_code = exit_code
        self.output = output
        self.calls: list[list[str]] = []

    def __call__(self, argv, cwd):  # type: ignore[no-untyped-def]
        self.calls.append(list(argv))
        return self.exit_code, self.output

    @property
    def executed_with_delete(self) -> bool:
        return any("--execute" in call for call in self.calls)


def _opener_for(body: str):  # type: ignore[no-untyped-def]
    def _opener(url: str, timeout: float) -> str:
        return body

    return _opener


@pytest.fixture
def root(tmp_path: Path) -> Path:
    d = tmp_path / "omni_worktrees"
    d.mkdir()
    return d


@pytest.fixture
def prune_script(tmp_path: Path) -> Path:
    p = tmp_path / "prune-worktrees.sh"
    p.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    return p


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    return tmp_path / "state"


# ---------------------------------------------------------------------------
# (a) merged-PR-with-clean-worktree → passed to prune-worktrees.sh
# ---------------------------------------------------------------------------
def test_merged_clean_row_drives_prune_script(
    root: Path, prune_script: Path, state_dir: Path
) -> None:
    recorder = _PruneRecorder(exit_code=0, output="Removed stale worktree")
    body = _projection_body([_row(pr_number=101, cursor=7)], next_cursor=7)

    outcome = worktree_reaper.run_reaper(
        base_url="http://projection.test",  # onex-allow-internal-ip
        state_dir=state_dir,
        roots=[root],
        prune_script=prune_script,
        execute=True,
        opener=_opener_for(body),
        runner=recorder,
    )

    assert outcome
    assert outcome.rows_seen == 1
    assert outcome.rows_reaped_ok == 1
    assert len(recorder.calls) == 1
    argv = recorder.calls[0]
    assert "bash" in argv[0]
    assert str(prune_script) in argv
    assert "--worktrees-root" in argv
    assert str(root) in argv
    assert "--execute" in argv


# ---------------------------------------------------------------------------
# (b) dirty/unpushed worktree → SKIPPED → no advance
# ---------------------------------------------------------------------------
def test_dirty_or_unpushed_worktree_is_skipped(
    root: Path, prune_script: Path, state_dir: Path
) -> None:
    recorder = _PruneRecorder(exit_code=2, output="SKIP: working tree dirty")
    body = _projection_body([_row(pr_number=202, cursor=9)], next_cursor=9)
    worktree_reaper.write_cursor(state_dir, 3)

    outcome = worktree_reaper.run_reaper(
        base_url="http://projection.test",  # onex-allow-internal-ip
        state_dir=state_dir,
        roots=[root],
        prune_script=prune_script,
        execute=True,
        opener=_opener_for(body),
        runner=recorder,
    )

    assert outcome.rows_reaped_ok == 0
    assert outcome.cursor_advanced is False
    assert outcome.cursor_after == 3
    assert worktree_reaper.read_cursor(state_dir) == 3


# ---------------------------------------------------------------------------
# (c) cursor advances ONLY on a fully-successful execute pass
# ---------------------------------------------------------------------------
def test_cursor_advances_only_on_full_success(
    root: Path, prune_script: Path, state_dir: Path
) -> None:
    recorder = _PruneRecorder(exit_code=0, output="OK")
    body = _projection_body(
        [_row(pr_number=301, cursor=11), _row(pr_number=302, cursor=12)],
        next_cursor=12,
    )
    worktree_reaper.write_cursor(state_dir, 4)

    outcome = worktree_reaper.run_reaper(
        base_url="http://projection.test",  # onex-allow-internal-ip
        state_dir=state_dir,
        roots=[root],
        prune_script=prune_script,
        execute=True,
        opener=_opener_for(body),
        runner=recorder,
    )

    assert outcome.cursor_advanced is True
    assert outcome.cursor_before == 4
    assert outcome.cursor_after == 12
    assert worktree_reaper.read_cursor(state_dir) == 12


def test_cursor_does_not_advance_when_one_of_many_rows_fails(
    root: Path, prune_script: Path, state_dir: Path
) -> None:
    class _FailSecond:
        def __init__(self) -> None:
            self.n = 0
            self.calls: list[list[str]] = []

        def __call__(self, argv, cwd):  # type: ignore[no-untyped-def]
            self.calls.append(list(argv))
            self.n += 1
            return (0, "OK") if self.n == 1 else (2, "boom")

    runner = _FailSecond()
    body = _projection_body(
        [_row(pr_number=401, cursor=20), _row(pr_number=402, cursor=21)],
        next_cursor=21,
    )
    worktree_reaper.write_cursor(state_dir, 10)

    outcome = worktree_reaper.run_reaper(
        base_url="http://projection.test",  # onex-allow-internal-ip
        state_dir=state_dir,
        roots=[root],
        prune_script=prune_script,
        execute=True,
        opener=_opener_for(body),
        runner=runner,
    )

    assert outcome.cursor_advanced is False
    assert worktree_reaper.read_cursor(state_dir) == 10


# ---------------------------------------------------------------------------
# (d) dry-run never deletes and never advances
# ---------------------------------------------------------------------------
def test_dry_run_never_deletes_or_advances(
    root: Path, prune_script: Path, state_dir: Path
) -> None:
    recorder = _PruneRecorder(exit_code=0, output="would remove (dry-run)")
    body = _projection_body([_row(pr_number=501, cursor=30)], next_cursor=30)
    worktree_reaper.write_cursor(state_dir, 2)

    outcome = worktree_reaper.run_reaper(
        base_url="http://projection.test",  # onex-allow-internal-ip
        state_dir=state_dir,
        roots=[root],
        prune_script=prune_script,
        execute=False,
        opener=_opener_for(body),
        runner=recorder,
    )

    assert outcome.dry_run is True
    assert len(recorder.calls) == 1
    assert "--execute" not in recorder.calls[0]
    assert recorder.executed_with_delete is False
    assert outcome.cursor_advanced is False
    assert worktree_reaper.read_cursor(state_dir) == 2


# ---------------------------------------------------------------------------
# Extra safety / robustness
# ---------------------------------------------------------------------------
def test_projection_fetch_failure_leaves_cursor_un_advanced(
    root: Path, prune_script: Path, state_dir: Path
) -> None:
    def _boom(url: str, timeout: float) -> str:
        raise OSError("connection refused")

    worktree_reaper.write_cursor(state_dir, 17)
    outcome = worktree_reaper.run_reaper(
        base_url="http://projection.test",  # onex-allow-internal-ip
        state_dir=state_dir,
        roots=[root],
        prune_script=prune_script,
        execute=True,
        opener=_boom,
    )

    assert not outcome
    assert outcome.error.startswith("projection_fetch_failed")
    assert outcome.cursor_advanced is False
    assert worktree_reaper.read_cursor(state_dir) == 17


def test_malformed_rows_are_dropped_not_fabricated() -> None:
    body = json.dumps(
        {
            "rows": [
                {"repo": "x", "branch": "b", "pr_number": 1, "projection_cursor": 1},
                {"garbage": True},
                "not-an-object",
            ],
            "next_cursor": 1,
        }
    )
    page = worktree_reaper.parse_projection_page(body, since=0)
    assert len(page.rows) == 1
    assert page.rows[0].pr_number == 1


def test_next_cursor_never_regresses_below_since() -> None:
    body = json.dumps({"rows": [], "next_cursor": 3})
    page = worktree_reaper.parse_projection_page(body, since=10)
    assert page.next_cursor == 10


def test_prune_driven_across_all_roots(
    tmp_path: Path, prune_script: Path, state_dir: Path
) -> None:
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    root_a.mkdir()
    root_b.mkdir()
    recorder = _PruneRecorder(exit_code=0, output="OK")
    body = _projection_body([_row(pr_number=601, cursor=40)], next_cursor=40)

    worktree_reaper.run_reaper(
        base_url="http://projection.test",  # onex-allow-internal-ip
        state_dir=state_dir,
        roots=[root_a, root_b],
        prune_script=prune_script,
        execute=True,
        opener=_opener_for(body),
        runner=recorder,
    )

    rooted = {
        call[call.index("--worktrees-root") + 1]
        for call in recorder.calls
        if "--worktrees-root" in call
    }
    assert str(root_a) in rooted
    assert str(root_b) in rooted


def test_pr_merged_topic_default_is_canonical() -> None:
    # The default (no ONEX_PR_MERGED_TOPIC override) is the canonical pr-merged topic.
    assert (
        worktree_reaper._PR_MERGED_TOPIC_DEFAULT == "onex.evt.github.pr-merged.v1"
    )  # onex-allow-internal-ip


def test_build_projection_url_includes_since_and_topic() -> None:
    url = worktree_reaper.build_projection_url(
        "http://host:3002", worktree_reaper.PR_MERGED_TOPIC, 42
    )
    assert url == (
        f"http://host:3002/projection/{worktree_reaper.PR_MERGED_TOPIC}?since=42"
    )


def test_resolve_projection_base_url_fails_fast_when_unset() -> None:
    with pytest.raises(KeyError):
        worktree_reaper.resolve_projection_base_url(env={})


def test_resolve_projection_base_url_strips_trailing_slash() -> None:
    url = worktree_reaper.resolve_projection_base_url(
        env={"ONEX_PROJECTION_URL": "http://host:3002/"}
    )
    assert url == "http://host:3002"


def test_default_roots_include_legacy_and_onex_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OMNI_HOME", str(tmp_path / "omni_home"))
    roots = worktree_reaper._resolve_roots([])
    root_strs = [str(r) for r in roots]
    assert any(r.endswith("omni_worktrees") for r in root_strs)
    assert any(".onex_state/worktrees" in r for r in root_strs)
    assert any(r.endswith("Code/omni_worktrees") for r in root_strs)
