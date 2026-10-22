# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""OMN-19513: a session start never scans the turn counter directory.

Sampled on the operator Mac at 2026-10-22T01:22:34Z: four ``session.started`` writers
had each sat 8 s in uninterruptible ``stat`` inside ``hook_turn_id.prune_stale``, the
glob-and-stat of the whole counter directory (17,674 entries, shared with the reply and
usage markers) that every session start ran. A workflow starts its agents together, so
the scans queued behind each other, and the slowest emits missed their 30 s budget and
were killed before journalling: "The event was NOT recorded (nothing reached the
journal)". The scan never removed a counter there (the oldest was 27 days old, the
bound is 30). These tests pin that no emit scans the directory.
"""

from __future__ import annotations

import importlib
import os
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.unit

_LIB_DIR = Path(__file__).resolve().parents[2] / "plugins" / "onex" / "hooks" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

DAY = 24 * 3600


def _lib(name: str) -> ModuleType:
    return importlib.import_module(name)


def _counter(turn_dir: Path, name: str, age_s: float) -> Path:
    turn_dir.mkdir(parents=True, exist_ok=True)
    path = turn_dir / f"{name}.turn"
    path.write_text("3", encoding="utf-8")
    stamp = time.time() - age_s
    os.utime(path, (stamp, stamp))
    return path


def test_session_started_never_scans_the_counter_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    turn_id = _lib("hook_turn_id")
    turn_dir = tmp_path / turn_id.TURN_DIRNAME
    stale = _counter(turn_dir, "old-session", 40 * DAY)

    def scan(*_args: object, **_kwargs: object) -> int:
        raise AssertionError("session.started scanned the turn counter directory")

    monkeypatch.setattr(turn_id, "prune_stale", scan)
    got = turn_id.resolve_turn_id(
        turn_dir, event_type="session.started", session_id="s-1", host_turn_id=None
    )
    assert got is None
    assert stale.exists()


def test_a_session_start_emit_journals_without_globbing_the_counters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    turn_id = _lib("hook_turn_id")
    append = _lib("hook_emit_append")
    journal_dir = tmp_path / "hook_emit_journal"
    turn_dir = journal_dir.parent / turn_id.TURN_DIRNAME
    stale = _counter(turn_dir, "old-session", 40 * DAY)
    real_glob = Path.glob

    def guarded_glob(self: Path, pattern: str) -> Iterator[Path]:
        if self == turn_dir:
            raise AssertionError("the emit globbed the turn counter directory")
        return real_glob(self, pattern)

    monkeypatch.setattr(Path, "glob", guarded_glob)
    code = append.main(
        [
            "--event-type",
            "session.started",
            "--payload",
            "{}",
            "--session-id",
            "s-2",
            "--journal-dir",
            str(journal_dir),
        ]
    )
    assert code == 0
    assert len(list(real_glob(journal_dir, "*.json"))) == 1
    assert stale.exists()


def test_prune_stale_still_removes_only_stale_counters_when_a_maintenance_job_calls_it(
    tmp_path: Path,
) -> None:
    turn_id = _lib("hook_turn_id")
    turn_dir = tmp_path / turn_id.TURN_DIRNAME
    stale = _counter(turn_dir, "old-session", 40 * DAY)
    fresh = _counter(turn_dir, "live-session", 60)
    assert turn_id.prune_stale(turn_dir) == 1
    assert not stale.exists()
    assert fresh.exists()
