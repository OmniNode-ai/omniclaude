# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-20284 AC1: the status line's optional extension is bounded, cached and optional.

Drives the real ``plugins/onex/hooks/scripts/statusline.sh``. No network: every
service host points at a closed local port, ``HOME`` and ``ONEX_STATE_DIR`` are
temp dirs, the built-in PR segment reads a pre-seeded cache, and the extensions
are throwaway scripts.

The shell suite ``tests/hooks/test_statusline_pr_extension.sh`` widens the
budget to tolerate loaded hosts. This module pins the shipped 300 ms default
instead, using extensions that run for a second or more so the bound is
exceeded by a wide margin on any host.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
STATUSLINE = REPO_ROOT / "plugins" / "onex" / "hooks" / "scripts" / "statusline.sh"
ANSI = re.compile(r"\x1b\[[0-9;]*m")
BUILTIN_MARK = "PRs(main/dev):"

pytestmark = pytest.mark.unit


def _ext(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(f"#!/bin/bash\n{body}\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _render(
    tmp_path: Path,
    ext: str,
    cache: Path,
    budget_ms: str | None = None,
) -> tuple[list[str], float]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    pr_cache = tmp_path / "prcache.json"
    pr_cache.write_text(
        '{"schema":2,"refreshed_at":9999999999,"status":"ok",'
        '"failed":[],"repos":{"core":"0/2"}}'
    )
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(home),
        "ONEX_STATE_DIR": str(tmp_path / "nostate"),
        "POSTGRES_HOST": "127.0.0.1",
        "POSTGRES_PORT": "1",
        "VALKEY_HOST": "127.0.0.1",
        "VALKEY_PORT": "1",
        "KAFKA_BOOTSTRAP_SERVERS": "127.0.0.1:1",
        "OMNICLAUDE_MODE": "full",
        "ONEX_STATUSLINE_PR_EXT": ext,
        "ONEX_STATUSLINE_EXT_CACHE": str(cache),
        "ONEX_STATUSLINE_PR_CACHE": str(pr_cache),
    }
    if budget_ms is not None:
        env["ONEX_STATUSLINE_EXT_BUDGET_MS"] = budget_ms
    stdin = (
        '{"workspace":{"project_dir":"' + str(REPO_ROOT) + '"},'
        '"model":{"id":"t","display_name":"T"},"context_window":{}}'
    )
    start = time.monotonic()
    result = subprocess.run(
        ["bash", str(STATUSLINE)],
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )
    elapsed = time.monotonic() - start
    assert result.returncode == 0, result.stderr
    return ANSI.sub("", result.stdout).splitlines(), elapsed


def test_no_extension_renders_builtin_segment(tmp_path: Path) -> None:
    lines, _ = _render(tmp_path, "none", tmp_path / "c")
    assert len(lines) == 3
    assert BUILTIN_MARK in lines[2]


def test_missing_extension_path_falls_back(tmp_path: Path) -> None:
    lines, _ = _render(tmp_path, str(tmp_path / "absent"), tmp_path / "c")
    assert len(lines) == 3
    assert BUILTIN_MARK in lines[2]


def test_extension_output_replaces_segment_and_is_cached(tmp_path: Path) -> None:
    ext = _ext(tmp_path, "good", "printf 'SEG-A\\nSEG-B\\n'")
    cache = tmp_path / "c"
    # A widened budget for the success path only: a bare process start on a
    # loaded runner can take longer than 300 ms.
    lines, _ = _render(tmp_path, str(ext), cache, budget_ms="3000")
    assert len(lines) == 4
    assert lines[2].endswith("SEG-A")
    assert lines[3] == "SEG-B"
    assert BUILTIN_MARK not in "\n".join(lines)
    assert cache.read_text() == "SEG-A\nSEG-B"


@pytest.mark.parametrize("budget_ms", [None, "300", "not-a-number"])
def test_default_300ms_budget_kills_slow_extension(
    tmp_path: Path, budget_ms: str | None
) -> None:
    # The extension needs about a second, more than three times the 300 ms bound.
    # A malformed budget falls back to 300, not to unbounded.
    ext = _ext(tmp_path, "slow", "sleep 1; echo SLOW-SEG")
    lines, _ = _render(tmp_path, str(ext), tmp_path / "c", budget_ms=budget_ms)
    out = "\n".join(lines)
    assert "SLOW-SEG" not in out
    assert BUILTIN_MARK in lines[2]
    assert len(lines) == 3


def test_slow_extension_does_not_hold_the_render(tmp_path: Path) -> None:
    ext = _ext(tmp_path, "slower", "sleep 20; echo SLOW-SEG")
    lines, elapsed = _render(tmp_path, str(ext), tmp_path / "c")
    assert BUILTIN_MARK in lines[2]
    assert elapsed < 10, f"render took {elapsed:.1f}s with a 20 s extension"


def test_slow_extension_serves_last_good_cache(tmp_path: Path) -> None:
    cache = tmp_path / "c"
    cache.write_text("CACHED-A\nCACHED-B\n")
    ext = _ext(tmp_path, "slow", "sleep 1; echo SLOW-SEG")
    lines, _ = _render(tmp_path, str(ext), cache)
    assert len(lines) == 4
    assert lines[2].endswith("CACHED-A")
    assert lines[3] == "CACHED-B"
    assert BUILTIN_MARK not in "\n".join(lines)


def test_failing_extension_output_is_discarded(tmp_path: Path) -> None:
    cache = tmp_path / "c"
    ext = _ext(tmp_path, "bad", "echo PARTIAL; exit 1")
    lines, _ = _render(tmp_path, str(ext), cache, budget_ms="3000")
    assert "PARTIAL" not in "\n".join(lines)
    assert BUILTIN_MARK in lines[2]
    assert not cache.exists()


def test_cache_older_than_an_hour_is_not_served(tmp_path: Path) -> None:
    cache = tmp_path / "c"
    cache.write_text("STALE-A\n")
    old = time.time() - 7200
    os.utime(cache, (old, old))
    ext = _ext(tmp_path, "bad", "exit 1")
    lines, _ = _render(tmp_path, str(ext), cache)
    assert "STALE-A" not in "\n".join(lines)
    assert BUILTIN_MARK in lines[2]
