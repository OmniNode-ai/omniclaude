# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Rows of the work ledger from the work-ledger reader node, for callers that open no file (OMN-26330).

Lifted out of ``scripts/worktree_auto_prune.py`` and the git admission handler, both baselined files
that may only shrink. The node runs under its own interpreter, so it is a subprocess and never an
import. An answer is the node's own rows: not moved (exit 3), unreadable (exit 69), no interpreter and
a read past the bound each raise :class:`LedgerRowsUnavailable`, never an empty list, because no rows
reads exactly like a clean bill of health and the ledger file is never read in its place.
"""

from __future__ import annotations

import os
import shlex
from collections.abc import Mapping, Sequence
from pathlib import Path
from subprocess import SubprocessError, run

READER_MODULE = "omnimarket.nodes.node_work_ledger_reader_effect"


class LedgerRowsUnavailable(OSError):
    """The work-ledger reader node did not answer the rows read."""


def reader_interpreter(environ: Mapping[str, str], declared: str = "") -> str:
    """The python that runs the reader node: the caller's, the host's, then the registry's venv."""
    named = declared.strip() or (
        environ.get("ONEX_LEDGER_READER_PYTHON")
        or environ.get("ONEX_LEDGER_BUS_APPEND_COMMAND")
        or ""
    )
    words = shlex.split(named)
    if words:
        return words[0]
    home = environ.get("OMNI_HOME", "").strip()
    venv = Path(home, ".onex-dispatch-venv", "bin", "python") if home else None
    return str(venv) if venv is not None and os.access(venv, os.X_OK) else ""


def read_rows(
    reader: str,
    window_hours: int,
    kinds: Sequence[str] = (),
    *,
    interpreter: str = "",
    environ: Mapping[str, str] | None = None,
    timeout_s: float = 150.0,
    row_lanes: Sequence[str] = (),
) -> list[str]:
    """The ledger rows of the last ``window_hours`` hours (one ``--kind`` per entry of ``kinds``).

    ``row_lanes`` keeps only the rows of those lanes (one ``--row-lane`` each): the node scans every
    row of the window either way, but it prints and parses only the rows of the named lanes.
    """
    env = dict(os.environ if environ is None else environ)
    python = reader_interpreter(env, interpreter)
    if not python:
        raise LedgerRowsUnavailable("no interpreter for the work-ledger reader node")
    argv = [python, "-m", READER_MODULE, "--reader", reader, "--query", "rows"]
    argv += ["--window-hours", str(window_hours)]
    for kind in kinds:
        argv += ["--kind", kind]
    for lane in row_lanes:
        argv += ["--row-lane", lane]
    try:
        done = run(
            argv,
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout_s,
            check=False,
        )
    except (OSError, SubprocessError) as exc:
        raise LedgerRowsUnavailable(f"the reader node did not answer ({exc})") from exc
    if done.returncode not in (0, 1):
        raise LedgerRowsUnavailable(f"the reader node exited {done.returncode}")
    return [line for line in done.stdout.splitlines() if line.strip()]
