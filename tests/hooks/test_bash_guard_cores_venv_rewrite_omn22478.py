# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The Bash guards' shared runner survives a rewrite of the hook venv (OMN-22478).

A sync of the hook venv rewrites its editable-install file. An interpreter that
started inside the rewrite has no package on its path for its whole life, so
retrying the import in that process cannot succeed, and the venv it runs from is
the venv a fallback would try. The runner retries in a NEW interpreter of every
declared venv, itself included, for a bounded time, and refuses exactly as before
when the module is still missing after it.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.unit

LIB = str(Path(__file__).resolve().parents[2] / "plugins/onex/hooks/lib")

CORE = (
    'def main(argv):\n    print("CORE-RAN", argv)\n    return 0\n'
    'if __name__ == "__main__":\n'
    "    import sys\n    sys.exit(main(sys.argv[1:]))\n"
)


@pytest.fixture
def runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """The runner module, run as if from the hook venv at `tmp_path/data/.venv`.

    The venv's python is a wrapper that execs the real interpreter, and
    `sys.executable` is set to that very path: the failing interpreter IS the
    declared venv, which is the incident (the first pass skips it).
    """
    monkeypatch.syspath_prepend(LIB)
    import bash_guard_cores

    python = tmp_path / "data/.venv/bin/python3"
    python.parent.mkdir(parents=True)
    python.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    python.chmod(0o755)
    monkeypatch.setattr(sys, "executable", str(python))
    return bash_guard_cores


def _request(runner: ModuleType, tmp_path: Path, module: str) -> object:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["CLAUDE_PLUGIN_DATA"] = str(tmp_path / "data")
    env.pop("OMNI_HOME", None)
    return runner.Request(
        stderr_mode="merge",
        cwd=str(tmp_path),
        stdin="{}",
        argv=(sys.executable, "-m", module, "x"),
        env=env,
    )


def test_a_core_importable_only_after_the_rewrite_recovers(
    runner: ModuleType, tmp_path: Path
) -> None:
    # The module appears 0.2 s in: after the first import failed in this
    # process and in the first fresh probe, before a later fresh probe looks.
    threading.Timer(
        0.2, (tmp_path / "onex_rewrite_window_core.py").write_text, args=(CORE,)
    ).start()
    rc, output = runner.run_core(_request(runner, tmp_path, "onex_rewrite_window_core"))
    assert rc == 0, output
    assert "CORE-RAN ['x']" in output
    assert "guard core cannot be imported" not in output


def test_a_core_that_stays_missing_is_still_refused_within_a_bound(
    runner: ModuleType, tmp_path: Path
) -> None:
    started = time.monotonic()
    rc, output = runner.run_core(
        _request(runner, tmp_path, "onex_rewrite_window_never")
    )
    assert rc == 1
    first = output.splitlines()[0]
    assert first.startswith(
        "guard core cannot be imported: ModuleNotFoundError: "
        "No module named 'onex_rewrite_window_never'"
    )
    # Each tried venv is named once, not once per retry.
    tried = first.rsplit("declared interpreters tried: ", 1)[1].rstrip(")").split(", ")
    assert tried[0] == "CLAUDE_PLUGIN_DATA"
    assert len(tried) == len(set(tried))
    assert time.monotonic() - started < 15
