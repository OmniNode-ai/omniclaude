# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""The hook-emit drainer log and hooks.log rotate at a size bound (OMN-19519).

The defect, read on the operator Mac on 2026-09-25 at 01:39Z:
``hooks/logs/hook-emit-drainer.log`` was 255,667,885 bytes and ``logs/hooks.log``
436,491,662 bytes, and nothing rotated either. The only rotation in the hook
tree was the OMN-8429 guard inside one script.

What each test pins
-------------------
* AC1 -- the drainer rotates its own log at the bound, keeps at most the
  configured number of backups, and after a rollover every write lands in the
  fresh file, including raw writes to fd 2. That last part is load-bearing: the
  drainer's log is launchd's StandardErrorPath, so a rename by anyone else would
  leave the process writing into the renamed file forever.
* AC2 -- the shared shell helper rotates a log over the bound into numbered
  backups, keeps at most the configured count, leaves a log under the bound
  untouched, keeps the pre-rotation content whole in ``.1``, and is not stopped
  by a lock a dead rotator left behind.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).parent.parent.parent.parent
_LIB_DIR = _REPO_ROOT / "plugins" / "onex" / "hooks" / "lib"
_PATHS_SH = _REPO_ROOT / "plugins" / "onex" / "hooks" / "scripts" / "onex-paths.sh"
_DRAINER = _LIB_DIR / "hook_emit_drainer.py"


# --------------------------------------------------------------------------
# AC1 -- the drainer's own log
# --------------------------------------------------------------------------


def _run_drainer_logging(
    log: Path, *, max_bytes: int, backups: int, lines: int
) -> None:
    """Start a process whose stderr IS the log file, as launchd starts the drainer."""
    program = textwrap.dedent(
        f"""
        import logging, os, sys
        sys.path.insert(0, {str(_LIB_DIR)!r})
        import hook_emit_drainer as drainer
        drainer.configure_logging(
            "INFO", log_file=None, max_bytes={max_bytes}, backups={backups}
        )
        log = logging.getLogger("hook_emit_drainer")
        log.info("FIRST-LINE-BEFORE-ANY-ROLLOVER")
        for i in range({lines}):
            log.info("line %05d %s", i, "x" * 80)
        log.info("LAST-LOGGED-LINE")
        os.write(2, b"RAW-FD2-AFTER-ROLLOVER\\n")
        print("STDOUT-AFTER-ROLLOVER", flush=True)
        """
    )
    with open(log, "ab") as sink:
        subprocess.run(
            [sys.executable, "-c", program],
            stdout=sink,
            stderr=sink,
            check=True,
            timeout=60,
            env={**os.environ, "PYTHONPATH": ""},
        )


def test_the_drainer_rotates_its_launchd_stderr_log_at_the_bound(
    tmp_path: Path,
) -> None:
    log = tmp_path / "hook-emit-drainer.log"
    log.write_text("PRE-EXISTING-TAIL-LINE\n")
    _run_drainer_logging(log, max_bytes=4096, backups=3, lines=400)

    backups = sorted(p.name for p in tmp_path.glob("hook-emit-drainer.log.*"))
    assert backups, "the log never rotated"
    assert backups == [
        "hook-emit-drainer.log.1",
        "hook-emit-drainer.log.2",
        "hook-emit-drainer.log.3",
    ], f"retention must be bounded at 3 backups, found {backups}"
    assert log.stat().st_size <= 4096 + 256
    for path in [log, *tmp_path.glob("hook-emit-drainer.log.*")]:
        assert path.stat().st_size <= 4096 + 256, f"{path.name} exceeds the bound"


def test_writes_after_a_rollover_land_in_the_fresh_file(tmp_path: Path) -> None:
    log = tmp_path / "hook-emit-drainer.log"
    _run_drainer_logging(log, max_bytes=4096, backups=3, lines=400)
    current = log.read_text()
    assert "LAST-LOGGED-LINE" in current
    assert "RAW-FD2-AFTER-ROLLOVER" in current, (
        "a raw fd-2 write went to a rotated file: the process still holds the old one"
    )
    assert "STDOUT-AFTER-ROLLOVER" in current


def test_the_first_rotation_keeps_the_existing_content_whole(tmp_path: Path) -> None:
    """The live log already holds 255 MB; its tail must survive the first rollover."""
    log = tmp_path / "hook-emit-drainer.log"
    log.write_text("OLD\n" * 2000 + "PRE-EXISTING-TAIL-LINE\n")
    _run_drainer_logging(log, max_bytes=4096, backups=5, lines=5)
    first_backup = tmp_path / "hook-emit-drainer.log.1"
    assert first_backup.exists()
    assert first_backup.read_text().rstrip().endswith("PRE-EXISTING-TAIL-LINE")


def test_the_drainer_leaves_a_terminal_stderr_alone(tmp_path: Path) -> None:
    """Run by hand in a terminal (stderr not a regular file), nothing is rotated."""
    program = textwrap.dedent(
        f"""
        import sys
        sys.path.insert(0, {str(_LIB_DIR)!r})
        import hook_emit_drainer as drainer
        print(drainer.configure_logging("INFO", log_file=None, max_bytes=10, backups=1))
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
        cwd=tmp_path,
    )
    assert result.stdout.strip() == "None"
    assert not list(tmp_path.iterdir())


def test_the_drainer_cli_exposes_the_bound_and_the_retention() -> None:
    result = subprocess.run(
        [sys.executable, str(_DRAINER), "--help"],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    assert "--log-max-mb" in result.stdout
    assert "--log-backups" in result.stdout


# --------------------------------------------------------------------------
# AC2 -- the shared shell helper for hooks.log and the bus-mirror logs
# --------------------------------------------------------------------------


def _rotate(
    log: Path, *, max_bytes: int, backups: int
) -> subprocess.CompletedProcess[str]:
    script = (
        f'set -euo pipefail; source "{_PATHS_SH}"; '
        f'onex_rotate_log_if_over "{log}" {max_bytes} {backups}; echo "rc=$?"'
    )
    env = {**os.environ, "ONEX_STATE_DIR": str(log.parent / "state")}
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
        env=env,
    )


def test_the_shell_helper_rotates_a_log_over_the_bound(tmp_path: Path) -> None:
    log = tmp_path / "hooks.log"
    log.write_text("a" * 5000 + "\nPRE-ROTATION-TAIL\n")
    result = _rotate(log, max_bytes=4096, backups=3)
    assert result.returncode == 0, result.stderr
    assert "rc=0" in result.stdout
    assert (tmp_path / "hooks.log.1").read_text().endswith("PRE-ROTATION-TAIL\n")
    assert not log.exists() or log.stat().st_size == 0


def test_the_shell_helper_keeps_at_most_the_configured_backups(tmp_path: Path) -> None:
    log = tmp_path / "hooks.log"
    for generation in range(6):
        log.write_text(f"generation-{generation}\n" + "b" * 5000)
        assert _rotate(log, max_bytes=4096, backups=3).returncode == 0
    names = sorted(p.name for p in tmp_path.glob("hooks.log.*"))
    assert names == ["hooks.log.1", "hooks.log.2", "hooks.log.3"], names
    assert (tmp_path / "hooks.log.1").read_text().startswith("generation-5")
    assert (tmp_path / "hooks.log.3").read_text().startswith("generation-3")


def test_the_shell_helper_leaves_a_log_under_the_bound_untouched(
    tmp_path: Path,
) -> None:
    log = tmp_path / "hooks.log"
    log.write_text("small\n")
    assert _rotate(log, max_bytes=4096, backups=3).returncode == 0
    assert log.read_text() == "small\n"
    assert not list(tmp_path.glob("hooks.log.*"))


def test_a_stale_lock_does_not_stop_rotation(tmp_path: Path) -> None:
    log = tmp_path / "hooks.log"
    log.write_text("c" * 5000)
    lock = tmp_path / "hooks.log.rotate.lock"
    lock.mkdir()
    old = time.time() - 600
    os.utime(lock, (old, old))
    assert _rotate(log, max_bytes=4096, backups=3).returncode == 0
    assert (tmp_path / "hooks.log.1").exists(), "a dead rotator's lock froze rotation"
    assert not lock.exists()


def test_a_live_lock_defers_to_the_rotator_holding_it(tmp_path: Path) -> None:
    log = tmp_path / "hooks.log"
    log.write_text("d" * 5000)
    (tmp_path / "hooks.log.rotate.lock").mkdir()
    assert _rotate(log, max_bytes=4096, backups=3).returncode == 0
    assert not (tmp_path / "hooks.log.1").exists()


def test_sourcing_the_paths_file_never_fails_under_errexit(tmp_path: Path) -> None:
    """57 hook scripts source onex-paths.sh, some without ``|| true``."""
    for _ in range(40):
        result = subprocess.run(
            ["bash", "-c", f'set -euo pipefail; source "{_PATHS_SH}"; echo ok'],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
            env={**os.environ, "ONEX_STATE_DIR": str(tmp_path / "state")},
        )
        assert result.returncode == 0 and result.stdout.strip() == "ok", result.stderr


@pytest.mark.parametrize(
    "script",
    [
        "session_start_bus_mirror.sh",
        "session_end_bus_mirror.sh",
        "post_tool_use_bus_mirror.sh",
        "user_prompt_submit_bus_mirror.sh",
    ],
)
def test_every_bus_mirror_log_is_bounded(script: str) -> None:
    body = (_PATHS_SH.parent / script).read_text()
    assert 'onex_maybe_rotate_log "$LOG_FILE"' in body, (
        f"{script} appends to its own log on every event and must bound it"
    )


def test_the_paths_file_bounds_hooks_log_itself() -> None:
    assert 'onex_maybe_rotate_log "$ONEX_HOOK_LOG"' in _PATHS_SH.read_text()
